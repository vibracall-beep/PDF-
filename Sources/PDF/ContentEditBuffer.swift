import Foundation
import SwiftUI

/// Keeps unprepared values distinct from the validated export plan. Selection
/// changes never discard a value or silently replace the plan already queued.
struct ContentEditBuffer: Equatable {
    private(set) var prepared: [String: ContentEditDraft] = [:]
    private(set) var drafts: [String: ContentEditDraft] = [:]
    var hasChanges: Bool { !prepared.isEmpty || !drafts.isEmpty }

    func value(for item: ContentObjectDescriptor) -> ContentEditDraft {
        drafts[item.id] ?? prepared[item.id] ?? ContentEditDraft(item)
    }
    mutating func update(_ value: ContentEditDraft, for item: ContentObjectDescriptor) {
        let baseline = prepared[item.id] ?? ContentEditDraft(item)
        if value == baseline { drafts.removeValue(forKey:item.id) }
        else { drafts[item.id] = value }
    }
    mutating func prepare(_ value: ContentEditDraft, for item: ContentObjectDescriptor, in content: ContentInspection) throws {
        var candidate = prepared; candidate[item.id] = value
        try content.validateEditSelection(Set(candidate.keys))
        _ = try value.options(for:item,pages:content.pages)
        prepared = candidate; drafts.removeValue(forKey:item.id)
    }
    mutating func prepareAll(in content: ContentInspection) throws {
        var candidate = prepared
        for (id,value) in drafts { candidate[id] = value }
        try content.validateEditSelection(Set(candidate.keys))
        for item in content.objects {
            if let value = candidate[item.id] { _ = try value.options(for:item,pages:content.pages) }
        }
        prepared = candidate; drafts = [:]
    }
    mutating func remove(_ id:String) { prepared.removeValue(forKey:id); drafts.removeValue(forKey:id) }
    mutating func reset() { prepared = [:]; drafts = [:] }
    func exportOptions(in content: ContentInspection) throws -> [[String:Any]] {
        guard drafts.isEmpty else {
            throw AdvancedDocumentValidation.failure("Existem rascunhos ainda não preparados. Prepare os rascunhos ou descarte-os antes de exportar para não salvar uma versão anterior ao que está nos controles.")
        }
        try content.validateEditSelection(Set(prepared.keys))
        return try content.objects.compactMap { item in try prepared[item.id]?.options(for:item,pages:content.pages) }
    }
}

@MainActor final class ContentEditorSession: ObservableObject, ToolDraftSource {
    let controller: AdvancedDocumentController
    let draftID = "content-editor"
    var draftTitle: String { "Editor de conteúdo" + (controller.sourceName.isEmpty ? "" : " · " + controller.sourceName) }
    private(set) var draftRevision = UUID()
    @Published var page = 1
    @Published var selection: String?
    @Published var draft: ContentEditDraft?
    @Published var buffer = ContentEditBuffer() { didSet { if oldValue != buffer { draftRevision = UUID() } } }
    @Published var validation = ""
    @Published var loadingAsset = false
    @Published private(set) var exportedPlan: Data?
    init(controller:AdvancedDocumentController? = nil) { self.controller = controller ?? AdvancedDocumentController() }
    var hasUnsavedDraft: Bool {
        guard buffer.hasChanges else { return false }
        guard buffer.drafts.isEmpty,let plan = try? planIdentity() else { return true }
        return exportedPlan != plan
    }
    func planIdentity() throws -> Data {
        guard let content = controller.content else { throw AdvancedDocumentValidation.failure("Carregue o documento antes de exportar.") }
        return try JSONSerialization.data(withJSONObject:["source_sha256":content.source_sha256,"edits":buffer.exportOptions(in:content)],options:[.sortedKeys])
    }
    func didExport(_ identity:Data) { exportedPlan = identity; draftRevision = UUID() }
    func disposeDraft(model:Workspace) { controller.close(model:model); buffer.reset(); draft = nil }
}

enum ContentEditBufferAudit {
    static func run() throws {
        func require(_ value:Bool,_ message:String) throws {
            guard value else { throw AdvancedDocumentValidation.failure("Rascunhos do editor: "+message) }
        }
        let pages = [ContentPageDescriptor(page:1,width:600,height:800,rotation:0),ContentPageDescriptor(page:2,width:600,height:800,rotation:0)]
        func object(_ id:String,page:Int,text:String) -> ContentObjectDescriptor {
            ContentObjectDescriptor(id:id,kind:"text",page:page,rect:[20,40,240,90],text:text,font:"Helvetica",font_size:12,
                color:"#000000",editable:true,limitations:[],font_status:"original",substitution_font:nil)
        }
        let first = object("first",page:1,text:"Original é"), second = object("second",page:2,text:"Outra página")
        let content = ContentInspection(version:1,source_sha256:String(repeating:"a",count:64),page_count:2,pages:pages,objects:[first,second])
        var buffer = ContentEditBuffer(), draft = ContentEditDraft(first)
        draft.text = "Preparado inicialmente"
        buffer.update(draft,for:first); try buffer.prepare(draft,for:first,in:content)
        let initial = try buffer.exportOptions(in:content)
        try require(initial.count == 1 && initial[0]["text"] as? String == draft.text,"a primeira preparação perdeu o texto")
        draft.text = "Alterado após preparar"
        buffer.update(draft,for:first)
        var other = ContentEditDraft(second); other.text = "Página dois revisada"
        buffer.update(other,for:second)
        try require(buffer.value(for:first).text == draft.text && buffer.value(for:second).text == other.text && buffer.drafts.count == 2,
                    "alternar objeto ou página perdeu os valores visíveis")
        var refused = false
        do { _ = try buffer.exportOptions(in:content) } catch { refused = true }
        try require(refused,"exportar aceitou a versão preparada anterior aos controles")
        var invalid = other; invalid.width = -1; buffer.update(invalid,for:second)
        refused = false
        do { try buffer.prepareAll(in:content) } catch { refused = true }
        try require(refused && buffer.prepared[first.id]?.text == "Preparado inicialmente" && buffer.drafts.count == 2,
                    "um rascunho inválido alterou parcialmente o plano ou perdeu os rascunhos")
        buffer.update(other,for:second); try buffer.prepareAll(in:content)
        let exported = try buffer.exportOptions(in:content)
        try require(buffer.drafts.isEmpty && exported.count == 2 && exported[0]["text"] as? String == draft.text && exported[1]["text"] as? String == other.text,
                    "Preparar rascunhos não publicou exatamente os valores revisados")
        buffer.reset(); draft = ContentEditDraft(first); draft.text = "Original e\u{301}"
        buffer.update(draft,for:first)
        try require(buffer.hasChanges && buffer.drafts[first.id]?.text.utf8.elementsEqual(draft.text.utf8) == true,
                    "a comparação normalizou Unicode e descartou uma alteração dos bytes")
        buffer.update(ContentEditDraft(first),for:first)
        try require(!buffer.hasChanges,"voltar ao valor original não eliminou o rascunho")
        buffer.update(other,for:second); buffer.remove(second.id)
        try require(!buffer.hasChanges,"remover uma alteração não limpou seu rascunho")
    }
}
