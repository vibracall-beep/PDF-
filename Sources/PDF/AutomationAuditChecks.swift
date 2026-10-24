import Foundation

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
        let first = try AutomationFolderInspector.scan(input)
        try check(first.count == 1 && first[old.path] != nil,"scan deve ignorar links e subpastas")
        var overlapRejected = false
        do { try AutomationFolderInspector.validate(input:root,output:output) } catch { overlapRejected = true }
        try check(overlapRejected,"entrada e saída sobrepostas devem ser recusadas")
        let coordinator = AutomationCoordinator(defaults:defaults)
        try coordinator.add(name:"Regra de auditoria",input:input,output:output,workflow:workflow)
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
        let unchanged = try Data(contentsOf:old)
        try check(unchanged == original && FileManager.default.contentsOfDirectory(atPath:output.path).isEmpty,"planejamento e estabilização não podem alterar originais nem publicar saídas")
        var protected = raw; protected["stages"] = [["id":stage.uuidString,"operation":"protect"]]
        var rejected = false
        do { _ = try AutomationWorkflowBridge.options(.init(id:id,name:workflow.name,data:JSONSerialization.data(withJSONObject:protected))) } catch { rejected = true }
        try check(rejected,"fluxos que exigem senha não podem ser automatizados")
        print("Automation audit passed: explicit opt-in, existing-file baseline, stable arrivals, deduplication, pause, restart, links and password refusal")
    }
}
