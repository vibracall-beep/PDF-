import Foundation
import PDFKit
import CryptoKit
import Darwin

struct LibraryLabels: Codable, Sendable, Equatable {
    var title: String
    var collection: String
    var tags: [String]
}

struct LibraryRevision: Codable, Sendable, Equatable, Identifiable {
    let id: UUID
    let parents: [UUID]
    let fingerprint: String
    let byteCount: Int
    let pages: Int
    let encrypted: Bool
    let created: Date
    let note: String
    let labels: LibraryLabels
}

struct LibraryDocument: Codable, Sendable, Equatable, Identifiable {
    let id: UUID
    var preferred: UUID
    var revisions: [LibraryRevision]
    var current: LibraryRevision { revisions.first { $0.id == preferred }! }
    var heads: [LibraryRevision] {
        let ancestors = Set(revisions.flatMap(\.parents))
        return revisions.filter { !ancestors.contains($0.id) }.sorted { $0.id.uuidString < $1.id.uuidString }
    }
}

struct LibraryCatalog: Codable, Sendable, Equatable {
    var version = 1
    let device: UUID
    var documents: [LibraryDocument]
    static func empty() -> Self { .init(device: UUID(), documents: []) }
}

struct LibraryImportReport: Sendable {
    let imported: Int
    let duplicate: Int
    let catalog: LibraryCatalog
}

struct LibrarySyncReport: Sendable {
    let received: Int
    let conflicts: Int
    let configurationsReceived: Int
    let catalog: LibraryCatalog
}

enum LibraryFailure: LocalizedError {
    case unsafePath, corrupt, destinationExists, tooLarge, searchTooLarge, syncTooLarge, missing, busy, invalidPDF, invalidMetadata, noTextPermission
    var errorDescription: String? {
        switch self {
        case .unsafePath: return "A biblioteca recusou um link, caminho ou arquivo não regular. Os originais foram preservados."
        case .corrupt: return "A integridade da biblioteca ou da pasta de sincronização não confere. Nenhum catálogo existente foi substituído."
        case .destinationExists: return "O destino já existe. Escolha outro nome para preservar o arquivo."
        case .tooLarge: return "O limite desta biblioteca foi atingido: 256 MiB por PDF, 2.000 documentos e 20.000 versões."
        case .searchTooLarge: return "Reduza a consulta para até 100 documentos, 10.000 páginas e 16 MiB de texto extraído."
        case .syncTooLarge: return "A pasta atingiu o limite de 512 manifestos ou 64 MiB de metadados. Escolha uma nova pasta de sincronização para publicar o catálogo completo; a pasta anterior permanece intacta."
        case .missing: return "O documento ou a versão não está mais disponível no catálogo."
        case .busy: return "Outra operação está usando a biblioteca. Aguarde a conclusão e tente novamente."
        case .invalidPDF: return "A importação exige um PDF legível, com ao menos uma página quando desbloqueado."
        case .invalidMetadata: return "Use um título de até 200 caracteres, coleção de até 80 e no máximo 32 etiquetas de até 40 caracteres."
        case .noTextPermission: return "O documento não permite extrair texto com esta credencial."
        }
    }
}

