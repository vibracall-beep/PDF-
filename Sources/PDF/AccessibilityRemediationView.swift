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
    let children: [String]
    let depth: Int
}

struct AccessibilityRemediationView: View {
    @EnvironmentObject private var model: Workspace
    @State private var source: URL?
    @State private var report: AccessibilityTreeReport?
    @State private var selection: String?
    @State private var role = "P"
    @State private var alt = ""
    @State private var actualText = ""
    @State private var tagTitle = ""
    @State private var tagLanguage = ""
    @State private var scope = "Column"
    @State private var language = "pt-BR"
    @State private var edits: [String: [String: Any]] = [:]
    @State private var pageRoles: [String] = []
    @State private var pageAlternatives: [String] = []
    @State private var reviewedPages = false
    @State private var result: URL?
    @State private var error = ""
    @State private var showValidation = false
    private let roles = ["Document", "Part", "Sect", "Div", "P", "H", "H1", "H2", "H3", "H4", "H5", "H6", "L", "LI", "Lbl", "LBody", "Table", "TR", "TH", "TD", "THead", "TBody", "TFoot", "Figure", "Formula", "Caption", "Note", "Link", "Span", "Quote", "BlockQuote"]

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
                TextField("Idioma do documento (BCP 47)", text: $language).textFieldStyle(.roundedBorder)
                if report.has_structure_tree { taggedEditor(report) }
                else { pageEditor(report) }
                HStack {
                    Text("\(edits.count) tag(s) com alterações guardadas").font(.caption).foregroundStyle(.secondary)
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
                }
            }
            if model.busy { HStack { ProgressView().controlSize(.small); Text(model.message); Button("Cancelar") { model.cancel() } } }
            if !error.isEmpty { Text(error).foregroundStyle(.red).textSelection(.enabled) }
        }.padding(24).frame(minWidth: 760, minHeight: 580)
            .onAppear { if !model.hasUnsavedChanges { source = model.savedDocumentURL ?? model.url } }
            .sheet(isPresented: $showValidation) { VerificationView(initialMode: "pdfua", sourceURL: result).environmentObject(model) }
    }

    private func taggedEditor(_ report: AccessibilityTreeReport) -> some View {
        HStack(alignment: .top, spacing: 18) {
            List(selection: $selection) {
                ForEach(orderedNodes(report)) { node in
                    VStack(alignment: .leading, spacing: 3) {
                        Text("\(edits[node.id]?["role"] as? String ?? node.role)\(node.page.map { " · página \($0)" } ?? "")").font(.headline)
                        Text(node.title.isEmpty ? node.alt : node.title).font(.caption).lineLimit(2)
                    }.padding(.leading, CGFloat(min(node.depth, 8)) * 10).tag(node.id)
                }
            }.frame(minWidth: 260).onChange(of: selection) { _, _ in loadSelection() }
            VStack(alignment: .leading, spacing: 10) {
                if selection != nil {
                    Picker("Papel", selection: $role) { ForEach(roles, id: \.self) { Text($0).tag($0) } }
                    TextField("Título da tag", text: $tagTitle).textFieldStyle(.roundedBorder)
                    TextField("Texto alternativo", text: $alt, axis: .vertical).lineLimit(3...6).textFieldStyle(.roundedBorder)
                    TextField("Texto de substituição (ActualText)", text: $actualText, axis: .vertical).lineLimit(2...4).textFieldStyle(.roundedBorder)
                    TextField("Idioma da tag (opcional)", text: $tagLanguage).textFieldStyle(.roundedBorder)
                    if role == "TH" { Picker("Cabeçalho da tabela", selection: $scope) { Text("Coluna").tag("Column"); Text("Linha").tag("Row"); Text("Ambos").tag("Both") } }
                    Button("Guardar alteração desta tag") { stageSelection() }
                    HStack { Button("Ler antes") { reorder(-1) }; Button("Ler depois") { reorder(1) } }
                    Text("A ordem muda somente entre tags do mesmo pai. MCIDs, objetos e páginas permanecem vinculados ao conteúdo original.").font(.caption).foregroundStyle(.secondary)
                } else { Text("Selecione uma tag para revisar.").foregroundStyle(.secondary) }
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
                        }.labelsHidden().frame(width: 100)
                        TextField("Descrição da figura (quando aplicável)", text: $pageAlternatives[index]).textFieldStyle(.roundedBorder)
                    }
                }
            }.frame(minHeight: 160, maxHeight: 320)
            Toggle("Revisei cada página e confirmo que um bloco por página representa sua leitura", isOn: $reviewedPages)
        }.disabled(model.busy)
    }
    private func choose() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        if panel.runModal() == .OK { source = panel.url; report = nil; selection = nil; edits = [:]; result = nil; error = "" }
    }
    private func inspect() {
        guard let source else { return }; error = ""
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
                    reviewedPages = false; edits = [:]; selection = nil; result = nil
                } catch { self.error = error.localizedDescription }
            })
        } catch { self.error = error.localizedDescription }
    }
    private func loadSelection() {
        guard let node = report?.nodes.first(where: { $0.id == selection }) else { return }
        let edit = edits[node.id] ?? [:]
        role = edit["role"] as? String ?? node.role; alt = edit["alt"] as? String ?? node.alt
        actualText = edit["actual_text"] as? String ?? node.actual_text; tagTitle = edit["title"] as? String ?? node.title
        tagLanguage = edit["language"] as? String ?? node.language; scope = edit["scope"] as? String ?? node.scope ?? "Column"
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
        guard let selection else { return }
        var edit = edits[selection] ?? ["id": selection]
        edit["role"] = role; edit["alt"] = alt; edit["actual_text"] = actualText; edit["title"] = tagTitle
        edit["language"] = tagLanguage
        if role == "TH" { edit["scope"] = scope } else { edit.removeValue(forKey: "scope") }
        edits[selection] = edit
    }
    private func reorder(_ offset: Int) {
        guard let report, let node = report.nodes.first(where: { $0.id == selection }), let parent = node.parent,
              let parentNode = report.nodes.first(where: { $0.id == parent }) else { error = "Selecione uma tag com pai para ajustar a ordem entre irmãos."; return }
        var order = edits[parent]?["children"] as? [String] ?? parentNode.children
        guard let index = order.firstIndex(of: node.id), order.indices.contains(index + offset) else { return }
        order.swapAt(index, index + offset); var edit = edits[parent] ?? ["id": parent]; edit["children"] = order; edits[parent] = edit
    }
    private func save() {
        guard let source, let report, let output = NativeOutput.destination(model: model, toolName: "Acessibilidade", extension: "pdf", originalURL: source) else { return }
        var options: [String: Any] = ["input_sha256": report.input_sha256, "language": language, "edits": Array(edits.values)]
        if !report.has_structure_tree {
            options["create_page_tags"] = (0..<report.pages).map { ["page": $0 + 1, "role": pageRoles[$0], "alt": pageAlternatives[$0]] as [String: Any] }
        }
        error = ""
        model.execute(operation: "accessibility-remediate", inputs: [source], output: output, options: options, title: "Corrigindo tags", completion: { outcome in
            switch outcome { case .success(let url): result = url; case .failure(let failure): error = failure.localizedDescription }
        })
    }
}
