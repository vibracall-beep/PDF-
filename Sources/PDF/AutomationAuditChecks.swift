import Foundation
import Darwin

@MainActor enum AutomationAuditChecks {
    static func run() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Automation-Audit-"+UUID().uuidString,isDirectory:true)
        let suite = "PDF.Automation.Audit."+UUID().uuidString
        guard let defaults = UserDefaults(suiteName:suite) else { throw PreferenceError.invalid("Não foi possível isolar a auditoria de automação.") }
        defer { try? FileManager.default.removeItem(at:root); defaults.removePersistentDomain(forName:suite) }
        let input = root.appendingPathComponent("input",isDirectory:true),output = root.appendingPathComponent("output",isDirectory:true)
        try FileManager.default.createDirectory(at:input,withIntermediateDirectories:true)
        try FileManager.default.createDirectory(at:output,withIntermediateDirectories:true)
        func check(_ value:Bool,_ message:String) throws { if !value { throw PreferenceError.invalid("Automação: "+message) } }
        let id = UUID(),stage = UUID()
        let raw:[String:Any] = ["id":id.uuidString,"version":2,"name":"Rotação de auditoria","stages":[["id":stage.uuidString,"operation":"rotate","degrees":90]]]
        let workflow = AutomationWorkflow(id:id,name:"Rotação de auditoria",data:try JSONSerialization.data(withJSONObject:raw))
        let options = try AutomationWorkflowBridge.options(workflow)
        try check(options["batch"] as? Bool == true && (options["steps"] as? [[String:Any]])?.count == 1,"fluxo precisa gerar um lote validado com uma etapa")
        let old = input.appendingPathComponent("existing.pdf")
        let original = Data("%PDF-1.7\nexisting audit bytes\n%%EOF".utf8)
        try original.write(to:old)
        let link = input.appendingPathComponent("linked.pdf")
        try FileManager.default.createSymbolicLink(at:link,withDestinationURL:old)
        let subdirectory = input.appendingPathComponent("subfolder",isDirectory:true)
        try FileManager.default.createDirectory(at:subdirectory,withIntermediateDirectories:true)
        try original.write(to:subdirectory.appendingPathComponent("nested.pdf"))
        // Diagnose the former combined assertion without printing private paths:
        // Foundation's enumerated URL may spell /var as /private/var on macOS.
        let foundationFiles = try FileManager.default.contentsOfDirectory(at:input,includingPropertiesForKeys:[.isRegularFileKey,.isSymbolicLinkKey],options:[.skipsHiddenFiles])
        let legacyPaths = try foundationFiles.filter { $0.pathExtension.lowercased() == "pdf" }.compactMap { file -> String? in
            let info = try file.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey])
            guard info.isRegularFile == true,info.isSymbolicLink != true,
                  (try FileManager.default.attributesOfItem(atPath:file.path)[.type]) as? FileAttributeType == .typeRegular else { return nil }
            return file.path
        }
        guard let realFile = realpath(old.path,nil) else { throw POSIXError(.EIO) }
        let canonicalFile = String(cString:realFile); free(realFile)
        print("Automation path diagnostic: legacyCount=\(legacyPaths.count), rawLookup=\(legacyPaths.contains(old.path)), canonicalLookup=\(legacyPaths.contains(canonicalFile)), rootHasAlias=\(old.path != canonicalFile)")
        let first = try AutomationFolderInspector.scan(input)
        try check(first.count == 1,"scan deve incluir exatamente um PDF regular, ignorando links e subpastas")
        try check(Set(first.keys) == [canonicalFile],"a chave do PDF deve usar a identidade canônica da pasta")
        try check(try AutomationFolderInspector.stamp(link) == nil,"stamp não pode seguir a folha simbólica")
        let pdfDirectory = input.appendingPathComponent("directory.pdf",isDirectory:true)
        try FileManager.default.createDirectory(at:pdfDirectory,withIntermediateDirectories:false)
        try original.write(to:pdfDirectory.appendingPathComponent("also-nested.pdf"))
        let broken = input.appendingPathComponent("broken.pdf")
        try FileManager.default.createSymbolicLink(at:broken,withDestinationURL:root.appendingPathComponent("missing.pdf"))
        let fifo = input.appendingPathComponent("pipe.pdf")
        try check(mkfifo(fifo.path,0o600) == 0,"não foi possível criar a fixture de FIFO")
        let hidden = input.appendingPathComponent(".hidden.pdf"); try original.write(to:hidden)
        try check(try AutomationFolderInspector.scan(input) == first,"scan não pode incluir diretório .pdf, PDF aninhado, link quebrado, FIFO ou arquivo oculto")
        let parentAlias = root.appendingPathComponent("parent-alias",isDirectory:true)
        try FileManager.default.createSymbolicLink(at:parentAlias,withDestinationURL:root)
        let aliasedInput = parentAlias.appendingPathComponent("input",isDirectory:true)
        let aliasedScan = try AutomationFolderInspector.scan(aliasedInput)
        try check(aliasedScan == first,"aliases de ancestrais devem produzir as mesmas chaves e stamps")
        var aliasTracker = AutomationArrivalTracker(baseline:aliasedScan)
        for _ in 0..<3 { try check(aliasTracker.observe(first).isEmpty,"alternar a grafia canônica não pode reenfileirar a baseline") }
        let directoryLink = root.appendingPathComponent("linked-input",isDirectory:true)
        try FileManager.default.createSymbolicLink(at:directoryLink,withDestinationURL:input)
        var linkedRootRejected = false
        do { _ = try AutomationFolderInspector.scan(directoryLink) } catch { linkedRootRejected = true }
        try check(linkedRootRejected,"a pasta selecionada não pode ser um link simbólico final")
        let switched = input.appendingPathComponent("switched.pdf")
        try original.write(to:switched)
        try check(try AutomationFolderInspector.stamp(switched) != nil,"a folha inicial deve ser regular")
        try FileManager.default.removeItem(at:switched)
        try FileManager.default.createSymbolicLink(at:switched,withDestinationURL:old)
        try check(try AutomationFolderInspector.stamp(switched) == nil && AutomationFolderInspector.scan(input) == first,"trocar a folha regular por link não pode seguir seu destino")
        let cancelledScan = Task { try AutomationFolderInspector.scan(input) }
        cancelledScan.cancel()
        var cancellationObserved = false
        do { _ = try await cancelledScan.value } catch is CancellationError { cancellationObserved = true }
        try check(cancellationObserved,"uma varredura cancelada não pode retornar uma lista de trabalho")
        var overlapRejected = false
        do { try AutomationFolderInspector.validate(input:root,output:output) } catch { overlapRejected = true }
        try check(overlapRejected,"entrada e saída sobrepostas devem ser recusadas")
        let coordinator = AutomationCoordinator(defaults:defaults)
        try coordinator.add(name:"Regra de auditoria",input:input,output:output,workflow:workflow)
        var duplicateAliasRejected = false
        do { try coordinator.add(name:"Alias da mesma pasta",input:aliasedInput,output:output,workflow:workflow) } catch { duplicateAliasRejected = true }
        try check(duplicateAliasRejected && coordinator.rules.count == 1,"um alias da mesma entrada não pode criar outra regra")
        guard let ruleID = coordinator.rules.first?.id else { throw PreferenceError.invalid("Regra de auditoria ausente.") }
        try check(coordinator.rules.first?.enabled == false,"criar regra jamais deve ativá-la")
        await coordinator.scanNow(); await coordinator.scanNow(); await coordinator.scanNow()
        try check(coordinator.pendingCount == 0,"regra desativada não pode enfileirar documentos")
        await coordinator.setEnabled(true,id:ruleID)
        await coordinator.scanNow(); await coordinator.scanNow(); await coordinator.scanNow()
        try check(coordinator.pendingCount == 0,"ativação deve ignorar todos os documentos existentes")
        let newFile = input.appendingPathComponent("arrival.pdf")
        try original.write(to:newFile)
        await coordinator.scanNow(); await coordinator.scanNow()
        try check(coordinator.pendingCount == 0,"arquivo ainda não estável não pode entrar na fila")
        try (original+Data("\nchanged".utf8)).write(to:newFile)
        await coordinator.scanNow(); await coordinator.scanNow()
        try check(coordinator.pendingCount == 0,"alterar arquivo deve reiniciar a estabilização")
        await coordinator.scanNow()
        try check(coordinator.pendingCount == 1,"arquivo estável deve entrar uma única vez")
        await coordinator.scanNow(); try check(coordinator.pendingCount == 1,"scan repetido não pode duplicar trabalho")
        await coordinator.setEnabled(false,id:ruleID)
        try check(coordinator.pendingCount == 0 && coordinator.rules.first?.enabled == false,"pausar deve descartar a fila ainda não iniciada")
        await coordinator.setEnabled(true,id:ruleID)
        await coordinator.scanNow(); await coordinator.scanNow(); await coordinator.scanNow()
        try check(coordinator.pendingCount == 0,"reativação não pode repetir chegadas anteriores")
        let reopened = AutomationCoordinator(defaults:defaults)
        try check(reopened.rules.first?.enabled == true,"ativação escolhida deve persistir")
        await reopened.setEnabled(true,id:ruleID)
        await reopened.scanNow(); await reopened.scanNow(); await reopened.scanNow()
        try check(reopened.pendingCount == 0,"reinício deve estabelecer nova baseline sem replay")
        // Quit cancellation pauses scheduling without silently changing the
        // user's opt-in. A refused quit resumes the same stable-arrival state.
        let resumedFile = input.appendingPathComponent("arrival-after-refused-quit.pdf")
        ApplicationWork.cancelAll()
        do {
            try original.write(to: resumedFile)
            await coordinator.scanNow(); await coordinator.scanNow(); await coordinator.scanNow()
            try check(coordinator.pendingCount == 0 && coordinator.rules.first?.enabled == true,
                      "encerrar deve suspender a fila sem desativar a preferência da regra")
        } catch { ApplicationWork.resumeAcceptingWork(); throw error }
        ApplicationWork.resumeAcceptingWork()
        await coordinator.scanNow(); await coordinator.scanNow(); await coordinator.scanNow()
        try check(coordinator.pendingCount == 1 && coordinator.rules.first?.enabled == true,
                  "recusar a saída deve retomar chegadas estáveis sem repetir arquivos antigos")
        await coordinator.setEnabled(false, id: ruleID)
        let unchanged = try Data(contentsOf:old)
        try check(unchanged == original && FileManager.default.contentsOfDirectory(atPath:output.path).isEmpty,"planejamento e estabilização não podem alterar originais nem publicar saídas")
        var protected = raw; protected["stages"] = [["id":stage.uuidString,"operation":"protect"]]
        var rejected = false
        do { _ = try AutomationWorkflowBridge.options(.init(id:id,name:workflow.name,data:JSONSerialization.data(withJSONObject:protected))) } catch { rejected = true }
        try check(rejected,"fluxos que exigem senha não podem ser automatizados")
        print("Automation audit passed: explicit opt-in, existing-file baseline, stable arrivals, deduplication, pause, restart, links and password refusal")
    }
}
