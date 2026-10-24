import Foundation
import AppKit
import PDFKit

/// Uses controlled continuations, not timing assumptions or synthetic success,
/// to prove that a cancelled worker remains owned until its cleanup completes.
@MainActor enum ApplicationTaskAuditChecks {
    static func run() async throws {
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw PreferenceError.invalid("Encerramento de tarefas: " + message) }
        }
        guard ApplicationWork.isAcceptingWork else { throw PreferenceError.invalid("A auditoria exige um aplicativo que aceite tarefas.") }
        let deadline = ProcessInfo.processInfo.systemUptime + 10
        while ApplicationWork.activeCount > 0, ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(for: .milliseconds(25))
        }
        try require(ApplicationWork.activeCount == 0, "trabalhos anteriores ainda não confirmaram cleanup; a auditoria não pode ignorá-los")
        let baseline = ApplicationWork.activeCount
        defer { ApplicationWork.resumeAcceptingWork() }
        let entered = ApplicationAuditGate(), release = ApplicationAuditGate()
        let cancelled = ApplicationAuditFlag(), cleaned = ApplicationAuditFlag()
        let task = ApplicationTask.start(cancel: { cancelled.set() }) {
            await entered.open()
            await release.wait()
            // A cancellation-insensitive callback may finish later. Until this
            // final cleanup happens, its ticket must remain visible to quit.
            cleaned.set()
        }
        await entered.wait()
        let registered = ApplicationWork.activeCount == baseline + 1
        ApplicationWork.cancelAll()
        let resourceCancelled = cancelled.value && !ApplicationWork.isAcceptingWork
        let retainedUntilCleanup = !cleaned.value && ApplicationWork.activeCount == baseline + 1
        await release.open()
        await task.value
        try require(registered, "a tarefa em andamento não foi registrada")
        try require(resourceCancelled, "o cancelamento não chegou ao recurso da tarefa")
        try require(retainedUntilCleanup, "cancelar não pode ser confundido com cleanup concluído")
        try require(cleaned.value && ApplicationWork.activeCount == baseline, "o registro deve terminar somente depois do cleanup")

        let cancelledBeforeStart = ApplicationAuditFlag(), observedCancelledTask = ApplicationAuditFlag()
        let rejected = ApplicationTask.start(cancel: { cancelledBeforeStart.set() }) {
            if Task.isCancelled { observedCancelledTask.set() }
        }
        await rejected.value
        try require(cancelledBeforeStart.value && observedCancelledTask.value,
                    "cancelar antes de instalar a Task deve cancelar também seu handle")
        try require(ApplicationWork.activeCount == baseline, "uma tarefa recusada não pode deixar registro órfão")
        var ranWhileStopping = false
        do { _ = try await ApplicationTask.run { ranWhileStopping = true; return true } }
        catch is CancellationError { }
        try require(!ranWhileStopping, "uma operação externa não pode começar durante o encerramento")
        ApplicationWork.resumeAcceptingWork()
        let result = try await ApplicationTask.run { 42 }
        try require(result == 42 && ApplicationWork.activeCount == baseline, "recusar a saída deve permitir novas operações e preservar resultados")
        try await sessionChangesDuringTermination()
        ApplicationWork.resumeAcceptingWork()
        try await PagesCleanupAuditChecks.run()
    }

    private static func sessionChangesDuringTermination() async throws {
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw PreferenceError.invalid("Sessão durante encerramento: " + message) }
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-quit-state-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let suite = "PDF.QuitState." + UUID().uuidString
        guard let defaults = UserDefaults(suiteName: suite) else { throw PreferenceError.invalid("A auditoria não pôde isolar as preferências.") }
        defer {
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: directory)
            ApplicationWork.resumeAcceptingWork()
        }
        let document = PDFDocument(), page = PDFPage()
        page.setBounds(CGRect(x: 0, y: 0, width: 200, height: 300), for: .mediaBox)
        let field = PDFAnnotation(bounds: CGRect(x: 20, y: 100, width: 140, height: 24), forType: .widget, withProperties: nil)
        field.widgetFieldType = .text; field.fieldName = "shutdown-state"; field.widgetStringValue = "antes"
        page.addAnnotation(field); document.insert(page, at: 0)
        let original = try NativePDFSerialization.serialize(document: document)
        let source = directory.appendingPathComponent("original.pdf")
        try NativeOutput.write(original, to: source)
        let store = RecoveryStore(directory: directory.appendingPathComponent("recovery"))
        let model = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        model.open(url: source); await model.waitForPendingOpen()
        guard let loaded = model.document, let widget = loaded.page(at: 0)?.annotations.first(where: { $0.fieldName == "shutdown-state" }) else {
            throw PreferenceError.invalid("A auditoria não abriu o formulário real.")
        }
        let reader = DrawingPDFView(frame: CGRect(x: 0, y: 0, width: 400, height: 500))
        reader.document = loaded
        if let first = loaded.page(at: 0) { reader.go(to: first) }
        model.pdfView = reader
        // Workspace keeps only a weak reference. Retain the actual reader
        // across every suspension so addNote uses its real current PDF page.
        defer { withExtendedLifetime(reader) {} }
        try require(reader.currentPage === loaded.page(at: 0), "o leitor não apresentou a página da auditoria")
        try model.checkpointRecoveryNow()
        let records = try store.list()
        guard let oldCheckpoint = records.first else { throw PreferenceError.invalid("A recuperação inicial não foi publicada.") }
        model.captureTerminationDecision()
        let cancellation = ApplicationAuditFlag()
        let pending = ApplicationWork.begin { cancellation.set() }
        defer { pending.finish() }
        let waiting = Task { @MainActor in await model.prepareForTermination(externalDeadline: 3) }
        let deadline = ProcessInfo.processInfo.systemUptime + 2
        while !cancellation.value, ProcessInfo.processInfo.systemUptime < deadline { try await Task.sleep(for: .milliseconds(10)) }
        try require(cancellation.value, "a espera de encerramento não foi iniciada")
        widget.widgetStringValue = "alteração-Ω"
        model.addNote("Nota criada durante a espera")
        pending.finish()
        let allowed = await waiting.value
        try require(!allowed && ApplicationWork.isAcceptingWork, "a saída aceitou alterações posteriores à decisão")
        try require(widget.widgetStringValue == "alteração-Ω" && loaded.page(at: 0)?.annotations.contains(where: { $0.contents == "Nota criada durante a espera" }) == true,
                    "a recusa descartou a edição ou a nota em memória")
        try require(try Data(contentsOf: source) == original, "o original foi modificado")
        let oldData = try store.load(oldCheckpoint)
        let oldDocument = try NativePDFSerialization.open(data: oldData)
        try require(oldDocument.page(at: 0)?.annotations.first(where: { $0.fieldName == "shutdown-state" })?.widgetStringValue == "antes",
                    "a recuperação anterior foi perdida durante a recusa")

        try model.checkpointRecoveryNow()
        model.captureTerminationDecision()
        let ready = await model.prepareForTermination(externalDeadline: 3)
        try require(ready, "uma nova decisão estável continuou bloqueada")
        // Simulate an event between the async return and AppKit's synchronous
        // final reply; the delegate's second guard must catch it too.
        model.toggleBookmark()
        try require(!model.authorizeTerminationIfUnchanged() && ApplicationWork.isAcceptingWork,
                    "a autorização final não revalidou o estado após o await")
        try model.checkpointRecoveryNow()
        model.captureTerminationDecision()
        let finalReady = await model.prepareForTermination(externalDeadline: 3)
        try require(finalReady && model.authorizeTerminationIfUnchanged(), "a recusa deixou o aplicativo permanentemente bloqueado")
    }
}

private actor ApplicationAuditGate {
    private var opened = false
    private var waiting: [CheckedContinuation<Void, Never>] = []
    func wait() async {
        if opened { return }
        await withCheckedContinuation { waiting.append($0) }
    }
    func open() {
        opened = true
        let callbacks = waiting; waiting.removeAll()
        for callback in callbacks { callback.resume() }
    }
}

private final class ApplicationAuditFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var flag = false
    var value: Bool { lock.lock(); defer { lock.unlock() }; return flag }
    func set() { lock.lock(); flag = true; lock.unlock() }
}
