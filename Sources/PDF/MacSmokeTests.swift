import AppKit
import CoreGraphics
import PDFKit

/// Executed by the installer and CI on macOS before a build is activated.
@MainActor
enum MacSmokeTests {
    static func run() throws {
        _ = NSApplication.shared
        func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            guard condition() else {
                throw NSError(domain: "PDF.NativeChecks", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: message])
            }
        }

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("PDF-native-check-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let source = directory.appendingPathComponent("source.pdf")
        var bounds = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let context = CGContext(source as CFURL, mediaBox: &bounds, nil) else {
            throw NSError(domain: "PDF.NativeChecks", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Não foi possível criar o PDF de teste."])
        }
        context.beginPDFPage(nil)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        ("PDF native verification — ação" as NSString).draw(
            at: NSPoint(x: 72, y: 720),
            withAttributes: [.font: NSFont.systemFont(ofSize: 18), .foregroundColor: NSColor.black])
        NSGraphicsContext.restoreGraphicsState()
        context.endPDFPage()
        context.closePDF()

        guard let document = PDFDocument(url: source), let page = document.page(at: 0) else {
            throw NSError(domain: "PDF.NativeChecks", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "PDFKit não abriu o PDF gerado."])
        }
        try require(document.pageCount == 1, "Contagem de páginas incorreta.")
        try require((document.string ?? "").contains("PDF native verification"), "Extração de texto falhou.")
        try require(!document.findString("verification", withOptions: .caseInsensitive).isEmpty,
                    "Busca de texto falhou.")

        let annotation = PDFAnnotation(bounds: CGRect(x: 72, y: 700, width: 120, height: 24),
                                       forType: .highlight, withProperties: nil)
        annotation.color = .systemYellow
        page.addAnnotation(annotation)
        let field = PDFAnnotation(bounds: CGRect(x: 72, y: 620, width: 200, height: 30),
                                  forType: .widget, withProperties: nil)
        field.widgetFieldType = .text
        field.fieldName = "native-test"
        field.widgetStringValue = "PDF"
        page.addAnnotation(field)
        let copy = directory.appendingPathComponent("copy.pdf")
        try require(document.write(to: copy), "Gravação de cópia falhou.")
        guard let restored = PDFDocument(url: copy), let restoredPage = restored.page(at: 0) else {
            throw NSError(domain: "PDF.NativeChecks", code: 4,
                          userInfo: [NSLocalizedDescriptionKey: "Cópia não pôde ser reaberta."])
        }
        try require(restoredPage.annotations.count == 2, "Anotações não persistiram.")
        try require(restoredPage.annotations.contains { $0.fieldName == "native-test" && $0.widgetStringValue == "PDF" },
                    "Campo de formulário não persistiu.")
        let thumbnail = restoredPage.thumbnail(of: NSSize(width: 120, height: 170), for: .mediaBox)
        try require(thumbnail.size.width > 0 && thumbnail.size.height > 0, "Renderização de miniatura falhou.")
        let reader = PDFView(frame: NSRect(x: 0, y: 0, width: 800, height: 600))
        reader.document = restored
        reader.autoScales = true
        try require(reader.document?.pageCount == 1, "O leitor não recebeu o documento.")

        let raster = page.thumbnail(of: NSSize(width: 1190, height: 1684), for: .mediaBox)
        guard let image = raster.cgImage(forProposedRect: nil, context: nil, hints: nil),
              let scannedPage = PDFPage(image: raster) else {
            throw NSError(domain: "PDF.NativeChecks", code: 5,
                          userInfo: [NSLocalizedDescriptionKey: "Não foi possível criar uma página digitalizada de teste."])
        }
        let enhanced = try GPUImageProcessor.enhance(image)
        try require(enhanced.width == image.width && enhanced.height == image.height,
                    "O processamento gráfico alterou as dimensões da imagem.")
        let scanned = PDFDocument()
        scanned.insert(scannedPage, at: 0)
        try require((scanned.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                    "A amostra de OCR precisa conter apenas imagem.")
        guard let scannedData = scanned.dataRepresentation() else {
            throw NSError(domain: "PDF.NativeChecks", code: 6,
                          userInfo: [NSLocalizedDescriptionKey: "Amostra de OCR inválida."])
        }
        let recognizedData = try VisionPDF.create(data: scannedData, language: "en", enhanceContrast: true,
                                                  cancellation: NativeCancellation()) { _, _ in }
        let recognized = PDFDocument(data: recognizedData)
        try require((recognized?.string ?? "").localizedCaseInsensitiveContains("verification"),
                    "Vision não criou texto pesquisável na página digitalizada.")

        let chunks = IntelligenceText.chunks("Primeiro parágrafo\nSegundo parágrafo", limit: 20)
        try require(chunks.count == 2 && chunks.allSatisfy { $0.count <= 20 },
                    "Divisão do documento para IA inválida.")
        let exported = try IntelligenceText.PDF("Resumo de teste com ação e conteúdo em português.")
        try require((PDFDocument(data: exported)?.string ?? "").contains("Resumo de teste"),
                    "Exportação do resultado de IA para PDF falhou.")
        let importedPDF = try ContinuityCaptureFile.save(exported, isPDF: true, directory: directory)
        try require(PDFDocument(url: importedPDF)?.pageCount == 1, "Importação de captura PDF falhou.")
        guard let imageData = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
            throw NSError(domain: "PDF.NativeChecks", code: 7,
                          userInfo: [NSLocalizedDescriptionKey: "Não foi possível codificar a captura de teste."])
        }
        let importedImage = try ContinuityCaptureFile.save(imageData, isPDF: false, directory: directory)
        try require(NSImage(contentsOf: importedImage) != nil, "Importação de captura de imagem falhou.")
        var refusedInvalidCapture = false
        do { _ = try ContinuityCaptureFile.save(Data("not a PDF".utf8), isPDF: true, directory: directory) }
        catch { refusedInvalidCapture = true }
        try require(refusedInvalidCapture, "Uma captura PDF inválida foi aceita.")

        let protectedOptions: [AnyHashable: Any] = [
            AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): "native-check-owner-123",
            AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): "native-check-reader-123"
        ]
        guard let protectedData = restored.dataRepresentation(options: protectedOptions),
              let protectedCopy = PDFDocument(data: protectedData) else {
            throw NSError(domain: "PDF.NativeChecks", code: 8,
                          userInfo: [NSLocalizedDescriptionKey: "A exportação PDFKit protegida falhou."])
        }
        try require(protectedCopy.isEncrypted && protectedCopy.isLocked, "A cópia nativa perdeu a proteção.")
        try require(!protectedCopy.unlock(withPassword: ""), "A cópia nativa aceitou senha vazia.")
        try require(protectedCopy.unlock(withPassword: "native-check-reader-123"), "A senha da cópia nativa não funciona.")
        let atomic = directory.appendingPathComponent("atomic.txt")
        try NativeOutput.write(Data("original".utf8), to: atomic)
        var refusedOverwrite = false
        do {
            try NativeOutput.write(Data("replacement".utf8), to: atomic)
        } catch {
            refusedOverwrite = true
        }
        let retained = try String(contentsOf: atomic, encoding: .utf8)
        try require(refusedOverwrite && retained == "original", "A publicação não preservou o arquivo existente.")
    }
}
