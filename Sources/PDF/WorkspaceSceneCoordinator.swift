import AppKit
import Combine

/// Presentation is separate from document ownership. A background invocation
/// can register its scene without opening a window or activating the app.
@MainActor final class WorkspaceScenePresentation {
    enum Reason: String {
        case preview, initialLaunch, activation, reopen, openDocument, showWorkspace
    }
    typealias Schedule = (@escaping () -> Void) -> Void
    private let schedule: Schedule
    private let presentExisting: () -> Bool
    private let trace: (String) -> Void
    private var openWindow: (() -> Void)?
    private var launchFinished = false
    private var pending = false
    private var scheduled = false
    private var constructing = false
    private var opening = false
    private var actions: [() -> Void] = []

    init(schedule: @escaping Schedule, presentExisting: @escaping () -> Bool,
         trace: @escaping (String) -> Void = { _ in }) {
        self.schedule = schedule; self.presentExisting = presentExisting; self.trace = trace
    }

    func registerOpenWindow(_ action: @escaping () -> Void) {
        let first = openWindow == nil
        openWindow = action
        if first { trace("openWindow action registered") }
        enqueue()
    }

    func didFinishLaunching(defaultLaunch: Bool, explicitPresentation: Bool) {
        launchFinished = true
        if explicitPresentation { requestPresentation(reason: .preview) }
        else if defaultLaunch { requestPresentation(reason: .initialLaunch) }
        else { enqueue() }
    }

    func requestPresentation(reason: Reason, action: (() -> Void)? = nil) {
        trace("presentation requested: " + reason.rawValue)
        pending = true
        if let action { actions.append(action) }
        enqueue()
    }

    func didBecomeActive(hasVisibleOrMiniaturizedWindow: Bool) {
        // Activation is not permission to replace the Settings window's focus
        // or to expand a workspace that the user deliberately minimized.
        guard !hasVisibleOrMiniaturizedWindow else { return }
        requestPresentation(reason: .activation)
    }

    func sceneConstructionBegan() {
        constructing = true
        trace("scene construction began")
    }

    func windowAttached() {
        constructing = false; opening = false
        trace("workspace window attached")
        enqueue()
    }

    func allWindowsClosed() {
        constructing = false; opening = false
        trace("last workspace closed")
        // Closing the last window is not itself a request to reopen it.
        enqueue()
    }

    private func enqueue() {
        guard pending, launchFinished, openWindow != nil, !scheduled else { return }
        scheduled = true
        // Commands can register while SwiftUI evaluates its body. Never call
        // openWindow or activate AppKit from that evaluation stack.
        schedule { [weak self] in
            guard let self else { return }
            self.scheduled = false
            self.presentIfNeeded()
        }
    }

    private func presentIfNeeded() {
        guard pending, launchFinished, let openWindow else { return }
        if presentExisting() {
            pending = false; opening = false
            let ready = actions; actions.removeAll()
            trace("existing workspace presented")
            for action in ready { action() }
            return
        }
        // Automatic restoration may already be building the same scene.
        // Registration, activation and repeated menu actions must not create
        // another window while either automatic or explicit opening is pending.
        guard !constructing, !opening else { return }
        opening = true
        trace("openWindow action invoked")
        openWindow()
    }
}

/// Owns only weak references to the genuine WindowGroup windows. Closing a
/// window keeps the shared Workspace (tabs and recovery state) intact.
@MainActor final class WorkspaceSceneCoordinator: NSObject, ObservableObject {
    static let workspaceID = "pdf-workspace"
    private let windows = NSHashTable<NSWindow>.weakObjects()
    private lazy var presentation = WorkspaceScenePresentation(
        schedule: { operation in DispatchQueue.main.async(execute: operation) },
        presentExisting: { [weak self] in self?.presentExistingWindow() ?? false },
        trace: { PreviewStartupTrace.record("workspace scene", details: "; " + $0) })

    override init() {
        super.init()
        NotificationCenter.default.addObserver(self, selector:#selector(workspaceWillClose(_:)),
            name:NSWindow.willCloseNotification, object:nil)
    }
    deinit { NotificationCenter.default.removeObserver(self) }

    var workspaceWindows: [NSWindow] { windows.allObjects }

    func registerOpenWindow(_ action: @escaping () -> Void) { presentation.registerOpenWindow(action) }
    func didFinishLaunching(defaultLaunch: Bool, explicitPresentation: Bool) {
        presentation.didFinishLaunching(defaultLaunch: defaultLaunch, explicitPresentation: explicitPresentation)
    }
    func didBecomeActive() {
        presentation.didBecomeActive(hasVisibleOrMiniaturizedWindow:
            NSApplication.shared.windows.contains { $0.isVisible || $0.isMiniaturized })
    }
    func requestPresentation(reason: WorkspaceScenePresentation.Reason = .showWorkspace,
                             action: (() -> Void)? = nil) {
        presentation.requestPresentation(reason: reason, action: action)
    }
    func sceneConstructionBegan() {
        if workspaceWindows.isEmpty { presentation.sceneConstructionBegan() }
    }
    func windowAttached(_ window: NSWindow) {
        windows.add(window)
        presentation.windowAttached()
    }
    func windowClosed(_ window: NSWindow) {
        guard windows.contains(window) else { return }
        windows.remove(window)
        if workspaceWindows.isEmpty { presentation.allWindowsClosed() }
    }
    @objc private func workspaceWillClose(_ notification:Notification) {
        if let window = notification.object as? NSWindow { windowClosed(window) }
    }

    private func presentExistingWindow() -> Bool {
        let candidates = workspaceWindows
        guard let window = candidates.first(where: \.isKeyWindow)
                ?? candidates.first(where: \.isMainWindow) ?? candidates.first else { return false }
        if window.isMiniaturized { window.deminiaturize(nil) }
        window.makeKeyAndOrderFront(nil)
        if !NSApplication.shared.isActive { NSApplication.shared.activate(ignoringOtherApps: true) }
        return true
    }
}
