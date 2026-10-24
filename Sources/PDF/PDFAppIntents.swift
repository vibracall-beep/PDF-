import AppIntents
import AppKit
import PDFKit
import UniformTypeIdentifiers

struct PDFWorkflowEntity: AppEntity, Sendable {
    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Fluxo salvo do PDF"
    static var defaultQuery = PDFWorkflowQuery()
    let id: UUID
    let name: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(name)") }
}

struct PDFWorkflowQuery: EntityQuery {
    func entities(for identifiers: [UUID]) async throws -> [PDFWorkflowEntity] {
        let all = try await suggestedEntities()
        return identifiers.compactMap { identifier in all.first { $0.id == identifier } }
    }
    func suggestedEntities() async throws -> [PDFWorkflowEntity] {
        try await MainActor.run {
            try AutomationWorkflowBridge.saved().compactMap { item in
                guard (try? AutomationWorkflowBridge.options(item)) != nil else { return nil }
                return PDFWorkflowEntity(id: item.id, name: item.name)
            }
        }
    }
}

struct OpenPDFIntent: AppIntent {
    static var title: LocalizedStringResource = "Abrir PDF"
    static var description = IntentDescription("Importa uma cópia intacta do PDF para a biblioteca local e abre o leitor. PDFs protegidos pedem a senha no aplicativo; a senha não fica no atalho.")
    static var openAppWhenRun = true
    @Parameter(title: "Documento", supportedContentTypes: [.pdf]) var document: IntentFile

    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        let title = try await PDFShortcutsRuntime.shared.open(document)
        return .result(dialog: "\(title) foi aberto no PDF. Se estiver protegido, informe a senha na janela do aplicativo.")
    }
}

struct RunSavedPDFWorkflowIntent: AppIntent {
    static var title: LocalizedStringResource = "Executar fluxo do PDF"
    static var description = IntentDescription("Executa um fluxo salvo em uma cópia do documento, após confirmação. O PDF abre para escolher uma pasta de resultado nova; os originais são preservados. Fluxos que exigem senha devem ser executados manualmente no aplicativo.")
    static var openAppWhenRun = true
    @Parameter(title: "Documento", supportedContentTypes: [.pdf]) var document: IntentFile
    @Parameter(title: "Fluxo") var workflow: PDFWorkflowEntity

    @MainActor func perform() async throws -> some IntentResult & ProvidesDialog {
        try await requestConfirmation(conditions: [], actionName: .continue, dialog: "Executar o fluxo \(workflow.name)? O PDF solicitará uma nova pasta de resultados. O documento original será preservado.")
        let output = try await PDFShortcutsRuntime.shared.run(document, workflowID: workflow.id)
        return .result(dialog: "Fluxo concluído. Resultados em \(output.lastPathComponent).")
    }
}

struct PDFAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: OpenPDFIntent(), phrases: ["Abrir documento no \(.applicationName)"], shortTitle: "Abrir PDF", systemImageName: "doc.richtext")
        AppShortcut(intent: RunSavedPDFWorkflowIntent(), phrases: ["Executar fluxo no \(.applicationName)"], shortTitle: "Executar fluxo", systemImageName: "arrow.triangle.branch")
    }
}

