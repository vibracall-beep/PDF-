import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers
import Darwin

/// Runs Apple Pages on a private copy. The user's open documents and Pages
/// process are never terminated; only this application's osascript child is.
private final class PagesProcessControl: @unchecked Sendable {
    private let lock = NSLock()
    private var process: OwnedChildProcess?
    private var cancelled = false
    private var exceededTime = false
    private var launched = false
    var didLaunch: Bool { lock.lock(); defer { lock.unlock() }; return launched }

    func attach(_ value: OwnedChildProcess) {
        lock.lock(); process = value; launched = true; let stop = cancelled || exceededTime; lock.unlock()
        if stop { terminate(value) }
    }
    func detach() { lock.lock(); process = nil; lock.unlock() }
    func cancel() {
        lock.lock(); cancelled = true; let current = process; lock.unlock()
        if let current { terminate(current) }
    }
    func timeout() {
        lock.lock(); exceededTime = true; let current = process; lock.unlock()
        if let current { terminate(current) }
    }
    func check() throws {
        lock.lock(); let stopped = cancelled; let timedOut = exceededTime; lock.unlock()
        if stopped { throw CancellationError() }
        if timedOut { throw PagesConversionError.timeout }
    }
    private func terminate(_ value: OwnedChildProcess) {
        value.cancel(grace: 2, signal: SIGTERM)
    }
}

