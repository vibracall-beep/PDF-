import AppKit
import SwiftUI
import PDFKit
import QuartzCore

/// Captures the real WindowServer-composited application surface in the native CI session.
/// NSView.cacheDisplay cannot capture all SwiftUI material or PDFKit tiled layers.
@MainActor
enum MacPreview {
    static func render(to destination: URL) throws {
        let application = NSApplication.shared
        guard !application.isRunning else {
            throw failure(1, "A prévia precisa iniciar em um processo dedicado, antes do loop principal do aplicativo.")
        }
        let previousDelegate = application.delegate
        let delegate = PreviewApplicationDelegate(destination: destination)
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        // run() owns the full AppKit launch lifecycle. Building the window inside
        // applicationDidFinishLaunching avoids rendering from SwiftUI App.init.
        application.run()
        application.delegate = previousDelegate
        guard let result = delegate.result else {
            throw failure(2, "O ciclo de captura terminou sem produzir um resultado.")
        }
        try result.get()
    }

    fileprivate static func failure(_ code: Int, _ message: String) -> NSError {
        NSError(domain: "PDF.Preview", code: code, userInfo: [NSLocalizedDescriptionKey: message])
    }

    fileprivate static func capture(_ window: NSWindow, to destination: URL) throws {
        guard window.isVisible, window.windowNumber > 0 else {
            throw failure(3, "A janela da prévia não foi registrada no WindowServer.")
        }
        window.contentView?.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
        CATransaction.flush()
        guard let content = window.contentView, content.bounds.width > 100, content.bounds.height > 100 else {
            throw failure(4, "A janela da prévia ainda não possui uma área de conteúdo válida.")
        }
        let logicalFrame = window.frame
        print("PDF preview window: frame=\(Int(logicalFrame.width))x\(Int(logicalFrame.height)); content=\(Int(content.bounds.width))x\(Int(content.bounds.height)); backingScale=\(window.backingScaleFactor)")
        let folder = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let temporary = folder.appendingPathComponent(".PDF-window-\(UUID().uuidString).png")
        defer { try? FileManager.default.removeItem(at: temporary) }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        process.arguments = ["-x", "-o", "-l", String(window.windowNumber), "-t", "png", temporary.path]
        let errors = Pipe(); process.standardError = errors; process.standardOutput = errors
        try process.run()
        let deadline = Date().addingTimeInterval(20)
        // Keep AppKit and the compositor responsive while the screenshot process works.
        while process.isRunning && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        if process.isRunning {
            process.terminate()
            throw failure(5, "A captura da janela excedeu 20 segundos. Verifique o acesso à sessão gráfica e a permissão de Gravação de Tela.")
        }
        process.waitUntilExit()
        let diagnostics = String(data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        guard process.terminationStatus == 0, FileManager.default.fileExists(atPath: temporary.path) else {
            throw failure(6, "O WindowServer não permitiu capturar a janela. A sessão gráfica deve estar ativa e autorizar a captura de tela. " + diagnostics.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        let data = try Data(contentsOf: temporary)
        guard let bitmap = NSBitmapImageRep(data: data), bitmap.pixelsWide > 0, bitmap.pixelsHigh > 0 else {
            throw failure(7, "A captura devolvida pelo WindowServer está vazia ou não é um PNG válido.")
        }
        let scaleX = Double(bitmap.pixelsWide) / logicalFrame.width
        let scaleY = Double(bitmap.pixelsHigh) / logicalFrame.height
        guard scaleX >= 0.9, scaleY >= 0.9, abs(scaleX - scaleY) < 0.05 else {
            throw failure(9, "A captura não corresponde às dimensões efetivas da janela: \(bitmap.pixelsWide)x\(bitmap.pixelsHigh) pixels para \(Int(logicalFrame.width))x\(Int(logicalFrame.height)) pontos.")
        }
        try NativeOutput.write(data, to: destination)
        print("PDF preview captured from WindowServer: \(destination.lastPathComponent); window=\(window.windowNumber); content=\(Int(content.bounds.width))x\(Int(content.bounds.height)); pixels=\(bitmap.pixelsWide)x\(bitmap.pixelsHigh)")
    }

    fileprivate static func sampleDocument() throws -> PDFDocument {
        let data = NSMutableData()
        var pageBounds = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let consumer = CGDataConsumer(data: data as CFMutableData),
              let context = CGContext(consumer: consumer, mediaBox: &pageBounds, nil) else {
            throw NSError(domain: "PDF.Preview", code: 3)
        }
        for index in 1...2 {
            context.beginPDFPage(nil)
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
            ((index == 1 ? "Um espaço para seus documentos." : "Cada detalhe, no seu ritmo.") as NSString)
                .draw(at: NSPoint(x: 48, y: 746), withAttributes: [.font: NSFont.systemFont(ofSize: 23, weight: .semibold), .foregroundColor: NSColor.systemBlue])
            let lines = index == 1
                ? ["Leia com clareza, encontre informações e marque o que importa.",
                   "O PDF reúne leitura, organização, conversão e inteligência local.",
                   "", "Selecione texto para realçar. Adicione notas ou desenhe na página.",
                   "Use as miniaturas, o sumário e os marcadores para navegar.",
                   "", "Salve uma nova cópia para preservar seu documento original."]
                : ["Escolha seus favoritos e organize as ferramentas como preferir.",
                   "Converta formatos, prepare formulários e automatize tarefas.",
                   "", "Busque evidências no documento e consulte as páginas citadas."]
            for (line, text) in lines.enumerated() {
                (text as NSString).draw(at: NSPoint(x: 48, y: CGFloat(690 - line * 27)),
                                       withAttributes: [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: NSColor.black])
            }
            ("PDF · Documento de demonstração · \(index) / 2" as NSString).draw(
                at: NSPoint(x: 48, y: 38), withAttributes: [.font: NSFont.systemFont(ofSize: 10), .foregroundColor: NSColor.gray])
            NSGraphicsContext.restoreGraphicsState()
            context.endPDFPage()
        }
        context.closePDF()
        guard let document = PDFDocument(data: data as Data), document.pageCount == 2 else {
            throw NSError(domain: "PDF.Preview", code: 4)
        }
        return document
    }
}

@MainActor private final class PreviewApplicationDelegate: NSObject, NSApplicationDelegate {
    let destination: URL
    var result: Result<Void, Error>?
    private var model: Workspace?
    private var window: NSWindow?
    init(destination: URL) { self.destination = destination }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Return from the launch notification before constructing and activating views.
        DispatchQueue.main.async { [weak self] in self?.showWindow() }
    }

    private func showWindow() {
        let model = Workspace()
        let view = ContentView().environmentObject(model).frame(minWidth: 1050, minHeight: 720)
        let host = NSHostingView(rootView: view)
        let rectangle = NSRect(x: 0, y: 0, width: 1280, height: 860)
        let window = NSWindow(contentRect: rectangle, styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "PDF"
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.setContentSize(rectangle.size)
        if let screen = NSScreen.main {
            window.setFrameTopLeftPoint(NSPoint(x: screen.frame.minX + 20, y: screen.frame.maxY - 30))
        }
        self.model = model; self.window = window
        NSApplication.shared.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        host.layoutSubtreeIfNeeded()
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.captureHome() }
    }

    private func captureHome() {
        guard let window, let model else { finish(.failure(MacPreview.failure(8, "A janela de prévia foi encerrada."))); return }
        do {
            try MacPreview.capture(window, to: destination)
            model.document = try MacPreview.sampleDocument()
            model.url = URL(fileURLWithPath: "/Amostras/Guia do PDF.pdf")
            model.section = "Leitor"
            window.contentView?.layoutSubtreeIfNeeded()
            window.displayIfNeeded()
            CATransaction.flush()
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in self?.captureReader() }
        } catch { finish(.failure(error)) }
    }

    private func captureReader() {
        guard let window else { finish(.failure(MacPreview.failure(8, "A janela de prévia foi encerrada."))); return }
        do {
            let readerDestination = destination.deletingPathExtension().appendingPathExtension("leitor.png")
            try MacPreview.capture(window, to: readerDestination)
            finish(.success(Void()))
        } catch { finish(.failure(error)) }
    }

    private func finish(_ outcome: Result<Void, Error>) {
        guard result == nil else { return }
        result = outcome
        window?.orderOut(nil)
        NSApplication.shared.stop(nil)
        // Wake the event loop so run() returns even when a runner receives no UI events.
        if let event = NSEvent.otherEvent(with: .applicationDefined, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil, subtype: 0, data1: 0, data2: 0) {
            NSApplication.shared.postEvent(event, atStart: false)
        }
    }
}
