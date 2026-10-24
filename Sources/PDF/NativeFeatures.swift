import SwiftUI
import AppKit
import PDFKit
import Vision
import CoreML
import CoreText
import ImageIO
import Darwin
@preconcurrency import ImageCaptureCore
@preconcurrency import Quartz
import UniformTypeIdentifiers

/// Publishes a fully generated file without replacing an existing destination.
/// The hard-link operation is atomic, so even a concurrent creator is preserved.
enum NativeOutput {
    static func write(_ data: Data, to destination: URL) throws {
        let temporary = destination.deletingLastPathComponent().appendingPathComponent(".pdf-\(UUID().uuidString).tmp")
        let descriptor = Darwin.open(temporary.path, O_WRONLY | O_CREAT | O_EXCL, mode_t(0o600))
        guard descriptor >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno), userInfo: [NSFilePathErrorKey: temporary.path]) }
        defer { try? FileManager.default.removeItem(at: temporary) }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        try handle.write(contentsOf: data)
        try handle.synchronize()
        try FileManager.default.linkItem(at: temporary, to: destination)
    }
    @MainActor static func destination(model: Workspace, toolName: String, extension suffix: String = "pdf", originalURL: URL? = nil) -> URL? {
        // All result panels use the workspace's filename template, directory
        // and isolated defaults. Publication still uses the no-clobber writer.
        model.selectOutput(extension: suffix, toolName: toolName, originalURL: originalURL)
    }
}

/// Thread-safe cooperative cancellation, also forwarding cancellation to Vision.
final class NativeCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    private var request: VNRequest?
    func cancel() {
        lock.lock(); cancelled = true; let current = request; lock.unlock()
        current?.cancel()
    }
    func check() throws {
        lock.lock(); let value = cancelled; lock.unlock()
        if value { throw CancellationError() }
    }
    func install(_ value: VNRequest?) {
        lock.lock(); request = value; let shouldCancel = cancelled; lock.unlock()
        if shouldCancel { value?.cancel() }
    }
}

private enum NativePDFError: LocalizedError {
    case unreadable, noImage, render, output, emptyScan, encrypted
    var errorDescription: String? {
        switch self {
        case .encrypted: return "Desbloqueie uma cópia explicitamente antes de importar ou processar um documento protegido."
        case .unreadable: return "Não foi possível ler o documento."
        case .noImage: return "Não foi possível ler uma das imagens."
        case .render: return "Não foi possível renderizar uma página."
        case .output: return "Não foi possível criar o PDF de saída."
        case .emptyScan: return "Digitalize ou importe ao menos uma imagem."
        }
    }
}

/// Marks only errors thrown while Vision is executing an already configured request.
/// Foundation can erase Vision's runtime error into _GenericObjCError; configuration
/// failures outside perform must never receive the same retry policy.
struct VisionExecutionFailure: Error {
    let underlying: Error
}

/// A runtime failure confirmed by the configured in-process attempts and the
/// private child. It alone permits the product's alternate local OCR engine.
struct VisionRuntimeUnavailable: LocalizedError {
    let detail: String
    var errorDescription: String? { detail }
}

