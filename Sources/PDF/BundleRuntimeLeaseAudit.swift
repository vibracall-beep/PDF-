import Foundation
import Darwin

/// Exercises actual exec/descriptor inheritance through two native processes,
/// including an installer-exclusive app lease when smoke runs during install.
enum BundleRuntimeLeaseAudit {
    static let argument = "--bundle-lease-audit-worker"
    private struct Receipt: Codable { let version: Int; let processID: Int32; let childID: Int32 }
    private final class Cancellation: @unchecked Sendable {
        private let lock = NSLock(); private var value = false
        func cancel() { lock.lock(); value = true; lock.unlock() }
        var cancelled: Bool { lock.lock(); defer { lock.unlock() }; return value }
    }

    static func handleCommandLineIfNeeded() -> Bool {
        guard CommandLine.arguments.contains(argument) else { return false }
        do {
            guard CommandLine.arguments.count == 4, CommandLine.arguments[1] == argument,
                  ["middle", "leaf"].contains(CommandLine.arguments[2]) else { throw failure("argumentos inválidos") }
            try worker(role: CommandLine.arguments[2], directory: URL(fileURLWithPath: CommandLine.arguments[3], isDirectory: true))
            exit(0)
        } catch {
            // Only fixed diagnostic text, never an arbitrary error or path.
            FileHandle.standardError.write(Data("Native bundle lease audit worker failed.\n".utf8))
            exit(2)
        }
    }

    static func run() async throws {
        try await Task.detached(priority: .utility) { try audit() }.value
    }

