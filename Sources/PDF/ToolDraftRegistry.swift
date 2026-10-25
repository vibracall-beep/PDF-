import Foundation
import AppKit

/// Drafts remain in this workspace's memory across SwiftUI navigation. They
/// are not saved as unencrypted preference files or mixed with reader recovery.
@MainActor protocol ToolDraftSource: AnyObject {
    var draftID: String { get }
    var draftTitle: String { get }
    var draftRevision: UUID { get }
    var hasUnsavedDraft: Bool { get }
    func disposeDraft(model:Workspace)
}
extension ToolDraftSource { func disposeDraft(model:Workspace) {} }

struct ToolDraftCheckpoint: Equatable {
    let id: String
    let revision: UUID
    let unsaved: Bool
}

@MainActor final class ToolDraftRegistry {
    private var sessions: [String: any ToolDraftSource] = [:]
    func session<T: ToolDraftSource>(id: String, create: () -> T) -> T {
        if let existing = sessions[id] {
            guard let typed = existing as? T else { preconditionFailure("A draft ID was reused by a different workspace type.") }
            return typed
        }
        let value = create()
        precondition(value.draftID == id, "A draft registration must preserve its stable identifier.")
        sessions[id] = value
        return value
    }
    var checkpoints: [ToolDraftCheckpoint] {
        sessions.keys.sorted().compactMap { id in
            sessions[id].map { ToolDraftCheckpoint(id:id,revision:$0.draftRevision,unsaved:$0.hasUnsavedDraft) }
        }
    }
    var unsavedTitles: [String] { sessions.keys.sorted().compactMap { id in
        guard let value = sessions[id],value.hasUnsavedDraft else { return nil }; return value.draftTitle
    } }
    func dispose(model:Workspace) { for value in sessions.values { value.disposeDraft(model:model) }; sessions = [:] }
    func confirmDiscardForExit() -> Bool {
        let titles = unsavedTitles
        guard !titles.isEmpty else { return true }
        let alert = NSAlert()
        alert.messageText = "Há revisões de ferramentas ainda não exportadas"
        alert.informativeText = titles.joined(separator:"\n") + "\n\nAs revisões permanecem disponíveis ao navegar neste espaço. Para preservá-las após sair, volte e exporte as cópias. A recuperação do leitor não inclui estes rascunhos."
        alert.alertStyle = .warning
        alert.addButton(withTitle:"Continuar editando")
        alert.addButton(withTitle:"Sair descartando revisões")
        // Do not clear anything here: a later cleanup failure must leave all
        // drafts intact if the application cannot complete termination.
        return alert.runModal() == .alertSecondButtonReturn
    }
}
