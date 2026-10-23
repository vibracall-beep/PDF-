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
    @FocusedValue(\.readerCommandActions) private var readerActions
    @FocusedValue(\.catalogSearchAction) private var catalogSearch
    @FocusedValue(\.recoveryAction) private var recoveryAction
    var body:some Commands {
            CommandGroup(replacing:.newItem) {
                Button("Abrir PDF…") { model.open() }.keyboardShortcut("o")
                Button("Abrir PDF em nova aba…") { model.open() }.keyboardShortcut("t")
                Button("Fechar aba atual") { if let id = model.activeSessionID { model.closeSession(id) } }.keyboardShortcut("w").disabled(model.activeSessionID == nil)
                Menu("Abrir recente") {
                    ForEach(model.recentURLs, id:\.path) { url in Button(url.lastPathComponent) { model.open(url:url) } }
                    Divider()
                    Button("Limpar recentes") { model.clearRecent() }
                }
            }
            CommandGroup(replacing:.saveItem) {
                Button("Salvar cópia…") { model.save() }.keyboardShortcut("s", modifiers:[.command,.shift]).disabled(model.document == nil)
            }
            CommandGroup(replacing:.printItem) {
                Button("Imprimir…") { model.printDocument() }.keyboardShortcut("p").disabled(model.document == nil)
            }
            CommandMenu("Documento") {
                Button("Buscar…") {
                    if model.section == "Leitor",let actions = readerActions { actions.focusSearch() }
                    else { catalogSearch?() }
                }.keyboardShortcut("f")
                Button("Próxima ocorrência") { readerActions?.findNext() }.keyboardShortcut("g").disabled(model.section != "Leitor" || model.document == nil)
                Button("Ir para página…") { readerActions?.focusPage() }.keyboardShortcut("l").disabled(model.section != "Leitor" || model.document == nil)
                Divider()
                Button("Aba anterior") { activateNeighbor(-1) }.keyboardShortcut("[",modifiers:[.command,.shift]).disabled(model.sessions.count < 2)
                Button("Próxima aba") { activateNeighbor(1) }.keyboardShortcut("]",modifiers:[.command,.shift]).disabled(model.sessions.count < 2)
                Button("Recuperar trabalho…") { recoveryAction?() }.keyboardShortcut("t",modifiers:[.command,.shift])
                Divider()
                Button("Página anterior") { model.previousPage() }.keyboardShortcut(.leftArrow, modifiers:[.command])
                Button("Próxima página") { model.nextPage() }.keyboardShortcut(.rightArrow, modifiers:[.command])
                Divider()
                Button("Realçar seleção") { model.highlight() }.keyboardShortcut("h", modifiers:[.command,.shift])
                Button("Marcar página") { model.toggleBookmark() }.keyboardShortcut("d", modifiers:[.command,.shift])
                Button("Girar página atual") { model.rotatePage() }
                Button("Editar anotações…") { readerActions?.toggleInspector() }.keyboardShortcut("i",modifiers:[.command,.shift]).disabled(model.section != "Leitor" || model.document == nil)
                Button("Desfazer anotação") { model.undoAnnotation() }.keyboardShortcut("z",modifiers:[.command,.option]).disabled(!model.canUndoAnnotation)
                Button("Refazer anotação") { model.redoAnnotation() }.keyboardShortcut("z",modifiers:[.command,.option,.shift]).disabled(!model.canRedoAnnotation)
                Divider()
                Button("Mostrar/ocultar páginas e sumário") { readerActions?.toggleSidebar() }.keyboardShortcut("s",modifiers:[.command,.option]).disabled(model.section != "Leitor")
                Button("Compartilhar…") { readerActions?.share() }.keyboardShortcut("s",modifiers:[.command,.control]).disabled(model.section != "Leitor" || model.document == nil)
            }
    }
    private func activateNeighbor(_ offset:Int) {
        guard !model.sessions.isEmpty else { return }
        let current = model.sessions.firstIndex { $0.id == model.activeSessionID } ?? 0
        model.activateSession(model.sessions[(current+offset+model.sessions.count) % model.sessions.count].id)
    }
}
