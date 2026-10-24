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
        var failures: [String] = []
        func audit(_ phase: String, _ operation: () throws -> Void) {
            do { try check(phase, operation) }
            catch {
                let detail = (error as NSError).localizedDescription
                failures.append(detail)
                CIDiagnostics.record(detail, level: "error")
                FileHandle.standardError.write(Data(("Native check failed: " + detail + "\n").utf8))
            }
        }
        func trace(_ phase: String) {
            FileHandle.standardError.write(Data(("Native PDF fixture: " + phase + "\n").utf8))
        }

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("PDF-native-check-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        audit("Workflow presets and credentials") { try WorkflowAuditChecks.run(in: directory) }
        audit("Pages isolated copy") { try PagesPrivateCopyAuditChecks.run(in: directory) }
        audit("Capture import and orientation") { try CaptureImportAuditChecks.run(in: directory) }
        audit("Native serialization editable annotation and form roundtrips") {
            try QPDFStructuralAudit.verifyEditableRoundTrips()
        }
        audit("Native AES-256, permissions and Unicode credentials") {
            try QPDFStructuralAudit.verifyEncryptionGuards()
        }

        audit("PDFKit, capture encoding, AI text helpers and protected output") {
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
            let originalBytes = try Data(contentsOf: source)

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
            audit("Independent stream-length rejection and repair") {
                try QPDFStructuralAudit.verifyCorruptionDetection()
            }
            let copy = directory.appendingPathComponent("copy.pdf")
            let copyPrepared = try NativePDFSerialization.prepare(document: document)
            try QPDFStructuralAudit.recordRawPDFKit(copyPrepared.data, phase: "unencrypted framework serialization")
            let copyBytes = try NativePDFSerialization.finish(copyPrepared)
            try NativeOutput.write(copyBytes, to: copy)
            audit("Published native copy structural integrity") {
                try QPDFStructuralAudit.check(Data(contentsOf: copy), phase: "published unencrypted copy")
            }
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
            audit("Core Image processing") {
                let enhanced = try GPUImageProcessor.enhance(image)
                try require(enhanced.width == image.width && enhanced.height == image.height,
                            "O processamento gráfico alterou as dimensões da imagem.")
            }
            let scanned = PDFDocument()
            scanned.insert(scannedPage, at: 0)
            try require((scanned.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                        "A amostra de OCR precisa conter apenas imagem.")
            guard let scannedData = scanned.dataRepresentation() else {
                throw NSError(domain: "PDF.NativeChecks", code: 6,
                              userInfo: [NSLocalizedDescriptionKey: "Amostra de OCR inválida."])
            }
            let serializedSample = PDFDocument(data: scannedData)
            try require(serializedSample?.pageCount == 1 &&
                        (serializedSample?.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                        "A amostra serializada de OCR não pode conter uma camada de texto anterior.")
            audit("Product searchable PDF") {
                let result = try LocalOCRPDF.create(data: scannedData, language: "en", enhanceContrast: true,
                                                    cancellation: NativeCancellation()) { _, _ in }
                let recognized = PDFDocument(data: result.data)
                try require((recognized?.string ?? "").localizedCaseInsensitiveContains("verification"),
                            "O aplicativo não criou texto pesquisável na página digitalizada.")
                try require(recognized?.pageCount == 1 && result.pages.count == 1 && result.pages[0].page == 1,
                            "O OCR alterou a contagem de páginas ou perdeu a identificação da página processada.")
                let evidence = result.pages[0]
                try require(["apple-vision", "tesseract"].contains(evidence.backend),
                            "O OCR não identificou o motor real usado na página.")
                if evidence.backend == "tesseract" {
                    try require(!(evidence.fallbackReason ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                                "O OCR alternativo omitiu a falha do Vision que motivou a substituição.")
                } else {
                    try require(evidence.fallbackReason == nil, "O resultado nativo contém uma justificativa de substituição inconsistente.")
                }
                let expected = scannedPage.bounds(for: .cropBox)
                let actual = recognized?.page(at: 0)?.bounds(for: .mediaBox) ?? .zero
                try require(abs(actual.width - expected.width) < 0.01 && abs(actual.height - expected.height) < 0.01,
                            "O OCR modificou as dimensões visíveis da página.")
                guard let outputPage = recognized?.page(at: 0),
                      let selection = recognized?.findString("verification", withOptions: .caseInsensitive).first else {
                    throw NSError(domain: "PDF.NativeChecks", code: 9,
                                  userInfo: [NSLocalizedDescriptionKey: "O texto reconhecido não pôde ser localizado na página de saída."])
                }
                let selectionBounds = selection.bounds(for: outputPage)
                try require(selectionBounds.minY > actual.height / 2 &&
                            actual.insetBy(dx: -1, dy: -1).contains(selectionBounds),
                            "A camada de texto pesquisável foi posicionada fora do texto visível da amostra.")
                FileHandle.standardOutput.write(Data(("Product OCR page 1 backend: \(evidence.backend)\n").utf8))
            }
            audit("Tesseract installed runtime and transport") {
                try TesseractPageAuditChecks.run()
                let normalized = try VisionRecognition.canonicalImage(image)
                // The helper exercises English; this original fixture also
                // contains Portuguese and exercises the UI's primary language.
                let result = try TesseractPageRecognizer.recognizePage(normalized, language: "pt", cancellation: NativeCancellation())
                try require(result.backend == "tesseract" && result.language == "pt" &&
                            result.width == normalized.width && result.height == normalized.height,
                            "O Tesseract instalado perdeu os metadados da página, idioma ou motor.")
                try require(result.observations.contains { $0.string.localizedCaseInsensitiveContains("verification") },
                            "O Tesseract instalado não reconheceu o texto real da amostra.")
                try VisionTextObservation.validate(result.observations)
                // The fixture puts the known text near the top, at y=720/842.
                // This independent check catches a top-left/bottom-left mixup
                // even when a syntactically valid normalized box is returned.
                try require(result.observations.contains {
                    $0.string.localizedCaseInsensitiveContains("verification") && $0.boundingBox.minY > 0.5
                }, "As coordenadas do texto reconhecido não correspondem à posição real na página.")
                FileHandle.standardOutput.write(Data("Direct OCR backend: tesseract; language: pt\n".utf8))
            }

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
            trace("AI PDF export begin")
            let exported = try IntelligenceText.PDF("Resumo de teste com ação e conteúdo em português.")
            try require((PDFDocument(data: exported)?.string ?? "").contains("Resumo de teste"),
                        "Exportação do resultado de IA para PDF falhou.")
            trace("AI PDF export and reopen end")
            trace("capture PDF import begin")
            let importedPDF = try ContinuityCaptureFile.save(exported, isPDF: true, directory: directory)
            try require(PDFDocument(url: importedPDF)?.pageCount == 1, "Importação de captura PDF falhou.")
            trace("capture PDF import and reopen end")
            guard let imageData = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
                throw NSError(domain: "PDF.NativeChecks", code: 7,
                              userInfo: [NSLocalizedDescriptionKey: "Não foi possível codificar a captura de teste."])
            }
            trace("capture image import begin")
            let importedImage = try ContinuityCaptureFile.save(imageData, isPDF: false, directory: directory)
            try require(NSImage(contentsOf: importedImage) != nil, "Importação de captura de imagem falhou.")
            trace("capture image import and reopen end")
            var refusedInvalidCapture = false
            trace("invalid capture rejection begin")
            do { _ = try ContinuityCaptureFile.save(Data("not a PDF".utf8), isPDF: true, directory: directory) }
            catch { refusedInvalidCapture = true }
            try require(refusedInvalidCapture, "Uma captura PDF inválida foi aceita.")
            trace("invalid capture rejection end")

            let password = "native-check-reader-123"
            trace("protected serialize begin")
            let protectedPrepared = try NativePDFSerialization.prepare(document: restored, password: password)
            try QPDFStructuralAudit.recordRawPDFKit(protectedPrepared.data, password: password,
                                                    phase: "encrypted framework serialization")
            let protectedData = try NativePDFSerialization.finish(protectedPrepared)
            trace("protected serialize end")
            let protectedFile = directory.appendingPathComponent("protected-copy.pdf")
            try NativeOutput.write(protectedData, to: protectedFile)
            audit("Published protected copy structural integrity") {
                try QPDFStructuralAudit.check(Data(contentsOf: protectedFile), password: password,
                                              phase: "published protected copy")
                try QPDFStructuralAudit.verifyAES256(Data(contentsOf: protectedFile), password: password)
            }
            trace("protected open begin")
            guard let protectedCopy = PDFDocument(data: protectedData) else {
                throw NSError(domain: "PDF.NativeChecks", code: 8,
                              userInfo: [NSLocalizedDescriptionKey: "A cópia PDFKit protegida não pôde ser aberta."])
            }
            trace("protected open end")
            try require(protectedCopy.isEncrypted && protectedCopy.isLocked, "A cópia nativa perdeu a proteção.")
            trace("protected empty-password rejection begin")
            try require(!protectedCopy.unlock(withPassword: ""), "A cópia nativa aceitou senha vazia.")
            trace("protected empty-password rejection end")
            trace("protected unlock begin")
            try require(protectedCopy.unlock(withPassword: password), "A senha da cópia nativa não funciona.")
            trace("protected unlock end")
            trace("protected content integrity begin")
            try require(!protectedCopy.isLocked && protectedCopy.pageCount == 1 &&
                        (protectedCopy.string ?? "").contains("PDF native verification"),
                        "A cópia protegida perdeu páginas ou texto após desbloquear.")
            try require(protectedCopy.page(at: 0)?.annotations.count == 2,
                        "A cópia protegida perdeu anotações após desbloquear.")
            try require(protectedCopy.page(at: 0)?.annotations.contains {
                $0.fieldName == "native-test" && $0.widgetStringValue == "PDF"
            } == true, "A cópia protegida perdeu o campo preenchido após desbloquear.")
            trace("protected content integrity end")
            audit("Native serialization fidelity and encryption guards") {
                try QPDFStructuralAudit.verifyFidelityGuards(copy: copyBytes, prepared: copyPrepared,
                                                            protected: protectedData, protectedPrepared: protectedPrepared)
            }
            audit("Native serialization private process and cancellation") {
                try QPDFStructuralAudit.verifyProcessGuards(prepared: protectedPrepared, password: password)
            }
            let sourceAfterSerialization = try Data(contentsOf: source)
            try require(sourceAfterSerialization == originalBytes, "A gravação de cópias modificou o PDF original.")
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
        audit("Tool presets") { try ToolPresetAuditChecks.run() }
        audit("Native regression audit") { try NativeAuditChecks.run() }
        audit("Appearance and reader preferences") { try AppearanceAuditChecks.run() }
        audit("Recovery storage and encryption") { try RecoveryAuditChecks.run() }
        audit("Reader sessions and annotation editing") { try SessionAnnotationAuditChecks.run() }
        audit("Semantic retrieval and verifiable citations") { try SemanticAuditChecks.run() }
        audit("Performance measurement harness") { try BenchmarkAuditChecks.run() }
        print("Native checks hardware: \(AppleHardware.summary)")
        guard failures.isEmpty else {
            throw NSError(domain: "PDF.NativeChecks", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "Falharam \(failures.count) grupos de verificação nativa:\n" + failures.joined(separator: "\n")])
        }
    }
}
