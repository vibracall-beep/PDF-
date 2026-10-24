import Foundation
import Darwin
import PDFKit

/// Real child processes and disposable files; this proves the owned process
/// protocol, not cleanup of third-party programs that escape their own groups.
@MainActor enum OwnedChildProcessAudit {
    static let workerArgument = "--owned-child-signal-audit"
    nonisolated static func handleCommandLineIfNeeded() -> Bool {
        guard CommandLine.arguments.contains("--owned-child-signal-audit") else { return false }
        do {
            guard CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--owned-child-signal-audit",
                  ["ignore", "no-wait"].contains(CommandLine.arguments[2]) else { throw error("argumentos de worker inválidos.") }
            let mode = CommandLine.arguments[2]
            var policy = sigaction()
            sigemptyset(&policy.sa_mask)
            policy.__sigaction_u.__sa_handler = mode == "ignore" ? SIG_IGN : SIG_DFL
            policy.sa_flags = mode == "no-wait" ? SA_NOCLDWAIT : 0
            guard sigaction(SIGCHLD, &policy, nil) == 0 else { throw error("não foi possível preparar a política isolada.") }
            let config = Process()
            config.executableURL = URL(fileURLWithPath: "/usr/bin/true")
            config.standardInput = FileHandle.nullDevice; config.standardOutput = FileHandle.nullDevice; config.standardError = FileHandle.nullDevice
            var refused = false
            do { _ = try OwnedChildProcess(configuration: config) }
            catch { refused = (error as NSError).domain == "PDF.OwnedChild.Ownership" }
            guard refused else { throw error("a política incompatível permitiu iniciar um filho.") }
            try NativeOutput.write(JSONSerialization.data(withJSONObject: ["mode": mode, "refused": true]),
                                   to: URL(fileURLWithPath: CommandLine.arguments[3]))
            exit(0)
        } catch {
            FileHandle.standardError.write(Data("Owned child signal-policy audit failed.\n".utf8))
            exit(2)
        }
    }
    static func run() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-child-audit-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: root); ApplicationWork.resumeAcceptingWork() }
        let source = root.appendingPathComponent("original.txt")
        let original = Data("original preservado\n".utf8)
        try NativeOutput.write(original, to: source)
        try await rejectAutomaticReaping(root: root)

        // The same unlinked private stdin used by Workspace survives dup2;
        // neither command arguments nor environment contain its payload.
        let payload = Data("{\"senha\":\"verificação-Ω\"}".utf8)
        let input = try EngineInputTransport(data: payload)
        defer { input.close() }
        let cat = Process(), pipe = Pipe()
        cat.executableURL = URL(fileURLWithPath: "/bin/cat")
        cat.standardInput = input.handle; cat.standardOutput = pipe; cat.standardError = FileHandle.nullDevice
        let copier = try OwnedChildProcess(configuration: cat)
        let copied = try await Task.detached { () -> Data in
            defer { try? pipe.fileHandleForReading.close() }
            var bytes = Data()
            let exit = try copier.collectOutput(from: pipe.fileHandleForReading) { bytes.append($0) }
            try require(exit.status == 0 && !exit.signalled, "o transporte de stdin falhou.")
            return bytes
        }.value
        try require(copied == payload, "os bytes privados de stdin foram alterados.")
        try reaped(copier)

        // The shell owns its sleep descendant, handles cancellation, waits for
        // that descendant and then acknowledges cleanup before it exits.
        let cooperative = try launch(script: """
        trap 'kill -TERM "$child" 2>/dev/null; wait "$child"; printf done > "$1/cleaned"; exit 130' INT TERM
        /bin/sleep 30 &
        child=$!
        printf '%s' "$child" > "$1/descendant"
        printf ready > "$1/ready"
        wait "$child"
        """, name: "cooperative", directory: root)
        try await waitReady(root.appendingPathComponent("ready"), child: cooperative)
        cooperative.cancel(grace: 10)
        let cancelled = try await Task.detached { try cooperative.waitUntilExit() }.value
        try require(cancelled.status == 130 && !cancelled.signalled, "o cancelamento não aguardou o cleanup cooperante.")
        try require(try Data(contentsOf: root.appendingPathComponent("cleaned")) == Data("done".utf8), "o descendente não confirmou cleanup.")
        let descendantText = try String(contentsOf: root.appendingPathComponent("descendant"), encoding: .utf8)
        guard let descendant = Int32(descendantText) else { throw error("o recibo do descendente é inválido.") }
        try require(Darwin.kill(descendant, 0) == -1 && errno == ESRCH, "o descendente cooperante continuou vivo.")
        try reaped(cooperative)

        // Escalation is tested against a child with no descendants, deliberately
        // ignoring INT/TERM. It must be killed and reaped by its original owner.
        let resistant = try launch(script: """
        trap '' INT TERM
        printf ready > "$1/resistant-ready"
        while :; do :; done
        """, name: "resistant", directory: root)
        try await waitReady(root.appendingPathComponent("resistant-ready"), child: resistant)
        resistant.cancel(grace: 0.1)
        let forced = try await Task.detached { try resistant.waitUntilExit() }.value
        try require(forced.signalled && forced.status == SIGKILL, "a escalada não encerrou o filho pertencente ao teste.")
        try reaped(resistant)

        // A real EINVAL from kill on this owned child must not poison waitpid.
        // The child stays alive until the private gate permits a natural exit;
        // no PID outside this audit and no synthetic process result is used.
        let signalFailure = try launch(script: """
        printf ready > "$1/signal-failure-ready"
        while [ ! -f "$1/signal-failure-release" ]; do :; done
        exit 7
        """, name: "signal-failure", directory: root)
        try await waitReady(root.appendingPathComponent("signal-failure-ready"), child: signalFailure)
        signalFailure.cancel(grace: 10, signal: -1)
        let signalErrorCode = signalFailure.cancellationFailure.map { ($0 as NSError).code }
        try require(signalErrorCode == Int(EINVAL), "o teste não alcançou uma recusa real de sinal EINVAL.")
        try require(try signalFailure.isRunning(), "a recusa de sinal impediu observar o filho ainda vivo.")
        try NativeOutput.write(Data("release".utf8), to: root.appendingPathComponent("signal-failure-release"))
        let natural = try await Task.detached { try signalFailure.waitUntilExit() }.value
        try require(natural.status == 7 && !natural.signalled, "a falha de sinal impediu recolher a saída natural.")
        try reaped(signalFailure)

        let completed = try launch(script: "printf completed > \"$1/result\"", name: "completed", directory: root)
        let completion = try await Task.detached { try completed.waitUntilExit() }.value
        completed.cancel(grace: 0); completed.cancel(grace: 0)
        let repeated = try completed.waitUntilExit()
        try require(completion.status == 0 && repeated.status == 0 && !repeated.signalled, "um cancelamento tardio mudou a conclusão.")
        try require(try Data(contentsOf: root.appendingPathComponent("result")) == Data("completed".utf8), "o resultado concluído foi removido.")
        try require(try Data(contentsOf: source) == original, "o arquivo original foi modificado.")

        // A pipe kept open by a descendant is not permission to wait forever
        // after the owned leader exits. This descendant self-terminates; no PID
        // discovered after reaping is ever signalled by this test.
        let inheritedOutput = Pipe()
        let writer = try launch(script: """
        (SECONDS=0; while ((SECONDS < 2)); do printf 'finite-output\\n'; done) &
        exit 0
        """, name: "inherited-output", directory: root, output: inheritedOutput)
        let started = ProcessInfo.processInfo.systemUptime
        let drainExit = try await Task.detached { try writer.collectOutput(from: inheritedOutput.fileHandleForReading) { _ in } }.value
        try? inheritedOutput.fileHandleForReading.close()
        try require(drainExit.status == 0 && ProcessInfo.processInfo.systemUptime - started < 1.5,
                    "a drenagem continuou esperando o descendente após a saída do líder.")
        // Allow the self-bounded fixture's cleanup process to finish before
        // deleting its directory. This is not an application timeout policy.
        try await Task.sleep(for: .milliseconds(2100))
        try reaped(writer)

        try await workspaceTermination(root: root)
        try await ticketLifecycle(root: root)
    }

    private static func rejectAutomaticReaping(root: URL) async throws {
        guard let executable = Bundle.main.executableURL else { throw error("o executável da auditoria está indisponível.") }
        for mode in ["ignore", "no-wait"] {
            let report = root.appendingPathComponent("policy-" + mode + ".json")
            let config = Process()
            config.executableURL = executable; config.arguments = [workerArgument, mode, report.path]
            config.standardInput = FileHandle.nullDevice; config.standardOutput = FileHandle.nullDevice; config.standardError = FileHandle.nullDevice
            let lease = try BundleRuntimeLease.configureChild(config)
            defer { try? lease?.close() }
            let child = try OwnedChildProcess(configuration: config)
            let deadline = ProcessInfo.processInfo.systemUptime + 5
            while try child.isRunning() {
                guard ProcessInfo.processInfo.systemUptime < deadline else {
                    child.cancel(grace: 0); _ = try? child.waitUntilExit()
                    throw error("a recusa de política herdada excedeu o prazo.")
                }
                try await Task.sleep(for: .milliseconds(20))
            }
            let completion = try child.waitUntilExit()
            let result = try JSONSerialization.jsonObject(with: Data(contentsOf: report)) as? [String: Any]
            try require(completion.status == 0 && !completion.signalled && result?["mode"] as? String == mode && result?["refused"] as? Bool == true,
                        "SIG_IGN/SA_NOCLDWAIT não foram recusados no processo isolado.")
        }
    }

    private static func workspaceTermination(root: URL) async throws {
        let suite = "PDF.EngineQuitAudit." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite); ApplicationWork.resumeAcceptingWork() }
        let input = root.appendingPathComponent("engine-input.pdf"), output = root.appendingPathComponent("engine-output.pdf")
        let original = try IntelligenceText.PDF("Documento original para verificar o encerramento da conversão.")
        try NativeOutput.write(original, to: input)
        let workspace = Workspace(defaults: defaults, recoveryStore: RecoveryStore(directory: root.appendingPathComponent("engine-recovery")), enableRecoveryPolling: false)
        var completions = 0
        workspace.execute(operation: "rotate", inputs: [input], output: output, options: ["degrees": 90], title: "Auditoria de encerramento", completion: { _ in completions += 1 })
        try require(workspace.busy, "o motor real não iniciou antes da solicitação de término.")
        let ready = await workspace.prepareForTermination()
        try require(ready && !workspace.busy && completions == 1, "o término não aguardou a conclusão única da execução real.")
        try require(try Data(contentsOf: input) == original, "o encerramento alterou os bytes do PDF original.")
        if FileManager.default.fileExists(atPath: output.path) {
            guard let result = PDFDocument(url: output) else { throw error("um resultado publicado não pôde ser reaberto.") }
            try require(result.pageCount == 1 && result.page(at: 0)?.rotation == 90,
                        "o encerramento deixou um resultado incompleto no destino.")
        }
    }

    private static func ticketLifecycle(root: URL) async throws {
        let suite = "PDF.ChildAudit." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = Workspace(defaults: defaults, recoveryStore: RecoveryStore(directory: root.appendingPathComponent("recovery")), enableRecoveryPolling: false)
        let cancellation = NativeCancellation()
        let unfinished = ApplicationWork.begin { cancellation.cancel() }
        defer { unfinished.finish() }
        let refused = await model.prepareForTermination(externalDeadline: 0.05)
        try require(!refused, "o término foi aprovado antes da conclusão do trabalho registrado.")
        do { try cancellation.check(); throw error("o término não solicitou cancelamento.") }
        catch is CancellationError { }
        unfinished.finish(); unfinished.finish()
        let freshCancellation = NativeCancellation()
        let fresh = ApplicationWork.begin { freshCancellation.cancel() }
        try freshCancellation.check()
        fresh.finish()
        try require(await model.prepareForTermination(externalDeadline: 0.1), "o término continuou bloqueado após o cleanup.")
        ApplicationWork.resumeAcceptingWork()
    }

    private static func launch(script: String, name: String, directory: URL, output: Pipe? = nil) throws -> OwnedChildProcess {
        let file = directory.appendingPathComponent(name + ".sh")
        try NativeOutput.write(Data(script.utf8), to: file)
        let config = Process()
        config.executableURL = URL(fileURLWithPath: "/bin/bash")
        config.arguments = [file.path, directory.path]
        config.standardInput = FileHandle.nullDevice
        config.standardOutput = output ?? Pipe()
        // Discard unused output without creating a pipe the fixture can fill.
        if output == nil { config.standardOutput = FileHandle.nullDevice }
        config.standardError = FileHandle.nullDevice
        return try OwnedChildProcess(configuration: config)
    }
    private static func waitReady(_ file: URL, child: OwnedChildProcess) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        while !FileManager.default.fileExists(atPath: file.path) {
            guard try child.isRunning(), ProcessInfo.processInfo.systemUptime < deadline else {
                child.cancel(grace: 0); _ = try? child.waitUntilExit()
                throw error("o processo de auditoria não ficou pronto.")
            }
            try await Task.sleep(for: .milliseconds(10))
        }
    }
    private static func reaped(_ child: OwnedChildProcess) throws {
        var status: Int32 = 0
        let result = waitpid(child.processIdentifier, &status, WNOHANG)
        try require(result == -1 && errno == ECHILD, "o processo filho não foi recolhido.")
    }
    nonisolated private static func require(_ condition: Bool, _ reason: String) throws {
        guard condition else { throw error(reason) }
    }
    nonisolated private static func error(_ reason: String) -> NSError {
        NSError(domain: "PDF.ChildAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: reason])
    }
}
