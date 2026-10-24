import Foundation

struct LibraryConfigurationSnapshot: Codable, Identifiable, Sendable, Equatable {
    let id: String
    let kind: String
    let created: Date
    let device: UUID
    let payloadHash: String
    let byteCount: Int
    let schema: Int
}

/// A transferable snapshot is inert JSON, never an executable preference file.
/// The settings UI validates its domain schema again before explicit application.
enum LibraryConfigurationFiles {
    static let maximumEnvelope = 12 * 1_024 * 1_024
    static let maximumTotal = 128 * 1_024 * 1_024
    struct Envelope: Codable {
        let schema: Int
        let kind: String
        let created: Date
        let device: UUID
        let payloadHash: String
        let payload: Data
    }
    static func validatePayload(kind: String, payload: Data) throws {
        guard ["preferences", "profiles", "bookmarks"].contains(kind), !payload.isEmpty, payload.count <= 8 * 1_024 * 1_024 else { throw LibraryFailure.invalidMetadata }
        let value = try JSONSerialization.jsonObject(with: payload)
        guard JSONSerialization.isValidJSONObject(value) else { throw LibraryFailure.corrupt }
        func inspect(_ value: Any, depth: Int) throws {
            guard depth <= 32 else { throw LibraryFailure.corrupt }
            if let map = value as? [String: Any] {
                for (key, item) in map {
                    let normalized = key.lowercased()
                    guard !normalized.contains("password"), !["senha", "secret", "credential", "privatekey", "private_key"].contains(normalized) else {
                        throw SemanticEvidence.failure("A troca de configurações não aceita credenciais ou senhas.")
                    }
                    try inspect(item, depth: depth + 1)
                }
            } else if let array = value as? [Any] {
                for item in array { try inspect(item, depth: depth + 1) }
            }
        }
        try inspect(value, depth: 0)
    }
    static func encode(kind: String, payload: Data, device: UUID) throws -> Data {
        try validatePayload(kind: kind, payload: payload)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let bytes = try encoder.encode(Envelope(schema: 1, kind: kind, created: Date(), device: device, payloadHash: LibraryFiles.hash(payload), payload: payload))
        guard bytes.count <= maximumEnvelope else { throw LibraryFailure.tooLarge }
        return bytes
    }
    static func decode(_ bytes: Data, expectedHash: String) throws -> (LibraryConfigurationSnapshot, Data) {
        guard bytes.count <= maximumEnvelope, LibraryFiles.validHash(expectedHash), LibraryFiles.hash(bytes) == expectedHash else { throw LibraryFailure.corrupt }
        let envelope = try JSONDecoder().decode(Envelope.self, from: bytes)
        guard envelope.schema == 1, envelope.created.timeIntervalSince1970.isFinite,
              (0...32_503_680_000).contains(envelope.created.timeIntervalSince1970),
              LibraryFiles.validHash(envelope.payloadHash), LibraryFiles.hash(envelope.payload) == envelope.payloadHash else { throw LibraryFailure.corrupt }
        try validatePayload(kind: envelope.kind, payload: envelope.payload)
        return (LibraryConfigurationSnapshot(id: expectedHash, kind: envelope.kind, created: envelope.created, device: envelope.device,
                                             payloadHash: envelope.payloadHash, byteCount: envelope.payload.count, schema: envelope.schema), envelope.payload)
    }
    static func files(_ folder: URL) throws -> [URL] {
        let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil).filter { !$0.lastPathComponent.hasPrefix(".") }
        guard files.count <= 128, files.allSatisfy({ $0.pathExtension == "json" && LibraryFiles.validHash($0.deletingPathExtension().lastPathComponent) }) else {
            throw SemanticEvidence.failure("A troca de configurações exige até 128 snapshots JSON com nomes verificáveis. Nenhum ajuste foi aplicado.")
        }
        return files.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }
    static func read(_ url: URL) throws -> (LibraryConfigurationSnapshot, Data, Data) {
        let bytes = try LibraryFiles.read(url, maximum: maximumEnvelope)
        let (metadata, payload) = try decode(bytes, expectedHash: url.deletingPathExtension().lastPathComponent)
        return (metadata, payload, bytes)
    }
}
