import Foundation
import SwiftUI

/// Raw typed text survives selection/filter/page changes. Validation is atomic
/// before export, so an invalid word never causes an older correction to ship.
struct OCRReviewBuffer {
    private(set) var corrections = OCRCorrectionState()
    private(set) var drafts: [String: String] = [:]
    var modifiedIDs: Set<String> { Set(corrections.values.keys).union(drafts.keys) }
    var hasChanges: Bool { !corrections.values.isEmpty || !drafts.isEmpty }
    func contains(_ id: String) -> Bool { corrections.values[id] != nil || drafts[id] != nil }
    func value(for word: OCRReviewWord) -> String { drafts[word.id] ?? corrections.values[word.id] ?? word.text }
    mutating func update(_ text: String, for word: OCRReviewWord) {
        let baseline = corrections.values[word.id] ?? word.text
        if text.utf8.elementsEqual(baseline.utf8) { drafts.removeValue(forKey: word.id) }
        else { drafts[word.id] = text }
    }
    mutating func prepare(_ word: OCRReviewWord) throws {
        var candidate = corrections
        try candidate.set(value(for: word), for: word)
        corrections = candidate; drafts.removeValue(forKey: word.id)
    }
    mutating func prepareAll(words: [OCRReviewWord]) throws {
        guard Set(drafts.keys).isSubset(of: Set(words.map(\.id))) else {
            throw AdvancedDocumentValidation.failure("Um rascunho OCR não pertence à revisão carregada.")
        }
        var candidate = corrections
        for word in words { if let text = drafts[word.id] { try candidate.set(text, for: word) } }
        _ = try candidate.payload(words: words)
        corrections = candidate; drafts = [:]
    }
    func payload(words: [OCRReviewWord]) throws -> [[String: Any]] {
        guard drafts.isEmpty else { throw AdvancedDocumentValidation.failure("Há texto OCR digitado ainda não validado para exportação.") }
        return try corrections.payload(words: words)
    }
    mutating func remove(_ id: String) { corrections.remove(id); drafts.removeValue(forKey: id) }
    mutating func reset() { corrections.reset(); drafts = [:] }
}

