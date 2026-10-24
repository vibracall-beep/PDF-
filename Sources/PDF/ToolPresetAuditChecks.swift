import Foundation

@MainActor enum ToolPresetAuditChecks {
    static func run() throws {
        func require(_ value:Bool,_ message:String) throws {
            if !value { throw NSError(domain:"PDF.PresetAudit",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
        }
        let suiteName = "PDF.preset-audit." + UUID().uuidString
        guard let defaults = UserDefaults(suiteName:suiteName) else { throw ToolPresetError.invalid }
        defer { defaults.removePersistentDomain(forName:suiteName) }
        let store = ToolPresetStore(defaults:defaults)
        var options = ToolStyleOptions(); options.dpi = 300; options.transparentPNG = true
        let id = try store.save(name:"Imagens transparentes",toolID:"png",options:options)
        try store.setDefault(id,for:"png")
        let restored = ToolPresetStore(defaults:defaults)
        try require(restored.defaultOptions(for:"png") == options,"A configuração padrão não persistiu entre instâncias.")
        options.dpi = 144
        let updatedID = try restored.save(name:"Imagens transparentes",toolID:"png",options:options)
        try require(updatedID == id && restored.entries(for:"png").count == 1,"Atualizar uma configuração duplicou o registro ou perdeu sua identidade.")
        let exported = try restored.exported(id)
        let object = try JSONSerialization.jsonObject(with:exported) as? [String:Any]
        let savedOptions = object?["options"] as? [String:Any]
        let sensitive = Set(["password","new_password","second_password","input_passwords","text","replacement","inputs","font_file","pages","image","values"])
        try require(sensitive.isDisjoint(with:Set(savedOptions?.keys.map { $0 } ?? [])),"Configurações reutilizáveis incluíram conteúdo, caminhos ou senhas.")
        var foreignRejected = false
        do { _ = try restored.importPreset(exported,for:"jpg") } catch { foreignRejected = true }
        try require(foreignRejected,"Importação aceitou configuração de outra ferramenta.")
        var altered = try JSONSerialization.jsonObject(with:exported) as! [String:Any]
        var alteredOptions = altered["options"] as! [String:Any]
        alteredOptions["dpi"] = -100
        altered["options"] = alteredOptions
        var invalidRejected = false
        do { _ = try restored.importPreset(JSONSerialization.data(withJSONObject:altered),for:"png") } catch { invalidRejected = true }
        try require(invalidRejected && restored.defaultOptions(for:"png")?.dpi == 144,"Uma importação inválida alterou a configuração anterior.")
        try restored.remove(id)
        let removed = ToolPresetStore(defaults:defaults)
        try require(removed.entries(for:"png").isEmpty && removed.defaultOptions(for:"png") == nil,"Excluir configuração deixou referência padrão inválida.")
        var structured = ToolStyleOptions()
        structured.structureSource = "ocr"; structured.structureDPI = 240; structured.structureMinimumConfidence = 52
        structured.tableDetection = "aligned"
        structured.structureDeskew = true
        let scanID = try restored.save(name:"Digitalizações",toolID:"word",options:structured)
        let scanData = try restored.exported(scanID)
        let roundTrip = try JSONDecoder().decode(ToolPreset.self,from:scanData)
        try require(roundTrip.options == structured,"Os parâmetros de OCR não sobreviveram à exportação e leitura do preset.")
        var legacyObject = try JSONSerialization.jsonObject(with:scanData) as! [String:Any]
        var legacyOptions = legacyObject["options"] as! [String:Any]
        for key in ["structureSource","structureDPI","structureMinimumConfidence","tableDetection","structureDeskew"] { legacyOptions.removeValue(forKey:key) }
        legacyObject["options"] = legacyOptions
        legacyObject["toolID"] = "png" // A tool that already supported presets before this change.
        let legacy = try JSONDecoder().decode(ToolPreset.self,from:JSONSerialization.data(withJSONObject:legacyObject))
        try legacy.validate()
        try require(legacy.options.structureSource == nil && legacy.options.structureDPI == nil && legacy.options.structureMinimumConfidence == nil && legacy.options.tableDetection == nil && legacy.options.structureDeskew == nil,"Um preset anterior ao OCR estruturado deixou de ser compatível.")
        for toolID in ["word","excel","markdown","forms","fill-forms"] { try structured.validate(toolID:toolID) }
        for invalidCase in 0..<5 {
            var invalid = structured
            if invalidCase == 0 { invalid.structureSource = "unsupported" }
            if invalidCase == 1 { invalid.structureDPI = 119 }
            if invalidCase == 2 { invalid.structureMinimumConfidence = 101 }
            if invalidCase == 3 { invalid.structureMinimumConfidence = .nan }
            if invalidCase == 4 { invalid.tableDetection = "unsupported" }
            var rejected = false
            do { try invalid.validate(toolID:"forms") } catch { rejected = true }
            try require(rejected,"Um parâmetro OCR inválido foi aceito no preset.")
        }
        let structuredJSON = try JSONSerialization.jsonObject(with:scanData) as! [String:Any]
        let structuredKeys = Set((structuredJSON["options"] as! [String:Any]).keys)
        try require(Set(["fields","label","detectedLabel","detectionSummary","rows","words","certificate_password"]).isDisjoint(with:structuredKeys),"O preset de OCR persistiu conteúdo extraído ou credenciais.")
        defaults.set(Data("configuração danificada".utf8),forKey:"PDF.toolPresets.v1")
        let corrupted = ToolPresetStore(defaults:defaults)
        var refusedCorruptOverwrite = false
        do { _ = try corrupted.save(name:"Nova",toolID:"png",options:options) } catch { refusedCorruptOverwrite = true }
        try require(corrupted.loadFailed && refusedCorruptOverwrite && corrupted.originalData() == Data("configuração danificada".utf8),"Biblioteca inválida foi sobrescrita sem recuperação explícita.")
        corrupted.resetLibrary()
        _ = try corrupted.save(name:"Recuperada",toolID:"png",options:options)
        try require(!corrupted.loadFailed && corrupted.entries(for:"png").count == 1,"Restauração explícita não recuperou a biblioteca.")
        print("Tool preset audit passed: persistence, defaults, update, privacy, import validation, legacy OCR compatibility, OCR bounds, removal and recovery")
    }
}
