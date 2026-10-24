import AppKit
import SwiftUI
import PDFKit
import QuartzCore
import ScreenCaptureKit
import Darwin

/// Startup breadcrumbs precede AppKit's window lifecycle. They are enabled
/// only for the explicit preview command and contain no paths or document data.
enum PreviewStartupTrace {
    static func record(_ phase: StaticString) {
        guard CommandLine.arguments.contains("--render-preview") else { return }
        let line = "PDF preview startup: \(phase); mainThread=\(pthread_main_np() != 0)\n"
        // No stdout/stdio buffer: a timeout before WindowGroup attachment must
        // still retain the last phase. Failure to log never changes app behavior.
        let bytes = Array(line.utf8)
        bytes.withUnsafeBytes { buffer in
            guard let base = buffer.baseAddress else { return }
            var offset = 0
            while offset < buffer.count {
                let written = Darwin.write(STDERR_FILENO, base.advanced(by: offset), buffer.count - offset)
                if written > 0 { offset += written }
                else if written < 0 && errno == EINTR { continue }
                else { break }
            }
        }
    }
}

/// Captures the real WindowServer-composited application surface in the native CI session.
/// NSView.cacheDisplay cannot capture all SwiftUI material or PDFKit tiled layers.
@MainActor
enum MacPreview {
    fileprivate static func trace(_ phase:String) {
        // Bypass stdout buffering so a terminated CI process still identifies its last phase.
        let line = "PDF preview phase [\(String(format:"%.3f",ProcessInfo.processInfo.systemUptime))]: \(phase)\n"
        FileHandle.standardError.write(Data(line.utf8))
    }
    fileprivate static func failure(_ code: Int, _ message: String) -> NSError {
        NSError(domain: "PDF.Preview", code: code, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private struct WindowGeometry: Equatable {
        var id: Int
        var frame: CGRect
        var contentBounds: CGRect
        var contentLayout: CGRect
        var backingScale: CGFloat
    }

    private struct CaptureGeometry: Equatable {
        var window: WindowGeometry
        var serverFrame: CGRect
        var filterRect: CGRect
        var pixelScale: CGFloat
        var onScreen: Bool

        var isAligned: Bool {
            let rectangles = [window.frame, window.contentBounds, window.contentLayout, serverFrame, filterRect]
            guard onScreen, window.id > 0,
                  rectangles.allSatisfy({ rect in
                      [rect.minX, rect.minY, rect.width, rect.height].allSatisfy(\.isFinite)
                          && rect.width > 100 && rect.height > 100
                  }),
                  pixelScale.isFinite, pixelScale > 0,
                  window.backingScale.isFinite, window.backingScale > 0,
                  abs(pixelScale - window.backingScale) < 0.01 else { return false }
            // NSWindow and SCWindow origins use different screen coordinate
            // systems. Compare their sizes; retain both full frames to detect
            // movement between metadata samples without inventing an offset.
            for size in [serverFrame.size, filterRect.size] {
                guard abs(size.width - window.frame.width) < 0.01,
                      abs(size.height - window.frame.height) < 0.01 else { return false }
            }
            return [filterRect.width * pixelScale, filterRect.height * pixelScale].allSatisfy {
                $0.isFinite && $0 > 100 && $0 < CGFloat(Int.max)
            }
        }

        func agrees(with other: CaptureGeometry) -> Bool {
            isAligned && other.isAligned && self == other
        }
    }

    private struct CaptureSample {
        let geometry: CaptureGeometry
        let filter: SCContentFilter
    }

    private static func windowGeometry(_ window: NSWindow) throws -> WindowGeometry {
        guard window.isVisible, window.windowNumber > 0 else {
            throw failure(3, "A janela da prévia não foi registrada no WindowServer.")
        }
        guard let content = window.contentView, content.bounds.width > 100, content.bounds.height > 100 else {
            throw failure(4, "A janela da prévia ainda não possui uma área de conteúdo válida.")
        }
        return WindowGeometry(id: window.windowNumber, frame: window.frame,
            contentBounds: content.bounds, contentLayout: window.contentLayoutRect,
            backingScale: window.backingScaleFactor)
    }

    private static func captureSample(_ window: NSWindow) async throws -> CaptureSample? {
        let before = try windowGeometry(window)
        // Fresh metadata is necessary after a SwiftUI route changes window chrome.
        // This API is restricted to our process and does not request global access.
        let available: SCShareableContent
        do { available = try await SCShareableContent.currentProcess }
        catch {
            let error = error as NSError
            throw failure(11, "O sistema não disponibilizou as janelas capturáveis deste processo. ScreenCaptureKit \(error.domain) código \(error.code): \(error.localizedDescription)")
        }
        try Task.checkCancellation()
        let current = try windowGeometry(window)
        guard before == current else {
            trace("window geometry changed while acquiring WindowServer metadata")
            return nil
        }
        guard let ownWindow = available.windows.first(where: { $0.windowID == CGWindowID(current.id) }) else {
            trace("current window not yet present in current-process capture metadata")
            return nil
        }
        if let owner = ownWindow.owningApplication, owner.processID != ProcessInfo.processInfo.processIdentifier {
            throw failure(15, "O WindowServer associou o ID selecionado a outro processo. A captura foi recusada.")
        }
        let filter = SCContentFilter(desktopIndependentWindow: ownWindow)
        let geometry = CaptureGeometry(window: current, serverFrame: ownWindow.frame,
            filterRect: filter.contentRect, pixelScale: CGFloat(filter.pointPixelScale), onScreen: ownWindow.isOnScreen)
        guard geometry.isAligned else {
            trace("waiting for matching capture geometry: window=\(current.frame.size); server=\(ownWindow.frame.size); filter=\(filter.contentRect.size); backingScale=\(current.backingScale); filterScale=\(geometry.pixelScale); onScreen=\(geometry.onScreen)")
            return nil
        }
        return CaptureSample(geometry: geometry, filter: filter)
    }

    /// Uses the observed 0bd macOS 26 mismatch and post-capture changes as
    /// negative fixtures. This checks geometry acceptance, not image sharpness.
    static func runGeometryAuditChecks() throws {
        func require(_ value: Bool, _ message: String) throws {
            guard value else { throw failure(42, "Geometria da prévia: " + message) }
        }
        let frame = CGRect(x: 20, y: 80, width: 1050, height: 772)
        let bounds = CGRect(x: 0, y: 0, width: 1050, height: 772)
        let window = WindowGeometry(id: 30, frame: frame, contentBounds: bounds,
            contentLayout: CGRect(x: 0, y: 0, width: 1050, height: 720), backingScale: 1)
        let stable = CaptureGeometry(window: window,
            serverFrame: CGRect(x: 20, y: 30, width: 1050, height: 772),
            filterRect: bounds, pixelScale: 1, onScreen: true)
        try require(stable.isAligned && stable.agrees(with: stable), "geometria consistente recusada")
        var stale = stable
        stale.filterRect.size.height = 752
        try require(!stale.isAligned && !stable.agrees(with: stale), "filtro antigo 1050×752 aceito para janela 1050×772")
        stale = stable; stale.serverFrame.size.height = 752
        try require(!stale.isAligned, "frame antigo do WindowServer aceito")
        var afterCapture = stable
        afterCapture.window.frame.size.height = 792
        afterCapture.window.contentBounds.size.height = 792
        afterCapture.window.contentLayout.size.height = 740
        afterCapture.serverFrame.size.height = 792
        afterCapture.filterRect.size.height = 792
        try require(afterCapture.isAligned && !stable.agrees(with: afterCapture), "redimensionamento durante a captura aceito")
        afterCapture = stable; afterCapture.window.frame.origin.x += 10
        afterCapture.serverFrame.origin.x += 10
        try require(afterCapture.isAligned && !stable.agrees(with: afterCapture), "movimento durante a captura aceito")
        afterCapture = stable; afterCapture.window.id += 1
        try require(!stable.agrees(with: afterCapture), "troca de identidade durante a captura aceita")
        for scale in [CGFloat(0), -1, .nan, .infinity, 2] {
            var invalid = stable; invalid.pixelScale = scale
            try require(!invalid.isAligned, "escala inválida ou divergente aceita")
        }
        var retina = stable; retina.window.backingScale = 2; retina.pixelScale = 2
        try require(retina.isAligned && !stable.agrees(with: retina), "escala Retina consistente recusada ou troca de tela ignorada")
        var hidden = stable; hidden.onScreen = false
        try require(!hidden.isAligned, "janela fora da tela aceita")
    }

    fileprivate static func capture(_ window: NSWindow, to destination: URL) async throws {
        _ = try windowGeometry(window)
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
        let deadline = ProcessInfo.processInfo.systemUptime + 6
        var previous: CaptureGeometry?
        var attempts = 0
        while ProcessInfo.processInfo.systemUptime < deadline {
            try Task.checkCancellation()
            attempts += 1
            window.contentView?.layoutSubtreeIfNeeded()
            window.displayIfNeeded()
            CATransaction.flush()
            guard let current = try await captureSample(window) else {
                previous = nil
                if ProcessInfo.processInfo.systemUptime < deadline { try await Task.sleep(for: .milliseconds(100)) }
                continue
            }
            guard ProcessInfo.processInfo.systemUptime < deadline else { break }
            if previous?.agrees(with: current.geometry) != true {
                let wasChanging = previous != nil
                previous = current.geometry
                // A matching first sample needs a second fresh metadata read,
                // not a fixed delay. Only observed changes wait for another turn.
                if wasChanging { try await Task.sleep(for: .milliseconds(100)) }
                continue
            }
            let geometry = current.geometry
            let configuration = SCStreamConfiguration()
            configuration.width = Int(ceil(geometry.filterRect.width * geometry.pixelScale))
            configuration.height = Int(ceil(geometry.filterRect.height * geometry.pixelScale))
            configuration.showsCursor = false
            configuration.includeChildWindows = false
            configuration.ignoreShadowsSingleWindow = true
            configuration.scalesToFit = false
            print("PDF preview diagnostics: destinationWritable=true; globalCapturePreflight=\(globalAccess); captureScope=currentProcess; frame=\(Int(geometry.window.frame.width))x\(Int(geometry.window.frame.height)); content=\(Int(geometry.window.contentBounds.width))x\(Int(geometry.window.contentBounds.height)); backingScale=\(geometry.window.backingScale)")
            print("PDF preview own-window filter: window=\(geometry.window.id); onScreen=\(geometry.onScreen); points=\(Int(geometry.filterRect.width))x\(Int(geometry.filterRect.height)); requestedPixels=\(configuration.width)x\(configuration.height)")
            let image: CGImage
            do { image = try await SCScreenshotManager.captureImage(contentFilter: current.filter, configuration: configuration) }
            catch {
                let error = error as NSError
                throw failure(13, "A captura da própria janela falhou. ScreenCaptureKit \(error.domain) código \(error.code): \(error.localizedDescription)")
            }
            try Task.checkCancellation()
            guard ProcessInfo.processInfo.systemUptime < deadline else { break }
            // Do not encode or publish an image made with geometry that changed
            // during capture. Obtain another current-process filter to verify it.
            guard let after = try await captureSample(window), geometry.agrees(with: after.geometry) else {
                trace("discarded capture after geometry changed; destination untouched")
                previous = nil
                if ProcessInfo.processInfo.systemUptime < deadline { try await Task.sleep(for: .milliseconds(100)) }
                continue
            }
            guard ProcessInfo.processInfo.systemUptime < deadline else { break }
            guard image.width == configuration.width, image.height == configuration.height, image.width > 100, image.height > 100 else {
                throw failure(14, "O WindowServer retornou dimensões incompatíveis com o filtro da própria janela: \(image.width)x\(image.height).")
            }
            let bitmap = NSBitmapImageRep(cgImage: image)
            guard let data = bitmap.representation(using: .png, properties: [:]) else {
                throw failure(7, "A captura real da janela não pôde ser codificada como PNG.")
            }
            try Task.checkCancellation()
            guard ProcessInfo.processInfo.systemUptime < deadline else { break }
            guard geometry.window == (try windowGeometry(window)) else {
                trace("discarded capture before publication after window geometry changed")
                previous = nil
                continue
            }
            try NativeOutput.write(data, to: destination)
            print("PDF preview captured from WindowServer via ScreenCaptureKit: \(destination.lastPathComponent); window=\(geometry.window.id); content=\(Int(geometry.window.contentBounds.width))x\(Int(geometry.window.contentBounds.height)); pixels=\(image.width)x\(image.height); geometrySamples=\(attempts)")
            return
        }
        throw failure(41, "A geometria da janela e do WindowServer não permaneceu consistente durante os 6 segundos de verificação. Nenhum PNG foi gravado.")
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

/// Runs inside PDFApp's real WindowGroup. Only the data and selected route are
/// isolated; SwiftUI owns the application, window, toolbar and accessibility lifecycle.
@MainActor final class MacPreviewSession:ObservableObject {
    private enum Route {
        case workspace(Bool), customization(String), recovery, tool(String), workflow, verification(String), advanced(String), production(ProductionMode), palette
        var identity:String {
            switch self {
            case .workspace(let inspector): return "workspace-\(inspector)"
            case .customization(let tab): return "customization-" + tab
            case .recovery: return "recovery"
            case .tool(let id): return "tool-" + id
            case .workflow: return "workflow"
            case .verification(let mode): return "verification-" + mode
            case .advanced(let mode): return "advanced-" + mode
            case .production(let mode): return "production-" + mode.rawValue
            case .palette: return "palette"
            }
        }
        var title:String? {
            switch self {
            case .workspace: return nil
            case .customization: return "Personalizar — PDF"
            case .recovery: return "Recuperar trabalho — PDF"
            case .tool: return "Marca d’água — PDF"
            case .workflow: return "Fluxos em lote — PDF"
            case .verification(let mode): return ["sign":"Assinatura digital — PDF","verify":"Verificar assinaturas — PDF","pdfa":"Validar PDF/A — PDF","pdfua":"Acessibilidade PDF/UA — PDF"][mode]
            case .advanced: return "Ferramentas avançadas — PDF"
            case .production(let mode): return mode.title + " — PDF"
            case .palette: return "Comandos — PDF"
            }
        }
    }
    @Published private var route:Route = .workspace(false)
    let defaults:UserDefaults
    let model:Workspace
    let preferences:AppearancePreferences
    private let destination:URL?
    private let suiteName:String?
    private let scratchDirectory:URL?
    private weak var window:NSWindow?
    private var fixtureInputs:[URL] = []
    private let contentController = AdvancedDocumentController()
    private let ocrController = AdvancedDocumentController()
    private var accessibilityInspection: AccessibilityInspectionRequest?
    private lazy var automation = AutomationCoordinator(defaults: defaults)
    private lazy var toolPresets = ToolPresetStore(defaults:defaults)
    private var started = false
    private var finished = false
    private var captureTask:Task<Void,Never>?
    private var watchdog:Task<Void,Never>?
    var isEnabled:Bool { destination != nil }
    var routeIdentity:String { route.identity }

    init(destination:URL? = nil) throws {
        PreviewStartupTrace.record("preview session init begin")
        self.destination = destination
        if destination != nil {
            let suite = "PDF-preview-" + UUID().uuidString
            guard let defaults = UserDefaults(suiteName:suite) else { throw MacPreview.failure(16,"Não foi possível isolar as preferências da prévia.") }
            PreviewStartupTrace.record("isolated defaults ready")
            let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Preview-" + UUID().uuidString,isDirectory:true)
            try FileManager.default.createDirectory(at:scratch,withIntermediateDirectories:false,attributes:[.posixPermissions:0o700])
            self.defaults = defaults; suiteName = suite; scratchDirectory = scratch
            PreviewStartupTrace.record("isolated scratch directory ready")
            let appearance = AppearancePreferences(defaults:defaults)
            appearance.state.colorScheme = "light"
            preferences = appearance
            PreviewStartupTrace.record("appearance preferences ready")
            model = Workspace(defaults:defaults,recoveryStore:RecoveryStore(directory:scratch.appendingPathComponent("Recovery",isDirectory:true)),enableRecoveryPolling:false)
            PreviewStartupTrace.record("workspace ready")
        } else {
            defaults = .standard; suiteName = nil; scratchDirectory = nil
            model = Workspace(); preferences = AppearancePreferences.shared
        }
        PreviewStartupTrace.record("preview session init end")
    }

    @ViewBuilder var content:some View {
        switch route {
        case .workspace(let inspector): ContentView(initialReaderInspector:inspector)
        case .customization(let tab): CustomizationView(closable:false,initialTab:tab)
        case .recovery: RecoveryDocumentsView()
        case .tool(let id):
            if let tool = tools.first(where:{$0.id == id}) { ToolConfigurationView(tool:tool,presetStore:toolPresets) }
        case .workflow:
            WorkflowView(initialInputs:fixtureInputs,finalExport:"word",libraryDirectory:scratchDirectory?.appendingPathComponent("Workflows",isDirectory:true))
        case .verification(let mode): VerificationView(initialMode:mode)
        case .palette: CommandPaletteView(onSelect: { _ in })
        case .production(let mode): ProductionToolsView(initialMode: mode)
        case .advanced(let mode):
            switch mode {
            case "content": AdvancedContentEditorView(controller: contentController)
            case "ocr": OCRReviewView(controller: ocrController)
            case "library": DocumentLibraryView(directory: scratchDirectory?.appendingPathComponent("Library", isDirectory: true))
            case "accessibility": AccessibilityRemediationView(initialInspection: accessibilityInspection)
            case "signatures": SignatureRequestView()
            default: AutomationView(coordinator: automation)
            }
        }
    }

    func attach(to window:NSWindow) {
        guard isEnabled,!started else { return }
        started = true; self.window = window
        MacPreview.trace("real SwiftUI WindowGroup attached")
        // The same minimum as PDFApp's normal WindowGroup, without replacing its host.
        window.setContentSize(NSSize(width:1050,height:720))
        if let screen = window.screen ?? NSScreen.main { window.setFrameTopLeftPoint(NSPoint(x:screen.frame.minX+20,y:screen.frame.maxY-30)) }
        let regular = NSApplication.shared.setActivationPolicy(.regular)
        MacPreview.trace("preview regular activation policy accepted=\(regular)")
        NSApplication.shared.activate(ignoringOtherApps:true)
        window.makeKeyAndOrderFront(nil)
        watchdog = Task { @MainActor [weak self] in
            do { try await Task.sleep(for:.seconds(280)); try Task.checkCancellation() }
            catch { return }
            self?.finish(.failure(MacPreview.failure(5,"A captura da WindowGroup excedeu 280 segundos. Nenhum fallback de bitmap foi usado.")))
        }
        captureTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do { try await captureSequence(); finish(.success(Void())) }
            catch { finish(.failure(error)) }
        }
    }

    private func present(_ destination:Route) {
        window?.makeFirstResponder(nil)
        MacPreview.trace("SwiftUI route: " + destination.identity)
        route = destination
    }

    private func capture(_ name:String? = nil,auditRequired:[String]? = nil) async throws {
        guard let window,let destination else { throw MacPreview.failure(8, "A janela da prévia foi encerrada.") }
        let stage = name ?? "home"
        CIDiagnostics.record("Capture starting: " + stage,title:"PDF preview")
        MacPreview.trace("\(stage): settle begin")
        NSApplication.shared.activate(ignoringOtherApps:true)
        window.makeKeyAndOrderFront(nil)
        try await Task.sleep(for:.seconds(1.5))
        try Task.checkCancellation()
        // SwiftUI has now committed the real route. Standalone tool views share this
        // production WindowGroup's minimum rather than a replacement NSHostingView.
        if let title = route.title { window.title = title }
        MacPreview.trace("\(stage): layout begin")
        window.contentView?.layoutSubtreeIfNeeded(); window.displayIfNeeded(); CATransaction.flush()
        MacPreview.trace("\(stage): active=\(NSApplication.shared.isActive); key=\(window.isKeyWindow); main=\(window.isMainWindow); activationPolicy=\(NSApplication.shared.activationPolicy().rawValue)")
        MacPreview.trace("\(stage): window frame \(window.frame); content layout \(window.contentLayoutRect); host \(String(describing:window.contentView?.bounds))")
        let path = name.map { destination.deletingPathExtension().appendingPathExtension($0 + ".png") } ?? destination
        MacPreview.trace("\(stage): ScreenCaptureKit begin")
        try await MacPreview.capture(window,to:path)
        MacPreview.trace("\(stage): PNG written")
        if let auditRequired {
            let reportURL = path.deletingPathExtension().appendingPathExtension("accessibility.json")
            MacPreview.trace("\(stage): accessibility traversal begin")
            CIDiagnostics.record("Accessibility starting: " + stage,title:"PDF preview")
            let report = try await AccessibilityAudit.write(window:window,to:reportURL,requiredIdentifiers:auditRequired)
            MacPreview.trace("\(stage): accessibility JSON written (\(report.nodes.count) nodes)")
            if let client = report.client { MacPreview.trace("\(stage): public own-process AX status=\(client.status); trusted=\(client.processTrusted); code=\(String(describing:client.errorCode)); windows=\(client.ownWindowCount); matches=\(client.matchingWindowCount)") }
            print("PDF own-window accessibility audit: \(reportURL.lastPathComponent); nodes=\(report.nodes.count); missingRequired=\(report.missingRequiredIdentifiers.count); findings=\(report.findings.count)")
        }
        CIDiagnostics.record("Capture completed: " + stage,title:"PDF preview")
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
        guard let scratchDirectory else { throw MacPreview.failure(8, "A prévia não foi iniciada.") }
        let documents = try fixtures(in:scratchDirectory)
        fixtureInputs = [documents.guide,documents.reference]
        MacPreview.trace("two fixture PDFs written")
        try await capture(auditRequired:["pdf.catalog.search","pdf.customize.toolbar"])

        // Use the normal open path so tabs, per-document state and file identity are real.
        MacPreview.trace("open primary document begin")
        model.open(url:documents.guide)
        await model.waitForPendingOpen()
        try Task.checkCancellation()
        MacPreview.trace("open primary document end")
        guard let guideID = model.activeSessionID else { throw MacPreview.failure(18,"A abertura do documento de demonstração não criou uma sessão.") }
        try await capture("leitor",auditRequired:["pdf.reader.document","pdf.reader.search","pdf.reader.page"])
        MacPreview.trace("open second document begin")
        model.open(url:documents.reference)
        await model.waitForPendingOpen()
        try Task.checkCancellation()
        MacPreview.trace("open second document end")
        guard model.sessions.count == 2 else { throw MacPreview.failure(19,"A abertura do segundo documento não preservou a primeira aba.") }
        try await capture("abas")
        model.comparisonSessionID = guideID
        try await capture("lado-a-lado",auditRequired:["pdf.reader.document","pdf.reader.reference"])
        MacPreview.trace("leave split and select first tab begin")
        model.comparisonSessionID = nil
        model.activateSession(guideID)
        MacPreview.trace("leave split and select first tab end")
        try await Task.sleep(for:.seconds(0.5))
        guard model.pdfView?.document === model.document else { throw MacPreview.failure(20,"O leitor ainda não apresentou a aba selecionada.") }
        MacPreview.trace("create and select note begin")
        model.addNote("Revisar esta passagem antes de concluir o documento.",colorHex:"#FFCC00")
        MacPreview.trace("note added; read annotation list begin")
        guard let note = model.annotationsOnCurrentPage.last(where:{ PDFAnnotationKind.matches($0,.text) }) else {
            throw MacPreview.failure(21,"A anotação da demonstração não foi criada no documento.")
        }
        MacPreview.trace("note located; select annotation begin")
        model.selectAnnotation(note)
        MacPreview.trace("create and select note end")
        present(.workspace(true))
        try await capture("anotacoes",auditRequired:["pdf.reader.document","pdf.reader.inspector"])
        MacPreview.trace("checkpoint recovery begin")
        try model.checkpointRecoveryNow()
        MacPreview.trace("checkpoint recovery end; refresh begin")
        try model.refreshRecoveryNow()
        MacPreview.trace("refresh recovery end")
        guard model.recoveryItems.count == 2 else { throw MacPreview.failure(22,"A recuperação local não preservou as duas sessões de demonstração.") }
        present(.recovery)
        try await capture("recuperacao")

        // Keep the original personalization captures, now without residual document chrome.
        for (tab,name) in [("Aparência","personalizar"),("Ferramentas","ferramentas"),("Navegação","navegacao"),("Leitor","opcoes-leitura"),("Arquivos","arquivos"),("Atalhos","atalhos"),("Perfis","perfis")] {
            present(.customization(tab))
            try await capture(name)
        }
        preferences.state.colorScheme = "dark"
        preferences.state.accentHex = "#AF52DE"
        preferences.state.showCategoryLabels = true
        model.section = "Início"
        present(.workspace(false))
        try await capture("escuro")
        preferences.applyPreset("focus")
        preferences.state.colorScheme = "light"
        preferences.state.accentHex = "#248A3D"
        preferences.state.sidebarStyle = "icons"
        preferences.state.toolOrder = ["ocr","merge","word","summary"]
        preferences.state.toolTitles["merge"] = "Reunir meus documentos"
        preferences.state.toolIcons["merge"] = "folder.badge.plus"
        present(.workspace(false))
        try await capture("lista")
        preferences.reset(); preferences.state.colorScheme = "light"
        guard tools.contains(where:{$0.id == "watermark"}) else { throw MacPreview.failure(23,"A ferramenta Marca d’água não está no catálogo.") }
        present(.tool("watermark"))
        try await capture("configuracao-ferramenta")

        // A batch and an actual terminal export configured through the editor's initializer.
        present(.workflow)
        try await capture("fluxo-lote")
        // Verification starts from the clean reference tab, never from the unsaved annotation copy.
        if let reference = model.sessions.first(where:{$0.id != guideID}) { model.activateSession(reference.id) }
        for (mode,name) in [("sign","assinatura-digital"),("verify","verificar-assinaturas"),("pdfa","validar-pdfa"),("pdfua","auditar-pdfua")] {
            present(.verification(mode))
            try await capture(name)
        }
        present(.palette); try await capture("paleta")
        contentController.load(model: model, ocr: false)
        try await waitForReview(contentController)
        guard contentController.content?.objects.isEmpty == false else { throw MacPreview.failure(24, "O editor não carregou objetos reais da amostra.") }
        present(.advanced("content")); try await capture("editor-conteudo")

        guard let page = model.document?.page(at: 0) else {
            throw MacPreview.failure(25, "Não foi possível preparar a amostra raster para revisão OCR.")
        }
        let thumbnail = page.thumbnail(of: NSSize(width: 1200, height: 1600), for: .cropBox)
        guard let imagePage = PDFPage(image: thumbnail) else { throw MacPreview.failure(25, "Não foi possível preparar a amostra raster para revisão OCR.") }
        let originalBounds = page.bounds(for: .cropBox), imageBounds = imagePage.bounds(for: .cropBox)
        let rasterSizes = thumbnail.representations.map { "\($0.pixelsWide)x\($0.pixelsHigh)" }.joined(separator: ",")
        MacPreview.trace("OCR fixture: sourcePoints=\(originalBounds.width)x\(originalBounds.height); thumbnailPoints=\(thumbnail.size.width)x\(thumbnail.size.height); bitmapPixels=\(rasterSizes); scanPoints=\(imageBounds.width)x\(imageBounds.height)")
        let scanned = PDFDocument(); scanned.insert(imagePage, at: 0)
        let scanURL = scratchDirectory.appendingPathComponent("Revisão digitalizada.pdf")
        guard let bytes = scanned.dataRepresentation() else { throw MacPreview.failure(26, "A amostra raster está vazia.") }
        try NativeOutput.write(bytes, to: scanURL)
        model.open(url: scanURL); await model.waitForPendingOpen()
        ocrController.load(model: model, ocr: true, language: "eng", segmentation: 3)
        try await waitForReview(ocrController)
        guard ocrController.review?.words.isEmpty == false else { throw MacPreview.failure(27, "O OCR não recuperou palavras reais da amostra.") }
        guard let destination, let reportURL = ocrController.ocrReviewURL,
              ocrController.review?.recognitionConfiguration == OCRRecognitionConfiguration(language: "eng", segmentation: 3),
              try Data(contentsOf: scanURL) == bytes else {
            throw MacPreview.failure(27, "As opções OCR ou a amostra original não foram preservadas na prévia.")
        }
        let evidence = destination.deletingPathExtension()
        try NativeOutput.write(bytes, to: evidence.appendingPathExtension("revisao-ocr.source.pdf"))
        try NativeOutput.write(Data(contentsOf: reportURL), to: evidence.appendingPathExtension("revisao-ocr.analysis.json"))
        present(.advanced("ocr")); try await capture("revisao-ocr")

        let library = DocumentLibraryStore(directory: scratchDirectory.appendingPathComponent("Library", isDirectory: true))
        _ = try await library.importFiles(fixtureInputs, collection: "Documentos de demonstração", tags: ["Revisão"])
        present(.advanced("library")); try await capture("biblioteca", auditRequired: ["pdf.library"])
        try await presentAccessibilityFixture(source: documents.reference, directory: scratchDirectory)
        try await capture("corrigir-acessibilidade", auditRequired: ["pdf.accessibility.tag.title", "pdf.accessibility.tag.alt",
            "pdf.accessibility.tag.actual-text", "pdf.accessibility.tag.language", "pdf.accessibility.tag.scope"])
        present(.advanced("signatures")); try await capture("solicitar-assinaturas")
        present(.advanced("automation")); try await capture("automacao")
        for mode in [ProductionMode.preflight, .bates, .measure, .pdfx] {
            present(.production(mode)); try await capture("producao-" + mode.rawValue)
        }
    }

    private func previewOperation(_ operation: String, source: URL, output: URL, options: [String: Any]) async throws -> URL {
        try Task.checkCancellation()
        guard !model.busy else { throw MacPreview.failure(29, "O motor ainda está ocupado ao preparar a amostra acessível.") }
        return try await withCheckedThrowingContinuation { continuation in
            model.execute(operation: operation, inputs: [source], output: output, options: options,
                          title: "Preparando amostra acessível", completion: { continuation.resume(with: $0) })
        }
    }

    private func presentAccessibilityFixture(source: URL, directory: URL) async throws {
        MacPreview.trace("accessibility fixture: create real page tags")
        let tagged = try await previewOperation("accessibility-remediate", source: source,
            output: directory.appendingPathComponent("Estrutura inicial.pdf"),
            options: ["input_sha256": LibraryFiles.hash(try Data(contentsOf: source)), "language": "pt-BR",
                      "create_page_tags": [["page": 1, "role": "P"], ["page": 2, "role": "P"]]])
        let inspectionURL = try await previewOperation("accessibility-inspect", source: tagged,
            output: directory.appendingPathComponent("Estrutura inicial.json"), options: [:])
        guard let inspected = try JSONSerialization.jsonObject(with: Data(contentsOf: inspectionURL)) as? [String: Any],
              inspected["schema_version"] as? Int == 1,
              let hash = inspected["input_sha256"] as? String, LibraryFiles.validHash(hash),
              let nodes = inspected["nodes"] as? [[String: Any]],
              let node = nodes.first(where: { $0["role"] as? String == "P" && $0["page"] as? Int == 1 }),
              let identity = node["id"] as? String else {
            throw MacPreview.failure(30, "A inspeção real não recuperou a tag da amostra acessível.")
        }
        let expected = ["title": "Prazo de entrega", "alt": "Cabeçalho da coluna com o prazo de entrega.",
                        "actual_text": "Prazo de entrega em dias úteis", "language": "pt-BR", "scope": "Column"]
        var edit: [String: Any] = expected
        edit["id"] = identity; edit["role"] = "TH"
        MacPreview.trace("accessibility fixture: apply real TH attributes")
        let prepared = try await previewOperation("accessibility-remediate", source: tagged,
            output: directory.appendingPathComponent("Cabeçalho com atributos.pdf"),
            options: ["input_sha256": hash, "edits": [edit]])
        let expectedHash = LibraryFiles.hash(try Data(contentsOf: prepared))
        // The view obtains its own report from the production inspection action.
        // This callback resumes only after its actual selected fields are loaded.
        let selected: AccessibilityInspectedSelection = try await withCheckedThrowingContinuation { continuation in
            accessibilityInspection = AccessibilityInspectionRequest(sourceURL: prepared, selectedRole: "TH",
                completion: { continuation.resume(with: $0) })
            present(.advanced("accessibility"))
        }
        try Task.checkCancellation()
        guard selected.sourceSHA256 == expectedHash, !selected.tagID.isEmpty,
              selected.role == "TH", selected.values == expected else {
            throw MacPreview.failure(31, "O formulário não carregou os atributos reais da tag TH inspecionada.")
        }
        MacPreview.trace("accessibility fixture: production inspection and selected fields ready")
    }

    private func waitForReview(_ controller: AdvancedDocumentController) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 90
        while controller.working {
            try Task.checkCancellation()
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw MacPreview.failure(28, "A revisão da amostra ultrapassou 90 segundos.") }
            try await Task.sleep(for: .milliseconds(50))
        }
    }

    private func finish(_ outcome:Result<Void,Error>) {
        guard !finished else { return }
        finished = true
        watchdog?.cancel(); captureTask?.cancel(); model.cancelSearch()
        if let suiteName { defaults.removePersistentDomain(forName:suiteName) }
        if let scratchDirectory { try? FileManager.default.removeItem(at:scratchDirectory) }
        switch outcome {
        case .success:
            MacPreview.trace("real WindowGroup preview completed")
            exit(0)
        case .failure(let error):
            CIDiagnostics.record(error.localizedDescription,level:"error",title:"PDF preview")
            FileHandle.standardError.write(Data(("PDF preview failed: " + error.localizedDescription + "\n").utf8))
            exit(1)
        }
    }
}

/// Locates the WindowGroup-owned window after SwiftUI has mounted its content.
/// It does not replace the window delegate, content view, toolbar or safe-area policy.
struct MacPreviewWindowObserver:NSViewRepresentable {
    let session:MacPreviewSession
    func makeNSView(context:Context) -> WindowObserver {
        PreviewStartupTrace.record("window observer creation begin")
        let view = WindowObserver()
        view.attached = { [weak session] window in
            DispatchQueue.main.async { session?.attach(to:window) }
        }
        PreviewStartupTrace.record("window observer creation end")
        return view
    }
    func updateNSView(_ view:WindowObserver,context:Context) {
        if let window = view.window { view.attached?(window) }
    }
    final class WindowObserver:NSView {
        var attached:((NSWindow)->Void)?
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let window {
                PreviewStartupTrace.record("window observer received WindowGroup window")
                attached?(window)
            }
        }
    }
}
