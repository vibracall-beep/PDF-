import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers
import ImageIO
import Darwin

/// Uses the public AppKit Services requestor protocol for Continuity Camera.
/// AppKit owns discovery, pairing and the actual capture UI. No camera controls or
/// menu selectors are synthesized by the application.
struct ContinuityCaptureView: NSViewRepresentable {
    let directory: URL
    let onCapture: (URL) -> Void
    let onError: (String) -> Void
    var onBusyChanged: (Bool) -> Void = { _ in }

    func makeNSView(context: Context) -> ContinuityCaptureNSView {
        ContinuityCaptureNSView(directory: directory, onCapture: onCapture, onError: onError, onBusyChanged: onBusyChanged)
    }
    func updateNSView(_ view: ContinuityCaptureNSView, context: Context) {
        view.directory = directory
        view.onCapture = onCapture
        view.onError = onError
        view.onBusyChanged = onBusyChanged
    }
    static func dismantleNSView(_ view: ContinuityCaptureNSView, coordinator: ()) {
        view.cancelPendingImports()
    }
}

@MainActor final class ContinuityCaptureNSView: NSView, @MainActor NSServicesMenuRequestor {
    var directory: URL
    var onCapture: (URL) -> Void
    var onError: (String) -> Void
    var onBusyChanged: (Bool) -> Void
    private enum Payload {
        case data(Data, Bool)
        case file(URL)
        var retainedBytes: Int { if case .data(let data, _) = self { return data.count }; return 0 }
    }
    private struct PendingImport {
        let payload: Payload
        let directory: URL
        let onCapture: (URL) -> Void
        let onError: (String) -> Void
    }
    private var pending: [PendingImport] = []
    private var retainedBytes = 0
    private var processing: Task<Void, Never>?
    private static let captureMenuIdentifier = NSUserInterfaceItemIdentifier("local.pdf.continuity-menu")
    private static let supportedTypes: [NSPasteboard.PasteboardType] = {
        let types: [NSPasteboard.PasteboardType] = [.pdf, .png, .tiff, NSPasteboard.PasteboardType(UTType.jpeg.identifier), NSPasteboard.PasteboardType(UTType.heic.identifier)]
        return types + NSImage.imageTypes.map { NSPasteboard.PasteboardType($0) }.filter { !types.contains($0) }
    }()
    private let detail = NSTextField(wrappingLabelWithString: "Use o menu Captura ou clique com o botão direito nesta área. O macOS mostra os dispositivos compatíveis disponíveis.")

    init(directory: URL, onCapture: @escaping (URL) -> Void, onError: @escaping (String) -> Void, onBusyChanged: @escaping (Bool) -> Void = { _ in }) {
        self.directory = directory
        self.onCapture = onCapture
        self.onError = onError
        self.onBusyChanged = onBusyChanged
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 14
        layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        setAccessibilityElement(true)
        setAccessibilityLabel("Importar foto ou digitalização do iPhone ou iPad")
        let heading = NSTextField(labelWithString: "iPhone e iPad · Câmera de Continuidade")
        heading.font = .systemFont(ofSize: 14, weight: .semibold)
        detail.font = .systemFont(ofSize: 12)
        detail.textColor = .secondaryLabelColor
        let menuButton = NSButton(title: "Abrir menu de captura", target: self, action: #selector(showCaptureMenu(_:)))
        let pasteButton = NSButton(title: "Colar captura", target: self, action: #selector(pasteCapture(_:)))
        let importButton = NSButton(title: "Importar arquivo…", target: self, action: #selector(importCapture(_:)))
        let cancelButton = NSButton(title: "Cancelar importação", target: self, action: #selector(cancelCapture(_:)))
        [menuButton, pasteButton, importButton, cancelButton].forEach { $0.bezelStyle = .rounded }
        let buttons = NSStackView(views: [menuButton, pasteButton, importButton, cancelButton])
        buttons.orientation = .horizontal
        buttons.spacing = 8
        let stack = NSStackView(views: [heading, detail, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 10
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -16),
            stack.topAnchor.constraint(equalTo: topAnchor, constant: 16),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: bottomAnchor, constant: -16)
        ])
        NSApp.registerServicesMenuSendTypes([], returnTypes: Self.supportedTypes)
    }
    required init?(coder: NSCoder) { return nil }
    override var acceptsFirstResponder: Bool { true }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard window != nil else { return }
        installCaptureMenu()
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        super.mouseDown(with: event)
    }
    override func rightMouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        super.rightMouseDown(with: event)
    }
    override func menu(for event: NSEvent) -> NSMenu? { captureMenu() }