/// Automatic device selection and the SDK's default recognition revision come first.
/// Runtime failures may receive a CPU attempt and one supported older accurate engine.
/// No retry changes the requested language or switches to fast recognition.
enum VisionRecognition {
    /// Materialize all inputs in a CPU bitmap with a fixed, explicit pixel layout.
    /// In particular, a Core Image RGBA8 request can still return noneSkipLast or
    /// a deferred image; the recognizer should not depend on that representation.
    static func canonicalImage(_ image: CGImage) throws -> CGImage {
        guard image.width > 0, image.height > 0, image.width <= 30_000, image.height <= 30_000,
              image.width <= 100_000_000 / image.height,
              let space = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                                      bytesPerRow: image.width * 4, space: space,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else {
            throw NSError(domain: "PDF.Vision", code: 7, userInfo: [NSLocalizedDescriptionKey: "Não foi possível preparar os pixels da página para reconhecimento."])
        }
        context.setBlendMode(.copy)
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        guard let output = context.makeImage() else {
            throw NSError(domain: "PDF.Vision", code: 7, userInfo: [NSLocalizedDescriptionKey: "Não foi possível materializar a imagem para reconhecimento."])
        }
        return output
    }
    private static func chain(_ error: Error) -> [NSError] {
        var current = (error as? VisionExecutionFailure)?.underlying ?? error
        var result: [NSError] = []
        var visited = Set<ObjectIdentifier>()
        for _ in 0..<8 {
            let native = current as NSError
            guard visited.insert(ObjectIdentifier(native)).inserted else { break }
            result.append(native)
            guard let underlying = native.userInfo[NSUnderlyingErrorKey] as? Error else { break }
            current = underlying
        }
        return result
    }
    static func shouldRetryOnCPU(_ error: Error) -> Bool {
        if error is CancellationError { return false }
        let execution = error as? VisionExecutionFailure
        if execution?.underlying is CancellationError { return false }
        let retryable = [VNErrorCode.operationFailed, .internalError, .unknownError, .unsupportedComputeStage, .unsupportedComputeDevice]
        let errors = chain(error)
        return !errors.isEmpty && errors.allSatisfy { native in
            if native.domain == VNErrorDomain {
                // A nested cancellation, bad input, missing model or memory failure
                // vetoes a retry even when wrapped in a generic execution error.
                return retryable.contains(where: { $0.rawValue == native.code })
            }
            if native.domain == "TextRecognition.CRImageReaderError" {
                return native.code == 9 || native.localizedDescription.localizedCaseInsensitiveContains("unknownError")
            }
            // Observed from perform on SDK 27. This permits a bounded compatibility
            // attempt; it does not establish a hardware cause for the failure.
            return execution != nil && native.domain == "Foundation._GenericObjCError" && native.code == 0
        }
    }
    static func description(_ error: Error) -> String {
        chain(error).map { "\($0.domain) (\($0.code)): \($0.localizedDescription)" }.joined(separator: " → ")
    }
    static func recognize(_ input: CGImage, language: String, cancellation: NativeCancellation) throws -> [VisionTextObservation] {
        try cancellation.check()
        guard ["pt", "en"].contains(language) else {
            throw NSError(domain: "PDF.Vision", code: 5, userInfo: [NSLocalizedDescriptionKey: "Escolha português ou inglês para o reconhecimento."])
        }
        let image = try canonicalImage(input)
        try cancellation.check()
        func terminal(_ error: NSError, canIsolate: Bool) throws -> [VisionTextObservation] {
            var reported = error
            var runtimeUnavailable = false
            if canIsolate {
                print("Vision OCR: in-process runtime failed; trying one isolated native process in accurate mode")
                do {
                    let observations = try VisionWorker.recognize(image, language: language, cancellation: cancellation)
                    print("Vision OCR: isolated native process completed with \(observations.count) observations; previous in-process failure: \(error.localizedDescription)")
                    return observations
                } catch {
                    try cancellation.check()
                    if error is CancellationError { throw error }
                    runtimeUnavailable = error is VisionWorker.RuntimeFailure
                    reported = NSError(domain: "PDF.Vision", code: 8, userInfo: [
                        NSLocalizedDescriptionKey: reported.localizedDescription + " Processo nativo isolado: " + description(error),
                        NSUnderlyingErrorKey: error
                    ])
                }
            }
            if CommandLine.arguments.contains("--vision-audit") {
                VisionFailureDiagnostics.run(image: image, language: language, expectedText: "verification", cancellation: cancellation)
            }
            // Diagnostic probes never replace the product result or suppress a
            // failing assertion. The original request still fails its audit.
            if runtimeUnavailable { throw VisionRuntimeUnavailable(detail: reported.localizedDescription) }
            throw reported
        }
        let defaultRevision = VNRecognizeTextRequest.defaultRevision
        // Revision 1 is English-only. Select an older engine only if this runtime
        // still advertises it; each attempt also validates its accurate languages.
        let compatibleRevision = VNRecognizeTextRequest.supportedRevisions.filter { $0 >= 2 && $0 < defaultRevision }.max()
        func perform(revision: Int, cpuOnly: Bool) throws -> [VisionTextObservation] {
            try cancellation.check()
            let request = VNRecognizeTextRequest()
            request.revision = revision
            request.recognitionLevel = .accurate; request.usesLanguageCorrection = true
            let supported = try request.supportedRecognitionLanguages()
            let wanted = language == "pt" ? ["pt-BR", "pt-PT", "en-US"] : ["en-US"]
            request.recognitionLanguages = wanted.filter { supported.contains($0) }
            guard request.recognitionLanguages.contains(where: { $0.hasPrefix(language == "pt" ? "pt" : "en") }) else {
                throw NSError(domain: "PDF.Vision", code: 5, userInfo: [NSLocalizedDescriptionKey: "O Vision não disponibilizou o idioma escolhido neste sistema."])
            }
            // The user selects Portuguese or English. Vision's public API
            // recommends explicit languages when the language is already known.
            request.automaticallyDetectsLanguage = false
            if CommandLine.arguments.contains(where: { ["--smoke-test", "--vision-audit", "--benchmark"].contains($0) }) {
                print("Vision OCR configuration: revision=\(request.revision); accurate=true; automaticLanguage=false; languages=\(request.recognitionLanguages.joined(separator: ",")); cpuOnly=\(cpuOnly); image=\(image.width)x\(image.height); bitsPerComponent=\(image.bitsPerComponent); bitsPerPixel=\(image.bitsPerPixel); bitmapInfo=\(image.bitmapInfo.rawValue); colorSpace=\(image.colorSpace?.name as String? ?? "unnamed"); alpha=\(image.alphaInfo.rawValue); orientation=up")
            }
            cancellation.install(request)
            defer { cancellation.install(nil) }
            if cpuOnly {
                let stages = try request.supportedComputeStageDevices
                guard !stages.isEmpty else {
                    throw NSError(domain: "PDF.Vision", code: 1, userInfo: [NSLocalizedDescriptionKey: "O Vision não declarou estágios de execução compatíveis com CPU."])
                }
                for (stage, devices) in stages {
                    guard let cpu = devices.first(where: { if case .cpu = $0 { return true }; return false }) else {
                        throw NSError(domain: "PDF.Vision", code: 2, userInfo: [NSLocalizedDescriptionKey: "O estágio \(stage) não oferece execução em CPU neste sistema."])
                    }
                    request.setComputeDevice(cpu, for: stage)
                }
            }
            try cancellation.check()
            do { try VNImageRequestHandler(cgImage: image, orientation: .up, options: [:]).perform([request]) }
            catch { try cancellation.check(); throw VisionExecutionFailure(underlying: error) }
            try cancellation.check()
            return try VisionTextObservation.from(request.results ?? [])
        }
        do { return try perform(revision: defaultRevision, cpuOnly: false) }
        catch {
            try cancellation.check()
            if error is CancellationError { throw error }
            let first = error
            guard shouldRetryOnCPU(first) else {
                return try terminal(NSError(domain: "PDF.Vision", code: 3, userInfo: [NSLocalizedDescriptionKey: "O reconhecimento de texto falhou: \(description(first))", NSUnderlyingErrorKey: first]), canIsolate: false)
            }
            print("Vision OCR: automatic execution failed (\(description(first))); retrying once with supported CPU devices")
            do {
                let observations = try perform(revision: defaultRevision, cpuOnly: true)
                print("Vision OCR: CPU retry completed with \(observations.count) observations")
                return observations
            } catch {
                try cancellation.check()
                if error is CancellationError { throw error }
                let second = error
                let cpuConfiguration = second as NSError
                let cpuUnavailable = cpuConfiguration.domain == "PDF.Vision" && [1, 2].contains(cpuConfiguration.code)
                if let compatibleRevision, shouldRetryOnCPU(second) || cpuUnavailable {
                    print("Vision OCR: CPU execution failed (\(description(second))); trying supported accurate revision \(compatibleRevision)")
                    do {
                        let observations = try perform(revision: compatibleRevision, cpuOnly: false)
                        print("Vision OCR: compatible accurate revision \(compatibleRevision) completed with \(observations.count) observations")
                        return observations
                    } catch {
                        try cancellation.check()
                        if error is CancellationError { throw error }
                        return try terminal(NSError(domain: "PDF.Vision", code: 6,
                            userInfo: [NSLocalizedDescriptionKey: "O reconhecimento falhou nas três tentativas nativas em modo preciso. Automática: \(description(first)). CPU: \(description(second)). Revisão compatível \(compatibleRevision): \(description(error)). Nenhum resultado foi publicado.", NSUnderlyingErrorKey: error]), canIsolate: shouldRetryOnCPU(error))
                    }
                }
                return try terminal(NSError(domain: "PDF.Vision", code: 4,
                    userInfo: [NSLocalizedDescriptionKey: "O reconhecimento falhou nas duas tentativas. Automática: \(description(first)). CPU: \(description(second)). Nenhum resultado foi publicado.", NSUnderlyingErrorKey: second]), canIsolate: shouldRetryOnCPU(second) || cpuUnavailable)
            }
        }
    }
}

