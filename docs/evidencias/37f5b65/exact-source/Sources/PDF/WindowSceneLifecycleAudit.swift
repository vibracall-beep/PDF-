import AppKit
import Foundation
import Darwin

private struct WindowLifecycleCheck: Codable {
    let id: String
    let passed: Bool
    let detail: String
}

private struct WindowLifecycleEvent: Codable {
    let phase: String
    let milliseconds: Double
    let workspaceWindows: Int
    let visibleWorkspaceWindows: Int
    let applicationWindows: Int
    let windowNumber: Int?
    let contentViewClass: String?
    let sameWorkspace: Bool?
}

private struct WindowLifecycleReport: Codable {
    let schemaVersion: Int
    let createdAt: Date
    let status: String
    let operatingSystem: String
    let hardware: String
    let bundleIdentifier: String?
    let automaticPresentationDeliberatelySuppressed: Bool
    let restorationDeliberatelyDisabled: Bool
    let realSwiftUIWindowGroup: Bool
    let previewCaptureEnabled: Bool
    let privateState: Bool
    let privateStateCleaned: Bool
    let presentationRequests: Int
    let readyActionsExecuted: Int
    let maximumAttachedWorkspaceWindows: Int
    let guardCloseRequests: Int
    let observedWindowCloses: Int
    let totalMilliseconds: Double
    let checks: [WindowLifecycleCheck]
    let events: [WindowLifecycleEvent]
    let failure: String?
    let methodology: String
    let limitations: [String]
}

/// A separate GUI diagnostic: PDFApp deliberately suppresses automatic scene
/// presentation for this argument, then this observer exercises the ordinary
/// coordinator/openWindow action and the actual WorkspaceWindowGuard. It never
/// constructs an NSWindow, NSHostingView or a substitute scene itself.
@MainActor final class WindowSceneLifecycleAudit {
    nonisolated static let argument = "--window-lifecycle-audit"
    private let output: URL
    private let session: MacPreviewSession
    private let coordinator: WorkspaceSceneCoordinator
    private let beganAt = ProcessInfo.processInfo.systemUptime
    private var started = false
    private var finished = false
    private var worker: Task<Void, Never>?
    private var watchdog: Task<Void, Never>?
    private var cleanupTask: Task<Void, Never>?
    private var closeObserver: NSObjectProtocol?
    private var checks: [WindowLifecycleCheck] = []
    private var events: [WindowLifecycleEvent] = []
    private var attached: Set<ObjectIdentifier> = []
    private var attachedToExpectedModel: [ObjectIdentifier: Bool] = [:]
    private var closeRequests: [ObjectIdentifier: Int] = [:]
    private var observedCloses: [ObjectIdentifier: Int] = [:]
    private var requests = 0
    private var readyActions = 0
    private var maximumWindowCount = 0
    private var allAttachmentsUseExpectedModel = true
    private var allCloseGuardsUseExpectedModel = true
    private var allReadyActionsHaveRealWindow = true

