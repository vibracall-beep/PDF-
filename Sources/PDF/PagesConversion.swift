import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers
import Darwin

/// Runs Apple Pages on a private copy. The user's open documents and Pages
/// process are never terminated; only this application's osascript child is.
private final class PagesProcessControl: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false
    private var exceededTime = false

    func attach(_ value: Process) {
        lock.lock(); process = value; let stop = cancelled || exceededTime; lock.unlock()
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
    private func terminate(_ value: Process) {
        if value.isRunning { value.terminate() }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 2) {
            if value.isRunning { kill(value.processIdentifier, SIGKILL) }
        }
    }
}

private enum PagesConversionError: LocalizedError {
    case source, destination, pagesMissing, timeout, automation, export(String), invalidPDF
    var errorDescription: String? {
        switch self {
        case .source: return "Escolha um documento .pages acessível."
        case .destination: return "Escolha um nome novo para o PDF. Arquivos existentes serão preservados."
        case .pagesMissing: return "Instale o Pages pela App Store para usar esta conversão."
        case .timeout: return "O Pages não concluiu a exportação em 3 minutos. O arquivo original foi preservado."
        case .automation: return "Autorize PDF a controlar Pages em Ajustes do Sistema › Privacidade e Segurança › Automação, e repita a conversão."
        case .export(let reason): return "O Pages não concluiu a exportação: \(reason)"
        case .invalidPDF: return "O Pages não produziu um PDF legível dentro do limite de 512 MB."
        }
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
                    try
                        if (POSIX path of (file of candidate as alias)) is privatePath then
                            close candidate saving no
                        end if
                    end try
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
        defer { try? FileManager.default.removeItem(at: temporary) }
        let copied = temporary.appendingPathComponent("PDF-conversao-\(UUID().uuidString).pages")
        let exported = temporary.appendingPathComponent("resultado.pdf")
        try FileManager.default.copyItem(at: source, to: copied)
        try control.check()
        do {
            try script(exportScript, arguments: [copied.path, exported.path], directory: temporary, timeout: 180, control: control)
        } catch {
            // Only the uniquely named private copy can be closed. This never
            // sends quit to Pages or closes another document belonging to it.
            try? script(cleanupScript, arguments: [copied.path], directory: temporary, timeout: 6, control: PagesProcessControl())
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

    private static func script(_ source: String, arguments: [String], directory: URL, timeout: TimeInterval, control: PagesProcessControl) throws {
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
        try process.run()
        control.attach(process)
        let timeoutAction = DispatchWorkItem { control.timeout() }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: timeoutAction)
        defer {
            timeoutAction.cancel()
            if process.isRunning { control.cancel(); process.waitUntilExit() }
            control.detach()
        }
        var log = Data()
        while let chunk = try output.fileHandleForReading.read(upToCount: 8192), !chunk.isEmpty {
            if log.count < 65_536 { log.append(chunk.prefix(65_536 - log.count)) }
        }
        process.waitUntilExit()
        try control.check()
        if process.terminationStatus != 0 {
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
        guard !running else { return }
        guard NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.iWork.Pages") != nil else {
            error = PagesConversionError.pagesMissing.localizedDescription
            completion(.failure(PagesConversionError.pagesMissing))
            return
        }
        let token = PagesProcessControl()
        control = token; running = true; result = nil; error = ""
        Task { @MainActor in
            do {
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
                    Button("Escolher destino…") { destination = NativeOutput.destination(name: (source?.deletingPathExtension().lastPathComponent ?? "Pages") + ".pdf", type: .pdf) }
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
