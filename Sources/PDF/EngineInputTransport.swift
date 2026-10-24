import Foundation
import Darwin

/// Seekable private stdin prevents a cancelled/failed child from trapping a
/// writer in a full pipe or delivering SIGPIPE to the application process.
/// Unlink immediately after opening: process loss then releases the anonymous
/// descriptor without leaving an options pathname containing credentials.
final class EngineInputTransport: @unchecked Sendable {
    let directory: URL
    let file: URL
    let handle: FileHandle
    private let lock = NSLock()
    private var closed = false
    init(data: Data) throws {
        guard !data.isEmpty, data.count <= 64 * 1024 * 1024 else {
            throw NSError(domain: "PDF.EngineInput", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "As opções excedem o limite de 64 MiB da operação."])
        }
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-engine-input-" + UUID().uuidString, isDirectory: true)
        file = directory.appendingPathComponent("options.json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        do {
            try NativeOutput.write(data, to: file)
            let input = try FileHandle(forReadingFrom: file)
            do {
                try FileManager.default.removeItem(at: file)
                try FileManager.default.removeItem(at: directory)
            } catch { try? input.close(); throw error }
            handle = input
        } catch {
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
    }
    func close() {
        lock.lock(); defer { lock.unlock() }
        guard !closed else { return }; closed = true
        try? handle.close()
        try? FileManager.default.removeItem(at: directory)
    }
    deinit { close() }
}

enum EngineInputAuditChecks {
    static func run() throws {
        let payload = Data(("{\"text\":\"" + String(repeating: "áΩ", count: 300_000) + "\"}").utf8)
        let input = try EngineInputTransport(data: payload)
        defer { input.close() }
        var metadata = stat()
        guard fstat(input.handle.fileDescriptor, &metadata) == 0,
              metadata.st_mode & 0o777 == 0o600, metadata.st_nlink == 0,
              !FileManager.default.fileExists(atPath: input.directory.path),
              try input.handle.readToEnd() == payload else {
            throw NSError(domain: "PDF.EngineInputAudit", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "O transporte das opções não preservou bytes ou permissões privadas."])
        }
        input.close(); input.close()
        guard !FileManager.default.fileExists(atPath: input.directory.path) else {
            throw NSError(domain: "PDF.EngineInputAudit", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "O transporte de opções deixou arquivos após o fechamento."])
        }
    }
}
