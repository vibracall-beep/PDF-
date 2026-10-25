import SwiftUI
import AppKit
import UniformTypeIdentifiers

private struct AccessibilityTreeReport: Decodable {
    let schema_version: Int
    let input_sha256: String
    let pages: Int
    let language: String
    let has_structure_tree: Bool
    let nodes: [AccessibilityTag]
}
private struct AccessibilityTag: Decodable, Identifiable {
    let id: String
    let parent: String?
    let role: String
    let page: Int?
    let alt: String
    let actual_text: String
    let title: String
    let language: String
    let scope: String?
    let present_fields: [String]?
    let children: [String]
    let depth: Int

    var textValues: [String: String] {
        ["alt": alt, "actual_text": actual_text, "title": title, "language": language, "scope": scope ?? ""]
    }
    var presentFields: Set<String> {
        // Reports from an older engine cannot distinguish absent from empty.
        Set(present_fields ?? textValues.filter { !$0.value.isEmpty }.map(\.key))
    }
}

/// Programmatic opening uses the same engine inspection and selection as the
/// buttons. It carries no report or editable values that could bypass inspection.
struct AccessibilityInspectionRequest {
    let sourceURL: URL
    let selectedRole: String
    let completion: (Result<AccessibilityInspectedSelection, Error>) -> Void
}

struct AccessibilityInspectedSelection: Sendable {
    let sourceSHA256: String
    let tagID: String
    let role: String
    let values: [String: String]
}

/// The UI stages only an explicit contiguous group; the engine revalidates the
/// actual structure and page/content bindings against the inspected SHA-256.
enum AccessibilityGroupingEdits {
    static let roles = ["Sect", "Part", "Div", "L", "LI", "LBody", "Table", "TR", "THead", "TBody", "TFoot", "Quote", "BlockQuote"]
    static func stage(selected: Set<String>, siblings: [String], role: String, title: String) throws -> [String: Any] {
        guard !selected.isEmpty, selected.count <= 10000, selected.isSubset(of: Set(siblings)),
              let first = siblings.firstIndex(where: { selected.contains($0) }),
              first + selected.count <= siblings.count,
              Set(siblings[first..<(first + selected.count)]) == selected,
              roles.contains(role), title.count <= 16384, !title.contains("\0") else {
            throw NSError(domain: "PDF.AccessibilityGrouping", code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Marque tags irmãs contíguas e escolha um papel de grupo. Reordene os irmãos antes de agrupar."])
        }
        var result: [String: Any] = ["children": Array(siblings[first..<(first + selected.count)]), "role": role]
        if !title.isEmpty { result["title"] = title }
        return result
    }
    static func runAuditChecks() throws {
        let group = try stage(selected: ["2:0", "3:0"], siblings: ["1:0", "2:0", "3:0", "4:0"], role: "TR", title: "Linha revisada")
        guard group["children"] as? [String] == ["2:0", "3:0"], group["role"] as? String == "TR" else {
            throw NSError(domain: "PDF.AccessibilityGrouping", code: 2)
        }
        let rejected: [Set<String>] = [[], ["1:0", "3:0"], ["9:0"]]
        for selection in rejected {
            do {
                _ = try stage(selected: selection, siblings: ["1:0", "2:0", "3:0"], role: "Sect", title: "")
            } catch { continue }
            throw NSError(domain: "PDF.AccessibilityGrouping", code: 3,
                userInfo: [NSLocalizedDescriptionKey: "O agrupamento aceitou tags desconhecidas ou não contíguas."])
        }
    }
}

/// The edit protocol distinguishes omission (preserve), null (remove), and text.
/// Keep this independent from SwiftUI state so the actual JSON contract is audited.
enum AccessibilityTagEdits {
    static func stage(id: String, originalRole: String, role: String,
                      original: [String: String], values: [String: String],
                      present: Set<String>, existing: [String: Any]) -> [String: Any] {
        var edit = existing
        edit["id"] = id
        if role.utf8.elementsEqual(originalRole.utf8) { edit.removeValue(forKey: "role") }
        else { edit["role"] = role }
        for key in ["alt", "actual_text", "title", "language", "scope"] {
            let value = values[key] ?? "", baseline = original[key] ?? ""
            if key == "scope", role != "TH" {
                if present.contains(key) { edit[key] = NSNull() }
                else { edit.removeValue(forKey: key) }
            } else if value.utf8.elementsEqual(baseline.utf8) {
                // An explicitly removed, originally empty attribute must stay
                // removed when the same tag is revisited and saved again.
                if !(value.isEmpty && present.contains(key) && edit[key] is NSNull) {
                    edit.removeValue(forKey: key)
                }
            } else if value.isEmpty {
                if present.contains(key) { edit[key] = NSNull() }
                else { edit.removeValue(forKey: key) }
            } else { edit[key] = value }
        }
        return edit
    }

