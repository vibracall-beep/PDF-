import Foundation
import AppKit
import PDFKit
import CryptoKit
import Darwin

/// The publication boundary for native PDF writers. PDFKit can emit malformed
/// stream lengths while keeping a readable document. Never publish those raw
/// bytes: independently check them, repair only recoverable structural warnings,
/// then check the resulting structure and the original document's semantics.
enum NativePDFSerialization {
    struct Prepared: Sendable {
        let data: Data
        fileprivate let snapshot: Snapshot
        fileprivate let password: String?
        fileprivate let encrypted: Bool
    }
    fileprivate struct Snapshot: Sendable, Equatable {
        let pages: [Page]
    }
    fileprivate struct Page: Sendable, Equatable {
        let media: [Double]
        let crop: [Double]
        let rotation: Int
        let textDigest: Data
        let annotations: [String]
    }
    private static let maximumBytes = 1_073_741_824
    private static let executable = URL(fileURLWithPath: "/opt/homebrew/bin/qpdf")
    typealias LaunchObserver = (Process, URL) -> Void

    /// Call on the queue that owns document. The baseline precedes PDFKit's
    /// writer; Prepared contains only immutable values safe to send to a worker.
    static func prepare(document: PDFDocument, password: String? = nil) throws -> Prepared {
        try checkCancellation(nil)
        guard !document.isLocked else { throw failure("Desbloqueie o documento antes de salvar uma cópia.") }
        try validatePassword(password)
        if document.isEncrypted, password == nil {
            throw failure("A publicação de um documento protegido exige a senha da cópia. Nenhum arquivo sem proteção será criado.")
        }
        let baseline = try snapshot(document)
        let bytes: Data?
        if let password {
            bytes = document.dataRepresentation(options: [
                AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): password,
                AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): password
            ])
        } else { bytes = document.dataRepresentation() }
        guard let bytes, !bytes.isEmpty, bytes.count <= maximumBytes else {
            throw failure("O escritor nativo não produziu uma cópia válida dentro do limite de 1 GiB.")
        }
        try checkCancellation(nil)
        return Prepared(data: bytes, snapshot: baseline, password: password, encrypted: password != nil)
    }

    static func serialize(document: PDFDocument, password: String? = nil,
                          cancellation: NativeCancellation = NativeCancellation()) throws -> Data {
        try checkCancellation(cancellation)
        return try finish(prepare(document: document, password: password), cancellation: cancellation)
    }

    /// For bytes created by CGContext or another native producer. This does not
    /// invoke PDFKit's serializer a second time. Encrypted input stays encrypted.
    static func normalize(data: Data, password: String? = nil,
                          cancellation: NativeCancellation = NativeCancellation()) throws -> Data {
        try checkCancellation(cancellation)
        try validatePassword(password)
        guard !data.isEmpty, data.count <= maximumBytes, let document = PDFDocument(data: data) else {
            throw failure("O PDF gerado não pôde ser aberto para validar sua estrutura.")
        }
        let encrypted = document.isEncrypted
        if password != nil, !encrypted {
            throw failure("A cópia fornecida não está criptografada, embora uma senha tenha sido exigida. Nenhum arquivo sem proteção será publicado.")
        }
        if encrypted {
            guard let password, document.isLocked, !document.unlock(withPassword: ""), document.unlock(withPassword: password) else {
                throw failure("Não foi possível confirmar a proteção do PDF gerado.")
            }
        }
        let prepared = Prepared(data: data, snapshot: try snapshot(document, cancellation: cancellation), password: encrypted ? password : nil, encrypted: encrypted)
        return try finish(prepared, cancellation: cancellation)
    }

    static func finish(_ prepared: Prepared, cancellation: NativeCancellation = NativeCancellation(),
                       onLaunch: LaunchObserver? = nil, timeout: TimeInterval = 60) throws -> Data {
        try checkCancellation(cancellation)
        guard timeout.isFinite, timeout > 0, timeout <= 60 else { throw failure("O prazo do verificador PDF é inválido.") }
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw failure("O verificador PDF não está instalado. Execute novamente o instalador completo; nenhum arquivo foi publicado.")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-serialization-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let input = directory.appendingPathComponent("input.pdf")
        let output = directory.appendingPathComponent("checked.pdf")
        let credential = directory.appendingPathComponent("password.txt")
        try NativeOutput.write(prepared.data, to: input)
        try NativeOutput.write(Data(((prepared.password ?? "") + "\n").utf8), to: credential)
        let initial = try run(["--password-file=-", "--check", input.path], credential: credential,
                              directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        let result: Data
        switch initial {
        case 0:
            result = prepared.data
        case 3:
            // A private, pre-created 0600 file keeps encrypted and unencrypted
            // documents private even if qpdf's default umask is permissive.
            try NativeOutput.write(Data(), to: output)
            let rewritten = try run(["--password-file=-", "--object-streams=preserve", "--stream-data=preserve", input.path, output.path],
                                    credential: credential, directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
            guard rewritten == 0 || rewritten == 3 else {
                throw failure("Não foi possível corrigir a estrutura da cópia nativa (status \(rewritten)). Nenhum arquivo foi publicado.")
            }
            let final = try run(["--password-file=-", "--check", output.path], credential: credential,
                                directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
            guard final == 0 else {
                throw failure("A cópia nativa ainda apresenta erros ou avisos estruturais (status \(final)). Nenhum arquivo foi publicado.")
            }
            result = try readPrivate(output, cancellation: cancellation)
        default:
            throw failure("O PDF gerado foi recusado pelo verificador estrutural (status \(initial)). Nenhum arquivo foi publicado.")
        }
        try checkCancellation(cancellation)
        try verifyFidelity(data: result, prepared: prepared, cancellation: cancellation)
        try checkCancellation(cancellation)
        return result
    }

    /// Internal testable boundary: structural repair must not lose pages, text,
    /// editable annotations or form values. It is not a pixel-equivalence claim.
    static func verifyFidelity(data: Data, prepared: Prepared, cancellation: NativeCancellation? = nil) throws {
        try checkCancellation(cancellation)
        guard !data.isEmpty, data.count <= maximumBytes, let reopened = PDFDocument(data: data),
              reopened.isEncrypted == prepared.encrypted else {
            throw failure("A cópia alterou a proteção ou não pode ser reaberta.")
        }
        if prepared.encrypted {
            guard let password = prepared.password, reopened.isLocked,
                  !reopened.unlock(withPassword: ""), reopened.unlock(withPassword: password) else {
                throw failure("A cópia não preservou a senha e a proteção esperadas.")
            }
        }
        guard try snapshot(reopened, cancellation: cancellation) == prepared.snapshot else {
            throw failure("A cópia alterou páginas, texto, anotações ou campos preenchidos. Nenhum arquivo foi publicado.")
        }
    }

    private static func snapshot(_ document: PDFDocument, cancellation: NativeCancellation? = nil) throws -> Snapshot {
        guard !document.isLocked, document.pageCount > 0 else { throw failure("O documento não contém páginas acessíveis.") }
        var pages: [Page] = []
        pages.reserveCapacity(document.pageCount)
        for index in 0..<document.pageCount {
            try checkCancellation(cancellation)
            guard let page = document.page(at: index) else { throw failure("Uma página não pôde ser verificada.") }
            let text = Data((page.string ?? "").utf8)
            pages.append(Page(media: try rectangle(page.bounds(for: .mediaBox)), crop: try rectangle(page.bounds(for: .cropBox)),
                              rotation: ((page.rotation % 360) + 360) % 360, textDigest: Data(SHA256.hash(data: text)),
                              annotations: try page.annotations.map(annotation).sorted()))
        }
        return Snapshot(pages: pages)
    }

    private static func annotation(_ item: PDFAnnotation) throws -> String {
        var values: [String: Any] = ["type": PDFAnnotationKind.normalizedName(item.type) ?? "",
            "bounds": try rectangle(item.bounds), "contents": item.contents ?? "", "display": item.shouldDisplay,
            "print": item.shouldPrint, "color": try color(item.color)]
        if PDFAnnotationKind.matchesAny(item, [.ink, .line, .square, .circle, .freeText]) {
            // PDFKit may materialize an implicit border with its default width.
            values["width"] = try number(item.border?.lineWidth ?? 1)
        }
        if PDFAnnotationKind.matches(item, .freeText) {
            values["fontSize"] = try number(item.font?.pointSize ?? 12)
            values["fontColor"] = try color(item.fontColor ?? .black)
        }
        if PDFAnnotationKind.hasQuadrilaterals(item) {
            values["quadrilaterals"] = try (item.quadrilateralPoints ?? []).flatMap { try point($0.pointValue) }
        }
        if PDFAnnotationKind.matches(item, .line) {
            values["start"] = try point(item.startPoint); values["end"] = try point(item.endPoint)
            values["startStyle"] = item.startLineStyle.rawValue; values["endStyle"] = item.endLineStyle.rawValue
        }
        if PDFAnnotationKind.matches(item, .ink) {
            values["paths"] = try (item.paths ?? []).map { path -> [Double] in
                var result: [Double] = []
                for index in 0..<path.elementCount {
                    var points = [NSPoint](repeating: .zero, count: 3)
                    let element = points.withUnsafeMutableBufferPointer { path.element(at: index, associatedPoints: $0.baseAddress!) }
                    result.append(Double(element.rawValue))
                    let count = element == .curveTo ? 3 : element == .closePath ? 0 : 1
                    for value in points.prefix(count) { result += try point(value) }
                }
                return result
            }
        }
        if PDFAnnotationKind.matches(item, .widget) {
            values["field"] = item.fieldName ?? ""
            values["fieldType"] = PDFAnnotationKind.normalizedName(item.widgetFieldType.rawValue) ?? ""
            values["value"] = item.widgetStringValue ?? ""; values["default"] = item.widgetDefaultStringValue ?? ""
            values["readOnly"] = item.isReadOnly
            if item.widgetFieldType == .button {
                values["buttonState"] = item.buttonWidgetState.rawValue; values["control"] = item.widgetControlType.rawValue
                values["buttonName"] = item.buttonWidgetStateString
            } else if item.widgetFieldType == .choice {
                values["choices"] = item.choices ?? []; values["choiceValues"] = item.values ?? []
                values["list"] = item.isListChoice
            } else if item.widgetFieldType == .text {
                values["multiline"] = item.isMultiline; values["maxLength"] = item.maximumLength
            }
        }
        if PDFAnnotationKind.matches(item, .link) { values["url"] = item.url?.absoluteString ?? "" }
        let data = try JSONSerialization.data(withJSONObject: values, options: [.sortedKeys])
        return String(decoding: data, as: UTF8.self)
    }

    private static func number(_ value: CGFloat) throws -> Double {
        guard value.isFinite else { throw failure("O documento contém geometria não finita.") }
        let rounded = (Double(value) * 1000).rounded() / 1000
        return rounded == 0 ? 0 : rounded
    }
    private static func rectangle(_ value: CGRect) throws -> [Double] {
        try [number(value.origin.x), number(value.origin.y), number(value.size.width), number(value.size.height)]
    }
    private static func point(_ value: CGPoint) throws -> [Double] { try [number(value.x), number(value.y)] }
    private static func color(_ value: NSColor) throws -> [Int] {
        guard let rgb = value.usingColorSpace(.sRGB) else { throw failure("Uma cor do documento não pôde ser verificada.") }
        return try [rgb.redComponent, rgb.greenComponent, rgb.blueComponent, rgb.alphaComponent].map {
            guard $0.isFinite else { throw failure("O documento contém uma cor inválida.") }
            return Int((min(1, max(0, $0)) * 255).rounded())
        }
    }
    private static func validatePassword(_ value: String?) throws {
        guard let value else { return }
        guard !value.isEmpty, !value.contains("\n"), !value.contains("\r"), !value.contains("\0"), value.utf8.count <= 4096 else {
            throw failure("A senha não pode ser transmitida com segurança ao verificador PDF.")
        }
    }
    private static func checkCancellation(_ token: NativeCancellation?) throws {
        try token?.check()
        if Task.isCancelled { throw CancellationError() }
    }

    private static func run(_ arguments: [String], credential: URL, directory: URL,
                            cancellation: NativeCancellation, onLaunch: LaunchObserver?, timeout: TimeInterval) throws -> Int32 {
        try checkCancellation(cancellation)
        let stdin = try FileHandle(forReadingFrom: credential)
        defer { try? stdin.close() }
        let process = Process()
        process.executableURL = executable; process.arguments = arguments; process.currentDirectoryURL = directory
        process.standardInput = stdin; process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { throw failure("Não foi possível iniciar o verificador PDF.") }
        defer {
            if process.isRunning {
                process.terminate()
                let grace = ProcessInfo.processInfo.systemUptime + 1
                while process.isRunning && ProcessInfo.processInfo.systemUptime < grace { Thread.sleep(forTimeInterval: 0.02) }
                if process.isRunning { _ = Darwin.kill(process.processIdentifier, SIGKILL) }
            }
            process.waitUntilExit()
        }
        onLaunch?(process, directory)
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        while process.isRunning {
            try checkCancellation(cancellation)
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw failure("O verificador PDF excedeu o prazo de execução. Nenhum arquivo foi publicado.") }
            Thread.sleep(forTimeInterval: 0.02)
        }
        process.waitUntilExit()
        try checkCancellation(cancellation)
        guard process.terminationReason == .exit else { throw failure("O verificador PDF terminou por sinal. Nenhum arquivo foi publicado.") }
        return process.terminationStatus
    }

    private static func readPrivate(_ url: URL, cancellation: NativeCancellation) throws -> Data {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("O resultado privado do verificador não está disponível.") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_mode & 0o077 == 0, info.st_size > 0,
              info.st_size <= Int64(maximumBytes) else { throw failure("O resultado PDF não é um arquivo privado e regular dentro do limite.") }
        var data = Data()
        while let chunk = try handle.read(upToCount: min(1_048_576, maximumBytes + 1 - data.count)), !chunk.isEmpty {
            try checkCancellation(cancellation)
            data.append(chunk)
            guard data.count <= maximumBytes else { throw failure("O PDF cresceu além do limite permitido.") }
        }
        return data
    }
    private static func failure(_ text: String) -> NSError {
        NSError(domain: "PDF.NativeSerialization", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
}
