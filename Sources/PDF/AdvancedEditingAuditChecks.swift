import Foundation
import AppKit
import PDFKit
import CryptoKit
import Darwin

/// Validates editor coordinates and review transactions independently of views.
/// Engine operation roundtrips are covered by the backend's real PDF fixtures.
enum AdvancedEditingAuditChecks {
    @MainActor static func run() throws {
        func require(_ value: Bool, _ message: String) throws {
            if !value { throw AdvancedDocumentValidation.failure("Auditoria da edição avançada: " + message) }
        }
        func rejects(_ action: () throws -> Void) -> Bool { do { try action(); return false } catch { return true } }
        let hash = String(repeating: "a", count: 64)
        let page = ContentPageDescriptor(page: 1, width: 200, height: 300, rotation: 0)
        let box = [20.0, 30, 70, 50]
        try require(page.displayRect(box) == CGRect(x: 20, y: 30, width: 50, height: 20), "a página sem rotação deslocou o objeto")
        let rotated = ContentPageDescriptor(page: 1, width: 200, height: 300, rotation: 90)
        try require(rotated.displayRect(box) == CGRect(x: 250, y: 20, width: 20, height: 50), "a rotação de90graus não preservou a área selecionada")
        let reversed = ContentPageDescriptor(page: 1, width: 200, height: 300, rotation: 270)
        try require(reversed.displayRect(box) == CGRect(x: 30, y: 130, width: 20, height: 50), "a rotação de270graus não preservou a área selecionada")
        let item = ContentObjectDescriptor(id: "p1-text0", kind: "text", page: 1, rect: box, text: "Texto original",
            font: "Helvetica", font_size: 12, color: "#000000", editable: true, limitations: [], font_status: "original", substitution_font: nil)
        let inspection = ContentInspection(version: 1, source_sha256: hash, page_count: 1, pages: [page], objects: [item])
        let decoded = try JSONDecoder().decode(ContentInspection.self, from: JSONEncoder().encode(inspection))
        try decoded.validate(digest: hash)
        try require(rejects { try decoded.validate(digest: String(repeating: "b", count: 64)) }, "aceitou a análise de outra versão do documento")
        try require(rejects { try AdvancedDocumentValidation.rect([20, 30, 201, 50], page: 1, pages: [page]) }, "aceitou um objeto fora da página")
        try require(rejects { try AdvancedDocumentValidation.rect([20, 30, 10, 50], page: 1, pages: [page]) }, "aceitou uma largura negativa")
        var draft = ContentEditDraft(item)
        draft.text = "Parágrafo corrigido"; draft.alignment = "justify"; draft.fontSize = 16
        let payload = try draft.options(for: item, pages: [page])
        try require(payload["text"] as? String == "Parágrafo corrigido" && payload["alignment"] as? String == "justify" &&
                    payload["allow_font_substitution"] as? Bool == false, "o texto ou o consentimento de fonte mudou")
        draft.width = .infinity
        try require(rejects { _ = try draft.options(for: item, pages: [page]) }, "aceitou geometria não finita")
        let image = ContentObjectDescriptor(id: "p1-image0", kind: "image", page: 1, rect: box, text: nil, font: nil,
            font_size: nil, color: nil, editable: true, limitations: [], font_status: nil, substitution_font: nil)
        var replacement = ContentEditDraft(image); replacement.action = "replace"
        try require(rejects { _ = try replacement.options(for: image, pages: [page]) }, "aceitou substituição de imagem sem arquivo")
        replacement.action = "delete"
        let deletion = try replacement.options(for: image, pages: [page])
        try require(deletion.count == 2 && deletion["action"] as? String == "delete", "exclusão carregou parâmetros de substituição")
        let word = OCRReviewWord(id: "word-1", page: 1, rect: box, text: "a\u{301}", confidence: 0.65)
        let review = OCRReviewDocument(version: 1, source_sha256: hash, page_count: 1, pages: [page], words: [word], backend: "tesseract", language: "por")
        try review.validate(digest: hash)
        var corrections = OCRCorrectionState()
        try corrections.set("á", for: word)
        let edits = try corrections.payload(words: [word])
        try require(edits.count == 1 && Data((edits[0]["text"] as? String ?? "").utf8) == Data("á".utf8), "normalizou silenciosamente uma correção Unicode")
        try require(rejects { _ = try corrections.payload(words: []) }, "aceitou correção de outra análise")
        try require(rejects { try corrections.set("  ", for: word) }, "aceitou correção vazia")
        corrections.remove(word.id)
        try require(try corrections.payload(words: [word]).isEmpty, "restaurar o original não removeu a correção")
        let invalid = OCRReviewDocument(version: 1, source_sha256: hash, page_count: 1, pages: [page],
            words: [OCRReviewWord(id: "bad", page: 1, rect: box, text: "x", confidence: .nan)], backend: "tesseract", language: "por")
        try require(rejects { try invalid.validate(digest: hash) }, "aceitou confiança OCR inválida")
        try auditPrivateCapture()
    }

