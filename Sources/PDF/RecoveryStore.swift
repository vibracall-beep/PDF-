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
}

enum RecoveryError: LocalizedError {
    case invalidState, invalidDocument, unsafePath, invalidRecord, tooLarge, encryptionMismatch, changed
    var errorDescription:String? {
        switch self {
        case .invalidState: return "O estado da sessão de leitura é inválido."
        case .invalidDocument: return "A cópia de recuperação não contém um PDF válido."
        case .unsafePath: return "O armazenamento de recuperação contém um caminho, link ou arquivo que não pode ser usado com segurança."
        case .invalidRecord: return "Uma cópia de recuperação está incompleta ou possui metadados inválidos. Ela foi preservada."
        case .tooLarge: return "Esta cópia excede o limite de 1 GB da recuperação automática. Salve uma cópia pelo menu Arquivo."
        case .encryptionMismatch: return "A recuperação de um documento protegido exige uma cópia criptografada que não aceite senha vazia. A senha não é gravada."
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
    init(directory:URL = RecoveryStore.defaultDirectory) { self.directory = directory.standardizedFileURL }

    func list() throws -> [RecoveryRecord] {
        lock.lock(); defer { lock.unlock() }
        try prepareDirectory(); notices = []
        let all = try records()
        var latest:[UUID:RecoveryRecord] = [:]
        for record in all {
            if latest[record.id].map({ $0.modifiedAt < record.modifiedAt }) ?? true { latest[record.id] = record }
        }
        return latest.values.sorted { $0.modifiedAt > $1.modifiedAt }
    }

    func save(documentData:Data, sourceURL:URL?, sessionID:UUID, encrypted:Bool, title:String, state:RecoverySessionState) throws {
        lock.lock(); defer { lock.unlock() }
        try Task.checkCancellation()
        try state.validate()
        guard sourceURL == nil || sourceURL!.isFileURL else { throw RecoveryError.invalidState }
        guard documentData.count <= maximumPDFBytes else { throw RecoveryError.tooLarge }
        try checkDocument(documentData, encrypted:encrypted)
        try prepareDirectory()
        let previous = try records().filter { $0.id == sessionID }
        let generation = UUID()
        let temporary = directory.appendingPathComponent(".pending-" + generation.uuidString,isDirectory:true)
        let destination = folder(generation)
        try FileManager.default.createDirectory(at:temporary,withIntermediateDirectories:false,attributes:[.posixPermissions:0o700])
        let identity = try directoryIdentity(temporary)
        var published = false
        defer {
            if !published, (try? directoryIdentity(temporary)) == identity { try? FileManager.default.removeItem(at:temporary) }
        }
        let cleanTitle = String(title.split(whereSeparator:{ $0.isNewline }).joined(separator:" ").prefix(200))
        let latestDate = previous.map(\.modifiedAt).max() ?? .distantPast
        let record = RecoveryRecord(id:sessionID,title:cleanTitle.isEmpty ? "Documento PDF" : cleanTitle,
                                    sourceURL:sourceURL,encrypted:encrypted,state:state,
                                    modifiedAt:max(Date(),latestDate.addingTimeInterval(0.001)),version:1,generation:generation,
                                    sha256:digest(documentData))
        try NativeOutput.write(documentData,to:temporary.appendingPathComponent("document.pdf"))
        try NativeOutput.write(JSONEncoder().encode(record),to:temporary.appendingPathComponent("record.json"))
        try synchronize(temporary.appendingPathComponent("document.pdf"))
        try synchronize(temporary.appendingPathComponent("record.json"))
        try synchronizeDirectory(temporary)
        try Task.checkCancellation()
        try FileManager.default.moveItem(at:temporary,to:destination)
        published = true
        // Do not remove an older snapshot before both its replacement's files
        // and the parent's rename have reached the filesystem's sync boundary.
        try synchronizeDirectory(directory)
        // Cleanup happens only after the new generation is complete. A failure
        // leaves an older copy, rather than invalidating the successful snapshot.
        for old in previous {
            do { try removeGeneration(old) }
            catch { notice("Uma geração anterior foi preservada: " + error.localizedDescription) }
        }
    }

    func load(_ record:RecoveryRecord) throws -> Data {
        lock.lock(); defer { lock.unlock() }
        try prepareDirectory()
        let actual = try readRecord(at:folder(record.generation))
        guard actual == record else { throw RecoveryError.changed }
        let data = try readFile(folder(record.generation).appendingPathComponent("document.pdf"),maximum:maximumPDFBytes)
        guard digest(data) == record.sha256 else { throw RecoveryError.changed }
        try checkDocument(data,encrypted:record.encrypted)
        return data
    }

    func delete(_ id:UUID) throws {
        lock.lock(); defer { lock.unlock() }
        try prepareDirectory()
        for record in try records() where record.id == id { try removeGeneration(record) }
        try synchronizeDirectory(directory)
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
            if entry.lastPathComponent.hasPrefix(".pending-") { continue }
            guard UUID(uuidString:entry.lastPathComponent) != nil else {
                notice("Um item não reconhecido foi preservado na pasta de recuperação."); continue
            }
            do { result.append(try readRecord(at:entry)) }
            catch { notice("Uma cópia de recuperação não pôde ser listada e foi preservada: " + error.localizedDescription) }
        }
        return result
    }
    private func readRecord(at url:URL) throws -> RecoveryRecord {
        _ = try directoryIdentity(url)
        let record = try JSONDecoder().decode(RecoveryRecord.self,from:readFile(url.appendingPathComponent("record.json"),maximum:131_072))
        guard record.version == 1, record.generation.uuidString == url.lastPathComponent,
              !record.title.isEmpty, record.title.count <= 200, record.sourceURL == nil || record.sourceURL!.isFileURL,
              record.modifiedAt.timeIntervalSince1970.isFinite,
              record.sha256.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil else { throw RecoveryError.invalidRecord }
        try record.state.validate()
        let descriptor = try openFile(url.appendingPathComponent("document.pdf"),maximum:maximumPDFBytes)
        close(descriptor)
        return record
    }
    private func removeGeneration(_ record:RecoveryRecord) throws {
        let location = folder(record.generation)
        guard try readRecord(at:location) == record else { throw RecoveryError.changed }
        try FileManager.default.removeItem(at:location)
    }
    private func openFile(_ url:URL, maximum:Int) throws -> Int32 {
        let descriptor = Darwin.open(url.path,O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
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
        let descriptor = Darwin.open(url.path,O_WRONLY | O_NOFOLLOW | O_CLOEXEC)
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
        let changed = try IntelligenceText.PDF("Recovery snapshot after an edit.")
        try store.save(documentData:changed,sourceURL:source,sessionID:id,encrypted:false,title:"Alterado",state:state)
        let second = try store.list()
        try require(second.count == 1 && second[0].generation != first[0].generation,"A nova geração não substituiu atomicamente a anterior.")
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
        let reopened = PDFDocument(data:try store.load(protectedRecord))!
        try require(reopened.isLocked && !reopened.unlock(withPassword:"") && reopened.unlock(withPassword:"recovery-test-pass"),"A cópia protegida perdeu criptografia ou sua senha.")
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
        print("Recovery audit passed: atomic generations, state, encryption, original preservation, corruption and links")
    }
}
