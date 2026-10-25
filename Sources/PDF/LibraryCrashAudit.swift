import AppKit
import CoreGraphics
import PDFKit
import Darwin

/// Interrupt real library writes, including a partially written object, in a
/// disposable child. A surviving pointer must always select a complete catalog
/// and every referenced object must still match its original SHA-256.
@MainActor enum LibraryCrashAudit {
    static let argument = "--library-crash-worker"
    private static let prefix = "PDF-library-crash-"
    private enum Boundary: String, Codable, CaseIterable, Sendable {
        case objectPartial, objectPublished, catalogPublished, pointerStaged, pointerReplaced
        case smartPointerStaged, smartPointerReplaced
        var smart: Bool { self == .smartPointerStaged || self == .smartPointerReplaced }
        var committed: Bool { self == .pointerReplaced || self == .smartPointerReplaced }
        func matches(_ phase: String, _ target: URL) -> Bool {
            switch self {
            case .objectPartial: return phase == "partial" && target.deletingLastPathComponent().lastPathComponent == "objects"
            case .objectPublished: return phase == "published" && target.deletingLastPathComponent().lastPathComponent == "objects"
            case .catalogPublished: return phase == "published" && target.deletingLastPathComponent().lastPathComponent == "catalogs"
            case .pointerStaged: return phase == "pointer-staged" && target.lastPathComponent == "current.json"
            case .pointerReplaced: return phase == "pointer-replaced" && target.lastPathComponent == "current.json"
            case .smartPointerStaged: return phase == "pointer-staged" && target.lastPathComponent == "smart-folders.json"
            case .smartPointerReplaced: return phase == "pointer-replaced" && target.lastPathComponent == "smart-folders.json"
            }
        }
    }
    private struct Request: Codable, Sendable {
        let version: Int
        let id: UUID
        let boundary: Boundary
        let sourceSHA256: String
    }
    private struct Receipt: Codable {
        let id: UUID
        let boundary: Boundary
        let pid: Int32
        let sourceSHA256: String
    }
    nonisolated private static func failure(_ text: String) -> NSError {
        NSError(domain: "PDF.LibraryCrashAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
    private static func require(_ condition: @autoclosure () throws -> Bool, _ text: String) throws {
        if try !condition() { throw failure(text) }
    }
    static func handleCommandLineIfNeeded() async -> Bool {
        let arguments = CommandLine.arguments
        guard arguments.contains(argument) else { return false }
        do {
            guard arguments.count == 3, arguments[1] == argument else { throw failure("Argumentos inválidos.") }
            let root = URL(fileURLWithPath: arguments[2], isDirectory: true).standardizedFileURL
            var metadata = stat()
            guard lstat(root.path, &metadata) == 0, metadata.st_mode & S_IFMT == S_IFDIR,
                  metadata.st_uid == geteuid(), metadata.st_mode & 0o077 == 0 else { throw failure("Diretório privado inválido.") }
            let request = try JSONDecoder().decode(Request.self, from: LibraryFiles.read(root.appendingPathComponent("request.json"), maximum: 8192))
            guard request.version == 1, root.lastPathComponent == prefix + request.id.uuidString else { throw failure("Identidade inválida.") }
            let source = root.appendingPathComponent("changed.pdf")
            guard LibraryFiles.hash(try LibraryFiles.read(source, maximum: LibraryFiles.maximumPDF)) == request.sourceSHA256 else {
                throw failure("A origem da auditoria foi alterada.")
            }
            // Bounds a faulty test child even if its parent disappears. This is
            // not a timeout/retry change in the reader or library product path.
            alarm(20)
            let store = DocumentLibraryStore(directory: root.appendingPathComponent("Library"))
            try await LibraryWriteAudit.$observer.withValue({ phase, target in
                guard request.boundary.matches(phase, target) else { return }
                let receipt = Receipt(id: request.id, boundary: request.boundary, pid: getpid(), sourceSHA256: request.sourceSHA256)
                // Use the independent native publisher: calling LibraryFiles
                // here would recursively invoke the checkpoint observer.
                try NativeOutput.write(try JSONEncoder().encode(receipt), to: root.appendingPathComponent("ready.json"))
                while true { usleep(25_000) }
            }) {
                if request.boundary.smart {
                    _ = try await store.saveSmartFolder(name: "Recuperação de regras", filter: LibrarySmartFilter())
                } else {
                    _ = try await store.importFiles([source], collection: "Checkpoint interrompido")
                }
            }
            throw failure("O checkpoint solicitado não foi atingido.")
        } catch {
            FileHandle.standardError.write(Data("Library crash worker failed before its verified boundary.\n".utf8))
            exit(2)
        }
    }
    static func run() async throws {
        let unchanged = try fixture(image: false), changed = try fixture(image: true)
        try require(changed.count > 128 * 1024, "A fixture não exercita gravação parcial real.")
        for boundary in Boundary.allCases {
            let id = UUID(), manager = FileManager.default
            let root = manager.temporaryDirectory.appendingPathComponent(prefix + id.uuidString, isDirectory: true)
            try manager.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            defer { try? manager.removeItem(at: root) }
            let source = root.appendingPathComponent("original.pdf"), next = root.appendingPathComponent("changed.pdf")
            try NativeOutput.write(unchanged, to: source); try NativeOutput.write(changed, to: next)
            let store = DocumentLibraryStore(directory: root.appendingPathComponent("Library"))
            let initial = try await store.importFiles([source])
            let initialDocument = initial.catalog.documents[0]
            let request = Request(version: 1, id: id, boundary: boundary, sourceSHA256: LibraryFiles.hash(changed))
            try NativeOutput.write(try JSONEncoder().encode(request), to: root.appendingPathComponent("request.json"))
            try await interrupt(root: root, request: request)

            let fresh = DocumentLibraryStore(directory: root.appendingPathComponent("Library"))
            let recovered = try await fresh.list()
            let expectedCount = !boundary.smart && boundary.committed ? 2 : 1
            try require(recovered.documents.count == expectedCount, "O catálogo recuperado contém uma publicação incompleta: \(boundary.rawValue).")
            let restored = try await fresh.verifiedBytes(document: initialDocument.id)
            try require(restored.data == unchanged && restored.fingerprint == LibraryFiles.hash(unchanged), "O documento anterior foi alterado durante o crash.")
            for item in recovered.documents {
                let verified = try await fresh.verifiedBytes(document: item.id)
                try require(verified.data == (item.id == initialDocument.id ? unchanged : changed), "Um objeto publicado ficou truncado ou com bytes diferentes.")
            }
            let rules = try await fresh.smartFolders()
            try require(rules.count == (boundary == .smartPointerReplaced ? 1 : 0), "As pastas inteligentes perderam a atomicidade.")
            try require(try LibraryFiles.read(source, maximum: LibraryFiles.maximumPDF) == unchanged &&
                        LibraryFiles.read(next, maximum: LibraryFiles.maximumPDF) == changed, "A interrupção modificou arquivos de origem.")
            // A fresh successful operation must still be possible after lock
            // loss. Unreferenced immutable objects do not replace the catalog.
            _ = try await fresh.updateLabels(document: initialDocument.id, title: "Recuperado", collection: "", tags: [])
            let after = try await fresh.list()
            try require(after.documents.first(where: { $0.id == initialDocument.id })?.current.labels.title == "Recuperado", "A biblioteca não voltou a aceitar alterações.")
            print("[Library crash] \(boundary.rawValue): real SIGKILL, complete catalog and original bytes PASS")
        }
    }
    private static func interrupt(root: URL, request: Request) async throws {
        guard let executable = Bundle.main.executableURL else { throw failure("Executável ausente.") }
        let config = Process()
        config.executableURL = executable; config.arguments = [argument, root.path]
        config.standardInput = FileHandle.nullDevice; config.standardOutput = FileHandle.nullDevice; config.standardError = FileHandle.nullDevice
        let lease = try BundleRuntimeLease.configureChild(config)
        defer { try? lease?.close() }
        let child = try OwnedChildProcess(configuration: config)
        defer { child.cancel(grace: 0); _ = try? child.waitUntilExit() }
        let deadline = ProcessInfo.processInfo.systemUptime + 15
        let ready = root.appendingPathComponent("ready.json")
        while !FileManager.default.fileExists(atPath: ready.path) {
            try Task.checkCancellation()
            guard try child.isRunning(), ProcessInfo.processInfo.systemUptime < deadline else {
                throw failure("O processo não atingiu o checkpoint \(request.boundary.rawValue) no prazo.")
            }
            try await Task.sleep(for: .milliseconds(25))
        }
        let receipt = try JSONDecoder().decode(Receipt.self, from: LibraryFiles.read(ready, maximum: 8192))
        try require(receipt.id == request.id && receipt.pid == child.processIdentifier && receipt.boundary == request.boundary &&
                    receipt.sourceSHA256 == request.sourceSHA256, "O recibo não pertence ao filho lançado.")
        child.cancel(grace: 0, signal: SIGKILL)
        let result = try await Task.detached { try child.waitUntilExit() }.value
        try require(result.signalled && result.status == SIGKILL, "O teste não executou encerramento real por SIGKILL.")
    }
    private static func fixture(image: Bool) throws -> Data {
        let bytes = NSMutableData()
        guard let consumer = CGDataConsumer(data: bytes as CFMutableData) else { throw failure("Consumer indisponível.") }
        var bounds = CGRect(x: 0, y: 0, width: 500, height: 650)
        guard let context = CGContext(consumer: consumer, mediaBox: &bounds, nil) else { throw failure("Contexto PDF indisponível.") }
        context.beginPDFPage(nil)
        if image {
            var state: UInt32 = 0x1F305A89
            var pixels = [UInt8](repeating: 0, count: 256 * 256 * 3)
            for index in pixels.indices {
                state = state &* 1_664_525 &+ 1_013_904_223
                pixels[index] = UInt8(truncatingIfNeeded: state >> 16)
            }
            guard let provider = CGDataProvider(data: Data(pixels) as CFData),
                  let raster = CGImage(width: 256, height: 256, bitsPerComponent: 8, bitsPerPixel: 24,
                    bytesPerRow: 256 * 3, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: 0),
                    provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent) else { throw failure("Imagem de auditoria indisponível.") }
            context.draw(raster, in: CGRect(x: 30, y: 40, width: 400, height: 400))
        }
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        ((image ? "Versão seguinte — recuperação" : "Original preservado — ação") as NSString).draw(at: CGPoint(x: 30, y: 560),
            withAttributes: [.font: NSFont.systemFont(ofSize: 16), .foregroundColor: NSColor.black])
        NSGraphicsContext.restoreGraphicsState(); context.endPDFPage(); context.closePDF()
        guard PDFDocument(data: bytes as Data)?.pageCount == 1 else { throw failure("Fixture PDF inválida.") }
        return bytes as Data
    }
}