    @MainActor private static func auditPrivateCapture() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-AdvancedAudit-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let buffer = NSMutableData()
        var bounds = CGRect(x: 0, y: 0, width: 200, height: 300)
        guard let consumer = CGDataConsumer(data: buffer as CFMutableData),
              let context = CGContext(consumer: consumer, mediaBox: &bounds, nil) else {
            throw AdvancedDocumentValidation.failure("A auditoria não pôde criar a página sintética.")
        }
        context.beginPDFPage(nil)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        ("Advanced content verification" as NSString).draw(at: CGPoint(x: 10, y: 200), withAttributes: [.font: NSFont.systemFont(ofSize: 10)])
        NSGraphicsContext.restoreGraphicsState()
        context.endPDFPage(); context.closePDF()
        guard let document = PDFDocument(data: buffer as Data) else { throw AdvancedDocumentValidation.failure("A amostra não pôde ser aberta.") }
        for password in [nil, "Revisão-🔑-privada"] as [String?] {
            let data = try NativePDFSerialization.serialize(document: document, password: password)
            let source = directory.appendingPathComponent(UUID().uuidString + ".pdf")
            try NativeOutput.write(data, to: source)
            let captured = try AdvancedSourceCapture.create(source: source, password: password, cancellation: NativeCancellation())
            defer { try? FileManager.default.removeItem(at: captured.directory) }
            let copied = try Data(contentsOf: captured.url)
            let original = try Data(contentsOf: source)
            let sourceAttributes = try FileManager.default.attributesOfItem(atPath: captured.directory.path)
            let fileAttributes = try FileManager.default.attributesOfItem(atPath: captured.url.path)
            let reopened = try NativePDFSerialization.finishOpen(captured.opening)
            guard copied == data, original == data,
                  captured.digest == SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined(),
                  (sourceAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o700,
                  (fileAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o600,
                  reopened.pageCount == 1, reopened.string?.contains("Advanced content verification") == true,
                  PDFDocument(data: copied)?.isEncrypted == (password != nil) else {
                throw AdvancedDocumentValidation.failure("A captura privada alterou a origem, a proteção ou o conteúdo da página.")
            }
            let token = NativeCancellation(); token.cancel()
            var cancelled = false
            do { _ = try AdvancedSourceCapture.create(source: source, password: password, cancellation: token) }
            catch is CancellationError { cancelled = true }
            guard cancelled else { throw AdvancedDocumentValidation.failure("A captura ignorou o cancelamento anterior à leitura.") }
        }
        let fifo = directory.appendingPathComponent("source-fifo")
        guard Darwin.mkfifo(fifo.path, mode_t(0o600)) == 0 else { throw AdvancedDocumentValidation.failure("A auditoria não pôde criar o controle de arquivo irregular.") }
        var refused = false
        do { _ = try AdvancedSourceCapture.create(source: fifo, password: nil, cancellation: NativeCancellation()) }
        catch { refused = true }
        guard refused else { throw AdvancedDocumentValidation.failure("A captura aceitou um fluxo no lugar de um PDF regular.") }
    }
}