    override func validRequestor(forSendType sendType: NSPasteboard.PasteboardType?, returnType: NSPasteboard.PasteboardType?) -> Any? {
        if sendType == nil, let returnType, Self.supportedTypes.contains(returnType) { return self }
        return super.validRequestor(forSendType: sendType, returnType: returnType)
    }

    /// This exact selector is declared by NSServicesMenuRequestor in AppKit.
    /// Services dispatches to this first-responder NSView on AppKit's UI thread.
    /// The explicitly MainActor-isolated conformance preserves that contract.
    func readSelection(from pasteboard: NSPasteboard) -> Bool {
        dispatchPrecondition(condition: .onQueue(.main))
        let items = pasteboard.pasteboardItems ?? []
        guard items.count <= 32 else {
            onError("Importe no máximo 32 capturas por vez.")
            return false
        }
        var captures: [(Data, NSPasteboard.PasteboardType)] = []
        var totalBytes = 0
        for item in items {
            guard let type = Self.supportedTypes.first(where: { item.types.contains($0) }), let data = item.data(forType: type) else { continue }
            guard data.count <= ContinuityCaptureFile.maximumBytes else {
                onError("Uma captura excede o limite de 128 MB.")
                return false
            }
            totalBytes += data.count
            guard totalBytes <= ContinuityCaptureFile.maximumBytes else {
                onError("As capturas excedem 128 MB no total. Importe em grupos menores.")
                return false
            }
            captures.append((data, type))
        }
        if captures.isEmpty, let type = pasteboard.availableType(from: Self.supportedTypes), let data = pasteboard.data(forType: type), data.count <= ContinuityCaptureFile.maximumBytes {
            captures.append((data, type))
        }
        guard !captures.isEmpty else {
            onError("A área de transferência não contém um PDF ou uma imagem compatível.")
            return false
        }
        return enqueue(captures.map { .data($0.0, $0.1 == .pdf) })
    }

    @discardableResult private func enqueue(_ payloads: [Payload]) -> Bool {
        let incomingBytes = payloads.reduce(0) { $0 + $1.retainedBytes }
        guard pending.count + payloads.count + (processing == nil ? 0 : 1) <= 32,
              retainedBytes + incomingBytes <= ContinuityCaptureFile.maximumBytes else {
            onError("Aguarde as capturas atuais terminarem antes de importar mais arquivos.")
            return false
        }
        retainedBytes += incomingBytes
        pending += payloads.map { PendingImport(payload: $0, directory: directory, onCapture: onCapture, onError: onError) }
        guard processing == nil else { return true }
        detail.stringValue = "Importando capturas na ordem recebida…"
        onBusyChanged(true)
        // A single task drains one explicit FIFO. Actor serialization alone does
        // not guarantee that separately created tasks preserve pasteboard order.
        processing = Task { @MainActor [self] in
            var successes = 0
            var failures = 0
            defer {
                processing = nil
                onBusyChanged(false)
                if Task.isCancelled { detail.stringValue = "Importação cancelada. \(successes) captura(s) já concluída(s) foram preservadas." }
                else if failures > 0 { detail.stringValue = "\(successes) captura(s) importada(s); \(failures) falha(s). Verifique a mensagem de erro." }
                else { detail.stringValue = "\(successes) captura(s) pronta(s) para montar o PDF." }
            }
            while !pending.isEmpty && !Task.isCancelled {
                let job = pending.removeFirst()
                defer { retainedBytes -= job.payload.retainedBytes }
                do {
                    let url: URL
                    switch job.payload {
                    case .data(let data, let isPDF):
                        url = try await ContinuityCaptureProcessor.shared.save(data, isPDF: isPDF, directory: job.directory)
                    case .file(let source):
                        url = try await ContinuityCaptureProcessor.shared.importFile(source, directory: job.directory)
                    }
                    // A committed capture is always delivered, even if cancellation
                    // arrived immediately after atomic publication.
                    successes += 1
                    job.onCapture(url)
                } catch is CancellationError {
                    break
                } catch {
                    failures += 1
                    job.onError(error.localizedDescription)
                }
            }
            retainedBytes -= pending.reduce(0) { $0 + $1.payload.retainedBytes }
            pending.removeAll()
        }
        return true
    }