enum PagesScriptReceipt: String {
    case openDenied = "private-copy-open-denied"
    case exportedAndClosed = "private-copy-exported-and-closed"
    case closed = "private-copy-closed"
    case notOpen = "private-copy-not-open"
    static func parse(_ stdout: String) -> PagesScriptReceipt? {
        Self(rawValue: stdout.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

private final class PagesScriptDiagnostics: @unchecked Sendable {
    private let lock = NSLock()
    private var bytes = Data()
    private var failed = false
    func append(_ data: Data) {
        lock.lock(); defer { lock.unlock() }
        if bytes.count < 65_536 { bytes.append(data.prefix(65_536 - bytes.count)) }
    }
    func recordFailure() { lock.lock(); failed = true; lock.unlock() }
    var snapshot: (Data, Bool) { lock.lock(); defer { lock.unlock() }; return (bytes, failed) }
}

private enum PagesConversionError: LocalizedError {
    case source, unsafeSource, destination, pagesMissing, timeout, automation, export(String), invalidPDF
    case cleanup(String, String)
    var errorDescription: String? {
        switch self {
        case .source: return "Escolha um documento .pages acessível."
        case .unsafeSource: return "O documento contém links ou entradas especiais. Exporte uma cópia normal do Pages antes de converter."
        case .destination: return "Escolha um nome novo para o PDF. Arquivos existentes serão preservados."
        case .pagesMissing: return "Instale o Pages pela App Store para usar esta conversão."
        case .timeout: return "O Pages não concluiu a exportação em 3 minutos. O arquivo original foi preservado."
        case .automation: return "Autorize PDF a controlar Pages em Ajustes do Sistema › Privacidade e Segurança › Automação, e repita a conversão."
        case .export(let reason): return "O Pages não concluiu a exportação: \(reason)"
        case .invalidPDF: return "O Pages não produziu um PDF legível dentro do limite de 512 MB."
        case .cleanup(let reason, let directory): return "\(reason) Não foi possível confirmar o fechamento da cópia privada no Pages. Ela foi preservada em \(directory). Seu original não foi alterado."
        }
    }
}

/// An unconfirmed AppleEvent may outlive its osascript sender. Keep a separate
/// lifetime for that private document until a later close is confirmed. This
/// never represents ownership of Pages itself or any original user document.
final class PendingPagesCleanup: Identifiable, @unchecked Sendable {
    let id = UUID()
    let directory: URL
    let document: URL
    private let identities: [String]
    private let ticket: ApplicationWork.Ticket
    private let operationLock = NSLock()
    private var closureConfirmed = false
    private var finished = false
    init(directory: URL, document: URL) throws {
        guard document.deletingLastPathComponent().standardizedFileURL == directory.standardizedFileURL else {
            throw PagesConversionError.unsafeSource
        }
        self.directory = directory; self.document = document
        identities = [try Self.identity(directory, directory: true), try Self.identity(document, directory: nil)]
        ticket = ApplicationWork.begin(cancelWhenStopping: false) {}
    }
    private static func identity(_ url: URL, directory: Bool?) throws -> String {
        var value = stat()
        guard lstat(url.path, &value) == 0, value.st_uid == getuid(),
              value.st_mode & S_IFMT == S_IFREG || value.st_mode & S_IFMT == S_IFDIR,
              directory != true || value.st_mode & S_IFMT == S_IFDIR else { throw PagesConversionError.unsafeSource }
        return "\(value.st_dev):\(value.st_ino):\(value.st_mode & S_IFMT)"
    }
    func verifyIdentity() throws {
        guard identities == [try Self.identity(directory, directory: true), try Self.identity(document, directory: nil)] else {
            throw PagesConversionError.unsafeSource
        }
    }
    /// The supplied operation must confirm closure, not merely send cancel.
    /// Audit calls use actual disposable child processes, never the Pages app.
    func finishConfirmed(_ close: () throws -> Void) throws {
        operationLock.lock(); defer { operationLock.unlock() }
        if finished { return }
        if !closureConfirmed {
            try verifyIdentity()
            try close()
            try verifyIdentity()
            closureConfirmed = true
        } else {
            // A prior close may have succeeded while deleting its private
            // directory failed. Retrying cleanup must not require a document
            // that was already removed during that partial filesystem cleanup.
            var status = stat()
            if lstat(directory.path, &status) != 0, errno == ENOENT {
                finished = true; ticket.finish(); return
            }
            guard try Self.identity(directory, directory: true) == identities[0] else { throw PagesConversionError.unsafeSource }
        }
        try FileManager.default.removeItem(at: directory)
        finished = true
        ticket.finish()
    }
    fileprivate func finishUnusedOrClosed() {
        operationLock.lock(); defer { operationLock.unlock() }
        finished = true; ticket.finish()
    }
}

@MainActor final class PagesCleanupRegistry: ObservableObject {
    static let shared = PagesCleanupRegistry()
    @Published private(set) var pending: [PendingPagesCleanup] = []
    @Published private(set) var retrying = Set<UUID>()
    @Published private(set) var messages: [UUID: String] = [:]
    nonisolated static func retain(_ item: PendingPagesCleanup) {
        Task { @MainActor in
            if !shared.pending.contains(where: { $0.id == item.id }) { shared.pending.append(item) }
        }
    }
    func retry(_ item: PendingPagesCleanup) {
        guard ApplicationWork.isAcceptingWork, !retrying.contains(item.id), pending.contains(where: { $0.id == item.id }) else { return }
        retrying.insert(item.id); messages[item.id] = "Confirmando o fechamento da cópia privada…"
        let control = PagesProcessControl()
        ApplicationTask.start(cancel: { control.cancel() }) { [self] in
            defer { retrying.remove(item.id) }
            do {
                try Task.checkCancellation()
                try await Task.detached(priority: .userInitiated) {
                    try item.finishConfirmed { try PagesExporter.closePrivateCopy(item.document, in: item.directory, control: control) }
                }.value
                pending.removeAll { $0.id == item.id }; messages[item.id] = nil
            } catch {
                messages[item.id] = "O fechamento ou a limpeza ainda não foram confirmados. A cópia privada foi preservada. Aguarde o Pages responder e tente novamente."
            }
        }
    }
}

/// Resolves a selected alias-like symlink before copying, then verifies the
/// complete copy. Pages must never receive a symlink back to the user's source.
enum PagesPrivateCopy {
    static func create(source: URL, in directory: URL) throws -> URL {
        let resolved = source.resolvingSymlinksInPath()
        try validateTree(resolved)
        let copied = directory.appendingPathComponent("PDF-conversao-\(UUID().uuidString).pages")
        try FileManager.default.copyItem(at: resolved, to: copied)
        do {
            try validateTree(copied)
            return copied.resolvingSymlinksInPath()
        } catch {
            try? FileManager.default.removeItem(at: copied)
            throw error
        }
    }
    private static func validateTree(_ root: URL) throws {
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .isDirectoryKey, .isSymbolicLinkKey, .isAliasFileKey]
        func validate(_ url: URL) throws -> Bool {
            let values = try url.resourceValues(forKeys: keys)
            guard values.isSymbolicLink != true, values.isAliasFile != true,
                  values.isRegularFile == true || values.isDirectory == true else { throw PagesConversionError.unsafeSource }
            return values.isDirectory == true
        }
        guard try validate(root) else { return }
        var traversalError: Error?
        guard let entries = FileManager.default.enumerator(at: root, includingPropertiesForKeys: Array(keys), options: [], errorHandler: { _, error in
            traversalError = error
            return false
        }) else { throw PagesConversionError.source }
        var count = 0
        for case let child as URL in entries {
            count += 1
            guard count <= 100_000 else { throw PagesConversionError.unsafeSource }
            _ = try validate(child)
        }
        if let traversalError { throw traversalError }
    }
}

private enum PagesExporter {
    private static let exportScript = """
    on run argv
        set sourceFile to POSIX file (item 1 of argv)
        set outputFile to POSIX file (item 2 of argv)
        with timeout of 170 seconds
            tell application id "com.apple.iWork.Pages"
                try
                    set convertedDocument to open sourceFile
                on error openMessage number openNumber
                    if openNumber is -1743 then return "private-copy-open-denied"
                    error openMessage number openNumber
                end try
                try
                    export convertedDocument to outputFile as PDF
                    close convertedDocument saving no
                    return "private-copy-exported-and-closed"
                on error messageText number messageNumber
                    try
                        close convertedDocument saving no
                    end try
                    error messageText number messageNumber
                end try
            end tell
        end timeout
    end run
    """
    private static let cleanupScript = """
    on run argv
        set privatePath to item 1 of argv
        with timeout of 4 seconds
            tell application id "com.apple.iWork.Pages"
                repeat with candidate in documents
                    set matchesPrivateCopy to false
                    set candidateFile to file of candidate
                    if candidateFile is not missing value then
                        set matchesPrivateCopy to ((POSIX path of (candidateFile as alias)) is privatePath)
                    end if
                    if matchesPrivateCopy then
                        close candidate saving no
                        return "private-copy-closed"
                    end if
                end repeat
            end tell
            return "private-copy-not-open"
        end timeout
    end run
    """

    static func convert(source: URL, destination: URL, control: PagesProcessControl) throws -> URL {
        try control.check()
        guard source.pathExtension.lowercased() == "pages", FileManager.default.isReadableFile(atPath: source.path) else { throw PagesConversionError.source }
        guard !FileManager.default.fileExists(atPath: destination.path), source.resolvingSymlinksInPath() != destination.resolvingSymlinksInPath() else { throw PagesConversionError.destination }
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Pages-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        var preserveTemporary = false
        var cleanup: PendingPagesCleanup?
        defer {
            if !preserveTemporary {
                try? FileManager.default.removeItem(at: temporary)
                cleanup?.finishUnusedOrClosed()
            }
        }
        let copied = try PagesPrivateCopy.create(source: source, in: temporary)
        let reserved = try PendingPagesCleanup(directory: temporary, document: copied)
        cleanup = reserved
        let exported = temporary.appendingPathComponent("resultado.pdf")
        try control.check()
        var knownClosedOrUnopened = false
        do {
            let output = try script(exportScript, arguments: [copied.path, exported.path], directory: temporary, timeout: 180, control: control)
            switch PagesScriptReceipt.parse(output) {
            case .openDenied:
                knownClosedOrUnopened = true
                throw PagesConversionError.automation
            case .exportedAndClosed: knownClosedOrUnopened = true
            default: throw PagesConversionError.export("O Pages não confirmou a conclusão da exportação e do fechamento.")
            }
        } catch {
            // Only the uniquely named private copy can be closed. This never
            // sends quit to Pages or closes another document belonging to it.
            guard control.didLaunch else { throw error }
            if knownClosedOrUnopened { throw error }
            do {
                try closePrivateCopy(copied, in: temporary, control: PagesProcessControl())
            } catch {
                // Pages can still own an in-flight AppleEvent after its sender
                // exits. Keep its backing copy when closure cannot be confirmed.
                preserveTemporary = true
                PagesCleanupRegistry.retain(reserved)
                throw PagesConversionError.cleanup("A exportação foi interrompida.", temporary.path)
            }
            throw error
        }
        try control.check()
        let handle: FileHandle
        do { handle = try FileHandle(forReadingFrom: exported) }
        catch { throw PagesConversionError.invalidPDF }
        defer { try? handle.close() }
        let limit = 512 * 1024 * 1024
        let data = try handle.read(upToCount: limit + 1) ?? Data()
        guard !data.isEmpty, data.count <= limit, let document = PDFDocument(data: data), document.pageCount > 0, !document.isLocked else { throw PagesConversionError.invalidPDF }
        try control.check()
        try NativeOutput.write(data, to: destination)
        return destination
    }

    static func closePrivateCopy(_ document: URL, in directory: URL, control: PagesProcessControl) throws {
        let receipt = try script(cleanupScript, arguments: [document.path], directory: directory, timeout: 6,
                                 control: control, completingCleanup: true)
        let confirmation = PagesScriptReceipt.parse(receipt)
        guard confirmation == .closed || confirmation == .notOpen else {
            throw PagesConversionError.cleanup("O Pages não confirmou o fechamento.", directory.path)
        }
    }

    @discardableResult private static func script(_ source: String, arguments: [String], directory: URL, timeout: TimeInterval, control: PagesProcessControl, completingCleanup: Bool = false) throws -> String {
        try control.check()
        let scriptURL = directory.appendingPathComponent("\(UUID().uuidString).applescript")
        try Data(source.utf8).write(to: scriptURL, options: .withoutOverwriting)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        // Paths travel only as argv. They are never interpolated into source
        // code, shell commands, AppleScript literals or an application selector.
        process.arguments = [scriptURL.path] + arguments
        process.standardInput = FileHandle.nullDevice
        return try runScriptProcess(process, timeout: timeout, control: control, completingCleanup: completingCleanup)
    }

    static func runScriptProcess(_ process: Process, timeout: TimeInterval, control: PagesProcessControl,
                                 completingCleanup: Bool = false, onExit: (() -> Void)? = nil) throws -> String {
        try control.check()
        let output = Pipe(), diagnostics = Pipe()
        process.standardOutput = output
        process.standardError = diagnostics
        let child = try OwnedChildProcess(configuration: process, completingCleanup: completingCleanup)
        control.attach(child)
        let diagnosticBytes = PagesScriptDiagnostics(), diagnosticReader = DispatchGroup()
        diagnosticReader.enter()
        DispatchQueue.global(qos: .utility).async {
            defer { try? diagnostics.fileHandleForReading.close(); diagnosticReader.leave() }
            do { _ = try child.collectOutput(from: diagnostics.fileHandleForReading) { diagnosticBytes.append($0) } }
            catch { diagnosticBytes.recordFailure(); child.cancel(grace: 2, signal: SIGTERM) }
        }
        let timeoutAction = DispatchWorkItem { control.timeout() }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: timeoutAction)
        defer {
            timeoutAction.cancel()
            child.cancel(grace: 2, signal: SIGTERM); _ = try? child.waitUntilExit()
            diagnosticReader.wait()
            try? output.fileHandleForReading.close()
            control.detach()
        }
        var log = Data()
        let exit = try child.collectOutput(from: output.fileHandleForReading) { chunk in
            if log.count < 65_536 { log.append(chunk.prefix(65_536 - log.count)) }
        }
        diagnosticReader.wait()
        onExit?()
        let (stderr, diagnosticFailure) = diagnosticBytes.snapshot
        guard !diagnosticFailure else { throw PagesConversionError.export("Não foi possível acompanhar a confirmação do Pages.") }
        if exit.status != 0 || exit.signalled {
            try control.check()
            let details = String(data: stderr, encoding: .utf8) ?? "Erro desconhecido."
            throw PagesConversionError.export(details.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        // A normal exit carries the trusted script's stdout receipt even when
        // cancellation arrives just afterwards. The caller still checks its
        // cancellation token before publishing any PDF, separately from cleanup.
        return String(data: log, encoding: .utf8) ?? ""
    }
}

@MainActor private final class PagesConversionController: ObservableObject {
    @Published var running = false
    @Published var error = ""
    @Published var result: URL?
    private var control: PagesProcessControl?

    func run(source: URL, destination: URL, completion: @escaping (Result<URL, Error>) -> Void) {
        guard !running, ApplicationWork.isAcceptingWork else { completion(.failure(CancellationError())); return }
        guard NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.iWork.Pages") != nil else {
            error = PagesConversionError.pagesMissing.localizedDescription
            completion(.failure(PagesConversionError.pagesMissing))
            return
        }
        let token = PagesProcessControl()
        control = token; running = true; result = nil; error = ""
        ApplicationTask.start(cancel: { token.cancel() }) { [self] in
            do {
                try Task.checkCancellation()
                let output = try await Task.detached(priority: .userInitiated) {
                    try PagesExporter.convert(source: source, destination: destination, control: token)
                }.value
                running = false; control = nil; result = output
                completion(.success(output))
            } catch {
                running = false; control = nil
                self.error = error is CancellationError ? "Conversão cancelada. O original foi preservado." : error.localizedDescription
                completion(.failure(error))
            }
        }
    }
    func cancel() { control?.cancel() }
}

struct PagesConversionView: View {
    @EnvironmentObject var model: Workspace
    @StateObject private var converter = PagesConversionController()
    @ObservedObject private var cleanup = PagesCleanupRegistry.shared
    @State private var source: URL?
    @State private var destination: URL?

    var body: some View {
        ScrollView {
        VStack(alignment: .leading, spacing: 22) {
            Label("Pages para PDF", systemImage: "doc.richtext").font(.system(size: 30, weight: .semibold, design: .rounded))
            Text("Exporte com o mecanismo nativo do Pages, preservando a composição do documento.").foregroundStyle(.secondary)
            GroupBox {
                VStack(alignment: .leading, spacing: 16) {
                    Label(source?.lastPathComponent ?? "Selecione um documento .pages", systemImage: "doc")
                    Button("Escolher documento…") { chooseSource() }
                    Divider()
                    Label(destination?.lastPathComponent ?? "Escolha um novo PDF de saída", systemImage: "square.and.arrow.down")
                    Button("Escolher destino…") { destination = NativeOutput.destination(model: model, toolName: "Pages para PDF", originalURL: source) }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(10)
            }.disabled(converter.running)
            Text("O Pages precisa estar instalado. Na primeira conversão, o macOS pode solicitar autorização para o PDF controlar o Pages. Uma cópia privada é usada para exportar; seu documento original permanece intacto.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Button("Abrir Pages na App Store", systemImage: "arrow.up.forward.app") {
                    if let url = URL(string: "macappstore://apps.apple.com/app/pages/id409201541") { NSWorkspace.shared.open(url) }
                }
                Spacer()
                if converter.running {
                    ProgressView().controlSize(.small)
                    Text("Exportando no Pages…").foregroundStyle(.secondary)
                    Button("Cancelar", role: .cancel) { converter.cancel() }
                } else {
                    Button("Converter para PDF", systemImage: "arrow.right.doc.on.clipboard") { convert() }
                        .buttonStyle(.borderedProminent).disabled(source == nil || destination == nil || model.busy)
                }
            }
            if !converter.error.isEmpty { Text(converter.error).foregroundStyle(.red).textSelection(.enabled) }
            if !cleanup.pending.isEmpty {
                GroupBox("Cópias privadas aguardando fechamento") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("O Pages ainda não confirmou o encerramento destas cópias. O PDF manterá a sessão aberta até a confirmação; seus documentos originais não serão fechados.")
                            .font(.callout)
                        ForEach(cleanup.pending) { item in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(item.document.lastPathComponent).lineLimit(2).help(item.document.lastPathComponent)
                                if let message = cleanup.messages[item.id] { Text(message).font(.callout).foregroundStyle(.secondary) }
                                Button("Tentar encerrar cópia privada") { cleanup.retry(item) }
                                    .disabled(cleanup.retrying.contains(item.id))
                                    .accessibilityLabel("Tentar encerrar a cópia privada \(item.document.lastPathComponent)")
                                    .accessibilityIdentifier("pdf.pages.cleanup.\(item.id.uuidString)")
                            }
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }
            }
            if let result = converter.result {
                HStack {
                    Label("PDF criado", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    Button("Abrir no leitor") { model.open(url: result); model.section = "Leitor" }
                    Button("Mostrar no Finder") { NSWorkspace.shared.activateFileViewerSelecting([result]) }
                }
            }
            Spacer()
        }
        .padding(30)
        }
        .onDisappear { converter.cancel() }
    }
    private func chooseSource() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "pages") ?? .data]
        panel.canChooseDirectories = false
        panel.treatsFilePackagesAsDirectories = false
        guard panel.runModal() == .OK, let selected = panel.url else { return }
        source = selected
    }
    private func convert() {
        guard let source, let destination, !model.busy else { return }
        model.busy = true
        model.externalCancellation = { converter.cancel() }
        model.message = "Convertendo com Pages…"
        converter.run(source: source, destination: destination) { result in
            model.busy = false
            model.externalCancellation = nil
            switch result {
            case .success(let url): model.lastOutput = url; model.message = "PDF criado pelo Pages."
            case .failure(let error): model.message = error is CancellationError ? "Conversão cancelada." : error.localizedDescription
            }
        }
    }
}