enum VisionPDF {
    static func create(data: Data, language: String, enhanceContrast: Bool = false, cancellation: NativeCancellation,
                       progress: @escaping @Sendable (Int, Int) -> Void) throws -> Data {
        try SearchablePDFRenderer.create(data: data, enhanceContrast: enhanceContrast, cancellation: cancellation,
                                         progress: progress) { image in
            PageOCRResult(observations: try VisionRecognition.recognize(image, language: language, cancellation: cancellation),
                          backend: "apple-vision", fallbackReason: nil)
        }.data
    }
}

/// Shared page rendering and invisible text placement. The recognizer decides
/// the engine; both strict Vision and the product path preserve the source page.
enum SearchablePDFRenderer {
    static func create(data: Data, enhanceContrast: Bool, cancellation: NativeCancellation,
                       progress: @escaping @Sendable (Int, Int) -> Void,
                       recognize: (CGImage) throws -> PageOCRResult) throws -> OCRPDFResult {
        guard let provider = CGDataProvider(data: data as CFData),
              let document = CGPDFDocument(provider) else { throw NativePDFError.unreadable }
        guard !document.isEncrypted else { throw NativePDFError.encrypted }
        guard document.numberOfPages > 0 else { throw NativePDFError.unreadable }
        let buffer = NSMutableData()
        guard let consumer = CGDataConsumer(data: buffer as CFMutableData),
              let context = CGContext(consumer: consumer, mediaBox: nil, nil) else { throw NativePDFError.output }
        var closed = false
        defer { if !closed { context.closePDF() } }
        var evidence: [OCRPageEvidence] = []
        for index in 1...document.numberOfPages {
            try cancellation.check()
            try autoreleasepool {
                guard let page = document.page(at: index) else { throw NativePDFError.unreadable }
                let crop = page.getBoxRect(.cropBox)
                let rotated = abs(page.rotationAngle) % 180 == 90
                let size = rotated ? CGSize(width: crop.height, height: crop.width) : crop.size
                let bounds = CGRect(origin: .zero, size: size)
                guard size.width.isFinite, size.height.isFinite, size.width > 0, size.height > 0,
                      size.width <= 100_000, size.height <= 100_000 else { throw NativePDFError.render }
                let scale = min(2.5, 3200 / max(size.width, size.height))
                let width = max(1, Int(ceil(size.width * scale)))
                let height = max(1, Int(ceil(size.height * scale)))
                guard let bitmap = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                             bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                             bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { throw NativePDFError.render }
                bitmap.setFillColor(CGColor(gray: 1, alpha: 1)); bitmap.fill(CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
                bitmap.scaleBy(x: CGFloat(width) / size.width, y: CGFloat(height) / size.height)
                let transform = page.getDrawingTransform(.cropBox, rect: bounds, rotate: 0, preserveAspectRatio: true)
                bitmap.concatenate(transform); bitmap.drawPDFPage(page)
                guard let image = bitmap.makeImage() else { throw NativePDFError.render }
                try cancellation.check()
                let recognitionImage = enhanceContrast ? try GPUImageProcessor.enhance(image) : image
                try cancellation.check()
                let result = try recognize(recognitionImage)
                try VisionTextObservation.validate(result.observations)
                try cancellation.check()
                var media = bounds
                let mediaData = Data(bytes: &media, count: MemoryLayout<CGRect>.size)
                context.beginPDFPage([kCGPDFContextMediaBox as String: mediaData] as CFDictionary)
                context.saveGState(); context.concatenate(transform); context.drawPDFPage(page); context.restoreGState()
                for observation in result.observations {
                    let text = observation.string
                    let box = observation.boundingBox
                    let rect = CGRect(x: box.minX * size.width, y: box.minY * size.height, width: box.width * size.width, height: box.height * size.height)
                    let attributed = NSAttributedString(string: text, attributes: [.font: NSFont.systemFont(ofSize: 12)])
                    let line = CTLineCreateWithAttributedString(attributed as CFAttributedString)
                    var ascent: CGFloat = 0, descent: CGFloat = 0
                    let measured = CGFloat(CTLineGetTypographicBounds(line, &ascent, &descent, nil))
                    guard measured > 0, ascent + descent > 0 else { continue }
                    context.saveGState()
                    context.translateBy(x: rect.minX, y: rect.minY)
                    context.scaleBy(x: rect.width / measured, y: rect.height / (ascent + descent))
                    context.textMatrix = .identity; context.textPosition = CGPoint(x: 0, y: descent)
                    context.setTextDrawingMode(.invisible)
                    CTLineDraw(line, context)
                    context.restoreGState()
                }
                context.endPDFPage()
                evidence.append(OCRPageEvidence(page: index, backend: result.backend, fallbackReason: result.fallbackReason))
            }
            progress(index, document.numberOfPages)
        }
        context.closePDF()
        closed = true
        try cancellation.check()
        let normalized = try NativePDFSerialization.normalize(data: buffer as Data, cancellation: cancellation)
        try cancellation.check()
        return OCRPDFResult(data: normalized, pages: evidence)
    }
}

/// Every frame of an imported TIFF becomes a page; orientation uses ImageIO metadata.
enum ScannerPDF {
    static func assemble(urls: [URL], cancellation: NativeCancellation,
                         progress: @escaping @Sendable (Int, Int) -> Void) throws -> Data {
        guard !urls.isEmpty else { throw NativePDFError.emptyScan }
        let document = PDFDocument()
        for (fileIndex, url) in urls.enumerated() {
            try cancellation.check()
            try autoreleasepool {
                if url.pathExtension.lowercased() == "pdf" {
                    guard let source = PDFDocument(url: url) else { throw NativePDFError.unreadable }
                    guard !source.isEncrypted, !source.isLocked else { throw NativePDFError.encrypted }
                    guard source.pageCount > 0 else { throw NativePDFError.unreadable }
                    for index in 0..<source.pageCount {
                        try cancellation.check()
                        guard let page = source.page(at: index)?.copy() as? PDFPage else { throw NativePDFError.unreadable }
                        document.insert(page, at: document.pageCount)
                    }
                } else {
                    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { throw NativePDFError.noImage }
                    let count = try CaptureImageDecoder.frameCount(source)
                    for index in 0..<count {
                        try cancellation.check()
                        let image = try CaptureImageDecoder.frame(source, index: index)
                        let native = NSImage(cgImage: image, size: CaptureImageDecoder.pageSize(source, index: index, image: image))
                        guard let page = PDFPage(image: native) else { throw NativePDFError.noImage }
                        document.insert(page, at: document.pageCount)
                    }
                }
            }
            progress(fileIndex + 1, urls.count)
        }
        try cancellation.check()
        guard document.pageCount > 0 else { throw NativePDFError.output }
        let data = try NativePDFSerialization.serialize(document: document, cancellation: cancellation)
        try cancellation.check()
        return data
    }
}

@MainActor final class ScannerController: NSObject, ObservableObject, ICDeviceBrowserDelegate, IKScannerDeviceViewDelegate {
    @Published var devices: [ICScannerDevice] = []
    @Published var selectedID: String = ""
    @Published var captures: [URL] = []
    @Published var error = ""
    @Published var importingContinuity = false
    private let browser = ICDeviceBrowser()
    private var started = false
    @Published private(set) var folder: URL?
    var selected: ICScannerDevice? { devices.first { identity($0) == selectedID } }
    override init() {
        super.init()
        browser.delegate = self
        let mask = ICDeviceTypeMask.scanner.rawValue | ICDeviceLocationTypeMask.local.rawValue | ICDeviceLocationTypeMask.bonjour.rawValue | ICDeviceLocationTypeMask.shared.rawValue
        browser.browsedDeviceTypeMask = ICDeviceTypeMask(rawValue: mask)!
    }
    func identity(_ device: ICScannerDevice) -> String { device.uuidString ?? String(describing: ObjectIdentifier(device)) }
    func start() {
        guard !started else { return }
        if folder == nil {
            do {
                let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
                let path = base.appendingPathComponent("PDF/Capturas/\(UUID().uuidString)", isDirectory: true)
                try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
                folder = path
            } catch { self.error = error.localizedDescription }
        }
        guard folder != nil else { return }
        started = true; browser.start()
    }
    func stop() { guard started else { return }; started = false; browser.stop(); devices = []; selectedID = "" }
    nonisolated func deviceBrowser(_ browser: ICDeviceBrowser, didAdd device: ICDevice, moreComing: Bool) {
        DispatchQueue.main.async { [weak self] in self?.addDevice(device) }
    }
    private func addDevice(_ device: ICDevice) {
        guard started else { return }
        guard let scanner = device as? ICScannerDevice else { return }
        if !devices.contains(where: { $0 === scanner }) { devices.append(scanner) }
        if selectedID.isEmpty { selectedID = identity(scanner) }
    }
    nonisolated func deviceBrowser(_ browser: ICDeviceBrowser, didRemove device: ICDevice, moreGoing: Bool) {
        DispatchQueue.main.async { [weak self] in self?.removeDevice(device) }
    }
    private func removeDevice(_ device: ICDevice) {
        devices.removeAll { $0 === device }
        if selected == nil { selectedID = devices.first.map(identity) ?? "" }
    }
    @objc(scannerDeviceView:didScanToURL:fileData:error:)
    nonisolated func scannerDeviceView(_ scannerDeviceView: IKScannerDeviceView!, didScanTo url: URL!, fileData data: Data!, error: Error!) {
        let message = error?.localizedDescription
        DispatchQueue.main.async { [weak self] in self?.receiveCapture(url: url, data: data, error: message) }
    }
    private func receiveCapture(url: URL?, data: Data?, error message: String?) {
        if let message { self.error = message; return }
        guard let folder else { self.error = "A pasta de capturas não está disponível."; return }
        do {
            let payload: Data
            if let data, !data.isEmpty { payload = data }
            else if let url { payload = try Data(contentsOf: url) }
            else { throw NativePDFError.noImage }
            let suffix = payload.starts(with: Data("%PDF".utf8)) ? "pdf" : "tiff"
            let path = folder.appendingPathComponent("captura-\(UUID().uuidString).\(suffix)")
            try NativeOutput.write(payload, to: path); captures.append(path)
        } catch { self.error = error.localizedDescription }
    }
    @objc(scannerDeviceView:didEncounterError:)
    nonisolated func scannerDeviceView(_ scannerDeviceView: IKScannerDeviceView!, didEncounterError error: Error!) {
        let message = error?.localizedDescription ?? "O scanner encontrou um erro."
        DispatchQueue.main.async { [weak self] in self?.error = message }
    }
    func importImages() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.image, .pdf]; panel.allowsMultipleSelection = true
        if panel.runModal() == .OK { captures.append(contentsOf: panel.urls) }
    }
}

