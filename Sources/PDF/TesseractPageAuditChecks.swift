import Foundation
import CoreGraphics
import CoreText
import Darwin

/// Called only by the native smoke runner after installing the local runtime.
/// Transport fixtures test validation; the OCR assertion uses actual pixels
/// and the installed Tesseract executable, never a substituted observation.
enum TesseractPageAuditChecks {
    static func run() throws {
        try auditTransport()
        try auditRuntime()
    }

    static func auditTransport() throws {
        let word: [String: Any] = ["string": "Ação verification", "confidence": 0.91,
            "boundingBox": ["origin": ["x": 0.1, "y": 0.2], "size": ["width": 0.3, "height": 0.1]]]
        let response: [String: Any] = ["version": 1, "backend": "tesseract", "language": "pt", "width": 1400, "height": 500,
                                        "observations": [word]]
        func encoded(_ value: [String: Any]) throws -> Data { try JSONSerialization.data(withJSONObject: value) }
        func decoded(_ value: [String: Any]) throws -> TesseractPageRecognizer.PageResult {
            try TesseractPageRecognizer.decodeResponse(encoded(value), language: "pt", width: 1400, height: 500)
        }
        let bytes = try encoded(response)
        let valid = try decoded(response)
        try require(valid.backend == "tesseract" && valid.language == "pt" && valid.width == 1400 && valid.height == 500 &&
                    valid.observations.count == 1 && valid.observations[0].string == "Ação verification" &&
                    valid.observations[0].boundingBox == CGRect(x: 0.1, y: 0.2, width: 0.3, height: 0.1),
                    "O transporte de OCR perdeu motor, Unicode, dimensões ou coordenadas.")
        for (key, value) in [("version", 2 as Any), ("backend", "vision" as Any), ("language", "en" as Any),
                             ("width", 1401 as Any), ("height", 501 as Any), ("error", "Falha real" as Any)] {
            var changed = response; changed[key] = value
            try require(rejects { _ = try decoded(changed) }, "O transporte aceitou metadados incompatíveis.")
        }
        for badBox in [
            ["origin": ["x": -0.1, "y": 0.2], "size": ["width": 0.3, "height": 0.1]],
            ["origin": ["x": 0.9, "y": 0.2], "size": ["width": 0.3, "height": 0.1]],
            ["origin": ["x": 0.1, "y": 0.2], "size": ["width": 0.0, "height": 0.1]],
            ["origin": ["x": 0.1, "y": 0.95], "size": ["width": 0.3, "height": 0.1]],
        ] {
            var changedWord = word; changedWord["boundingBox"] = badBox
            var changed = response; changed["observations"] = [changedWord]
            try require(rejects { _ = try decoded(changed) }, "O transporte aceitou coordenadas fora da página.")
        }
        for (key, value) in [("string", "" as Any), ("string", "bad\0text" as Any), ("confidence", -0.1 as Any),
                             ("confidence", 1.1 as Any), ("string", String(repeating: "á", count: 32_769) as Any)] {
            var changedWord = word; changedWord[key] = value
            var changed = response; changed["observations"] = [changedWord]
            try require(rejects { _ = try decoded(changed) }, "O transporte aceitou texto ou confiança inválidos.")
        }
        var blank = response; blank["observations"] = [[String: Any]]()
        try require(try decoded(blank).observations.isEmpty, "Uma página realmente vazia deve permanecer um resultado vazio válido.")
        var excessive = response; excessive["observations"] = Array(repeating: word, count: 50_001)
        try require(rejects { _ = try decoded(excessive) }, "O transporte não limitou a quantidade de observações.")
        try require(rejects { _ = try TesseractPageRecognizer.decodeResponse(Data("not JSON".utf8), language: "pt", width: 1400, height: 500) },
                    "O transporte aceitou um resultado corrompido.")
        try require(rejects {
            _ = try TesseractPageRecognizer.decodeResponse(Data(repeating: 32, count: TesseractPageRecognizer.outputLimit + 1),
                                                           language: "pt", width: 1400, height: 500)
        }, "O transporte tentou decodificar JSON acima do limite de 16 MiB.")

        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-TesseractAudit-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: folder) }
        let regular = folder.appendingPathComponent("private.json")
        try NativeOutput.write(bytes, to: regular)
        try require(try TesseractPageRecognizer.readPrivateResponse(regular) == bytes, "A leitura privada não preservou o JSON de OCR.")
        let link = folder.appendingPathComponent("linked.json")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: regular)
        try require(rejects { _ = try TesseractPageRecognizer.readPrivateResponse(link) }, "A leitura de OCR seguiu um link simbólico.")
        let fifo = folder.appendingPathComponent("fifo.json")
        guard mkfifo(fifo.path, mode_t(0o600)) == 0 else { throw failure("Não foi possível preparar o FIFO de auditoria.") }
        let started = ProcessInfo.processInfo.systemUptime
        try require(rejects { _ = try TesseractPageRecognizer.readPrivateResponse(fifo) } && ProcessInfo.processInfo.systemUptime - started < 1,
                    "A leitura de OCR não rejeitou FIFO sem bloquear.")
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: regular.path)
        try require(rejects { _ = try TesseractPageRecognizer.readPrivateResponse(regular) }, "A leitura aceitou um resultado de OCR não privado.")
        let oversized = folder.appendingPathComponent("oversized.json")
        try NativeOutput.write(Data([32]), to: oversized)
        let oversizedHandle = try FileHandle(forWritingTo: oversized)
        do { try oversizedHandle.truncate(atOffset: UInt64(TesseractPageRecognizer.outputLimit + 1)); try oversizedHandle.close() }
        catch { try? oversizedHandle.close(); throw error }
        try require(rejects { _ = try TesseractPageRecognizer.readPrivateResponse(oversized) },
                    "A leitura não recusou um arquivo de OCR acima do limite antes de alocar seu conteúdo.")
    }

    static func auditRuntime() throws {
        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: 1400, height: 500, bitsPerComponent: 8, bytesPerRow: 0,
                space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else {
            throw failure("Não foi possível criar a imagem de auditoria do OCR local.")
        }
        context.setFillColor(CGColor(gray: 1, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 1400, height: 500))
        let font = CTFontCreateWithName("Helvetica" as CFString, 64, nil)
        let attributes: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0, alpha: 1),
        ]
        for (text, y) in [("Local OCR verification", 320.0), ("Private processing 2026", 210.0)] {
            let line = CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: attributes) as CFAttributedString)
            context.textPosition = CGPoint(x: 70, y: y)
            CTLineDraw(line, context)
        }
        guard let image = context.makeImage() else { throw failure("A imagem de auditoria do OCR local está vazia.") }
        let token = NativeCancellation(); token.cancel()
        do {
            _ = try TesseractPageRecognizer.recognizePage(image, language: "en", cancellation: token)
            throw failure("O OCR local ignorou cancelamento anterior à criação do processo.")
        } catch is CancellationError { /* Required: no subprocess is started. */ }
        try require(rejects { _ = try TesseractPageRecognizer.recognizePage(image, language: "xx", cancellation: NativeCancellation()) },
                    "O OCR local aceitou um idioma desconhecido.")
        let runningToken = NativeCancellation()
        var child: Int32 = 0, launches = 0
        let cancellationStarted = ProcessInfo.processInfo.systemUptime
        do {
            _ = try TesseractPageRecognizer.recognizePage(image, language: "en", cancellation: runningToken) { pid in
                child = pid; launches += 1; runningToken.cancel()
            }
            throw failure("O OCR local ignorou cancelamento após iniciar o processo.")
        } catch is CancellationError { /* Cleanup must already have reaped Python. */ }
        try require(launches == 1 && child > 0, "A auditoria de cancelamento não iniciou um processo real.")
        let status = Darwin.kill(child, 0), statusError = errno
        try require(status == -1 && statusError == ESRCH, "O cancelamento deixou o processo Python em execução ou sem reap.")
        try require(ProcessInfo.processInfo.systemUptime - cancellationStarted < 10,
                    "O cancelamento do OCR local excedeu o prazo de encerramento e limpeza.")
        let result = try TesseractPageRecognizer.recognizePage(image, language: "en", cancellation: NativeCancellation())
        try require(result.backend == "tesseract" && result.language == "en" && result.width == 1400 && result.height == 500,
                    "O reconhecimento real não informou sua proveniência corretamente.")
        try require(result.observations.contains { $0.string.localizedCaseInsensitiveContains("verification") },
                    "O Tesseract instalado não reconheceu a palavra conhecida nos pixels reais da amostra.")
        try VisionTextObservation.validate(result.observations)
    }

    private static func rejects(_ action: () throws -> Void) -> Bool {
        do { try action(); return false } catch { return true }
    }
    private static func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw failure(message) }
    }
    private static func failure(_ message: String) -> NSError {
        NSError(domain: "PDF.TesseractAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
