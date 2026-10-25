import SwiftUI
import PDFKit
import AppKit

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
    private let initialController: AdvancedDocumentController?
    @MainActor init(controller: AdvancedDocumentController? = nil) { initialController = controller }
    var body: some View {
        OCRReviewWorkspace(session: model.toolDrafts.session(id: "ocr-review") { OCRReviewSession(controller: initialController) })
            .environmentObject(model)
    }
}

private struct OCRReviewWorkspace: View {
    @EnvironmentObject private var model: Workspace
    @ObservedObject private var session: OCRReviewSession
    @ObservedObject private var controller: AdvancedDocumentController
    @MainActor init(session: OCRReviewSession) { self.session = session; self.controller = session.controller }
    private var page: Int { session.page }
    private var recognition: OCRRecognitionConfiguration { session.recognition }
    private var buffer: OCRReviewBuffer { session.buffer }
    private var lowConfidenceOnly: Bool { session.lowConfidenceOnly }
    private var confidenceThreshold: Double { session.confidenceThreshold }
    private var validation: String { get { session.validation } nonmutating set { session.validation = newValue } }
    private var visibleWords: [OCRReviewWord] { session.visibleWords }
    private var selected: OCRReviewWord? { session.selected }
    private var pendingRecognitionChanges: Bool { session.pendingRecognitionChanges }
    private var selectionBinding: Binding<String?> { Binding(get: { session.selection }, set: { session.select($0) }) }
    private var pageBinding: Binding<Int> { Binding(get: { page }, set: { session.changePage($0) }) }
    private var replacementBinding: Binding<String> { Binding(get: { session.replacement }, set: { session.setReplacement($0) }) }
    private var filterBinding: Binding<Bool> { Binding(get: { lowConfidenceOnly }, set: {
        session.retainCurrent(); session.lowConfidenceOnly = $0; session.selectFirstWord()
    }) }
    private var confidenceBinding: Binding<Double> { Binding(get: { confidenceThreshold }, set: {
        session.retainCurrent(); session.confidenceThreshold = $0; session.selectFirstWord()
    }) }
    private func recognize() {
        if session.hasUnexportedCorrections {
            let alert = NSAlert()
            alert.messageText = "Reconhecer novamente e descartar esta revisão?"
            alert.informativeText = "Há correções OCR ainda não exportadas. Você pode manter a revisão para exportar primeiro ou substituí-la por um novo reconhecimento."
            alert.alertStyle = .warning
            alert.addButton(withTitle: "Manter revisão")
            alert.addButton(withTitle: "Reconhecer novamente")
            guard alert.runModal() == .alertSecondButtonReturn else { return }
        }
        if controller.load(model: model, ocr: true, language: recognition.language,
                           deskew: recognition.deskew, segmentation: recognition.segmentation) {
            session.resetForAcceptedLoad()
        }
    }
    var body: some View {
        GeometryReader { geometry in
        ScrollView {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading) {
                    Text("Revisar OCR").font(.largeTitle.bold())
                    Text(controller.sourceName.isEmpty ? "Imagem original e palavras reconhecidas, lado a lado" : controller.sourceName).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Abrir PDF…") { model.open() }.disabled(controller.working || model.busy)
                    .help("Abre o documento no leitor. Use Reconhecer versão salva para iniciar uma nova revisão OCR.")
            }
            Text(controller.review == nil ? "Opções de reconhecimento" : "Opções para reconhecer novamente").font(.headline)
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 20) { languagePicker; layoutPicker }
                VStack(alignment: .leading, spacing: 10) { languagePicker; layoutPicker }
            }.disabled(controller.working)
            HStack {
                Button("Reconhecer versão salva") { recognize() }
                    .buttonStyle(.borderedProminent).disabled(model.document == nil || model.busy || controller.working)
                Spacer()
                if session.review != nil {
                    Button("Exportar PDF pesquisável…") { export() }.disabled(controller.working || model.busy)
                }
            }
            Toggle("Compensar pequena inclinação durante o reconhecimento", isOn: $session.recognition.deskew)
                .disabled(controller.working)
                .help("Compensa até 7° quando há evidência suficiente em uma grade ou em várias linhas de texto. Páginas ambíguas permanecem sem rotação. A imagem original fica intacta; reconheça novamente para aplicar a opção.")
            if pendingRecognitionChanges {
                Text("Opções alteradas. Reconheça novamente para aplicá-las; a lista e a exportação ainda usam a análise anterior.")
                    .font(.callout).foregroundStyle(.orange)
            }
            Text("Use um PDF digitalizado sem texto selecionável. Confira cada trecho contra a imagem. A exportação mantém a página original e aplica uma camada de texto invisível; a imagem impressa não muda com as correções.")
                .font(.callout).foregroundStyle(.secondary)
            if let review = session.review, let document = controller.preview {
                ContentReviewActions {
                    Picker("Página", selection: pageBinding) { ForEach(review.pages) { Text("\($0.page)").tag($0.page) } }.frame(width: 150)
                    Toggle("Mostrar apenas baixa confiança", isOn: filterBinding)
                    if lowConfidenceOnly {
                        HStack {
                            Slider(value: confidenceBinding, in: 0...100, step: 5).frame(width: 110).accessibilityLabel("Limite de confiança OCR")
                            Text("< \(Int(confidenceThreshold))%").monospacedDigit()
                        }
                    }
                    ContentReviewActions {
                        Text("\(PortugueseCount.label(buffer.modifiedIDs.count, "correção", "correções"))").foregroundStyle(.secondary)
                        Button("Descartar correções") { session.discardAll() }.disabled(!buffer.hasChanges || controller.working)
                    }
                }
                ContentReviewWorkspace(availableHeight: geometry.size.height,
                                       inspectorLabel: "Palavras reconhecidas e correções OCR") {
                    ContentPagePreview(document: document, page: review.pages[page - 1], regions: visibleWords.map {
                        ContentPreviewRegion(id: $0.id, rect: $0.rect,
                            label: "OCR: \($0.text), confiança \(Int($0.confidence * 100)) por cento",
                            changed: buffer.contains($0.id), warning: $0.confidence * 100 < confidenceThreshold)
                    }, selection: selectionBinding)
                } inspector: {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Palavras reconhecidas").font(.headline).fixedSize(horizontal: false, vertical: true)
                        Text("Análise: \(review.recognitionConfiguration.languageTitle) · \(review.recognitionConfiguration.layoutTitle)")
                            .font(.caption).foregroundStyle(.secondary)
                        Text("Motor: \(review.backend)" + (review.recognitionConfiguration.deskew ? " · compensação de inclinação solicitada" : ""))
                            .font(.caption).foregroundStyle(.secondary)
                        List(visibleWords, selection: selectionBinding) { word in
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(buffer.value(for: word)).lineLimit(3)
                                    if buffer.contains(word.id) { Text("Original: \(word.text)").font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                                }
                                Spacer()
                                Text("\(Int(word.confidence * 100))%").font(.caption.monospacedDigit()).foregroundStyle(word.confidence * 100 < confidenceThreshold ? Color.orange : Color.secondary)
                            }.tag(word.id)
                        }.frame(height: 180).accessibilityLabel("Palavras reconhecidas da página")
                        if let selected {
                            Text("Original: \(selected.text)").font(.callout).textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                            TextEditor(text: replacementBinding).frame(height: 120).border(.quaternary).disabled(controller.working)
                                .accessibilityLabel("Correção do trecho OCR selecionado")
                            ContentReviewActions {
                                Button("Guardar correção") { saveCorrection() }.buttonStyle(.borderedProminent)
                                Button("Restaurar original") { session.restoreSelected() }
                                    .disabled(!buffer.contains(selected.id))
                            }.disabled(controller.working)
                        } else { Text("Selecione uma palavra na lista ou na página para corrigir o texto.").foregroundStyle(.secondary) }
                    }
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
        }.padding(24)
        }
        }.onAppear { session.synchronizeReview() }
            .onChange(of: controller.review?.review_sha256 ?? controller.review?.source_sha256) { _, _ in session.synchronizeReview() }
    }
    private var languagePicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Idioma do OCR").font(.callout)
            Picker("Idioma do OCR", selection: $session.recognition.language) {
                Text("Português + inglês").tag("por+eng"); Text("Português").tag("por")
                Text("Inglês").tag("eng"); Text("Espanhol").tag("spa")
                if !["por+eng", "por", "eng", "spa"].contains(recognition.language) {
                    Text(recognition.languageTitle).tag(recognition.language)
                }
            }.labelsHidden().accessibilityLabel("Idioma do OCR")
        }.frame(minWidth: 225, maxWidth: 310, alignment: .leading)
    }
    private var layoutPicker: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Organização do texto").font(.callout)
            Picker("Organização do texto", selection: $session.recognition.segmentation) {
                Text("Página automática").tag(3)
                Text("Bloco de texto uniforme").tag(6)
                Text("Texto esparso").tag(11)
                if ![3, 6, 11].contains(recognition.segmentation) {
                    Text(recognition.layoutTitle).tag(recognition.segmentation)
                }
            }.labelsHidden().accessibilityLabel("Organização do texto")
                .help("Página automática separa títulos, colunas e corpo. Bloco uniforme trata a página como um único bloco. Texto esparso procura trechos separados; confira a ordem de leitura.")
        }.frame(minWidth: 240, maxWidth: 330, alignment: .leading)
    }
    private func saveCorrection() {
        do { try session.prepareSelected() }
        catch { validation = error.localizedDescription }
    }
    private func export() {
        do {
            let corrections = try session.prepareExport()
            let identity = try session.planIdentity()
            controller.apply(model: model, edits: [], corrections: corrections, completion: { result in
                if case .success = result { session.didExport(identity) }
            })
        }
        catch { validation = error.localizedDescription }
    }
}