/// Validates copy isolation without launching Pages or asserting that an export
/// was performed. A real Pages export remains a separate integration check.
enum PagesPrivateCopyAuditChecks {
    static func run(in root: URL) throws {
        func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            guard condition() else { throw NSError(domain: "PDF.PagesCopyAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        let directory = root.appendingPathComponent("pages-copy-audit", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let original = directory.appendingPathComponent("original.pages")
        let bytes = Data("original-private-copy-check".utf8)
        try bytes.write(to: original, options: .withoutOverwriting)
        let link = directory.appendingPathComponent("alias.pages")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: original)
        let copied = try PagesPrivateCopy.create(source: link, in: directory)
        let properties = try copied.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey])
        try require(properties.isSymbolicLink != true && properties.isRegularFile == true, "A cópia privada ainda aponta para a origem.")
        try Data("changed-copy".utf8).write(to: copied)
        let retained = try Data(contentsOf: original)
        try require(retained == bytes, "Editar a cópia privada alterou o arquivo original.")
        let package = directory.appendingPathComponent("linked-package.pages", isDirectory: true)
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: false)
        try FileManager.default.createSymbolicLink(at: package.appendingPathComponent("outside"), withDestinationURL: original)
        var refused = false
        do { _ = try PagesPrivateCopy.create(source: package, in: directory) } catch { refused = true }
        try require(refused, "Um pacote com link externo foi entregue para conversão.")
    }
}

