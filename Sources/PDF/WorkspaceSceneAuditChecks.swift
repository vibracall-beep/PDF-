import Foundation

/// Deterministic scheduling checks complement the separate real WindowGroup
/// lifecycle audit. These checks do not claim that SwiftUI opened a window.
@MainActor enum WorkspaceSceneAuditChecks {
    static func run() throws {
        func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            guard condition() else { throw NSError(domain: "PDF.WorkspaceSceneAudit", code: 1,
                userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        @MainActor final class Harness {
            var queue: [() -> Void] = []
            var hasWindow = false
            var requests = 0
            var presentations = 0
            lazy var policy = WorkspaceScenePresentation(schedule: { [unowned self] in queue.append($0) },
                presentExisting: { [unowned self] in
                    guard hasWindow else { return false }
                    presentations += 1; return true
                })
            func register() { policy.registerOpenWindow { [unowned self] in requests += 1 } }
            func drain() throws {
                var turns = 0
                while !queue.isEmpty {
                    turns += 1
                    guard turns <= 20 else { throw NSError(domain: "PDF.WorkspaceSceneAudit", code: 2) }
                    queue.removeFirst()()
                }
            }
            func attach() { hasWindow = true; policy.windowAttached() }
        }

        let early = Harness()
        early.register(); early.policy.requestPresentation(reason: .showWorkspace)
        try early.drain()
        try require(early.requests == 0, "A cena foi aberta antes de didFinishLaunching.")
        early.policy.didFinishLaunching(defaultLaunch: false, explicitPresentation: false)
        try require(early.requests == 0, "openWindow foi executado de forma reentrante na pilha de registro.")
        try early.drain()
        try require(early.requests == 1, "O pedido anterior ao lançamento foi perdido.")

        let late = Harness()
        var opened: [Int] = []
        late.policy.requestPresentation(reason: .openDocument, action: { opened.append(1) })
        late.policy.didFinishLaunching(defaultLaunch: false, explicitPresentation: false)
        try late.drain()
        try require(late.requests == 0 && opened.isEmpty, "Abrir foi perdido ou executado antes do registro da cena.")
        late.register(); late.register(); try late.drain()
        try require(late.requests == 1 && opened.isEmpty, "Registro tardio duplicou janela ou abriu documento sem janela.")
        late.policy.sceneConstructionBegan()
        late.policy.requestPresentation(reason: .reopen)
        late.policy.requestPresentation(reason: .openDocument, action: { opened.append(2) })
        try late.drain()
        try require(late.requests == 1 && opened.isEmpty, "Pedidos concorrentes duplicaram a construção da cena.")
        late.attach(); try late.drain()
        try require(late.requests == 1 && opened == [1, 2], "Ações aguardando janela não foram preservadas na ordem original.")
        late.hasWindow = false; late.policy.allWindowsClosed(); try late.drain()
        try require(late.requests == 1, "Fechar a última janela reabriu a cena sem pedido do usuário.")
        late.policy.requestPresentation(reason: .showWorkspace); try late.drain()
        try require(late.requests == 2, "O pedido após fechar a última janela não criou uma nova cena.")
        late.attach(); try late.drain()
        late.policy.requestPresentation(reason: .activation); late.register(); try late.drain()
        try require(late.requests == 2, "Ativar uma janela existente criou uma duplicata.")

        let restored = Harness()
        restored.register(); restored.policy.sceneConstructionBegan()
        restored.policy.didFinishLaunching(defaultLaunch: true, explicitPresentation: false)
        try restored.drain()
        try require(restored.requests == 0, "O lançamento duplicou uma cena que o SwiftUI já estava restaurando.")
        restored.attach(); try restored.drain()
        try require(restored.requests == 0 && restored.presentations == 1, "A cena restaurada não foi reapresentada.")

        let background = Harness()
        background.register()
        background.policy.didFinishLaunching(defaultLaunch: false, explicitPresentation: false)
        try background.drain()
        try require(background.requests == 0 && background.presentations == 0,
                    "Uma inicialização em segundo plano abriu uma janela ou tomou o foco.")
        background.policy.didBecomeActive(hasVisibleOrMiniaturizedWindow: true); try background.drain()
        try require(background.requests == 0 && background.presentations == 0,
                    "Ativar Ajustes ou uma janela minimizada abriu o workspace ou tomou seu foco.")
        background.policy.didBecomeActive(hasVisibleOrMiniaturizedWindow: false); try background.drain()
        try require(background.requests == 1, "A ativação explícita posterior não apresentou a cena.")

        for existingWorkspace in [false, true] {
            let focused = Harness(); focused.hasWindow = existingWorkspace
            focused.register(); focused.policy.didFinishLaunching(defaultLaunch: false, explicitPresentation: false)
            focused.policy.didBecomeActive(hasVisibleOrMiniaturizedWindow: true); try focused.drain()
            try require(focused.requests == 0 && focused.presentations == 0,
                        "Ativação passiva alterou Ajustes visível ou workspace minimizada.")
            focused.policy.requestPresentation(reason: .showWorkspace); try focused.drain()
            try require(existingWorkspace ? focused.requests == 0 && focused.presentations == 1 : focused.requests == 1,
                        "Mostrar explicitamente não distinguiu a janela existente do workspace ausente.")
        }

        let preview = Harness()
        preview.register(); preview.policy.didFinishLaunching(defaultLaunch: false, explicitPresentation: true)
        try preview.drain()
        try require(preview.requests == 1, "A prévia explícita dependeu incorretamente de defaultLaunch=true.")
    }
}
