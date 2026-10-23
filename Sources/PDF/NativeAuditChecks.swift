import AppKit
import PDFKit
import ImageIO
import UniformTypeIdentifiers
import Vision
import Darwin

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
        let rgba = Data([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255])
        guard let rgbaProvider = CGDataProvider(data: rgba as CFData), let rgbSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let sample = CGImage(width: 2, height: 2, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: 8,
                                   space: rgbSpace, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue),
                                   provider: rgbaProvider, decode: nil, shouldInterpolate: false, intent: .defaultIntent) else {
            throw NSError(domain: "PDF.NativeAudit", code: 10)
        }
        let canonical = try VisionRecognition.canonicalImage(sample)
        guard let materialized = canonical.dataProvider?.data else { throw NSError(domain: "PDF.NativeAudit", code: 11) }
        try require(canonical.width == 2 && canonical.height == 2 && canonical.bitsPerComponent == 8 && canonical.bitsPerPixel == 32 &&
                    canonical.alphaInfo == .premultipliedLast && canonical.bitmapInfo.contains(.byteOrder32Big),
                    "A normalização de OCR não produziu o formato RGBA explícito.")
        try require((materialized as Data) == rgba, "A preparação de pixels alterou as cores ou orientação da amostra de OCR.")
        // Retry only execution failures. A generic Foundation wrapper must not
        // hide cancellation, invalid images or exhausted memory and repeat work.
        let generic = NSError(domain: "Foundation._GenericObjCError", code: 0)
        try require(!VisionRecognition.shouldRetryOnCPU(generic) && VisionRecognition.shouldRetryOnCPU(VisionExecutionFailure(underlying: generic)),
                    "O retry de compatibilidade não distinguiu execução de configuração.")
        for code in [VNErrorCode.requestCancelled, .invalidImage, .invalidArgument, .outOfMemory] {
            let cause = NSError(domain: VNErrorDomain, code: code.rawValue)
            let wrapped = NSError(domain: "Foundation._GenericObjCError", code: 0, userInfo: [NSUnderlyingErrorKey: cause])
            try require(!VisionRecognition.shouldRetryOnCPU(VisionExecutionFailure(underlying: wrapped)),
                        "O retry de OCR ignorou cancelamento ou erro definitivo na cadeia de causas.")
        }
        let executionFailure = NSError(domain: "TextRecognition.CRImageReaderError", code: 9)
        try require(VisionRecognition.shouldRetryOnCPU(VisionExecutionFailure(underlying: executionFailure)) &&
                    !VisionRecognition.shouldRetryOnCPU(VisionExecutionFailure(underlying: CancellationError())),
                    "O retry de OCR não respeitou o erro de execução observado ou o cancelamento.")
        let textObservation = VisionTextObservation(string: "Ação 中文\nlinha 2", boundingBox: CGRect(x: 0.1, y: 0.2, width: 0.3, height: 0.4), confidence: 0.91)
        let workerResponse = VisionWorker.Response(language: "pt", width: 64, height: 96, observations: [textObservation], error: nil)
        let workerBytes = try JSONEncoder().encode(workerResponse)
        let decodedWorker = try JSONDecoder().decode(VisionWorker.Response.self, from: workerBytes)
        let restoredWorker = try VisionWorker.validateResponse(decodedWorker, language: "pt", width: 64, height: 96, successfulExit: true)
        try require(restoredWorker.count == 1 && restoredWorker[0].string == textObservation.string && restoredWorker[0].boundingBox == textObservation.boundingBox && restoredWorker[0].confidence == textObservation.confidence,
                    "O transporte privado de OCR perdeu Unicode, ordem do texto, geometria ou confiança.")
        try require(rejects { _ = try VisionWorker.validateResponse(decodedWorker, language: "en", width: 64, height: 96, successfulExit: true) } &&
                    rejects { _ = try VisionWorker.validateResponse(decodedWorker, language: "pt", width: 65, height: 96, successfulExit: true) } &&
                    rejects { _ = try VisionWorker.validateResponse(decodedWorker, language: "pt", width: 64, height: 96, successfulExit: false) },
                    "O transporte aceitou idioma, dimensões ou término do processo incorretos.")
        var incompatibleWorker = decodedWorker; incompatibleWorker.version = 2
        try require(rejects { _ = try VisionWorker.validateResponse(incompatibleWorker, language: "pt", width: 64, height: 96, successfulExit: true) }, "O transporte aceitou uma versão desconhecida.")
        let errorWorker = VisionWorker.Response(language: "pt", width: 64, height: 96, observations: [], error: "Falha real")
        try require(rejects { _ = try VisionWorker.validateResponse(errorWorker, language: "pt", width: 64, height: 96, successfulExit: true) }, "Uma falha do OCR foi tratada como página vazia.")
        // Only a matching, normally exited child can attest a runtime failure.
        // Neither a malformed envelope nor the wording of an error permits the
        // product to silently change OCR engines.
        func attestsRuntime(_ response: VisionWorker.Response, successfulExit: Bool = false,
                            runtimeFailureExit: Bool = true) -> Bool {
            do {
                _ = try VisionWorker.validateResponse(response, language: "pt", width: 64, height: 96,
                    successfulExit: successfulExit, runtimeFailureExit: runtimeFailureExit)
                return false
            } catch is VisionWorker.RuntimeFailure { return true }
            catch { return false }
        }
        let runtimeResponse = VisionWorker.Response(language: "pt", width: 64, height: 96, observations: nil,
            error: "Foundation._GenericObjCError (0)", runtimeFailure: true)
        let runtimeBytes = try JSONEncoder().encode(runtimeResponse)
        let decodedRuntime = try JSONDecoder().decode(VisionWorker.Response.self, from: runtimeBytes)
        try require(attestsRuntime(decodedRuntime), "O transporte perdeu a classificação de falha real do runtime.")
        try require(!attestsRuntime(decodedRuntime, successfulExit: true) &&
                    !attestsRuntime(decodedRuntime, runtimeFailureExit: false),
                    "Um status de sucesso, sinal ou término inválido autorizou outro motor OCR.")
        var runtimeVersionMismatch = decodedRuntime; runtimeVersionMismatch.version = 2
        let falseRuntimeResponses = [
            VisionWorker.Response(language: "pt", width: 64, height: 96, observations: nil, error: "Foundation._GenericObjCError (0)"),
            VisionWorker.Response(language: "pt", width: 64, height: 96, observations: nil, error: "Falha", runtimeFailure: false),
            VisionWorker.Response(language: "pt", width: 64, height: 96, observations: [], error: "Falha", runtimeFailure: true),
            VisionWorker.Response(language: "pt", width: 64, height: 96, observations: nil, error: nil, runtimeFailure: true),
            VisionWorker.Response(language: "pt", width: 64, height: 96, observations: nil, error: " \n", runtimeFailure: true),
            VisionWorker.Response(language: "en", width: 64, height: 96, observations: nil, error: "Falha", runtimeFailure: true),
            VisionWorker.Response(language: "pt", width: 65, height: 96, observations: nil, error: "Falha", runtimeFailure: true),
            VisionWorker.Response(language: "pt", width: 64, height: 96, observations: nil, error: String(repeating: "a", count: 32_001), runtimeFailure: true),
            runtimeVersionMismatch
        ]
        try require(falseRuntimeResponses.allSatisfy { !attestsRuntime($0) },
                    "Um resultado incompatível ou sem proveniência de execução autorizou outro motor OCR.")
        let invalidBoxes = [CGRect(x: 0.8, y: 0.4, width: -0.2, height: 0.1), CGRect(x: 0.2, y: 0.8, width: 0.1, height: -0.2),
                            CGRect(x: -0.1, y: 0.2, width: 0.3, height: 0.4), CGRect(x: 0.9, y: 0.2, width: 0.2, height: 0.4),
                            CGRect(x: 0.1, y: 0.2, width: 0, height: 0.4), CGRect(x: CGFloat.infinity, y: 0.2, width: 0.3, height: 0.4)]
        for box in invalidBoxes {
            try require(rejects { try VisionTextObservation.validate([VisionTextObservation(string: "Texto", boundingBox: box, confidence: 0.9)]) },
                        "O transporte aceitou uma caixa de texto inválida.")
        }
        let invalidConfidences: [Float] = [.nan, .infinity, -0.1, 1.1]
        for confidence in invalidConfidences {
            try require(rejects { try VisionTextObservation.validate([VisionTextObservation(string: "Texto", boundingBox: textObservation.boundingBox, confidence: confidence)]) },
                        "O transporte aceitou confiança inválida.")
        }
        try require(rejects { _ = try VisionWorker.readRegularFile(atomic, limit: 3) }, "O transporte ignorou limite de leitura.")
        let workerLink = directory.appendingPathComponent("worker-link")
        try FileManager.default.createSymbolicLink(at: workerLink, withDestinationURL: atomic)
        try require(rejects { _ = try VisionWorker.readRegularFile(workerLink, limit: 100) }, "O transporte seguiu um link simbólico.")
        let workerFIFO = directory.appendingPathComponent("worker-fifo")
        guard mkfifo(workerFIFO.path, mode_t(0o600)) == 0 else { throw NSError(domain: "PDF.NativeAudit", code: 12) }
        let fifoStart = ProcessInfo.processInfo.systemUptime
        try require(rejects { _ = try VisionWorker.readRegularFile(workerFIFO, limit: 100) } && ProcessInfo.processInfo.systemUptime - fifoStart < 1,
                    "A leitura privada não recusou FIFO sem bloquear.")
        try require(rejects { _ = try VisionWorker.recognize(canonical, language: "en", cancellation: token) }, "O processo OCR ignorou cancelamento anterior à criação do filho.")

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
