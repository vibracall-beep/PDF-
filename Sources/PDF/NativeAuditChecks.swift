import AppKit
import PDFKit
import ImageIO
import UniformTypeIdentifiers

/// Regression checks for native file publication, reader preferences and scan assembly.
/// Invoked by the macOS smoke runner; hardware acquisition and model generation remain manual.
@MainActor enum NativeAuditChecks {
    static func run() throws {
        func require(_ value: @autoclosure () -> Bool, _ message: String) throws {
            guard value() else { throw NSError(domain: "PDF.NativeAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func rejects(_ operation: () throws -> Void) -> Bool {
            do { try operation(); return false } catch { return true }
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-audit-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }

        let name = OutputFilename.make(template: "{original}/{ferramenta}.pdf.pdf", prefix: "legacy", original: "Contrato.pdf", tool: "OCR", suffix: "pdf")
        try require(name == "Contrato-OCR.pdf", "O modelo de nome não sanitizou separadores ou repetiu a extensão.")
        let literal = OutputFilename.make(template: "{original}-{ferramenta}", prefix: "legacy", original: "{ferramenta}.pdf", tool: "Girar", suffix: "pdf")
        try require(literal == "{ferramenta}-Girar.pdf", "Tokens dentro do nome de origem foram expandidos novamente.")
        try require(OutputFilename.make(template: nil, prefix: "Meu-PDF", original: "a.pdf", tool: "PDF", suffix: "pdf") == "Meu-PDF.pdf", "O prefixo existente não foi preservado.")
        let longName = OutputFilename.make(template: String(repeating: "ação", count: 200), prefix: "PDF", original: "a.pdf", tool: "PDF", suffix: "pdf")
        try require(longName.utf8.count <= 184, "O nome final excedeu o limite seguro de componente UTF-8.")

        let atomic = directory.appendingPathComponent("private.txt")
        try NativeOutput.write(Data("private".utf8), to: atomic)
        let attributes = try FileManager.default.attributesOfItem(atPath: atomic.path)
        let mode = (attributes[.posixPermissions] as? NSNumber)?.intValue ?? 0
        try require(mode & 0o077 == 0, "A publicação nativa concedeu acesso a outros usuários.")
        try require(rejects { try NativeOutput.write(Data("replaced".utf8), to: atomic) }, "A publicação substituiu um arquivo existente.")
        let retained = try String(contentsOf: atomic, encoding: .utf8)
        try require(retained == "private", "A tentativa de sobrescrita alterou o arquivo original.")
        let leftovers = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        try require(!leftovers.contains(where: { $0.hasPrefix(".pdf-") }), "A publicação deixou arquivo temporário após falha.")

        guard let bitmap = CGContext(data: nil, width: 64, height: 96, bitsPerComponent: 8, bytesPerRow: 64 * 4,
                                     space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else {
            throw NSError(domain: "PDF.NativeAudit", code: 2)
        }
        bitmap.setFillColor(CGColor(red: 0.1, green: 0.4, blue: 0.8, alpha: 1)); bitmap.fill(CGRect(x: 0, y: 0, width: 64, height: 96))
        guard let image = bitmap.makeImage() else { throw NSError(domain: "PDF.NativeAudit", code: 3) }
        let tiff = directory.appendingPathComponent("two-pages.tiff")
        guard let destination = CGImageDestinationCreateWithURL(tiff as CFURL, UTType.tiff.identifier as CFString, 2, nil) else {
            throw NSError(domain: "PDF.NativeAudit", code: 4)
        }
        CGImageDestinationAddImage(destination, image, nil)
        CGImageDestinationAddImage(destination, image, [kCGImagePropertyOrientation: 6] as CFDictionary)
        try require(CGImageDestinationFinalize(destination), "Não foi possível criar TIFF de teste.")
        let assembled = try ScannerPDF.assemble(urls: [tiff], cancellation: NativeCancellation()) { _, _ in }
        guard let document = PDFDocument(data: assembled), let second = document.page(at: 1) else {
            throw NSError(domain: "PDF.NativeAudit", code: 5, userInfo: [NSLocalizedDescriptionKey: "A montagem omitiu a segunda página TIFF."])
        }
        try require(document.pageCount == 2, "A montagem do scanner perdeu uma página TIFF.")
        try require(second.bounds(for: .mediaBox).width > second.bounds(for: .mediaBox).height, "A orientação EXIF da segunda captura foi ignorada.")
        let token = NativeCancellation(); token.cancel()
        try require(rejects { _ = try ScannerPDF.assemble(urls: [tiff], cancellation: token) { _, _ in } }, "A montagem ignorou cancelamento prévio.")
        try require(rejects { _ = try GPUImageProcessor.enhance(image, contrast: .nan) }, "O filtro gráfico aceitou contraste não finito.")
        let enhanced = try GPUImageProcessor.enhance(image)
        try require(enhanced.width == image.width && enhanced.height == image.height && enhanced.bitsPerComponent == 8 && enhanced.bitsPerPixel == 32 && enhanced.colorSpace?.model == .rgb,
                    "O processamento não produziu a imagem RGB de 8 bits e resolução preservada exigida pelo OCR.")

        let protected = directory.appendingPathComponent("protected.pdf")
        let options: [AnyHashable: Any] = [AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): "audit-reader-123",
                                         AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): "audit-owner-123"]
        guard let bytes = document.dataRepresentation(options: options) else { throw NSError(domain: "PDF.NativeAudit", code: 6) }
        try NativeOutput.write(bytes, to: protected)
        try require(rejects { _ = try ScannerPDF.assemble(urls: [protected], cancellation: NativeCancellation()) { _, _ in } }, "A importação do scanner aceitou um PDF protegido sem senha.")

        let reader = PDFView(frame: CGRect(x: 0, y: 0, width: 800, height: 600)); reader.document = document
        let settings = ReaderSettings(mode: 1, direction: "horizontal", box: "media", background: "#123456", autoScale: false, zoom: 1.25, pageBreaks: false)
        settings.apply(to: reader, previous: nil, changedDocument: true)
        try require(reader.displayMode == .singlePage && reader.displayDirection == .horizontal && reader.displayBox == .mediaBox && !reader.displaysPageBreaks,
                    "As preferências do leitor não foram aplicadas ao PDFKit.")
        reader.scaleFactor = 1.5
        let manual = reader.scaleFactor
        settings.apply(to: reader, previous: settings, changedDocument: false)
        try require(abs(reader.scaleFactor - manual) < 0.001, "Uma atualização sem mudanças redefiniu o zoom manual.")

        try require(IntelligenceText.sourcePage(in: "[Página 3]\nTexto [Página 99]") == 3, "Texto do documento alterou a página de origem.")
        try require(IntelligenceText.sourcePage(in: "[Página -1]\nTexto") == nil, "Uma referência inválida foi aceita.")
        let context = IntelligenceText.context(from: ["Sem metadado", "[Página 2]\nConteúdo"], budget: 300)
        try require(context.pages == [2] && !context.text.contains("Sem metadado"), "Um trecho sem origem foi tratado como evidência.")
        try require(rejects { _ = try IntelligenceText.validatedResponse("   \n") }, "Uma tradução vazia poderia substituir conteúdo.")
        try require(rejects { _ = try IntelligenceText.PDF("  ") }, "Uma exportação sem texto produziu PDF vazio.")
        let searchModel = Workspace()
        searchModel.document = PDFDocument(data: try IntelligenceText.PDF("Auditoria primeira ocorrência. Auditoria segunda ocorrência."))
        reader.document = searchModel.document; searchModel.pdfView = reader
        searchModel.search("Auditoria")
        let deadline = Date().addingTimeInterval(10)
        while searchModel.searching, Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
        try require(!searchModel.searching && searchModel.message == "Ocorrência 1 de 2", "A busca assíncrona não terminou com as ocorrências esperadas.")
        searchModel.search("Auditoria")
        try require(searchModel.message == "Ocorrência 2 de 2", "A busca não avançou para a próxima ocorrência.")
        searchModel.search("Auditoria")
        try require(searchModel.message == "Ocorrência 1 de 2", "A busca não retornou ao início após a última ocorrência.")
        searchModel.cancelSearch()
        // Exercise the same annotation methods used by toolbar actions and pointer strokes.
        guard let annotationPage = searchModel.document?.page(at: 0) else { throw NSError(domain: "PDF.NativeAudit", code: 7) }
        annotationPage.setBounds(CGRect(x: 10, y: 20, width: 560, height: 800), for: .cropBox)
        guard let selection = searchModel.document?.findString("Auditoria", withOptions: .caseInsensitive).first else {
            throw NSError(domain: "PDF.NativeAudit", code: 9, userInfo: [NSLocalizedDescriptionKey: "A amostra não contém texto selecionável para realçar."])
        }
        reader.setCurrentSelection(selection, animate: false)
        try require(reader.currentSelection != nil, "O leitor não reteve a seleção necessária ao realce.")
        searchModel.highlight(colorHex: "#11AA33")
        searchModel.addNote("Nota personalizada", colorHex: "#8844AA")
        let inkView = DrawingPDFView(frame: CGRect(x: 0, y: 0, width: 800, height: 600))
        inkView.document = searchModel.document; inkView.inkColor = ReaderAnnotationStyle.color("#2255CC", fallback: "#007AFF"); inkView.inkWidth = 7.5
        inkView.beginStroke(on: annotationPage, at: NSPoint(x: 40, y: 50))
        inkView.extendStroke(to: NSPoint(x: 100, y: 120)); inkView.finishStroke()
        let createdTypes = annotationPage.annotations.map { $0.type ?? "nil" }.joined(separator: ", ")
        try require(annotationPage.annotations.contains { PDFAnnotationKind.matches($0, .highlight) }, "O comando de realce não criou a anotação; tipos presentes: \(createdTypes).")
        guard let annotatedData = searchModel.document?.dataRepresentation(), let reopenedDocument = PDFDocument(data: annotatedData), let reopened = reopenedDocument.page(at: 0) else {
            throw NSError(domain: "PDF.NativeAudit", code: 8)
        }
        func matches(_ color: NSColor, hex: String) -> Bool {
            guard let actual = color.usingColorSpace(.sRGB), let expected = ReaderAnnotationStyle.color(hex, fallback: hex).usingColorSpace(.sRGB) else { return false }
            return abs(actual.redComponent - expected.redComponent) < 0.015 && abs(actual.greenComponent - expected.greenComponent) < 0.015 && abs(actual.blueComponent - expected.blueComponent) < 0.015
        }
        let highlight = reopened.annotations.first { PDFAnnotationKind.matches($0, .highlight) }
        let note = reopened.annotations.first { PDFAnnotationKind.matches($0, .text) }
        let ink = reopened.annotations.first { PDFAnnotationKind.matches($0, .ink) }
        let serializedTypes = reopened.annotations.map { $0.type ?? "nil" }.joined(separator: ", ")
        try require(highlight != nil && note != nil && ink != nil, "Uma anotação não foi identificada após reabrir; tipos: \(serializedTypes); constante de realce: \(PDFAnnotationSubtype.highlight.rawValue).")
        try require(highlight.map { matches($0.color, hex: "#11AA33") } == true, "A cor personalizada do realce não persistiu no PDF; cor recebida: \(highlight?.color.description ?? "ausente").")
        try require(note.map { matches($0.color, hex: "#8844AA") && $0.contents == "Nota personalizada" } == true, "A nota perdeu a cor ou o conteúdo personalizados.")
        try require(ink.map { matches($0.color, hex: "#2255CC") && abs(($0.border?.lineWidth ?? 0) - 7.5) < 0.01 && !($0.paths ?? []).isEmpty } == true,
                    "O traço desenhado não preservou a cor, espessura ou caminho no PDF.")
        try require(ReaderAnnotationStyle.width(.nan) == 2.5 && ReaderAnnotationStyle.width(100) == 20 && ReaderAnnotationStyle.width(0) == 0.5, "Espessuras inválidas não receberam limites seguros.")
        try require(PDFAnnotationKind.normalizedName("/Highlight") == PDFAnnotationKind.normalizedName("Highlight") && PDFAnnotationKind.normalizedName(nil) == nil,
                    "A identificação dos tipos não normalizou o prefixo de nome PDF.")
        try require(!PDFAnnotationKind.matches(PDFAnnotation(bounds: .zero, forType: .link, withProperties: nil), .highlight), "A identificação aceitou um tipo diferente.")
        print("Native audit: naming, private atomic publication, TIFF pages/orientation, protected imports, cancellation, reader settings, AI source metadata passed")
    }
}
