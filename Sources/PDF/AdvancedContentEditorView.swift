import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers

struct ContentEditDraft: Equatable {
    var action = "replace"
    var text: String
    var x: Double
    var y: Double
    var width: Double
    var height: Double
    var fontSize: Double
    var color: String
    var alignment = "left"
    var lineSpacing: Double
    var characterSpacing = 0.0
    var strokeEnabled = true
    var fillEnabled = false
    var strokeWidth = 1.0
    var fillColor = "#ffffff"
    var allowFontSubstitution = false
    var imageURL: URL?
    var fontURL: URL?
    static func == (lhs:ContentEditDraft,rhs:ContentEditDraft) -> Bool {
        func exact(_ left:String,_ right:String) -> Bool { left.utf8.elementsEqual(right.utf8) }
        func url(_ left:URL?,_ right:URL?) -> Bool {
            switch (left,right) {
            case (nil,nil): return true
            case let (.some(a),.some(b)): return exact(a.absoluteString,b.absoluteString)
            default: return false
            }
        }
        return exact(lhs.action,rhs.action) && exact(lhs.text,rhs.text) && lhs.x == rhs.x && lhs.y == rhs.y &&
            lhs.width == rhs.width && lhs.height == rhs.height && lhs.fontSize == rhs.fontSize && exact(lhs.color,rhs.color) &&
            exact(lhs.alignment,rhs.alignment) && lhs.lineSpacing == rhs.lineSpacing && lhs.characterSpacing == rhs.characterSpacing &&
            lhs.strokeEnabled == rhs.strokeEnabled && lhs.fillEnabled == rhs.fillEnabled && lhs.strokeWidth == rhs.strokeWidth &&
            exact(lhs.fillColor,rhs.fillColor) && lhs.allowFontSubstitution == rhs.allowFontSubstitution &&
            url(lhs.imageURL,rhs.imageURL) && url(lhs.fontURL,rhs.fontURL)
    }
    init(_ item: ContentObjectDescriptor) {
        text = item.text ?? ""; x = item.rect[0]; y = item.rect[1]
        width = item.rect[2] - item.rect[0]; height = item.rect[3] - item.rect[1]
        fontSize = item.font_size ?? 12
        lineSpacing = item.line_spacing ?? 1.2
        alignment = item.alignment ?? "left"
        color = item.color ?? "#000000"
        strokeEnabled = item.color != nil; fillEnabled = item.fill_color != nil
        strokeWidth = max(0.1, item.stroke_width ?? 1); fillColor = item.fill_color ?? "#ffffff"
        action = ["image", "vector"].contains(item.kind) && item.supportedActions.contains("move") ? "move" : (item.supportedActions.first ?? "replace")
    }
    var rect: [Double] { [x, y, x + width, y + height] }
    func options(for item: ContentObjectDescriptor, pages: [ContentPageDescriptor]) throws -> [String: Any] {
        guard item.editable, item.supportedActions.contains(action) else { throw AdvancedDocumentValidation.failure("Este objeto não aceita a operação selecionada.") }
        var value: [String: Any] = ["id": item.id, "action": action]
        if action == "delete" { return value }
        try AdvancedDocumentValidation.rect(rect, page: item.page, pages: pages)
        value["rect"] = rect
        if item.isText {
            guard fontSize.isFinite, (4...300).contains(fontSize), ["left", "center", "right", "justify"].contains(alignment),
                  color.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil else {
                throw AdvancedDocumentValidation.failure("O tamanho da fonte ou alinhamento é inválido.")
            }
            try AdvancedDocumentValidation.text(text, maximum: 65_536)
            value["text"] = text; value["font_size"] = fontSize; value["alignment"] = alignment
            value["color"] = color
            guard characterSpacing.isFinite, (-5...20).contains(characterSpacing) else {
                throw AdvancedDocumentValidation.failure("Use espaçamento adicional entre caracteres de −5 a 20 pontos.")
            }
            value["character_spacing"] = characterSpacing
            if item.kind == "paragraph" {
                guard lineSpacing.isFinite, (1...3).contains(lineSpacing) else { throw AdvancedDocumentValidation.failure("Use espaçamento entre linhas de 1 a 3 vezes o tamanho da fonte.") }
                value["line_spacing"] = lineSpacing
            }
            value["allow_font_substitution"] = allowFontSubstitution
            if let fontURL { value["font_file"] = fontURL.path }
        } else if item.kind == "vector", action == "replace" {
            guard strokeWidth.isFinite, (0.1...100).contains(strokeWidth), strokeEnabled || fillEnabled,
                  color.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil,
                  fillColor.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil,
                  item.vector_shape != "line" || (strokeEnabled && !fillEnabled) else {
                throw AdvancedDocumentValidation.failure("A forma precisa de traço ou preenchimento válido; linhas exigem somente traço. Use espessura de 0,1 a 100 pontos.")
            }
            value["stroke_width"] = strokeWidth
            value["stroke_color"] = strokeEnabled ? color as Any : NSNull()
            value["fill_color"] = fillEnabled ? fillColor as Any : NSNull()
        } else if item.kind == "image", action == "replace" {
            guard let imageURL else { throw AdvancedDocumentValidation.failure("Selecione a imagem que substituirá o objeto.") }
            guard rect == item.rect else { throw AdvancedDocumentValidation.failure("A substituição de imagem mantém sua posição. Exporte a substituição antes de mover a imagem em outra revisão.") }
            value["image_path"] = imageURL.path
        }
        return value
    }
}