/// All names beneath a store are generated from validated UUIDs or SHA-256. No
/// imported manifest supplies a filesystem path. Original PDF bytes stay intact.
enum LibraryFiles {
    static let maximumPDF = 256 * 1_024 * 1_024
    static let maximumManifest = 8 * 1_024 * 1_024
    static func hash(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
    static func validHash(_ value: String) -> Bool { value.count == 64 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) } }

    static func directory(_ url: URL, create: Bool) throws {
        guard url.isFileURL else { throw LibraryFailure.unsafePath }
        var info = stat()
        let result = url.path.withCString { lstat($0, &info) }
        if result == 0 {
            guard info.st_mode & S_IFMT == S_IFDIR else { throw LibraryFailure.unsafePath }
        } else if errno == ENOENT && create {
            // Creation starts at a user-selected or OS-provided parent; inspect
            // each missing component and reject links inside the managed tree.
            let parent = url.deletingLastPathComponent()
            guard parent.path != url.path else { throw LibraryFailure.unsafePath }
            try directory(parent, create: true)
            let created = mkdir(url.path, 0o700)
            if created != 0 && errno != EEXIST { throw POSIXError(.EIO) }
            try directory(url, create: false)
            if created == 0 { try synchronizeDirectory(parent) }
        } else { throw LibraryFailure.unsafePath }
    }

    static func read(_ url: URL, maximum: Int) throws -> Data {
        let fd = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard fd >= 0 else { throw LibraryFailure.unsafePath }
        defer { Darwin.close(fd) }
        var before = stat()
        guard fstat(fd, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_size >= 0, before.st_size <= maximum else { throw LibraryFailure.unsafePath }
        var bytes = Data(), buffer = [UInt8](repeating: 0, count: 128 * 1_024)
        while true {
            try Task.checkCancellation()
            let count = Darwin.read(fd, &buffer, buffer.count)
            if count < 0 { if errno == EINTR { continue }; throw POSIXError(.EIO) }
            if count == 0 { break }
            guard bytes.count <= maximum - count else { throw LibraryFailure.tooLarge }
            bytes.append(contentsOf: buffer.prefix(count))
        }
        var after = stat()
        guard fstat(fd, &after) == 0, before.st_size == after.st_size, bytes.count == before.st_size,
              before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else { throw LibraryFailure.corrupt }
        return bytes
    }

    /// Fully write and fsync a private staging file, then publish with link(2).
    /// Existing destinations, including symlinks, are never replaced.
    static func publish(_ bytes: Data, to url: URL) throws {
        let temp = url.deletingLastPathComponent().appendingPathComponent(".pending-" + UUID().uuidString)
        let fd = Darwin.open(temp.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, mode_t(0o600))
        guard fd >= 0 else { throw LibraryFailure.unsafePath }
        defer { Darwin.close(fd); unlink(temp.path) }
        try bytes.withUnsafeBytes { raw in
            var position = 0
            while position < raw.count {
                try Task.checkCancellation()
                let written = Darwin.write(fd, raw.baseAddress!.advanced(by: position), raw.count - position)
                if written < 0 { if errno == EINTR { continue }; throw POSIXError(.EIO) }
                position += written
            }
        }
        guard fsync(fd) == 0 else { throw POSIXError(.EIO) }
        try Task.checkCancellation()
        guard link(temp.path, url.path) == 0 else {
            if errno == EEXIST { throw LibraryFailure.destinationExists }
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
        // Persist the directory entry as well as the bytes. In particular the
        // current-catalog pointer must never outlive an unsynced object link.
        try synchronizeDirectory(url.deletingLastPathComponent())
    }

    static func synchronizeDirectory(_ url: URL) throws {
        let fd = Darwin.open(url.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { throw LibraryFailure.unsafePath }
        defer { Darwin.close(fd) }
        guard fsync(fd) == 0 else { throw POSIXError(.EIO) }
    }

    static func ensureObject(_ bytes: Data, hash: String, folder: URL) throws {
        guard validHash(hash), Self.hash(bytes) == hash else { throw LibraryFailure.corrupt }
        let url = folder.appendingPathComponent(hash + ".pdf")
        var metadata = stat()
        if lstat(url.path, &metadata) == 0 {
            guard Self.hash(try read(url, maximum: maximumPDF)) == hash else { throw LibraryFailure.corrupt }
            try synchronizeDirectory(folder)
        } else {
            do { try publish(bytes, to: url) }
            catch LibraryFailure.destinationExists {
                // Another Mac may publish this identical immutable object. A
                // racing different file is rejected instead of overwritten.
                guard Self.hash(try read(url, maximum: maximumPDF)) == hash else { throw LibraryFailure.corrupt }
                try synchronizeDirectory(folder)
            }
        }
    }

    static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(value)
        guard data.count <= maximumManifest else { throw LibraryFailure.tooLarge }
        return data
    }
    static func validateManifestBudget(count: Int, bytes: Int, addedBytes: Int) throws {
        guard count >= 0, bytes >= 0, addedBytes >= 0, count <= 512, bytes <= 64 * 1_024 * 1_024,
              (addedBytes == 0 || count < 512), addedBytes <= 64 * 1_024 * 1_024 - bytes else { throw LibraryFailure.syncTooLarge }
    }
    static func labels(title: String, collection: String, tags: [String]) throws -> LibraryLabels {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let collection = collection.trimmingCharacters(in: .whitespacesAndNewlines)
        let tags = Array(Set(tags.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty })).sorted()
        let strings = [title, collection] + tags
        guard !title.isEmpty, title.count <= 200, collection.count <= 80, tags.count <= 32,
              tags.allSatisfy({ $0.count <= 40 }), strings.allSatisfy({ $0.rangeOfCharacter(from: .controlCharacters) == nil }) else { throw LibraryFailure.invalidMetadata }
        return LibraryLabels(title: title, collection: collection, tags: tags)
    }
    static func validate(_ catalog: LibraryCatalog) throws {
        guard catalog.version == 1, catalog.documents.count <= 2_000,
              Set(catalog.documents.map(\.id)).count == catalog.documents.count,
              catalog.documents.reduce(0, { $0 + $1.revisions.count }) <= 20_000 else { throw LibraryFailure.corrupt }
        var objects: [String: String] = [:]
        for document in catalog.documents {
            guard !document.revisions.isEmpty, document.revisions.count <= 2_000,
                  Set(document.revisions.map(\.id)).count == document.revisions.count,
                  document.revisions.contains(where: { $0.id == document.preferred }) else { throw LibraryFailure.corrupt }
            let byID = Dictionary(uniqueKeysWithValues: document.revisions.map { ($0.id, $0) })
            for revision in document.revisions {
                guard validHash(revision.fingerprint), (1...maximumPDF).contains(revision.byteCount),
                      (0...100_000).contains(revision.pages), revision.pages > 0 || revision.encrypted,
                      revision.note.count <= 500, revision.created.timeIntervalSince1970.isFinite,
                      (0...32_503_680_000).contains(revision.created.timeIntervalSince1970),
                      revision.parents.count <= 64, Set(revision.parents).count == revision.parents.count,
                      revision.parents.allSatisfy({ $0 != revision.id && byID[$0] != nil }),
                      try labels(title: revision.labels.title, collection: revision.labels.collection, tags: revision.labels.tags) == revision.labels else { throw LibraryFailure.corrupt }
                let metadata = "\(revision.byteCount):\(revision.pages):\(revision.encrypted)"
                if let previous = objects[revision.fingerprint], previous != metadata { throw LibraryFailure.corrupt }
                objects[revision.fingerprint] = metadata
            }
            // Iterative topological walk rejects cycles without recursive stack
            // growth on a deliberately hostile synchronization manifest.
            var resolved = Set<UUID>(), remaining = document.revisions
            while !remaining.isEmpty {
                let ready = remaining.filter { Set($0.parents).isSubset(of: resolved) }
                guard !ready.isEmpty else { throw LibraryFailure.corrupt }
                resolved.formUnion(ready.map(\.id)); remaining.removeAll { resolved.contains($0.id) }
            }
        }
    }
}

