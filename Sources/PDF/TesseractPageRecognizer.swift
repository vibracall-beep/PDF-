import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Darwin

/// Local CPU OCR, deliberately identified separately from Apple's Vision path.
/// The synchronous API belongs on a worker queue, like VisionRecognition.
enum TesseractPageRecognizer {
    static let backend = "tesseract"
    static let inputLimit = 128 * 1_024 * 1_024
    static let outputLimit = 16 * 1_024 * 1_024
    static let pixelLimit = 40_000_000

    struct PageResult: Sendable {
        let backend: String
        let language: String
        let width: Int
        let height: Int
        let observations: [VisionTextObservation]
    }

    // Explicit wire types: CGRect's Codable representation is not this API.
    struct Response: Decodable {
        let version: Int
        let backend: String
        let language: String
        let width: Int
        let height: Int
        let observations: [Observation]
        let error: String?
    }
    struct Observation: Decodable {
        let string: String
        let boundingBox: Box
        let confidence: Double
    }
    struct Box: Decodable {
        struct Point: Decodable { let x: Double; let y: Double }
        struct Size: Decodable { let width: Double; let height: Double }
        let origin: Point
        let size: Size
    }

    static func recognize(_ image: CGImage, language: String, cancellation: NativeCancellation) throws -> [VisionTextObservation] {
        try recognizePage(image, language: language, cancellation: cancellation).observations
    }

