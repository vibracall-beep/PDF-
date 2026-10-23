import AppKit
import SwiftUI

/// Preferences are exercised in disposable suites, never the user's standard domain.
@MainActor enum AppearanceAuditChecks {
    static func run() throws {
        func require(_ value: @autoclosure () throws -> Bool, _ message: String) throws {
            guard try value() else { throw NSError(domain: "PDF.AppearanceAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func rejects(_ operation: () throws -> Void) -> Bool {
            do { try operation(); return false } catch { return true }
        }
        let readerKeys = ["readerMode", "readerDirection", "readerDisplayBox", "readerPageBackground", "readerAutoScale", "readerZoom",
                          "readerDisplayPageBreaks", "readerSidebar", "readerShowAnnotations", "readerHiddenToolbar", "readerHiddenAnnotations",
                          "readerHighlightColor", "readerNoteColor", "readerInkColor", "readerInkWidth"]
        let watchedKeys = readerKeys + [AppearancePreferences.storageKey, "outputPrefix"]
        let standardBefore = watchedKeys.map { UserDefaults.standard.object(forKey: $0) as? NSObject }
        let firstName = "PDF.AppearanceAudit.source.\(UUID().uuidString)", secondName = "PDF.AppearanceAudit.target.\(UUID().uuidString)"
        guard let source = UserDefaults(suiteName: firstName), let target = UserDefaults(suiteName: secondName) else {
            throw NSError(domain: "PDF.AppearanceAudit", code: 2)
        }
        defer { source.removePersistentDomain(forName: firstName); target.removePersistentDomain(forName: secondName) }
        guard tools.count >= 3 else { throw NSError(domain: "PDF.AppearanceAudit", code: 3) }
        let ids = Array(tools.prefix(3).map(\.id))

        // Legacy migration should preserve user intent while removing stale catalog IDs.
        source.set("Escuro", forKey: "appearance"); source.set("Violeta", forKey: "accent")
        source.set(true, forKey: "compact"); source.set(false, forKey: "showRecent")
        source.set([ids[2], ids[0], ids[2], "missing-tool"].joined(separator: ","), forKey: "toolOrder")
        let preferences = AppearancePreferences(defaults: source)
        try require(preferences.state.colorScheme == "dark" && preferences.state.accentHex == "#AF52DE" && preferences.state.density == "compact" && !preferences.state.showRecent,
                    "A migração não preservou as preferências legadas.")
        try require(preferences.state.toolOrder == [ids[2], ids[0]], "A migração não removeu duplicatas e ferramentas desconhecidas mantendo a ordem.")

        var customized = AppearanceState()
        customized.layout = "list"; customized.density = "spacious"; customized.cardWidth = 298
        customized.fontSize = 17; customized.iconSize = 29; customized.showDetails = false
        customized.showCategoryLabels = true; customized.groupByCategory = true; customized.showHero = false; customized.showRecent = false
        customized.accentHex = "#123abc"; customized.colorScheme = "dark"; customized.glassStyle = "frosted"
        customized.glassTransparency = 0.55; customized.backgroundStyle = "plain"
        customized.animationsEnabled = true; customized.animationStyle = "quick"; customized.animationDuration = 0.4; customized.hoverScale = 1.05
        customized.sidebarStyle = "labels"; customized.sidebarWidth = 280
        customized.sidebar.reverse()
        if let index = customized.sidebar.firstIndex(where: { $0.id == "Leitor" }) {
            customized.sidebar[index].label = "Minha leitura"; customized.sidebar[index].icon = "book.fill"
        }
        if let index = customized.sidebar.firstIndex(where: { $0.id == "Fluxos" }) { customized.sidebar[index].visible = false }
        customized.toolOrder = [ids[2], ids[0], ids[1]]; customized.favorites = [ids[1], ids[0]]
        customized.hiddenTools = [ids[2]]; customized.hiddenCategories = [AppearanceState.categories[0]]
        customized.toolTitles = [ids[0]: "Minha ferramenta"]; customized.toolIcons = [ids[0]: "star.fill"]
        try customized.validate(); preferences.state = customized
        let reloaded = AppearancePreferences(defaults: source)
        try require(reloaded.state == customized, "A aparência personalizada não persistiu ao recriar as preferências.")
        try require(reloaded.orderedTools().prefix(3).map(\.id) == customized.toolOrder, "A ordem personalizada de ferramentas não foi aplicada.")
        try require(reloaded.title(for: tools[0]) == "Minha ferramenta" && reloaded.icon(for: tools[0]) == "star.fill", "Nome ou ícone personalizado da ferramenta foi perdido.")
        try require(reloaded.preferredScheme == .dark, "A aparência escura não foi aplicada.")

        var reader = ReaderSettingsSnapshot(defaults: source)
        reader.mode = 2; reader.direction = "horizontal"; reader.displayBox = "media"; reader.background = "#112233"
        reader.autoScale = false; reader.zoom = 2.35; reader.pageBreaks = false; reader.sidebar = false; reader.annotations = false
        reader.hiddenToolbar = "open,save"; reader.hiddenAnnotations = "note,ink"
        reader.highlightColor = "#11AA33"; reader.noteColor = "#8844AA"; reader.inkColor = "#2255CC"; reader.inkWidth = 7.5
        try reader.validate(); reader.apply(to: source)
        let exported = try preferences.exportData()
        let imported = AppearancePreferences(defaults: target)
        try imported.importData(exported)
        try require(try imported.exportData() == exported, "Exportar/importar não preservou todos os ajustes de aparência e leitor.")
        try require(imported.state == customized && target.double(forKey: "readerZoom") == 2.35 && target.string(forKey: "readerHiddenAnnotations") == "note,ink",
                    "O snapshot não restaurou valores reais na suíte de destino.")
        let baseline = try imported.exportData()
        let storedAppearance = target.data(forKey: AppearancePreferences.storageKey)

        func invalidSnapshot(section: String, key: String, value: Any) throws -> Data {
            guard var object = try JSONSerialization.jsonObject(with: exported) as? [String: Any],
                  var part = object[section] as? [String: Any] else { throw NSError(domain: "PDF.AppearanceAudit", code: 4) }
            // A valid unrelated change proves rejection happens before either half is applied.
            if section == "reader", var appearance = object["appearance"] as? [String: Any] {
                appearance["fontSize"] = 18.0; object["appearance"] = appearance
            }
            part[key] = value; object[section] = part
            return try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        }
        func rejectAtomically(_ data: Data, label: String) throws {
            try require(rejects { try imported.importData(data) }, "Importação aceitou configuração inválida: \(label).")
            try require(try imported.exportData() == baseline, "Importação inválida alterou aparência ou leitor: \(label).")
            try require(target.data(forKey: AppearancePreferences.storageKey) == storedAppearance, "Importação inválida alterou o estado persistido: \(label).")
        }
        let badAppearance: [(String, Any)] = [
            ("version", 2), ("layout", "unknown"), ("density", "tiny"), ("colorScheme", "automatic"),
            ("glassStyle", "invisible"), ("backgroundStyle", "photo"), ("animationStyle", "infinite"), ("sidebarStyle", "unknown"),
            ("accentHex", "#zz1234"), ("cardWidth", 179.0), ("fontSize", 20.1), ("iconSize", 41.0),
            ("glassTransparency", 0.91), ("animationDuration", 0.0), ("hoverScale", 1.08), ("sidebarWidth", 321.0)
        ]
        for (key, value) in badAppearance { try rejectAtomically(invalidSnapshot(section: "appearance", key: key, value: value), label: key) }
        let badReader: [(String, Any)] = [
            ("mode", -1), ("mode", 3), ("direction", "diagonal"), ("displayBox", "unknown"), ("background", "red"),
            ("zoom", 0.09), ("zoom", 8.1), ("hiddenToolbar", "open,delete"), ("hiddenAnnotations", "ink,unknown"),
            ("highlightColor", "yellow"), ("noteColor", "#XX4400"), ("inkColor", "#11223"), ("inkWidth", 0.49), ("inkWidth", 20.1)
        ]
        for (key, value) in badReader { try rejectAtomically(invalidSnapshot(section: "reader", key: key, value: value), label: key) }
        let sidebarData = try JSONEncoder().encode(customized.sidebar)
        guard let sidebar = try JSONSerialization.jsonObject(with: sidebarData) as? [[String: Any]] else { throw NSError(domain: "PDF.AppearanceAudit", code: 5) }
        var unknownSidebar = sidebar; unknownSidebar[0]["id"] = "unknown-section"
        try rejectAtomically(invalidSnapshot(section: "appearance", key: "sidebar", value: unknownSidebar), label: "sidebar ID")
        var duplicateSidebar = sidebar; duplicateSidebar[0] = duplicateSidebar[1]
        try rejectAtomically(invalidSnapshot(section: "appearance", key: "sidebar", value: duplicateSidebar), label: "sidebar duplicate")
        var hiddenHome = sidebar
        if let index = hiddenHome.firstIndex(where: { $0["id"] as? String == "Início" }) { hiddenHome[index]["visible"] = false }
        try rejectAtomically(invalidSnapshot(section: "appearance", key: "sidebar", value: hiddenHome), label: "hidden home")
        var blankLabel = sidebar; blankLabel[0]["label"] = " \n "
        try rejectAtomically(invalidSnapshot(section: "appearance", key: "sidebar", value: blankLabel), label: "empty sidebar label")
        try rejectAtomically(Data("{invalid-json".utf8), label: "malformed JSON")
        try rejectAtomically(Data(repeating: 0, count: 1_048_577), label: "oversized snapshot")
        var nonFiniteAppearance = customized; nonFiniteAppearance.cardWidth = .infinity
        try require(rejects { try nonFiniteAppearance.validate() }, "Aparência aceitou tamanho infinito.")
        var nonFiniteReader = reader; nonFiniteReader.zoom = .nan
        try require(rejects { try nonFiniteReader.validate() }, "Leitor aceitou zoom NaN.")
        var nonFiniteInk = reader; nonFiniteInk.inkWidth = .infinity
        try require(rejects { try nonFiniteInk.validate() }, "Leitor aceitou espessura de traço infinita.")

        // Version-1 snapshots made before annotation styling must remain importable.
        guard var legacySnapshot = try JSONSerialization.jsonObject(with: exported) as? [String: Any],
              var legacyReader = legacySnapshot["reader"] as? [String: Any] else { throw NSError(domain: "PDF.AppearanceAudit", code: 6) }
        for key in ["highlightColor", "noteColor", "inkColor", "inkWidth"] { legacyReader.removeValue(forKey: key) }
        legacySnapshot["reader"] = legacyReader
        try imported.importData(JSONSerialization.data(withJSONObject: legacySnapshot))
        let migratedReader = ReaderSettingsSnapshot(defaults: target)
        try require(migratedReader.highlightColor == "#FFE600" && migratedReader.noteColor == "#FFCC00" && migratedReader.inkColor == "#007AFF" && migratedReader.inkWidth == 2.5 && migratedReader.zoom == reader.zoom,
                    "Snapshot antigo não importou os estilos padrão ou perdeu opções de leitura existentes.")
        try imported.importData(exported)

        // Tool IDs intentionally normalize for presets imported after catalog changes.
        var normalized = customized
        normalized.toolOrder = [ids[1], "missing-tool", ids[1], ids[0]]
        normalized.favorites = [ids[0], ids[0], "missing-tool"]
        normalized.hiddenTools = ["missing-tool", ids[2], ids[2]]
        try normalized.validate()
        try require(normalized.toolOrder == [ids[1], ids[0]] && normalized.favorites == [ids[0]] && normalized.hiddenTools == [ids[2]],
                    "A normalização do catálogo alterou a ordem ou manteve IDs inválidos.")

        for style in ["gentle", "spring", "quick"] {
            imported.state.animationStyle = style; imported.state.animationsEnabled = true
            try require(imported.animation(reduceMotion: false) != nil, "Animação habilitada não foi criada.")
            try require(imported.animation(reduceMotion: true) == nil, "A animação ignorou Reduzir Movimento.")
        }
        imported.state.animationsEnabled = false
        try require(imported.animation(reduceMotion: false) == nil && imported.animation(reduceMotion: true) == nil, "A preferência de desativar animações foi ignorada.")

        target.set("preservar-prefixo", forKey: "outputPrefix")
        let appearanceBeforeReset = imported.state
        imported.resetReader()
        try require(readerKeys.allSatisfy { target.object(forKey: $0) == nil }, "Restaurar leitor não removeu todas as preferências da suíte injetada.")
        try require(target.string(forKey: "outputPrefix") == "preservar-prefixo" && imported.state == appearanceBeforeReset, "Restaurar leitor alterou preferências de arquivos ou aparência.")
        let defaults = ReaderSettingsSnapshot(defaults: target)
        try require(defaults.mode == 0 && defaults.direction == "vertical" && defaults.displayBox == "crop" && defaults.background == "#E8E9EF" && defaults.autoScale && defaults.zoom == 1 && defaults.pageBreaks && defaults.sidebar && defaults.annotations && defaults.hiddenToolbar.isEmpty && defaults.hiddenAnnotations.isEmpty,
                    "Restaurar leitor não recuperou os valores padrão.")
        try require(defaults.highlightColor == "#FFE600" && defaults.noteColor == "#FFCC00" && defaults.inkColor == "#007AFF" && defaults.inkWidth == 2.5,
                    "Restaurar leitor não recuperou as cores e a espessura padrão das anotações.")
        for (index, key) in watchedKeys.enumerated() {
            let current = UserDefaults.standard.object(forKey: key) as? NSObject
            let same = standardBefore[index].map { before in current.map { before.isEqual($0) } ?? false } ?? (current == nil)
            try require(same, "O teste de aparência alterou UserDefaults.standard em \(key).")
        }
        print("Appearance audit: isolated persistence, complete snapshot round-trip, atomic rejection, catalog normalization, reader reset and motion accessibility passed")
    }
}