actor DocumentLibraryStore {
    static var defaultDirectory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PDF/Library", isDirectory: true)
    }
    let directory: URL
    private struct CachedText { let page: Int; let part: Int; let text: String }
    private var textCache: [String: [CachedText]] = [:]
    private var cachedCharacters = 0
    init(directory: URL = DocumentLibraryStore.defaultDirectory) { self.directory = directory.standardizedFileURL }
    private var objects: URL { directory.appendingPathComponent("objects", isDirectory: true) }
    private var catalogs: URL { directory.appendingPathComponent("catalogs", isDirectory: true) }
    private var currentFile: URL { directory.appendingPathComponent("current.json") }
    private struct Pointer: Codable { let version: Int; let hash: String }

    private func locked<T>(_ action: () throws -> T) throws -> T {
        try LibraryFiles.directory(directory, create: true)
        try LibraryFiles.directory(objects, create: true); try LibraryFiles.directory(catalogs, create: true)
        for managed in [directory, objects, catalogs] {
            let descriptor = Darwin.open(managed.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard descriptor >= 0 else { throw LibraryFailure.unsafePath }
            defer { Darwin.close(descriptor) }
            var info = stat()
            guard fstat(descriptor, &info) == 0, info.st_uid == geteuid(), fchmod(descriptor, 0o700) == 0 else { throw LibraryFailure.unsafePath }
        }
        let fd = Darwin.open(directory.appendingPathComponent(".lock").path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK, mode_t(0o600))
        guard fd >= 0 else { throw LibraryFailure.unsafePath }
        defer { Darwin.close(fd) }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG else { throw LibraryFailure.unsafePath }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { throw LibraryFailure.busy }
        defer { flock(fd, LOCK_UN) }
        return try action()
    }
    private func readCatalog() throws -> LibraryCatalog {
        var info = stat()
        if lstat(currentFile.path, &info) != 0 {
            guard errno == ENOENT else { throw LibraryFailure.unsafePath }
            let empty = LibraryCatalog.empty(); try commit(empty); return empty
        }
        let pointer = try JSONDecoder().decode(Pointer.self, from: LibraryFiles.read(currentFile, maximum: 1_024))
        guard pointer.version == 1, LibraryFiles.validHash(pointer.hash) else { throw LibraryFailure.corrupt }
        let data = try LibraryFiles.read(catalogs.appendingPathComponent(pointer.hash + ".json"), maximum: LibraryFiles.maximumManifest)
        guard LibraryFiles.hash(data) == pointer.hash else { throw LibraryFailure.corrupt }
        let catalog = try JSONDecoder().decode(LibraryCatalog.self, from: data)
        try LibraryFiles.validate(catalog); return catalog
    }
    private func commit(_ catalog: LibraryCatalog) throws {
        try LibraryFiles.validate(catalog)
        let data = try LibraryFiles.encode(catalog), hash = LibraryFiles.hash(data)
        let target = catalogs.appendingPathComponent(hash + ".json")
        if FileManager.default.fileExists(atPath: target.path) {
            guard try LibraryFiles.read(target, maximum: LibraryFiles.maximumManifest) == data else { throw LibraryFailure.corrupt }
            try LibraryFiles.synchronizeDirectory(catalogs)
        } else { try LibraryFiles.publish(data, to: target) }
        let temporary = directory.appendingPathComponent(".pointer-" + UUID().uuidString)
        defer { unlink(temporary.path) }
        try LibraryFiles.publish(LibraryFiles.encode(Pointer(version: 1, hash: hash)), to: temporary)
        try Task.checkCancellation()
        guard rename(temporary.path, currentFile.path) == 0 else { throw POSIXError(.EIO) }
        try LibraryFiles.synchronizeDirectory(directory)
    }
    func list() throws -> LibraryCatalog { try locked { try readCatalog() } }

    private func pdf(_ data: Data) throws -> (pages: Int, encrypted: Bool) {
        guard data.count <= LibraryFiles.maximumPDF, data.starts(with: Data("%PDF-".utf8)), let pdf = PDFDocument(data: data),
              pdf.isLocked || pdf.pageCount > 0, pdf.pageCount <= 100_000 else { throw LibraryFailure.invalidPDF }
        return (pdf.isLocked ? 0 : pdf.pageCount, pdf.isEncrypted)
    }
    func importFiles(_ urls: [URL], collection: String = "", tags: [String] = []) throws -> LibraryImportReport {
        guard !urls.isEmpty, urls.count <= 200 else { throw LibraryFailure.tooLarge }
        return try locked {
            var catalog = try readCatalog(), duplicate = 0, imported = 0
            var hashes = Set(catalog.documents.flatMap { $0.revisions.map(\.fingerprint) })
            for url in urls {
                try Task.checkCancellation()
                let scope = url.startAccessingSecurityScopedResource(); defer { if scope { url.stopAccessingSecurityScopedResource() } }
                let data = try LibraryFiles.read(url, maximum: LibraryFiles.maximumPDF), hash = LibraryFiles.hash(data)
                if !hashes.insert(hash).inserted { duplicate += 1; continue }
                let info = try pdf(data)
                let labels = try LibraryFiles.labels(title: url.deletingPathExtension().lastPathComponent, collection: collection, tags: tags)
                let revision = LibraryRevision(id: UUID(), parents: [], fingerprint: hash, byteCount: data.count, pages: info.pages,
                                               encrypted: info.encrypted, created: Date(), note: "Importação explícita", labels: labels)
                try LibraryFiles.ensureObject(data, hash: hash, folder: objects)
                catalog.documents.append(LibraryDocument(id: UUID(), preferred: revision.id, revisions: [revision])); imported += 1
            }
            try commit(catalog)
            return LibraryImportReport(imported: imported, duplicate: duplicate, catalog: catalog)
        }
    }
    private func locate(_ id: UUID, revision: UUID?, in catalog: LibraryCatalog) throws -> (Int, LibraryRevision) {
        guard let index = catalog.documents.firstIndex(where: { $0.id == id }),
              let item = catalog.documents[index].revisions.first(where: { $0.id == (revision ?? catalog.documents[index].preferred) }) else { throw LibraryFailure.missing }
        return (index, item)
    }
    private func data(_ revision: LibraryRevision) throws -> Data {
        let bytes = try LibraryFiles.read(objects.appendingPathComponent(revision.fingerprint + ".pdf"), maximum: LibraryFiles.maximumPDF)
        guard bytes.count == revision.byteCount, LibraryFiles.hash(bytes) == revision.fingerprint else { throw LibraryFailure.corrupt }
        return bytes
    }
    func verifiedURL(document: UUID, revision: UUID? = nil) throws -> URL {
        try locked {
            let (_, item) = try locate(document, revision: revision, in: readCatalog()); _ = try data(item)
            return objects.appendingPathComponent(item.fingerprint + ".pdf")
        }
    }
    func export(document: UUID, revision: UUID? = nil, to url: URL) throws {
        try locked {
            let (_, item) = try locate(document, revision: revision, in: readCatalog())
            let bytes = try data(item); try LibraryFiles.publish(bytes, to: url)
        }
    }
    func addVersion(document: UUID, source: URL) throws -> LibraryCatalog {
        try locked {
            var catalog = try readCatalog(); let (index, current) = try locate(document, revision: nil, in: catalog)
            let scoped = source.startAccessingSecurityScopedResource(); defer { if scoped { source.stopAccessingSecurityScopedResource() } }
            let bytes = try LibraryFiles.read(source, maximum: LibraryFiles.maximumPDF), info = try pdf(bytes), hash = LibraryFiles.hash(bytes)
            try LibraryFiles.ensureObject(bytes, hash: hash, folder: objects)
            let revision = LibraryRevision(id: UUID(), parents: [current.id], fingerprint: hash, byteCount: bytes.count, pages: info.pages,
                                           encrypted: info.encrypted, created: Date(), note: "Nova versão importada", labels: current.labels)
            catalog.documents[index].revisions.append(revision); catalog.documents[index].preferred = revision.id
            try commit(catalog); return catalog
        }
    }
    func updateLabels(document: UUID, title: String, collection: String, tags: [String]) throws -> LibraryCatalog {
        let labels = try LibraryFiles.labels(title: title, collection: collection, tags: tags)
        return try locked {
            var catalog = try readCatalog(); let (index, current) = try locate(document, revision: nil, in: catalog)
            if try LibraryFiles.encode(current.labels) == LibraryFiles.encode(labels) { return catalog }
            let revision = LibraryRevision(id: UUID(), parents: [current.id], fingerprint: current.fingerprint, byteCount: current.byteCount,
                                           pages: current.pages, encrypted: current.encrypted, created: Date(), note: "Título, coleção ou etiquetas atualizados", labels: labels)
            catalog.documents[index].revisions.append(revision); catalog.documents[index].preferred = revision.id
            try commit(catalog); return catalog
        }
    }
    /// Restoration adds a new immutable revision; the selected historical bytes
    /// and every previous head remain present. It never writes to a source URL.
    func restore(document: UUID, revision: UUID) throws -> LibraryCatalog {
        try locked {
            var catalog = try readCatalog(); let (index, old) = try locate(document, revision: revision, in: catalog)
            let current = catalog.documents[index].current; _ = try data(old)
            let restored = LibraryRevision(id: UUID(), parents: [current.id], fingerprint: old.fingerprint, byteCount: old.byteCount,
                                            pages: old.pages, encrypted: old.encrypted, created: Date(), note: "Restaurada versão de \(old.created.formatted(date: .numeric, time: .shortened))", labels: old.labels)
            catalog.documents[index].revisions.append(restored); catalog.documents[index].preferred = restored.id
            try commit(catalog); return catalog
        }
    }
    /// Conflict resolution is an explicit merge revision, never last-writer-wins.
    /// Every branch remains an ancestor and its PDF remains independently stored.
    func resolve(document: UUID, revision: UUID) throws -> LibraryCatalog {
        try locked {
            var catalog = try readCatalog(); let (index, chosen) = try locate(document, revision: revision, in: catalog)
            let heads = catalog.documents[index].heads
            guard heads.count > 1, heads.count <= 64, heads.contains(where: { $0.id == chosen.id }) else { throw LibraryFailure.missing }
            _ = try data(chosen)
            let merged = LibraryRevision(id: UUID(), parents: heads.map(\.id), fingerprint: chosen.fingerprint, byteCount: chosen.byteCount,
                                         pages: chosen.pages, encrypted: chosen.encrypted, created: Date(), note: "Conflito resolvido por escolha explícita desta cópia", labels: chosen.labels)
            catalog.documents[index].revisions.append(merged); catalog.documents[index].preferred = merged.id
            try commit(catalog); return catalog
        }
    }

    /// Explicit exchange only. Each complete catalog is an immutable, hashed
    /// manifest. A provider still uploading an object is reported as incomplete;
    /// the local catalog is left unchanged and a later retry can succeed.
    func synchronize(with chosenFolder: URL) throws -> LibrarySyncReport {
        let scope = chosenFolder.startAccessingSecurityScopedResource(); defer { if scope { chosenFolder.stopAccessingSecurityScopedResource() } }
        let root = chosenFolder.standardizedFileURL.appendingPathComponent("PDF Library Exchange", isDirectory: true)
        let local = directory.resolvingSymlinksInPath().path, external = root.resolvingSymlinksInPath().path
        guard !external.hasPrefix(local + "/"), !local.hasPrefix(external + "/"), external != local else { throw LibraryFailure.unsafePath }
        return try locked {
            try LibraryFiles.directory(chosenFolder, create: false); try LibraryFiles.directory(root, create: true)
            let remoteObjects = root.appendingPathComponent("objects"), manifests = root.appendingPathComponent("manifests"), conflicts = root.appendingPathComponent("conflicts")
            for folder in [remoteObjects, manifests, conflicts] { try LibraryFiles.directory(folder, create: true) }
            var catalog = try readCatalog(); let previous = catalog.documents.reduce(0) { $0 + $1.revisions.count }
            let paths = try FileManager.default.contentsOfDirectory(at: manifests, includingPropertiesForKeys: nil)
                .filter { !$0.lastPathComponent.hasPrefix(".") }
            guard paths.count <= 512 else { throw LibraryFailure.syncTooLarge }
            var totalManifestBytes = 0
            for path in paths.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                try Task.checkCancellation()
                let name = path.deletingPathExtension().lastPathComponent
                guard path.pathExtension == "json", LibraryFiles.validHash(name) else { throw LibraryFailure.corrupt }
                let bytes = try LibraryFiles.read(path, maximum: LibraryFiles.maximumManifest)
                totalManifestBytes += bytes.count
                guard totalManifestBytes <= 64 * 1_024 * 1_024 else { throw LibraryFailure.syncTooLarge }
                guard LibraryFiles.hash(bytes) == name else { throw LibraryFailure.corrupt }
                let incoming = try JSONDecoder().decode(LibraryCatalog.self, from: bytes); try LibraryFiles.validate(incoming)
                for document in incoming.documents {
                    if let index = catalog.documents.firstIndex(where: { $0.id == document.id }) {
                        for revision in document.revisions {
                            if let existing = catalog.documents[index].revisions.first(where: { $0.id == revision.id }) {
                                guard try LibraryFiles.encode(existing) == LibraryFiles.encode(revision) else { throw LibraryFailure.corrupt }
                            } else { catalog.documents[index].revisions.append(revision) }
                        }
                    } else { catalog.documents.append(document) }
                }
                try LibraryFiles.validate(catalog)
            }
            for index in catalog.documents.indices {
                if catalog.documents[index].heads.count == 1 { catalog.documents[index].preferred = catalog.documents[index].heads[0].id }
            }
            let encoded = try LibraryFiles.encode(catalog), manifest = manifests.appendingPathComponent(LibraryFiles.hash(encoded) + ".json")
            let alreadyPublished = paths.contains { $0.lastPathComponent == manifest.lastPathComponent }
            try LibraryFiles.validateManifestBudget(count: paths.count, bytes: totalManifestBytes,
                                                     addedBytes: alreadyPublished ? 0 : encoded.count)
            // Verify every referenced byte sequence before publishing either
            // manifest or local pointer. Object copies are safe orphaned data.
            var verified = Set<String>()
            for document in catalog.documents {
                for revision in document.revisions where verified.insert(revision.fingerprint).inserted {
                    try Task.checkCancellation()
                    let localPath = objects.appendingPathComponent(revision.fingerprint + ".pdf")
                    let remotePath = remoteObjects.appendingPathComponent(revision.fingerprint + ".pdf")
                    let bytes: Data
                    if FileManager.default.fileExists(atPath: localPath.path) { bytes = try LibraryFiles.read(localPath, maximum: LibraryFiles.maximumPDF) }
                    else { bytes = try LibraryFiles.read(remotePath, maximum: LibraryFiles.maximumPDF) }
                    guard bytes.count == revision.byteCount, LibraryFiles.hash(bytes) == revision.fingerprint else { throw LibraryFailure.corrupt }
                    let info = try pdf(bytes)
                    guard info.encrypted == revision.encrypted, info.pages == revision.pages else { throw LibraryFailure.corrupt }
                    try LibraryFiles.ensureObject(bytes, hash: revision.fingerprint, folder: objects)
                    try LibraryFiles.ensureObject(bytes, hash: revision.fingerprint, folder: remoteObjects)
                }
                if document.heads.count > 1 {
                    let folder = conflicts.appendingPathComponent(document.id.uuidString)
                    try LibraryFiles.directory(folder, create: true)
                    for head in document.heads {
                        let destination = folder.appendingPathComponent(head.id.uuidString + ".pdf"), bytes = try data(head)
                        if FileManager.default.fileExists(atPath: destination.path) {
                            guard try LibraryFiles.read(destination, maximum: LibraryFiles.maximumPDF) == bytes else { throw LibraryFailure.corrupt }
                        } else { try LibraryFiles.publish(bytes, to: destination) }
                    }
                }
            }
            let configurationsReceived = try synchronizeConfigurations(remoteRoot: root)
            if FileManager.default.fileExists(atPath: manifest.path) {
                guard try LibraryFiles.read(manifest, maximum: LibraryFiles.maximumManifest) == encoded else { throw LibraryFailure.corrupt }
            } else { try LibraryFiles.publish(encoded, to: manifest) }
            try commit(catalog)
            return LibrarySyncReport(received: catalog.documents.reduce(0) { $0 + $1.revisions.count } - previous,
                                     conflicts: catalog.documents.filter { $0.heads.count > 1 }.count,
                                     configurationsReceived: configurationsReceived, catalog: catalog)
        }
    }

    func excerpts(documentIDs: Set<UUID>, passwords: [UUID: String] = [:], cancellation: NativeCancellation) throws -> LibrarySearchSource {
        try locked {
            let catalog = try readCatalog()
            let selected = catalog.documents.filter { documentIDs.contains($0.id) }
            guard selected.count <= 100 else { throw LibraryFailure.searchTooLarge }
            var excerpts: [LibraryExcerpt] = [], skipped: [String] = [], totalCharacters = 0, visitedPages = 0
            for document in selected.sorted(by: { $0.id.uuidString < $1.id.uuidString }) {
                try Task.checkCancellation(); try cancellation.check()
                let current = document.current, bytes = try data(current)
                if current.encrypted && current.pages == 0 && passwords[document.id] == nil { skipped.append(current.labels.title + ": protegido; informe a senha para incluir."); continue }
                if !current.encrypted, let cached = textCache[current.fingerprint] {
                    visitedPages += current.pages
                    totalCharacters += cached.reduce(0) { $0 + $1.text.utf8.count }
                    guard visitedPages <= 10_000, totalCharacters <= 16 * 1_024 * 1_024 else { throw LibraryFailure.searchTooLarge }
                    excerpts += cached.map { LibraryExcerpt(documentID: document.id, revisionID: current.id, fingerprint: current.fingerprint,
                                                           title: current.labels.title, page: $0.page, part: $0.part, text: $0.text) }
                    if cached.isEmpty { skipped.append(current.labels.title + ": sem camada de texto; execute OCR para pesquisar.") }
                    continue
                }
                let pdf: PDFDocument
                if current.encrypted { pdf = try NativePDFSerialization.open(data: bytes, password: passwords[document.id], cancellation: cancellation) }
                else { guard let opened = PDFDocument(data: bytes) else { throw LibraryFailure.invalidPDF }; pdf = opened }
                guard pdf.allowsCopying else { skipped.append(current.labels.title + ": extração não permitida."); continue }
                var found = false, cached: [CachedText] = []
                for index in 0..<pdf.pageCount {
                    try Task.checkCancellation(); try cancellation.check(); visitedPages += 1
                    guard visitedPages <= 10_000 else { throw LibraryFailure.searchTooLarge }
                    let text = pdf.page(at: index)?.string ?? ""
                    totalCharacters += text.utf8.count
                    guard totalCharacters <= 16 * 1_024 * 1_024 else { throw LibraryFailure.searchTooLarge }
                    for (part, chunk) in IntelligenceText.chunks(text, limit: 900).enumerated() where !chunk.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        excerpts.append(LibraryExcerpt(documentID: document.id, revisionID: current.id, fingerprint: current.fingerprint,
                                                       title: current.labels.title, page: index + 1, part: part, text: chunk)); found = true
                        if !current.encrypted { cached.append(CachedText(page: index + 1, part: part, text: chunk)) }
                    }
                }
                if !current.encrypted {
                    let bytes = cached.reduce(0) { $0 + $1.text.utf8.count }
                    if cachedCharacters + bytes > 16 * 1_024 * 1_024 { textCache = [:]; cachedCharacters = 0 }
                    textCache[current.fingerprint] = cached; cachedCharacters += bytes
                }
                if !found { skipped.append(current.labels.title + ": sem camada de texto; execute OCR para pesquisar.") }
            }
            return LibrarySearchSource(excerpts: excerpts, skipped: skipped)
        }
    }
    func clearSearchCache() { textCache = [:]; cachedCharacters = 0 }
}

