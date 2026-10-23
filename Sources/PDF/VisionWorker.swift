import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Vision
import Darwin

/// Validated OCR values consumed by PDF rendering and benchmarks. The enclosing
/// PageOCRResult records the engine; this worker itself returns only Vision data.
struct VisionTextObservation: Codable, Sendable {
    let string: String
    let boundingBox: CGRect
    let confidence: Float

    static func from(_ observations: [VNRecognizedTextObservation]) throws -> [Self] {
        let values = observations.compactMap { observation -> Self? in
            guard let candidate = observation.topCandidates(1).first, !candidate.string.isEmpty else { return nil }
            return Self(string: candidate.string, boundingBox: observation.boundingBox, confidence: candidate.confidence)
        }
        try validate(values)
        return values
    }
    static func validate(_ values: [Self]) throws {
        guard values.count <= 50_000 else { throw VisionWorker.failure(1, "O Vision retornou observações demais para uma página.") }
        var totalBytes = 0
        for value in values {
            let box = value.boundingBox
            let numbers = [box.origin.x, box.origin.y, box.size.width, box.size.height]
            let length = value.string.utf8.count
            guard !value.string.isEmpty, length <= 65_536,
                  numbers.allSatisfy(\.isFinite), box.size.width > 0, box.size.height > 0,
                  box.minX >= 0, box.minY >= 0, box.maxX <= 1, box.maxY <= 1,
                  value.confidence.isFinite, (0...1).contains(value.confidence) else {
                throw VisionWorker.failure(2, "O Vision retornou texto, coordenadas ou confiança inválidos.")
            }
            totalBytes += length
            guard totalBytes <= 8 * 1_024 * 1_024 else { throw VisionWorker.failure(3, "O texto reconhecido excedeu o limite de uma página.") }
        }
    }
}

enum VisionWorker {
    static let argument = "--vision-worker"
    static let inputLimit = 128 * 1_024 * 1_024
    static let outputLimit = 16 * 1_024 * 1_024

    struct Response: Codable {
        var version = 1
        let language: String
        let width: Int
        let height: Int
        let observations: [VisionTextObservation]?
        let error: String?
        // Set only when the configured Vision request itself threw a known
        // runtime failure. Configuration, decoding and DTO failures are false.
        var runtimeFailure: Bool? = nil
    }

    struct RuntimeFailure: LocalizedError {
        let detail: String
        var errorDescription: String? { detail }
    }

    static func failure(_ code: Int, _ message: String) -> NSError {
        NSError(domain: "PDF.VisionWorker", code: code, userInfo: [NSLocalizedDescriptionKey: message])
    }

    /// Called by the executable entry point before constructing the SwiftUI App.
    /// No Workspace, PDFDocument, window, preferences or recovery store is created.
    static func handleCommandLineIfNeeded() {
        let arguments = CommandLine.arguments
        guard arguments.contains(argument) else { return }
        guard arguments.count == 5, arguments[1] == argument, ["pt", "en"].contains(arguments[4]) else {
            FileHandle.standardError.write(Data("Vision worker: invalid arguments\n".utf8)); exit(2)
        }
        let input = URL(fileURLWithPath: arguments[2]), output = URL(fileURLWithPath: arguments[3]), language = arguments[4]
        do {
            try validateContainer(input: input, output: output)
            let data = try readRegularFile(input, limit: inputLimit)
            guard let source = CGImageSourceCreateWithData(data as CFData, nil), CGImageSourceGetCount(source) == 1,
                  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
                  let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
                  width > 0, height > 0, width <= 30_000, height <= 30_000, width <= 100_000_000 / height else {
                throw failure(4, "A imagem enviada ao processo de reconhecimento é inválida.")
            }
            do {
                let values = try performDirect(data: data, language: language)
                let response = Response(language: language, width: width, height: height, observations: values, error: nil)
                try write(response, to: output)
                exit(0)
            } catch {
                // Keep failure separate from an empty but successful recognition.
                let detail = String((VisionRecognition.description(error) + "; Swift=" + String(reflecting: error)).prefix(8_000))
                let runtimeFailure = error is VisionExecutionFailure && VisionRecognition.shouldRetryOnCPU(error)
                try write(Response(language: language, width: width, height: height, observations: nil,
                                   error: detail, runtimeFailure: runtimeFailure), to: output)
                exit(1)
            }
        } catch {
            FileHandle.standardError.write(Data(("Vision worker failed: " + String(String(reflecting: error).prefix(8_000)) + "\n").utf8))
            exit(2)
        }
    }

    /// Exactly one request. Calling the parent wrapper here would recurse and
    /// would reuse the runtime state that process isolation is meant to avoid.
    private static func performDirect(data: Data, language: String) throws -> [VisionTextObservation] {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.automaticallyDetectsLanguage = false
        let supported = try request.supportedRecognitionLanguages()
        request.recognitionLanguages = (language == "pt" ? ["pt-BR", "pt-PT", "en-US"] : ["en-US"]).filter { supported.contains($0) }
        guard request.recognitionLanguages.contains(where: { $0.hasPrefix(language) }) else {
            throw failure(5, "O Vision não oferece o idioma solicitado neste processo.")
        }
        do { try VNImageRequestHandler(data: data, orientation: .up, options: [:]).perform([request]) }
        catch { throw VisionExecutionFailure(underlying: error) }
        return try VisionTextObservation.from(request.results ?? [])
    }

