import Foundation
import Darwin

/// Process is configuration only. This owner alone spawns, signals and reaps
/// the child: the PID cannot be reused between its state check and a signal.
final class OwnedChildProcess: @unchecked Sendable {
    let configuration: Process
    struct Exit: Sendable {
        let status: Int32
        let signalled: Bool
    }
    private let lock = NSLock()
    private var pid: pid_t = 0
    private var result: Exit?
    private var failure: Error?
    private var signalFailure: Error?
    private var cancellationRequested = false
    private var workTicket: ApplicationWork.Ticket?
    var processIdentifier: pid_t { lock.lock(); defer { lock.unlock() }; return pid }
    var cancellationFailure: Error? { lock.lock(); defer { lock.unlock() }; return signalFailure }

    init(configuration: Process, completingCleanup: Bool = false) throws {
        self.configuration = configuration
        guard configuration.processIdentifier == 0, let executable = configuration.executableURL,
              executable.isFileURL, !executable.path.utf8.contains(0) else {
            throw Self.error("A configuração do processo auxiliar é inválida.")
        }
        let arguments = [executable.path] + (configuration.arguments ?? [])
        let environment = (configuration.environment ?? ProcessInfo.processInfo.environment).map { "\($0.key)=\($0.value)" }
        guard arguments.allSatisfy({ !$0.utf8.contains(0) }), environment.allSatisfy({ !$0.utf8.contains(0) }) else {
            throw Self.error("Os argumentos do processo auxiliar são inválidos.")
        }
        try Self.validateReapingPolicy()
        // Register before spawning. A quit concurrent with preparation either
        // prevents the spawn or cancels this same child after its PID is set.
        workTicket = ApplicationWork.begin(cancelWhenStopping: !completingCleanup) { [weak self] in self?.cancel() }
        defer { if pid == 0 { workTicket?.finish(); workTicket = nil } }
        var actions: posix_spawn_file_actions_t?
        var attributes: posix_spawnattr_t?
        try Self.check(posix_spawn_file_actions_init(&actions))
        defer { posix_spawn_file_actions_destroy(&actions) }
        try Self.check(posix_spawnattr_init(&attributes))
        defer { posix_spawnattr_destroy(&attributes) }
        var copies: [Int32] = []
        defer { for descriptor in copies { Darwin.close(descriptor) } }
        let streams: [Any?] = [configuration.standardInput, configuration.standardOutput, configuration.standardError]
        for (index, value) in streams.enumerated() {
            let descriptor: Int32
            var openedNull: Int32?
            defer { if let openedNull { Darwin.close(openedNull) } }
            if let handle = value as? FileHandle {
                // Foundation's null handle can be a sink object with no real
                // descriptor. Process.run handles this intention specially;
                // posix_spawn needs a real /dev/null descriptor instead.
                // An arbitrary invalid/closed handle is never treated as null.
                if handle === FileHandle.nullDevice {
                    let opened = Darwin.open("/dev/null", (index == 0 ? O_RDONLY : O_WRONLY) | O_CLOEXEC | O_NOFOLLOW)
                    guard opened >= 0 else { throw Self.descriptorError(index: index, code: errno) }
                    openedNull = opened; descriptor = opened
                } else { descriptor = handle.fileDescriptor }
            }
            else if let pipe = value as? Pipe {
                descriptor = index == 0 ? pipe.fileHandleForReading.fileDescriptor : pipe.fileHandleForWriting.fileDescriptor
            } else if value == nil { descriptor = Int32(index) }
            else { throw Self.error("O transporte do processo auxiliar é inválido.") }
            let copy = try Self.duplicateDescriptor(descriptor, streamIndex: index)
            copies.append(copy)
            try Self.check(posix_spawn_file_actions_adddup2(&actions, copy, Int32(index)))
        }
        if let directory = configuration.currentDirectoryURL {
            try directory.path.withCString { try Self.check(posix_spawn_file_actions_addchdir(&actions, $0)) }
        }
        // Only explicit stdio survives. The installation lease is already
        // carried in stdin/stderr by BundleRuntimeLease before this method.
        let flags = POSIX_SPAWN_CLOEXEC_DEFAULT | POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF
        try Self.check(posix_spawnattr_setflags(&attributes, Int16(flags)))
        try Self.check(posix_spawnattr_setpgroup(&attributes, 0))
        var mask = sigset_t(); sigemptyset(&mask)
        try Self.check(posix_spawnattr_setsigmask(&attributes, &mask))
        var defaults = sigset_t(); sigemptyset(&defaults)
        for signal in [SIGINT, SIGTERM, SIGHUP, SIGPIPE] { sigaddset(&defaults, signal) }
        try Self.check(posix_spawnattr_setsigdefault(&attributes, &defaults))
        var argv = arguments.map { strdup($0) } + [nil]
        var envp = environment.map { strdup($0) } + [nil]
        defer { for value in argv { free(value) }; for value in envp { free(value) } }
        guard argv.dropLast().allSatisfy({ $0 != nil }), envp.dropLast().allSatisfy({ $0 != nil }) else {
            throw Self.error("Não foi possível reservar os argumentos do processo auxiliar.")
        }
        var child: pid_t = 0
        lock.lock()
        if cancellationRequested { lock.unlock(); throw CancellationError() }
        do { try Self.validateReapingPolicy() }
        catch { lock.unlock(); throw error }
        let status = executable.path.withCString { path in
            argv.withUnsafeMutableBufferPointer { arguments in
                envp.withUnsafeMutableBufferPointer { environment in
                    posix_spawn(&child, path, &actions, &attributes, arguments.baseAddress!, environment.baseAddress!)
                }
            }
        }
        if status == 0 { pid = child }
        lock.unlock()
        try Self.check(status)
        // Foundation normally closes these child ends after Process.run().
        // This owner did the spawn, so it must release them itself.
        var closed = Set<ObjectIdentifier>()
        for (index, value) in streams.enumerated() {
            guard let pipe = value as? Pipe else { continue }
            let handle = index == 0 ? pipe.fileHandleForReading : pipe.fileHandleForWriting
            if closed.insert(ObjectIdentifier(handle)).inserted { try? handle.close() }
        }
    }

