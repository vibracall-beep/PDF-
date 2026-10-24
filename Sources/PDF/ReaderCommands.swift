import SwiftUI

/// Commands follow the focused scene; editing text keeps AppKit's own undo responder chain.
struct ReaderCommandActions {
    var focusSearch: () -> Void
    var findNext: () -> Void
    var focusPage: () -> Void
    var toggleSidebar: () -> Void
    var toggleInspector: () -> Void
    var share: () -> Void
}
private struct ReaderCommandKey: FocusedValueKey { typealias Value = ReaderCommandActions }
private struct CatalogSearchKey: FocusedValueKey { typealias Value = () -> Void }
private struct RecoveryCommandKey: FocusedValueKey { typealias Value = () -> Void }
extension FocusedValues {
    var readerCommandActions: ReaderCommandActions? {
        get { self[ReaderCommandKey.self] }
        set { self[ReaderCommandKey.self] = newValue }
    }
    var catalogSearchAction: (() -> Void)? {
        get { self[CatalogSearchKey.self] }
        set { self[CatalogSearchKey.self] = newValue }
    }
    var recoveryAction: (() -> Void)? {
        get { self[RecoveryCommandKey.self] }
        set { self[RecoveryCommandKey.self] = newValue }
    }
}

struct PDFMenuCommands:Commands {
    @ObservedObject var model:Workspace
    @ObservedObject private var shortcutStore:AdvancedCustomizationStore
    init(model:Workspace, preferences:AppearancePreferences) { self.model = model; shortcutStore = preferences.advanced }
    @FocusedValue(\.readerCommandActions) private var readerActions
    @FocusedValue(\.catalogSearchAction) private var catalogSearch
    @FocusedValue(\.recoveryAction) private var recoveryAction
    var body:some Commands {
            CommandGroup(replacing:.newItem) {
                Button("Abrir PDF…") { model.open() }.configuredShortcut("action:open",store:shortcutStore)
                Button("Abrir PDF em nova aba…") { model.open() }.configuredShortcut("action:new-tab",store:shortcutStore)
                Button("Fechar aba atual") { if let id = model.activeSessionID { model.closeSession(id) } }.configuredShortcut("action:close-tab",store:shortcutStore).disabled(model.activeSessionID == nil)
                Menu("Abrir recente") {
                    ForEach(model.recentURLs, id:\.path) { url in Button(url.lastPathComponent) { model.open(url:url) } }
                    Divider()
                    Button("Limpar recentes") { model.clearRecent() }
                }
            }
            CommandGroup(replacing:.saveItem) {
                Button("Salvar cópia…") { model.save() }.configuredShortcut("action:save",store:shortcutStore).disabled(model.document == nil)
            }
            CommandGroup(replacing:.printItem) {
                Button("Imprimir…") { model.printDocument() }.configuredShortcut("action:print",store:shortcutStore).disabled(model.document == nil)
            }
            CommandMenu("Documento") {
                Button("Buscar…") {
                    if model.section == "Leitor",let actions = readerActions { actions.focusSearch() }
                    else { catalogSearch?() }
                }.configuredShortcut("action:search",store:shortcutStore)
                Button("Próxima ocorrência") { readerActions?.findNext() }.configuredShortcut("action:find-next",store:shortcutStore).disabled(model.section != "Leitor" || model.document == nil)
                Button("Ir para página…") { readerActions?.focusPage() }.configuredShortcut("action:page",store:shortcutStore).disabled(model.section != "Leitor" || model.document == nil)
                Divider()
                Button("Aba anterior") { activateNeighbor(-1) }.configuredShortcut("action:previous-tab",store:shortcutStore).disabled(model.sessions.count < 2)
                Button("Próxima aba") { activateNeighbor(1) }.configuredShortcut("action:next-tab",store:shortcutStore).disabled(model.sessions.count < 2)
                Button("Recuperar trabalho…") { recoveryAction?() }.configuredShortcut("action:recovery",store:shortcutStore)
                Divider()
                Button("Página anterior") { model.previousPage() }.configuredShortcut("action:previous-page",store:shortcutStore)
                Button("Próxima página") { model.nextPage() }.configuredShortcut("action:next-page",store:shortcutStore)
                Divider()
                Button("Realçar seleção") { model.highlight() }.configuredShortcut("action:highlight",store:shortcutStore)
                Button("Marcar página") { model.toggleBookmark() }.configuredShortcut("action:bookmark",store:shortcutStore)
                Button("Girar página atual") { model.rotatePage() }
                Button("Editar anotações…") { readerActions?.toggleInspector() }.configuredShortcut("action:inspector",store:shortcutStore).disabled(model.section != "Leitor" || model.document == nil)
                Button("Desfazer anotação") { model.undoAnnotation() }.configuredShortcut("action:undo-annotation",store:shortcutStore).disabled(!model.canUndoAnnotation)
                Button("Refazer anotação") { model.redoAnnotation() }.configuredShortcut("action:redo-annotation",store:shortcutStore).disabled(!model.canRedoAnnotation)
                Divider()
                Button("Mostrar/ocultar páginas e sumário") { readerActions?.toggleSidebar() }.configuredShortcut("action:sidebar",store:shortcutStore).disabled(model.section != "Leitor")
                Button("Compartilhar…") { readerActions?.share() }.configuredShortcut("action:share",store:shortcutStore).disabled(model.section != "Leitor" || model.document == nil)
            }
    }
    private func activateNeighbor(_ offset:Int) {
        guard !model.sessions.isEmpty else { return }
        let current = model.sessions.firstIndex { $0.id == model.activeSessionID } ?? 0
        model.activateSession(model.sessions[(current+offset+model.sessions.count) % model.sessions.count].id)
    }
}

@MainActor enum PDFCommandExecution {
    /// Used by the palette in the same focused scene as the ordinary menus.
    @discardableResult static func perform(_ id:String,model:Workspace,reader:ReaderCommandActions?,search:()->Void,recovery:()->Void) -> Bool {
        switch id {
        case "action:open", "action:new-tab": model.open()
        case "action:close-tab": if let active = model.activeSessionID { model.closeSession(active) }
        case "action:save": model.save()
        case "action:print": model.printDocument()
        case "action:search": if model.section == "Leitor",let reader { reader.focusSearch() } else { search() }
        case "action:find-next": reader?.findNext()
        case "action:page": reader?.focusPage()
        case "action:previous-page": model.previousPage()
        case "action:next-page": model.nextPage()
        case "action:highlight": model.highlight()
        case "action:bookmark": model.toggleBookmark()
        case "action:inspector": reader?.toggleInspector()
        case "action:undo-annotation": model.undoAnnotation()
        case "action:redo-annotation": model.redoAnnotation()
        case "action:sidebar": reader?.toggleSidebar()
        case "action:share": reader?.share()
        case "action:recovery": recovery()
        case "action:previous-tab", "action:next-tab":
            guard !model.sessions.isEmpty else { return true }
            let index = model.sessions.firstIndex { $0.id == model.activeSessionID } ?? 0
            let delta = id == "action:previous-tab" ? -1 : 1
            model.activateSession(model.sessions[(index+delta+model.sessions.count) % model.sessions.count].id)
        default:return false
        }
        return true
    }
}
