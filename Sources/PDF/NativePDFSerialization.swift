import Foundation
import AppKit
import PDFKit
import CryptoKit
import Darwin
import Security

/// The publication boundary for native PDF writers. PDFKit can emit malformed
/// stream lengths and string types while keeping a readable document. Check the
/// raw structure, repair only proven defects using the pre-writer baseline, then
/// independently verify structure, protection and original document semantics.
enum NativePDFSerialization {
    struct Opening: Sendable {
        let originalData: Data
        let requiresPassword: Bool
        let isEncrypted: Bool
        let usedCompatibilityCopy: Bool
        fileprivate let nativeData: Data
        fileprivate let nativePassword: String?
        fileprivate let protection: SourceProtection?
    }

    fileprivate struct SourceProtection: Sendable {
        let sourceDigest: Data
        let permissions: EncryptionPermissions
        let bits: Int
        let ownerAuthenticated: Bool
    }

    private final class ProtectionBox: NSObject {
        let value: SourceProtection
        init(_ value: SourceProtection) { self.value = value }
    }
    private final class ProtectionRegistry: @unchecked Sendable {
        private let lock = NSLock()
        private let records = NSMapTable<PDFDocument, ProtectionBox>(
            keyOptions: [.weakMemory, .objectPointerPersonality], valueOptions: .strongMemory)
        func set(_ protection: SourceProtection, for document: PDFDocument) {
            lock.lock(); defer { lock.unlock() }
            records.setObject(ProtectionBox(protection), forKey: document)
        }
        func get(_ document: PDFDocument) -> SourceProtection? {
            lock.lock(); defer { lock.unlock() }
            return records.object(forKey: document)?.value
        }
    }
    private static let protectedSources = ProtectionRegistry()

    struct Prepared: Sendable {
        let data: Data
        // Private staging authentication only. Never persist this credential in
        // session/recovery metadata or show it in diagnostics.
        let inputPassword: String?
        fileprivate let snapshot: Snapshot
        fileprivate let password: String?
        fileprivate let encrypted: Bool
        fileprivate let permissions: EncryptionPermissions
        fileprivate let strings: NativePDFStringRepair.Baseline?
    }
    fileprivate struct Snapshot: Sendable, Equatable {
        let pages: [Page]
    }
    fileprivate struct Page: Sendable, Equatable {
        let media: [Double]
        let crop: [Double]
        let rotation: Int
        let textDigest: Data
        // Swift String equality folds canonically equivalent Unicode. PDF field
        // identifiers and editable values require the exact original codepoints.
        let annotations: [Data]
    }
    fileprivate struct EncryptionPermissions: Sendable, Equatable {
        let accessibility: Bool
        let extract: Bool
        let annotate: Bool
        let assemble: Bool
        let form: Bool
        let modifyOther: Bool
        let printLow: Bool
        let printHigh: Bool

        static let unrestricted = EncryptionPermissions(accessibility: true, extract: true, annotate: true,
            assemble: true, form: true, modifyOther: true, printLow: true, printHigh: true)
        var capabilities: [String: Bool] {
            ["accessibility": accessibility, "extract": extract, "modifyannotations": annotate,
             "modifyassembly": assemble, "modifyforms": form, "modifyother": modifyOther,
             "printlow": printLow, "printhigh": printHigh]
        }
        var options: [String: String] {
            ["accessibility": "y", "extract": extract ? "y" : "n", "annotate": annotate ? "y" : "n",
             "assemble": assemble ? "y" : "n", "form": form ? "y" : "n", "modifyOther": modifyOther ? "y" : "n",
             "print": printHigh ? "full" : printLow ? "low" : "none"]
        }
    }
    private static let maximumBytes = 1_073_741_824
    private static let maximumRepairJSONBytes = 64 * 1_024 * 1_024
    private static var executable: URL {
        if let resources = Bundle.main.resourceURL,
           FileManager.default.fileExists(atPath: resources.appendingPathComponent("runtime/portable.json").path) {
            // A portable installation must never fall back to a host dependency.
            return resources.appendingPathComponent("runtime/bin/qpdf")
        }
        return URL(fileURLWithPath: "/opt/homebrew/bin/qpdf")
    }
    typealias LaunchObserver = (Process, URL) -> Void

