import SwiftUI
import AppKit

@MainActor final class PDFApplicationDelegate:NSObject,NSApplicationDelegate {
    weak var model:Workspace?
    private var waitingForOperationCleanup = false
    override init() {
        super.init()
        PreviewStartupTrace.record("application delegate initialized")
    }
    func applicationWillFinishLaunching(_ notification: Notification) {
        PreviewStartupTrace.record("application will finish launching")
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        PreviewStartupTrace.record("application did finish launching")
    }
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        if waitingForOperationCleanup { return .terminateLater }
        guard model?.confirmDiscardEdits() != false else { return .terminateCancel }
        guard let model else { return .terminateNow }
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
}

/// Keep SwiftUI's existing window delegate while adding a guard for unsaved edits.
struct WorkspaceWindowGuard:NSViewRepresentable {
    let model:Workspace
    func makeCoordinator() -> Coordinator { Coordinator(model:model) }
    func makeNSView(context:Context) -> GuardView { let view = GuardView(); view.coordinator = context.coordinator; return view }
    func updateNSView(_ nsView:GuardView,context:Context) { context.coordinator.model = model; context.coordinator.install(on:nsView.window) }
    static func dismantleNSView(_ nsView:GuardView,coordinator:Coordinator) {
        if let window = coordinator.installedWindow, window.delegate === coordinator { window.delegate = coordinator.previous }
        coordinator.installedWindow = nil
    }
    final class GuardView:NSView {
        weak var coordinator:Coordinator?
        override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); coordinator?.install(on:window) }
    }
    final class Coordinator:NSObject,NSWindowDelegate {
        weak var model:Workspace?
        weak var previous:(any NSWindowDelegate)?
        weak var installedWindow:NSWindow?
        init(model:Workspace) { self.model = model }
        func install(on window:NSWindow?) {
            guard let window, installedWindow !== window else { return }
            if let installedWindow, installedWindow.delegate === self { installedWindow.delegate = previous }
            previous = window.delegate; installedWindow = window; window.delegate = self
        }
        func windowShouldClose(_ sender:NSWindow) -> Bool {
            guard model?.confirmDiscardEdits() != false else { return false }
            let close = previous?.windowShouldClose?(sender) ?? true
            if close { model?.cancelDocumentOpenings() }
            return close
        }
        override func responds(to selector:Selector!) -> Bool { super.responds(to:selector) || (previous?.responds(to:selector) ?? false) }
        override func forwardingTarget(for selector:Selector!) -> Any? { previous }
    }
}