extension DocumentLibraryStore {
    private var configurationFolder: URL { directory.appendingPathComponent("configurations", isDirectory: true) }

    func publishConfiguration(kind: String, payload: Data) throws -> LibraryConfigurationSnapshot {
        try LibraryConfigurationFiles.validatePayload(kind: kind, payload: payload)
        return try locked {
            try LibraryFiles.directory(configurationFolder, create: true)
            let catalog = try readCatalog(), hash = LibraryFiles.hash(payload)
            let files = try LibraryConfigurationFiles.files(configurationFolder)
            var total = 0, existing: LibraryConfigurationSnapshot?
            for file in files {
                let (metadata, _, bytes) = try LibraryConfigurationFiles.read(file); total += bytes.count
                guard total <= LibraryConfigurationFiles.maximumTotal else { throw LibraryFailure.tooLarge }
                if metadata.kind == kind && metadata.payloadHash == hash { existing = metadata }
            }
            if let existing { return existing }
            let bytes = try LibraryConfigurationFiles.encode(kind: kind, payload: payload, device: catalog.device)
            guard files.count < 128, total <= LibraryConfigurationFiles.maximumTotal - bytes.count else {
                throw SemanticEvidence.failure("O histórico de configurações atingiu 128 snapshots ou 128 MiB. Exporte uma cópia antes de reorganizar sua biblioteca.")
            }
            let id = LibraryFiles.hash(bytes), (metadata, _) = try LibraryConfigurationFiles.decode(bytes, expectedHash: id)
            try LibraryFiles.publish(bytes, to: configurationFolder.appendingPathComponent(id + ".json"))
            return metadata
        }
    }