    static func value(_ key: String, original: String, edit: [String: Any]) -> String {
        edit[key] is NSNull ? "" : edit[key] as? String ?? original
    }

    static func runAuditChecks() throws {
        func require(_ condition: Bool) throws {
            guard condition else { throw NSError(domain: "PDF.AccessibilityEditAudit", code: 1,
                userInfo: [NSLocalizedDescriptionKey: "O contrato de alterações das tags não preservou os atributos opcionais."]) }
        }
        func encoded(_ edit: [String: Any]) throws -> [String: Any] {
            let data = try JSONSerialization.data(withJSONObject: edit)
            return try JSONSerialization.jsonObject(with: data) as! [String: Any]
        }
        let blank = ["alt": "", "actual_text": "", "title": "", "language": "", "scope": ""]
        let roleOnly = try encoded(stage(id: "1:0", originalRole: "P", role: "H2", original: blank,
            values: blank, present: [], existing: ["children": ["2:0", "3:0"]]))
        try require(Set(roleOnly.keys) == ["id", "role", "children"])
        try require(roleOnly["children"] as? [String] == ["2:0", "3:0"])
        let existingEmpty = stage(id: "1:0", originalRole: "P", role: "H2", original: blank,
            values: blank, present: ["actual_text"], existing: [:])
        try require(existingEmpty["actual_text"] == nil)
        let removed = try encoded(stage(id: "1:0", originalRole: "P", role: "H2", original: blank,
            values: blank, present: ["actual_text"], existing: ["actual_text": NSNull()]))
        try require(removed["actual_text"] is NSNull)
        try require(value("actual_text", original: "Original replacement", edit: removed).isEmpty)
        var original = blank; original["actual_text"] = "Existing replacement"; original["scope"] = "Column"
        var values = original; values["actual_text"] = ""
        let cleared = try encoded(stage(id: "1:0", originalRole: "TH", role: "TD", original: original,
            values: values, present: ["actual_text", "scope"], existing: [:]))
        try require(cleared["scope"] is NSNull && cleared["actual_text"] is NSNull)
        original["title"] = "é"; values = original; values["title"] = "e\u{301}"
        let unicode = try encoded(stage(id: "1:0", originalRole: "TH", role: "TH", original: original,
            values: values, present: ["title", "actual_text", "scope"], existing: [:]))
        try require((unicode["title"] as? String)?.utf8.elementsEqual("e\u{301}".utf8) == true)
        try require(unicode["actual_text"] == nil && unicode["scope"] == nil)
        let restored = stage(id: "1:0", originalRole: "TH", role: "TH", original: original,
            values: original, present: ["title", "actual_text", "scope"], existing: cleared)
        try require(Set(restored.keys) == ["id"])
        try AccessibilityGroupingEdits.runAuditChecks()
    }
}

struct AccessibilityRemediationView: View {
    @EnvironmentObject private var model: Workspace
    private let initialInspection: AccessibilityInspectionRequest?
    @State private var beganInitialInspection = false
    @State private var source: URL?
    @State private var report: AccessibilityTreeReport?
    @State private var selection: String?
    @State private var role = "P"
    @State private var alt = ""
    @State private var actualText = ""
    @State private var tagTitle = ""
    @State private var tagLanguage = ""
    @State private var scope = ""
    @State private var language = "pt-BR"
    @State private var edits: [String: [String: Any]] = [:]
    @State private var groupSelection = Set<String>()
    @State private var groupRole = "Sect"
    @State private var groupTitle = ""
    @State private var groups: [[String: Any]] = []
    @State private var pageRoles: [String] = []
    @State private var pageAlternatives: [String] = []
    @State private var reviewedPages = false
    @State private var result: URL?
    @State private var error = ""
    @State private var showValidation = false
    private let roles = ["Document", "Part", "Sect", "Div", "P", "H", "H1", "H2", "H3", "H4", "H5", "H6", "L", "LI", "Lbl", "LBody", "Table", "TR", "TH", "TD", "THead", "TBody", "TFoot", "Figure", "Formula", "Caption", "Note", "Link", "Span", "Quote", "BlockQuote"]

