import AppKit
import SwiftUI
import PDFKit
import QuartzCore
import ScreenCaptureKit

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

    fileprivate static func capture(_ window: NSWindow, to destination: URL) async throws {
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
        let folder = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let probe = folder.appendingPathComponent("PDF-write-probe-\(UUID().uuidString).tmp")
        do {
            defer { try? FileManager.default.removeItem(at: probe) }
            try Data("PDF preview write check".utf8).write(to: probe, options: .withoutOverwriting)
        } catch {
            throw failure(10, "O diretório de saída não aceitou uma gravação de diagnóstico: \(error.localizedDescription)")
        }
        let globalAccess = CGPreflightScreenCaptureAccess()
        print("PDF preview diagnostics: destinationWritable=true; globalCapturePreflight=\(globalAccess); captureScope=currentProcess; frame=\(Int(logicalFrame.width))x\(Int(logicalFrame.height)); content=\(Int(content.bounds.width))x\(Int(content.bounds.height)); backingScale=\(window.backingScaleFactor)")
        // This public API exposes only content the current process may capture
        // under the operating system's own-process rules. It neither asks for
        // global capture access nor changes TCC settings or enumerates other apps.
        let available: SCShareableContent
        do { available = try await SCShareableContent.currentProcess }
        catch {
            let error = error as NSError
            throw failure(11, "O sistema não disponibilizou as janelas capturáveis deste processo. ScreenCaptureKit \(error.domain) código \(error.code): \(error.localizedDescription)")
        }
        guard let ownWindow = available.windows.first(where: { $0.windowID == CGWindowID(window.windowNumber) }) else {
            throw failure(12, "A própria janela PDF não consta no conteúdo que o sistema autoriza este processo a capturar. Não foi realizada captura de outra janela.")
        }
        if let owner = ownWindow.owningApplication, owner.processID != ProcessInfo.processInfo.processIdentifier {
            throw failure(15, "O WindowServer associou o ID selecionado a outro processo. A captura foi recusada.")
        }
        let filter = SCContentFilter(desktopIndependentWindow: ownWindow)
        let configuration = SCStreamConfiguration()
        let scale = CGFloat(filter.pointPixelScale)
        configuration.width = max(1, Int(ceil(filter.contentRect.width * scale)))
        configuration.height = max(1, Int(ceil(filter.contentRect.height * scale)))
        configuration.showsCursor = false
        configuration.includeChildWindows = false
        configuration.ignoreShadowsSingleWindow = true
        configuration.scalesToFit = false
        print("PDF preview own-window filter: window=\(ownWindow.windowID); onScreen=\(ownWindow.isOnScreen); points=\(Int(filter.contentRect.width))x\(Int(filter.contentRect.height)); requestedPixels=\(configuration.width)x\(configuration.height)")
        let image: CGImage
        do { image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) }
        catch {
            let error = error as NSError
            throw failure(13, "A captura da própria janela falhou. ScreenCaptureKit \(error.domain) código \(error.code): \(error.localizedDescription)")
        }
        guard image.width == configuration.width, image.height == configuration.height, image.width > 100, image.height > 100 else {
            throw failure(14, "O WindowServer retornou dimensões incompatíveis com o filtro da própria janela: \(image.width)x\(image.height).")
        }
        let bitmap = NSBitmapImageRep(cgImage: image)
        guard let data = bitmap.representation(using: .png, properties: [:]) else {
            throw failure(7, "A captura real da janela não pôde ser codificada como PNG.")
        }
        try NativeOutput.write(data, to: destination)
        print("PDF preview captured from WindowServer via ScreenCaptureKit: \(destination.lastPathComponent); window=\(window.windowNumber); content=\(Int(content.bounds.width))x\(Int(content.bounds.height)); pixels=\(image.width)x\(image.height)")
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
    private let suiteName = "PDF-preview-" + UUID().uuidString
    private var defaults: UserDefaults?
    private var preferences: AppearancePreferences?
    init(destination: URL) { self.destination = destination }

    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.main.async { [weak self] in self?.showWindow() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self] in
            guard let self, self.result == nil else { return }
            self.finish(.failure(MacPreview.failure(5, "A captura das próprias janelas excedeu 120 segundos. Nenhum fallback de bitmap foi usado.")))
        }
    }

    private func showWindow() {
        guard let defaults = UserDefaults(suiteName:suiteName) else {
            finish(.failure(MacPreview.failure(16, "Não foi possível isolar as preferências da prévia."))); return
        }
        self.defaults = defaults
        let preferences = AppearancePreferences(defaults:defaults)
        preferences.state.colorScheme = "light"
        self.preferences = preferences
        let model = Workspace()
        self.model = model
        let window = NSWindow(contentRect:NSRect(x:0,y:0,width:1050,height:720),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title = "PDF"
        window.isReleasedWhenClosed = false
        self.window = window
        display(ContentView(),size:NSSize(width:1050,height:720))
        NSApplication.shared.activate(ignoringOtherApps:true)
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        Task { @MainActor in
            do { try await captureSequence(); finish(.success(Void())) }
            catch { finish(.failure(error)) }
        }
    }

    private func display<V:View>(_ view:V,size:NSSize) {
        guard let window,let model,let preferences,let defaults else { return }
        let root = view.environmentObject(model).environmentObject(preferences).defaultAppStorage(defaults)
            .tint(preferences.accent).preferredColorScheme(preferences.preferredScheme)
        window.contentView = NSHostingView(rootView:root)
        window.appearance = NSAppearance(named:preferences.state.colorScheme == "dark" ? .darkAqua : .aqua)
        window.setContentSize(size)
        if let screen = NSScreen.main {
            window.setFrameTopLeftPoint(NSPoint(x:screen.frame.minX+20,y:screen.frame.maxY-30))
        }
        window.contentView?.layoutSubtreeIfNeeded()
        window.displayIfNeeded()
    }

    private func capture(_ name:String? = nil) async throws {
        guard let window else { throw MacPreview.failure(8, "A janela da prévia foi encerrada.") }
        // Give AppKit, PDFKit tiles and SwiftUI transitions a full settled frame.
        try await Task.sleep(for:.seconds(1.5))
        let path = name.map { destination.deletingPathExtension().appendingPathExtension($0 + ".png") } ?? destination
        try await MacPreview.capture(window,to:path)
    }

    private func captureSequence() async throws {
        guard let model,let preferences else { throw MacPreview.failure(8, "A prévia não foi iniciada.") }
        try await capture()
        model.document = try MacPreview.sampleDocument()
        model.url = URL(fileURLWithPath:"/Amostras/Guia do PDF.pdf")
        model.section = "Leitor"
        try await capture("leitor")
        for (tab,name) in [("Aparência","personalizar"),("Ferramentas","ferramentas"),("Navegação","navegacao"),("Leitor","opcoes-leitura"),("Arquivos","arquivos")] {
            display(CustomizationView(closable:false,initialTab:tab),size:NSSize(width:850,height:690))
            try await capture(name)
        }
        preferences.state.colorScheme = "dark"
        preferences.state.accentHex = "#AF52DE"
        preferences.state.showCategoryLabels = true
        model.section = "Início"
        display(ContentView(),size:NSSize(width:1050,height:720))
        try await capture("escuro")
        preferences.applyPreset("focus")
        preferences.state.colorScheme = "light"
        preferences.state.accentHex = "#248A3D"
        preferences.state.sidebarStyle = "icons"
        preferences.state.toolOrder = ["ocr","merge","word","summary"]
        preferences.state.toolTitles["merge"] = "Reunir meus documentos"
        preferences.state.toolIcons["merge"] = "folder.badge.plus"
        display(ContentView(),size:NSSize(width:1050,height:720))
        try await capture("lista")
        preferences.reset()
        preferences.state.colorScheme = "light"
        if let watermark = tools.first(where:{$0.id == "watermark"}) {
            display(ToolConfigurationView(tool:watermark),size:NSSize(width:690,height:730))
            try await capture("configuracao-ferramenta")
        }
    }

    private func finish(_ outcome:Result<Void,Error>) {
        guard result == nil else { return }
        result = outcome
        window?.orderOut(nil)
        defaults?.removePersistentDomain(forName:suiteName)
        NSApplication.shared.stop(nil)
        if let event = NSEvent.otherEvent(with:.applicationDefined,location:.zero,modifierFlags:[],timestamp:0,windowNumber:0,context:nil,subtype:0,data1:0,data2:0) {
            NSApplication.shared.postEvent(event,atStart:false)
        }
    }
}