    init?(arguments: [String], session: MacPreviewSession,
          coordinator: WorkspaceSceneCoordinator) throws {
        guard arguments.contains(Self.argument) else { return nil }
        do {
            guard arguments.count == 3, arguments[1] == Self.argument,
                  !arguments[2].isEmpty, !arguments[2].hasPrefix("--") else {
                throw PreferenceError.invalid("Use --window-lifecycle-audit seguido de um novo caminho JSON, sem outros modos de execução.")
            }
            let destination = URL(fileURLWithPath: arguments[2]).standardizedFileURL
            var metadata = stat()
            let existing = destination.path.withCString { lstat($0, &metadata) }
            guard existing != 0, errno == ENOENT else {
                throw PreferenceError.invalid("O destino da auditoria de janela já existe ou não pode ser inspecionado.")
            }
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: destination.deletingLastPathComponent().path,
                                                isDirectory: &isDirectory), isDirectory.boolValue,
                  session.isIsolated, !session.isEnabled else {
                throw PreferenceError.invalid("A auditoria de janela exige uma pasta de saída existente e estado privado sem captura de prévia.")
            }
            output = destination
        } catch {
            if session.isIsolated { try? session.cleanupIsolatedState() }
            throw error
        }
        self.session = session
        self.coordinator = coordinator
        closeObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification, object: nil, queue: .main
        ) { [weak self] notification in
            guard let window = notification.object as? NSWindow else { return }
            MainActor.assumeIsolated { self?.windowWillClose(window) }
        }
        watchdog = Task { @MainActor [weak self] in
            do { try await Task.sleep(for: .seconds(55)); try Task.checkCancellation() }
            catch { return }
            self?.finish(error: PreferenceError.invalid("A auditoria da janela real excedeu 55 segundos."))
        }
        event("diagnostic-created")
    }

    /// Called after the real NSApplication didFinishLaunching notification.
    /// PDFApp disables only the coordinator's automatic requests in this mode.
    func start() {
        guard !started, !finished else { return }
        started = true
        event("application-did-finish-launching")
        worker = Task { @MainActor [weak self] in
            guard let self else { return }
            do { try await exerciseRealWindow(); finish(error: nil) }
            catch { finish(error: error) }
        }
    }

    /// This callback is installed in the genuine WindowGroup's guard, after
    /// SwiftUI has attached its content to an AppKit window.
    func windowAttached(_ window: NSWindow, model: Workspace) {
        guard !finished else { return }
        let identity = ObjectIdentifier(window)
        let sameModel = model === session.model
        allAttachmentsUseExpectedModel = allAttachmentsUseExpectedModel && sameModel
        attached.insert(identity)
        attachedToExpectedModel[identity] = sameModel
        event("real-window-attached", window: window, sameModel: sameModel)
    }

    /// Observation at entry to the shared product close guard. No result is
    /// injected, and no confirmation dialog is automatically answered.
    func windowCloseRequested(_ window: NSWindow, model: Workspace) {
        guard !finished else { return }
        let identity = ObjectIdentifier(window)
        closeRequests[identity, default: 0] += 1
        let sameModel = model === session.model
        allCloseGuardsUseExpectedModel = allCloseGuardsUseExpectedModel && sameModel
        event("product-close-guard-entered", window: window, sameModel: sameModel)
    }

    private func windowWillClose(_ window: NSWindow) {
        let identity = ObjectIdentifier(window)
        guard !finished, attached.contains(identity) else { return }
        observedCloses[identity, default: 0] += 1
        event("appkit-window-will-close", window: window)
    }

    private func exerciseRealWindow() async throws {
        try check("isolated-state", session.isIsolated && !session.isEnabled
                  && session.model.sessions.isEmpty && session.model.toolDrafts.unsavedTitles.isEmpty,
                  "Modelo e preferências privados, sem PDF, rascunho sujo, motor ou captura de imagens.")
        // Let the real launch finish before proving the controlled empty state.
        try await settle(milliseconds: 350)
        try check("automatic-presentation-suppressed", coordinator.workspaceWindows.isEmpty
                  && attached.isEmpty && NSApp.windows.allSatisfy { !$0.isVisible },
                  "Nenhuma janela foi criada antes do primeiro pedido explícito; apresentação automática e restauração estão desativadas somente nesta condição diagnóstica artificial.")
        event("suppressed-launch-observed-without-window")

        for _ in 0..<8 { requestPresentation() }
        try await waitFor("A ação real openWindow não apresentou a primeira janela.", seconds: 12) {
            readyWindow() != nil && readyActions == 8
        }
        try await settle(milliseconds: 400)
        guard let first = readyWindow() else { throw failure("A primeira janela deixou de estar disponível.") }
        let firstIdentity = ObjectIdentifier(first)
        try check("first-real-window", coordinator.workspaceWindows.count == 1
                  && attachedToExpectedModel[firstIdentity] == true
                  && first.delegate is WorkspaceWindowGuard.Coordinator,
                  "openWindow apresentou uma única WindowGroup com o Workspace e o guard reais do produto.")
        try check("queued-actions-use-attached-window", readyActions == 8 && allReadyActionsHaveRealWindow,
                  "Os oito pedidos iniciais concluíram suas ações somente com a janela real anexada.")

        session.model.section = "Favoritos"
        session.preferences.state.sidebarWidth = 248
        session.defaults.set("preserved-window-lifecycle", forKey: "windowLifecycleAuditMarker")
        for _ in 0..<8 { requestPresentation() }
        try await waitFor("Pedidos sobre a janela existente não foram concluídos.", seconds: 5) { readyActions == 16 }
        try await settle(milliseconds: 400)
        try check("existing-window-no-duplicates", coordinator.workspaceWindows.count == 1
                  && readyWindow() === first && maximumWindowCount == 1,
                  "Pedidos repetidos reapresentaram a mesma janela sem criar outra cena anexada.")
        try check("close-without-modal-data-loss", session.model.sessions.isEmpty
                  && session.model.toolDrafts.unsavedTitles.isEmpty,
                  "O fechamento usa os guards reais em um modelo vazio; nenhum diálogo de descarte é contornado.")
        event("perform-close-on-last-workspace", window: first)
        first.performClose(nil)
        try await waitFor("O fechamento da última janela não completou pelo guard do produto.", seconds: 7) {
            coordinator.workspaceWindows.isEmpty && !first.isVisible
                && (closeRequests[firstIdentity] ?? 0) > 0
                && (observedCloses[firstIdentity] ?? 0) > 0
        }
        try check("last-window-closed-through-product-guard", coordinator.workspaceWindows.isEmpty
                  && (closeRequests[firstIdentity] ?? 0) == 1
                  && (observedCloses[firstIdentity] ?? 0) == 1 && allCloseGuardsUseExpectedModel,
                  "performClose atravessou WorkspaceWindowGuard e produziu willClose; a registry ficou vazia.")
        event("last-workspace-closed")

        for _ in 0..<8 { requestPresentation() }
        try await waitFor("A mesma ação do produto não reabriu a área de trabalho.", seconds: 12) {
            readyWindow() != nil && readyActions == 24
        }
        try await settle(milliseconds: 400)
        guard let reopened = readyWindow() else { throw failure("A janela reaberta não está disponível.") }
        try check("reopened-real-window", coordinator.workspaceWindows.count == 1
                  && attachedToExpectedModel[ObjectIdentifier(reopened)] == true
                  && reopened.delegate is WorkspaceWindowGuard.Coordinator,
                  "A ação compartilhada reapresentou uma WindowGroup real após fechar a última janela.")
        try check("workspace-and-private-preferences-preserved", session.model.section == "Favoritos"
                  && session.preferences.state.sidebarWidth == 248
                  && session.defaults.string(forKey: "windowLifecycleAuditMarker") == "preserved-window-lifecycle"
                  && allAttachmentsUseExpectedModel,
                  "A cena reaberta recebeu a mesma instância de Workspace, seção e preferências privadas.")
        try check("all-requests-no-duplicate-windows", requests == 24 && readyActions == 24
                  && allReadyActionsHaveRealWindow && maximumWindowCount == 1 && coordinator.workspaceWindows.count == 1,
                  "Vinte e quatro pedidos reais, em três fases, mantiveram no máximo uma janela de trabalho anexada.")
        event("lifecycle-checks-completed", window: reopened, sameModel: true)
    }

    private func requestPresentation() {
        requests += 1
        // The same coordinator reason/action used by the product's explicit
        // workspace command; no test replacement is registered for openWindow.
        coordinator.requestPresentation(reason: .showWorkspace) { [weak self] in
            guard let self, !self.finished else { return }
            self.readyActions += 1
            self.allReadyActionsHaveRealWindow = self.allReadyActionsHaveRealWindow && self.readyWindow() != nil
            self.event("shared-presentation-action-ready")
        }
        event("shared-presentation-requested")
    }

    private func readyWindow() -> NSWindow? {
        guard coordinator.workspaceWindows.count == 1,
              let window = coordinator.workspaceWindows.first,
              window.isVisible, window.contentView != nil, window.windowNumber > 0,
              attachedToExpectedModel[ObjectIdentifier(window)] == true else { return nil }
        return window
    }

    private func waitFor(_ detail: String, seconds: Double, until condition: () -> Bool) async throws {
        let deadline = min(beganAt + 52, ProcessInfo.processInfo.systemUptime + seconds)
        while !condition() {
            try Task.checkCancellation()
            guard coordinator.workspaceWindows.count <= 1 else { throw failure("Foram anexadas janelas de trabalho duplicadas.") }
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw failure(detail) }
            try await Task.sleep(for: .milliseconds(50))
        }
    }

    private func settle(milliseconds: Int) async throws {
        try await Task.sleep(for: .milliseconds(milliseconds))
        try Task.checkCancellation()
    }

    private func check(_ id: String, _ passed: Bool, _ detail: String) throws {
        checks.append(WindowLifecycleCheck(id: id, passed: passed, detail: detail))
        if !passed { throw failure(id + ": " + detail) }
    }

    private func failure(_ detail: String) -> Error { PreferenceError.invalid(detail) }

    private func event(_ phase: String, window: NSWindow? = nil, sameModel: Bool? = nil) {
        let windows = coordinator.workspaceWindows
        maximumWindowCount = max(maximumWindowCount, windows.count)
        events.append(WindowLifecycleEvent(phase: phase,
            milliseconds: (ProcessInfo.processInfo.systemUptime - beganAt) * 1_000,
            workspaceWindows: windows.count, visibleWorkspaceWindows: windows.filter(\.isVisible).count,
            applicationWindows: NSApp?.windows.count ?? 0, windowNumber: window?.windowNumber,
            contentViewClass: window?.contentView.map { String(reflecting: type(of: $0)) }, sameWorkspace: sameModel))
        PreviewStartupTrace.record("window lifecycle audit", details: "; phase=" + phase + "; workspaceWindows=\(windows.count)")
    }

    private func finish(error: Error?) {
        guard !finished else { return }
        finished = true
        watchdog?.cancel(); worker?.cancel()
        if let closeObserver { NotificationCenter.default.removeObserver(closeObserver) }
        // ContentView and Workspace can have real asynchronous recovery-list
        // operations even with no PDF open. Await the shared termination path
        // before deleting their private directory; cancellation alone is not
        // proof that a worker cannot recreate it.
        cleanupTask = Task { @MainActor [self] in
            let remaining = max(0, min(3, beganAt + 58 - ProcessInfo.processInfo.systemUptime))
            let ready = await session.model.prepareForTermination(externalDeadline: remaining)
            let drained = ready && ApplicationWork.activeCount == 0
            checks.append(WindowLifecycleCheck(id: "background-work-drained", passed: drained,
                detail: "O encerramento compartilhado aguardou as tarefas reais antes de remover seus dados privados."))
            publish(error: error, drained: drained)
        }
    }

    private func publish(error: Error?, drained: Bool) {
        var primaryError = error
        var cleaned = false
        if drained {
            do { try session.cleanupIsolatedState(); cleaned = true }
            catch { if primaryError == nil { primaryError = error } }
        } else if primaryError == nil {
            primaryError = failure("As tarefas da auditoria ainda não confirmaram o encerramento; a limpeza não foi aprovada.")
        }
        checks.append(WindowLifecycleCheck(id: "private-state-cleanup", passed: cleaned,
            detail: "O domínio de preferências e o diretório privados fornecidos ao Workspace foram removidos."))
        let passed = primaryError == nil && !checks.isEmpty && checks.allSatisfy(\.passed)
        let report = WindowLifecycleReport(schemaVersion: 1, createdAt: Date(), status: passed ? "passed" : "failed",
            operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString, hardware: AppleHardware.summary,
            bundleIdentifier: Bundle.main.bundleIdentifier,
            automaticPresentationDeliberatelySuppressed: true,
            restorationDeliberatelyDisabled: true,
            realSwiftUIWindowGroup: !attached.isEmpty, previewCaptureEnabled: session.isEnabled,
            privateState: session.isIsolated, privateStateCleaned: cleaned,
            presentationRequests: requests, readyActionsExecuted: readyActions,
            maximumAttachedWorkspaceWindows: maximumWindowCount,
            guardCloseRequests: closeRequests.values.reduce(0, +), observedWindowCloses: observedCloses.values.reduce(0, +),
            totalMilliseconds: (ProcessInfo.processInfo.systemUptime - beganAt) * 1_000,
            checks: checks, events: events, failure: primaryError?.localizedDescription,
            methodology: "Uma WindowGroup real do produto inicia com a apresentação automática e a restauração deliberadamente desativadas somente no modo diagnóstico. A ação compartilhada do coordenador chama openWindow, reapresenta sem duplicar, fecha a última janela com performClose e o guard real e reabre preservando o Workspace. Nenhuma NSWindow/NSHostingView substituta, mock, captura de imagem, PDF ou motor externo é criado pela auditoria.",
            limitations: [
                "A supressão inicial e a restauração desativada são condições artificiais controladas; passar não reproduz nem demonstra a causa do timeout histórico do SwiftUI. O modo normal conserva sua política de restauração.",
                "O modelo fica sem documentos e sem rascunhos sujos. O ensaio não valida escolhas humanas de descarte, recuperação de PDFs ou todos os percursos de restauração.",
                "O relatório mede o ciclo de janela observado nesta execução; não aprova sozinho o pacote, os 33 PNGs/relatórios AX da prévia ou compatibilidade geral entre sistemas."
            ])
        do {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]; encoder.dateEncodingStrategy = .iso8601
            try NativeOutput.write(encoder.encode(report), to: output)
        } catch {
            fputs("Window lifecycle audit could not publish its report: \(error)\n", stderr)
            exit(1)
        }
        if passed { print("PDF real WindowGroup lifecycle audit passed") }
        else { fputs("PDF real WindowGroup lifecycle audit failed: \(primaryError?.localizedDescription ?? "check failed")\n", stderr) }
        exit(passed ? 0 : 1)
    }
}
