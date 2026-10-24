import AppKit
import PDFKit
import CryptoKit
import Darwin

/// A real process-loss regression, confined to disposable files and preferences.
/// It proves recovery after a completed automatic checkpoint and SIGKILL. It
/// does not claim that every possible interruption inside a disk write is covered.
@MainActor enum CrashRecoveryAudit {
    static let argument = "--recovery-crash-worker"
    private static let directoryPrefix = "PDF-crash-audit-"
    private static let fieldName = "crash-audit-field"
    private static let fieldValue = "Recuperação — ação Ω 🔑 e\u{301}"
    private static let noteValue = "Nota não salva — revisão Ω 🔑"
    private static let marker = "PDF crash recovery verification"

    private struct Request: Codable {
        let version: Int
        let id: UUID
        let sourceSHA256: String
        let password: String
    }
    private struct Ready: Codable {
        let version: Int
        let id: UUID
        let processID: Int32
        let sessionID: UUID
        let sourceSHA256: String
        let snapshotSHA256: String
        let recordSHA256: String
    }
    private struct AuditFailure: LocalizedError {
        let step: String
        var errorDescription: String? { "Auditoria de recuperação após encerramento abrupto: " + step }
    }
    @MainActor private final class WorkerContext {
        let workspace: Workspace
        var writes: [Task<RecoveryRecord?, Error>] = []
        init(_ workspace: Workspace) { self.workspace = workspace }
        func cancel() {
            workspace.cancelDocumentOpenings()
            for session in workspace.sessions {
                if let write = session.recoveryWrite { writes.append(write) }
                session.cancelRecoveryTask()
            }
        }
        func settle() async {
            cancel()
            await workspace.waitForPendingOpen()
            for write in writes { _ = try? await write.value }
            writes.removeAll()
        }
    }

    /// Call before SwiftUI creates the real App/Workspace. The worker has no
    /// window, never uses the default recovery store and never receives a secret
    /// in its arguments. A synthetic credential exists only in private input.
    static func handleCommandLineIfNeeded() async -> Bool {
        let arguments = CommandLine.arguments
        guard arguments.contains(argument) else { return false }
        guard arguments.count == 3, arguments[1] == argument else {
            FileHandle.standardError.write(Data("Recovery crash worker: invalid arguments.\n".utf8))
            exit(2)
        }
        let directory = URL(fileURLWithPath: arguments[2], isDirectory: true).standardizedFileURL
        let task = Task { @MainActor in try await worker(directory: directory) }
        let signals = CrashAuditSignalCancellation { task.cancel() }
        // Leave time for cancellation to terminate/reap a normalizer before
        // the parent's final 30-second process deadline.
        let watchdog = Task.detached {
            do { try await Task.sleep(for: .seconds(20)); task.cancel() }
            catch { }
        }
        defer { watchdog.cancel(); withExtendedLifetime(signals) { } }
        do { try await task.value }
        catch {
            // An OS/framework error may include private paths or credentials.
            // The parent receives only a fixed phase, not an arbitrary error.
            FileHandle.standardError.write(Data("Recovery crash worker did not reach the verified crash boundary.\n".utf8))
            exit(2)
        }
        return true
    }

