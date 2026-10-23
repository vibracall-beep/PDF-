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

    fileprivate static func sampleDocument(title:String = "Um espaço para seus documentos.") throws -> PDFDocument {
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
            ((index == 1 ? title : "Cada detalhe, no seu ritmo.") as NSString)
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
    private var scratchDirectory:URL?
    private var standaloneTitle:String?
    private var captureTask:Task<Void,Never>?
    init(destination: URL) { self.destination = destination }

    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.main.async { [weak self] in self?.showWindow() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 160) { [weak self] in
            guard let self, self.result == nil else { return }
            self.finish(.failure(MacPreview.failure(5, "A captura das próprias janelas excedeu 160 segundos. Nenhum fallback de bitmap foi usado.")))
        }
    }

    private func showWindow() {
        guard let defaults = UserDefaults(suiteName:suiteName) else {
            finish(.failure(MacPreview.failure(16, "Não foi possível isolar as preferências da prévia."))); return
        }
        self.defaults = defaults
        do {
            let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Preview-" + UUID().uuidString,isDirectory:true)
            try FileManager.default.createDirectory(at:scratch,withIntermediateDirectories:false,attributes:[.posixPermissions:0o700])
            scratchDirectory = scratch
            let preferences = AppearancePreferences(defaults:defaults)
            preferences.state.colorScheme = "light"
            self.preferences = preferences
            let recovery = RecoveryStore(directory:scratch.appendingPathComponent("Recovery",isDirectory:true))
            let model = Workspace(defaults:defaults,recoveryStore:recovery,enableRecoveryPolling:false)
            self.model = model
            let window = NSWindow(contentRect:NSRect(x:0,y:0,width:1050,height:720),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
            window.title = "PDF"
            window.isReleasedWhenClosed = false
            self.window = window
            display(ContentView(),size:NSSize(width:1050,height:720),title:"PDF",applicationNavigation:true)
            NSApplication.shared.activate(ignoringOtherApps:true)
            window.makeKeyAndOrderFront(nil)
            window.orderFrontRegardless()
            captureTask = Task { @MainActor in
                do { try await captureSequence(); finish(.success(Void())) }
                catch { finish(.failure(error)) }
            }
        } catch { finish(.failure(error)) }
    }

    private func resetWindowChrome(title:String) {
        guard let window else { return }
        window.toolbar = nil
        while !window.titlebarAccessoryViewControllers.isEmpty { window.removeTitlebarAccessoryViewController(at:0) }
        window.title = title; window.subtitle = ""; window.representedURL = nil
        window.isDocumentEdited = false; window.titleVisibility = .visible
        window.titlebarAppearsTransparent = false; window.toolbarStyle = .automatic
    }
    private func display<V:View>(_ view:V,size:NSSize,title:String,applicationNavigation:Bool = false) {
        guard let window,let model,let preferences,let defaults else { return }
        window.makeFirstResponder(nil)
        window.contentView = nil
        resetWindowChrome(title:title)
        standaloneTitle = applicationNavigation ? nil : title
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

    private func capture(_ name:String? = nil,auditRequired:[String]? = nil) async throws {
        guard let window else { throw MacPreview.failure(8, "A janela da prévia foi encerrada.") }
        try await Task.sleep(for:.seconds(1.5))
        try Task.checkCancellation()
        // A removed NavigationSplitView may detach its titlebar asynchronously. Standalone
        // panels get their own real window chrome, instead of the previous document's toolbar.
        if let standaloneTitle { resetWindowChrome(title:standaloneTitle) }
        window.contentView?.layoutSubtreeIfNeeded(); window.displayIfNeeded(); CATransaction.flush()
        let path = name.map { destination.deletingPathExtension().appendingPathExtension($0 + ".png") } ?? destination
        try await MacPreview.capture(window,to:path)
        if let auditRequired {
            let reportURL = path.deletingPathExtension().appendingPathExtension("accessibility.json")
            let report = try AccessibilityAudit.write(window:window,to:reportURL,requiredIdentifiers:auditRequired)
            print("PDF own-window accessibility audit: \(reportURL.lastPathComponent); nodes=\(report.nodes.count); missingRequired=\(report.missingRequiredIdentifiers.count); findings=\(report.findings.count)")
        }
    }

    private func fixtures(in directory:URL) throws -> (guide:URL,reference:URL) {
        let guide = directory.appendingPathComponent("Guia do PDF.pdf")
        let reference = directory.appendingPathComponent("Referência de revisão.pdf")
        guard let first = try MacPreview.sampleDocument().dataRepresentation(),
              let second = try MacPreview.sampleDocument(title:"Uma referência para comparar.").dataRepresentation() else {
            throw MacPreview.failure(17,"Não foi possível criar os documentos locais da demonstração.")
        }
        try NativeOutput.write(first,to:guide); try NativeOutput.write(second,to:reference)
        return (guide,reference)
    }
    private func captureSequence() async throws {
        guard let model,let preferences,let scratchDirectory else { throw MacPreview.failure(8, "A prévia não foi iniciada.") }
        let documents = try fixtures(in:scratchDirectory)
        try await capture(auditRequired:["pdf.catalog.search","pdf.customize.toolbar"])

        // Use the normal open path so tabs, per-document state and file identity are real.
        model.open(url:documents.guide)
        guard let guideID = model.activeSessionID else { throw MacPreview.failure(18,"A abertura do documento de demonstração não criou uma sessão.") }
        try await capture("leitor",auditRequired:["pdf.reader.document","pdf.reader.search","pdf.reader.page"])
        model.open(url:documents.reference)
        guard model.sessions.count == 2 else { throw MacPreview.failure(19,"A abertura do segundo documento não preservou a primeira aba.") }
        try await capture("abas")
        model.comparisonSessionID = guideID
        try await capture("lado-a-lado",auditRequired:["pdf.reader.document","pdf.reader.reference"])
        model.comparisonSessionID = nil
        model.activateSession(guideID)
        try await Task.sleep(for:.seconds(0.5))
        guard model.pdfView?.document === model.document else { throw MacPreview.failure(20,"O leitor ainda não apresentou a aba selecionada.") }
        model.addNote("Revisar esta passagem antes de concluir o documento.",colorHex:"#FFCC00")
        guard let note = model.annotationsOnCurrentPage.last(where:{ PDFAnnotationKind.matches($0,.text) }) else {
            throw MacPreview.failure(21,"A anotação da demonstração não foi criada no documento.")
        }
        model.selectAnnotation(note)
        display(ContentView(initialReaderInspector:true),size:NSSize(width:1050,height:720),title:"PDF",applicationNavigation:true)
        try await capture("anotacoes",auditRequired:["pdf.reader.document","pdf.reader.inspector"])
        try model.checkpointRecoveryNow()
        try model.refreshRecoveryNow()
        guard model.recoveryItems.count == 2 else { throw MacPreview.failure(22,"A recuperação local não preservou as duas sessões de demonstração.") }
        display(RecoveryDocumentsView(),size:NSSize(width:720,height:510),title:"Recuperar trabalho — PDF")
        try await capture("recuperacao")

        // Keep the original personalization captures, now without residual document chrome.
        for (tab,name) in [("Aparência","personalizar"),("Ferramentas","ferramentas"),("Navegação","navegacao"),("Leitor","opcoes-leitura"),("Arquivos","arquivos")] {
            display(CustomizationView(closable:false,initialTab:tab),size:NSSize(width:850,height:690),title:"Personalizar — PDF")
            try await capture(name)
        }
        preferences.state.colorScheme = "dark"
        preferences.state.accentHex = "#AF52DE"
        preferences.state.showCategoryLabels = true
        model.section = "Início"
        display(ContentView(),size:NSSize(width:1050,height:720),title:"PDF",applicationNavigation:true)
        try await capture("escuro")
        preferences.applyPreset("focus")
        preferences.state.colorScheme = "light"
        preferences.state.accentHex = "#248A3D"
        preferences.state.sidebarStyle = "icons"
        preferences.state.toolOrder = ["ocr","merge","word","summary"]
        preferences.state.toolTitles["merge"] = "Reunir meus documentos"
        preferences.state.toolIcons["merge"] = "folder.badge.plus"
        display(ContentView(),size:NSSize(width:1050,height:720),title:"PDF",applicationNavigation:true)
        try await capture("lista")
        preferences.reset(); preferences.state.colorScheme = "light"
        if let watermark = tools.first(where:{$0.id == "watermark"}) {
            display(ToolConfigurationView(tool:watermark),size:NSSize(width:690,height:730),title:"Marca d’água — PDF")
            try await capture("configuracao-ferramenta")
        }

        // A batch and an actual terminal export configured through the editor's initializer.
        display(WorkflowView(initialInputs:[documents.guide,documents.reference],finalExport:"word",libraryDirectory:scratchDirectory.appendingPathComponent("Workflows",isDirectory:true)),size:NSSize(width:1050,height:720),title:"Fluxos em lote — PDF")
        try await capture("fluxo-lote")
        // Verification starts from the clean reference tab, never from the unsaved annotation copy.
        if let reference = model.sessions.first(where:{$0.id != guideID}) { model.activateSession(reference.id) }
        for (mode,name,title) in [("sign","assinatura-digital","Assinatura digital — PDF"),("verify","verificar-assinaturas","Verificar assinaturas — PDF"),("pdfa","validar-pdfa","Validar PDF/A — PDF"),("pdfua","auditar-pdfua","Acessibilidade PDF/UA — PDF")] {
            display(VerificationView(initialMode:mode),size:NSSize(width:760,height:700),title:title)
            try await capture(name)
        }
    }

    private func finish(_ outcome:Result<Void,Error>) {
        guard result == nil else { return }
        result = outcome
        captureTask?.cancel(); model?.cancelSearch()
        window?.orderOut(nil); window?.contentView = nil
        defaults?.removePersistentDomain(forName:suiteName)
        if let scratchDirectory { try? FileManager.default.removeItem(at:scratchDirectory) }
        NSApplication.shared.stop(nil)
        if let event = NSEvent.otherEvent(with:.applicationDefined,location:.zero,modifierFlags:[],timestamp:0,windowNumber:0,context:nil,subtype:0,data1:0,data2:0) {
            NSApplication.shared.postEvent(event,atStart:false)
        }
    }
}