    func isRunning() throws -> Bool {
        lock.lock(); defer { lock.unlock() }
        try observeLocked()
        return result == nil
    }
    /// Internal audit/control hook; signals only while this owner still has
    /// the unreaped child. Never signal a PID obtained from a completed child.
    @discardableResult func signalOwned(_ signal: Int32) throws -> Bool {
        lock.lock(); defer { lock.unlock() }
        return try signalLocked(signal)
    }

    func waitUntilExit() throws -> Exit {
        while true {
            lock.lock()
            do {
                try observeLocked()
                if let result { lock.unlock(); return result }
                lock.unlock()
            } catch { lock.unlock(); throw error }
            Thread.sleep(forTimeInterval: 0.02)
        }
    }

    /// Read while the child is alive, without waiting forever for EOF from an
    /// unrelated descendant that inherited stdout. Python owns its converters;
    /// completion here is the child exit, not a promise about arbitrary trees.
    func collectOutput(from handle: FileHandle, check: () throws -> Void = {}, chunk: (Data) -> Void) throws -> Exit {
        let descriptor = handle.fileDescriptor
        let flags = fcntl(descriptor, F_GETFL)
        guard flags >= 0, fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) == 0 else {
            throw Self.error("Não foi possível acompanhar a saída do motor.")
        }
        var buffer = [UInt8](repeating: 0, count: 16_384)
        var remainingAfterExit = 131_072
        while true {
            try check()
            let running = try isRunning()
            let count = buffer.withUnsafeMutableBytes { Darwin.read(descriptor, $0.baseAddress!, $0.count) }
            if count > 0 {
                chunk(Data(buffer.prefix(count)))
                if !running {
                    remainingAfterExit -= count
                    if remainingAfterExit <= 0 { return try waitUntilExit() }
                }
                continue
            }
            if count < 0 && errno == EINTR { continue }
            guard count >= 0 || errno == EAGAIN || errno == EWOULDBLOCK else {
                throw Self.error("Não foi possível ler a saída do motor.")
            }
            if !running { return try waitUntilExit() }
            // EOF does not imply process exit; the child may close its output
            // before completing publication and converter cleanup.
            if count == 0 { Thread.sleep(forTimeInterval: 0.02); continue }
            var event = pollfd(fd: descriptor, events: Int16(POLLIN | POLLHUP), revents: 0)
            if Darwin.poll(&event, 1, 50) < 0 && errno != EINTR {
                throw Self.error("Não foi possível aguardar a saída do motor.")
            }
        }
    }

    /// SIGINT lets Python unwind and clean its own converter groups (up to
    /// eight seconds). Escalation targets only this owned child, never Pages.
    func cancel(grace: TimeInterval = 10, signal: Int32 = SIGINT) {
        lock.lock()
        guard !cancellationRequested else { lock.unlock(); return }
        cancellationRequested = true
        do { _ = try signalLocked(signal) } catch { signalFailure = error }
        let finished = result != nil
        lock.unlock()
        guard !finished else { return }
        let delay = grace.isFinite ? min(30, max(0, grace)) : 10
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + delay) { [self] in
            lock.lock(); defer { lock.unlock() }
            do { _ = try signalLocked(SIGKILL) } catch { signalFailure = error }
        }
    }

    private func observeLocked() throws {
        if result != nil { return }
        // A signalling failure does not transfer/revoke ownership. Continue
        // waitpid so a natural exit or later escalation can still be collected.
        // Only a waitpid ownership failure is permanent and blocks reuse.
        if let failure { throw failure }
        guard pid > 0 else { return }
        var status: Int32 = 0
        var observed: pid_t
        repeat { observed = waitpid(pid, &status, WNOHANG) } while observed < 0 && errno == EINTR
        if observed == 0 { return }
        guard observed == pid else {
            let error = Self.error("Não foi possível confirmar o encerramento do processo auxiliar.")
            failure = error; throw error
        }
        let signal = status & 0x7f
        // A debugger can make waitpid report a stopped tracee even without
        // WUNTRACED. That is not a terminal/reaped child or permission to quit.
        if signal == 0x7f { return }
        result = Exit(status: signal == 0 ? ((status >> 8) & 0xff) : signal, signalled: signal != 0)
        workTicket?.finish(); workTicket = nil
    }

    private func signalLocked(_ signal: Int32) throws -> Bool {
        try observeLocked()
        guard result == nil, pid > 0 else { return false }
        // No other code can reap our child while this lock is held. Even if
        // it exits here, its unreaped PID still identifies this exact child.
        if Darwin.kill(pid, signal) != 0 {
            if errno == ESRCH { return false }
            throw NSError(domain: "PDF.OwnedChild.Signal", code: Int(errno), userInfo:
                [NSLocalizedDescriptionKey: "Não foi possível sinalizar o processo auxiliar pertencente ao PDF."])
        }
        return true
    }
    private static func check(_ status: Int32) throws {
        guard status == 0 else { throw error("Não foi possível iniciar o processo auxiliar (\(status)).") }
    }
    static func duplicateDescriptor(_ descriptor: Int32, streamIndex: Int) throws -> Int32 {
        guard (0...2).contains(streamIndex) else { throw error("O transporte do processo auxiliar é inválido.") }
        let copy = fcntl(descriptor, F_DUPFD_CLOEXEC, 3)
        guard copy >= 0 else { throw descriptorError(index: streamIndex, code: errno) }
        return copy
    }
    private static func descriptorError(index: Int, code: Int32) -> NSError {
        let names = ["entrada padrão", "saída padrão", "saída de diagnóstico"]
        return NSError(domain: "PDF.OwnedChild.Descriptor", code: Int(code), userInfo: [
            NSLocalizedDescriptionKey: "Não foi possível preparar a \(names[index]) do processo auxiliar (erro \(code)).",
            "streamIndex": index
        ])
    }
    private static func validateReapingPolicy() throws {
        var disposition = sigaction()
        guard sigaction(SIGCHLD, nil, &disposition) == 0,
              disposition.sa_flags & SA_NOCLDWAIT == 0,
              unsafeBitCast(disposition.__sigaction_u.__sa_handler, to: UInt.self) == unsafeBitCast(SIG_DFL, to: UInt.self) else {
            throw NSError(domain: "PDF.OwnedChild.Ownership", code: 1, userInfo:
                [NSLocalizedDescriptionKey: "A política de processos herdada impede confirmar o encerramento seguro dos auxiliares. Reabra o PDF em uma sessão normal do macOS."])
        }
    }
    private static func error(_ message: String) -> NSError {
        NSError(domain: "PDF.OwnedChild", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