    func configurationSnapshots() throws -> [LibraryConfigurationSnapshot] {
        try locked {
            try LibraryFiles.directory(configurationFolder, create: true)
            var total = 0, values: [LibraryConfigurationSnapshot] = []
            for file in try LibraryConfigurationFiles.files(configurationFolder) {
                let (metadata, _, bytes) = try LibraryConfigurationFiles.read(file); total += bytes.count
                guard total <= LibraryConfigurationFiles.maximumTotal else { throw LibraryFailure.tooLarge }
                values.append(metadata)
            }
            return values.sorted { $0.created == $1.created ? $0.id < $1.id : $0.created > $1.created }
        }
    }

    func loadConfiguration(_ snapshot: LibraryConfigurationSnapshot) throws -> Data {
        try locked {
            guard LibraryFiles.validHash(snapshot.id) else { throw LibraryFailure.corrupt }
            try LibraryFiles.directory(configurationFolder, create: false)
            let (actual, payload, _) = try LibraryConfigurationFiles.read(configurationFolder.appendingPathComponent(snapshot.id + ".json"))
            guard actual == snapshot else { throw LibraryFailure.corrupt }
            return payload
        }
    }

    /// Receiving settings never changes UserDefaults, profiles, reading state,
    /// output folders or credentials. The settings UI must explicitly validate
    /// and apply one chosen snapshot after the transfer has completed.
    private func synchronizeConfigurations(remoteRoot: URL) throws -> Int {
        let remote = remoteRoot.appendingPathComponent("configurations", isDirectory: true)
        try LibraryFiles.directory(configurationFolder, create: true); try LibraryFiles.directory(remote, create: true)
        let localFiles = try LibraryConfigurationFiles.files(configurationFolder), remoteFiles = try LibraryConfigurationFiles.files(remote)
        let localNames = Set(localFiles.map(\.lastPathComponent)), remoteNames = Set(remoteFiles.map(\.lastPathComponent))
        let names = localNames.union(remoteNames).sorted()
        guard names.count <= 128 else { throw LibraryFailure.tooLarge }
        // Preflight both sides before publishing the first new snapshot. Keep
        // only byte counts here; large JSON payloads are read one at a time.
        var total = 0
        for name in names {
            try Task.checkCancellation()
            let localPath = configurationFolder.appendingPathComponent(name), remotePath = remote.appendingPathComponent(name)
            let (_, _, bytes) = try LibraryConfigurationFiles.read(localNames.contains(name) ? localPath : remotePath)
            total += bytes.count
            guard total <= LibraryConfigurationFiles.maximumTotal else { throw LibraryFailure.tooLarge }
            if localNames.contains(name) && remoteNames.contains(name) {
                guard try LibraryConfigurationFiles.read(remotePath).2 == bytes else { throw LibraryFailure.corrupt }
            }
        }
        var received = 0
        for name in names {
            try Task.checkCancellation()
            let localPath = configurationFolder.appendingPathComponent(name), remotePath = remote.appendingPathComponent(name)
            let (_, _, bytes) = try LibraryConfigurationFiles.read(localNames.contains(name) ? localPath : remotePath)
            if !localNames.contains(name) { try LibraryFiles.publish(bytes, to: localPath); received += 1 }
            if !remoteNames.contains(name) { try LibraryFiles.publish(bytes, to: remotePath) }
        }
        return received
    }
}