    static func run() async throws {
        let id = UUID()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(directoryPrefix + id.uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let workerSuite = suite(id, role: "worker"), parentSuite = suite(id, role: "restore")
        defer {
            UserDefaults(suiteName: workerSuite)?.removePersistentDomain(forName: workerSuite)
            UserDefaults(suiteName: parentSuite)?.removePersistentDomain(forName: parentSuite)
            try? FileManager.default.removeItem(at: directory)
        }
        _ = NSApplication.shared
        let password = "Recuperação-" + UUID().uuidString + "-🔑"
        let original = try fixture(password: password)
        let source = directory.appendingPathComponent("source.pdf")
        try NativeOutput.write(original, to: source)
        let request = Request(version: 1, id: id, sourceSHA256: digest(original), password: password)
        try NativeOutput.write(try encode(request), to: directory.appendingPathComponent("request.json"))
        let process = Process()
        guard let executable = Bundle.main.executableURL else { throw AuditFailure(step: "executável do aplicativo indisponível.") }
        process.executableURL = executable
        process.arguments = [argument, directory.path]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        let deadline = ProcessInfo.processInfo.systemUptime + 30
        try process.run()
        let ready: Ready
        do {
            let readyURL = directory.appendingPathComponent("ready.json")
            while !FileManager.default.fileExists(atPath: readyURL.path) {
                try Task.checkCancellation()
                guard process.isRunning else { throw AuditFailure(step: "o processo filho terminou antes do checkpoint automático.") }
                guard ProcessInfo.processInfo.systemUptime < deadline - 6 else { throw AuditFailure(step: "o checkpoint automático excedeu o prazo do processo isolado.") }
                await pause()
            }
            ready = try JSONDecoder().decode(Ready.self, from: privateFile(readyURL, limit: 16_384))
            try require(ready.version == 1 && ready.id == id && ready.processID == process.processIdentifier && ready.sourceSHA256 == request.sourceSHA256,
                        "o recibo de recuperação não pertence ao processo lançado.")
            try require(process.isRunning && Darwin.kill(process.processIdentifier, SIGKILL) == 0,
                        "não foi possível encerrar abruptamente o processo de auditoria.")
            while process.isRunning && ProcessInfo.processInfo.systemUptime < deadline { await pause() }
            try require(!process.isRunning, "o processo encerrado não pôde ser recolhido no prazo.")
            process.waitUntilExit()
            try require(process.terminationReason == .uncaughtSignal && process.terminationStatus == SIGKILL,
                        "a execução não terminou por SIGKILL real.")
        } catch {
            await stop(process, deadline: deadline)
            throw error
        }

        let store = RecoveryStore(directory: directory.appendingPathComponent("Recovery", isDirectory: true))
        let records = try store.list()
        try require(records.count == 1 && store.warnings.isEmpty, "a reabertura encontrou uma geração ausente ou inválida.")
        guard let record = records.first, record.id == ready.sessionID else { throw AuditFailure(step: "a sessão recuperável mudou após SIGKILL.") }
        let recovered = try store.load(record)
        try require(record.encrypted && digest(recovered) == ready.snapshotSHA256 && digest(try encode(record)) == ready.recordSHA256,
                    "a geração ou seu hash mudou após SIGKILL.")
        guard let locked = PDFDocument(data: recovered) else { throw AuditFailure(step: "o checkpoint não contém PDF.") }
        try require(locked.isEncrypted && locked.isLocked && !locked.unlock(withPassword: ""),
                    "a recuperação protegida deixou de exigir uma credencial.")
        let noPassword = try NativePDFSerialization.prepareOpen(data: recovered, timeout: 10)
        try require(noPassword.requiresPassword, "a abertura do checkpoint ignorou a proteção.")
        var refusedWrong = false
        do { _ = try NativePDFSerialization.prepareOpen(data: recovered, password: "crash-audit-wrong-password", timeout: 10) }
        catch { refusedWrong = true }
        try require(refusedWrong, "a recuperação aceitou uma senha incorreta.")
        guard let defaults = UserDefaults(suiteName: parentSuite) else { throw AuditFailure(step: "preferências isoladas indisponíveis.") }
        defaults.set(false, forKey: "recoveryEnabled")
        let workspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try workspace.refreshRecoveryNow()
        workspace.restoreRecovery(id: record.id)
        await workspace.waitForPendingOpen()
        try require(workspace.needsPassword && workspace.document == nil && workspace.sessions.isEmpty,
                    "a sessão foi instalada antes da autenticação.")
        workspace.documentPassword = password
        workspace.unlockPendingDocument()
        await workspace.waitForPendingOpen()
        guard let document = workspace.document, let session = workspace.activeSession else { throw AuditFailure(step: "a senha Unicode não restaurou a sessão.") }
        try validateEdits(document)
        try require(document.isEncrypted && !document.isLocked && session.password == password && session.id == record.id,
                    "a restauração perdeu a proteção ou a credencial original da sessão.")
        try require(workspace.currentPage == 2 && workspace.bookmarks == [1, 2] && session.isDirty && workspace.hasUnsavedChanges &&
                    !session.autoScale && abs(session.zoom - 1.75) < 0.001,
                    "a restauração perdeu página, zoom, marcadores ou alterações pendentes.")
        try require(try privateFile(source, limit: 16 * 1_024 * 1_024) == original,
                    "o encerramento ou a restauração modificou os bytes do arquivo original.")
        try require(try store.load(record) == recovered, "restaurar a sessão substituiu o checkpoint protegido.")
        // Ready and recovery metadata must not persist the session credential or
        // annotation/form content. The private input request is intentionally
        // excluded: it transports only this test's synthetic credential.
        let metadata = try encode(record), receipt = try privateFile(directory.appendingPathComponent("ready.json"), limit: 16_384)
        for bytes in [metadata, receipt] {
            try require(bytes.range(of: Data(password.utf8)) == nil && bytes.range(of: Data(fieldValue.utf8)) == nil && bytes.range(of: Data(noteValue.utf8)) == nil,
                        "o recibo ou metadados persistiram conteúdo privado da sessão.")
        }
        print("[Crash recovery] real automatic checkpoint + SIGKILL + authenticated reader restore: PASS")
    }

    private static func worker(directory: URL) async throws {
        try validateDirectory(directory)
        let request = try JSONDecoder().decode(Request.self, from: privateFile(directory.appendingPathComponent("request.json"), limit: 16_384))
        try require(request.version == 1 && directory.lastPathComponent == directoryPrefix + request.id.uuidString &&
                    request.password.utf8.count <= 127 && !request.password.isEmpty,
                    "a configuração privada do processo é inválida.")
        let source = directory.appendingPathComponent("source.pdf")
        try require(digest(try privateFile(source, limit: 16 * 1_024 * 1_024)) == request.sourceSHA256,
                    "a fixture original mudou antes da abertura.")
        _ = NSApplication.shared
        let suiteName = suite(request.id, role: "worker")
        guard let defaults = UserDefaults(suiteName: suiteName) else { throw AuditFailure(step: "preferências privadas indisponíveis.") }
        defaults.removePersistentDomain(forName: suiteName)
        defaults.set(true, forKey: "recoveryEnabled")
        defaults.set(false, forKey: "readerAutoScale")
        defaults.set(1.75, forKey: "readerZoom")
        let store = RecoveryStore(directory: directory.appendingPathComponent("Recovery", isDirectory: true))
        // Polling and the actual 650ms edit debounce remain enabled. No explicit
        // synchronous save/checkpoint is used to manufacture the ready state.
        let workspace = Workspace(defaults: defaults, recoveryStore: store)
        let context = WorkerContext(workspace)
        do {
            try await withTaskCancellationHandler {
                workspace.open(url: source)
                await workspace.waitForPendingOpen()
                try Task.checkCancellation()
                try require(workspace.needsPassword && workspace.document == nil, "o original cifrado não solicitou senha.")
                workspace.documentPassword = request.password
                workspace.unlockPendingDocument()
                await workspace.waitForPendingOpen()
                try Task.checkCancellation()
                guard let document = workspace.document, let session = workspace.activeSession,
                      let page = document.page(at: 0), let widget = page.annotations.first(where: { $0.fieldName == fieldName }) else {
                    throw AuditFailure(step: "a fixture não abriu no leitor protegido.")
                }
                let view = PDFView(frame: CGRect(x: 0, y: 0, width: 800, height: 600))
                view.document = document; view.autoScales = false; view.scaleFactor = 1.75; view.go(to: page)
                workspace.pdfView = view
                workspace.addNote(noteValue, colorHex: "#4070C0")
                widget.widgetStringValue = fieldValue
                workspace.goToPage(2); workspace.bookmarks = [1, 2]
                workspace.didEdit()
                try validateEdits(document)
                try require(session.isDirty, "as edições não marcaram a sessão como alterada.")
                while session.recoveryRecord == nil || session.recoveryTask != nil || session.recoveryWrite != nil {
                    try Task.checkCancellation()
                    try await Task.sleep(for: .milliseconds(25))
                }
                try Task.checkCancellation()
                guard let record = session.recoveryRecord else { throw AuditFailure(step: "o autosave não publicou uma geração.") }
                let bytes = try store.load(record)
                try require(record.encrypted && record.state.page == 2 && record.state.bookmarks == [1, 2],
                            "o checkpoint automático não capturou as alterações de estado.")
                let reopened = try NativePDFSerialization.open(data: bytes, password: request.password)
                try validateEdits(reopened)
                try require(digest(try privateFile(source, limit: 16 * 1_024 * 1_024)) == request.sourceSHA256,
                            "o autosave alterou o documento original.")
                let ready = Ready(version: 1, id: request.id, processID: getpid(), sessionID: session.id,
                                  sourceSHA256: request.sourceSHA256, snapshotSHA256: digest(bytes), recordSHA256: digest(try encode(record)))
                // No normalizer or recovery write remains in flight at this
                // boundary, so SIGKILL cannot orphan a qpdf child in this test.
                try require(session.recoveryTask == nil && session.recoveryWrite == nil,
                            "há uma gravação pendente no limite de crash escolhido.")
                try NativeOutput.write(try encode(ready), to: directory.appendingPathComponent("ready.json"))
                withExtendedLifetime(view) { }
                while true { try await Task.sleep(for: .milliseconds(100)); try Task.checkCancellation() }
            } onCancel: {
                Task { @MainActor in context.cancel() }
            }
        } catch {
            await context.settle()
            throw error
        }
    }

    private static func fixture(password: String) throws -> Data {
        guard let document = PDFDocument(data: try IntelligenceText.PDF(marker)), let first = document.page(at: 0),
              let second = first.copy() as? PDFPage else { throw AuditFailure(step: "não foi possível criar a fixture de duas páginas.") }
        document.insert(second, at: 1)
        let widget = PDFAnnotation(bounds: CGRect(x: 70, y: 500, width: 300, height: 28), forType: .widget, withProperties: nil)
        widget.widgetFieldType = .text; widget.fieldName = fieldName
        widget.widgetStringValue = "Original"; widget.widgetDefaultStringValue = ""
        first.addAnnotation(widget)
        return try NativePDFSerialization.finish(NativePDFSerialization.prepare(document: document, password: password), timeout: 10)
    }
    private static func validateEdits(_ document: PDFDocument) throws {
        try require(!document.isLocked && document.pageCount == 2 && (document.string ?? "").contains(marker),
                    "a recuperação perdeu páginas ou texto original.")
        guard let first = document.page(at: 0) else { throw AuditFailure(step: "página recuperada ausente.") }
        let notes = first.annotations.filter { PDFAnnotationKind.matches($0, .text) }
        try require(notes.count == 1 && Data((notes[0].contents ?? "").utf8) == Data(noteValue.utf8),
                    "a nota recuperada não conserva o conteúdo Unicode exato.")
        let widgets = first.annotations.filter { $0.fieldName == fieldName }
        try require(widgets.count == 1 && Data((widgets[0].widgetStringValue ?? "").utf8) == Data(fieldValue.utf8),
                    "o formulário recuperado não conserva o conteúdo Unicode exato.")
    }
    private static func validateDirectory(_ directory: URL) throws {
        let fd = Darwin.open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { throw AuditFailure(step: "pasta de auditoria indisponível.") }
        defer { Darwin.close(fd) }
        var info = stat()
        try require(fstat(fd, &info) == 0 && info.st_mode & S_IFMT == S_IFDIR && info.st_uid == getuid() && info.st_mode & 0o077 == 0,
                    "a pasta de auditoria não é privada.")
    }
    private static func privateFile(_ url: URL, limit: Int) throws -> Data {
        let fd = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard fd >= 0 else { throw AuditFailure(step: "arquivo privado da auditoria indisponível.") }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        try require(fstat(fd, &info) == 0 && info.st_mode & S_IFMT == S_IFREG && info.st_uid == getuid() && info.st_mode & 0o077 == 0 &&
                    info.st_size > 0 && info.st_size <= Int64(limit), "arquivo de auditoria irregular, público ou grande demais.")
        var data = Data()
        while let bytes = try handle.read(upToCount: min(65_536, limit + 1 - data.count)), !bytes.isEmpty {
            data.append(bytes)
            try require(data.count <= limit, "arquivo privado cresceu além do limite.")
        }
        try require(data.count == Int(info.st_size), "arquivo privado mudou durante a leitura.")
        return data
    }
    private static func suite(_ id: UUID, role: String) -> String { "PDF.CrashRecoveryAudit." + id.uuidString + "." + role }
    private static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(value)
    }
    private static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func require(_ condition: @autoclosure () throws -> Bool, _ step: String) throws {
        guard try condition() else { throw AuditFailure(step: step) }
    }
    private static func pause() async {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 0.025) { continuation.resume() }
        }
    }
    private static func stop(_ process: Process, deadline: TimeInterval) async {
        guard process.processIdentifier > 0 else { return }
        if process.isRunning {
            process.terminate()
            let grace = min(deadline, ProcessInfo.processInfo.systemUptime + 6)
            while process.isRunning && ProcessInfo.processInfo.systemUptime < grace { await pause() }
            if process.isRunning { _ = Darwin.kill(process.processIdentifier, SIGKILL) }
        }
        process.waitUntilExit()
    }
}

private final class CrashAuditSignalCancellation {
    private let source: DispatchSourceSignal
    private let previous: sig_t?
    init(cancel: @escaping @Sendable () -> Void) {
        previous = Darwin.signal(SIGTERM, SIG_IGN)
        source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global(qos: .utility))
        source.setEventHandler(handler: cancel)
        source.resume()
    }
    deinit { source.cancel(); Darwin.signal(SIGTERM, previous) }
}
