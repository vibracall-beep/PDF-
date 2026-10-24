import Foundation

@MainActor enum SettingsExchangeAuditChecks {
    static func run() async throws {
        let suite = "PDF.SettingsExchange.Audit."+UUID().uuidString
        guard let defaults = UserDefaults(suiteName:suite) else { throw PreferenceError.invalid("Falha ao isolar ajustes.") }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-SettingsExchange-"+UUID().uuidString,isDirectory:true)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        defer { defaults.removePersistentDomain(forName:suite); try? FileManager.default.removeItem(at:folder) }
        func check(_ value:Bool,_ detail:String) throws { if !value { throw PreferenceError.invalid("Troca de ajustes: "+detail) } }
        let preferences = AppearancePreferences(defaults:defaults),store = preferences.advanced
        try store.saveProfile(name:"Revisão",settings:preferences.exportData())
        let initial = try JSONDecoder().decode(PDFWorkspaceProfilesSnapshot.self,from:store.exportProfiles())
        var incoming = initial
        guard var profile = incoming.profiles.first else { throw PreferenceError.invalid("Perfil ausente.") }
        var object = try JSONSerialization.jsonObject(with:profile.settings) as! [String:Any]
        var appearance = object["appearance"] as! [String:Any]; appearance["accentHex"] = "#112233"; object["appearance"] = appearance
        object["password"] = "must-never-be-exported"
        profile.settings = try JSONSerialization.data(withJSONObject:object); incoming.profiles = [profile]
        let bytes = try JSONEncoder().encode(incoming)
        try store.importProfiles(bytes,policy:.keepBoth)
        try check(store.profiles.count == 2 && Set(store.profiles.map(\.id)).count == 2,"conflito deve manter ambas as identidades quando solicitado")
        try check(Set(store.profiles.map(\.name)).count == 2,"perfis conflitantes precisam de nomes distintos")
        let exported = try AdvancedCustomizationStore.decodeProfiles(store.exportProfiles())
        for item in exported.profiles {
            let value = try JSONSerialization.jsonObject(with:item.settings) as! [String:Any]
            try check(value["password"] == nil,"campos desconhecidos não podem escapar por Data em base64")
        }
        try store.importProfiles(bytes,policy:.replaceMatchingIdentifiers)
        try check(store.profiles.count == 2 && store.profiles.contains(where:{$0.id == profile.id && $0.settings != initial.profiles[0].settings}),"substituição explícita deve atingir apenas o identificador correspondente")
        let currentAppearance = preferences.state
        _ = try store.exportProfiles()
        try check(preferences.state == currentAppearance,"transferir perfis não deve aplicá-los")
        let document = folder.appendingPathComponent("source.pdf")
        try MacBenchmark.fixture(pages:3,to:document)
        let identity = try await Task.detached { try ReadingSourceIdentity.read(document,cancellation:NativeCancellation()) }.value
        let model = Workspace(defaults:defaults,recoveryStore:RecoveryStore(directory:folder.appendingPathComponent("recovery")),enableRecoveryPolling:false)
        model.open(url:document); await model.waitForPendingOpen()
        guard let id = model.activeSessionID else { throw PreferenceError.invalid("Sessão de teste ausente.") }
        let original = try Data(contentsOf:document)
        try model.applyImportedReadingState(bookmarks:[1,3],page:nil,zoom:nil,autoScale:nil,expectedSessionID:id,source:identity,expectedHash:identity.sha256)
        try check(model.bookmarks == [1,3] && model.currentPage == 1,"unir marcadores sem posição não pode navegar")
        try model.applyImportedReadingState(bookmarks:[2],page:2,zoom:1.75,autoScale:false,expectedSessionID:id,source:identity,expectedHash:identity.sha256)
        try check(model.bookmarks == [2] && model.currentPage == 2 && model.activeSession?.zoom == 1.75 && model.activeSession?.autoScale == false,"restauração explícita deve aplicar estado completo")
        var rejected = false
        do { try model.applyImportedReadingState(bookmarks:[1],page:1,zoom:1,autoScale:true,expectedSessionID:UUID(),source:identity,expectedHash:identity.sha256) } catch { rejected = true }
        try check(rejected && model.bookmarks == [2],"troca de aba deve impedir aplicação tardia")
        rejected = false
        do { try model.applyImportedReadingState(bookmarks:[1],page:nil,zoom:nil,autoScale:nil,expectedSessionID:id,source:identity,expectedHash:String(repeating:"0",count:64)) } catch { rejected = true }
        try check(rejected && model.bookmarks == [2],"hash de outro documento deve ser recusado")
        rejected = false
        do { try model.applyImportedReadingState(bookmarks:[4],page:nil,zoom:nil,autoScale:nil,expectedSessionID:id,source:identity,expectedHash:identity.sha256) } catch { rejected = true }
        try check(rejected && model.bookmarks == [2],"páginas inexistentes devem ser recusadas atomicamente")
        try check(try Data(contentsOf:document) == original,"importar estado de leitura não pode alterar PDF")
        let handle = try FileHandle(forWritingTo:document); try handle.seekToEnd(); try handle.write(contentsOf:Data("\n% changed".utf8)); try handle.close()
        try check(!identity.stillMatchesFile(),"alteração dos bytes deve invalidar identidade anterior")
        rejected = false
        do { try model.applyImportedReadingState(bookmarks:[1],page:nil,zoom:nil,autoScale:nil,expectedSessionID:id,source:identity,expectedHash:identity.sha256) } catch { rejected = true }
        try check(rejected && model.bookmarks == [2],"arquivo alterado durante a verificação não pode receber marcadores")
        model.cancelDocumentOpenings(); model.cancelSearch()
        print("Settings exchange audit passed: explicit conflict policy, canonical profiles, SHA-bound bookmarks, session race and unchanged PDF bytes")
    }
}