    func cancelPendingImports() {
        processing?.cancel()
    }

    private func captureMenu() -> NSMenu {
        let menu = NSMenu(title: "Captura")
        menu.allowsContextMenuPlugIns = true
        // The public identifier asks AppKit to populate a genuine Continuity
        // Camera item. Its content and availability are controlled by macOS.
        let systemCapture = NSMenuItem(title: "Importar do iPhone ou iPad", action: nil, keyEquivalent: "")
        systemCapture.identifier = NSMenuItem.importFromDeviceIdentifier
        menu.addItem(systemCapture)
        menu.addItem(.separator())
        let paste = NSMenuItem(title: "Colar captura", action: #selector(pasteCapture(_:)), keyEquivalent: "")
        paste.target = self
        menu.addItem(paste)
        let imported = NSMenuItem(title: "Importar arquivo…", action: #selector(importCapture(_:)), keyEquivalent: "")
        imported.target = self
        menu.addItem(imported)
        return menu
    }

    private func installCaptureMenu() {
        guard let main = NSApp.mainMenu else { return }
        // A separate identified top-level item avoids guessing localized File
        // menu names or replacing menus owned by SwiftUI.
        if let existing = main.items.first(where: { $0.identifier == Self.captureMenuIdentifier }) {
            existing.submenu = captureMenu()
            return
        }
        let item = NSMenuItem(title: "Captura", action: nil, keyEquivalent: "")
        item.identifier = Self.captureMenuIdentifier
        item.submenu = captureMenu()
        main.insertItem(item, at: main.items.count > 1 ? main.items.count - 1 : main.items.count)
    }

    @objc private func showCaptureMenu(_ sender: Any?) {
        window?.makeFirstResponder(self)
        installCaptureMenu()
        if let event = NSApp.currentEvent { NSMenu.popUpContextMenu(captureMenu(), with: event, for: self) }
        else { captureMenu().popUp(positioning: nil, at: NSPoint(x: 16, y: 16), in: self) }
    }
    @objc private func cancelCapture(_ sender: Any?) { cancelPendingImports() }
    @objc private func pasteCapture(_ sender: Any?) {
        window?.makeFirstResponder(self)
        _ = readSelection(from: .general)
    }
    @objc private func importCapture(_ sender: Any?) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.pdf, .image]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        enqueue([.file(url)])
    }
}

/// Serial decoding avoids allocating several full-resolution scans at once.
private actor ContinuityCaptureProcessor {
    static let shared = ContinuityCaptureProcessor()
    func save(_ data: Data, isPDF: Bool, directory: URL) throws -> URL {
        try autoreleasepool { try ContinuityCaptureFile.save(data, isPDF: isPDF, directory: directory) }
    }
    func importFile(_ url: URL, directory: URL) throws -> URL {
        try Task.checkCancellation()
        let data = try CaptureImageDecoder.readData(from: url, maximumBytes: ContinuityCaptureFile.maximumBytes)
        let isPDF = data.prefix(1024).range(of: Data("%PDF-".utf8)) != nil
        return try save(data, isPDF: isPDF, directory: directory)
    }
}

