import SwiftUI
import AppKit

/// Stable command IDs, rather than translated labels, are the persisted identity.
struct PDFMenuSnapshot: Codable, Equatable {
    var version = 1
    var quickTitle = "Acesso rápido"
    var quickCommands = ["action:open", "action:save", "tool:merge", "tool:ocr", "tool:content-editor"]
    var categoryOrder: [String] = []
    var categoryTitles: [String: String] = [:]
    var documentOrder: [String] = []
    var hiddenDocumentCommands: [String] = []
    var actionTitles: [String: String] = [:]

    func validate() throws {
        guard version == 1, Self.validTitle(quickTitle, limit: 40) else {
            throw PreferenceError.invalid("O nome ou a versão dos menus é inválido.")
        }
        let commands = Set(PDFCommandCatalog.all.map(\.id)).subtracting(["action:palette"])
        try PDFMenuLayout.validateIDs(quickCommands, allowed: commands)
        try PDFMenuLayout.validateIDs(categoryOrder, allowed: Set(AppearanceState.categories))
        try PDFMenuLayout.validateIDs(documentOrder, allowed: Set(PDFMenuLayout.documentDefaults))
        try PDFMenuLayout.validateIDs(hiddenDocumentCommands, allowed: Set(PDFMenuLayout.documentDefaults))
        guard Set(categoryTitles.keys).isSubset(of: Set(AppearanceState.categories)),
              categoryTitles.values.allSatisfy({ Self.validTitle($0, limit: 40) }),
              Set(actionTitles.keys).isSubset(of: Set(PDFCommandCatalog.all.filter { $0.id.hasPrefix("action:") }.map(\.id))),
              actionTitles.values.allSatisfy({ Self.validTitle($0, limit: 80) }) else {
            throw PreferenceError.invalid("Um título personalizado contém um comando desconhecido ou texto inválido.")
        }
    }
    private static func validTitle(_ title: String, limit: Int) -> Bool {
        !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && title.count <= limit &&
        title.unicodeScalars.allSatisfy { !CharacterSet.controlCharacters.contains($0) }
    }
}

enum PDFMenuLayout {
    static let documentDefaults = ["action:search", "action:find-next", "action:page", "action:previous-tab",
        "action:next-tab", "action:recovery", "action:previous-page", "action:next-page", "action:highlight",
        "action:bookmark", "action:rotate", "action:inspector", "action:undo-annotation", "action:redo-annotation",
        "action:sidebar", "action:share"]

    static func validateIDs(_ ids: [String], allowed: Set<String>) throws {
        guard ids.count <= allowed.count, Set(ids).count == ids.count, Set(ids).isSubset(of: allowed) else {
            throw PreferenceError.invalid("A organização contém uma ação desconhecida ou repetida.")
        }
    }
    static func ordered(_ configured: [String], defaults: [String]) -> [String] {
        let allowed = Set(defaults)
        var seen = Set<String>()
        return (configured + defaults).filter { allowed.contains($0) && seen.insert($0).inserted }
    }
    static func move(_ id: String, before target: String, in values: [String]) -> [String] {
        guard id != target, values.contains(id), values.contains(target) else { return values }
        var candidate = values.filter { $0 != id }
        guard let index = candidate.firstIndex(of: target) else { return values }
        candidate.insert(id, at: index)
        return candidate
    }
    static func documentCommands(_ snapshot: PDFMenuSnapshot, hidden: Bool) -> [PDFCommandDefinition] {
        let lookup = Dictionary(uniqueKeysWithValues: PDFCommandCatalog.all.map { ($0.id, $0) })
        return ordered(snapshot.documentOrder, defaults: documentDefaults).compactMap { id in
            guard snapshot.hiddenDocumentCommands.contains(id) == hidden else { return nil }
            return lookup[id]
        }
    }
    @MainActor static func menuTools(_ preferences: AppearancePreferences, hidden: Bool) -> [Tool] {
        preferences.orderedTools().filter { tool in
            let concealed = preferences.state.hiddenTools.contains(tool.id) || preferences.state.hiddenCategories.contains(tool.category)
            return concealed == hidden
        }
    }
}

