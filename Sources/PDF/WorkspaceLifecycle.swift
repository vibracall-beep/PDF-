import SwiftUI
import AppKit

@MainActor final class PDFApplicationDelegate:NSObject,NSApplicationDelegate {
    weak var model:Workspace?
    func applicationShouldTerminate(_ sender:NSApplication) -> NSApplication.TerminateReply {
        model?.confirmDiscardEdits() == false ? .terminateCancel : .terminateNow
    }
}

/// Keep SwiftUI's existing window delegate while adding a guard for unsaved edits.
struct WorkspaceWindowGuard:NSViewRepresentable {
    let model:Workspace
    func makeCoordinator() -> Coordinator { Coordinator(model:model) }
    func makeNSView(context:Context) -> GuardView { let view = GuardView(); view.coordinator = context.coordinator; return view }
    func updateNSView(_ nsView:GuardView,context:Context) { context.coordinator.model = model; context.coordinator.install(on:nsView.window) }
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
            previous = window.delegate; installedWindow = window; window.delegate = self
        }
        func windowShouldClose(_ sender:NSWindow) -> Bool {
            guard model?.confirmDiscardEdits() != false else { return false }
            return previous?.windowShouldClose?(sender) ?? true
        }
        override func responds(to selector:Selector!) -> Bool { super.responds(to:selector) || (previous?.responds(to:selector) ?? false) }
        override func forwardingTarget(for selector:Selector!) -> Any? { previous }
    }
}