/// File decoding is separate from the view so CI can exercise the actual
/// incoming PDF/image path without pretending to have a paired iPhone.
enum ContinuityCaptureFile {
    static let maximumBytes = 128 * 1024 * 1024
    static func save(_ data: Data, isPDF: Bool, directory: URL) throws -> URL {
        try Task.checkCancellation()
        guard !data.isEmpty, data.count <= maximumBytes else { throw CaptureError.size }
        let payload: Data
        let ext: String
        if isPDF {
            // Refuse obvious non-PDF pasteboard data before invoking CoreGraphics.
            // Permit a header within the first 1 KB, as PDF readers commonly do;
            // PDFKit still validates the complete document and its protection.
            guard data.prefix(1024).range(of: Data("%PDF-".utf8)) != nil else { throw CaptureError.pdf }
            guard let document = PDFDocument(data: data), document.pageCount > 0, !document.isEncrypted else { throw CaptureError.pdf }
            payload = data
            ext = "pdf"
        } else {
            guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { throw CaptureError.image }
            let count = try CaptureImageDecoder.frameCount(source)
            if count == 1 {
                let image = try CaptureImageDecoder.frame(source, index: 0)
                let encoded = NSMutableData()
                guard let writer = CGImageDestinationCreateWithData(encoded, UTType.png.identifier as CFString, 1, nil) else { throw CaptureError.image }
                CGImageDestinationAddImage(writer, image, nil)
                guard CGImageDestinationFinalize(writer) else { throw CaptureError.image }
                payload = encoded as Data
                ext = "png"
            } else {
                // Multipage TIFF/HEIF captures must not silently lose every page
                // after frame zero. Stream each decoded frame into a PDF page.
                let encoded = NSMutableData()
                guard let consumer = CGDataConsumer(data: encoded as CFMutableData),
                      let context = CGContext(consumer: consumer, mediaBox: nil, nil) else { throw CaptureError.image }
                var closed = false
                defer { if !closed { context.closePDF() } }
                for index in 0..<count {
                    try autoreleasepool {
                        let image = try CaptureImageDecoder.frame(source, index: index)
                        var bounds = CGRect(origin: .zero, size: CaptureImageDecoder.pageSize(source, index: index, image: image))
                        let box = NSData(bytes: &bounds, length: MemoryLayout<CGRect>.size)
                        context.beginPDFPage([kCGPDFContextMediaBox as String: box] as CFDictionary)
                        context.draw(image, in: bounds)
                        context.endPDFPage()
                    }
                    guard encoded.length <= 512 * 1024 * 1024 else { throw CaptureError.outputSize }
                }
                context.closePDF(); closed = true
                guard encoded.length <= 512 * 1024 * 1024 else { throw CaptureError.outputSize }
                payload = encoded as Data
                ext = "pdf"
            }
        }
        try Task.checkCancellation()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let output = directory.appendingPathComponent("Captura-\(UUID().uuidString)").appendingPathExtension(ext)
        try NativeOutput.write(payload, to: output)
        return output
    }
    private enum CaptureError: LocalizedError {
        case size, outputSize, pdf, image, dimensions
        var errorDescription: String? {
            switch self {
            case .size: return "A captura está vazia ou excede 128 MB."
            case .outputSize: return "O PDF das capturas excede 512 MB. Importe um grupo menor de páginas."
            case .pdf: return "A captura não é um PDF legível ou está protegida por senha."
            case .image: return "Não foi possível decodificar a imagem recebida."
            case .dimensions: return "A imagem excede o limite de dimensões para uma captura."
            }
        }
    }
}

/// Shared ImageIO normalization for Continuity Camera and scanner assembly.
/// Frames are decoded one at a time and EXIF orientation is applied exactly once.
enum CaptureImageDecoder {
    static func readData(from url: URL, maximumBytes: Int) throws -> Data {
        guard maximumBytes > 0, maximumBytes < Int.max else { throw DecodeError.source }
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard descriptor >= 0 else { throw DecodeError.source }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),
              info.st_size > 0, info.st_size <= Int64(maximumBytes) else { throw DecodeError.source }
        let data = try handle.read(upToCount: maximumBytes + 1) ?? Data()
        guard !data.isEmpty, data.count <= maximumBytes else { throw DecodeError.source }
        return data
    }
    static func frameCount(_ source: CGImageSource) throws -> Int {
        let count = CGImageSourceGetCount(source)
        guard (1...512).contains(count) else { throw DecodeError.frames }
        return count
    }
    static func frame(_ source: CGImageSource, index: Int) throws -> CGImage {
        try Task.checkCancellation()
        guard index >= 0, index < (try frameCount(source)),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let height = properties[kCGImagePropertyPixelHeight] as? NSNumber else { throw DecodeError.source }
        let w = width.doubleValue, h = height.doubleValue
        guard w.isFinite, h.isFinite, w > 0, h > 0, w <= 30_000, h <= 30_000, w * h <= 100_000_000 else { throw DecodeError.dimensions }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: Int(max(w, h))
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, index, options as CFDictionary) else { throw DecodeError.source }
        try Task.checkCancellation()
        return image
    }
    static func pageSize(_ source: CGImageSource, index: Int, image: CGImage) -> CGSize {
        let properties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any]
        let rawDPI = (properties?[kCGImagePropertyDPIWidth] as? NSNumber)?.doubleValue ?? 72
        let dpi = rawDPI.isFinite && (10...2400).contains(rawDPI) ? rawDPI : 72
        let width = Double(image.width) * 72 / dpi
        let height = Double(image.height) * 72 / dpi
        let scale = min(1, 14_400 / max(width, height))
        return CGSize(width: width * scale, height: height * scale)
    }
    enum DecodeError: LocalizedError {
        case source, dimensions, frames
        var errorDescription: String? {
            switch self {
            case .source: return "Escolha uma imagem ou PDF comum e legível, com até 128 MB."
            case .dimensions: return "A imagem excede 30.000 pixels em um eixo ou 100 milhões de pixels por quadro."
            case .frames: return "A captura precisa conter de 1 a 512 quadros. Divida arquivos maiores antes de importar."
            }
        }
    }
}

