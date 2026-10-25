import Foundation
import PDFKit
import CryptoKit
import Darwin

struct RecoverySessionState: Codable, Sendable, Equatable {
    var page: Int
    var zoom: Double
    var autoScale: Bool
    var bookmarks: [Int]
    init(page:Int = 1, zoom:Double = 1, autoScale:Bool = true, bookmarks:[Int] = []) {
        self.page = page; self.zoom = zoom; self.autoScale = autoScale; self.bookmarks = bookmarks
    }
    func validate() throws {
        guard (1...10_000_000).contains(page), zoom.isFinite, (0.05...100).contains(zoom),
              bookmarks.count <= 100_000, bookmarks.allSatisfy({ (1...10_000_000).contains($0) }),
              Set(bookmarks).count == bookmarks.count else { throw RecoveryError.invalidState }
    }
}

struct RecoveryRecord: Codable, Identifiable, Sendable, Equatable {
    let id: UUID
    let title: String
    let sourceURL: URL?
    let encrypted: Bool
    let state: RecoverySessionState
    let modifiedAt: Date
    fileprivate let version: Int
    fileprivate let generation: UUID
    fileprivate let sha256: String
    fileprivate func sameContent(as other: RecoveryRecord) -> Bool {
        id == other.id && version == other.version && generation == other.generation && sha256 == other.sha256 && encrypted == other.encrypted
            && title == other.title && sourceURL == other.sourceURL
    }
}

private struct RecoveryNavigation: Codable {
    let version: Int
    let sessionID: UUID
    let generation: UUID
    let sha256: String
    let state: RecoverySessionState
    let modifiedAt: Date
}

private struct RecoveryStagingFile: Codable {
    let identity: String
    let count: Int
    let prefixCount: Int
    let prefixSHA256: String
    let sha256: String
}
private struct RecoveryStaging: Codable {
    let version: Int
    let generation: UUID
    let parentIdentity: String
    let directoryIdentity: String
    let files: [String: RecoveryStagingFile]
}

enum RecoveryError: LocalizedError {
    case invalidState, invalidDocument, unsafePath, invalidRecord, tooLarge, metadataTooLarge, encryptionMismatch, changed, busy
    var errorDescription:String? {
        switch self {
        case .invalidState: return "O estado da sessão de leitura é inválido."
        case .invalidDocument: return "A cópia de recuperação não contém um PDF válido."
        case .unsafePath: return "O armazenamento de recuperação contém um caminho, link ou arquivo que não pode ser usado com segurança."
        case .invalidRecord: return "Uma cópia de recuperação está incompleta ou possui metadados inválidos. Ela foi preservada."
        case .tooLarge: return "Esta cópia excede o limite de 1 GB da recuperação automática. Salve uma cópia pelo menu Arquivo."
        case .metadataTooLarge: return "Os metadados da sessão excedem o limite de 128 KiB. Reduza a quantidade de marcadores antes de tentar novamente."
        case .encryptionMismatch: return "A recuperação de um documento protegido exige uma cópia criptografada que não aceite senha vazia. A senha não é gravada."
        case .busy: return "Outra instância do PDF está gravando a recuperação. Tente novamente em instantes."
        case .changed: return "A cópia de recuperação foi alterada ou danificada. Nenhum documento original foi substituído."
        }
    }
}

