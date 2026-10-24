import Foundation

/// Seekable private stdin prevents a cancelled/failed child from trapping a
/// writer in a full pipe or delivering SIGPIPE to the application process.
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
            handle = try FileHandle(forReadingFrom: file)
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
        let directoryMode = try FileManager.default.attributesOfItem(atPath: input.directory.path)[.posixPermissions] as? NSNumber
        let fileMode = try FileManager.default.attributesOfItem(atPath: input.file.path)[.posixPermissions] as? NSNumber
        guard directoryMode?.intValue == 0o700, fileMode?.intValue == 0o600,
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