/// Tests capture decoding with generated fixtures, independently of a physical
/// scanner or paired phone. It verifies frame preservation and EXIF handling.
enum CaptureImportAuditChecks {
    static func run(in root: URL) throws {
        func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            guard condition() else { throw NSError(domain: "PDF.CaptureAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func makeImage(width: Int, height: Int, red: CGFloat, blue: CGFloat) throws -> CGImage {
            guard let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                          space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
                throw CaptureImageDecoder.DecodeError.source
            }
            context.setFillColor(CGColor(red: red, green: 0, blue: blue, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: width, height: height))
            guard let result = context.makeImage() else { throw CaptureImageDecoder.DecodeError.source }
            return result
        }
        let directory = root.appendingPathComponent("capture-audit", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let encoded = NSMutableData()
        guard let writer = CGImageDestinationCreateWithData(encoded, UTType.tiff.identifier as CFString, 2, nil) else { throw CaptureImageDecoder.DecodeError.source }
        let first = try makeImage(width: 40, height: 60, red: 1, blue: 0)
        let second = try makeImage(width: 80, height: 30, red: 0, blue: 1)
        CGImageDestinationAddImage(writer, first, [kCGImagePropertyOrientation: 6, kCGImagePropertyDPIWidth: 144, kCGImagePropertyDPIHeight: 144] as CFDictionary)
        CGImageDestinationAddImage(writer, second, [kCGImagePropertyOrientation: 1, kCGImagePropertyDPIWidth: 144, kCGImagePropertyDPIHeight: 144] as CFDictionary)
        try require(CGImageDestinationFinalize(writer), "Não foi possível gerar TIFF com várias páginas.")
        guard let source = CGImageSourceCreateWithData(encoded as CFData, nil) else { throw CaptureImageDecoder.DecodeError.source }
        let frameCount = try CaptureImageDecoder.frameCount(source)
        try require(frameCount == 2, "O TIFF de teste precisa ter duas páginas.")
        let oriented = try CaptureImageDecoder.frame(source, index: 0)
        try require(oriented.width == 60 && oriented.height == 40, "A orientação EXIF da captura não foi aplicada.")
        let output = try ContinuityCaptureFile.save(encoded as Data, isPDF: false, directory: directory)
        guard let document = PDFDocument(url: output), let page0 = document.page(at: 0), let page1 = document.page(at: 1) else {
            throw CaptureImageDecoder.DecodeError.source
        }
        try require(output.pathExtension == "pdf" && document.pageCount == 2, "A captura TIFF perdeu páginas.")
        let bounds0 = page0.bounds(for: .mediaBox), bounds1 = page1.bounds(for: .mediaBox)
        try require(abs(bounds0.width / bounds0.height - 1.5) < 0.01 && abs(bounds1.width / bounds1.height - (80.0 / 30.0)) < 0.01,
                    "As páginas da captura mudaram de ordem ou orientação.")
        let fifo = directory.appendingPathComponent("special.tiff")
        try require(mkfifo(fifo.path, 0o600) == 0, "Não foi possível preparar o arquivo especial de teste.")
        var refusedFIFO = false
        do { _ = try CaptureImageDecoder.readData(from: fifo, maximumBytes: 1024) } catch { refusedFIFO = true }
        try require(refusedFIFO, "A importação de captura aceitou um arquivo especial.")
    }
}