    static func recognizePage(_ image: CGImage, language: String, cancellation: NativeCancellation,
                              onLaunch: ((Int32) -> Void)? = nil) throws -> PageResult {
        try checkCancellation(cancellation)
        guard ["en", "pt"].contains(language) else {
            throw failure(1, "O OCR local aceita português ou inglês.")
        }
        guard image.width > 0, image.height > 0, image.width <= 30_000, image.height <= 30_000,
              image.width <= pixelLimit / image.height else {
            throw failure(2, "A página excedeu o limite de 40 milhões de pixels do OCR local.")
        }
        let runtime = try resolveRuntime()
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Tesseract-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: folder) }
        let input = folder.appendingPathComponent("input.png")
        let output = folder.appendingPathComponent("result.json")
        let options = folder.appendingPathComponent("options.json")
        let bytes = NSMutableData()
        guard let encoder = CGImageDestinationCreateWithData(bytes as CFMutableData, UTType.png.identifier as CFString, 1, nil) else {
            throw failure(3, "Não foi possível preparar a página para o OCR local.")
        }
        CGImageDestinationAddImage(encoder, image, nil)
        guard CGImageDestinationFinalize(encoder), bytes.length <= inputLimit else {
            throw failure(4, "A imagem excedeu o limite de 128 MiB do OCR local.")
        }
        try checkCancellation(cancellation)
        try NativeOutput.write(bytes as Data, to: input)
        try NativeOutput.write(JSONSerialization.data(withJSONObject: ["language": language]), to: options)

        // Use a finite private file as stdin, avoiding a writer pipe which can
        // block or receive SIGPIPE if Python rejects its runtime before reading.
        let optionsHandle = try FileHandle(forReadingFrom: options)
        defer { try? optionsHandle.close() }
        let process = Process()
        process.executableURL = runtime.python
        process.arguments = ["-E", "-s", "-B", runtime.engine.path, "ocr-page", input.path, "--output", output.path]
        process.currentDirectoryURL = folder
        var environment = ProcessInfo.processInfo.environment
        environment["PDF_OPTIONS_STDIN"] = "1"
        environment["PATH"] = runtime.python.deletingLastPathComponent().path + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        environment["TMPDIR"] = folder.path + "/"
        process.environment = environment
        process.standardInput = optionsHandle
        // Neither recognized text nor converter stderr is a diagnostic channel.
        // The only result transport is the bounded private JSON file.
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try checkCancellation(cancellation)
        do { try process.run() }
        catch { throw failure(5, "Não foi possível iniciar o motor local de OCR. Execute novamente o instalador completo.") }
        // Reap the exact child before removing the directory it may still use.
        defer { stopAndReap(process) }
        // Internal audit hook: the production call omits it. Installing cleanup
        // first makes cancellation here exercise a child which really started.
        onLaunch?(process.processIdentifier)
        let deadline = ProcessInfo.processInfo.systemUptime + 90
        while process.isRunning {
            try checkCancellation(cancellation)
            guard ProcessInfo.processInfo.systemUptime < deadline else {
                throw failure(6, "O OCR local excedeu 90 segundos e foi encerrado.")
            }
            Thread.sleep(forTimeInterval: 0.03)
        }
        process.waitUntilExit()
        try checkCancellation(cancellation)
        guard process.terminationReason == .exit, process.terminationStatus == 0 else {
            if process.terminationReason == .exit && process.terminationStatus == 130 { throw CancellationError() }
            throw failure(7, "O Tesseract não concluiu o reconhecimento (status \(process.terminationStatus)). Verifique o motor local e os idiomas instalados.")
        }
        let result = try decodeResponse(readPrivateResponse(output), language: language, width: image.width, height: image.height)
        try checkCancellation(cancellation)
        return result
    }

    static func decodeResponse(_ data: Data, language: String, width: Int, height: Int) throws -> PageResult {
        guard !data.isEmpty, data.count <= outputLimit else { throw failure(8, "O resultado do OCR local excedeu o limite permitido.") }
        let response: Response
        do { response = try JSONDecoder().decode(Response.self, from: data) }
        catch { throw failure(9, "O motor local retornou um resultado de OCR inválido.") }
        guard response.version == 1, response.backend == backend, response.language == language,
              ["en", "pt"].contains(language), response.width == width, response.height == height,
              width > 0, height > 0, width <= 30_000, height <= 30_000, width <= pixelLimit / height,
              response.error == nil else {
            throw failure(10, "O resultado do OCR local não corresponde à página, ao idioma ou ao motor solicitado.")
        }
        guard response.observations.count <= 50_000 else { throw failure(11, "O OCR local retornou observações demais para uma página.") }
        var totalBytes = 0
        var values: [VisionTextObservation] = []
        values.reserveCapacity(response.observations.count)
        for observation in response.observations {
            let box = observation.boundingBox
            let x = box.origin.x, y = box.origin.y, w = box.size.width, h = box.size.height
            let length = observation.string.utf8.count
            guard !observation.string.isEmpty, length <= 65_536, !observation.string.contains("\0"),
                  [x, y, w, h, observation.confidence].allSatisfy(\.isFinite),
                  x >= 0, y >= 0, w > 0, h > 0, x + w <= 1, y + h <= 1,
                  (0...1).contains(observation.confidence) else {
                throw failure(12, "O OCR local retornou texto, coordenadas ou confiança inválidos.")
            }
            totalBytes += length
            guard totalBytes <= 8 * 1_024 * 1_024 else { throw failure(13, "O texto reconhecido excedeu o limite de uma página.") }
            values.append(VisionTextObservation(string: observation.string,
                boundingBox: CGRect(x: x, y: y, width: w, height: h), confidence: Float(observation.confidence)))
        }
        return PageResult(backend: backend, language: language, width: width, height: height, observations: values)
    }

    static func readPrivateResponse(_ url: URL) throws -> Data {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure(14, "O motor local terminou sem um resultado privado de OCR.") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_mode & 0o077 == 0,
              info.st_size > 0, info.st_size <= Int64(outputLimit) else {
            throw failure(15, "O resultado de OCR precisa ser um arquivo regular, privado e de tamanho limitado.")
        }
        var data = Data()
        while let chunk = try handle.read(upToCount: min(65_536, outputLimit + 1 - data.count)), !chunk.isEmpty {
            data.append(chunk)
            guard data.count <= outputLimit else { throw failure(16, "O resultado de OCR cresceu além do limite permitido.") }
        }
        return data
    }

    private static func resolveRuntime() throws -> (python: URL, engine: URL) {
        let files = FileManager.default
        let python: URL, engine: URL
        if Bundle.main.bundleURL.pathExtension.lowercased() == "app", let resources = Bundle.main.resourceURL {
            // An installed app must use its own complete runtime, never a
            // different engine discovered in the user's working directory.
            python = resources.appendingPathComponent("runtime/bin/python3")
            engine = resources.appendingPathComponent("engine/pdf_engine.py")
        } else {
            let checkout = URL(fileURLWithPath: files.currentDirectoryPath, isDirectory: true)
            python = checkout.appendingPathComponent(".venv/bin/python3")
            engine = checkout.appendingPathComponent("engine/pdf_engine.py")
        }
        guard files.isExecutableFile(atPath: python.path),
              let values = try? engine.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]),
              values.isRegularFile == true, values.isSymbolicLink != true else {
            throw failure(17, "O motor local de OCR não foi instalado. Execute o instalador completo do PDF.")
        }
        return (python, engine)
    }

    private static func checkCancellation(_ cancellation: NativeCancellation) throws {
        try cancellation.check()
        if Task.isCancelled { throw CancellationError() }
    }

    private static func stopAndReap(_ process: Process) {
        if process.isRunning {
            // Python handles SIGTERM and gives its own Tesseract process group
            // up to three seconds to exit, then kills and reaps it. Killing
            // Python immediately could strand that grandchild.
            process.terminate()
            let grace = ProcessInfo.processInfo.systemUptime + 6
            while process.isRunning && ProcessInfo.processInfo.systemUptime < grace { Thread.sleep(forTimeInterval: 0.02) }
            if process.isRunning { _ = Darwin.kill(process.processIdentifier, SIGKILL) }
        }
        process.waitUntilExit()
    }

    private static func failure(_ code: Int, _ message: String) -> NSError {
        NSError(domain: "PDF.Tesseract", code: code, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
