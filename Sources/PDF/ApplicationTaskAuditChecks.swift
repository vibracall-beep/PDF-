import Foundation

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
