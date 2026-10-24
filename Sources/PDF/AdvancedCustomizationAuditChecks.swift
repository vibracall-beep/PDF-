import Foundation

@MainActor enum AdvancedCustomizationAuditChecks {
    static func run() throws {
        let suite = "PDF.AdvancedCustomization.Audit."+UUID().uuidString
        guard let defaults = UserDefaults(suiteName:suite) else { throw PreferenceError.invalid("Não foi possível isolar os ajustes de auditoria.") }
        defer { defaults.removePersistentDomain(forName:suite) }
        let preferences = AppearancePreferences(defaults:defaults),store = preferences.advanced
        func check(_ condition:Bool,_ message:String) throws { if !condition { throw PreferenceError.invalid("Personalização avançada: "+message) } }
        try AdvancedCustomizationStore.validate(store.snapshot)
        let catalogIDs = tools.map(\.id)
        try check(Set(catalogIDs).count == catalogIDs.count,"IDs do catálogo precisam ser únicos")
        try check(Set(tools.map(\.category)).isSubset(of:Set(AppearanceState.categories)),"todas as categorias precisam aparecer nos filtros e menus")
        let commandIDs = PDFCommandCatalog.all.map(\.id)
        try check(Set(commandIDs).count == commandIDs.count && Set(catalogIDs.map { "tool:"+$0 }).isSubset(of:Set(commandIDs)),"cada ferramenta precisa ter um comando único na paleta")
        try check(preferences.orderedTools().map(\.id) == catalogIDs,"a personalização inicial deve incluir todas as ferramentas")
        let originalTools:Set<String> = ["merge", "split", "compress", "word", "powerpoint", "excel", "word-pdf", "powerpoint-pdf", "excel-pdf", "edit", "jpg", "images", "signature", "watermark", "rotate", "html", "unlock", "protect", "organize", "pdfa", "repair", "numbers", "scan", "ocr", "compare", "redact", "crop", "forms", "summary", "translate", "markdown", "workflow", "png", "odt-pdf", "txt-pdf", "rtf-pdf", "epub-pdf", "csv-pdf", "pages-pdf", "flatten", "delete-pages", "extract-pages", "converter", "share", "annotate", "fill-forms", "chat", "quiz", "sign-service", "digital-sign", "verify-signatures", "validate-pdfa", "validate-pdfua", "benchmark"]
        try check(originalTools.isSubset(of:Set(catalogIDs)),"a expansão não pode remover ferramentas existentes")
        let original = store.binding(for:"action:open")
        do { try store.assign(.init(key:"q"),to:"action:open"); throw PreferenceError.invalid("Atalho reservado foi aceito.") }
        catch { try check(store.binding(for:"action:open") == original,"rejeitar tecla reservada deve preservar o atalho anterior") }
        var conflictRejected = false
        do { try store.assign(.init(key:"o"),to:"tool:merge") } catch { conflictRejected = true }
        try check(conflictRejected && store.binding(for:"tool:merge") == nil,"atalho duplicado não pode ser publicado")
        try store.assign(.init(key:"j",modifiers:["shift","command","option"]),to:"tool:merge")
        let saved = AdvancedCustomizationStore(defaults:defaults)
        try check(saved.binding(for:"tool:merge")?.label == "⌥⇧⌘J","atalhos devem persistir e normalizar modificadores")
        try store.assign(nil,to:"action:open")
        try check(store.binding(for:"action:open") == nil,"remover atalho padrão deve permanecer removido")
        try store.assign(.init(key:"o"),to:"tool:merge")
        try check(store.binding(for:"tool:merge")?.key == "o","atalho liberado deve poder ser reutilizado")
        store.restoreBindings()
        preferences.state.hiddenTools = ["ocr"]
        var expectedToolOrder = catalogIDs.filter { $0 != "ocr" }
        expectedToolOrder.insert("ocr", at: try require(expectedToolOrder.firstIndex(of: "merge")))
        var expectedSidebar = preferences.state.sidebar.filter { $0.id != "Fluxos" }
        let flows = try require(preferences.state.sidebar.first { $0.id == "Fluxos" })
        expectedSidebar.insert(flows, at: try require(expectedSidebar.firstIndex { $0.id == "Leitor" }))
        preferences.moveTool("ocr",before:"merge")
        preferences.moveSidebar("Fluxos",before:"Leitor")
        try check(preferences.orderedTools().map(\.id) == expectedToolOrder,"mover antes de uma ferramenta deve preservar todas as outras posições relativas")
        try check(preferences.state.sidebar == expectedSidebar,"mover uma seção deve preservar as demais seções")
        defaults.set("{original} · revisão",forKey:"outputFilenameTemplate")
        defaults.set("/tmp/PDF-Audit-Output",forKey:"outputDirectory")
        defaults.set(false,forKey:"readerAutoScale")
        defaults.set(1.75,forKey:"readerZoom")
        let data = try preferences.exportData()
        try store.saveProfile(name:"Revisão",settings:data)
        let profileID = try require(store.profiles.first?.id)
        preferences.state.accentHex = "#AABBCC"; preferences.state.hiddenTools = []
        preferences.state.toolOrder = Array(expectedToolOrder.reversed())
        preferences.state.sidebar.reverse()
        try check(preferences.orderedTools().map(\.id) != expectedToolOrder && preferences.state.sidebar != expectedSidebar,"a auditoria precisa alterar a ordem antes de restaurar o perfil")
        defaults.set("Outro",forKey:"outputFilenameTemplate"); defaults.set(2.5,forKey:"readerZoom")
        try preferences.importData(try require(store.profiles.first?.settings))
        try check(preferences.state.accentHex == "#007AFF" && preferences.state.hiddenTools == ["ocr"],"perfil deve restaurar aparência e visibilidade")
        try check(preferences.state.toolOrder == expectedToolOrder && preferences.orderedTools().map(\.id) == expectedToolOrder,"a ordem completa deve ser restaurada pelo perfil e pelo consumidor do catálogo")
        try check(preferences.state.sidebar == expectedSidebar,"o perfil deve restaurar a ordem e as propriedades da navegação")
        try check(preferences.state.sidebar.first(where:{$0.id == "Início"})?.visible == true,"reordenação não pode ocultar Início")
        try check(defaults.double(forKey:"readerZoom") == 1.75 && defaults.string(forKey:"outputFilenameTemplate") == "{original} · revisão","perfil deve restaurar leitura e nomes de saída")
        let reloaded = AdvancedCustomizationStore(defaults:defaults)
        try check(reloaded.profiles.first?.id == profileID,"perfis devem persistir sem alterar identidade")
        let restored = AppearancePreferences(defaults: defaults)
        try check(restored.orderedTools().map(\.id) == expectedToolOrder && restored.state.sidebar == expectedSidebar,"reabrir as preferências deve preservar as ordens publicadas no armazenamento")
        let restoredSnapshot = try JSONDecoder().decode(CustomizationSnapshot.self, from: try require(reloaded.profiles.first?.settings))
        try check(restoredSnapshot.appearance.toolOrder == expectedToolOrder,"os bytes persistidos do perfil devem manter a ordem completa")
        var migration = try JSONDecoder().decode(CustomizationSnapshot.self, from: data)
        migration.appearance.toolOrder = ["ocr", "removed-tool", "merge", "ocr"]
        preferences.state.toolOrder = migration.appearance.toolOrder
        let migratedOrder = ["ocr", "merge"] + catalogIDs.filter { !["ocr", "merge"].contains($0) }
        try check(preferences.orderedTools().map(\.id) == migratedOrder,"o consumidor deve ignorar IDs antigos e duplicados e anexar novas ferramentas sem trocar identidades")
        try store.saveProfile(name: "Migração", settings: JSONEncoder().encode(migration))
        let migratedProfile = try require(store.profiles.first { $0.name == "Migração" })
        let normalized = try JSONDecoder().decode(CustomizationSnapshot.self, from: migratedProfile.settings)
        try check(normalized.appearance.toolOrder == ["ocr", "merge"],"a normalização validada deve ser gravada no perfil, não descartada por uma nova decodificação")
        try preferences.importData(migratedProfile.settings)
        try check(preferences.orderedTools().map(\.id) == migratedOrder,"o perfil migrado deve resolver IDs para as mesmas ferramentas no catálogo")
        store.deleteProfile(migratedProfile.id)
        try preferences.importData(try require(store.profiles.first?.settings))
        var invalid = try JSONDecoder().decode(CustomizationSnapshot.self,from:data)
        invalid.appearance.accentHex = "#FF0000"
        invalid.shortcuts = PDFShortcutSnapshot(bindings:["tool:merge":.init(key:"q")],disabled:[])
        let stateBefore = preferences.state,zoomBefore = defaults.double(forKey:"readerZoom")
        var invalidRejected = false
        do { try preferences.importData(JSONEncoder().encode(invalid)) } catch { invalidRejected = true }
        try check(invalidRejected && preferences.state == stateBefore && defaults.double(forKey:"readerZoom") == zoomBefore,"importação inválida deve ser atômica")
        var legacy = try JSONSerialization.jsonObject(with:data) as! [String:Any]
        legacy.removeValue(forKey:"shortcuts"); legacy.removeValue(forKey:"output")
        try preferences.importData(JSONSerialization.data(withJSONObject:legacy))
        store.deleteProfile(profileID)
        try check(AdvancedCustomizationStore(defaults:defaults).profiles.isEmpty,"excluir perfil deve persistir sem excluir ajustes atuais")
        print("Advanced customization audit passed: shortcut conflicts, persistence, profiles, ordering and atomic legacy import")
    }
    private static func require<T>(_ value:T?) throws -> T {
        guard let value else { throw PreferenceError.invalid("Valor esperado ausente na auditoria de personalização.") }; return value
    }
}