    init(initialInspection: AccessibilityInspectionRequest? = nil) {
        self.initialInspection = initialInspection
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Label("Estrutura e acessibilidade", systemImage: "figure.roll").font(.title2.bold())
                Spacer()
                Button("Escolher PDF…") { choose() }.disabled(model.busy)
                Button("Inspecionar tags") { inspect() }.disabled(source == nil || model.busy)
            }
            Text(source?.lastPathComponent ?? "Escolha uma cópia salva para revisar.").foregroundStyle(.secondary)
            Text("Defina o significado e a ordem de leitura. A edição preserva vínculos com o conteúdo; tags sozinhas não certificam PDF/UA.")
                .font(.callout).foregroundStyle(.secondary)
            if let report {
                LabeledContent("Idioma do documento (BCP 47)") {
                    TextField("pt-BR", text: $language).textFieldStyle(.roundedBorder).accessibilityLabel("Idioma do documento (BCP 47)")
                }
                if report.has_structure_tree { taggedEditor(report) }
                else { pageEditor(report) }
                HStack {
                    Text("\(PortugueseCount.label(edits.count, "tag", "tags")) com alterações guardadas").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Salvar cópia com correções…") { save() }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.busy || (!report.has_structure_tree && !reviewedPages))
                }
            } else { ContentUnavailableView("Inspecione a estrutura", systemImage: "list.bullet.indent", description: Text("Você poderá editar títulos, textos alternativos, cabeçalhos de tabelas e a ordem de tags irmãs.")) }
            if let result {
                HStack {
                    Label(result.lastPathComponent, systemImage: "doc.badge.checkmark")
                    Button("Validar PDF/UA…") { showValidation = true }
                    Button("Mostrar cópia") { NSWorkspace.shared.activateFileViewerSelecting([result]) }
                    Button("Continuar nesta cópia") { source = result; inspect() }.disabled(model.busy)
                }
            }
            if model.busy { HStack { ProgressView().controlSize(.small); Text(model.message); Button("Cancelar") { model.cancel() } } }
            if !error.isEmpty { Text(error).foregroundStyle(.red).textSelection(.enabled) }
        }.padding(24).frame(minWidth: 760, minHeight: 580)
            .onAppear {
                if let initialInspection, !beganInitialInspection {
                    beganInitialInspection = true
                    source = initialInspection.sourceURL
                    inspect(request: initialInspection)
                } else if initialInspection == nil, !model.hasUnsavedChanges {
                    source = model.savedDocumentURL ?? model.url
                }
            }
            .sheet(isPresented: $showValidation) { VerificationView(initialMode: "pdfua", sourceURL: result).environmentObject(model) }
    }

    private func taggedEditor(_ report: AccessibilityTreeReport) -> some View {
        HStack(alignment: .top, spacing: 18) {
            List(selection: $selection) {
                ForEach(orderedNodes(report)) { node in
                    HStack(alignment: .top, spacing: 8) {
                        Toggle("Incluir \(node.role) \(node.id) no grupo", isOn: Binding(
                            get: { groupSelection.contains(node.id) },
                            set: { if $0 { groupSelection.insert(node.id) } else { groupSelection.remove(node.id) } }))
                            .toggleStyle(.checkbox).labelsHidden()
                            .accessibilityLabel("Incluir tag \(node.role) \(node.id) no grupo")
                            .disabled(model.busy || groups.contains { ($0["children"] as? [String] ?? []).contains(node.id) })
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\(edits[node.id]?["role"] as? String ?? node.role)\(node.page.map { " · página \($0)" } ?? "")").font(.headline)
                            Text(node.title.isEmpty ? node.alt : node.title).font(.caption).lineLimit(2)
                        }
                    }.padding(.leading, CGFloat(min(node.depth, 8)) * 10).tag(node.id)
                }
            }.frame(minWidth: 260).onChange(of: selection) { _, _ in loadSelection() }
            ScrollView {
              VStack(alignment: .leading, spacing: 10) {
                if selection != nil {
                    Picker("Papel", selection: $role) { ForEach(roles, id: \.self) { Text($0).tag($0) } }
                        .accessibilityLabel("Papel da tag")
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Título da tag").font(.caption)
                        TextField("Título", text: $tagTitle).textFieldStyle(.roundedBorder).accessibilityLabel("Título da tag")
                            .accessibilityIdentifier("pdf.accessibility.tag.title")
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Texto alternativo").font(.caption)
                        TextField("Descrição do conteúdo", text: $alt, axis: .vertical).lineLimit(3...6).textFieldStyle(.roundedBorder).accessibilityLabel("Texto alternativo")
                            .accessibilityIdentifier("pdf.accessibility.tag.alt")
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Texto de substituição (ActualText)").font(.caption)
                        TextField("Texto de substituição", text: $actualText, axis: .vertical).lineLimit(2...4).textFieldStyle(.roundedBorder).accessibilityLabel("Texto de substituição (ActualText)")
                            .accessibilityIdentifier("pdf.accessibility.tag.actual-text")
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Idioma da tag (opcional)").font(.caption)
                        TextField("pt-BR", text: $tagLanguage).textFieldStyle(.roundedBorder).accessibilityLabel("Idioma da tag (opcional)")
                            .accessibilityIdentifier("pdf.accessibility.tag.language")
                    }
                    if role == "TH" {
                        Picker("Cabeçalho da tabela", selection: $scope) { Text("Não definido").tag(""); Text("Coluna").tag("Column"); Text("Linha").tag("Row"); Text("Ambos").tag("Both") }
                            .accessibilityLabel("Escopo do cabeçalho da tabela")
                            .accessibilityIdentifier("pdf.accessibility.tag.scope")
                    }
                    Menu("Remover atributo…") {
                        Button("Texto de substituição (ActualText)") { removeAttribute("actual_text") }
                        Button("Texto alternativo") { removeAttribute("alt") }
                        Button("Título da tag") { removeAttribute("title") }
                        Button("Idioma da tag") { removeAttribute("language") }
                        if role == "TH" { Button("Escopo do cabeçalho") { removeAttribute("scope") } }
                    }
                    Text("Campos sem alteração são preservados. Apagar um valor remove o atributo; remover ActualText permite voltar ao texto do conteúdo.").font(.caption).foregroundStyle(.secondary)
                    Button("Guardar alteração desta tag") { stageSelection() }
                    HStack { Button("Ler antes") { reorder(-1) }; Button("Ler depois") { reorder(1) } }
                    Text("A ordem muda somente entre tags do mesmo pai. MCIDs, objetos e páginas permanecem vinculados ao conteúdo original.").font(.caption).foregroundStyle(.secondary)
                } else { Text("Selecione uma tag para revisar.").foregroundStyle(.secondary) }
                Divider()
                Text("Reconstruir grupos de leitura").font(.headline)
                Text("Marque tags irmãs contíguas para formar uma seção, lista, linha ou tabela. Defina TH/TD antes de agrupar uma linha e TR antes de agrupar uma tabela.")
                    .font(.caption).foregroundStyle(.secondary)
                Picker("Papel do novo grupo", selection: $groupRole) {
                    ForEach(AccessibilityGroupingEdits.roles, id: \.self) { Text($0).tag($0) }
                }.accessibilityIdentifier("pdf.accessibility.group.role")
                TextField("Título do grupo (opcional)", text: $groupTitle).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Título do novo grupo")
                Button("Agrupar tags marcadas") { stageGroup(report) }
                    .disabled(groupSelection.isEmpty).accessibilityIdentifier("pdf.accessibility.group.stage")
                if !groups.isEmpty {
                    Text("\(PortugueseCount.label(groups.count, "grupo", "grupos")) para criar ao salvar").font(.caption)
                    Button("Descartar agrupamentos") { groups = []; groupSelection = [] }
                }
                Text("Os grupos preservam os vínculos com o conteúdo. Salve e continue na cópia para construir níveis adicionais; confirme depois a leitura com tecnologia assistiva.")
                    .font(.caption).foregroundStyle(.secondary)
              }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(minWidth: 320).disabled(model.busy)
        }.frame(minHeight: 320)
    }
    private func pageEditor(_ report: AccessibilityTreeReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Este PDF não tem árvore de tags. A criação manual abaixo trata cada página inteira como um único bloco. Páginas com colunas, tabelas ou vários papéis precisam de uma estrutura mais detalhada em um editor especializado.").font(.callout)
            ScrollView {
                ForEach(0..<min(report.pages, pageRoles.count), id: \.self) { index in
                    HStack {
                        Text("Página \(index + 1)").frame(width: 90, alignment: .leading)
                        Picker("Papel da página \(index + 1)", selection: $pageRoles[index]) {
                            ForEach(["P", "H1", "H2", "H3", "Figure", "Note"], id: \.self) { Text($0).tag($0) }
                        }.labelsHidden().accessibilityLabel("Papel da página \(index + 1)").frame(width: 100)
                        TextField("Descrição da figura (quando aplicável)", text: $pageAlternatives[index]).textFieldStyle(.roundedBorder)
                    }
                }
            }.frame(minHeight: 160, maxHeight: 320)
            Toggle("Revisei cada página e confirmo que um bloco por página representa sua leitura", isOn: $reviewedPages)
        }.disabled(model.busy)
    }
    private func choose() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        if panel.runModal() == .OK { source = panel.url; report = nil; selection = nil; edits = [:]; groups = []; groupSelection = []; result = nil; error = "" }
    }
    private func inspect(request: AccessibilityInspectionRequest? = nil) {
        guard let source, !model.busy else {
            request?.completion(.failure(NSError(domain: "PDF.Accessibility", code: 3,
                userInfo: [NSLocalizedDescriptionKey: "A inspeção exige um PDF de origem e o motor disponível."])))
            return
        }
        error = ""
        do {
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-accessibility-" + UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            model.execute(operation: "accessibility-inspect", inputs: [source], output: directory.appendingPathComponent("tree.json"), options: [:], title: "Inspecionando tags", completion: { outcome in
                defer { try? FileManager.default.removeItem(at: directory) }
                do {
                    let url = try outcome.get()
                    let size = (try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.intValue ?? Int.max
                    guard size <= 16 * 1024 * 1024 else { throw NSError(domain: "PDF.Accessibility", code: 1, userInfo: [NSLocalizedDescriptionKey: "A árvore excede o limite da revisão visual."]) }
                    let data = try Data(contentsOf: url)
                    guard data.count <= 16 * 1024 * 1024 else { throw NSError(domain: "PDF.Accessibility", code: 1, userInfo: [NSLocalizedDescriptionKey: "A árvore excede o limite da revisão visual."]) }
                    let value = try JSONDecoder().decode(AccessibilityTreeReport.self, from: data)
                    guard value.schema_version == 1, value.pages > 0, value.pages <= 10000, value.nodes.count <= 100000,
                          Set(value.nodes.map(\.id)).count == value.nodes.count,
                          value.input_sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
                          value.nodes.allSatisfy({ (0...128).contains($0.depth) && ($0.page == nil || (1...value.pages).contains($0.page!)) }) else { throw NSError(domain: "PDF.Accessibility", code: 2) }
                    report = value; language = value.language.isEmpty ? "pt-BR" : value.language
                    pageRoles = Array(repeating: "P", count: value.pages); pageAlternatives = Array(repeating: "", count: value.pages)
                    reviewedPages = false; edits = [:]; groups = []; groupSelection = []; selection = nil; result = nil
                    if let request {
                        let candidates = value.nodes.filter { $0.role == request.selectedRole }
                        guard candidates.count == 1, let chosen = candidates.first else {
                            throw NSError(domain: "PDF.Accessibility", code: 4,
                                userInfo: [NSLocalizedDescriptionKey: "A inspeção não encontrou exatamente uma tag do papel solicitado."])
                        }
                        selection = chosen.id
                        loadSelection()
                        request.completion(.success(AccessibilityInspectedSelection(sourceSHA256: value.input_sha256,
                            tagID: chosen.id, role: role,
                            values: ["title": tagTitle, "alt": alt, "actual_text": actualText, "language": tagLanguage, "scope": scope])))
                    }
                } catch {
                    self.error = error.localizedDescription
                    request?.completion(.failure(error))
                }
            })
        } catch {
            self.error = error.localizedDescription
            request?.completion(.failure(error))
        }
    }
    private func loadSelection() {
        guard let node = report?.nodes.first(where: { $0.id == selection }) else { return }
        let edit = edits[node.id] ?? [:]
        role = edit["role"] as? String ?? node.role
        alt = AccessibilityTagEdits.value("alt", original: node.alt, edit: edit)
        actualText = AccessibilityTagEdits.value("actual_text", original: node.actual_text, edit: edit)
        tagTitle = AccessibilityTagEdits.value("title", original: node.title, edit: edit)
        tagLanguage = AccessibilityTagEdits.value("language", original: node.language, edit: edit)
        scope = AccessibilityTagEdits.value("scope", original: node.scope ?? "", edit: edit)
    }
    private func orderedNodes(_ report: AccessibilityTreeReport) -> [AccessibilityTag] {
        let byID = Dictionary(uniqueKeysWithValues: report.nodes.map { ($0.id, $0) })
        var visited = Set<String>(); var ordered: [AccessibilityTag] = []
        func append(_ node: AccessibilityTag) {
            guard visited.insert(node.id).inserted else { return }
            ordered.append(node)
            for child in edits[node.id]?["children"] as? [String] ?? node.children {
                if let value = byID[child] { append(value) }
            }
        }
        for node in report.nodes where node.parent == nil { append(node) }
        return ordered
    }
    private func stageSelection() {
        guard let selection, let node = report?.nodes.first(where: { $0.id == selection }) else { return }
        let edit = AccessibilityTagEdits.stage(id: selection, originalRole: node.role, role: role,
            original: node.textValues,
            values: ["alt": alt, "actual_text": actualText, "title": tagTitle, "language": tagLanguage, "scope": scope],
            present: node.presentFields, existing: edits[selection] ?? [:])
        if edit.count > 1 { edits[selection] = edit } else { edits.removeValue(forKey: selection) }
    }
    private func removeAttribute(_ key: String) {
        guard let selection, let node = report?.nodes.first(where: { $0.id == selection }) else { return }
        stageSelection()
        var edit = edits[selection] ?? ["id": selection]
        if node.presentFields.contains(key) { edit[key] = NSNull() } else { edit.removeValue(forKey: key) }
        if edit.count > 1 { edits[selection] = edit } else { edits.removeValue(forKey: selection) }
        switch key {
        case "alt": alt = ""
        case "actual_text": actualText = ""
        case "title": tagTitle = ""
        case "language": tagLanguage = ""
        case "scope": scope = ""
        default: break
        }
    }
    private func reorder(_ offset: Int) {
        guard let report, let node = report.nodes.first(where: { $0.id == selection }), let parent = node.parent,
              let parentNode = report.nodes.first(where: { $0.id == parent }) else { error = "Selecione uma tag com pai para ajustar a ordem entre irmãos."; return }
        var order = edits[parent]?["children"] as? [String] ?? parentNode.children
        guard let index = order.firstIndex(of: node.id), order.indices.contains(index + offset) else { return }
        order.swapAt(index, index + offset); var edit = edits[parent] ?? ["id": parent]; edit["children"] = order; edits[parent] = edit
    }
    private func stageGroup(_ report: AccessibilityTreeReport) {
        do {
            let selected = report.nodes.filter { groupSelection.contains($0.id) }
            guard let first = selected.first, selected.allSatisfy({ $0.parent == first.parent }) else {
                throw NSError(domain: "PDF.AccessibilityGrouping", code: 4,
                    userInfo: [NSLocalizedDescriptionKey: "Marque somente tags do mesmo pai."])
            }
            let siblings: [String]
            if let parent = first.parent, let parentNode = report.nodes.first(where: { $0.id == parent }) {
                siblings = edits[parent]?["children"] as? [String] ?? parentNode.children
            } else { siblings = report.nodes.filter { $0.parent == nil }.map(\.id) }
            let occupied = Set(groups.flatMap { $0["children"] as? [String] ?? [] })
            guard occupied.isDisjoint(with: groupSelection) else {
                throw NSError(domain: "PDF.AccessibilityGrouping", code: 5,
                    userInfo: [NSLocalizedDescriptionKey: "Uma tag marcada já pertence a um agrupamento pendente."])
            }
            groups.append(try AccessibilityGroupingEdits.stage(selected: groupSelection, siblings: siblings, role: groupRole, title: groupTitle))
            groupSelection = []; groupTitle = ""; error = ""
        } catch { self.error = error.localizedDescription }
    }
    private func save() {
        guard let source, let report, let output = NativeOutput.destination(model: model, toolName: "Acessibilidade", extension: "pdf", originalURL: source) else { return }
        var options: [String: Any] = ["input_sha256": report.input_sha256, "language": language, "edits": Array(edits.values)]
        if !groups.isEmpty { options["groups"] = groups }
        if !report.has_structure_tree {
            options["create_page_tags"] = (0..<report.pages).map { ["page": $0 + 1, "role": pageRoles[$0], "alt": pageAlternatives[$0]] as [String: Any] }
        }
        error = ""
        model.execute(operation: "accessibility-remediate", inputs: [source], output: output, options: options, title: "Corrigindo tags", completion: { outcome in
            switch outcome { case .success(let url): result = url; case .failure(let failure): error = failure.localizedDescription }
        })
    }
}
