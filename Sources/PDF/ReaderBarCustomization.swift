import SwiftUI

struct ReaderBarItem: Identifiable {
    let id: String
    let title: String
    let icon: String
}

enum ReaderBarLayout {
    static let primary: [ReaderBarItem] = [
        .init(id: "sidebar", title: "Páginas e sumário", icon: "sidebar.left"),
        .init(id: "open", title: "Abrir arquivo", icon: "folder"),
        .init(id: "search", title: "Busca", icon: "magnifyingglass"),
        .init(id: "zoom", title: "Botões de zoom", icon: "plus.magnifyingglass"),
        .init(id: "compare", title: "Leitura de dois documentos", icon: "rectangle.split.2x1"),
        .init(id: "fit", title: "Ajustar à janela", icon: "arrow.up.left.and.arrow.down.right"),
        .init(id: "options", title: "Opções do documento", icon: "ellipsis.circle"),
        .init(id: "customize", title: "Personalizar leitor", icon: "slider.horizontal.3"),
        .init(id: "save", title: "Salvar cópia", icon: "square.and.arrow.down")
    ]
    static let annotations: [ReaderBarItem] = [
        .init(id: "highlight", title: "Realçar", icon: "highlighter"),
        .init(id: "note", title: "Notas", icon: "note.text"),
        .init(id: "ink", title: "Desenhar", icon: "pencil.tip"),
        .init(id: "editor", title: "Editar anotações", icon: "cursorarrow.rays"),
        .init(id: "history", title: "Desfazer e refazer", icon: "arrow.uturn.backward"),
        .init(id: "bookmark", title: "Marcar página", icon: "bookmark")
    ]
    static func validate(_ value: String, allowed: Set<String>) throws {
        guard value.count <= 1_024 else { throw PreferenceError.invalid("A organização da barra é muito grande.") }
        let ids = value.isEmpty ? [] : value.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
        try PDFMenuLayout.validateIDs(ids, allowed: allowed)
    }
    static func ordered(_ value: String, defaults: [ReaderBarItem]) -> [ReaderBarItem] {
        let lookup = Dictionary(uniqueKeysWithValues: defaults.map { ($0.id, $0) })
        return PDFMenuLayout.ordered(value.split(separator: ",").map(String.init), defaults: defaults.map(\.id)).compactMap { lookup[$0] }
    }
    static func visible(_ value: String, hidden: String, defaults: [ReaderBarItem], pinSave: Bool = false) -> [ReaderBarItem] {
        let hiddenIDs = Set(hidden.split(separator: ",").map(String.init))
        return ordered(value, defaults: defaults).filter { item in
            (item.id == "customize" || !hiddenIDs.contains(item.id)) && !(item.id == "save" && pinSave)
        }
    }
}

struct ReaderBarCustomizationControls: View {
    @EnvironmentObject private var preferences: AppearancePreferences
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage("readerToolbarOrder") private var toolbarOrder = ""
    @AppStorage("readerAnnotationOrder") private var annotationOrder = ""
    @AppStorage("readerHiddenToolbar") private var hiddenToolbar = ""
    @AppStorage("readerHiddenAnnotations") private var hiddenAnnotations = ""
    @AppStorage("readerPinSave") private var pinSave = true
    @AppStorage("readerShowAnnotations") private var showAnnotations = true

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Ordem e visibilidade das barras").font(.headline)
            Text("Arraste pela alça ou use as setas. Os ajustes entram em vigor imediatamente; Personalizar leitor permanece acessível.")
                .font(.caption).foregroundStyle(.secondary)
            Toggle("Manter Salvar cópia fixo à direita", isOn: $pinSave)
            Text("Desative para posicionar Salvar cópia junto dos demais controles. As barras podem ser roladas em janelas menores.").font(.caption).foregroundStyle(.secondary)
            Text("Barra principal").font(.subheadline.bold())
            rows(defaults: ReaderBarLayout.primary, order: $toolbarOrder, hidden: $hiddenToolbar, namespace: "primary")
            Text("Barra de anotações").font(.subheadline.bold())
            rows(defaults: ReaderBarLayout.annotations, order: $annotationOrder, hidden: $hiddenAnnotations, namespace: "annotation")
                .disabled(!showAnnotations)
            Button("Restaurar ordem e controles das barras") {
                withAnimation(preferences.animation(reduceMotion: reduceMotion)) {
                    toolbarOrder = ""; annotationOrder = ""; hiddenToolbar = ""; hiddenAnnotations = ""; pinSave = true
                }
            }
        }.animation(preferences.animation(reduceMotion: reduceMotion), value: toolbarOrder)
            .animation(preferences.animation(reduceMotion: reduceMotion), value: annotationOrder)
            .accessibilityIdentifier("pdf.customization.reader-bars")
    }

    private func rows(defaults: [ReaderBarItem], order: Binding<String>, hidden: Binding<String>, namespace: String) -> some View {
        let items = ReaderBarLayout.ordered(order.wrappedValue, defaults: defaults)
        return ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
            let fixed = item.id == "save" && pinSave
            HStack(spacing: 8) {
                Image(systemName: "line.3.horizontal").foregroundStyle(.secondary)
                    .draggable("pdf-reader-bar:" + namespace + ":" + item.id)
                    .help("Arrastar para reordenar").accessibilityLabel("Arrastar " + item.title)
                    .disabled(fixed)
                Toggle(isOn: visibility(item.id, in: hidden)) {
                    Label(item.title + (fixed ? " · fixo" : ""), systemImage: item.icon).font(.callout)
                }.disabled(item.id == "customize").accessibilityLabel("Mostrar " + item.title)
                Spacer(minLength: 4)
                Button { move(index, to: index - 1, items: items, order: order) } label: { Image(systemName: "arrow.up") }
                    .disabled(index == 0 || fixed).accessibilityLabel("Mover " + item.title + " para antes")
                Button { move(index, to: index + 1, items: items, order: order) } label: { Image(systemName: "arrow.down") }
                    .disabled(index == items.count - 1 || fixed).accessibilityLabel("Mover " + item.title + " para depois")
            }.padding(.vertical, 4).dropDestination(for: String.self) { values, _ in
                let prefix = "pdf-reader-bar:" + namespace + ":"
                guard !fixed, values.count == 1, let value = values.first, value.hasPrefix(prefix) else { return false }
                let id = String(value.dropFirst(prefix.count))
                guard id != item.id, !(id == "save" && pinSave), items.contains(where: { $0.id == id }) else { return false }
                order.wrappedValue = PDFMenuLayout.move(id, before: item.id, in: items.map(\.id)).joined(separator: ",")
                return true
            }
        }
    }
    private func move(_ from: Int, to: Int, items: [ReaderBarItem], order: Binding<String>) {
        guard items.indices.contains(from), items.indices.contains(to) else { return }
        var ids = items.map(\.id); ids.swapAt(from, to); order.wrappedValue = ids.joined(separator: ",")
    }
    private func visibility(_ id: String, in hidden: Binding<String>) -> Binding<Bool> {
        Binding(get: { id == "customize" || !hidden.wrappedValue.split(separator: ",").contains(Substring(id)) }, set: { visible in
            guard id != "customize" else { return }
            var ids = hidden.wrappedValue.split(separator: ",").map(String.init).filter { $0 != id }
            if !visible { ids.append(id) }; hidden.wrappedValue = ids.joined(separator: ",")
        })
    }
}