    private static func audit() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-lease-audit-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let resource = directory.appendingPathComponent("fixture.lock")
        let descriptor = Darwin.open(resource.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o444))
        guard descriptor >= 0 else { throw failure("não foi possível criar o recurso isolado") }
        Darwin.close(descriptor)
        var fixture: BundleRuntimeLease.Lease? = try BundleRuntimeLease.acquire(resource: resource, mode: .shared)
        try assertExclusiveBlocked(resource)
        let wrong = directory.appendingPathComponent("foreign.lock")
        let foreignFD = Darwin.open(wrong.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o444))
        guard foreignFD >= 0 else { throw failure("não foi possível criar o controle de identidade") }
        defer { Darwin.close(foreignFD) }
        var refused = false
        do { _ = try BundleRuntimeLease.acquire(resource: resource, mode: .shared, inherited: foreignFD) } catch { refused = true }
        guard refused else { throw failure("um descritor de outro recurso foi aceito") }
        let installer = try BundleRuntimeLease.acquire(resource: wrong, mode: .exclusive)
        refused = false
        do { _ = try BundleRuntimeLease.acquire(resource: wrong, mode: .shared, inherited: installer.descriptor) } catch { refused = true }
        guard refused else { throw failure("um modo incorreto rebaixou o bloqueio exclusivo do instalador") }
        let sharedProbe = Darwin.open(wrong.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard sharedProbe >= 0 else { throw failure("o controle do bloqueio exclusivo não pôde ser aberto") }
        let probeResult = flock(sharedProbe, LOCK_SH | LOCK_NB), probeError = errno
        Darwin.close(sharedProbe)
        guard probeResult == -1 && (probeError == EWOULDBLOCK || probeError == EAGAIN) else { throw failure("a recusa não preservou o bloqueio exclusivo original") }
        withExtendedLifetime(installer) { }

        let child = try process(role: "middle", directory: directory)
        let carrier = try fixture!.duplicate()
        child.standardOutput = carrier // fd 1 is unused by this private worker.
        let bundleCarrier = try BundleRuntimeLease.configureChild(child)
        defer { try? bundleCarrier?.close(); try? carrier.close() }
        try child.run()
        defer { stop(child, grace: 3) }
        // The children must keep the resource alive independently of all the
        // parent's descriptions. The app's actual installation lease remains.
        try carrier.close(); fixture = nil
        let deadline = ProcessInfo.processInfo.systemUptime + 18
        let receiptURL = directory.appendingPathComponent("middle-ready.json")
        try wait(for: receiptURL, process: child, deadline: deadline - 6)
        let receipt = try JSONDecoder().decode(Receipt.self, from: readReceipt(receiptURL))
        guard receipt.version == 1, receipt.processID == child.processIdentifier, receipt.childID > 1 else {
            throw failure("o recibo não pertence à cadeia de processos lançada")
        }
        try assertExclusiveBlocked(resource)
        try NativeOutput.write(Data("stop".utf8), to: directory.appendingPathComponent("stop-leaf"))
        let reapedURL = directory.appendingPathComponent("leaf-reaped.json")
        try wait(for: reapedURL, process: child, deadline: deadline - 3)
        let reaped = try JSONDecoder().decode(Receipt.self, from: readReceipt(reapedURL))
        guard reaped.version == 1, reaped.processID == receipt.processID, reaped.childID == receipt.childID else {
            throw failure("o processo intermediário não confirmou o recolhimento do filho correto")
        }
        try assertExclusiveBlocked(resource)
        guard child.isRunning, Darwin.kill(child.processIdentifier, SIGKILL) == 0 else { throw failure("SIGKILL do processo isolado falhou") }
        while child.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.02) }
        guard !child.isRunning else { throw failure("o processo encerrado excedeu o prazo de recolhimento") }
        child.waitUntilExit()
        guard child.terminationReason == .uncaughtSignal, child.terminationStatus == SIGKILL else { throw failure("o processo não terminou por SIGKILL real") }
        let exclusive = try BundleRuntimeLease.acquire(resource: resource, mode: .exclusive)
        withExtendedLifetime(exclusive) { }
        print("[Bundle lease] two native exec levels, foreign descriptor refusal, SIGKILL/reap and release: PASS")
    }

    private static func worker(role: String, directory: URL) throws {
        var info = stat()
        guard directory.lastPathComponent.hasPrefix("PDF-lease-audit-"), lstat(directory.path, &info) == 0,
              info.st_mode & S_IFMT == S_IFDIR, info.st_mode & 0o777 == 0o700, info.st_uid == getuid() else {
            throw failure("pasta privada inválida")
        }
        let fixture = try BundleRuntimeLease.acquire(resource: directory.appendingPathComponent("fixture.lock"), mode: .shared, inherited: STDOUT_FILENO)
        defer { withExtendedLifetime(fixture) { } }
        let cancelled = Cancellation()
        let previous = signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global(qos: .utility))
        source.setEventHandler { cancelled.cancel() }; source.resume()
        defer { source.cancel(); signal(SIGTERM, previous) }
        let deadline = ProcessInfo.processInfo.systemUptime + 12
        if role == "leaf" {
            try NativeOutput.write(try JSONEncoder().encode(Receipt(version: 1, processID: getpid(), childID: 0)), to: directory.appendingPathComponent("leaf-ready.json"))
            while !cancelled.cancelled && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.02) }
            return
        }
        let child = try process(role: "leaf", directory: directory)
        let carrier = try fixture.duplicate(); child.standardOutput = carrier
        let bundleCarrier = try BundleRuntimeLease.configureChild(child)
        defer { try? bundleCarrier?.close(); try? carrier.close() }
        try child.run()
        // The parent allows three seconds for this middle process to settle;
        // reap its own leaf within one second before that outer deadline.
        defer { stop(child, grace: 1) }
        try carrier.close()
        let readyURL = directory.appendingPathComponent("leaf-ready.json")
        try wait(for: readyURL, process: child, deadline: deadline - 3, cancellation: cancelled)
        let ready = try JSONDecoder().decode(Receipt.self, from: readReceipt(readyURL))
        guard ready.version == 1, ready.processID == child.processIdentifier, ready.childID == 0 else { throw failure("recibo do segundo nível inválido") }
        let receipt = Receipt(version: 1, processID: getpid(), childID: child.processIdentifier)
        try NativeOutput.write(try JSONEncoder().encode(receipt), to: directory.appendingPathComponent("middle-ready.json"))
        while !FileManager.default.fileExists(atPath: directory.appendingPathComponent("stop-leaf").path) {
            guard !cancelled.cancelled, child.isRunning, ProcessInfo.processInfo.systemUptime < deadline - 2 else { throw failure("prazo do segundo nível excedido") }
            Thread.sleep(forTimeInterval: 0.02)
        }
        guard Darwin.kill(child.processIdentifier, SIGKILL) == 0 else { throw failure("SIGKILL do segundo nível falhou") }
        while child.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.02) }
        guard !child.isRunning else { throw failure("o segundo nível não pôde ser recolhido") }
        child.waitUntilExit()
        guard child.terminationReason == .uncaughtSignal, child.terminationStatus == SIGKILL else { throw failure("o segundo nível não terminou por SIGKILL real") }
        try NativeOutput.write(try JSONEncoder().encode(receipt), to: directory.appendingPathComponent("leaf-reaped.json"))
        while !cancelled.cancelled && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.02) }
    }

    private static func process(role: String, directory: URL) throws -> Process {
        guard let executable = Bundle.main.executableURL else { throw failure("executável indisponível") }
        let child = Process(); child.executableURL = executable
        child.arguments = [argument, role, directory.path]
        child.standardInput = FileHandle.nullDevice; child.standardOutput = FileHandle.nullDevice; child.standardError = FileHandle.nullDevice
        return child
    }
    private static func assertExclusiveBlocked(_ resource: URL) throws {
        let descriptor = Darwin.open(resource.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("recurso isolado ausente") }
        defer { Darwin.close(descriptor) }
        let result = flock(descriptor, LOCK_EX | LOCK_NB), reason = errno
        guard result == -1 && (reason == EWOULDBLOCK || reason == EAGAIN) else { throw failure("o bloqueio exclusivo não foi impedido pelo processo ativo") }
    }
    private static func wait(for url: URL, process: Process, deadline: TimeInterval, cancellation: Cancellation? = nil) throws {
        while !FileManager.default.fileExists(atPath: url.path) {
            try Task.checkCancellation()
            guard cancellation?.cancelled != true, process.isRunning, ProcessInfo.processInfo.systemUptime < deadline else { throw failure("o processo não concluiu a fase no prazo") }
            Thread.sleep(forTimeInterval: 0.02)
        }
    }
    private static func readReceipt(_ url: URL) throws -> Data {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("recibo ausente") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == getuid(),
              info.st_mode & 0o777 == 0o600, info.st_size > 0, info.st_size <= 4096,
              let data = try handle.read(upToCount: 4097), data.count == info.st_size else { throw failure("recibo privado inválido") }
        return data
    }
    private static func stop(_ child: Process, grace: TimeInterval) {
        if child.isRunning {
            child.terminate()
            let deadline = ProcessInfo.processInfo.systemUptime + grace
            while child.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.02) }
            if child.isRunning { Darwin.kill(child.processIdentifier, SIGKILL) }
        }
        child.waitUntilExit()
    }
    private static func failure(_ phase: String) -> NSError {
        NSError(domain: "PDF.BundleLeaseAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: "Auditoria de bloqueio da instalação: " + phase + "."])
    }
}
