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
                Button(actionTitle("action:open",fallback:"Abrir PDF…")) { model.open() }.configuredShortcut("action:open",store:shortcutStore)
                Button(actionTitle("action:new-tab",fallback:"Abrir PDF em nova aba…")) { model.open() }.configuredShortcut("action:new-tab",store:shortcutStore)
                Button(actionTitle("action:close-tab",fallback:"Fechar aba atual")) { if let id = model.activeSessionID { model.closeSession(id) } }.configuredShortcut("action:close-tab",store:shortcutStore).disabled(model.activeSessionID == nil)
                Menu("Abrir recente") {
                    ForEach(model.recentURLs, id:\.path) { url in Button(url.lastPathComponent) { model.open(url:url) } }
                    Divider()
                    Button("Limpar recentes") { model.clearRecent() }
                }
            }
            CommandGroup(replacing:.saveItem) {
                Button(actionTitle("action:save",fallback:"Salvar cópia…")) { model.save() }.configuredShortcut("action:save",store:shortcutStore).disabled(model.document == nil)
            }
            CommandGroup(replacing:.printItem) {
                Button(actionTitle("action:print",fallback:"Imprimir…")) { model.printDocument() }.configuredShortcut("action:print",store:shortcutStore).disabled(model.document == nil)
            }
            CommandMenu("Documento") {
                ForEach(PDFMenuLayout.documentCommands(shortcutStore.menu,hidden:false)) { command in documentButton(command) }
                let hidden = PDFMenuLayout.documentCommands(shortcutStore.menu,hidden:true)
                if !hidden.isEmpty {
                    Divider()
                    Menu("Outros comandos") { ForEach(hidden) { command in documentButton(command) } }
                }
            }
    }
    private func actionTitle(_ id:String,fallback:String) -> String { shortcutStore.menu.actionTitles[id] ?? fallback }
    private func documentButton(_ command:PDFCommandDefinition) -> some View {
        Button(shortcutStore.menu.actionTitles[command.id] ?? command.title) {
            PDFCommandExecution.perform(command.id,model:model,reader:readerActions,
                search:{ catalogSearch?() },recovery:{ recoveryAction?() })
        }.configuredShortcut(command.id,store:shortcutStore).disabled(!commandEnabled(command.id))
    }
    private func commandEnabled(_ id:String) -> Bool {
        switch id {
        case "action:search": return (model.section == "Leitor" && readerActions != nil) || catalogSearch != nil
        case "action:recovery": return recoveryAction != nil
        case "action:previous-tab","action:next-tab": return model.sessions.count > 1
        case "action:sidebar": return model.section == "Leitor" && readerActions != nil
        case "action:find-next","action:page","action:inspector","action:share": return model.section == "Leitor" && model.document != nil && readerActions != nil
        case "action:undo-annotation": return model.canUndoAnnotation
        case "action:redo-annotation": return model.canRedoAnnotation
        default: return model.document != nil
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
        case "action:rotate": model.rotatePage()
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