struct AdvancedContentEditorView: View {
    @EnvironmentObject private var model: Workspace
    private let initialController:AdvancedDocumentController?
    @MainActor init(controller:AdvancedDocumentController? = nil) { initialController = controller }
    var body:some View {
        AdvancedContentEditorWorkspace(session:model.toolDrafts.session(id:"content-editor") {
            ContentEditorSession(controller:initialController)
        })
    }
}

private struct AdvancedContentEditorWorkspace: View {
    @EnvironmentObject private var model: Workspace
    @ObservedObject private var session:ContentEditorSession
    @ObservedObject private var controller:AdvancedDocumentController
    @State private var showDiscardPrompt = false
    @State private var pendingTransition: EditorTransition?
    private enum EditorTransition { case open, reload }
    @MainActor init(session:ContentEditorSession) { self.session = session; self.controller = session.controller }
    private var page:Int { get { session.page } nonmutating set { session.page = newValue } }
    private var selection:String? { get { session.selection } nonmutating set { session.selection = newValue } }
    private var draft:ContentEditDraft? { get { session.draft } nonmutating set { session.draft = newValue } }
    private var buffer:ContentEditBuffer { get { session.buffer } nonmutating set { session.buffer = newValue } }
    private var validation:String { get { session.validation } nonmutating set { session.validation = newValue } }
    private var loadingAsset:Bool { get { session.loadingAsset } nonmutating set { session.loadingAsset = newValue } }
    private var selected: ContentObjectDescriptor? { controller.content?.objects.first { $0.id == selection } }
    private var pageObjects: [ContentObjectDescriptor] { controller.content?.objects.filter { $0.page == page } ?? [] }
    private var edits:[String:ContentEditDraft] { buffer.prepared }
    private var selectionBinding:Binding<String?> { Binding(get:{ selection },set:{ select($0) }) }
    private var pageBinding:Binding<Int> { Binding(get:{ page },set:{ value in
        retainDraft(); page = value; selection = nil; draft = nil; selectFirstObject()
    }) }
    var body: some View {
        GeometryReader { geometry in
        ScrollView {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading) {
                    Text("Editar conteúdo original").font(.largeTitle.bold())
                    Text(controller.sourceName.isEmpty ? "Texto, imagens e formas isoladas do próprio PDF" : controller.sourceName).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Abrir PDF…") { requestTransition(.open) }.disabled(controller.working || model.busy || loadingAsset)
                Button("Carregar versão salva") { requestTransition(.reload) }
                    .disabled(controller.working || model.busy || loadingAsset || model.document == nil)
            }
            Text("A prévia mostra a origem. As alterações entram em uma nova cópia ao exportar. Objetos com sobreposição ou estrutura incompatível ficam indisponíveis com uma explicação.")
                .font(.callout).foregroundStyle(.secondary)
            if let content = controller.content, let document = controller.preview {
                VStack(alignment:.leading,spacing:8) {
                    HStack {
                        Picker("Página", selection: pageBinding) { ForEach(content.pages) { Text("\($0.page)").tag($0.page) } }.frame(width: 160)
                        Text("\(PortugueseCount.label(edits.count, "alteração preparada", "alterações preparadas"))").foregroundStyle(.secondary)
                        if !buffer.drafts.isEmpty { Text("\(PortugueseCount.label(buffer.drafts.count,"rascunho não preparado","rascunhos não preparados"))").foregroundStyle(.orange) }
                        Spacer()
                    }
                    HStack {
                        if !buffer.drafts.isEmpty { Button("Preparar rascunhos") { prepareDrafts() }.disabled(controller.working || model.busy || loadingAsset) }
                        Button("Descartar alterações") { buffer.reset(); draft = selected.map(ContentEditDraft.init); validation = "Alterações descartadas." }.disabled(!buffer.hasChanges || controller.working || loadingAsset)
                        Spacer()
                        Button("Exportar cópia…") { export() }.buttonStyle(.borderedProminent)
                            .disabled(edits.isEmpty || !buffer.drafts.isEmpty || controller.working || model.busy || loadingAsset)
                            .help(buffer.drafts.isEmpty ? "Exportar as alterações preparadas" : "Prepare ou descarte os rascunhos antes de exportar")
                    }
                }
                ContentReviewWorkspace(availableHeight: geometry.size.height,
                                       inspectorLabel: "Objetos da página e opções de edição") {
                    ContentPagePreview(document: document, page: content.pages[page - 1], regions: pageObjects.map {
                        ContentPreviewRegion(id: $0.id, rect: $0.rect,
                            label: $0.isText ? ($0.kind == "paragraph" ? "Parágrafo: " : "Texto: ") + String(($0.text ?? "").prefix(100)) : objectTitle($0) + " da página \(page)",
                            changed: edits[$0.id] != nil || buffer.drafts[$0.id] != nil, warning: !$0.editable)
                    }, selection: selectionBinding)
                } inspector: {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Objetos da página").font(.headline).fixedSize(horizontal: false, vertical: true)
                        List(pageObjects, selection: selectionBinding) { item in
                            HStack(alignment: .top) {
                                Image(systemName: item.kind == "paragraph" ? "paragraphsign" : item.isText ? "text.alignleft" : item.kind == "vector" ? "square.on.circle" : "photo")
                                VStack(alignment: .leading) {
                                    Text(item.isText ? String((item.text ?? "Texto").prefix(90)) : objectTitle(item)).lineLimit(2)
                                    if item.kind == "paragraph" { Text("Parágrafo · \(PortugueseCount.label(item.member_ids?.count ?? 0, "trecho", "trechos"))").font(.caption).foregroundStyle(.secondary) }
                                    if !item.editable { Text("Revisão somente").font(.caption).foregroundStyle(.orange) }
                                    if edits[item.id] != nil { Text("Alteração preparada").font(.caption).foregroundStyle(.green) }
                                    if buffer.drafts[item.id] != nil { Text("Rascunho não preparado").font(.caption).foregroundStyle(.orange) }
                                }
                            }.tag(item.id)
                        }.frame(height: 180).accessibilityLabel("Objetos da página")
                        if let item = selected, let draft {
                            inspector(item, draft: Binding(get: { self.draft ?? draft }, set: { self.draft = $0; buffer.update($0,for:item) }))
                        } else {
                            ContentUnavailableView("Selecione um objeto", systemImage: "cursorarrow.click", description: Text("Clique em um retângulo na página ou em um item da lista."))
                        }
                    }
                }
            } else {
                ContentUnavailableView("Carregue um documento", systemImage: "doc.text.magnifyingglass", description: Text("A análise identifica objetos existentes e informa quais podem ser modificados com segurança."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if !validation.isEmpty { Text(validation).foregroundStyle(.orange).textSelection(.enabled) }
            HStack {
                if controller.working || loadingAsset { ProgressView().controlSize(.small) }
                Text(controller.status).font(.callout).textSelection(.enabled)
                Spacer()
                if controller.working { Button("Cancelar") { controller.stop(model: model) } }
                if let output = controller.output { Button("Abrir resultado") { model.open(url: output) } }
            }
        }.padding(24)
        }
        }.onAppear { selectFirstObject() }
            .onChange(of: controller.content?.source_sha256) { _, _ in selectFirstObject() }
            .confirmationDialog("Descartar as alterações desta revisão?",isPresented:$showDiscardPrompt,titleVisibility:.visible) {
                Button("Descartar e continuar",role:.destructive) { if let pendingTransition { performTransition(pendingTransition) }; pendingTransition = nil }
                Button("Continuar editando",role:.cancel) { pendingTransition = nil }
            } message: { Text("Esta revisão contém alterações preparadas ou rascunhos. Exporte uma cópia para preservá-los antes de carregar outro documento.") }
    }
    @ViewBuilder private func inspector(_ item: ContentObjectDescriptor, draft: Binding<ContentEditDraft>) -> some View {
            VStack(alignment: .leading, spacing: 12) {
                Text(item.kind == "paragraph" ? "Parágrafo original" : item.isText ? "Trecho original" : objectTitle(item)).font(.headline)
                ForEach(Array(item.limitations.enumerated()), id: \.offset) { _, limitation in Text(explanation(limitation)).font(.caption).foregroundStyle(.secondary) }
                Picker("Operação", selection: draft.action) {
                    if item.supportedActions.contains("replace") { Text(item.isText ? "Substituir texto" : item.kind == "vector" ? "Alterar estilo da forma" : "Substituir imagem").tag("replace") }
                    if item.supportedActions.contains("move") { Text("Mover / redimensionar").tag("move") }
                    if item.supportedActions.contains("delete") { Text("Excluir objeto").tag("delete") }
                }
                if item.kind == "image", !item.supportedActions.contains("move") {
                    Text(item.supportedActions == ["replace"] ? "A estrutura acessível exige manter o objeto nesta posição. Substitua a imagem na mesma área e revise seu texto alternativo." : "Esta imagem usa recorte, composição ou estado gráfico da página. A substituição preserva sua área; mover poderia alterar o resultado.").font(.caption).foregroundStyle(.secondary)
                }
                if draft.wrappedValue.action != "delete" {
                    if item.isText {
                        TextEditor(text: draft.text).font(.body).frame(height: 120).border(.quaternary)
                            .accessibilityLabel("Texto substituto do objeto")
                        LabeledContent("Tamanho da fonte (pt)") {
                            TextField("Pontos", value: draft.fontSize, format: .number).frame(width: 100)
                                .accessibilityLabel("Tamanho da fonte em pontos")
                        }
                        Picker("Alinhamento", selection: draft.alignment) {
                            Text("Esquerda").tag("left"); Text("Centro").tag("center"); Text("Direita").tag("right"); Text("Justificado").tag("justify")
                        }
                        LabeledContent("Espaçamento adicional (pt)") {
                            TextField("Entre caracteres", value: draft.characterSpacing, format: .number).frame(width: 100)
                                .accessibilityLabel("Espaçamento adicional entre caracteres em pontos, de menos 5 a 20")
                        }
                        if draft.wrappedValue.characterSpacing != 0 {
                            Text("A exportação verifica os caracteres e seus limites. Espaçamento adicional exige fonte disponível e texto sem composição complexa; use esquerda, centro ou direita se houver quebra automática.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        if item.kind == "paragraph" {
                            HStack {
                                Text("Espaçamento entre linhas")
                                TextField("Multiplicador", value: draft.lineSpacing, format: .number).frame(width: 70)
                                    .accessibilityLabel("Espaçamento do parágrafo, de 1 a 3")
                            }
                            Text("O grupo reúne trechos originais compatíveis. Use de 1 a 3 vezes o tamanho da fonte; a cópia só será exportada se o novo texto couber na área escolhida.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Text("Fonte original: \(item.font ?? "não identificada")").font(.caption)
                        ColorPicker("Cor do texto", selection: Binding(get: {
                            Color(nsColor: ReaderAnnotationStyle.color(draft.wrappedValue.color, fallback: "#000000"))
                        }, set: { color in
                            guard let rgb = NSColor(color).usingColorSpace(.sRGB) else { return }
                            func byte(_ value: CGFloat) -> Int { Int((min(1, max(0, value)) * 255).rounded()) }
                            draft.wrappedValue.color = String(format: "#%02X%02X%02X", byte(rgb.redComponent), byte(rgb.greenComponent), byte(rgb.blueComponent))
                        }), supportsOpacity: false)
                        if item.font_status != "original" {
                            Text("A fonte original pode não estar disponível para reescrita. Substituição sugerida: \(item.substitution_font ?? "fonte local compatível"). A aparência e as quebras podem mudar.")
                                .font(.caption).foregroundStyle(.orange)
                        }
                        Toggle("Autorizar substituição de fonte", isOn: draft.allowFontSubstitution)
                        Button(draft.wrappedValue.fontURL?.lastPathComponent ?? "Selecionar fonte TTF / OTF…") { chooseAsset(font: true) }
                            .disabled(loadingAsset || controller.working)
                    } else if item.kind == "vector" {
                        Text("Linhas e retângulos isolados. Mover conserva o estilo original; a exportação recusa sobreposição com outros objetos.").font(.caption).foregroundStyle(.secondary)
                        if draft.wrappedValue.action == "replace" {
                            Toggle("Traço", isOn: draft.strokeEnabled).disabled(item.vector_shape == "line")
                            if draft.wrappedValue.strokeEnabled {
                                vectorColor("Cor do traço", value: draft.color)
                                LabeledContent("Espessura (pt)") {
                                    TextField("Espessura do traço", value: draft.strokeWidth, format: .number).frame(width: 100)
                                        .accessibilityLabel("Espessura do traço vetorial em pontos")
                                }
                            }
                            if item.vector_shape == "rectangle" {
                                Toggle("Preenchimento", isOn: draft.fillEnabled)
                                if draft.wrappedValue.fillEnabled { vectorColor("Cor do preenchimento", value: draft.fillColor) }
                            }
                        }
                    } else if draft.wrappedValue.action == "replace" {
                        Button(draft.wrappedValue.imageURL?.lastPathComponent ?? "Selecionar nova imagem…") { chooseAsset(font: false) }
                            .disabled(loadingAsset || controller.working)
                    }
                    if item.kind == "image", draft.wrappedValue.action == "replace" {
                        Text("A substituição mantém a posição e a ordem da imagem na página. Para reposicioná-la, use Mover em uma revisão separada.").font(.caption).foregroundStyle(.secondary)
                    }
                    Text("Posição na página sem rotação, em pontos").font(.caption).foregroundStyle(.secondary)
                    Grid(alignment: .leading) {
                        GridRow { Text("X"); TextField("X", value: draft.x, format: .number); Text("Y"); TextField("Y", value: draft.y, format: .number) }
                        GridRow { Text("Largura"); TextField("Largura", value: draft.width, format: .number); Text("Altura"); TextField("Altura", value: draft.height, format: .number) }
                    }.disabled(item.kind == "image" && draft.wrappedValue.action == "replace")
                } else { Text("O objeto selecionado será removido da cópia exportada.").foregroundStyle(.orange) }
                Button("Preparar alteração") { queue() }.buttonStyle(.borderedProminent).disabled(!item.editable || controller.working || loadingAsset)
                if edits[item.id] != nil || buffer.drafts[item.id] != nil {
                    Button("Descartar alteração deste objeto") { buffer.remove(item.id); self.draft = ContentEditDraft(item) }
                }
            }.disabled(!item.editable)
                .onChange(of: draft.wrappedValue.action) { _, value in
                    if item.kind == "image", value == "replace" {
                        draft.wrappedValue.x = item.rect[0]; draft.wrappedValue.y = item.rect[1]
                        draft.wrappedValue.width = item.rect[2] - item.rect[0]; draft.wrappedValue.height = item.rect[3] - item.rect[1]
                    }
                }
    }
    private func objectTitle(_ item: ContentObjectDescriptor) -> String {
        item.kind == "vector" ? (item.vector_shape == "line" ? "Linha vetorial" : "Retângulo vetorial") : "Imagem original"
    }
    private func vectorColor(_ label: String, value: Binding<String>) -> some View {
        ColorPicker(label, selection: Binding(get: {
            Color(nsColor: ReaderAnnotationStyle.color(value.wrappedValue, fallback: "#000000"))
        }, set: { color in
            guard let rgb = NSColor(color).usingColorSpace(.sRGB) else { return }
            func byte(_ component: CGFloat) -> Int { Int((min(1, max(0, component)) * 255).rounded()) }
            value.wrappedValue = String(format: "#%02X%02X%02X", byte(rgb.redComponent), byte(rgb.greenComponent), byte(rgb.blueComponent))
        }), supportsOpacity: false)
    }
    private func select(_ id: String?) {
        retainDraft()
        selection = id
        validation = ""
        guard let item = controller.content?.objects.first(where: { $0.id == id }) else { draft = nil; return }
        draft = buffer.value(for:item)
    }
    private func selectFirstObject() {
        guard selection == nil else { return }
        select(pageObjects.first(where: { $0.editable && $0.kind == "paragraph" })?.id ?? pageObjects.first(where: \.editable)?.id ?? pageObjects.first?.id)
    }
    private func queue() {
        guard let selected, let draft, let content = controller.content else { return }
        do {
            try buffer.prepare(draft,for:selected,in:content)
            validation = "Alteração preparada. A prévia acima ainda mostra a origem."
        }
        catch { validation = error.localizedDescription }
    }
    private func chooseAsset(font: Bool) {
        guard !loadingAsset, !controller.working else { return }
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = false
        panel.allowedContentTypes = font ? [UTType(filenameExtension: "ttf"), UTType(filenameExtension: "otf")].compactMap { $0 } : [.image]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        loadingAsset = true
        let selectedID = selection
        Task { @MainActor in
            defer { loadingAsset = false }
            do {
                let staged = try await controller.stageAsset(url, maximumBytes: font ? 33_554_432 : 67_108_864)
                guard selection == selectedID else { return }
                if font { draft?.fontURL = staged } else { draft?.imageURL = staged }
                retainDraft()
            } catch { validation = error.localizedDescription }
        }
    }
    private func export() {
        guard let content = controller.content else { return }
        do {
            retainDraft()
            let values = try buffer.exportOptions(in:content)
            guard values.count <= 1000 else { throw AdvancedDocumentValidation.failure("Exporte no máximo 1.000 alterações por revisão.") }
            let identity = try session.planIdentity()
            controller.apply(model: model, edits: values, completion:{ result in
                if case .success = result { session.didExport(identity) }
            })
        } catch { validation = error.localizedDescription }
    }
    private func retainDraft() {
        guard let selected, let draft else { return }
        buffer.update(draft,for:selected)
    }
    private func prepareDrafts() {
        guard let content = controller.content else { return }
        retainDraft()
        do { try buffer.prepareAll(in:content); validation = "Rascunhos preparados. Confira a revisão antes de exportar." }
        catch { validation = error.localizedDescription }
    }
    private func requestTransition(_ action:EditorTransition) {
        retainDraft()
        // Opening another reader document preserves this workspace's private
        // review. Only explicitly replacing the inspected revision discards it.
        if case .reload = action, session.hasUnsavedDraft {
            pendingTransition = action; showDiscardPrompt = true
        } else { performTransition(action) }
    }
    private func performTransition(_ action:EditorTransition) {
        switch action {
        case .open: model.open()
        case .reload:
            if controller.load(model:model,ocr:false) { buffer.reset(); selection = nil; draft = nil; page = 1 }
        }
    }
    private func explanation(_ code: String) -> String {
        switch code {
        case "rotated-or-skewed-text": return "Texto inclinado ou rotacionado: edição indisponível para preservar sua geometria."
        case "text-outside-visible-page", "image-outside-visible-page", "vector-outside-visible-page": return "O objeto ultrapassa a área visível da página."
        case "interactive-overlap": return "O objeto cruza um formulário, link ou anotação."
        case "pending-redaction": return "A página contém uma ocultação ainda não aplicada."
        case "nonstandard-or-invisible-text-rendering": return "Texto invisível ou com desenho especial. Use Revisar OCR para reconhecer uma digitalização."
        case "overlapping-text-runs": return "O texto se sobrepõe a outro trecho original."
        case "inline-image": return "Imagem incorporada diretamente ao desenho da página."
        case "shared-image-object": return "A mesma imagem é usada em mais de um local."
        case "rotated-skewed-or-reflected-image": return "Imagem rotacionada, inclinada ou espelhada."
        case "image-mask": return "A imagem usa uma máscara de transparência ou de pintura que precisa ser preservada."
        case "clipped-page-content": return "O objeto usa um recorte da página que precisa ser preservado."
        case "nonstandard-transparency-group": return "A página usa composição de transparência incompatível com esta reescrita."
        case "unmapped-text-paint-order": return "A ordem de desenho deste texto não pôde ser confirmada."
        case "later-object-overlap": return "Outro objeto cobre parte deste texto; reescrevê-lo alteraria a ordem visual."
        case "paragraph-object-overlap": return "Outro objeto ocupa a área entre as linhas; este trecho não pode ser reescrito como um único parágrafo."
        case "vector-object-overlap": return "A forma cruza outro conteúdo; alterar sua ordem poderia esconder ou revelar elementos."
        case "unsupported-vector-stroke": return "O traço original exige um estilo ainda não disponível neste editor."
        case "nonstandard-vector-opacity": return "A forma usa transparência que precisa ser preservada."
        case "optional-content-vector": return "A forma pertence a uma camada opcional do PDF."
        case "unmapped-vector-paint-order": return "A ordem de desenho da forma não pôde ser confirmada."
        case "vector-inspection-complexity": return "A quantidade de sobreposições excede o limite de verificação desta forma."
        case "vector-graphics-state-unproven", "content-graphics-state-unproven": return "A origem usa cor, perfil, sobreimpressão ou estado gráfico que este editor ainda não preserva."
        default: return "A estrutura deste objeto ainda não permite uma edição com preservação verificada."
        }
    }
}
