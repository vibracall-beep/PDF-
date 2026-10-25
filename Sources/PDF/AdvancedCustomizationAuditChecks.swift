import Foundation
import AppKit
import PDFKit
import SwiftUI

@MainActor enum AdvancedCustomizationAuditChecks {
    static func run() async throws {
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
        let requiredExpansions: Set<String> = ["content-editor", "conversion-audit", "ocr-review", "library",
            "document-history", "collection-research", "sync-library", "accessibility-edit", "signature-request",
            "print-preflight", "print-prepare", "pdfx", "bates", "dossier", "stamp", "measure", "automation"]
        try check(requiredExpansions.isDisjoint(with: originalTools) &&
                  originalTools.union(requiredExpansions).isSubset(of: Set(catalogIDs)),
                  "todas as 71 ferramentas entregues devem permanecer disponíveis após a ampliação")
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
        try menuAndToolbarRoundTrip()
        try await readerProfileRoundTrip()
        print("Advanced customization audit passed: shortcut conflicts, persistence, profiles, menu/toolbar ordering, hidden-command reachability and atomic legacy import")
    }
    private static func menuAndToolbarRoundTrip() throws {
        let suite = "PDF.MenuBars.Audit." + UUID().uuidString
        let defaults = try require(UserDefaults(suiteName:suite))
        defer { defaults.removePersistentDomain(forName:suite) }
        let preferences = AppearancePreferences(defaults:defaults), store = preferences.advanced
        func check(_ value:Bool,_ message:String) throws {
            guard value else { throw PreferenceError.invalid("Menus e barras: " + message) }
        }
        var menu = PDFMenuSnapshot()
        menu.quickTitle = "Minha revisão"
        menu.quickCommands = ["tool:ocr", "action:rotate", "action:save", "tool:library"]
        menu.categoryOrder = Array(AppearanceState.categories.reversed())
        menu.categoryTitles = ["Capturar":"Digitalização local"]
        menu.documentOrder = Array(PDFMenuLayout.documentDefaults.reversed())
        menu.hiddenDocumentCommands = ["action:share", "action:search"]
        menu.actionTitles = ["action:save":"Guardar resultado", "action:share":"Enviar uma cópia"]
        try store.applyMenu(menu)
        try check(AdvancedCustomizationStore(defaults:defaults).menu == menu,"a configuração dos menus não persistiu")
        preferences.state.hiddenTools = ["ocr"]
        preferences.state.hiddenCategories = ["Converter"]
        preferences.state.toolOrder = ["pdfa", "ocr", "merge"]
        let shown = PDFMenuLayout.menuTools(preferences,hidden:false).map(\.id)
        let hidden = PDFMenuLayout.menuTools(preferences,hidden:true).map(\.id)
        try check(Set(shown).isDisjoint(with:Set(hidden)) && Set(shown+hidden) == Set(tools.map(\.id)),
                  "a personalização deve conservar cada ferramenta exatamente uma vez entre menus visíveis e recolhidos")
        try check(shown.first == "merge" && hidden.prefix(2) == ["pdfa","ocr"],"os menus ignoraram a ordem ou visibilidade do catálogo")
        let documentShown = PDFMenuLayout.documentCommands(menu,hidden:false).map(\.id)
        let documentHidden = PDFMenuLayout.documentCommands(menu,hidden:true).map(\.id)
        try check(documentShown == menu.documentOrder.filter { !menu.hiddenDocumentCommands.contains($0) } &&
                  documentHidden == menu.documentOrder.filter { menu.hiddenDocumentCommands.contains($0) },"Documento precisa respeitar ordem e recolhimento sem trocar IDs")
        try check(Set(documentShown+documentHidden) == Set(PDFMenuLayout.documentDefaults),"recolher um comando o removeu de Documento")
        let shortcut = try require(store.binding(for:"action:search"))
        try check(shortcut.normalized == PDFKeyboardBinding(key:"f").normalized,"um comando recolhido perdeu o atalho")
        menu.hiddenDocumentCommands = PDFMenuLayout.documentDefaults
        try store.applyMenu(menu)
        try check(PDFMenuLayout.documentCommands(menu,hidden:false).isEmpty && PDFMenuLayout.documentCommands(menu,hidden:true).count == PDFMenuLayout.documentDefaults.count,
                  "recolher todos os comandos deve manter o submenu completo")
        menu.hiddenDocumentCommands = ["action:share", "action:search"]; try store.applyMenu(menu)
        var reader = ReaderSettingsSnapshot(defaults:defaults)
        reader.toolbarOrder = "save,search,fit,open,zoom,compare,options,customize,sidebar"
        reader.annotationOrder = "bookmark,history,editor,ink,note,highlight"
        reader.hiddenToolbar = "options,sidebar"
        reader.hiddenAnnotations = "ink"
        reader.pinSave = false
        try reader.validate(); reader.apply(to:defaults)
        try check(ReaderBarLayout.visible(reader.toolbarOrder ?? "",hidden:reader.hiddenToolbar,defaults:ReaderBarLayout.primary).map(\.id) ==
                  ["save","search","fit","open","zoom","compare","customize"],"a barra não aplicou a ordem configurada")
        try check(ReaderBarLayout.visible(reader.toolbarOrder ?? "",hidden:reader.hiddenToolbar,defaults:ReaderBarLayout.primary,pinSave:true).map(\.id) ==
                  ["search","fit","open","zoom","compare","customize"],"Salvar fixo apareceu também na área rolável")
        try check(ReaderBarLayout.visible(reader.annotationOrder ?? "",hidden:reader.hiddenAnnotations,defaults:ReaderBarLayout.annotations).map(\.id) ==
                  ["bookmark","history","editor","note","highlight"],"a barra de anotações ignorou visibilidade ou ordem")
        try check(ReaderBarLayout.ordered("search,unknown,search",defaults:ReaderBarLayout.primary).map(\.id) ==
                  ["search"] + ReaderBarLayout.primary.map(\.id).filter { $0 != "search" },"resolver ordem local não conservou controles novos/obrigatórios")
        try check(ReaderBarLayout.visible("",hidden:ReaderBarLayout.primary.map(\.id).joined(separator:","),defaults:ReaderBarLayout.primary).map(\.id) == ["customize"],
                  "uma preferência local alterada tornou Personalizar leitor inacessível")
        let exported = try preferences.exportData()
        try store.saveProfile(name:"Menus e barras",settings:exported)
        let profile = try require(store.profiles.first)
        try store.applyMenu(PDFMenuSnapshot()); preferences.resetReader()
        try preferences.importData(profile.settings)
        try check(store.menu == menu && defaults.string(forKey:"readerToolbarOrder") == reader.toolbarOrder &&
                  defaults.string(forKey:"readerAnnotationOrder") == reader.annotationOrder && !defaults.bool(forKey:"readerPinSave"),
                  "um perfil deixou de restaurar menus e ambas as barras")
        try check(try preferences.exportData() == exported,"a ida e volta alterou os bytes das preferências")
        let baseline = try preferences.exportData(), storedMenu = defaults.data(forKey:AdvancedCustomizationStore.menuKey)
        func rejectMenu(_ modify:(inout PDFMenuSnapshot)->Void) throws {
            var snapshot = try JSONDecoder().decode(CustomizationSnapshot.self,from:baseline)
            snapshot.appearance.fontSize = 18
            var invalid = menu; modify(&invalid); snapshot.menu = invalid
            var rejected = false
            do { try preferences.importData(JSONEncoder().encode(snapshot)) } catch { rejected = true }
            try check(rejected && (try preferences.exportData()) == baseline && defaults.data(forKey:AdvancedCustomizationStore.menuKey) == storedMenu,
                      "uma importação inválida alterou parte das preferências")
        }
        try rejectMenu { $0.quickCommands = ["tool:missing"] }
        try rejectMenu { $0.quickCommands = ["tool:ocr","tool:ocr"] }
        try rejectMenu { $0.documentOrder = ["action:open"] }
        try rejectMenu { $0.hiddenDocumentCommands = ["action:missing"] }
        try rejectMenu { $0.categoryOrder = ["Capturar","Capturar"] }
        try rejectMenu { $0.categoryTitles = ["missing":"Nome"] }
        try rejectMenu { $0.actionTitles = ["tool:ocr":"Renomeado fora do catálogo"] }
        try rejectMenu { $0.actionTitles = ["action:save":"Nome\ninválido"] }
        try rejectMenu { $0.quickTitle = " " }
        for order in ["search,search","unknown",",open","open,"] {
            var snapshot = try JSONDecoder().decode(CustomizationSnapshot.self,from:baseline)
            snapshot.reader.toolbarOrder = order; snapshot.appearance.fontSize = 19
            var rejected = false
            do { try preferences.importData(JSONEncoder().encode(snapshot)) } catch { rejected = true }
            try check(rejected && (try preferences.exportData()) == baseline,"ordem inválida alterou preferências")
        }
        var legacy = try JSONSerialization.jsonObject(with:baseline) as! [String:Any]
        legacy.removeValue(forKey:"menu")
        if var legacyReader = legacy["reader"] as? [String:Any] {
            legacyReader.removeValue(forKey:"toolbarOrder"); legacyReader.removeValue(forKey:"annotationOrder"); legacyReader.removeValue(forKey:"pinSave")
            legacy["reader"] = legacyReader
        }
        try preferences.importData(JSONSerialization.data(withJSONObject:legacy))
        try check(store.menu == menu && defaults.string(forKey:"readerToolbarOrder") == "" && defaults.bool(forKey:"readerPinSave"),
                  "exportação antiga precisa restaurar barras padrão e preservar menus fora do seu escopo")
        preferences.resetReader()
        try check(defaults.object(forKey:"readerToolbarOrder") == nil && defaults.object(forKey:"readerAnnotationOrder") == nil && defaults.object(forKey:"readerPinSave") == nil,
                  "restaurar leitor não removeu as preferências novas")
    }
    private static func readerProfileRoundTrip() async throws {
        let suite = "PDF.ProfileReader.Audit." + UUID().uuidString
        let defaults = try require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(suite, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        defaults.set(false, forKey: "recoveryEnabled")
        defaults.set(1.0, forKey: "readerZoom"); defaults.set(true, forKey: "readerAutoScale")
        defaults.set(1, forKey: "readerMode"); defaults.set("#204060", forKey: "readerPageBackground")
        defaults.set("media", forKey: "readerDisplayBox")
        let preferences = AppearancePreferences(defaults: defaults)
        try preferences.advanced.saveProfile(name: "Leitura automática", settings: preferences.exportData())
        let profile = try require(preferences.advanced.profiles.first)
        defaults.set(1.75, forKey: "readerZoom"); defaults.set(false, forKey: "readerAutoScale")
        defaults.set(0, forKey: "readerMode"); defaults.set("#E8E9EF", forKey: "readerPageBackground")
        defaults.set("crop", forKey: "readerDisplayBox")
        var sources: [(url: URL, data: Data)] = []
        for name in ["principal", "referencia", "novo"] {
            let document = try require(PDFDocument(data: IntelligenceText.PDF("Documento \(name): três páginas para verificar perfis de leitura.")))
            let page = try require(document.page(at: 0))
            page.setBounds(page.bounds(for: .mediaBox).insetBy(dx: 16, dy: 24), for: .cropBox)
            for index in 1...2 { document.insert(try require(page.copy() as? PDFPage), at: index) }
            let data = try require(document.dataRepresentation()), url = directory.appendingPathComponent(name + ".pdf")
            try NativeOutput.write(data, to: url); sources.append((url, data))
        }
        let workspace = Workspace(defaults: defaults, recoveryStore: RecoveryStore(directory: directory.appendingPathComponent("Recovery")), enableRecoveryPolling: false)
        workspace.open(url: sources[0].url); await workspace.waitForPendingOpen()
        let primary = try require(workspace.activeSession)
        workspace.currentPage = 2; workspace.bookmarks = [2]
        workspace.open(url: sources[1].url); await workspace.waitForPendingOpen()
        let reference = try require(workspace.activeSession)
        workspace.currentPage = 3; reference.zoom = 2.1; reference.autoScale = false
        workspace.activateSession(primary.id); workspace.comparisonSessionID = reference.id
        let host = NSHostingView(rootView: ProfileReaderAuditView().environmentObject(workspace).defaultAppStorage(defaults))
        host.frame = NSRect(x: 0, y: 0, width: 1100, height: 700)
        await settle(host)
        func check(_ condition: Bool, _ message: String) throws {
            guard condition else { throw PreferenceError.invalid("Perfil com leitores reais: " + message) }
        }
        func view(for session: PDFDocumentSession) throws -> PDFView {
            try require(pdfViews(in: host).first { $0.document === session.document })
        }
        func verifySessions() throws {
            let first = try view(for: primary), second = try view(for: reference)
            try check(!first.autoScales && abs(Double(first.scaleFactor) - 1.75) < 0.01 &&
                      !second.autoScales && abs(Double(second.scaleFactor) - 2.1) < 0.01,
                      "o perfil ou a troca de abas substituiu o zoom manual de uma sessão aberta")
            try check(primary.page == 2 && reference.page == 3 && primary.bookmarks == [2] &&
                      first.currentPage === primary.document.page(at: 1) && second.currentPage === reference.document.page(at: 2),
                      "a aplicação do perfil perdeu a página ou as marcas de uma das sessões")
            try check(abs(primary.zoom - 1.75) < 0.01 && abs(reference.zoom - 2.1) < 0.01 && !primary.autoScale && !reference.autoScale,
                      "o estado persistido das sessões divergiu dos leitores nativos")
        }
        try verifySessions()
        try preferences.importData(profile.settings); await settle(host)
        try verifySessions()
        for session in [primary, reference] {
            let reader = try view(for: session), color = try require(reader.backgroundColor.usingColorSpace(.sRGB))
            try check(reader.displayMode == .singlePage && reader.displayBox == .mediaBox && abs(color.redComponent - 32.0 / 255) < 0.001 &&
                      abs(color.greenComponent - 64.0 / 255) < 0.001 && abs(color.blueComponent - 96.0 / 255) < 0.001,
                      "preservar a navegação impediu que modo e aparência do perfil fossem aplicados")
        }
        try preferences.importData(profile.settings); await settle(host); try verifySessions()
        workspace.comparisonSessionID = primary.id; workspace.activateSession(reference.id)
        await settle(host); try verifySessions()
        workspace.comparisonSessionID = reference.id; workspace.activateSession(primary.id)
        await settle(host); try verifySessions()
        try check(defaults.double(forKey: "readerZoom") == 1 && defaults.bool(forKey: "readerAutoScale"),
                  "alternar abas sobrescreveu os padrões importados do perfil")
        workspace.open(url: sources[2].url); await workspace.waitForPendingOpen()
        let newSession = try require(workspace.activeSession)
        try check(newSession.zoom == 1 && newSession.autoScale, "uma nova aba ignorou os padrões do perfil")
        await settle(host)
        workspace.activateSession(primary.id); await settle(host); try verifySessions()
        // Use the same action called by the slider and fit button, then a real
        // PDFKit scale notification (as produced by a native gesture/keyboard action).
        workspace.setReaderMagnification(zoom: 2.4, autoScale: false); await settle(host)
        let firstView = try view(for: primary)
        try check(abs(Double(firstView.scaleFactor) - 2.4) < 0.01 && !firstView.autoScales &&
                  defaults.double(forKey: "readerZoom") == 2.4 && !defaults.bool(forKey: "readerAutoScale"),
                  "o controle explícito deixou de ajustar a aba e guardar o padrão")
        firstView.autoScales = false; firstView.scaleFactor = 2.65; await settle(host)
        try check(abs(workspace.currentReaderZoom - 2.65) < 0.01 && !workspace.currentReaderAutoScale &&
                  defaults.double(forKey: "readerZoom") == 2.4, "o zoom nativo não atualizou os controles ou alterou padrões sem comando explícito")
        workspace.setReaderMagnification(autoScale: true); await settle(host)
        try check(firstView.autoScales && workspace.currentReaderAutoScale, "Ajustar deixou de ativar o encaixe automático")
        let fittedZoom = Double(firstView.scaleFactor)
        workspace.setReaderMagnification(autoScale: false); await settle(host)
        try check(!firstView.autoScales && abs(Double(firstView.scaleFactor) - fittedZoom) < 0.01,
                  "desativar Ajustar perdeu o zoom efetivo da janela")
        try AppearancePreferences(defaults: defaults).importData(profile.settings); await settle(host)
        try check(!firstView.autoScales && abs(Double(firstView.scaleFactor) - fittedZoom) < 0.01 &&
                  !reference.autoScale && abs(reference.zoom - 2.1) < 0.01 && defaults.double(forKey: "readerZoom") == 1 && defaults.bool(forKey: "readerAutoScale"),
                  "restaurar um perfil substituiu o estado atual ou perdeu os padrões de novas abas")
        for source in sources { try check(try Data(contentsOf: source.url) == source.data, "a personalização alterou um PDF original") }
    }
    private static func settle(_ host: NSView) async {
        // Drain actual SwiftUI/PDFKit work. No fixed delay or nested run loop.
        for _ in 0..<2 {
            host.layoutSubtreeIfNeeded()
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                DispatchQueue.main.async { continuation.resume() }
            }
        }
        host.layoutSubtreeIfNeeded()
    }
    private static func pdfViews(in view: NSView) -> [PDFView] {
        if let pdf = view as? PDFView { return [pdf] }
        return view.subviews.flatMap { pdfViews(in: $0) }
    }
    private static func require<T>(_ value:T?) throws -> T {
        guard let value else { throw PreferenceError.invalid("Valor esperado ausente na auditoria de personalização.") }; return value
    }
}

private struct ProfileReaderAuditView: View {
    @EnvironmentObject var model: Workspace
    @AppStorage("readerMode") private var mode = 0
    var body: some View {
        HStack(spacing: 0) {
            Reader(mode: mode)
            if let reference = model.sessions.first(where: { $0.id == model.comparisonSessionID && $0.id != model.activeSessionID }) {
                SessionComparisonReader(session: reference, mode: mode)
            }
        }
    }
}