@MainActor final class OCRReviewSession: ObservableObject, ToolDraftSource {
    let draftID = "ocr-review"
    var draftTitle: String { "Revisão OCR" + (controller.sourceName.isEmpty ? "" : " · " + controller.sourceName) }
    private(set) var draftRevision = UUID()
    let controller: AdvancedDocumentController
    @Published private(set) var review: OCRReviewDocument?
    @Published var page = 1 { didSet { draftRevision = UUID() } }
    @Published var selection: String? { didSet { draftRevision = UUID() } }
    @Published var recognition: OCRRecognitionConfiguration { didSet { draftRevision = UUID() } }
    @Published var buffer = OCRReviewBuffer() { didSet { draftRevision = UUID() } }
    @Published private(set) var replacement = "" { didSet { draftRevision = UUID() } }
    @Published var lowConfidenceOnly = false { didSet { draftRevision = UUID() } }
    @Published var confidenceThreshold = 80.0 { didSet { draftRevision = UUID() } }
    @Published var validation = ""
    private var adoptedIdentity: Data?
    private var adoptedDigest: String?
    private var exportedPlan: Data?
    init(controller: AdvancedDocumentController? = nil) {
        let value = controller ?? AdvancedDocumentController()
        self.controller = value
        recognition = value.review?.recognitionConfiguration ?? OCRRecognitionConfiguration()
    }
    var selected: OCRReviewWord? { review?.words.first { $0.id == selection } }
    var visibleWords: [OCRReviewWord] {
        review?.words.filter { $0.page == page && (!lowConfidenceOnly || $0.confidence * 100 < confidenceThreshold) } ?? []
    }
    var pendingRecognitionChanges: Bool { review.map { recognition != $0.recognitionConfiguration } ?? false }
    var hasUnexportedCorrections: Bool {
        guard buffer.hasChanges else { return false }
        guard let identity = try? planIdentity() else { return true }
        return identity != exportedPlan
    }
    var hasUnsavedDraft: Bool { hasUnexportedCorrections || pendingRecognitionChanges }
    private static func identity(_ review: OCRReviewDocument) throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(review)
    }
    private func adopt(_ value: OCRReviewDocument) throws {
        try value.validate(digest: value.source_sha256)
        let identity = try Self.identity(value)
        guard identity != adoptedIdentity else { return }
        review = value; adoptedIdentity = identity; adoptedDigest = LibraryFiles.hash(identity); exportedPlan = nil
        buffer.reset(); page = 1; selection = nil; replacement = ""; validation = ""
        recognition = value.recognitionConfiguration; draftRevision = UUID()
        selectFirstWord()
    }
    func synchronizeReview() {
        guard let value = controller.review else { return }
        do { try adopt(value) } catch { validation = error.localizedDescription }
    }
    func resetForAcceptedLoad() {
        buffer.reset(); review = nil; adoptedIdentity = nil; adoptedDigest = nil; exportedPlan = nil
        page = 1; selection = nil; replacement = ""; validation = ""; draftRevision = UUID()
    }
    func retainCurrent() { if let selected { buffer.update(replacement, for: selected) } }
    func setReplacement(_ value: String) { replacement = value; retainCurrent() }
    func select(_ identity: String?) {
        retainCurrent()
        selection = identity
        replacement = selected.map { buffer.value(for: $0) } ?? ""; validation = ""
    }
    func selectFirstWord() {
        if !visibleWords.contains(where: { $0.id == selection }) {
            select(visibleWords.min(by: { $0.confidence < $1.confidence })?.id)
        }
    }
    func changePage(_ value: Int) {
        guard let review, review.pages.contains(where: { $0.page == value }) else { return }
        retainCurrent(); page = value; select(nil); selectFirstWord()
    }
    func discardAll() { buffer.reset(); replacement = selected?.text ?? ""; validation = "Correções descartadas." }
    func restoreSelected() {
        guard let selected else { return }
        buffer.remove(selected.id); replacement = selected.text; validation = "Texto original restaurado."
    }
    func prepareSelected() throws {
        guard let selected else { return }
        retainCurrent(); try buffer.prepare(selected); validation = "Correção guardada para exportação."
    }
    func prepareExport() throws -> [[String: Any]] {
        guard let review else { throw AdvancedDocumentValidation.failure("Reconheça o documento antes de exportar.") }
        retainCurrent(); try buffer.prepareAll(words: review.words)
        return try buffer.payload(words: review.words)
    }
    func planIdentity() throws -> Data {
        guard let review, let adoptedDigest else { throw AdvancedDocumentValidation.failure("A revisão OCR ainda não foi carregada.") }
        return try JSONSerialization.data(withJSONObject: ["source_sha256": review.source_sha256,
            "review_sha256": adoptedDigest, "corrections": buffer.payload(words: review.words)], options: [.sortedKeys])
    }
    func didExport(_ identity: Data) { exportedPlan = identity; draftRevision = UUID() }
    func disposeDraft(model: Workspace) {
        controller.close(model: model); buffer.reset(); review = nil; adoptedIdentity = nil; adoptedDigest = nil; exportedPlan = nil; replacement = ""
    }
    static func runAuditChecks() throws {
        func require(_ value: Bool, _ message: String) throws {
            guard value else { throw AdvancedDocumentValidation.failure("Rascunhos OCR: " + message) }
        }
        let words = [OCRReviewWord(id: "one", page: 1, rect: [20,30,80,50], text: "Original é", confidence: 0.6),
                     OCRReviewWord(id: "two", page: 2, rect: [20,30,80,50], text: "Outra página", confidence: 0.9)]
        let review = OCRReviewDocument(version: 1, source_sha256: String(repeating: "a", count: 64), page_count: 2,
            pages: [ContentPageDescriptor(page:1,width:200,height:300,rotation:0),ContentPageDescriptor(page:2,width:200,height:300,rotation:0)],
            words: words, backend: "tesseract", language: "por")
        let registry = ToolDraftRegistry()
        let session = registry.session(id: "ocr-review") { OCRReviewSession() }
        try session.adopt(review); session.select("one")
        session.setReplacement("Original e\u{301}"); session.changePage(2)
        session.setReplacement("Segunda página revista")
        let restored = registry.session(id: "ocr-review") { OCRReviewSession() }
        try require(restored === session && session.buffer.drafts.count == 2 && session.hasUnsavedDraft,
                    "navegar entre palavras, páginas ou ferramentas perdeu texto digitado")
        session.changePage(1)
        try require(session.replacement.utf8.elementsEqual("Original e\u{301}".utf8), "normalizou Unicode ao restaurar o rascunho")
        let payload = try session.prepareExport()
        try require(payload.count == 2 && (payload[0]["text"] as? String)?.utf8.elementsEqual("Original e\u{301}".utf8) == true,
                    "exportar deixou de incluir a palavra digitada ou outra página")
        let firstPlan = try session.planIdentity(); session.didExport(firstPlan)
        try require(!session.hasUnsavedDraft, "o recibo exato não reconheceu a exportação concluída")
        session.setReplacement("Mudança após exportar"); session.changePage(2); session.setReplacement("  ")
        var refused = false
        do { _ = try session.prepareExport() } catch { refused = true }
        try require(refused && session.buffer.drafts.count == 2 && session.buffer.corrections.values["one"]?.utf8.elementsEqual("Original e\u{301}".utf8) == true,
                    "uma palavra inválida publicou parcialmente o lote ou perdeu a versão anterior")
        session.didExport(firstPlan)
        try require(session.hasUnsavedDraft, "um recibo antigo apagou uma edição posterior")
        session.restoreSelected(); session.changePage(1); session.restoreSelected()
        try require(!session.buffer.hasChanges && !session.hasUnsavedDraft, "restaurar os originais deixou correções ocultas")
        session.setReplacement("Preservar no filtro")
        session.lowConfidenceOnly = true; session.confidenceThreshold = 10; session.selectFirstWord()
        try require(session.selection == nil && session.buffer.drafts["one"] == "Preservar no filtro", "filtrar uma palavra descartou seu rascunho")
    }
}