/// Real disposable child commands exercise failure/retry and file ownership.
/// This is not a Pages export or hardware/Automation integration claim.
@MainActor enum PagesCleanupAuditChecks {
    static func run() async throws {
        func require(_ value: Bool, _ detail: String) throws {
            guard value else { throw PreferenceError.invalid("Cleanup privado do Pages: " + detail) }
        }
        try await receiptContract()
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-pages-cleanup-audit-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: root); ApplicationWork.resumeAcceptingWork() }
        let privateDirectory = root.appendingPathComponent("private")
        try FileManager.default.createDirectory(at: privateDirectory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let original = root.appendingPathComponent("original.pages"), copy = privateDirectory.appendingPathComponent("copy.pages")
        let bytes = Data("private Pages cleanup verification".utf8)
        try NativeOutput.write(bytes, to: original); try NativeOutput.write(bytes, to: copy)
        let baseline = ApplicationWork.activeCount
        let pending = try PendingPagesCleanup(directory: privateDirectory, document: copy)
        // Keep the suite usable if an assertion fails; this fixture never asks
        // Pages to open anything and has no external document to leave behind.
        defer { pending.finishUnusedOrClosed() }
        let refused = await Task.detached { () -> Bool in
            do {
                try pending.finishConfirmed { try cleanupCommand(status: 17) }
                return false
            } catch { return true }
        }.value
        try require(refused && ApplicationWork.activeCount == baseline + 1, "a falha de confirmação liberou o ticket")
        let retainedCopy = try Data(contentsOf: copy), retainedOriginal = try Data(contentsOf: original)
        try require(retainedCopy == bytes && retainedOriginal == bytes, "a falha removeu a cópia privada ou alterou o original")
        let suite = "PDF.PagesCleanupAudit." + UUID().uuidString
        guard let defaults = UserDefaults(suiteName: suite) else { throw PreferenceError.invalid("Preferências isoladas indisponíveis.") }
        defer { defaults.removePersistentDomain(forName: suite) }
        let model = Workspace(defaults: defaults, recoveryStore: RecoveryStore(directory: root.appendingPathComponent("recovery")), enableRecoveryPolling: false)
        let allowed = await model.prepareForTermination(externalDeadline: 0.05)
        try require(!allowed && ApplicationWork.isAcceptingWork, "a saída aceitou um fechamento ainda não confirmado")
        let retainedDirectory = root.appendingPathComponent("retained-private")
        try FileManager.default.moveItem(at: privateDirectory, to: retainedDirectory)
        try FileManager.default.createDirectory(at: privateDirectory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let unrelated = Data("unrelated replacement".utf8)
        try NativeOutput.write(unrelated, to: copy)
        var rejectedReplacement = false
        do { try pending.finishConfirmed { try cleanupCommand(status: 0) } }
        catch { rejectedReplacement = true }
        let replacementBytes = try Data(contentsOf: copy)
        try require(rejectedReplacement && replacementBytes == unrelated && ApplicationWork.activeCount == baseline + 1,
                    "o retry aceitou ou removeu um diretório substituído")
        try FileManager.default.removeItem(at: privateDirectory)
        try FileManager.default.moveItem(at: retainedDirectory, to: privateDirectory)
        try await Task.detached { try pending.finishConfirmed { try cleanupCommand(status: 0) } }.value
        try require(ApplicationWork.activeCount == baseline && !FileManager.default.fileExists(atPath: privateDirectory.path),
                    "a nova confirmação não concluiu o registro e a limpeza")
        try require(try Data(contentsOf: original) == bytes, "o retry alterou o documento original")
        let ready = await model.prepareForTermination(externalDeadline: 1)
        try require(ready && model.authorizeTerminationIfUnchanged(), "o aplicativo permaneceu bloqueado após cleanup confirmado")
    }
    private static func receiptContract() async throws {
        for receipt in [PagesScriptReceipt.openDenied, .exportedAndClosed, .closed, .notOpen] {
            guard PagesScriptReceipt.parse(receipt.rawValue + "\n") == receipt else {
                throw PreferenceError.invalid("O recibo exato de fase não foi reconhecido.")
            }
        }
        for invalid in ["not authorized (-1743)", "error: private-copy-open-denied", "private-copy-closed\nprivate-copy-not-open", ""] {
            guard PagesScriptReceipt.parse(invalid) == nil else { throw PreferenceError.invalid("Texto genérico foi aceito como recibo de fechamento.") }
        }
        try await Task.detached {
            func command(_ script: String) -> Process {
                let configuration = Process()
                configuration.executableURL = URL(fileURLWithPath: "/bin/bash")
                configuration.arguments = ["--noprofile", "--norc", "-c", script]
                configuration.standardInput = FileHandle.nullDevice
                return configuration
            }
            let control = PagesProcessControl()
            let stdout = try PagesExporter.runScriptProcess(command("printf 'private-copy-exported-and-closed\\n'; printf 'private-copy-open-denied\\n' >&2"),
                timeout: 2, control: control, onExit: { control.cancel() })
            guard PagesScriptReceipt.parse(stdout) == .exportedAndClosed else {
                throw PreferenceError.invalid("O recibo normal foi perdido no cancelamento tardio ou misturado com stderr.")
            }
            var cancelled = false
            do { try control.check() } catch is CancellationError { cancelled = true }
            guard cancelled else { throw PreferenceError.invalid("Preservar o recibo perdeu o pedido de cancelamento.") }
            let fakeReceipt = try PagesExporter.runScriptProcess(command("printf 'private-copy-open-denied\\n' >&2"), timeout: 2, control: PagesProcessControl())
            guard PagesScriptReceipt.parse(fakeReceipt) == nil else {
                throw PreferenceError.invalid("Uma mensagem stderr passou a comprovar que o documento não foi aberto.")
            }
            var rejectedFailure = false
            do {
                _ = try PagesExporter.runScriptProcess(command("printf 'private-copy-open-denied\\n'; exit 17"), timeout: 2, control: PagesProcessControl())
            } catch { rejectedFailure = true }
            guard rejectedFailure else { throw PreferenceError.invalid("Um processo com falha produziu um recibo aprovado.") }
        }.value
    }
    nonisolated private static func cleanupCommand(status: Int) throws {
        let configuration = Process()
        configuration.executableURL = URL(fileURLWithPath: "/bin/bash")
        configuration.arguments = ["--noprofile", "--norc", "-c", "exit \"$1\"", "private-cleanup-audit", String(status)]
        configuration.standardInput = FileHandle.nullDevice; configuration.standardOutput = FileHandle.nullDevice; configuration.standardError = FileHandle.nullDevice
        let child = try OwnedChildProcess(configuration: configuration, completingCleanup: true)
        let exit = try child.waitUntilExit()
        guard !exit.signalled, exit.status == 0 else { throw PreferenceError.invalid("O comando privado não confirmou cleanup.") }
    }
}
