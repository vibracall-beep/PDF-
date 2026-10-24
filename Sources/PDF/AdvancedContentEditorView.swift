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
    var allowFontSubstitution = false
    var imageURL: URL?
    var fontURL: URL?
    init(_ item: ContentObjectDescriptor) {
        text = item.text ?? ""; x = item.rect[0]; y = item.rect[1]
        width = item.rect[2] - item.rect[0]; height = item.rect[3] - item.rect[1]
        fontSize = item.font_size ?? 12
        color = item.color ?? "#000000"
        action = item.kind == "image" ? "move" : "replace"
    }
    var rect: [Double] { [x, y, x + width, y + height] }
    func options(for item: ContentObjectDescriptor, pages: [ContentPageDescriptor]) throws -> [String: Any] {
        guard item.editable, ["replace", "move", "delete"].contains(action) else { throw AdvancedDocumentValidation.failure("Este objeto não aceita a operação selecionada.") }
        var value: [String: Any] = ["id": item.id, "action": action]
        if action == "delete" { return value }
        try AdvancedDocumentValidation.rect(rect, page: item.page, pages: pages)
        value["rect"] = rect
        if item.kind == "text" {
            guard fontSize.isFinite, (4...300).contains(fontSize), ["left", "center", "right", "justify"].contains(alignment),
                  color.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil else {
                throw AdvancedDocumentValidation.failure("O tamanho da fonte ou alinhamento é inválido.")
            }
            try AdvancedDocumentValidation.text(text, maximum: 65_536)
            value["text"] = text; value["font_size"] = fontSize; value["alignment"] = alignment
            value["color"] = color
            value["allow_font_substitution"] = allowFontSubstitution
            if let fontURL { value["font_file"] = fontURL.path }
        } else if action == "replace" {
            guard let imageURL else { throw AdvancedDocumentValidation.failure("Selecione a imagem que substituirá o objeto.") }
            guard rect == item.rect else { throw AdvancedDocumentValidation.failure("A substituição de imagem mantém sua posição. Exporte a substituição antes de mover a imagem em outra revisão.") }
            value["image_path"] = imageURL.path
        }
        return value
    }
}