/// Immutable generations keep the previous complete snapshot until a new one is
/// published. This store never writes to sourceURL and never accepts a password.
final class RecoveryStore: @unchecked Sendable {
    static let shared = RecoveryStore()
    static var defaultDirectory:URL {
        FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0]
            .appendingPathComponent("PDF/Recovery",isDirectory:true)
    }
    let directory:URL
    private let lock = NSRecursiveLock()
    private var notices:[String] = []
    var warnings:[String] { lock.lock(); defer { lock.unlock() }; return notices }
    private let maximumPDFBytes = 1_073_741_824
    // The observer is injected only by the internal fault harness. It cannot
    // be enabled by preferences, a PDF, CLI options or environment variables.
    private let checkpoint: ((String) throws -> Void)?
    init(directory:URL = RecoveryStore.defaultDirectory, checkpoint: ((String) throws -> Void)? = nil) {
        self.directory = directory.standardizedFileURL; self.checkpoint = checkpoint
    }

    func list() throws -> [RecoveryRecord] {
        lock.lock(); defer { lock.unlock() }
        try prepareDirectory(); notices = []
        // A live writer is never cleaned. Listing the last atomic generation
        // remains possible while another process owns the write lease.
        do {
            let descriptor = try processLock()
            defer { close(descriptor) }
            cleanupStaging()
        } catch RecoveryError.busy { }
        catch { notice("A limpeza de temporários foi adiada: " + error.localizedDescription) }
        let all = try records()
        var latest:[UUID:RecoveryRecord] = [:]
        for record in all {
            if latest[record.id].map({ $0.modifiedAt < record.modifiedAt }) ?? true { latest[record.id] = record }
        }
        return latest.values.sorted { $0.modifiedAt > $1.modifiedAt }
    }

    @discardableResult func save(documentData:Data, sourceURL:URL?, sessionID:UUID, encrypted:Bool, title:String, state:RecoverySessionState) throws -> RecoveryRecord {
        lock.lock(); defer { lock.unlock() }
        try Task.checkCancellation()
        try state.validate()
        guard sourceURL == nil || sourceURL!.isFileURL else { throw RecoveryError.invalidState }
        guard documentData.count <= maximumPDFBytes else { throw RecoveryError.tooLarge }
        try checkDocument(documentData, encrypted:encrypted)
        try prepareDirectory()
        let processDescriptor = try processLock(); defer { close(processDescriptor) }
        cleanupStaging()
        let previous = try records().filter { $0.id == sessionID }
        let generation = UUID()
        let cleanTitle = String(title.split(whereSeparator:{ $0.isNewline }).joined(separator:" ").prefix(200))
        let latestDate = previous.map(\.modifiedAt).max() ?? .distantPast
        let record = RecoveryRecord(id:sessionID,title:cleanTitle.isEmpty ? "Documento PDF" : cleanTitle,
                                    sourceURL:sourceURL,encrypted:encrypted,state:state,
                                    modifiedAt:max(Date(),latestDate.addingTimeInterval(0.001)),version:1,generation:generation,
                                    sha256:digest(documentData))
        let encoded = try boundedMetadata(record)
        let (temporary, ownership) = try makeStaging(generation: generation, files: ["document.pdf": documentData, "record.json": encoded])
        let destination = folder(generation)
        var published = false
        defer {
            if !published { cleanupOneStaging(temporary) }
        }
        try checkpoint?("staging-registered")
        try writeStaged(documentData, name: "document.pdf", at: temporary, ownership: ownership, phase: "pdf")
        try writeStaged(encoded, name: "record.json", at: temporary, ownership: ownership, phase: "metadata")
        try synchronizeDirectory(temporary)
        try checkpoint?("generation-synchronized")
        try Task.checkCancellation()
        try FileManager.default.moveItem(at:temporary,to:destination)
        published = true
        try checkpoint?("generation-published")
        // Do not remove an older snapshot before both its replacement's files
        // and the parent's rename have reached the filesystem's sync boundary.
        try synchronizeDirectory(directory)
        // Cleanup happens only after the new generation is complete. A failure
        // leaves an older copy, rather than invalidating the successful snapshot.
        for old in previous {
            do { try removeGeneration(old) }
            catch { notice("Uma geração anterior foi preservada: " + error.localizedDescription) }
        }
        return record
    }

    /// Update only navigation, never PDF bytes or encryption. A caller holding
    /// an older listing can still load this generation after navigation changes.
    /// nil means another content generation has replaced the expected snapshot.
    func updateState(record expected: RecoveryRecord, state: RecoverySessionState) throws -> RecoveryRecord? {
        lock.lock(); defer { lock.unlock() }
        try Task.checkCancellation(); try state.validate(); try prepareDirectory()
        let processDescriptor = try processLock(); defer { close(processDescriptor) }
        cleanupStaging()
        let current = try records().filter { $0.id == expected.id }.max { $0.modifiedAt < $1.modifiedAt }
        guard let current, current.sameContent(as: expected) else { return nil }
        let location = folder(current.generation), identity = try directoryIdentity(location)
        let base = try readRecord(at: location, includeNavigation: false)
        // Do not overwrite or delete a malformed sidecar. The immutable PDF
        // remains loadable and its original navigation state remains available.
        _ = try readNavigation(at: location, for: base)
        let navigation = RecoveryNavigation(version: 1, sessionID: current.id, generation: current.generation,
            sha256: current.sha256, state: state, modifiedAt: max(Date(), current.modifiedAt.addingTimeInterval(0.001)))
        let encoded = try boundedMetadata(navigation)
        let (staging, ownership) = try makeStaging(generation: UUID(), files: ["navigation.json": encoded])
        defer { cleanupOneStaging(staging) }
        let temporary = staging.appendingPathComponent("navigation.json")
        try writeStaged(encoded, name: "navigation.json", at: staging, ownership: ownership, phase: "navigation")
        try Task.checkCancellation()
        guard try directoryIdentity(location) == identity else { throw RecoveryError.changed }
        let destination = location.appendingPathComponent("navigation.json")
        try Task.checkCancellation()
        guard Darwin.rename(temporary.path, destination.path) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        try synchronizeDirectory(location)
        try checkpoint?("navigation-published")
        return applying(navigation, to: base)
    }

    func load(_ record:RecoveryRecord) throws -> Data {
        lock.lock(); defer { lock.unlock() }
        try prepareDirectory()
        let actual = try readRecord(at:folder(record.generation))
        guard actual.sameContent(as: record) else { throw RecoveryError.changed }
        let data = try readFile(folder(record.generation).appendingPathComponent("document.pdf"),maximum:maximumPDFBytes)
        guard digest(data) == record.sha256 else { throw RecoveryError.changed }
        try checkDocument(data,encrypted:record.encrypted)
        return data
    }

    func delete(_ id:UUID) throws {
        lock.lock(); defer { lock.unlock() }
        try prepareDirectory()
        let processDescriptor = try processLock(); defer { close(processDescriptor) }
        cleanupStaging()
        for record in try records() where record.id == id { try removeGeneration(record) }
        try synchronizeDirectory(directory)
    }

    private func processLock() throws -> Int32 {
        let path = directory.appendingPathComponent(".store.lock")
        let fd = Darwin.open(path.path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw RecoveryError.unsafePath }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_nlink == 1, info.st_mode & 0o077 == 0 else {
            close(fd); throw RecoveryError.unsafePath
        }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            let failure = errno; close(fd)
            if failure == EWOULDBLOCK { throw RecoveryError.busy }
            throw POSIXError(POSIXErrorCode(rawValue: failure) ?? .EIO)
        }
        return fd
    }
    private func fileIdentity(_ info: stat) -> String { "\(info.st_dev):\(info.st_ino)" }
    private func makeStaging(generation: UUID, files: [String: Data]) throws -> (URL, RecoveryStaging) {
        let location = directory.appendingPathComponent(".pending-" + generation.uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: location, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let ownedIdentity = try directoryIdentity(location)
        var entries: [String: RecoveryStagingFile] = [:]
        do {
            for (name, data) in files {
                let fd = Darwin.open(location.appendingPathComponent(name).path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
                guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
                var info = stat()
                let valid = fstat(fd, &info) == 0 && fsync(fd) == 0
                close(fd)
                guard valid else { throw RecoveryError.unsafePath }
                let prefixCount = min(65_536, max(1, data.count / 2))
                entries[name] = RecoveryStagingFile(identity: fileIdentity(info), count: data.count,
                    prefixCount: prefixCount, prefixSHA256: digest(Data(data.prefix(prefixCount))), sha256: digest(data))
            }
            let ownership = RecoveryStaging(version: 1, generation: generation,
                parentIdentity: try directoryIdentity(directory), directoryIdentity: ownedIdentity, files: entries)
            try NativeOutput.write(try boundedMetadata(ownership), to: location.appendingPathComponent(".owner.json"))
            try synchronizeDirectory(location); try synchronizeDirectory(directory)
            return (location, ownership)
        } catch {
            if (try? directoryIdentity(location)) == ownedIdentity { try? FileManager.default.removeItem(at: location) }
            throw error
        }
    }
    private func writeStaged(_ data: Data, name: String, at location: URL, ownership: RecoveryStaging, phase: String) throws {
        guard let entry = ownership.files[name], try directoryIdentity(location) == ownership.directoryIdentity else { throw RecoveryError.changed }
        let fd = Darwin.open(location.appendingPathComponent(name).path, O_WRONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard fd >= 0 else { throw RecoveryError.unsafePath }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_nlink == 1,
              info.st_uid == getuid(), info.st_size == 0, fileIdentity(info) == entry.identity else { throw RecoveryError.changed }
        // Two real writes expose an incomplete-file boundary to the failure
        // harness. Both files remain hidden until their generation is durable.
        try handle.write(contentsOf: data.prefix(entry.prefixCount))
        try checkpoint?(phase + "-partial")
        try Task.checkCancellation()
        try handle.write(contentsOf: data.dropFirst(entry.prefixCount))
        try handle.synchronize()
        try checkpoint?(phase + "-written")
    }
    private func cleanupStaging() {
        guard let entries = try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else { return }
        for entry in entries where entry.lastPathComponent.hasPrefix(".pending-") { cleanupOneStaging(entry) }
    }
    private func cleanupOneStaging(_ location: URL) {
        do {
            let marker = location.appendingPathComponent(".owner.json")
            let expectedDirectory = try directoryIdentity(location)
            var markerInfo = stat(), directoryInfo = stat()
            guard lstat(marker.path, &markerInfo) == 0, markerInfo.st_mode & S_IFMT == S_IFREG,
                  markerInfo.st_uid == getuid(), markerInfo.st_nlink == 1, markerInfo.st_mode & 0o077 == 0,
                  lstat(location.path, &directoryInfo) == 0, directoryInfo.st_mode & 0o077 == 0 else { throw RecoveryError.unsafePath }
            let ownership = try JSONDecoder().decode(RecoveryStaging.self, from: readFile(marker, maximum: 131_072))
            let keys = Set(ownership.files.keys)
            guard ownership.version == 1, location.lastPathComponent == ".pending-" + ownership.generation.uuidString,
                  ownership.parentIdentity == (try directoryIdentity(directory)), ownership.directoryIdentity == expectedDirectory,
                  keys == ["document.pdf", "record.json"] || keys == ["navigation.json"] else { throw RecoveryError.unsafePath }
            let actual = try FileManager.default.contentsOfDirectory(atPath: location.path)
            // A published navigation file has moved into its immutable PDF's
            // generation. Missing managed files are allowed; unknown files,
            // links and replacements are never recursively discarded.
            guard Set(actual).isSubset(of: keys.union([".owner.json"])) else { throw RecoveryError.unsafePath }
            for name in keys where actual.contains(name) {
                guard let entry = ownership.files[name], entry.count > 0, entry.prefixCount > 0,
                      entry.prefixCount < entry.count, entry.sha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
                      entry.prefixSHA256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { throw RecoveryError.invalidRecord }
                let maximum = name == "document.pdf" ? maximumPDFBytes : 131_072
                guard entry.count <= maximum else { throw RecoveryError.tooLarge }
                let fd = try openFile(location.appendingPathComponent(name), maximum: maximum)
                let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
                defer { try? handle.close() }
                var info = stat()
                guard fstat(fd, &info) == 0, fileIdentity(info) == entry.identity else { throw RecoveryError.changed }
                let count = Int(info.st_size)
                guard count == 0 || count == entry.prefixCount || count == entry.count else { throw RecoveryError.changed }
                var hash = SHA256()
                while let part = try handle.read(upToCount: 1_048_576), !part.isEmpty { hash.update(data: part) }
                let result = hash.finalize().map { String(format: "%02x", $0) }.joined()
                if count > 0 {
                    guard result == (count == entry.count ? entry.sha256 : entry.prefixSHA256) else { throw RecoveryError.changed }
                }
            }
            guard try directoryIdentity(location) == expectedDirectory,
                  Set(try FileManager.default.contentsOfDirectory(atPath: location.path)) == Set(actual) else { throw RecoveryError.changed }
            for name in keys where actual.contains(name) {
                let path = location.appendingPathComponent(name)
                var info = stat()
                guard lstat(path.path, &info) == 0, fileIdentity(info) == ownership.files[name]?.identity,
                      info.st_mode & S_IFMT == S_IFREG, info.st_nlink == 1 else { throw RecoveryError.changed }
                guard Darwin.unlink(path.path) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            }
            var currentMarker = stat()
            guard lstat(marker.path, &currentMarker) == 0, fileIdentity(currentMarker) == fileIdentity(markerInfo),
                  try directoryIdentity(location) == expectedDirectory else { throw RecoveryError.changed }
            guard Darwin.unlink(marker.path) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            // rmdir refuses an unexpected concurrent addition. Never recurse
            // through an unreviewed file that appeared after our inspection.
            guard Darwin.rmdir(location.path) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            try synchronizeDirectory(directory)
        } catch {
            notice("Um temporário de recuperação não pôde ser identificado com segurança e foi preservado: " + error.localizedDescription)
        }
    }

    private func prepareDirectory() throws {
        let manager = FileManager.default
        if !manager.fileExists(atPath:directory.path) {
            // fileExists follows links; lstat also catches a dangling link.
            var info = stat()
            if lstat(directory.path,&info) == 0 { throw RecoveryError.unsafePath }
            try manager.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        }
        _ = try directoryIdentity(directory)
        try manager.setAttributes([.posixPermissions:0o700],ofItemAtPath:directory.path)
    }
    private func folder(_ generation:UUID) -> URL { directory.appendingPathComponent(generation.uuidString,isDirectory:true) }
    private func directoryIdentity(_ url:URL) throws -> String {
        var info = stat()
        guard lstat(url.path,&info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFDIR), info.st_uid == getuid() else { throw RecoveryError.unsafePath }
        return "\(info.st_dev):\(info.st_ino)"
    }
    private func records() throws -> [RecoveryRecord] {
        var result:[RecoveryRecord] = []
        for entry in try FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil) {
            if entry.lastPathComponent.hasPrefix(".pending-") || entry.lastPathComponent == ".store.lock" { continue }
            guard UUID(uuidString:entry.lastPathComponent) != nil else {
                notice("Um item não reconhecido foi preservado na pasta de recuperação."); continue
            }
            do { result.append(try readRecord(at:entry)) }
            catch { notice("Uma cópia de recuperação não pôde ser listada e foi preservada: " + error.localizedDescription) }
        }
        return result
    }
    private func readRecord(at url:URL, includeNavigation: Bool = true) throws -> RecoveryRecord {
        _ = try directoryIdentity(url)
        let record = try JSONDecoder().decode(RecoveryRecord.self,from:readFile(url.appendingPathComponent("record.json"),maximum:131_072))
        guard record.version == 1, record.generation.uuidString == url.lastPathComponent,
              !record.title.isEmpty, record.title.count <= 200, record.sourceURL == nil || record.sourceURL!.isFileURL,
              record.modifiedAt.timeIntervalSince1970.isFinite,
              record.sha256.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil else { throw RecoveryError.invalidRecord }
        try record.state.validate()
        let descriptor = try openFile(url.appendingPathComponent("document.pdf"),maximum:maximumPDFBytes)
        close(descriptor)
        if includeNavigation {
            do { if let navigation = try readNavigation(at: url, for: record) { return applying(navigation, to: record) } }
            catch { notice("O estado de navegação de uma recuperação está inválido e foi preservado. O PDF permanece disponível: " + error.localizedDescription) }
        }
        return record
    }
    private func removeGeneration(_ record:RecoveryRecord) throws {
        let location = folder(record.generation)
        guard try readRecord(at:location).sameContent(as: record) else { throw RecoveryError.changed }
        try FileManager.default.removeItem(at:location)
    }
    private func openFile(_ url:URL, maximum:Int) throws -> Int32 {
        // Opening a FIFO must not block before fstat can reject its file type.
        let descriptor = Darwin.open(url.path,O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw RecoveryError.unsafePath }
        var info = stat()
        guard fstat(descriptor,&info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              info.st_uid == getuid(), info.st_nlink == 1, info.st_size >= 0 else {
            close(descriptor); throw RecoveryError.unsafePath
        }
        guard info.st_size <= maximum else { close(descriptor); throw RecoveryError.tooLarge }
        return descriptor
    }
    private func readFile(_ url:URL, maximum:Int) throws -> Data {
        let descriptor = try openFile(url,maximum:maximum)
        let handle = FileHandle(fileDescriptor:descriptor,closeOnDealloc:true)
        defer { try? handle.close() }
        var result = Data()
        while let part = try handle.read(upToCount:min(1_048_576,maximum-result.count+1)), !part.isEmpty {
            result.append(part)
            guard result.count <= maximum else { throw RecoveryError.tooLarge }
        }
        return result
    }
    private func synchronize(_ url:URL) throws {
        let descriptor = Darwin.open(url.path,O_WRONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw RecoveryError.unsafePath }
        defer { close(descriptor) }
        var info = stat()
        guard fstat(descriptor,&info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG), info.st_uid == getuid(), info.st_nlink == 1 else { throw RecoveryError.unsafePath }
        guard fsync(descriptor) == 0 else { throw POSIXError(POSIXErrorCode(rawValue:errno) ?? .EIO) }
    }
    private func notice(_ text:String) { if !notices.contains(text), notices.count < 50 { notices.append(text) } }
    private func synchronizeDirectory(_ url:URL) throws {
        _ = try directoryIdentity(url)
        let descriptor = Darwin.open(url.path,O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw RecoveryError.unsafePath }
        defer { close(descriptor) }
        guard fsync(descriptor) == 0 else { throw POSIXError(POSIXErrorCode(rawValue:errno) ?? .EIO) }
    }
    private func digest(_ data:Data) -> String { SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined() }
    private func boundedMetadata<T: Encodable>(_ value: T) throws -> Data {
        let encoded = try JSONEncoder().encode(value)
        guard encoded.count <= 131_072 else { throw RecoveryError.metadataTooLarge }
        return encoded
    }
    private func readNavigation(at location: URL, for record: RecoveryRecord) throws -> RecoveryNavigation? {
        let url = location.appendingPathComponent("navigation.json")
        var info = stat()
        guard lstat(url.path, &info) == 0 else {
            if errno == ENOENT { return nil }
            throw RecoveryError.unsafePath
        }
        let value = try JSONDecoder().decode(RecoveryNavigation.self, from: readFile(url, maximum: 131_072))
        guard value.version == 1, value.sessionID == record.id, value.generation == record.generation,
              value.sha256 == record.sha256, value.modifiedAt.timeIntervalSince1970.isFinite,
              value.modifiedAt >= record.modifiedAt else { throw RecoveryError.invalidRecord }
        try value.state.validate()
        return value
    }
    private func applying(_ navigation: RecoveryNavigation, to record: RecoveryRecord) -> RecoveryRecord {
        RecoveryRecord(id: record.id, title: record.title, sourceURL: record.sourceURL, encrypted: record.encrypted,
                       state: navigation.state, modifiedAt: navigation.modifiedAt, version: record.version,
                       generation: record.generation, sha256: record.sha256)
    }
    private func checkDocument(_ data:Data, encrypted:Bool) throws {
        guard let document = PDFDocument(data:data) else { throw RecoveryError.invalidDocument }
        guard document.isEncrypted == encrypted else { throw RecoveryError.encryptionMismatch }
        if encrypted {
            guard document.isLocked, !document.unlock(withPassword:"") else { throw RecoveryError.encryptionMismatch }
        } else if document.pageCount == 0 { throw RecoveryError.invalidDocument }
    }
}

@MainActor enum RecoveryAuditChecks {
    static func run() throws {
        func require(_ value:Bool,_ message:String) throws {
            if !value { throw NSError(domain:"PDF.RecoveryAudit",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-recovery-test-" + UUID().uuidString,isDirectory:true)
        defer { try? FileManager.default.removeItem(at:root) }
        let store = RecoveryStore(directory:root.appendingPathComponent("Recovery",isDirectory:true))
        let original = try IntelligenceText.PDF("Recovery preserves the original and annotations.")
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let source = root.appendingPathComponent("original.pdf")
        try NativeOutput.write(original,to:source)
        let id = UUID(), state = RecoverySessionState(page:1,zoom:1.5,autoScale:false,bookmarks:[1])
        try store.save(documentData:original,sourceURL:source,sessionID:id,encrypted:false,title:"Original",state:state)
        let first = try store.list()
        try require(first.count == 1 && first[0].state == state,"A sessão de recuperação perdeu página, zoom ou marcadores.")
        try require(try store.load(first[0]) == original,"A recuperação não preservou os bytes do documento.")
        let originalLocation = store.directory.appendingPathComponent(first[0].generation.uuidString).appendingPathComponent("document.pdf")
        let originalModification = try FileManager.default.attributesOfItem(atPath: originalLocation.path)[.modificationDate] as? Date
        let navigation = RecoverySessionState(page: 1, zoom: 2.25, autoScale: false, bookmarks: [])
        guard let navigated = try store.updateState(record: first[0], state: navigation) else { throw RecoveryError.changed }
        let afterNavigation = try store.list()
        try require(afterNavigation.first?.state == navigation && navigated.generation == first[0].generation,
                    "Atualizar navegação perdeu o estado ou criou outra geração do PDF.")
        try require(try Data(contentsOf: originalLocation) == original, "Atualizar navegação modificou os bytes do PDF.")
        let navigationModification = try FileManager.default.attributesOfItem(atPath: originalLocation.path)[.modificationDate] as? Date
        try require(originalModification != nil && navigationModification == originalModification, "Atualizar navegação regravou o PDF.")
        try require(try store.load(first[0]) == original, "Um registro listado antes da navegação deixou de carregar a mesma geração.")
        let navigationURL = originalLocation.deletingLastPathComponent().appendingPathComponent("navigation.json")
        let navigationPermissions = try FileManager.default.attributesOfItem(atPath: navigationURL.path)[.posixPermissions] as? NSNumber
        try require(navigationPermissions?.intValue == 0o600, "O estado de navegação não ficou privado.")
        _ = try store.updateState(record: navigated, state: RecoverySessionState())
        let resetNavigation = try store.list()
        try require(resetNavigation.first?.state == RecoverySessionState(), "Redefinir navegação não restaurou página, ajuste e marcadores padrão.")
        _ = try store.updateState(record: navigated, state: navigation)
        let afterResetModification = try FileManager.default.attributesOfItem(atPath: originalLocation.path)[.modificationDate] as? Date
        try require(afterResetModification == originalModification, "Redefinir navegação regravou o PDF.")
        let oversized = RecoverySessionState(bookmarks: Array(1...100_000))
        var oversizedRefused = false
        do { _ = try store.updateState(record: navigated, state: oversized) } catch RecoveryError.metadataTooLarge { oversizedRefused = true }
        let afterOversizedNavigation = try store.list()
        try require(oversizedRefused && afterOversizedNavigation.first?.state == navigation, "O sidecar excedeu o limite legível ou alterou o estado após recusa.")
        oversizedRefused = false
        do { try store.save(documentData: original, sourceURL: source, sessionID: id, encrypted: false, title: "Grande", state: oversized) }
        catch RecoveryError.metadataTooLarge { oversizedRefused = true }
        let afterOversizedRecord = try store.list()
        try require(oversizedRefused && afterOversizedRecord.first?.generation == first[0].generation, "O registro excedeu 128 KiB ou invalidou a geração anterior.")
        let changed = try IntelligenceText.PDF("Recovery snapshot after an edit.")
        try store.save(documentData:changed,sourceURL:source,sessionID:id,encrypted:false,title:"Alterado",state:state)
        let second = try store.list()
        try require(second.count == 1 && second[0].generation != first[0].generation,"A nova geração não substituiu atomicamente a anterior.")
        try require(try store.updateState(record: navigated, state: navigation) == nil, "Uma navegação antiga foi aplicada a uma nova geração de conteúdo.")
        try require(second[0].state == state, "A nova geração herdou o sidecar do conteúdo anterior.")
        try require(try Data(contentsOf:source) == original,"A recuperação alterou o arquivo original.")
        var refused = false
        do { try store.save(documentData:changed,sourceURL:source,sessionID:id,encrypted:true,title:"Protegido",state:state) } catch { refused = true }
        let afterRefusal = try store.list()
        try require(refused && afterRefusal.first?.generation == second[0].generation,"Um snapshot protegido aceitou texto claro ou invalidou a cópia anterior.")
        let document = PDFDocument(data:original)!
        let options:[AnyHashable:Any] = [AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue):"recovery-test-pass",AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue):"recovery-owner-pass"]
        guard let protected = document.dataRepresentation(options:options) else { throw RecoveryError.invalidDocument }
        let protectedID = UUID()
        try store.save(documentData:protected,sourceURL:source,sessionID:protectedID,encrypted:true,title:"Protegido",state:state)
        let protectedRecord = try store.list().first(where:{$0.id == protectedID})!
        let storedProtected = try store.load(protectedRecord)
        let envelope = PDFDocument(data: storedProtected)!
        let reopened = try NativePDFSerialization.open(data: storedProtected, password: "recovery-test-pass")
        try require(envelope.isLocked && !envelope.unlock(withPassword: "") && reopened.isEncrypted && !reopened.isLocked,
                    "A cópia protegida perdeu criptografia ou sua senha.")
        _ = try store.updateState(record: protectedRecord, state: navigation)
        let protectedNavigation = store.directory.appendingPathComponent(protectedRecord.generation.uuidString).appendingPathComponent("navigation.json")
        let protectedMetadata = try String(contentsOf: protectedNavigation, encoding: .utf8)
        try require(!protectedMetadata.contains("recovery-test-pass") && !protectedMetadata.contains("recovery-owner-pass"), "O sidecar persistiu credenciais.")
        let preservedEncrypted = try store.load(protectedRecord)
        try require(preservedEncrypted == protected && PDFDocument(data: preservedEncrypted)?.isLocked == true,
                    "Atualizar navegação alterou a criptografia do PDF protegido.")
        let unicodePassword = String(repeating: "🔑", count: 31) + "abc"
        let unicodeBytes = try NativePDFSerialization.serialize(document: PDFDocument(data: original)!, password: unicodePassword)
        try QPDFStructuralAudit.verifyAES256(unicodeBytes, password: unicodePassword)
        let unicodeID = UUID()
        let unicodeRecord = try store.save(documentData: unicodeBytes, sourceURL: source, sessionID: unicodeID,
                                          encrypted: true, title: "Recuperação Unicode", state: state)
        let loadedUnicode = try store.load(unicodeRecord)
        let unicodeOpening = try NativePDFSerialization.prepareOpen(data: loadedUnicode, password: unicodePassword)
        let unicodeDocument = try NativePDFSerialization.finishOpen(unicodeOpening)
        try require(unicodeOpening.originalData == unicodeBytes && unicodeDocument.isEncrypted && !unicodeDocument.isLocked &&
                    (unicodeDocument.string ?? "").contains("Recovery preserves the original"),
                    "A recuperação Unicode perdeu os bytes originais, a proteção ou o conteúdo.")
        _ = try store.updateState(record: unicodeRecord, state: navigation)
        let unicodeNavigation = store.directory.appendingPathComponent(unicodeRecord.generation.uuidString).appendingPathComponent("navigation.json")
        try require(!(try String(contentsOf: unicodeNavigation, encoding: .utf8)).contains(unicodePassword) &&
                    (try store.load(unicodeRecord)) == unicodeBytes && (try Data(contentsOf: source)) == original,
                    "A navegação Unicode persistiu credenciais ou alterou o snapshot/original.")
        try store.delete(unicodeID)
        let malformed = Data("malformed-navigation".utf8)
        try malformed.write(to: protectedNavigation)
        let afterMalformed = try store.list()
        try require(afterMalformed.contains(where: { $0.id == protectedID && $0.state == state }) && !store.warnings.isEmpty,
                    "Um sidecar inválido ocultou a recuperação válida ou não produziu diagnóstico.")
        try require(try store.load(protectedRecord) == protected, "O sidecar inválido impediu carregar o PDF intacto.")
        var malformedRefused = false
        do { _ = try store.updateState(record: protectedRecord, state: navigation) } catch { malformedRefused = true }
        let preservedMalformed = try Data(contentsOf: protectedNavigation)
        try require(malformedRefused && preservedMalformed == malformed, "Atualizar navegação destruiu um sidecar inválido que deveria ser preservado.")
        try FileManager.default.removeItem(at: protectedNavigation)
        guard Darwin.mkfifo(protectedNavigation.path, 0o600) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        let fifoStart = Date()
        let withFIFO = try store.list()
        try require(Date().timeIntervalSince(fifoStart) < 5 && withFIFO.contains(where: { $0.id == protectedID }) && !store.warnings.isEmpty,
                    "Um FIFO de navegação bloqueou a recuperação ou ocultou o PDF intacto.")
        try require(try store.load(protectedRecord) == protected, "Recusar um FIFO de navegação impediu carregar o PDF válido.")
        let plainLocation = store.directory.appendingPathComponent(second[0].generation.uuidString).appendingPathComponent("document.pdf")
        try Data("corrupted".utf8).write(to:plainLocation)
        refused = false
        do { _ = try store.load(second[0]) } catch { refused = true }
        try require(refused,"A recuperação aceitou bytes que não correspondem ao checksum.")
        try FileManager.default.removeItem(at:plainLocation)
        try FileManager.default.createSymbolicLink(at:plainLocation,withDestinationURL:source)
        let healthy = try store.list()
        try require(healthy.count == 1 && healthy[0].id == protectedID && !store.warnings.isEmpty,"Uma cópia inválida bloqueou outras recuperações ou foi aceita como link.")
        try store.delete(protectedID)
        try require(try store.list().isEmpty,"Excluir recuperação deixou uma sessão restaurável.")
        let permissions = try FileManager.default.attributesOfItem(atPath:store.directory.path)[.posixPermissions] as? NSNumber
        try require(permissions?.intValue == 0o700,"A pasta de recuperação não ficou privada.")
        try require(try Data(contentsOf:source) == original,"A limpeza da recuperação alterou a origem.")
        try interruptedWriteChecks(root: root, source: source, original: original)
        print("Recovery audit passed: atomic generations, state, encryption, original preservation, corruption, links and interrupted writes")
    }
    private static func interruptedWriteChecks(root: URL, source: URL, original: Data) throws {
        func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
            guard try condition() else { throw NSError(domain: "PDF.RecoveryWriteAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        let changed = try IntelligenceText.PDF("New generation must never replace the previous checkpoint with incomplete bytes.")
        let phases = ["staging-registered", "pdf-partial", "pdf-written", "metadata-partial", "metadata-written", "generation-synchronized"]
        for phase in phases {
            let location = root.appendingPathComponent("fault-" + phase, isDirectory: true), id = UUID()
            let store = RecoveryStore(directory: location)
            let baseline = try store.save(documentData: original, sourceURL: source, sessionID: id, encrypted: false,
                                          title: "Baseline", state: RecoverySessionState())
            let failing = RecoveryStore(directory: location, checkpoint: { point in
                if point == phase { throw POSIXError(.ENOSPC) }
            })
            var refused = false
            do { _ = try failing.save(documentData: changed, sourceURL: source, sessionID: id, encrypted: false, title: "New", state: RecoverySessionState(page: 2)) }
            catch let error as POSIXError { refused = error.code == .ENOSPC }
            try require(refused && (try store.load(baseline)) == original, "Erro durante " + phase + " destruiu a última geração completa.")
            let listed = try store.list()
            let items = try FileManager.default.contentsOfDirectory(atPath: location.path)
            try require(listed.count == 1 && listed[0] == baseline && !items.contains(where: { $0.hasPrefix(".pending-") }),
                        "Erro de escrita deixou uma geração parcial publicável ou staging registrado abandonado.")
        }
        let location = root.appendingPathComponent("foreign-staging", isDirectory: true), id = UUID()
        let store = RecoveryStore(directory: location)
        let baseline = try store.save(documentData: original, sourceURL: source, sessionID: id, encrypted: false, title: "Baseline", state: RecoverySessionState())
        let unknown = location.appendingPathComponent(".pending-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: unknown, withIntermediateDirectories: false)
        try NativeOutput.write(Data("user bytes".utf8), to: unknown.appendingPathComponent("keep.txt"))
        _ = try store.list()
        try require(FileManager.default.fileExists(atPath: unknown.appendingPathComponent("keep.txt").path) && !store.warnings.isEmpty,
                    "A limpeza removeu um diretório identificado apenas pelo nome.")
        try FileManager.default.removeItem(at: unknown)
        var replacement: URL?
        let foreign = RecoveryStore(directory: location, checkpoint: { phase in
            guard phase == "pdf-partial" else { return }
            let pending = try FileManager.default.contentsOfDirectory(at: location, includingPropertiesForKeys: nil).first { $0.lastPathComponent.hasPrefix(".pending-") }!
            let pdf = pending.appendingPathComponent("document.pdf")
            try FileManager.default.moveItem(at: pdf, to: root.appendingPathComponent("owned-partial-preserved.pdf"))
            try NativeOutput.write(Data("foreign replacement".utf8), to: pdf)
            replacement = pdf
            throw POSIXError(.EIO)
        })
        var rejected = false
        do { _ = try foreign.save(documentData: changed, sourceURL: source, sessionID: id, encrypted: false, title: "Foreign", state: RecoverySessionState()) }
        catch let error as POSIXError { rejected = error.code == .EIO }
        _ = try store.list()
        try require(rejected && replacement != nil && (try Data(contentsOf: replacement!)) == Data("foreign replacement".utf8) &&
                    (try store.load(baseline)) == original && !store.warnings.isEmpty,
                    "A recuperação removeu um arquivo substituído por terceiro ou perdeu a geração anterior.")
        try require((try Data(contentsOf: source)) == original, "A auditoria de escrita alterou a origem.")
    }

}
