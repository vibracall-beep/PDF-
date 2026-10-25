import AppKit
import Combine
import SwiftUI

/// The app owns one controller, bound to the same preferences as its SwiftUI
/// scenes. Creating preferences or a controller never changes AppKit appearance:
/// ownership starts only when an actual application window attaches.
@MainActor final class ApplicationAppearanceController: ObservableObject {
    @MainActor private final class WindowRecord {
        weak var window: NSWindow?
        let previous: NSAppearance?
        var appliedName: NSAppearance.Name?
        init(_ window: NSWindow) {
            self.window = window
            previous = window.appearance
        }
    }

    private let preferences: AppearancePreferences
    private weak var application: NSApplication?
    private var previousApplicationAppearance: NSAppearance?
    private var appliedApplicationName: NSAppearance.Name?
    private var subscription: AnyCancellable?
    private var windows: [ObjectIdentifier: WindowRecord] = [:]
    private(set) var isActive = false
    private(set) var selection = "system"

    init(preferences: AppearancePreferences) { self.preferences = preferences }

    /// AppKit toolbar materials and SwiftUI labels must resolve the same user
    /// preference, including when an older SDK's binary runs on a newer OS.
    /// This does not show/focus a window or modify the system's user defaults.
    func attach(to window: NSWindow) {
        remember(window)
        if !isActive {
            let application = NSApplication.shared
            self.application = application
            previousApplicationAppearance = application.appearance
            isActive = true
            // Published emits before its backing state changes. Use the emitted
            // selection, never reread preferences.state inside this callback.
            subscription = preferences.$state.map(\.colorScheme).removeDuplicates().sink { [weak self] selection in
                self?.apply(selection: selection)
            }
        } else {
            apply(selection: preferences.state.colorScheme)
        }
    }

    private func remember(_ window: NSWindow) {
        let identity = ObjectIdentifier(window)
        if windows[identity]?.window !== window { windows[identity] = WindowRecord(window) }
    }

    private func apply(selection: String) {
        guard isActive, let application else { return }
        self.selection = selection
        let appearance: NSAppearance?
        switch selection {
        case "dark": appearance = NSAppearance(named: .darkAqua)
        case "light": appearance = NSAppearance(named: .aqua)
        default: appearance = nil // Inherit changes made in macOS Appearance.
        }
        if application.appearance?.name != appearance?.name { application.appearance = appearance }
        appliedApplicationName = appearance?.name
        windows = windows.filter { $0.value.window != nil }
        var visited = Set<ObjectIdentifier>()
        func update(_ window: NSWindow) {
            let identity = ObjectIdentifier(window)
            guard visited.insert(identity).inserted else { return }
            remember(window)
            if window.appearance?.name != appearance?.name { window.appearance = appearance }
            windows[identity]?.appliedName = appearance?.name
            // Sheets created later inherit application appearance. Include live
            // sheets and child windows when the user changes their preference.
            if let sheet = window.attachedSheet { update(sheet) }
            for child in window.childWindows ?? [] { update(child) }
        }
        for window in windows.values.compactMap(\.window) { update(window) }
    }

    /// Release only appearances still owned by this controller. Used by the
    /// isolated native audit; ordinary scenes keep this owner for the app life.
    func stop() {
        subscription?.cancel(); subscription = nil
        for record in windows.values {
            if let window = record.window, window.appearance?.name == record.appliedName {
                window.appearance = record.previous
            }
        }
        windows.removeAll()
        if let application, application.appearance?.name == appliedApplicationName {
            application.appearance = previousApplicationAppearance
        }
        application = nil
        previousApplicationAppearance = nil
        appliedApplicationName = nil
        isActive = false
    }
}

/// Observe real AppKit attachment without replacing SwiftUI's window, toolbar,
/// hosting view or delegate. Weak window records survive route/view rebuilds
/// but do not retain closed windows or depend on declarative body evaluation.
@MainActor private struct ApplicationAppearanceWindowBinding: NSViewRepresentable {
    let controller: ApplicationAppearanceController
    func makeNSView(context: Context) -> AppearanceView {
        let view = AppearanceView()
        view.controller = controller
        return view
    }
    func updateNSView(_ view: AppearanceView, context: Context) {
        view.controller = controller
        if let window = view.window { controller.attach(to: window) }
    }
    @MainActor final class AppearanceView: NSView {
        weak var controller: ApplicationAppearanceController?
        override func viewWillMove(toWindow newWindow: NSWindow?) {
            if let newWindow { controller?.attach(to: newWindow) }
            super.viewWillMove(toWindow: newWindow)
        }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if let window { controller?.attach(to: window) }
        }
    }
}