struct ScannerDevicePanel: NSViewRepresentable {
    @ObservedObject var controller: ScannerController
    func makeNSView(context: Context) -> IKScannerDeviceView {
        let view = IKScannerDeviceView(frame: .zero)
        view.delegate = controller
        view.hasDisplayModeSimple = true; view.hasDisplayModeAdvanced = true
        view.mode = .advanced; view.transferMode = .memoryBased
        view.displaysDownloadsDirectoryControl = false; view.displaysPostProcessApplicationControl = false
        view.scanControlLabel = "Digitalizar"; view.overviewControlLabel = "Pré-visualizar"
        return view
    }
    func updateNSView(_ view: IKScannerDeviceView, context: Context) {
        view.delegate = controller; view.downloadsDirectory = controller.folder
        view.documentName = "PDF-captura"
        if view.scannerDevice !== controller.selected { view.scannerDevice = controller.selected }
    }
    static func dismantleNSView(_ view: IKScannerDeviceView, coordinator: ()) {
        view.scannerDevice = nil; view.delegate = nil
    }
}

struct NativeFeaturesView: View {
    @EnvironmentObject var model: Workspace
    @StateObject private var scanner = ScannerController()
    @State private var tab = 0
    @State private var language = "pt"
    @State private var enhanceContrast = false
    @State private var running = false
    @State private var progress = 0.0
    @State private var status = ""
    @State private var cancellation: NativeCancellation?
    @State private var result: URL?
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("Digitalização e OCR", systemImage: "scanner").font(.largeTitle.bold())
            Picker("Modo", selection: $tab) { Text("Scanner").tag(0); Text("OCR no Mac").tag(1) }.pickerStyle(.segmented).disabled(running)
            if tab == 0 { ScrollView { scannerContent } } else { ocrContent }
            if running, tab == 0 { HStack { ProgressView(value: progress); Button("Cancelar") { cancellation?.cancel() } } }
            if !status.isEmpty { Text(status).font(.callout).textSelection(.enabled) }
            if let result {
                HStack {
                    Button("Abrir resultado") { model.open(url: result) }
                    Button("Mostrar no Finder") { NSWorkspace.shared.activateFileViewerSelecting([result]) }
                }
            }
        }.padding(24).onAppear { scanner.start() }.onDisappear { scanner.stop(); cancellation?.cancel() }
    }
    private var scannerContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Picker("Scanner", selection: $scanner.selectedID) {
                    Text("Selecionar dispositivo").tag("")
                    ForEach(scanner.devices, id: \.self) { device in Text(device.name ?? "Scanner").tag(scanner.identity(device)) }
                }
                Button("Importar imagens…") { scanner.importImages() }
            }
            if let folder = scanner.folder {
                ContinuityCaptureView(directory: folder, onCapture: { scanner.captures.append($0) }, onError: { scanner.error = $0 }, onBusyChanged: { scanner.importingContinuity = $0 })
                    .frame(height: 160)
                    .accessibilityLabel("Capturar com iPhone, iPad ou área de transferência")
            }
            if scanner.selected != nil { ScannerDevicePanel(controller: scanner).frame(minHeight: 280) }
            else {
                ContentUnavailableView("Conecte um scanner", systemImage: "scanner", description: Text("Scanners compatíveis com Captura de Imagem aparecem aqui. Você também pode importar imagens ou PDFs digitalizados."))
            }
            List {
                ForEach(Array(scanner.captures.enumerated()), id: \.offset) { index, url in
                    HStack {
                        Text("\(index + 1). \(url.lastPathComponent)")
                        Spacer()
                        Button { if index > 0 { scanner.captures.swapAt(index, index - 1) } } label: { Image(systemName: "arrow.up") }.disabled(index == 0).accessibilityLabel("Mover página para cima")
                        Button { if index + 1 < scanner.captures.count { scanner.captures.swapAt(index, index + 1) } } label: { Image(systemName: "arrow.down") }.disabled(index + 1 == scanner.captures.count).accessibilityLabel("Mover página para baixo")
                        Button { scanner.captures.remove(at: index) } label: { Image(systemName: "minus.circle") }.accessibilityLabel("Remover da lista")
                    }
                }
            }.frame(minHeight: 90, maxHeight: 170)
            HStack {
                Text("\(scanner.captures.count) arquivos selecionados").foregroundStyle(.secondary)
                Spacer()
                Button("Criar PDF…") { assembleScans() }.buttonStyle(.borderedProminent).disabled(scanner.captures.isEmpty || scanner.importingContinuity)
            }
            if !scanner.error.isEmpty { Text(scanner.error).foregroundStyle(.red) }
        }.disabled(running)
    }
    private var ocrContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Reconheça o texto do PDF aberto com processamento local. O aplicativo usa Apple Vision e, se esse motor falhar durante o reconhecimento, tenta o Tesseract instalado. O resultado informa qual motor foi usado.")
            Text("Use em documentos digitalizados. A reconstrução não conserva formulários, links, anotações ou assinaturas digitais. Páginas que já contêm texto podem ganhar texto duplicado; use OCRmyPDF para ignorá-las automaticamente.").font(.caption).foregroundStyle(.secondary)
            Text((model.savedDocumentURL ?? model.url)?.lastPathComponent ?? "Abra primeiro um documento no leitor.").font(.headline)
            Picker("Idioma principal", selection: $language) { Text("Português e inglês").tag("pt"); Text("Inglês").tag("en") }
            Toggle("Melhorar contraste para reconhecimento com Metal", isOn: $enhanceContrast)
            Text("O ajuste atua na imagem usada pelo OCR, preservando a aparência das páginas de saída.").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Criar PDF pesquisável…") { startOCR() }.buttonStyle(.borderedProminent).disabled(running || model.document == nil)
                if running { Button("Cancelar") { status = "Cancelando o reconhecimento…"; cancellation?.cancel() } }
            }
            if running { ProgressView(value: progress).accessibilityLabel("Progresso do OCR") }
            Spacer()
        }
    }
    private func assembleScans() {
        guard !running, !scanner.importingContinuity, !scanner.captures.isEmpty else { return }
        guard let destination = NativeOutput.destination(model: model, toolName: "Digitalização", originalURL: scanner.captures.first) else { return }
        let captures = scanner.captures
        let token = NativeCancellation(); cancellation = token
        running = true; progress = 0; status = "Montando páginas digitalizadas…"; result = nil
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let output = try ScannerPDF.assemble(urls: captures, cancellation: token) { completed, total in
                    DispatchQueue.main.async { progress = Double(completed) / Double(total); status = "Arquivo \(completed) de \(total)" }
                }
                try token.check(); try NativeOutput.write(output, to: destination)
                DispatchQueue.main.async { running = false; cancellation = nil; result = destination; status = "PDF criado com todas as páginas. As capturas originais foram preservadas." }
            } catch is CancellationError {
                DispatchQueue.main.async { running = false; cancellation = nil; status = "Montagem cancelada. As capturas foram preservadas." }
            } catch {
                let detail = error.localizedDescription
                DispatchQueue.main.async { running = false; cancellation = nil; status = "Não foi possível montar o PDF: \(detail)" }
            }
        }
    }
    private func startOCR() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard !running else { return }
        guard let document = model.document else { return }
        guard !document.isEncrypted else { status = "Desbloqueie uma cópia explicitamente antes de usar OCR nativo em um documento protegido."; return }
        // This snapshot stays in memory and is only input to CoreGraphics. The
        // complete OCR output is normalized before it can be published.
        guard document.pageCount > 0, let data = document.dataRepresentation() else { status = "Não foi possível obter as páginas."; return }
        guard let destination = NativeOutput.destination(model: model, toolName: "OCR") else { return }
        let token = NativeCancellation(); cancellation = token
        let selectedLanguage = language
        let enhance = enhanceContrast
        running = true; progress = 0; status = "Reconhecendo texto…"; result = nil
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let output = try LocalOCRPDF.create(data: data, language: selectedLanguage, enhanceContrast: enhance, cancellation: token) { completed, total in
                    DispatchQueue.main.async { progress = Double(completed) / Double(total); status = "Página \(completed) de \(total)" }
                }
                try token.check()
                try NativeOutput.write(output.data, to: destination)
                let applePages = output.pages.filter { $0.backend == "apple-vision" }.count
                let compatibilityPages = output.pages.filter { $0.backend == "tesseract" }.count
                let detail = compatibilityPages == 0
                    ? "PDF pesquisável salvo com Apple Vision."
                    : "PDF pesquisável salvo. Apple Vision: \(applePages) páginas; Tesseract local: \(compatibilityPages) páginas. O Tesseract foi usado nas páginas em que o reconhecimento Apple falhou."
                DispatchQueue.main.async { running = false; cancellation = nil; result = destination; status = detail + " Revise o reconhecimento antes de compartilhar." }
            } catch is CancellationError {
                DispatchQueue.main.async { running = false; cancellation = nil; status = "OCR cancelado. Nenhum resultado foi publicado." }
            } catch {
                let message = error.localizedDescription
                DispatchQueue.main.async { running = false; cancellation = nil; status = "Falha no OCR: \(message)" }
            }
        }
    }
}
