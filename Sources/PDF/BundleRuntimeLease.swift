import Foundation
import Darwin

/// Keeps an installed bundle in use until the last cooperating native process
/// closes its descriptor. Never explicitly unlock a shared open-file description:
/// an installer or another inherited process may still own that same lease.
enum BundleRuntimeLease {
    enum Mode: String { case shared, exclusive
        var operation: Int32 { self == .shared ? LOCK_SH : LOCK_EX }
    }
    final class Lease: @unchecked Sendable {
        let descriptor: Int32
        let mode: Mode
        init(descriptor: Int32, mode: Mode) { self.descriptor = descriptor; self.mode = mode }
        deinit { Darwin.close(descriptor) }
        func duplicate() throws -> FileHandle {
            let copy = fcntl(descriptor, F_DUPFD_CLOEXEC, 3)
            guard copy >= 0 else { throw failure("Não foi possível transmitir o bloqueio do aplicativo ao processo auxiliar.") }
            return FileHandle(fileDescriptor: copy, closeOnDealloc: true)
        }
    }
    private static let lock = NSLock()
    private static var active = false
    private static var lease: Lease?
    private static let carrierKey = "PDF_RUNTIME_LEASE_STDIN"
    private static let installerFDKey = "PDF_INSTALLATION_LOCK_FD"
    private static let installerBundleKey = "PDF_INSTALLATION_LOCK_BUNDLE"

    /// Must run before any CLI worker, AppKit/SwiftUI entry point or runtime use.
    static func activate() throws {
        lock.lock(); defer { lock.unlock() }
        guard !active else { return }
        let environment = ProcessInfo.processInfo.environment
        let installerFD = environment[installerFDKey]
        let installerBundle = environment[installerBundleKey]
        let carrier = environment[carrierKey]
        let bundle = Bundle.main.bundleURL
        guard bundle.pathExtension.lowercased() == "app" else {
            // Development binaries have no installed bundle to update. An
            // inherited installation claim is still rejected, never ignored.
            guard installerFD == nil && installerBundle == nil && carrier == nil else {
                throw failure("O bloqueio recebido não pertence a um aplicativo instalado.")
            }
            active = true; return
        }
        let resource = bundle.appendingPathComponent("Contents/Resources/installation.lock")
        if let carrier {
            guard installerFD == nil && installerBundle == nil, let mode = Mode(rawValue: carrier) else {
                throw failure("O transporte do bloqueio do aplicativo é inválido.")
            }
            lease = try acquire(resource: resource, mode: mode, inherited: STDIN_FILENO)
        } else if installerFD != nil || installerBundle != nil {
            guard let value = installerFD, let descriptor = Int32(value), (3...4096).contains(descriptor),
                  value == String(descriptor), let installerBundle,
                  URL(fileURLWithPath: installerBundle).resolvingSymlinksInPath().standardizedFileURL == bundle.resolvingSymlinksInPath().standardizedFileURL else {
                throw failure("O bloqueio herdado não corresponde a esta instalação.")
            }
            lease = try acquire(resource: resource, mode: .exclusive, inherited: descriptor)
        } else {
            lease = try acquire(resource: resource, mode: .shared)
        }
        active = true
    }

    /// For this executable's file-based workers only: stdin has no request
    /// payload, so Process can dup the real descriptor to fd 0 across exec.
    /// The returned handle must remain alive until the child has been reaped.
    static func configureChild(_ process: Process) throws -> FileHandle? {
        try activate()
        guard let own = Bundle.main.executableURL, let target = process.executableURL,
              target.resolvingSymlinksInPath().standardizedFileURL == own.resolvingSymlinksInPath().standardizedFileURL else {
            throw failure("O bloqueio nativo só pode ser transmitido ao próprio executável PDF.")
        }
        lock.lock(); let current = lease; lock.unlock()
        var environment = process.environment ?? ProcessInfo.processInfo.environment
        environment.removeValue(forKey: installerFDKey)
        environment.removeValue(forKey: installerBundleKey)
        environment.removeValue(forKey: carrierKey)
        guard let current else { process.environment = environment; return nil }
        let handle = try current.duplicate()
        environment[carrierKey] = current.mode.rawValue
        process.environment = environment
        process.standardInput = handle
        return handle
    }