extension View {
    @MainActor func applicationAppearance(_ controller: ApplicationAppearanceController) -> some View {
        background(ApplicationAppearanceWindowBinding(controller: controller).frame(width: 0, height: 0))
    }
}

/// Real AppKit ownership checks, without displaying windows or changing the
/// user's saved preferences. Rendering/contrast still requires the GUI matrix.
@MainActor enum ApplicationAppearanceAuditChecks {
    static func run() throws {
        func require(_ value: @autoclosure () -> Bool, _ detail: String) throws {
            guard value() else { throw NSError(domain: "PDF.ApplicationAppearanceAudit", code: 1,
                userInfo: [NSLocalizedDescriptionKey: detail]) }
        }
        let suite = "PDF-appearance-owner-audit-" + UUID().uuidString
        guard let defaults = UserDefaults(suiteName: suite) else {
            throw NSError(domain: "PDF.ApplicationAppearanceAudit", code: 2)
        }
        defer { defaults.removePersistentDomain(forName: suite) }
        let application = NSApplication.shared
        let original = application.appearance
        let preferences = AppearancePreferences(defaults: defaults)
        preferences.state.colorScheme = "dark"
        let owner = ApplicationAppearanceController(preferences: preferences)
        let first = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 120, height: 100),
            styleMask: [.titled], backing: .buffered, defer: true)
        let settings = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 100, height: 80),
            styleMask: [.titled], backing: .buffered, defer: true)
        let child = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 80, height: 60),
            styleMask: [.titled], backing: .buffered, defer: true)
        for window in [first, settings, child] { window.isReleasedWhenClosed = false }
        first.appearance = NSAppearance(named: .aqua)
        settings.appearance = NSAppearance(named: .vibrantLight)
        defer { owner.stop(); first.close(); settings.close(); child.close(); application.appearance = original }
        try require(!owner.isActive && application.appearance?.name == original?.name,
            "Inicializar preferências/dono alterou a aparência sem uma janela real.")
        owner.attach(to: first)
        try require(application.appearance?.name == .darkAqua && first.appearance?.name == .darkAqua,
            "A primeira janela não recebeu a mesma aparência escura da aplicação.")
        owner.attach(to: settings); owner.attach(to: first)
        preferences.state.colorScheme = "light"
        try require(owner.selection == "light" && application.appearance?.name == .aqua &&
            first.appearance?.name == .aqua && settings.appearance?.name == .aqua,
            "A mudança emitida por Published não atualizou todas as janelas imediatamente.")
        first.addChildWindow(child, ordered: .above)
        defer { first.removeChildWindow(child) }
        preferences.state.colorScheme = "dark"
        try require(child.appearance?.name == .darkAqua,
            "A mudança de aparência ignorou uma janela filha do espaço de trabalho.")
        preferences.state.colorScheme = "system"
        try require(application.appearance == nil && first.appearance == nil &&
            settings.appearance == nil && child.appearance == nil,
            "Sistema manteve um override em vez de devolver a herança ao macOS.")
        let unrelated = AppearancePreferences(defaults: defaults)
        unrelated.state.colorScheme = "light"
        try require(application.appearance == nil && owner.selection == "system",
            "Outra instância de preferências alterou o dono real da aplicação.")
        owner.stop()
        preferences.state.colorScheme = "dark"
        try require(!owner.isActive && application.appearance?.name == original?.name,
            "Encerrar o dono não cancelou sua assinatura nem restaurou a aparência anterior.")
        try require(first.appearance?.name == .aqua && settings.appearance?.name == .vibrantLight &&
            child.appearance == nil,
            "Encerrar o dono não restaurou os overrides anteriores das janelas.")
        owner.attach(to: first)
        first.appearance = NSAppearance(named: .vibrantLight)
        application.appearance = NSAppearance(named: .vibrantLight)
        owner.stop()
        try require(first.appearance?.name == .vibrantLight && application.appearance?.name == .vibrantLight,
            "Encerrar o dono apagou uma aparência divergente definida depois por outro proprietário.")
        try require(!first.isVisible && !settings.isVisible && !child.isVisible,
            "A propagação de aparência apresentou uma janela durante a auditoria.")
    }
}
