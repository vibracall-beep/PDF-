import AppKit
import CoreGraphics
import PDFKit

/// Structured CI diagnostics complement the full logs. Only explicit CLI
/// validation phases use these annotations; normal application use is unchanged.
enum CIDiagnostics {
    static func record(_ message:String, level:String = "notice", title:String = "PDF native validation") {
        guard ProcessInfo.processInfo.environment["GITHUB_ACTIONS"] == "true" else { return }
        func escaped(_ value:String) -> String {
            String(value.prefix(4000)).replacingOccurrences(of:"%",with:"%25")
                .replacingOccurrences(of:"\r",with:"%0D").replacingOccurrences(of:"\n",with:"%0A")
        }
        let kind = level == "error" ? "error" : "notice"
        FileHandle.standardError.write(Data(("::\(kind) title=\(title)::\(escaped(message))\n").utf8))
    }
}

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
        func check<T>(_ phase:String, _ operation:() throws -> T) throws -> T {
            CIDiagnostics.record("Starting: " + phase)
            FileHandle.standardOutput.write(Data(("Native check starting: " + phase + "\n").utf8))
            do {
                let value = try operation()
                FileHandle.standardOutput.write(Data(("Native check passed: " + phase + "\n").utf8))
                return value
            } catch {
                let detail = error as NSError
                throw NSError(domain:"PDF.NativeChecks.Phase",code:detail.code,userInfo:[NSLocalizedDescriptionKey:phase + ": " + detail.localizedDescription + " (" + detail.domain + ", " + String(detail.code) + ")",NSUnderlyingErrorKey:detail])
            }
        }

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("PDF-native-check-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try check("Workflow presets and credentials") { try WorkflowAuditChecks.run(in: directory) }
        try check("Pages isolated copy") { try PagesPrivateCopyAuditChecks.run(in: directory) }
        try check("Capture import and orientation") { try CaptureImportAuditChecks.run(in: directory) }

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
        let enhanced = try check("Core Image processing") { try GPUImageProcessor.enhance(image) }
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
        let recognizedData = try check("Vision searchable PDF") {
            try VisionPDF.create(data: scannedData, language: "en", enhanceContrast: true,
                                 cancellation: NativeCancellation()) { _, _ in }
        }
        let recognized = PDFDocument(data: recognizedData)
        try require((recognized?.string ?? "").localizedCaseInsensitiveContains("verification"),
                    "Vision não criou texto pesquisável na página digitalizada.")

        let chunks = IntelligenceText.chunks("Primeiro parágrafo\nSegundo parágrafo", limit: 20)
        try require(chunks.count == 2 && chunks.allSatisfy { $0.count <= 20 },
                    "Divisão do documento para IA inválida.")
        let excerpts = ["[Página 1]\nAs receitas anuais foram de 120 mil reais.",
                        "[Página 2]\nO prazo contratual termina em dezembro de 2028."]
        let retrievedContext = IntelligenceText.retrieve(question: "Qual o prazo contratual?", chunks: excerpts)
        try require(retrievedContext.pages.contains(2) && retrievedContext.text.contains("dezembro de 2028"),
                    "A busca de contexto não preservou a página da evidência.")
        let bounded = IntelligenceText.context(from: ["[Página 8]\n" + String(repeating: "conteúdo ", count: 400)], budget: 300)
        try require(bounded.text.count <= 300 && bounded.pages == [8],
                    "O contexto da IA excedeu o limite ou perdeu a referência de página.")
        let unrelated = IntelligenceText.retrieve(question: "Qual a órbita de Netuno?",
            chunks: ["[Página 1]\n" + String(repeating: "Receitas e despesas anuais. ", count: 400)])
        try require(unrelated.text.isEmpty && unrelated.pages.isEmpty,
                    "A busca atribuiu evidência a um documento sem contexto correspondente.")
        let quiz = PDFQuizQuestion(question: "Em que mês termina o prazo?",
                                   options: ["Março", "Junho", "Setembro", "Dezembro"],
                                   answer: "D", explanation: "A página 2 informa dezembro de 2028.", pages: [2])
        try quiz.validate(allowedPages: [2], multipleChoice: true)
        let invalidQuizzes = [
            PDFQuizQuestion(question: quiz.question, options: ["Ação", " acao ", "Terceira", "Quarta"],
                            answer: "A", explanation: quiz.explanation, pages: [2]),
            PDFQuizQuestion(question: quiz.question, options: quiz.options,
                            answer: "D", explanation: quiz.explanation, pages: [99]),
            PDFQuizQuestion(question: "   ", options: quiz.options,
                            answer: "D", explanation: quiz.explanation, pages: [2])
        ]
        for invalidQuiz in invalidQuizzes {
            var rejected = false
            do { try invalidQuiz.validate(allowedPages: [2], multipleChoice: true) }
            catch { rejected = true }
            try require(rejected, "Uma questão com conteúdo ou referências inválidas foi aceita.")
        }
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
        try check("Tool presets") { try ToolPresetAuditChecks.run() }
        try check("Native regression audit") { try NativeAuditChecks.run() }
        try check("Appearance and reader preferences") { try AppearanceAuditChecks.run() }
        try check("Recovery storage and encryption") { try RecoveryAuditChecks.run() }
        try check("Reader sessions and annotation editing") { try SessionAnnotationAuditChecks.run() }
        try check("Semantic retrieval and verifiable citations") { try SemanticAuditChecks.run() }
        try check("Performance measurement harness") { try BenchmarkAuditChecks.run() }
        print("Native checks hardware: \(AppleHardware.summary)")
    }
}