struct AdvancedContentEditorView: View {
    @EnvironmentObject private var model: Workspace
    @StateObject private var controller: AdvancedDocumentController
    @State private var page = 1
    @State private var selection: String?
    @State private var draft: ContentEditDraft?
    @State private var edits: [String: ContentEditDraft] = [:]
    @State private var validation = ""
    @State private var loadingAsset = false
    @MainActor init(controller: AdvancedDocumentController? = nil) {
        _controller = StateObject(wrappedValue: controller ?? AdvancedDocumentController())
    }
    private var selected: ContentObjectDescriptor? { controller.content?.objects.first { $0.id == selection } }
    private var pageObjects: [ContentObjectDescriptor] { controller.content?.objects.filter { $0.page == page } ?? [] }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading) {
                    Text("Editar conteúdo original").font(.largeTitle.bold())
                    Text(controller.sourceName.isEmpty ? "Texto e imagens do próprio PDF" : controller.sourceName).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Abrir PDF…") { model.open() }.disabled(controller.working || model.busy)
                Button("Carregar versão salva") { edits = [:]; selection = nil; draft = nil; page = 1; controller.load(model: model, ocr: false) }
                    .disabled(controller.working || model.busy || model.document == nil)
            }
            Text("A prévia mostra a origem. As alterações entram em uma nova cópia ao exportar. Objetos com sobreposição ou estrutura incompatível ficam indisponíveis com uma explicação.")
                .font(.callout).foregroundStyle(.secondary)
            if let content = controller.content, let document = controller.preview {
                HStack {
                    Picker("Página", selection: $page) { ForEach(content.pages) { Text("\($0.page)").tag($0.page) } }.frame(width: 160)
                    Text("\(edits.count) alterações preparadas").foregroundStyle(.secondary)
                    Spacer()
                    Button("Descartar alterações") { edits = [:]; select(selection) }.disabled(edits.isEmpty)
                    Button("Exportar cópia…") { export() }.buttonStyle(.borderedProminent).disabled(edits.isEmpty || controller.working || model.busy || loadingAsset)
                }
                HSplitView {
                    ContentPagePreview(document: document, page: content.pages[page - 1], regions: pageObjects.map {
                        ContentPreviewRegion(id: $0.id, rect: $0.rect,
                            label: $0.kind == "text" ? "Texto: " + String(($0.text ?? "").prefix(100)) : "Imagem da página \(page)",
                            changed: edits[$0.id] != nil, warning: !$0.editable)
                    }, selection: $selection).frame(minWidth: 320, minHeight: 320)
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Objetos da página").font(.headline)
                        List(pageObjects, selection: $selection) { item in
                            HStack(alignment: .top) {
                                Image(systemName: item.kind == "text" ? "text.alignleft" : "photo")
                                VStack(alignment: .leading) {
                                    Text(item.kind == "text" ? String((item.text ?? "Texto").prefix(90)) : "Imagem original").lineLimit(2)
                                    if !item.editable { Text("Revisão somente").font(.caption).foregroundStyle(.orange) }
                                    if edits[item.id] != nil { Text("Alteração preparada").font(.caption).foregroundStyle(.green) }
                                }
                            }.tag(item.id)
                        }.frame(minHeight: 100, idealHeight: 170, maxHeight: 220)
                        if let item = selected, let draft {
                            inspector(item, draft: Binding(get: { self.draft ?? draft }, set: { self.draft = $0 }))
                        } else {
                            ContentUnavailableView("Selecione um objeto", systemImage: "cursorarrow.click", description: Text("Clique em um retângulo na página ou em um item da lista."))
                        }
                    }.padding(12).frame(minWidth: 300, idealWidth: 370, maxWidth: 460)
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
        }.padding(24).onChange(of: selection) { _, value in select(value) }
            .onAppear { selectFirstObject() }
            .onChange(of: controller.content?.source_sha256) { _, _ in selectFirstObject() }
            .onChange(of: page) { _, _ in selection = nil; draft = nil; selectFirstObject() }
            .onDisappear { controller.close(model: model) }
    }
    @ViewBuilder private func inspector(_ item: ContentObjectDescriptor, draft: Binding<ContentEditDraft>) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(item.kind == "text" ? "Parágrafo / trecho original" : "Imagem original").font(.headline)
                ForEach(Array(item.limitations.enumerated()), id: \.offset) { _, limitation in Text(explanation(limitation)).font(.caption).foregroundStyle(.secondary) }
                Picker("Operação", selection: draft.action) {
                    Text(item.kind == "text" ? "Substituir texto" : "Substituir imagem").tag("replace")
                    Text("Mover / redimensionar").tag("move")
                    Text("Excluir objeto").tag("delete")
                }
                if draft.wrappedValue.action != "delete" {
                    if item.kind == "text" {
                        TextEditor(text: draft.text).font(.body).frame(minHeight: 100).border(.quaternary)
                            .accessibilityLabel("Texto substituto do objeto")
                        HStack {
                            TextField("Fonte (pt)", value: draft.fontSize, format: .number).frame(width: 100)
                            Picker("Alinhamento", selection: draft.alignment) {
                                Text("Esquerda").tag("left"); Text("Centro").tag("center"); Text("Direita").tag("right"); Text("Justificado").tag("justify")
                            }
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
                    } else if draft.wrappedValue.action == "replace" {
                        Button(draft.wrappedValue.imageURL?.lastPathComponent ?? "Selecionar nova imagem…") { chooseAsset(font: false) }
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
                if edits[item.id] != nil { Button("Remover alteração preparada") { edits.removeValue(forKey: item.id); select(item.id) } }
            }.disabled(!item.editable)
                .onChange(of: draft.wrappedValue.action) { _, value in
                    if item.kind == "image", value == "replace" {
                        draft.wrappedValue.x = item.rect[0]; draft.wrappedValue.y = item.rect[1]
                        draft.wrappedValue.width = item.rect[2] - item.rect[0]; draft.wrappedValue.height = item.rect[3] - item.rect[1]
                    }
                }
        }
    }
    private func select(_ id: String?) {
        validation = ""
        guard let item = controller.content?.objects.first(where: { $0.id == id }) else { draft = nil; return }
        draft = edits[item.id] ?? ContentEditDraft(item)
    }
    private func selectFirstObject() {
        guard selection == nil else { return }
        selection = pageObjects.first(where: \.editable)?.id ?? pageObjects.first?.id
        select(selection)
    }
    private func queue() {
        guard let selected, let draft, let content = controller.content else { return }
        do { _ = try draft.options(for: selected, pages: content.pages); edits[selected.id] = draft; validation = "Alteração preparada. A prévia acima ainda mostra a origem." }
        catch { validation = error.localizedDescription }
    }
    private func chooseAsset(font: Bool) {
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
            } catch { validation = error.localizedDescription }
        }
    }
    private func export() {
        guard let content = controller.content else { return }
        do {
            let values = try content.objects.compactMap { item in try edits[item.id]?.options(for: item, pages: content.pages) }
            guard values.count <= 1000 else { throw AdvancedDocumentValidation.failure("Exporte no máximo 1.000 alterações por revisão.") }
            controller.apply(model: model, edits: values)
        } catch { validation = error.localizedDescription }
    }
    private func explanation(_ code: String) -> String {
        switch code {
        case "rotated-or-skewed-text": return "Texto inclinado ou rotacionado: edição indisponível para preservar sua geometria."
        case "text-outside-visible-page", "image-outside-visible-page": return "O objeto ultrapassa a área visível da página."
        case "interactive-overlap": return "O objeto cruza um formulário, link ou anotação."
        case "pending-redaction": return "A página contém uma ocultação ainda não aplicada."
        case "nonstandard-or-invisible-text-rendering": return "Texto invisível ou com desenho especial. Use Revisar OCR para reconhecer uma digitalização."
        case "overlapping-text-runs": return "O texto se sobrepõe a outro trecho original."
        case "inline-image": return "Imagem incorporada diretamente ao desenho da página."
        case "shared-image-object": return "A mesma imagem é usada em mais de um local."
        case "rotated-skewed-or-reflected-image": return "Imagem rotacionada, inclinada ou espelhada."
        case "image-mask": return "A imagem usa uma máscara de transparência que precisa ser preservada."
        default: return "A estrutura deste objeto ainda não permite uma edição com preservação verificada."
        }
    }
}
