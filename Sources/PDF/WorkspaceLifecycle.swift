import SwiftUI
import AppKit

@MainActor final class PDFApplicationDelegate:NSObject,NSApplicationDelegate {
    weak var model:Workspace?
    private weak var sceneCoordinator:WorkspaceSceneCoordinator?
    private var lifecycleAudit:WindowSceneLifecycleAudit?
    private var explicitPreview = false
    private var launchFinished = false
    private var defaultLaunch = false
    private var waitingForOperationCleanup = false
    override init() {
        super.init()
        PreviewStartupTrace.record("application delegate initialized")
    }
    func configure(sceneCoordinator:WorkspaceSceneCoordinator,
                   explicitPreview:Bool,lifecycleAudit:WindowSceneLifecycleAudit?) {
        let newlyAttached = self.sceneCoordinator !== sceneCoordinator
        self.sceneCoordinator = sceneCoordinator
        self.explicitPreview = explicitPreview; self.lifecycleAudit = lifecycleAudit
        if newlyAttached && launchFinished { finishSceneRegistration() }
    }
    func applicationWillFinishLaunching(_ notification: Notification) {
        PreviewStartupTrace.applicationState("application will finish launching")
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let defaultLaunch = (notification.userInfo?[NSApplication.launchIsDefaultUserInfoKey] as? NSNumber)?.boolValue
        self.defaultLaunch = defaultLaunch == true; launchFinished = true
        PreviewStartupTrace.applicationState("application did finish launching", defaultLaunch: defaultLaunch)
        finishSceneRegistration()
        if CommandLine.arguments.contains("--render-preview") {
            DispatchQueue.main.async {
                PreviewStartupTrace.applicationState("post-launch main queue turn", defaultLaunch: defaultLaunch)
            }
            // Observation only: capture does not wait for this callback.
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                PreviewStartupTrace.applicationState("post-launch two-second observation", defaultLaunch: defaultLaunch)
            }
        }
    }
    private func finishSceneRegistration() {
        sceneCoordinator?.didFinishLaunching(defaultLaunch:lifecycleAudit == nil && defaultLaunch,
            explicitPresentation:lifecycleAudit == nil && explicitPreview)
        lifecycleAudit?.start()
    }
    func applicationDidBecomeActive(_ notification:Notification) {
        // A background App Intent does not cause this callback. The controlled
        // lifecycle audit drives its own requests after proving zero windows.
        if lifecycleAudit == nil { sceneCoordinator?.didBecomeActive() }
    }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows flag:Bool) -> Bool {
        guard let sceneCoordinator else { return true }
        sceneCoordinator.requestPresentation(reason:.reopen)
        return false
    }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        if waitingForOperationCleanup { return .terminateLater }
        guard model?.confirmDiscardEdits() != false else { return .terminateCancel }
        guard let model else { return .terminateNow }
        guard model.toolDrafts.confirmDiscardForExit() else { return .terminateCancel }
        model.captureTerminationDecision()
        waitingForOperationCleanup = true
        Task { @MainActor in
            let ready = await model.prepareForTermination()
            let authorized = ready && model.authorizeTerminationIfUnchanged()
            waitingForOperationCleanup = false
            sender.reply(toApplicationShouldTerminate: authorized)
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification:Notification) {
        if let model { model.toolDrafts.dispose(model:model) }
    }
}

/// Keep SwiftUI's existing window delegate while adding a guard for unsaved edits.
@MainActor struct WorkspaceWindowGuard:NSViewRepresentable {
    let model:Workspace
    let sceneCoordinator:WorkspaceSceneCoordinator
    let lifecycleAudit:WindowSceneLifecycleAudit?
    func makeCoordinator() -> Coordinator {
        Coordinator(model:model,sceneCoordinator:sceneCoordinator,lifecycleAudit:lifecycleAudit)
    }
    func makeNSView(context:Context) -> GuardView {
        let view = GuardView(); view.coordinator = context.coordinator
        PreviewStartupTrace.record("workspace guard view created")
        return view
    }
    func updateNSView(_ nsView:GuardView,context:Context) {
        context.coordinator.model = model
        context.coordinator.install(on:nsView.window,guardID:nsView.guardID)
    }
    static func dismantleNSView(_ nsView:GuardView,coordinator:Coordinator) {
        coordinator.sceneCoordinator?.windowAttachmentEnded(id:nsView.guardID)
        if let window = coordinator.installedWindow, window.delegate === coordinator { window.delegate = coordinator.previous }
        coordinator.installedWindow = nil
    }
    @MainActor final class GuardView:NSView {
        let guardID = UUID()
        weak var coordinator:Coordinator?
        override func viewWillMove(toWindow newWindow:NSWindow?) {
            // A non-nil AppKit destination is evidence of actual association.
            // SwiftUI may evaluate/discard the old scene after it closes, so a
            // declarative builder or an unattached guard cannot supply this.
            if newWindow != nil { coordinator?.sceneCoordinator?.windowAttachmentBegan(id:guardID) }
            else { coordinator?.sceneCoordinator?.windowAttachmentEnded(id:guardID) }
            super.viewWillMove(toWindow:newWindow)
        }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if window == nil { coordinator?.sceneCoordinator?.windowAttachmentEnded(id:guardID) }
            else { coordinator?.install(on:window,guardID:guardID) }
        }
    }
    final class Coordinator:NSObject,NSWindowDelegate {
        @MainActor weak var model:Workspace?
        @MainActor weak var sceneCoordinator:WorkspaceSceneCoordinator?
        @MainActor weak var lifecycleAudit:WindowSceneLifecycleAudit?
        // NSObject's introspection/forwarding overrides are nonisolated. Keep
        // that existing delegate reference outside the UI-isolated state; only
        // install(on:) changes it, as part of AppKit's main-actor lifecycle.
        weak var previous:(any NSWindowDelegate)?
        @MainActor weak var installedWindow:NSWindow?
        @MainActor init(model:Workspace,sceneCoordinator:WorkspaceSceneCoordinator,lifecycleAudit:WindowSceneLifecycleAudit?) {
            self.model = model; self.sceneCoordinator = sceneCoordinator; self.lifecycleAudit = lifecycleAudit
        }
        @MainActor func install(on window:NSWindow?,guardID:UUID) {
            guard let window else { return }
            guard installedWindow !== window else {
                sceneCoordinator?.windowAttachmentEnded(id:guardID)
                return
            }
            if let installedWindow, installedWindow.delegate === self { installedWindow.delegate = previous }
            previous = window.delegate; installedWindow = window; window.delegate = self
            sceneCoordinator?.windowAttached(window,guardID:guardID)
            if let model { lifecycleAudit?.windowAttached(window,model:model) }
        }
        @MainActor func windowShouldClose(_ sender:NSWindow) -> Bool {
            if let model { lifecycleAudit?.windowCloseRequested(sender,model:model) }
            guard model?.confirmDiscardEdits() != false else { return false }
            guard model?.toolDrafts.confirmDiscardForExit() != false else { return false }
            let drafts = model?.toolDrafts.checkpoints
            let close = previous?.windowShouldClose?(sender) ?? true
            guard drafts == model?.toolDrafts.checkpoints else { return false }
            if close { model?.cancelDocumentOpenings() }
            return close
        }
        override func responds(to selector:Selector!) -> Bool { super.responds(to:selector) || (previous?.responds(to:selector) ?? false) }
        override func forwardingTarget(for selector:Selector!) -> Any? { previous }
    }
}