    static func recognize(_ image: CGImage, language: String, cancellation: NativeCancellation) throws -> [VisionTextObservation] {
        try cancellation.check()
        guard ["pt", "en"].contains(language), !CommandLine.arguments.contains(argument),
              let executable = Bundle.main.executableURL else { throw failure(6, "O processo nativo de reconhecimento não pôde ser iniciado.") }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Vision-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: folder) }
        let input = folder.appendingPathComponent("input.png"), output = folder.appendingPathComponent("result.json")
        let buffer = NSMutableData()
        guard let encoder = CGImageDestinationCreateWithData(buffer as CFMutableData, UTType.png.identifier as CFString, 1, nil) else {
            throw failure(7, "Não foi possível codificar a página para reconhecimento isolado.")
        }
        CGImageDestinationAddImage(encoder, image, nil)
        guard CGImageDestinationFinalize(encoder), buffer.length <= inputLimit else { throw failure(8, "A imagem excedeu o limite do processo de reconhecimento.") }
        try cancellation.check()
        try NativeOutput.write(buffer as Data, to: input)
        let process = Process()
        process.executableURL = executable
        process.arguments = [argument, input.path, output.path, language]
        process.currentDirectoryURL = folder
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        // Framework logging is not a transport. Structured errors are written
        // to the bounded private response; unbounded stderr is discarded.
        process.standardError = FileHandle.nullDevice
        try cancellation.check()
        try process.run()
        // Stop/reap this exact child before the enclosing defer removes its files.
        defer { stop(process) }
        let deadline = ProcessInfo.processInfo.systemUptime + 60
        while process.isRunning {
            try cancellation.check()
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw failure(10, "O processo isolado do Vision excedeu 60 segundos e foi encerrado.") }
            Thread.sleep(forTimeInterval: 0.03)
        }
        process.waitUntilExit()
        try cancellation.check()
        let response: Response
        do { response = try JSONDecoder().decode(Response.self, from: readRegularFile(output, limit: outputLimit)) }
        catch { throw failure(12, "O processo isolado do Vision terminou sem um resultado válido (status \(process.terminationStatus)).") }
        let values = try validateResponse(response, language: language, width: image.width, height: image.height,
                                          successfulExit: process.terminationReason == .exit && process.terminationStatus == 0,
                                          runtimeFailureExit: process.terminationReason == .exit && process.terminationStatus == 1)
        try cancellation.check()
        return values
    }

    static func validateResponse(_ response: Response, language: String, width: Int, height: Int, successfulExit: Bool,
                                 runtimeFailureExit: Bool = false) throws -> [VisionTextObservation] {
        guard response.version == 1, response.language == language, response.width == width, response.height == height else {
            throw failure(13, "O resultado isolado não corresponde à página e ao idioma solicitados.")
        }
        if !successfulExit, runtimeFailureExit, response.runtimeFailure == true,
           response.observations == nil, let detail = response.error,
           !detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, detail.utf8.count <= 32_000 {
            throw RuntimeFailure(detail: "O processo isolado do Vision falhou durante o reconhecimento: " + detail)
        }
        guard successfulExit, response.runtimeFailure != true, response.error == nil, let values = response.observations else {
            throw failure(14, "O processo isolado do Vision falhou: \(response.error ?? "sem detalhes do framework").")
        }
        try VisionTextObservation.validate(values)
        return values
    }

    private static func stop(_ process: Process) {
        if process.isRunning {
            process.terminate()
            let grace = ProcessInfo.processInfo.systemUptime + 1
            while process.isRunning && ProcessInfo.processInfo.systemUptime < grace { Thread.sleep(forTimeInterval: 0.02) }
            if process.isRunning { _ = Darwin.kill(process.processIdentifier, SIGKILL) }
        }
        process.waitUntilExit()
    }

    static func readRegularFile(_ url: URL, limit: Int) throws -> Data {
        guard limit > 0, limit <= inputLimit else { throw failure(22, "Limite inválido para leitura do reconhecimento.") }
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure(15, "Não foi possível abrir o arquivo privado de reconhecimento.") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var information = stat()
        guard fstat(descriptor, &information) == 0, information.st_mode & S_IFMT == S_IFREG,
              information.st_uid == getuid(), information.st_mode & 0o077 == 0,
              information.st_size > 0, information.st_size <= Int64(limit) else {
            throw failure(16, "O arquivo de reconhecimento precisa ser regular, privado e respeitar o limite de tamanho.")
        }
        var result = Data()
        while let chunk = try handle.read(upToCount: min(65_536, limit + 1 - result.count)), !chunk.isEmpty {
            result.append(chunk)
            guard result.count <= limit else { throw failure(17, "O arquivo de reconhecimento cresceu além do limite permitido.") }
        }
        return result
    }
    private static func validateContainer(input: URL, output: URL) throws {
        let folder = input.deletingLastPathComponent().standardizedFileURL
        guard input.lastPathComponent == "input.png", output.lastPathComponent == "result.json",
              output.deletingLastPathComponent().standardizedFileURL == folder else { throw failure(18, "Caminhos de reconhecimento incompatíveis.") }
        let descriptor = Darwin.open(folder.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure(19, "A pasta privada de reconhecimento não está disponível.") }
        defer { Darwin.close(descriptor) }
        var information = stat()
        guard fstat(descriptor, &information) == 0, information.st_uid == getuid(), information.st_mode & S_IFMT == S_IFDIR,
              information.st_mode & 0o077 == 0 else { throw failure(20, "A pasta de reconhecimento não é privada.") }
    }
    private static func write(_ response: Response, to destination: URL) throws {
        let data = try JSONEncoder().encode(response)
        guard data.count <= outputLimit else { throw failure(21, "O resultado de reconhecimento excedeu o limite permitido.") }
        try NativeOutput.write(data, to: destination)
    }
}
