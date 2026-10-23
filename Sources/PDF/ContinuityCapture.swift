import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers
import ImageIO

/// Uses the public AppKit Services requestor protocol for Continuity Camera.
/// AppKit owns discovery, pairing and the actual capture UI. No camera controls or
/// menu selectors are synthesized by the application.
struct ContinuityCaptureView: NSViewRepresentable {
    let directory: URL
    let onCapture: (URL) -> Void
    let onError: (String) -> Void

    func makeNSView(context: Context) -> ContinuityCaptureNSView {
        ContinuityCaptureNSView(directory: directory, onCapture: onCapture, onError: onError)
    }
    func updateNSView(_ view: ContinuityCaptureNSView, context: Context) {
        view.directory = directory
        view.onCapture = onCapture
        view.onError = onError
    }
}

@MainActor final class ContinuityCaptureNSView: NSView, NSServicesMenuRequestor {
    var directory: URL
    var onCapture: (URL) -> Void
    var onError: (String) -> Void
    private static let captureMenuIdentifier = NSUserInterfaceItemIdentifier("local.pdf.continuity-menu")
    private static let supportedTypes: [NSPasteboard.PasteboardType] = {
        let types: [NSPasteboard.PasteboardType] = [.pdf, .png, .tiff, NSPasteboard.PasteboardType(UTType.jpeg.identifier), NSPasteboard.PasteboardType(UTType.heic.identifier)]
        return types + NSImage.imageTypes.map { NSPasteboard.PasteboardType($0) }.filter { !types.contains($0) }
    }()
    private let detail = NSTextField(wrappingLabelWithString: "Use o menu Captura ou clique com o botão direito nesta área. O macOS mostra os dispositivos compatíveis disponíveis.")

    init(directory: URL, onCapture: @escaping (URL) -> Void, onError: @escaping (String) -> Void) {
        self.directory = directory
        self.onCapture = onCapture
        self.onError = onError
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
        [menuButton, pasteButton, importButton].forEach { $0.bezelStyle = .rounded }
        let buttons = NSStackView(views: [menuButton, pasteButton, importButton])
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
    func readSelection(from pasteboard: NSPasteboard) -> Bool {
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
        for (data, type) in captures { receive(data: data, type: type) }
        return true
    }

    private func receive(data: Data, type: NSPasteboard.PasteboardType) {
        let destination = directory
        let isPDF = type == .pdf
        detail.stringValue = "Recebendo captura…"
        Task { @MainActor [weak self] in
            do {
                let url = try await ContinuityCaptureProcessor.shared.save(data, isPDF: isPDF, directory: destination)
                self?.onCapture(url)
                self?.detail.stringValue = "Captura recebida. Você pode importar mais páginas ou gerar o PDF."
            } catch {
                self?.onError(error.localizedDescription)
                self?.detail.stringValue = "Não foi possível importar a captura. Tente novamente ou importe um arquivo."
            }
        }
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
        let destination = directory
        detail.stringValue = "Importando arquivo…"
        Task { @MainActor [weak self] in
            do {
                let output = try await ContinuityCaptureProcessor.shared.importFile(url, directory: destination)
                self?.onCapture(output)
                self?.detail.stringValue = "Arquivo importado. O original foi preservado."
            } catch { self?.onError(error.localizedDescription) }
        }
    }
}

/// Serial decoding avoids allocating several full-resolution scans at once.
private actor ContinuityCaptureProcessor {
    static let shared = ContinuityCaptureProcessor()
    func save(_ data: Data, isPDF: Bool, directory: URL) throws -> URL {
        try autoreleasepool { try ContinuityCaptureFile.save(data, isPDF: isPDF, directory: directory) }
    }
    func importFile(_ url: URL, directory: URL) throws -> URL {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: ContinuityCaptureFile.maximumBytes + 1) ?? Data()
        return try save(data, isPDF: url.pathExtension.lowercased() == "pdf", directory: directory)
    }
}

/// File decoding is separate from the view so CI can exercise the actual
/// incoming PDF/image path without pretending to have a paired iPhone.
enum ContinuityCaptureFile {
    static let maximumBytes = 128 * 1024 * 1024
    static func save(_ data: Data, isPDF: Bool, directory: URL) throws -> URL {
        guard !data.isEmpty, data.count <= maximumBytes else { throw CaptureError.size }
        let payload: Data
        let ext: String
        if isPDF {
            guard let document = PDFDocument(data: data), document.pageCount > 0, !document.isEncrypted else { throw CaptureError.pdf }
            payload = data
            ext = "pdf"
        } else {
            guard let source = CGImageSourceCreateWithData(data as CFData, nil), CGImageSourceGetCount(source) > 0,
                  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
                  let height = properties[kCGImagePropertyPixelHeight] as? NSNumber else { throw CaptureError.image }
            let w = width.doubleValue, h = height.doubleValue
            guard w.isFinite, h.isFinite, w > 0, h > 0, w <= 30_000, h <= 30_000, w * h <= 100_000_000 else { throw CaptureError.dimensions }
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: Int(max(w, h))
            ]
            guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { throw CaptureError.image }
            let encoded = NSMutableData()
            guard let writer = CGImageDestinationCreateWithData(encoded, UTType.png.identifier as CFString, 1, nil) else { throw CaptureError.image }
            CGImageDestinationAddImage(writer, image, nil)
            guard CGImageDestinationFinalize(writer) else { throw CaptureError.image }
            payload = encoded as Data
            ext = "png"
        }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let output = directory.appendingPathComponent("Captura-\(UUID().uuidString)").appendingPathExtension(ext)
        try NativeOutput.write(payload, to: output)
        return output
    }
    private enum CaptureError: LocalizedError {
        case size, pdf, image, dimensions
        var errorDescription: String? {
            switch self {
            case .size: return "A captura está vazia ou excede 128 MB."
            case .pdf: return "A captura não é um PDF legível ou está protegida por senha."
            case .image: return "Não foi possível decodificar a imagem recebida."
            case .dimensions: return "A imagem excede o limite de dimensões para uma captura."
            }
        }
    }
}