/// A private, bounded copy gives Shortcuts transfers a lifetime independent of
/// the provider. Opening imports these exact bytes into the managed library;
/// workflow execution removes the temporary copy after completion/cancellation.
struct PDFShortcutInput: Sendable {
    let directory: URL
    let url: URL
    let fingerprint: String
    static func prepare(_ file: IntentFile) throws -> Self {
        try Task.checkCancellation()
        let bytes: Data
        if let url = file.fileURL {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            bytes = try LibraryFiles.read(url, maximum: LibraryFiles.maximumPDF)
        } else { bytes = file.data }
        guard !bytes.isEmpty, bytes.count <= LibraryFiles.maximumPDF, bytes.starts(with: Data("%PDF-".utf8)),
              let pdf = PDFDocument(data: bytes), pdf.isLocked || pdf.pageCount > 0 else {
            throw PreferenceError.invalid("O Atalho precisa receber um PDF válido de até 256 MiB.")
        }
        try Task.checkCancellation()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Shortcut-"+UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let filename = safeFilename(file.filename)
        let url = directory.appendingPathComponent(filename)
        do { try NativeOutput.write(bytes, to: url) }
        catch { try? FileManager.default.removeItem(at: directory); throw error }
        return Self(directory: directory, url: url, fingerprint: LibraryFiles.hash(bytes))
    }
    static func safeFilename(_ proposed: String) -> String {
        let leaf = URL(fileURLWithPath: proposed).lastPathComponent
        let stem = (leaf as NSString).deletingPathExtension
            .components(separatedBy: .controlCharacters).joined().replacingOccurrences(of: ":", with: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        var bounded = stem.isEmpty ? "Documento do Atalho" : stem
        while bounded.utf8.count > 180 { bounded.removeLast() }
        return bounded+".pdf"
    }
    func remove() { try? FileManager.default.removeItem(at: directory) }
}

@MainActor final class PDFShortcutsRuntime {
    static let shared = PDFShortcutsRuntime()
    private weak var model: Workspace?
    private var waiting: [UUID: CheckedContinuation<Workspace, Error>] = [:]
    private var activeExecution: UUID?
    func attach(model: Workspace) {
        self.model = model
        let continuations = Array(waiting.values); waiting.removeAll()
        for continuation in continuations { continuation.resume(returning: model) }
    }
    private func workspace() async throws -> Workspace {
        try Task.checkCancellation()
        if let model { return model }
        let identifier = UUID()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                waiting[identifier] = continuation
                Task { @MainActor [weak self] in
                    try? await Task.sleep(for: .seconds(15))
                    self?.waiting.removeValue(forKey: identifier)?.resume(throwing: PreferenceError.invalid("A janela do PDF não ficou disponível. Abra o aplicativo e execute o Atalho novamente."))
                }
            }
        } onCancel: {
            Task { @MainActor [weak self] in self?.waiting.removeValue(forKey: identifier)?.resume(throwing: CancellationError()) }
        }
    }
    func open(_ file: IntentFile) async throws -> String {
        let model = try await workspace()
        let input = try await Task.detached(priority: .userInitiated) { try PDFShortcutInput.prepare(file) }.value
        defer { input.remove() }
        try Task.checkCancellation()
        let library = DocumentLibraryStore()
        let report = try await library.importFiles([input.url])
        guard let item = report.catalog.documents.first(where: { $0.revisions.contains(where: { $0.fingerprint == input.fingerprint }) }),
              let revision = item.revisions.first(where: { $0.fingerprint == input.fingerprint }) else { throw LibraryFailure.missing }
        let source = try await library.verifiedURL(document: item.id, revision: revision.id)
        try Task.checkCancellation()
        NSApp.activate(ignoringOtherApps: true)
        model.open(url: source, page: nil, displayTitle: revision.labels.title); await model.waitForPendingOpen()
        if !model.sessions.contains(where: { $0.sourceURL == source }), !model.needsPassword { throw PreferenceError.invalid(model.message.isEmpty ? "Não foi possível abrir o PDF recebido." : model.message) }
        return revision.labels.title
    }
    func run(_ file: IntentFile, workflowID: UUID) async throws -> URL {
        let model = try await workspace()
        guard !model.busy, activeExecution == nil else { throw PreferenceError.invalid("Aguarde a tarefa atual do PDF terminar antes de executar outro Atalho.") }
        guard let workflow = try AutomationWorkflowBridge.saved().first(where: { $0.id == workflowID }) else { throw PreferenceError.invalid("O fluxo selecionado foi removido. Escolha novamente um fluxo salvo no Atalhos.") }
        let options = try AutomationWorkflowBridge.options(workflow)
        let input = try await Task.detached(priority: .userInitiated) { try PDFShortcutInput.prepare(file) }.value
        defer { input.remove() }
        try Task.checkCancellation()
        guard !model.busy, activeExecution == nil else { throw PreferenceError.invalid("Outra tarefa começou no PDF. Execute o Atalho novamente após a conclusão.") }
        NSApp.activate(ignoringOtherApps: true)
        guard let output = model.selectOutput(directory: true, toolName: workflow.name, originalURL: input.url) else { throw CancellationError() }
        try Task.checkCancellation()
        let token = UUID(); activeExecution = token
        defer { if activeExecution == token { activeExecution = nil } }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                model.execute(operation: "workflow", inputs: [input.url], output: output, options: options, title: "Atalhos · "+workflow.name, completion: { [weak self] result in
                    if self?.activeExecution == token { self?.activeExecution = nil }
                    continuation.resume(with: result)
                })
            }
        } onCancel: {
            Task { @MainActor [weak self, weak model] in
                // A later manual operation must never receive this cancellation.
                guard self?.activeExecution == token else { return }; model?.cancel()
            }
        }
    }
}