struct MenuCustomizationControls: View {
    @ObservedObject var store: AdvancedCustomizationStore
    @EnvironmentObject private var preferences: AppearancePreferences
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var selectedCommand = "action:open"
    @State private var query = ""
    @State private var message = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Menus do aplicativo").font(.headline)
            Text("Organize Documento, Ferramentas e seu Acesso rápido. Comandos recolhidos continuam em Outros comandos, nas buscas e com seus atalhos. Os menus do macOS mantêm os controles do sistema.")
                .font(.caption).foregroundStyle(.secondary)
            if !message.isEmpty { Text(message).foregroundStyle(.secondary).accessibilityIdentifier("pdf.menus.feedback") }
            PreferenceNameField("Nome do menu de acesso rápido", value: Binding(get: { store.menu.quickTitle }, set: { value in
                update { $0.quickTitle = value }
            }),maximum:40,fallback:PDFMenuSnapshot().quickTitle)
                .accessibilityIdentifier("pdf.menus.quick-title")
            Text("Acesso rápido").font(.headline)
            Text("Arraste pela alça, use as setas ou remova uma entrada. Remover daqui preserva a ferramenta no catálogo.").font(.caption).foregroundStyle(.secondary)
            ForEach(Array(store.menu.quickCommands.enumerated()), id: \.element) { index, id in
                if let command = PDFCommandCatalog.all.first(where: { $0.id == id }) {
                    HStack {
                        handle("quick", id: id, title: title(command))
                        Label(title(command), systemImage: icon(command)).frame(maxWidth: .infinity, alignment: .leading)
                        moveButtons(index: index, ids: store.menu.quickCommands, title: title(command)) { values in update { $0.quickCommands = values } }
                        Button { update { $0.quickCommands.removeAll { $0 == id } } } label: { Image(systemName: "minus.circle") }
                            .accessibilityLabel("Remover " + title(command) + " do acesso rápido")
                    }.padding(.vertical, 4).dropDestination(for: String.self) { items, _ in
                        drop(items, namespace: "quick", target: id, values: store.menu.quickCommands) { values in update { $0.quickCommands = values } }
                    }
                }
            }
            let candidates = PDFCommandCatalog.all.filter { $0.id != "action:palette" && !store.menu.quickCommands.contains($0.id) }
            if !candidates.isEmpty {
                HStack {
                    Picker("Adicionar comando", selection: $selectedCommand) {
                        ForEach(candidates) { command in Text(title(command)).tag(command.id) }
                    }.accessibilityLabel("Adicionar comando ao acesso rápido")
                        .accessibilityIdentifier("pdf.menus.quick-add")
                    Button("Adicionar") {
                        let id = candidates.contains(where: { $0.id == selectedCommand }) ? selectedCommand : candidates[0].id
                        update { $0.quickCommands.append(id) }
                        selectedCommand = PDFCommandCatalog.all.first { $0.id != "action:palette" && !store.menu.quickCommands.contains($0.id) }?.id ?? ""
                    }
                }.onAppear { if !candidates.contains(where: { $0.id == selectedCommand }) { selectedCommand = candidates[0].id } }
            }
            Divider()
            Text("Categorias do menu Ferramentas").font(.headline)
            Text("A ordem das ferramentas, seus ícones, nomes e visibilidade são compartilhados com a seção Ferramentas da personalização.").font(.caption).foregroundStyle(.secondary)
            let categories = PDFMenuLayout.ordered(store.menu.categoryOrder, defaults: AppearanceState.categories)
            ForEach(Array(categories.enumerated()), id: \.element) { index, category in
                HStack {
                    handle("category", id: category, title: category)
                    PreferenceNameField("Nome da categoria " + category, value: Binding(get: { store.menu.categoryTitles[category] ?? category }, set: { value in
                        update { if value == category { $0.categoryTitles.removeValue(forKey: category) } else { $0.categoryTitles[category] = value } }
                    }),maximum:40,fallback:category)
                    moveButtons(index: index, ids: categories, title: category) { values in update { $0.categoryOrder = values } }
                }.padding(.vertical, 4).dropDestination(for: String.self) { items, _ in
                    drop(items, namespace: "category", target: category, values: categories) { values in update { $0.categoryOrder = values } }
                }
            }
            Divider()
            Text("Menu Documento").font(.headline)
            TextField("Encontrar comando para personalizar", text: $query).textFieldStyle(.roundedBorder)
            let documentIDs = PDFMenuLayout.ordered(store.menu.documentOrder, defaults: PDFMenuLayout.documentDefaults)
            ForEach(Array(documentIDs.enumerated()).filter { _, id in
                query.isEmpty || PDFCommandCatalog.all.first(where: { $0.id == id }).map { title($0).localizedStandardContains(query) || $0.title.localizedStandardContains(query) } == true
            }, id: \.element) { index, id in
                if let command = PDFCommandCatalog.all.first(where: { $0.id == id }) {
                    HStack {
                        handle("document", id: id, title: title(command))
                        Toggle("Mostrar", isOn: Binding(get: { !store.menu.hiddenDocumentCommands.contains(id) }, set: { visible in
                            update { $0.hiddenDocumentCommands.removeAll { $0 == id }; if !visible { $0.hiddenDocumentCommands.append(id) } }
                        })).labelsHidden().accessibilityLabel("Mostrar " + title(command) + " diretamente no menu Documento")
                        PreferenceNameField("Nome de " + command.title, value: Binding(get: { title(command) }, set: { value in
                            update { if value == command.title { $0.actionTitles.removeValue(forKey: id) } else { $0.actionTitles[id] = value } }
                        }),maximum:80,fallback:command.title)
                        moveButtons(index: index, ids: documentIDs, title: title(command)) { values in update { $0.documentOrder = values } }
                    }.padding(.vertical, 4).dropDestination(for: String.self) { items, _ in
                        drop(items, namespace: "document", target: id, values: documentIDs) { values in update { $0.documentOrder = values } }
                    }
                }
            }
            Divider()
            Text("Nomes de comandos de arquivo e janelas").font(.headline)
            ForEach(PDFCommandCatalog.all.filter { $0.id.hasPrefix("action:") && $0.id != "action:palette" && !PDFMenuLayout.documentDefaults.contains($0.id) }) { command in
                HStack {
                    Image(systemName:command.icon).frame(width:22).accessibilityHidden(true)
                    PreferenceNameField("Nome de "+command.title,value:Binding(get:{ title(command) },set:{ value in
                        update { if value == command.title { $0.actionTitles.removeValue(forKey:command.id) } else { $0.actionTitles[command.id] = value } }
                    }),maximum:80,fallback:command.title)
                }
            }
            Button("Restaurar menus e acesso rápido") { update { $0 = PDFMenuSnapshot() } }
        }.animation(preferences.animation(reduceMotion: reduceMotion), value: store.menu)
            // A plain VStack's identifier is inherited by its descendants and
            // overrides the individual field identifiers on macOS. Give the
            // group its own AX node while preserving all interactive children.
            .accessibilityElement(children:.contain)
            .accessibilityLabel("Personalização dos menus do aplicativo")
            .accessibilityIdentifier("pdf.customization.menus")
    }

    private func title(_ command: PDFCommandDefinition) -> String {
        if let tool = tools.first(where: { "tool:" + $0.id == command.id }) { return preferences.title(for: tool) }
        return store.menu.actionTitles[command.id] ?? command.title
    }
    private func icon(_ command: PDFCommandDefinition) -> String {
        if let tool = tools.first(where: { "tool:" + $0.id == command.id }) { return preferences.icon(for: tool) }
        return command.icon
    }
    private func update(_ edit: (inout PDFMenuSnapshot) -> Void) {
        var candidate = store.menu; edit(&candidate)
        do { try store.applyMenu(candidate); message = "" } catch { message = error.localizedDescription }
    }
    private func handle(_ namespace: String, id: String, title: String) -> some View {
        Image(systemName: "line.3.horizontal").foregroundStyle(.secondary).draggable("pdf-menu:" + namespace + ":" + id)
            .help("Arrastar para reordenar").accessibilityLabel("Arrastar " + title)
    }
    private func moveButtons(index: Int, ids: [String], title: String, apply: @escaping ([String]) -> Void) -> some View {
        HStack(spacing: 6) {
            Button { var values = ids; values.swapAt(index, index - 1); apply(values) } label: { Image(systemName: "arrow.up") }
                .disabled(index == 0).accessibilityLabel("Mover " + title + " para cima")
            Button { var values = ids; values.swapAt(index, index + 1); apply(values) } label: { Image(systemName: "arrow.down") }
                .disabled(index == ids.count - 1).accessibilityLabel("Mover " + title + " para baixo")
        }
    }
    private func drop(_ items: [String], namespace: String, target: String, values: [String], apply: ([String]) -> Void) -> Bool {
        let prefix = "pdf-menu:" + namespace + ":"
        guard items.count == 1, let item = items.first, item.hasPrefix(prefix) else { return false }
        let id = String(item.dropFirst(prefix.count))
        guard id != target, values.contains(id), values.contains(target) else { return false }
        apply(PDFMenuLayout.move(id, before: target, in: values)); return true
    }
}