    /// The engine consumes stdin as JSON and already combines stderr/stdout.
    /// Bootstrap receives a real lease on fd 2, duplicates it, restores stderr
    /// from stdout and execs the same bundled Python/engine. This remains held
    /// if the GUI is killed while the engine is still using bundle resources.
    static func configureRuntimeChild(_ process: Process) throws -> FileHandle? {
        try activate()
        lock.lock(); let current = lease; lock.unlock()
        guard let current else { return nil } // Development checkout unchanged.
        let bundle = Bundle.main.bundleURL
        let resources = bundle.appendingPathComponent("Contents/Resources", isDirectory: true)
        let python = resources.appendingPathComponent("runtime/bin/python3")
        let engine = resources.appendingPathComponent("engine/pdf_engine.py")
        let bootstrap = resources.appendingPathComponent("engine/runtime_lease.py")
        guard let executable = process.executableURL,
              executable.resolvingSymlinksInPath().standardizedFileURL == python.resolvingSymlinksInPath().standardizedFileURL else {
            throw failure("O bloqueio do motor só pode acompanhar o Python desta instalação.")
        }
        var arguments = process.arguments ?? []
        while let first = arguments.first, ["-E", "-s", "-B"].contains(first) { arguments.removeFirst() }
        guard let script = arguments.first,
              URL(fileURLWithPath: script).resolvingSymlinksInPath().standardizedFileURL == engine.resolvingSymlinksInPath().standardizedFileURL else {
            throw failure("O processo solicitado não corresponde ao motor desta instalação.")
        }
        var info = stat()
        guard lstat(bootstrap.path, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == 0 || info.st_uid == getuid(), info.st_size > 0, info.st_size <= 262_144 else {
            throw failure("O transporte do bloqueio do motor não foi instalado corretamente.")
        }
        let handle = try current.duplicate()
        var environment = process.environment ?? ProcessInfo.processInfo.environment
        for key in [installerFDKey, installerBundleKey, carrierKey, "PDF_RUNTIME_LEASE_FD", "PDF_RUNTIME_LEASE_MODE", "PDF_RUNTIME_LEASE_STDERR", "PDF_RUNTIME_LEASE_BUNDLE"] {
            environment.removeValue(forKey: key)
        }
        environment["PDF_RUNTIME_LEASE_STDERR"] = current.mode.rawValue
        environment["PDF_RUNTIME_LEASE_BUNDLE"] = bundle.path
        process.environment = environment
        process.arguments = ["-E", "-s", "-B", bootstrap.path, "--bootstrap", engine.path] + Array(arguments.dropFirst())
        process.standardError = handle
        return handle
    }

    /// Direct PDF serialization uses qpdf with private stdin and a separate
    /// inspection result on stdout. Its bootstrap restores stderr to /dev/null,
    /// then execs qpdf in-place: credentials, PID and cancellation stay intact.
    static func configureQPDFChild(_ process: Process) throws -> FileHandle? {
        try activate()
        lock.lock(); let current = lease; lock.unlock()
        guard let current else { return nil }
        let bundle = Bundle.main.bundleURL
        let resources = bundle.appendingPathComponent("Contents/Resources", isDirectory: true)
        let python = resources.appendingPathComponent("runtime/bin/python3")
        let bootstrap = resources.appendingPathComponent("engine/runtime_lease.py")
        let portable = FileManager.default.fileExists(atPath: resources.appendingPathComponent("runtime/portable.json").path)
        let expected = portable ? resources.appendingPathComponent("runtime/bin/qpdf") : URL(fileURLWithPath: "/opt/homebrew/bin/qpdf")
        guard let executable = process.executableURL,
              executable.resolvingSymlinksInPath().standardizedFileURL == expected.resolvingSymlinksInPath().standardizedFileURL,
              process.arguments == ["--job-json-file=/dev/stdin"], FileManager.default.isExecutableFile(atPath: python.path) else {
            throw failure("O verificador não corresponde ao protocolo privado desta instalação.")
        }
        var info = stat()
        guard lstat(bootstrap.path, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == 0 || info.st_uid == getuid(), info.st_size > 0, info.st_size <= 262_144 else {
            throw failure("O transporte do bloqueio do verificador não foi instalado corretamente.")
        }
        let handle = try current.duplicate()
        var environment = process.environment ?? ProcessInfo.processInfo.environment
        for key in [installerFDKey, installerBundleKey, carrierKey, "PDF_RUNTIME_LEASE_FD", "PDF_RUNTIME_LEASE_MODE", "PDF_RUNTIME_LEASE_STDERR", "PDF_RUNTIME_LEASE_BUNDLE"] {
            environment.removeValue(forKey: key)
        }
        environment["PDF_RUNTIME_LEASE_STDERR"] = current.mode.rawValue
        environment["PDF_RUNTIME_LEASE_BUNDLE"] = bundle.path
        process.environment = environment
        process.executableURL = python
        process.arguments = ["-E", "-s", "-B", bootstrap.path, "--qpdf", expected.path, "--job-json-file=/dev/stdin"]
        process.standardError = handle
        return handle
    }

    /// Shared by the runtime and the isolated native process audit. The inode,
    /// permissions and actual kernel lock are all checked; environment text is
    /// never sufficient proof of a lease.
    static func acquire(resource: URL, mode: Mode, inherited: Int32? = nil) throws -> Lease {
        let expected = Darwin.open(resource.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard expected >= 0 else { throw failure("Esta instalação não possui um bloqueio válido. Reinstale o PDF em uma pasta nova.") }
        var retained = false
        defer { if !retained { Darwin.close(expected) } }
        let identity = try validate(expected)
        if let inherited {
            let received = try validate(inherited)
            guard received.device == identity.device && received.inode == identity.inode else {
                throw failure("O descritor recebido pertence a outro aplicativo.")
            }
            // A fresh SH probe proves whether an EX description already exists.
            // Never downgrade the installer's actual EX because an environment
            // value incorrectly claims SH; nor manufacture EX from an unlocked fd.
            let probe = flock(expected, LOCK_SH | LOCK_NB)
            let reason = errno
            guard probe == 0 || (probe == -1 && (reason == EWOULDBLOCK || reason == EAGAIN)),
                  (probe == -1) == (mode == .exclusive) else {
                throw failure("O modo informado não corresponde ao bloqueio real do aplicativo.")
            }
            guard flock(inherited, mode.operation | LOCK_NB) == 0 else { throw failure("O bloqueio herdado não está disponível.") }
            let copy = fcntl(inherited, F_DUPFD_CLOEXEC, 3)
            guard copy >= 0 else { throw failure("Não foi possível manter o bloqueio herdado.") }
            return Lease(descriptor: copy, mode: mode)
        }
        guard flock(expected, mode.operation | LOCK_NB) == 0 else {
            throw failure("O PDF está sendo atualizado. Aguarde a conclusão antes de abrir o aplicativo.")
        }
        retained = true
        return Lease(descriptor: expected, mode: mode)
    }

    private static func validate(_ descriptor: Int32) throws -> (device: dev_t, inode: ino_t) {
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_size == 0, info.st_nlink == 1, info.st_uid == 0 || info.st_uid == getuid(),
              info.st_mode & 0o222 == 0 else {
            throw failure("O recurso de bloqueio deve ser regular, vazio e somente leitura.")
        }
        return (info.st_dev, info.st_ino)
    }
    private static func failure(_ message: String) -> NSError {
        NSError(domain: "PDF.BundleLease", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
