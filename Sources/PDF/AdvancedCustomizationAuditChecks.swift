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
        preferences.moveTool("ocr",before:"merge")
        preferences.moveSidebar("Fluxos",before:"Leitor")
        defaults.set("{original} · revisão",forKey:"outputFilenameTemplate")
        defaults.set("/tmp/PDF-Audit-Output",forKey:"outputDirectory")
        defaults.set(false,forKey:"readerAutoScale")
        defaults.set(1.75,forKey:"readerZoom")
        let data = try preferences.exportData()
        try store.saveProfile(name:"Revisão",settings:data)
        let profileID = try require(store.profiles.first?.id)
        preferences.state.accentHex = "#AABBCC"; preferences.state.hiddenTools = []
        defaults.set("Outro",forKey:"outputFilenameTemplate"); defaults.set(2.5,forKey:"readerZoom")
        try preferences.importData(try require(store.profiles.first?.settings))
        try check(preferences.state.accentHex == "#007AFF" && preferences.state.hiddenTools == ["ocr"],"perfil deve restaurar aparência e visibilidade")
        try check(preferences.orderedTools().first?.id == "ocr","reordenação deve persistir no perfil")
        try check(preferences.state.sidebar.first(where:{$0.id == "Início"})?.visible == true,"reordenação não pode ocultar Início")
        try check(defaults.double(forKey:"readerZoom") == 1.75 && defaults.string(forKey:"outputFilenameTemplate") == "{original} · revisão","perfil deve restaurar leitura e nomes de saída")
        let reloaded = AdvancedCustomizationStore(defaults:defaults)
        try check(reloaded.profiles.first?.id == profileID,"perfis devem persistir sem alterar identidade")
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
