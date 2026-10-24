import SwiftUI
import PDFKit

struct OCRCorrectionState {
    private(set) var values: [String: String] = [:]
    mutating func set(_ text: String, for word: OCRReviewWord) throws {
        try AdvancedDocumentValidation.text(text, maximum: 4096)
        if text.utf8.elementsEqual(word.text.utf8) { values.removeValue(forKey: word.id) }
        else { values[word.id] = text }
    }
    mutating func remove(_ id: String) { values.removeValue(forKey: id) }
    mutating func reset() { values = [:] }
    func payload(words: [OCRReviewWord]) throws -> [[String: Any]] {
        let known = Set(words.map(\.id))
        guard Set(values.keys).isSubset(of: known) else { throw AdvancedDocumentValidation.failure("Uma correção não pertence à análise atual.") }
        return try words.compactMap { word in
            guard let text = values[word.id] else { return nil }
            try AdvancedDocumentValidation.text(text, maximum: 4096)
            return ["id": word.id, "text": text]
        }
    }
}

struct OCRReviewView: View {
    @EnvironmentObject private var model: Workspace
    @StateObject private var controller: AdvancedDocumentController
    @State private var page = 1
    @State private var selection: String?
    @State private var language = "por+eng"
    @State private var deskew = false
    @State private var corrections = OCRCorrectionState()
    @State private var replacement = ""
    @State private var lowConfidenceOnly = false
    @State private var confidenceThreshold = 80.0
    @State private var validation = ""
    @MainActor init(controller: AdvancedDocumentController? = nil) {
        _controller = StateObject(wrappedValue: controller ?? AdvancedDocumentController())
    }
    private var allPageWords: [OCRReviewWord] { controller.review?.words.filter { $0.page == page } ?? [] }
    private var visibleWords: [OCRReviewWord] { allPageWords.filter { !lowConfidenceOnly || $0.confidence * 100 < confidenceThreshold } }
    private var selected: OCRReviewWord? { controller.review?.words.first { $0.id == selection } }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading) {
                    Text("Revisar OCR").font(.largeTitle.bold())
                    Text(controller.sourceName.isEmpty ? "Imagem original e palavras reconhecidas, lado a lado" : controller.sourceName).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Abrir PDF…") { model.open() }.disabled(controller.working || model.busy)
            }
            HStack {
                Picker("Idioma do OCR", selection: $language) {
                    Text("Português + inglês").tag("por+eng"); Text("Português").tag("por"); Text("Inglês").tag("eng"); Text("Espanhol").tag("spa")
                }.frame(maxWidth: 300).disabled(controller.working)
                Button("Reconhecer versão salva") {
                    if controller.load(model: model, ocr: true, language: language, deskew: deskew) {
                        page = 1; selection = nil; corrections.reset(); replacement = ""; validation = ""
                    }
                }.buttonStyle(.borderedProminent).disabled(model.document == nil || model.busy || controller.working)
                Spacer()
                if controller.review != nil {
                    Button("Exportar PDF pesquisável…") { export() }.disabled(controller.working || model.busy)
                }
            }
            Toggle("Compensar pequena inclinação durante o reconhecimento", isOn: $deskew)
                .disabled(controller.working)
                .help("Aplica compensação apenas com evidência suficiente de linhas inclinadas. A imagem original permanece intacta. Reconheça novamente para aplicar a opção.")
            Text("Use um PDF digitalizado sem texto selecionável. Confira cada trecho contra a imagem. A exportação mantém a página original e aplica uma camada de texto invisível; a imagem impressa não muda com as correções.")
                .font(.callout).foregroundStyle(.secondary)
            if let review = controller.review, let document = controller.preview {
                HStack {
                    Picker("Página", selection: $page) { ForEach(review.pages) { Text("\($0.page)").tag($0.page) } }.frame(width: 150)
                    Toggle("Mostrar apenas baixa confiança", isOn: $lowConfidenceOnly)
                    if lowConfidenceOnly {
                        Slider(value: $confidenceThreshold, in: 0...100, step: 5).frame(width: 110).accessibilityLabel("Limite de confiança OCR")
                        Text("< \(Int(confidenceThreshold))%").monospacedDigit()
                    }
                    Spacer()
                    Text("\(corrections.values.count) correções").foregroundStyle(.secondary)
                    Button("Descartar correções") { corrections.reset(); updateSelection() }.disabled(corrections.values.isEmpty)
                }
                HSplitView {
                    ContentPagePreview(document: document, page: review.pages[page - 1], regions: visibleWords.map {
                        ContentPreviewRegion(id: $0.id, rect: $0.rect,
                            label: "OCR: \($0.text), confiança \(Int($0.confidence * 100)) por cento",
                            changed: corrections.values[$0.id] != nil, warning: $0.confidence * 100 < confidenceThreshold)
                    }, selection: $selection).frame(minWidth: 320, minHeight: 330)
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Palavras reconhecidas").font(.headline)
                        Text("Motor: \(review.backend) · idioma: \(review.language)").font(.caption).foregroundStyle(.secondary)
                        List(visibleWords, selection: $selection) { word in
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(corrections.values[word.id] ?? word.text).lineLimit(3)
                                    if corrections.values[word.id] != nil { Text("Original: \(word.text)").font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                                }
                                Spacer()
                                Text("\(Int(word.confidence * 100))%").font(.caption.monospacedDigit()).foregroundStyle(word.confidence * 100 < confidenceThreshold ? Color.orange : Color.secondary)
                            }.tag(word.id)
                        }.frame(minHeight: 160)
                        if let selected {
                            Text("Original: \(selected.text)").font(.callout).textSelection(.enabled)
                            TextEditor(text: $replacement).frame(minHeight: 60, maxHeight: 120).border(.quaternary)
                                .accessibilityLabel("Correção do trecho OCR selecionado")
                            HStack {
                                Button("Guardar correção") { saveCorrection(selected) }.buttonStyle(.borderedProminent)
                                Button("Restaurar original") { corrections.remove(selected.id); updateSelection() }
                                    .disabled(corrections.values[selected.id] == nil)
                            }.disabled(controller.working)
                        } else { Text("Selecione uma palavra na lista ou na página para corrigir o texto.").foregroundStyle(.secondary) }
                    }.padding(12).frame(minWidth: 310, idealWidth: 380, maxWidth: 500)
                }
            } else {
                ContentUnavailableView("Imagem e texto sob revisão", systemImage: "text.viewfinder",
                    description: Text("O reconhecimento acontece neste Mac. A confiança do OCR ajuda a localizar erros; ela não substitui a conferência visual."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if !validation.isEmpty { Text(validation).foregroundStyle(.orange).textSelection(.enabled) }
            HStack {
                if controller.working { ProgressView().controlSize(.small) }
                Text(controller.status).font(.callout).textSelection(.enabled)
                Spacer()
                if controller.working { Button("Cancelar") { controller.stop(model: model) } }
                if let output = controller.output { Button("Abrir resultado") { model.open(url: output) } }
            }
        }.padding(24).onChange(of: selection) { _, _ in updateSelection() }
            .onAppear { selectFirstWord() }
            .onChange(of: controller.review?.source_sha256) { _, _ in selectFirstWord() }
            .onChange(of: page) { _, _ in selection = nil; selectFirstWord() }
            .onChange(of: lowConfidenceOnly) { _, _ in selectFirstWord() }
            .onChange(of: confidenceThreshold) { _, _ in selectFirstWord() }
            .onDisappear { controller.close(model: model) }
    }
    private func updateSelection() { replacement = selected.map { corrections.values[$0.id] ?? $0.text } ?? ""; validation = "" }
    private func selectFirstWord() {
        if !visibleWords.contains(where: { $0.id == selection }) {
            selection = visibleWords.min(by: { $0.confidence < $1.confidence })?.id
            updateSelection()
        }
    }
    private func saveCorrection(_ word: OCRReviewWord) {
        do { try corrections.set(replacement, for: word); validation = "Correção guardada para exportação." }
        catch { validation = error.localizedDescription }
    }
    private func export() {
        guard let review = controller.review else { return }
        do { controller.apply(model: model, edits: [], corrections: try corrections.payload(words: review.words)) }
        catch { validation = error.localizedDescription }
    }
}