    /// Read-only opening of the exact supplied bytes. Run this synchronous work
    /// off the UI queue; finishOpen constructs the PDFDocument on its owner queue.
    /// The original credential is used only to authenticate the original PDF.
    static func prepareOpen(data: Data, password: String? = nil,
                            cancellation: NativeCancellation = NativeCancellation(),
                            onLaunch: LaunchObserver? = nil, timeout: TimeInterval = 60) throws -> Opening {
        try checkCancellation(cancellation)
        guard !data.isEmpty, data.count <= maximumBytes, let candidate = PDFDocument(data: data) else {
            throw failure("O documento original não pôde ser aberto dentro do limite de 1 GiB.")
        }
        guard candidate.isEncrypted else {
            return Opening(originalData: data, requiresPassword: false, isEncrypted: false, usedCompatibilityCopy: false,
                           nativeData: data, nativePassword: nil, protection: nil)
        }
        if candidate.isLocked, password == nil {
            return Opening(originalData: data, requiresPassword: true, isEncrypted: true, usedCompatibilityCopy: false,
                           nativeData: data, nativePassword: nil, protection: nil)
        }
        let credential = password ?? ""
        guard !credential.contains("\0"), credential.utf8.count <= 4096 else {
            throw failure("A senha de abertura contém caracteres não suportados ou excede o limite permitido.")
        }
        guard timeout.isFinite, timeout > 0, timeout <= 60,
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw failure("O verificador de documentos protegidos não está disponível. Execute o instalador completo.")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-opening-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let input = directory.appendingPathComponent("original.pdf")
        try NativeOutput.write(data, to: input)
        let protection = try inspectOriginalProtection(input, data: data, password: credential,
            directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        _ = candidate.unlock(withPassword: credential)
        if !candidate.isLocked, !protection.ownerAuthenticated || candidate.permissionsStatus == .owner {
            guard !candidate.isLocked, candidate.pageCount > 0 else {
                throw failure("O documento autenticado não contém páginas acessíveis.")
            }
            return Opening(originalData: data, requiresPassword: false, isEncrypted: true, usedCompatibilityCopy: false,
                           nativeData: data, nativePassword: credential, protection: protection)
        }

        // Standalone CoreGraphics accepts these UTF-8 credentials, but PDFKit's
        // password API can leave the wrapper locked. Keep an encrypted
        // compatibility copy; never create a plaintext PDF and never replace
        // the original bytes or their password.
        guard protection.permissions.accessibility else {
            throw failure("O leitor nativo não aceitou esta senha e a proteção legada não permite criar uma cópia de compatibilidade sem ampliar permissões. O original permanece intacto.")
        }
        guard protection.bits <= 256 else { throw failure("A cifra original não pode ser preservada pela cópia de compatibilidade.") }
        let readerPassword = try randomCredential(byteCount: 16)
        let ownerPassword = try randomCredential(byteCount: 16)
        guard readerPassword != ownerPassword, readerPassword != credential, ownerPassword != credential else {
            throw failure("Não foi possível gerar credenciais temporárias distintas para o leitor.")
        }
        let output = directory.appendingPathComponent("compatible.pdf")
        try NativeOutput.write(Data(), to: output)
        let status = try runJob(["inputFile": input.path, "outputFile": output.path, "password": credential,
            "objectStreams": "preserve", "streamData": "preserve", "encrypt": [
                "userPassword": readerPassword, "ownerPassword": ownerPassword, "256bit": protection.permissions.options]],
            directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        guard status == 0 || status == 3 else { throw failure("A cópia cifrada para leitura não pôde ser preparada. O original permanece intacto.") }
        let checked = try runJob(["inputFile": output.path, "password": readerPassword, "check": ""],
            directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        guard checked == 0 else { throw failure("A cópia cifrada para leitura foi recusada pelo verificador estrutural.") }
        try verifyEncryption(output, password: readerPassword, permissions: protection.permissions,
            directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        let nativeData = try readPrivate(output, cancellation: cancellation)
        try checkCancellation(cancellation)
        return Opening(originalData: data, requiresPassword: false, isEncrypted: true, usedCompatibilityCopy: true,
            nativeData: nativeData, nativePassword: protection.ownerAuthenticated ? ownerPassword : readerPassword, protection: protection)
    }

    /// Invoke on the queue that will own the returned PDFDocument (MainActor for
    /// the reader, the current worker for a private fidelity verification).
    static func finishOpen(_ opening: Opening) throws -> PDFDocument {
        try checkCancellation(nil)
        guard !opening.requiresPassword else { throw failure("Informe a senha para abrir o documento protegido.") }
        guard let document = PDFDocument(data: opening.nativeData), document.isEncrypted == opening.isEncrypted else {
            throw failure("O documento preparado para leitura não preservou sua proteção.")
        }
        if opening.isEncrypted {
            guard let password = opening.nativePassword, let protection = opening.protection,
                  protection.sourceDigest == Data(SHA256.hash(data: opening.originalData)) else {
                throw failure("A origem do documento protegido não pôde ser comprovada.")
            }
            _ = document.unlock(withPassword: password)
            guard !document.isLocked, !protection.ownerAuthenticated || document.permissionsStatus == .owner else {
                throw failure("O documento autenticado não pôde ser aberto pelo leitor nativo.")
            }
            protectedSources.set(protection, for: document)
        }
        guard document.pageCount > 0 else { throw failure("O documento não contém páginas acessíveis.") }
        return document
    }

    static func open(data: Data, password: String? = nil,
                     cancellation: NativeCancellation = NativeCancellation()) throws -> PDFDocument {
        try finishOpen(prepareOpen(data: data, password: password, cancellation: cancellation))
    }

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
        let strings = try NativePDFStringRepair.capture(document: document)
        let permissions = try encryptionPermissions(document)
        if password != nil, !permissions.accessibility {
            throw failure("A restrição de acessibilidade deste PDF não pode ser preservada no AES-256 moderno. O original permanece intacto; nenhuma cópia foi publicada.")
        }
        // PDFKit exposes effective defaults that its writer does not always
        // persist (notably font size and a form's empty reset value). Make those
        // same values explicit only after capturing what the user had. The
        // final comparison must still match that earlier baseline.
        try materializeWriterDefaults(document)
        let bytes: Data?
        let inputPassword: String?
        if password != nil {
            // PDFKit's intermediate writer supports at most 32 ASCII password
            // bytes. Its Unicode handling can emit nil or even unprotected data.
            // Keep staging encrypted with a fresh ASCII secret; qpdf applies the
            // user's full UTF-8 password only to the final AES-256 document.
            let stagingPassword = try randomCredential(byteCount: 16)
            inputPassword = stagingPassword
            bytes = document.dataRepresentation(options: [
                AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): stagingPassword,
                AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): stagingPassword
            ])
        } else {
            inputPassword = nil
            bytes = document.dataRepresentation()
        }
        guard let bytes, !bytes.isEmpty, bytes.count <= maximumBytes else {
            throw failure("O escritor nativo não produziu uma cópia válida dentro do limite de 1 GiB.")
        }
        try checkCancellation(nil)
        return Prepared(data: bytes, inputPassword: inputPassword, snapshot: baseline,
                        password: password, encrypted: password != nil, permissions: permissions, strings: strings)
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
        guard !data.isEmpty, data.count <= maximumBytes, let original = PDFDocument(data: data) else {
            throw failure("O PDF gerado não pôde ser aberto para validar sua estrutura.")
        }
        let encrypted = original.isEncrypted
        if password != nil, !encrypted {
            throw failure("A cópia fornecida não está criptografada, embora uma senha tenha sido exigida. Nenhum arquivo sem proteção será publicado.")
        }
        let document: PDFDocument
        if encrypted {
            guard let password, original.isLocked, !original.unlock(withPassword: "") else {
                throw failure("Não foi possível confirmar a proteção do PDF gerado.")
            }
            document = try open(data: data, password: password, cancellation: cancellation)
        } else { document = original }
        let prepared = Prepared(data: data, inputPassword: encrypted ? password : nil, snapshot: try snapshot(document, cancellation: cancellation),
            password: encrypted ? password : nil, encrypted: encrypted, permissions: try encryptionPermissions(document), strings: nil)
        return try finish(prepared, cancellation: cancellation)
    }

    static func finish(_ prepared: Prepared, cancellation: NativeCancellation = NativeCancellation(),
                       onLaunch: LaunchObserver? = nil, timeout: TimeInterval = 60) throws -> Data {
        try checkCancellation(cancellation)
        guard timeout.isFinite, timeout > 0, timeout <= 60 else { throw failure("O prazo do verificador PDF é inválido.") }
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw failure("O verificador PDF não está instalado. Execute novamente o instalador completo; nenhum arquivo foi publicado.")
        }
        if prepared.encrypted {
            // A native-writer failure must never turn a protected session into
            // even a private plaintext staging file.
            guard let inputPassword = prepared.inputPassword,
                  let inputDocument = PDFDocument(data: prepared.data), inputDocument.isEncrypted,
                  inputDocument.isLocked, !inputDocument.unlock(withPassword: ""), inputDocument.unlock(withPassword: inputPassword) else {
                throw failure("O escritor nativo não preservou a proteção da cópia. Nenhum PDF temporário desprotegido foi criado.")
            }
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-serialization-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let input = directory.appendingPathComponent("input.pdf")
        let output = directory.appendingPathComponent("checked.pdf")
        try NativeOutput.write(prepared.data, to: input)
        let password = prepared.password ?? ""
        let inputPassword = prepared.inputPassword ?? ""
        let initial = try runJob(["inputFile": input.path, "password": inputPassword, "check": ""],
                                 directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        guard initial == 0 || initial == 3 else {
            throw failure("O PDF gerado foi recusado pelo verificador estrutural (status \(initial)). Nenhum arquivo foi publicado.")
        }
        let stringPatch: URL?
        if let strings = prepared.strings {
            stringPatch = try prepareStringPatch(input: input, password: inputPassword, baseline: strings,
                directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
        } else { stringPatch = nil }
        let result: Data
        if initial == 0, !prepared.encrypted, stringPatch == nil {
            result = prepared.data
        } else {
            // A private, pre-created 0600 file keeps encrypted and unencrypted
            // documents private even if qpdf's default umask is permissive.
            try NativeOutput.write(Data(), to: output)
            var job: [String: Any] = ["inputFile": input.path, "outputFile": output.path, "password": inputPassword,
                                      "objectStreams": "preserve", "streamData": "preserve"]
            if let stringPatch { job["updateFromJson"] = stringPatch.path }
            if prepared.encrypted {
                guard prepared.permissions.accessibility else {
                    throw failure("A restrição de acessibilidade deste PDF não pode ser preservada no AES-256 moderno. O original permanece intacto; nenhuma cópia foi publicada.")
                }
                // Upgrade even structurally valid PDFKit output. A separate
                // random owner credential prevents the reader password from
                // silently granting permission to change document restrictions.
                job["encrypt"] = ["userPassword": password, "ownerPassword": try ownerCredential(excluding: password),
                                  "256bit": prepared.permissions.options] as [String: Any]
            }
            let rewritten = try runJob(job, directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
            guard rewritten == 0 || rewritten == 3 else {
                throw failure("Não foi possível corrigir a estrutura da cópia nativa (status \(rewritten)). Nenhum arquivo foi publicado.")
            }
            let final = try runJob(["inputFile": output.path, "password": password, "check": ""],
                                  directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
            guard final == 0 else {
                throw failure("A cópia nativa ainda apresenta erros ou avisos estruturais (status \(final)). Nenhum arquivo foi publicado.")
            }
            if prepared.encrypted {
                try verifyEncryption(output, password: password, permissions: prepared.permissions,
                                     directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout)
            }
            result = try readPrivate(output, cancellation: cancellation)
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
        guard !data.isEmpty, data.count <= maximumBytes, let original = PDFDocument(data: data),
              original.isEncrypted == prepared.encrypted else {
            throw failure("A cópia alterou a proteção ou não pode ser reaberta.")
        }
        let reopened: PDFDocument
        if prepared.encrypted {
            guard let password = prepared.password, original.isLocked, !original.unlock(withPassword: "") else {
                throw failure("A cópia não preservou a senha e a proteção esperadas.")
            }
            reopened = try open(data: data, password: password, cancellation: cancellation ?? NativeCancellation())
        } else { reopened = original }
        let actual = try snapshot(reopened, cancellation: cancellation)
        guard actual == prepared.snapshot else {
            let categories = fidelityDifferences(expected: prepared.snapshot, actual: actual).joined(separator: "; ")
            throw failure("A cópia alterou páginas, texto, anotações ou campos preenchidos. Verificação: \(categories). Nenhum arquivo foi publicado.")
        }
    }

    /// Report only fixed field names and page numbers. Even on failure, never
    /// include document text, widget values, digests, passwords or file paths.
    private static func fidelityDifferences(expected: Snapshot, actual: Snapshot) -> [String] {
        var differences: [String] = []
        let maximum = 16
        if expected.pages.count != actual.pages.count { differences.append("quantidade de páginas") }
        for (index, pair) in zip(expected.pages, actual.pages).enumerated() {
            guard differences.count < maximum else { break }
            let (before, after) = pair
            let prefix = "página \(index + 1): "
            if before.media != after.media { differences.append(prefix + "mediaBox") }
            if before.crop != after.crop { differences.append(prefix + "cropBox") }
            if before.rotation != after.rotation { differences.append(prefix + "rotation") }
            if before.textDigest != after.textDigest { differences.append(prefix + "texto") }
            guard before.annotations != after.annotations else { continue }
            if before.annotations.count != after.annotations.count { differences.append(prefix + "quantidade de anotações") }
            // Remove exact matches as a multiset; order is not a semantic change.
            var remaining: [Data: Int] = [:]
            for value in after.annotations { remaining[value, default: 0] += 1 }
            var missing: [Data] = []
            for value in before.annotations {
                if let count = remaining[value], count > 0 { remaining[value] = count - 1 }
                else if missing.count < maximum { missing.append(value) }
            }
            var candidates: [[String: Any]] = []
            for (value, count) in remaining.sorted(by: { $0.key.lexicographicallyPrecedes($1.key) }) where count > 0 {
                guard candidates.count < maximum else { break }
                if let dictionary = annotationDictionary(value) {
                    for _ in 0..<min(count, maximum - candidates.count) { candidates.append(dictionary) }
                }
            }
            for value in missing {
                guard differences.count < maximum else { break }
                guard let original = annotationDictionary(value), !candidates.isEmpty else {
                    differences.append(prefix + "anotação ausente ou incompatível"); continue
                }
                // Matching by the smallest number of differing fields is for
                // diagnosis only. The strict snapshot equality above is final.
                let ranked = candidates.indices.map { candidate in
                    (candidate, differingAnnotationFields(original, candidates[candidate]))
                }.min { $0.1.count < $1.1.count }
                guard let ranked else { continue }
                candidates.remove(at: ranked.0)
                for field in ranked.1.prefix(maximum - differences.count) {
                    differences.append(prefix + "anotação." + field)
                }
            }
        }
        return differences.isEmpty ? ["anotações incompatíveis"] : Array(differences.prefix(maximum))
    }
    private static func annotationDictionary(_ value: Data) -> [String: Any]? {
        (try? JSONSerialization.jsonObject(with: value)) as? [String: Any]
    }
    private static func differingAnnotationFields(_ before: [String: Any], _ after: [String: Any]) -> [String] {
        // Only these implementation-owned names can reach a user-visible error.
        let fields = ["type", "bounds", "contents", "display", "print", "color", "width", "fontName", "fontSize", "fontColor",
                      "quadrilaterals", "start", "end", "startStyle", "endStyle", "paths", "field", "fieldType",
                      "value", "default", "readOnly", "buttonState", "control", "buttonName", "choices", "choiceValues",
                      "list", "multiline", "maxLength", "url", "open", "textFields", "flags"]
        return fields.filter { key in
            switch (before[key], after[key]) {
            case (nil, nil): return false
            case let (left?, right?):
                let leftBytes = try? JSONSerialization.data(withJSONObject: ["value": left], options: [.sortedKeys])
                let rightBytes = try? JSONSerialization.data(withJSONObject: ["value": right], options: [.sortedKeys])
                return leftBytes == nil || rightBytes == nil || leftBytes != rightBytes
            default: return true
            }
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
                              annotations: try page.annotations.filter { !isDerivedPopup($0, on: page) }.map(annotation)
                                .sorted { $0.lexicographicallyPrecedes($1) }))
        }
        return Snapshot(pages: pages)
    }

    private static func annotation(_ item: PDFAnnotation) throws -> Data {
        var values: [String: Any] = ["type": PDFAnnotationKind.normalizedName(item.type) ?? "",
            "bounds": try rectangle(item.bounds), "contents": item.contents ?? "", "display": item.shouldDisplay,
            "print": item.shouldPrint, "color": try annotationColor(item),
            "textFields": try NativePDFStringRepair.annotationTextFields(item)]
        if PDFAnnotationKind.matches(item, .text) {
            // Text annotations use a viewer-sized icon. PDFKit reopens them as
            // 24pt icons while retaining this upper-left document-space anchor.
            // Moving the note still changes the fingerprint; resizing its icon
            // is not a change to the note's placement or editable contents.
            values["bounds"] = try [number(item.bounds.minX), number(item.bounds.maxY)]
        }
        if PDFAnnotationKind.matchesAny(item, [.ink, .line, .square, .circle, .freeText]) {
            // PDFKit may materialize an implicit border with its default width.
            let defaultWidth: CGFloat = PDFAnnotationKind.matches(item, .freeText) ? 0 : 1
            values["width"] = try number(item.border?.lineWidth ?? defaultWidth)
        }
        if PDFAnnotationKind.matches(item, .freeText) {
            values["fontName"] = item.font?.fontName ?? ""
            values["fontSize"] = try number(item.font?.pointSize ?? 12)
            values["fontColor"] = try color(item.fontColor ?? .black)
        }
        if PDFAnnotationKind.matches(item, .popup) {
            // SDK26 reports shouldPrint=false for an unchanged popup whose
            // actual /F remains 4. Compare the complete PDF flags instead of
            // either convenience getter; preserve unknown bits as well.
            values.removeValue(forKey: "display")
            values.removeValue(forKey: "print")
            values["flags"] = try popupFlags(item)
            values["open"] = item.isOpen
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
                    let count = element == .cubicCurveTo ? 3 : element == .closePath ? 0 : 1
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
                values["value"] = try NativePDFStringRepair.choiceSelection(item)
                values["choices"] = item.choices ?? []; values["choiceValues"] = item.values ?? []
                values["list"] = item.isListChoice
            } else if item.widgetFieldType == .text {
                values["multiline"] = item.isMultiline; values["maxLength"] = item.maximumLength
            }
        }
        if PDFAnnotationKind.matches(item, .link) { values["url"] = item.url?.absoluteString ?? "" }
        return try JSONSerialization.data(withJSONObject: values, options: [.sortedKeys])
    }

    private static func materializeWriterDefaults(_ document: PDFDocument) throws {
        for index in 0..<document.pageCount {
            try checkCancellation(nil)
            guard let page = document.page(at: index) else { throw failure("Uma página não pôde ser preparada para gravação.") }
            for item in page.annotations {
                if PDFAnnotationKind.matches(item, .freeText) {
                    let font = item.font
                    let fontColor = item.fontColor
                    if let font { item.font = font }
                    if let fontColor { item.fontColor = fontColor }
                    if item.border == nil {
                        let border = PDFBorder()
                        border.lineWidth = 0
                        item.border = border
                    }
                    // /DA is a content-program STRING. SDK27 mistakes a
                    // leading slash for a PDF name, so reloading silently falls
                    // back to Helvetica 12 even when the appearance embeds the
                    // original font. Whitespace is neutral PDF syntax; preserve
                    // the entire program, font and color without reconstructing
                    // or changing any user-authored text.
                    let appearanceKey = PDFAnnotationKey(rawValue: "/DA")
                    if let appearance = item.value(forAnnotationKey: appearanceKey) as? String,
                       appearance.hasPrefix("/") {
                        guard item.setValue(" " + appearance, forAnnotationKey: appearanceKey) else {
                            throw failure("A aparência editável do texto não pôde ser preservada para gravação.")
                        }
                    }
                }
                if PDFAnnotationKind.matches(item, .widget),
                   item.widgetFieldType == .text || item.widgetFieldType == .choice {
                    // The getter can return an empty, non-nil string even when
                    // /DV is absent. Persist the effective reset value in both
                    // cases; the writer otherwise substitutes the current value.
                    let resetValue = item.widgetDefaultStringValue ?? ""
                    item.widgetDefaultStringValue = resetValue
                }
            }
        }
    }

    private static func isDerivedPopup(_ item: PDFAnnotation, on page: PDFPage) -> Bool {
        guard PDFAnnotationKind.matches(item, .popup), !item.isOpen else { return false }
        // A closed Text popup is a UI child. SDK26 serializes the automatic
        // empty child with inherited note text; SDK27 omits it altogether.
        // Keep independent, open, and independently authored popups strict.
        return page.annotations.contains { parent in
            guard PDFAnnotationKind.matches(parent, .text), parent.popup === item else { return false }
            let contents = item.contents ?? ""
            return contents.isEmpty || contents.utf8.elementsEqual((parent.contents ?? "").utf8)
        }
    }

    private static func annotationColor(_ item: PDFAnnotation) throws -> Any {
        // The Objective-C getter returns nil for widgets without /C, despite
        // its imported nonoptional Swift declaration. Public NSObject KVC keeps
        // that absence intact and avoids dereferencing the invalid Swift value.
        guard let value = item.value(forKey: "color") else { return NSNull() }
        guard let value = value as? NSColor else { throw failure("Uma cor do documento não pôde ser verificada.") }
        return try color(value)
    }

    private static func popupFlags(_ item: PDFAnnotation) throws -> UInt32 {
        guard let value = item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/F")) else { return 0 }
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue >= 0,
              number.doubleValue <= Double(UInt32.max), number.doubleValue.rounded(.towardZero) == number.doubleValue else {
            throw failure("As opções da anotação popup não puderam ser verificadas como um inteiro PDF válido.")
        }
        return number.uint32Value
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
    private static func encryptionPermissions(_ document: PDFDocument) throws -> EncryptionPermissions {
        guard document.isEncrypted else { return .unrestricted }
        // PDFKit.documentRef.accessPermissions reports high-quality print
        // access for a real low-only fixture on SDK26/27. Only qpdf evidence
        // from the ORIGINAL input bytes is authoritative; never infer
        // permissions from a reserialized copy.
        guard let proof = protectedSources.get(document) else {
            throw failure("Reabra o PDF protegido pelo aplicativo para verificar as permissões dos bytes originais antes de salvar. Nenhuma cópia foi publicada.")
        }
        return proof.permissions
    }

    private static func inspectOriginalProtection(_ input: URL, data: Data, password: String, directory: URL,
                                                  cancellation: NativeCancellation, onLaunch: LaunchObserver?,
                                                  timeout: TimeInterval) throws -> SourceProtection {
        let report = directory.appendingPathComponent("source-encryption-\(UUID().uuidString).json")
        let status = try runJob(["inputFile": input.path, "password": password, "json": "2", "jsonKey": ["encrypt"]],
            directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout, output: report)
        guard status == 0 || status == 3 else {
            throw failure("A senha não foi aceita ou o documento protegido não pôde ser autenticado. Os bytes originais permanecem intactos.")
        }
        let bytes = try readPrivate(report, cancellation: cancellation, limit: 65_536)
        guard let root = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any], root["version"] as? Int == 2,
              let encryption = root["encrypt"] as? [String: Any], encryption["encrypted"] as? Bool == true,
              let user = encryption["userpasswordmatched"] as? Bool,
              let owner = encryption["ownerpasswordmatched"] as? Bool, user || owner,
              let parameters = encryption["parameters"] as? [String: Any],
              let bits = parameters["bits"] as? Int, bits >= 40, bits <= 256,
              let capabilities = encryption["capabilities"] as? [String: Any] else {
            throw failure("A autenticação e as permissões originais não puderam ser comprovadas pelo verificador PDF.")
        }
        func flag(_ name: String) throws -> Bool {
            guard let result = capabilities[name] as? Bool else { throw failure("O verificador não retornou todas as permissões originais do PDF.") }
            return result
        }
        let permissions = try EncryptionPermissions(accessibility: flag("accessibility"), extract: flag("extract"),
            annotate: flag("modifyannotations"), assemble: flag("modifyassembly"), form: flag("modifyforms"),
            modifyOther: flag("modifyother"), printLow: flag("printlow"), printHigh: flag("printhigh"))
        try checkCancellation(cancellation)
        return SourceProtection(sourceDigest: Data(SHA256.hash(data: data)), permissions: permissions,
                                bits: bits, ownerAuthenticated: owner)
    }

    private static func ownerCredential(excluding password: String) throws -> String {
        let owner = try randomCredential(byteCount: 32)
        guard owner != password else { throw failure("Não foi possível criar credenciais de leitura e proprietário distintas.") }
        return owner
    }

    private static func randomCredential(byteCount: Int) throws -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw failure("Não foi possível gerar uma credencial temporária segura para a cópia.")
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    private static func verifyEncryption(_ file: URL, password: String, permissions: EncryptionPermissions,
                                         directory: URL, cancellation: NativeCancellation,
                                         onLaunch: LaunchObserver?, timeout: TimeInterval) throws {
        let report = directory.appendingPathComponent("encryption-\(UUID().uuidString).json")
        let status = try runJob(["inputFile": file.path, "password": password, "json": "2", "jsonKey": ["encrypt"]],
                                directory: directory, cancellation: cancellation, onLaunch: onLaunch,
                                timeout: timeout, output: report)
        guard status == 0 else { throw failure("A criptografia final da cópia não pôde ser verificada.") }
        // qpdf's JSON may include a recovered password. Keep it in the private
        // directory and inspect only this whitelist; never include it in logs.
        let data = try readPrivate(report, cancellation: cancellation, limit: 65_536)
        guard let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], root["version"] as? Int == 2,
              let encryption = root["encrypt"] as? [String: Any], encryption["encrypted"] as? Bool == true,
              encryption["userpasswordmatched"] as? Bool == true, encryption["ownerpasswordmatched"] as? Bool == false,
              let parameters = encryption["parameters"] as? [String: Any],
              parameters["bits"] as? Int == 256, parameters["V"] as? Int == 5, parameters["R"] as? Int == 6,
              ["method", "streammethod", "stringmethod", "filemethod"].allSatisfy({ parameters[$0] as? String == "AESv3" }),
              let capabilities = encryption["capabilities"] as? [String: Any],
              permissions.capabilities.allSatisfy({ capabilities[$0.key] as? Bool == $0.value }) else {
            throw failure("A cópia não preservou AES-256, senha de leitura e permissões esperadas. Nenhum arquivo foi publicado.")
        }
    }

    private static func prepareStringPatch(input: URL, password: String, baseline: NativePDFStringRepair.Baseline,
                                            directory: URL, cancellation: NativeCancellation,
                                            onLaunch: LaunchObserver?, timeout: TimeInterval) throws -> URL? {
        let report = directory.appendingPathComponent("strings-\(UUID().uuidString).json")
        // Stream bodies are excluded. This temporary object report may contain
        // annotation/form text, so it uses the same private directory and 0600
        // publication as credentials and is removed on every completion path.
        let status = try runJob(["inputFile": input.path, "password": password, "json": "2",
                                 "jsonKey": ["qpdf", "pages"], "jsonStreamData": "none"],
            directory: directory, cancellation: cancellation, onLaunch: onLaunch, timeout: timeout,
            output: report, outputLimit: maximumRepairJSONBytes)
        guard status == 0 || status == 3 else {
            throw failure("Os campos de texto da cópia nativa não puderam ser inspecionados com segurança.")
        }
        let bytes = try readPrivate(report, cancellation: cancellation, limit: maximumRepairJSONBytes)
        try checkCancellation(cancellation)
        guard let patch = try NativePDFStringRepair.patch(jsonData: bytes, baseline: baseline) else { return nil }
        guard !patch.isEmpty, patch.count <= maximumRepairJSONBytes else {
            throw failure("A correção dos tipos de texto excedeu o limite privado de 64 MiB.")
        }
        try checkCancellation(cancellation)
        let file = directory.appendingPathComponent("string-patch-\(UUID().uuidString).json")
        try NativeOutput.write(patch, to: file)
        return file
    }

    private static func validatePassword(_ value: String?) throws {
        guard let value else { return }
        guard !value.isEmpty, !value.contains("\n"), !value.contains("\r"), !value.contains("\0"), value.utf8.count <= 127 else {
            throw failure("A senha de saída deve ter de 1 a 127 bytes UTF-8, sem quebras de linha ou caracteres nulos.")
        }
    }
    private static func checkCancellation(_ token: NativeCancellation?) throws {
        try token?.check()
        if Task.isCancelled { throw CancellationError() }
    }

    private static func runJob(_ job: [String: Any], directory: URL, cancellation: NativeCancellation,
                               onLaunch: LaunchObserver?, timeout: TimeInterval, output: URL? = nil,
                               outputLimit: Int = 65_536) throws -> Int32 {
        try checkCancellation(cancellation)
        let input = directory.appendingPathComponent("job-\(UUID().uuidString).json")
        let data = try JSONSerialization.data(withJSONObject: job, options: [.sortedKeys])
        guard data.count <= 65_536 else { throw failure("A solicitação ao verificador PDF excedeu o limite privado.") }
        try NativeOutput.write(data, to: input)
        return try run(["--job-json-file=/dev/stdin"], credential: input, directory: directory,
                       cancellation: cancellation, onLaunch: onLaunch, timeout: timeout, output: output, outputLimit: outputLimit)
    }

    private static func run(_ arguments: [String], credential: URL, directory: URL,
                            cancellation: NativeCancellation, onLaunch: LaunchObserver?, timeout: TimeInterval,
                            output: URL? = nil, outputLimit: Int = 65_536) throws -> Int32 {
        try checkCancellation(cancellation)
        guard outputLimit > 0, outputLimit <= maximumRepairJSONBytes else {
            throw failure("O limite privado do relatório PDF é inválido.")
        }
        let stdin = try FileHandle(forReadingFrom: credential)
        defer { try? stdin.close() }
        var stdout: FileHandle?
        if let output {
            try NativeOutput.write(Data(), to: output)
            stdout = try FileHandle(forWritingTo: output)
        }
        defer { try? stdout?.close() }
        let process = Process()
        process.executableURL = executable; process.arguments = arguments; process.currentDirectoryURL = directory
        process.standardInput = stdin; process.standardOutput = stdout ?? FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        let runtimeLease = try BundleRuntimeLease.configureQPDFChild(process)
        defer { try? runtimeLease?.close() }
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
            if let stdout {
                var information = stat()
                guard fstat(stdout.fileDescriptor, &information) == 0, information.st_size <= Int64(outputLimit) else {
                    throw failure("O relatório privado do verificador excedeu o limite permitido.")
                }
            }
            Thread.sleep(forTimeInterval: 0.02)
        }
        process.waitUntilExit()
        try checkCancellation(cancellation)
        guard process.terminationReason == .exit else { throw failure("O verificador PDF terminou por sinal. Nenhum arquivo foi publicado.") }
        return process.terminationStatus
    }

    private static func readPrivate(_ url: URL, cancellation: NativeCancellation, limit: Int = maximumBytes) throws -> Data {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("O resultado privado do verificador não está disponível.") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_mode & 0o077 == 0, info.st_size > 0,
              info.st_size <= Int64(limit) else { throw failure("O resultado PDF não é um arquivo privado e regular dentro do limite.") }
        var data = Data()
        while let chunk = try handle.read(upToCount: min(1_048_576, limit + 1 - data.count)), !chunk.isEmpty {
            try checkCancellation(cancellation)
            data.append(chunk)
            guard data.count <= limit else { throw failure("O resultado privado cresceu além do limite permitido.") }
        }
        return data
    }
    private static func failure(_ text: String) -> NSError {
        NSError(domain: "PDF.NativeSerialization", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
}
