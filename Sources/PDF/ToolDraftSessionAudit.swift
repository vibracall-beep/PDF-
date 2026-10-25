import SwiftUI
import AppKit
import PDFKit
import CryptoKit

/// Exercises a real inspected PDF and destroys/recreates the hosting hierarchy.
/// The text restored in NSTextView is compared byte-for-byte with the draft.
@MainActor enum ToolDraftSessionAudit {
    static func run() async throws {
        func require(_ value:Bool,_ message:String) throws {
            guard value else { throw AdvancedDocumentValidation.failure("Sessão das ferramentas: "+message) }
        }
        let suite = "PDF.ToolDraftAudit."+UUID().uuidString
        guard let defaults = UserDefaults(suiteName:suite) else { throw AdvancedDocumentValidation.failure("Suíte de auditoria indisponível.") }
        defer { defaults.removePersistentDomain(forName:suite) }
        defaults.set(false,forKey:"recoveryEnabled")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(suite,isDirectory:true)
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:false,attributes:[.posixPermissions:0o700])
        defer { try? FileManager.default.removeItem(at:directory) }
        let original = try fixture()
        let source = directory.appendingPathComponent("revisao.pdf")
        try NativeOutput.write(original,to:source)
        let model = Workspace(defaults:defaults,recoveryStore:RecoveryStore(directory:directory.appendingPathComponent("Recovery")),enableRecoveryPolling:false)
        defer { model.toolDrafts.dispose(model:model) }
        model.open(url:source); await model.waitForPendingOpen()
        try require(model.document?.pageCount == 2,"a origem real não abriu no leitor")
        let session:ContentEditorSession = model.toolDrafts.session(id:"content-editor") { ContentEditorSession() }
        try require(session.controller.load(model:model,ocr:false),"a inspeção real não iniciou")
        let deadline = ProcessInfo.processInfo.systemUptime+30
        while session.controller.working {
            try Task.checkCancellation()
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw AdvancedDocumentValidation.failure("A inspeção da sessão excedeu o prazo: "+session.controller.status) }
            try await Task.sleep(for:.milliseconds(25))
        }
        guard let content = session.controller.content,let preview = session.controller.preview,
              let first = content.objects.first(where:{ $0.page == 1 && $0.kind == "text" && $0.editable }),
              let second = content.objects.first(where:{ $0.page == 2 && $0.kind == "text" && $0.editable }) else {
            let findings = session.controller.content?.objects.prefix(12).map {
                "\($0.kind) página \($0.page): \($0.limitations.joined(separator:", "))"
            }.joined(separator:"; ") ?? "sem resultado"
            throw AdvancedDocumentValidation.failure("A inspeção não publicou os objetos reais: "+session.controller.status+" · "+findings)
        }
        let hash = SHA256.hash(data:original).map { String(format:"%02x",$0) }.joined()
        try require(content.source_sha256 == hash,"a inspeção não corresponde à origem aberta")
        let asset = try await session.controller.stageAsset(source,maximumBytes:67_108_864)
        var prepared = ContentEditDraft(first); prepared.text = "Primeira página preparada"
        try session.buffer.prepare(prepared,for:first,in:content)
        var pending = ContentEditDraft(second); pending.text = "Rascunho persistido e\u{301} · segunda página"
        session.buffer.update(pending,for:second)
        session.page = 2; session.selection = second.id; session.draft = pending
        let preferences = AppearancePreferences(defaults:defaults); preferences.state.animationsEnabled = false
        let window = NSWindow(contentRect:NSRect(x:0,y:0,width:1100,height:850),styleMask:[.titled],backing:.buffered,defer:false)
        window.isReleasedWhenClosed = false
        defer { window.orderOut(nil); window.contentView = nil; window.close() }
        func makeHost() -> NSHostingView<AnyView> {
            let host = NSHostingView(rootView:AnyView(AdvancedContentEditorView().environmentObject(model).environmentObject(preferences).defaultAppStorage(defaults)))
            host.frame = NSRect(x:0,y:0,width:1100,height:850)
            return host
        }
        var host:NSHostingView<AnyView>? = makeHost()
        window.contentView = host; window.orderFront(nil)
        try await waitForText(pending.text,in:window)
        // Retain the old host until the new one exists: a freed allocation can
        // reuse the same address and falsely fail an ObjectIdentifier check.
        let oldHost = host!
        // SwiftUI removes the editor, then a different hosting tree opens it.
        host?.rootView = AnyView(Text("Outra ferramenta")); await settle(window)
        window.contentView = NSView(); host = nil; await settle(window)
        model.section = "Início"
        var modified = original; modified.append(Data("\n% external revision\n".utf8))
        try modified.write(to:source,options:.atomic)
        host = makeHost(); window.contentView = host
        try await waitForText(pending.text,in:window)
        let resumed:ContentEditorSession = model.toolDrafts.session(id:"content-editor") { ContentEditorSession() }
        try require(host! !== oldHost && resumed === session,"recriar a interface criou outra sessão")
        try require(resumed.page == 2 && resumed.selection == second.id && resumed.controller.preview === preview &&
                    resumed.controller.content?.source_sha256 == hash,"navegação substituiu página, seleção ou a revisão privada")
        try require(resumed.buffer.prepared[first.id]?.text == prepared.text && resumed.buffer.value(for:second).text.utf8.elementsEqual(pending.text.utf8),
                    "a interface recriada perdeu alterações preparadas ou normalizou os rascunhos")
        try require(FileManager.default.fileExists(atPath:asset.path) && (try Data(contentsOf:asset)) == original,
                    "a desmontagem da interface apagou o recurso privado ainda necessário")
        try require(model.toolDrafts.unsavedTitles.count == 1,"a saída não detectou a revisão não exportada")
        model.captureTerminationDecision()
        pending.text += " · edição tardia"; session.draft = pending; session.buffer.update(pending,for:second)
        try require(!model.authorizeTerminationIfUnchanged(),"a saída foi autorizada depois de uma alteração tardia do rascunho")
        try session.buffer.prepareAll(in:content)
        session.didExport(try session.planIdentity())
        try require(model.toolDrafts.unsavedTitles.isEmpty,"o recibo da revisão exportada não retirou o aviso de trabalho pendente")
        model.toolDrafts.dispose(model:model)
        try require(!FileManager.default.fileExists(atPath:asset.path) && session.controller.preview == nil,
                    "a limpeza final não encerrou a captura privada")
        try require(try Data(contentsOf:source) == modified,"a sessão modificou a origem externa")
        print("Tool draft session audit passed: real inspection, recreated NSTextView, source binding, late-edit refusal and private cleanup")
    }
    private static func textViews(_ view:NSView) -> [NSTextView] {
        (view as? NSTextView).map { [$0] } ?? view.subviews.flatMap(textViews)
    }
    private static func waitForText(_ value:String,in window:NSWindow) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime+5
        while true {
            await settle(window)
            if let content = window.contentView,textViews(content).contains(where:{ $0.string.utf8.elementsEqual(value.utf8) }) { return }
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw AdvancedDocumentValidation.failure("O TextEditor real não restaurou os bytes do rascunho.") }
            try await Task.sleep(for:.milliseconds(20))
        }
    }
    private static func settle(_ window:NSWindow) async {
        window.contentView?.layoutSubtreeIfNeeded()
        await withCheckedContinuation { (continuation:CheckedContinuation<Void,Never>) in DispatchQueue.main.async { continuation.resume() } }
        window.contentView?.layoutSubtreeIfNeeded()
    }
    private static func fixture() throws -> Data {
        let data = NSMutableData()
        var box = CGRect(x:0,y:0,width:500,height:650)
        guard let consumer = CGDataConsumer(data:data as CFMutableData),let context = CGContext(consumer:consumer,mediaBox:&box,nil) else {
            throw AdvancedDocumentValidation.failure("Não foi possível preparar a origem da auditoria.")
        }
        for page in 1...2 {
            context.beginPDFPage(nil)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext:context,flipped:false)
            ("Página \(page) original preservada" as NSString).draw(at:CGPoint(x:40,y:500),withAttributes:[.font:NSFont.systemFont(ofSize:14),.foregroundColor:NSColor.black])
            NSGraphicsContext.restoreGraphicsState(); context.endPDFPage()
        }
        context.closePDF(); return data as Data
    }
}
