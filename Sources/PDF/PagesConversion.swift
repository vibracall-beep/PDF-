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
                set convertedDocument to open sourceFile
                try
                    export convertedDocument to outputFile as PDF
                    close convertedDocument saving no
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
                    try
                        set matchesPrivateCopy to ((POSIX path of (file of candidate as alias)) is privatePath)
                    end try
                    if matchesPrivateCopy then
                        close candidate saving no
                        return
                    end if
                end repeat
            end tell
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
        defer { if !preserveTemporary { try? FileManager.default.removeItem(at: temporary) } }
        let copied = try PagesPrivateCopy.create(source: source, in: temporary)
        let exported = temporary.appendingPathComponent("resultado.pdf")
        try control.check()
        do {
            try script(exportScript, arguments: [copied.path, exported.path], directory: temporary, timeout: 180, control: control)
        } catch {
            // Only the uniquely named private copy can be closed. This never
            // sends quit to Pages or closes another document belonging to it.
            guard control.didLaunch else { throw error }
            if let failure = error as? PagesConversionError, case .automation = failure { throw error }
            do {
                try script(cleanupScript, arguments: [copied.path], directory: temporary, timeout: 6, control: PagesProcessControl(), completingCleanup: true)
            } catch {
                // Pages can still own an in-flight AppleEvent after its sender
                // exits. Keep its backing copy when closure cannot be confirmed.
                preserveTemporary = true
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

    private static func script(_ source: String, arguments: [String], directory: URL, timeout: TimeInterval, control: PagesProcessControl, completingCleanup: Bool = false) throws {
        try control.check()
        let scriptURL = directory.appendingPathComponent("\(UUID().uuidString).applescript")
        try Data(source.utf8).write(to: scriptURL, options: .withoutOverwriting)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        // Paths travel only as argv. They are never interpolated into source
        // code, shell commands, AppleScript literals or an application selector.
        process.arguments = [scriptURL.path] + arguments
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        let child = try OwnedChildProcess(configuration: process, completingCleanup: completingCleanup)
        control.attach(child)
        let timeoutAction = DispatchWorkItem { control.timeout() }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: timeoutAction)
        defer {
            timeoutAction.cancel()
            child.cancel(grace: 2, signal: SIGTERM); _ = try? child.waitUntilExit()
            try? output.fileHandleForReading.close()
            control.detach()
        }
        var log = Data()
        let exit = try child.collectOutput(from: output.fileHandleForReading) { chunk in
            if log.count < 65_536 { log.append(chunk.prefix(65_536 - log.count)) }
        }
        try control.check()
        if exit.status != 0 || exit.signalled {
            let details = String(data: log, encoding: .utf8) ?? "Erro desconhecido."
            if details.contains("-1743") || details.localizedCaseInsensitiveContains("not authorized") { throw PagesConversionError.automation }
            throw PagesConversionError.export(details.trimmingCharacters(in: .whitespacesAndNewlines))
        }
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
        ApplicationTask.start(cancel: { token.cancel() }) {
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
    @State private var source: URL?
    @State private var destination: URL?

    var body: some View {
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
