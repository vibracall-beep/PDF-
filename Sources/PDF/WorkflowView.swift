import SwiftUI
import AppKit
import UniformTypeIdentifiers
import Darwin

private enum WorkflowOperation: String, Codable, CaseIterable, Identifiable {
    case rotate, numbers, compress, watermark, organize, crop, text, redact, protect, unlock, repair, ocr, pdfa, flatten
    case deletePages = "delete-pages"
    case extractPages = "extract-pages"
    case word, excel, powerpoint, markdown, jpg, png
    var id: String { rawValue }
    var title: String {
        switch self {
        case .rotate: return "Rodar páginas"
        case .numbers: return "Numerar páginas"
        case .compress: return "Comprimir"
        case .watermark: return "Marca d’água"
        case .organize: return "Organizar páginas"
        case .crop: return "Recortar margens"
        case .text: return "Adicionar texto"
        case .redact: return "Remover texto permanentemente"
        case .protect: return "Proteger com senha"
        case .unlock: return "Remover proteção"
        case .repair: return "Reparar documento"
        case .ocr: return "Reconhecer texto (OCR)"
        case .pdfa: return "Converter para PDF/A"
        case .flatten: return "Achatar anotações e formulários"
        case .deletePages: return "Excluir páginas"
        case .extractPages: return "Extrair páginas"
        case .word: return "Exportar para Word"
        case .excel: return "Exportar para Excel"
        case .powerpoint: return "Exportar para PowerPoint"
        case .markdown: return "Exportar para Markdown"
        case .jpg: return "Exportar páginas JPG"
        case .png: return "Exportar páginas PNG"
        }
    }
    var symbol: String {
        switch self {
        case .rotate: return "rotate.right"
        case .numbers: return "number"
        case .compress: return "arrow.down.right.and.arrow.up.left"
        case .watermark: return "drop"
        case .organize: return "square.grid.2x2"
        case .crop: return "crop"
        case .text: return "textformat"
        case .redact: return "eraser"
        case .protect: return "lock.shield"
        case .unlock: return "lock.open"
        case .repair: return "wrench"
        case .ocr: return "text.viewfinder"
        case .pdfa: return "archivebox"
        case .flatten: return "square.stack.3d.down.right"
        case .deletePages: return "doc.badge.minus"
        case .extractPages: return "doc.on.doc"
        case .word: return "doc.text"
        case .excel: return "tablecells"
        case .powerpoint: return "rectangle.on.rectangle"
        case .markdown: return "text.badge.checkmark"
        case .jpg, .png: return "photo.stack"
        }
    }
    var isTerminal: Bool { [.word, .excel, .powerpoint, .markdown, .jpg, .png].contains(self) }
    var outputDirectory: Bool { self == .jpg || self == .png }
    var outputSuffix: String {
        switch self {
        case .word: return "docx"
        case .excel: return "xlsx"
        case .powerpoint: return "pptx"
        case .markdown: return "md"
        case .jpg, .png: return ""
        default: return "pdf"
        }
    }
    var hasText: Bool { [.text, .watermark, .redact].contains(self) }
    var hasTypography: Bool { [.text, .watermark, .numbers].contains(self) }
    var hasStructuredOCR: Bool { [.word, .excel, .markdown].contains(self) }
    var acceptsPages: Bool { isTerminal || [.rotate, .numbers, .watermark, .organize, .crop, .text, .redact, .deletePages, .extractPages].contains(self) }
}

private struct WorkflowStage: Identifiable, Codable {
    var id = UUID()
    var operation: WorkflowOperation
    var pages = ""
    var text = ""
    var degrees = 90
    var fontSize = 14.0
    var margin = 24.0
    var opacity = 1.0
    var position = "bottom-center"
    var language = "por+eng"
    var dpi = 144.0
    var exportMode = "editable"
    var transparent = false
    var tableDetection = "ruled"
    var source = "auto"
    // Keep this separate from the historical OCRmyPDF language field: exports
    // previously omitted that field and the structured engine defaulted to eng.
    var ocrLanguage = "eng"
    var ocrDPI = 200.0
    var minConfidence = 35.0
    var ocrDeskew = false
    var usesStructuredOCR: Bool { operation.hasStructuredOCR && source != "vector" }

    private enum CodingKeys: String, CodingKey {
        case id, operation, pages, text, degrees, fontSize, margin, opacity, position, language, dpi, exportMode, transparent, tableDetection
        case source, ocrLanguage, ocrDPI, minConfidence, ocrDeskew
    }
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.init(operation: try values.decode(WorkflowOperation.self, forKey: .operation))
        id = try values.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        pages = try values.decodeIfPresent(String.self, forKey: .pages) ?? ""
        text = try values.decodeIfPresent(String.self, forKey: .text) ?? ""
        degrees = try values.decodeIfPresent(Int.self, forKey: .degrees) ?? degrees
        fontSize = try values.decodeIfPresent(Double.self, forKey: .fontSize) ?? fontSize
        margin = try values.decodeIfPresent(Double.self, forKey: .margin) ?? margin
        opacity = try values.decodeIfPresent(Double.self, forKey: .opacity) ?? opacity
        position = try values.decodeIfPresent(String.self, forKey: .position) ?? position
        language = try values.decodeIfPresent(String.self, forKey: .language) ?? language
        dpi = try values.decodeIfPresent(Double.self, forKey: .dpi) ?? dpi
        exportMode = try values.decodeIfPresent(String.self, forKey: .exportMode) ?? exportMode
        transparent = try values.decodeIfPresent(Bool.self, forKey: .transparent) ?? false
        tableDetection = try values.decodeIfPresent(String.self, forKey: .tableDetection) ?? "ruled"
        source = try values.decodeIfPresent(String.self, forKey: .source) ?? source
        ocrLanguage = try values.decodeIfPresent(String.self, forKey: .ocrLanguage) ?? ocrLanguage
        ocrDPI = try values.decodeIfPresent(Double.self, forKey: .ocrDPI) ?? ocrDPI
        minConfidence = try values.decodeIfPresent(Double.self, forKey: .minConfidence) ?? minConfidence
        ocrDeskew = try values.decodeIfPresent(Bool.self, forKey: .ocrDeskew) ?? false
    }

    init(operation: WorkflowOperation) {
        self.operation = operation
        if operation == .watermark { opacity = 0.35; position = "center"; fontSize = 32 }
        if operation == .text { position = "top-left" }
        if operation == .markdown { source = "vector" }
    }

    var options: [String: Any] {
        var result: [String: Any] = [:]
        if operation.acceptsPages && !pages.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { result["pages"] = pages }
        if operation.hasText { result["text"] = text }
        if operation.hasTypography {
            result["font_size"] = fontSize
            result["opacity"] = opacity
            result["position"] = position
            result["margin"] = margin
        }
        if operation == .rotate { result["degrees"] = degrees }
        if operation == .crop { result["margin"] = margin }
        if operation == .ocr || operation == .pdfa { result["language"] = language }
        if operation == .jpg || operation == .png { result["dpi"] = dpi; result["mode"] = "pages" }
        if operation == .png { result["alpha"] = transparent }
        if operation == .powerpoint { result["mode"] = exportMode }
        if operation.hasStructuredOCR {
            result["table_detection"] = tableDetection
            result["source"] = source
            if usesStructuredOCR {
                result["language"] = ocrLanguage
                result["ocr_dpi"] = ocrDPI
                result["min_confidence"] = minConfidence
                result["ocr_deskew"] = ocrDeskew
            }
        }
        return result
    }

    var validation: String? {
        if operation.hasText && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Informe o texto da etapa \(operation.title)."
        }
        if [.organize, .deletePages, .extractPages].contains(operation) && pages.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Informe as páginas da etapa \(operation.title)."
        }
        if !pages.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            for component in pages.split(separator: ",", omittingEmptySubsequences: false) {
                let range = component.split(separator: "-", omittingEmptySubsequences: false)
                guard (1...2).contains(range.count), range.allSatisfy({ part in
                    let trimmed = part.trimmingCharacters(in: .whitespaces)
                    return !trimmed.isEmpty && trimmed.allSatisfy({ "0123456789".contains($0) }) && (Int(trimmed) ?? 0) > 0
                }) else { return "Use números de página positivos e intervalos, por exemplo 1,3-5." }
            }
        }
        if !dpi.isFinite || !(36...600).contains(dpi) { return "A resolução deve ficar entre 36 e 600 DPI." }
        if !["editable", "image"].contains(exportMode) { return "Escolha uma apresentação editável ou como imagens." }
        if !["ruled", "aligned"].contains(tableDetection) { return "Escolha um modo válido de reconhecimento de tabelas." }
        if !["vector", "ocr", "auto"].contains(source) { return "Escolha uma origem válida: texto vetorial, OCR ou automática." }
        if !ocrDPI.isFinite || !(120...400).contains(ocrDPI) || ocrDPI.rounded() != ocrDPI { return "A resolução do OCR deve ser um número inteiro entre 120 e 400 DPI." }
        if !minConfidence.isFinite || !(0...100).contains(minConfidence) { return "O limiar de confiança do OCR deve ficar entre 0 e 100." }
        if !["por+eng", "por", "eng", "spa", "fra", "deu"].contains(ocrLanguage) { return "Escolha um idioma de OCR disponível na lista." }
        if !fontSize.isFinite || !(4...144).contains(fontSize) { return "O tamanho da fonte deve ficar entre 4 e 144 pontos." }
        if !margin.isFinite || !(0...500).contains(margin) { return "A margem deve ficar entre 0 e 500 pontos." }
        if !opacity.isFinite || !(0...1).contains(opacity) { return "A opacidade deve ficar entre 0 e 100%." }
        if ![90, 180, 270].contains(degrees) { return "Escolha uma rotação de 90°, 180° ou 270°." }
        if !["top-left", "top-center", "top-right", "center", "bottom-left", "bottom-center", "bottom-right"].contains(position) {
            return "Escolha uma posição válida para o texto."
        }
        if !["por+eng", "por", "eng", "spa", "fra", "deu"].contains(language) { return "Escolha um idioma de OCR disponível na lista." }
        return nil
    }
}

private struct WorkflowPreset: Identifiable, Codable {
    var id = UUID()
    var version = 2
    var name = "Meu fluxo"
    var stages: [WorkflowStage] = [WorkflowStage(operation: .rotate), WorkflowStage(operation: .numbers)]

    var validation: String? {
        if ![1, 2].contains(version) { return "Esta versão de fluxo não é compatível." }
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Dê um nome ao fluxo." }
        if name.count > 120 { return "Use um nome com até 120 caracteres." }
        if stages.isEmpty { return "Adicione ao menos uma etapa." }
        if stages.count > 24 { return "Use no máximo 24 etapas por fluxo." }
        if Set(stages.map(\.id)).count != stages.count { return "O fluxo contém etapas com identificadores repetidos." }
        for (index, stage) in stages.enumerated() {
            if let error = stage.validation { return "Etapa \(index + 1): \(error)" }
            if stage.operation.isTerminal && index != stages.count - 1 { return "A exportação deve ser a última etapa: o resultado deixa de ser um PDF." }
            if stage.operation == .protect && index != stages.count - 1 { return "A proteção por senha deve ser a última etapa." }
            if stage.operation == .unlock && index != 0 { return "A remoção da proteção deve ser a primeira etapa." }
            if stage.operation == .pdfa && index != stages.count - 1 { return "A conversão para PDF/A deve ser a última etapa para preservar a conformidade." }
        }
        return nil
    }
}

@MainActor private final class WorkflowLibrary: ObservableObject {
    @Published private(set) var presets: [WorkflowPreset] = []
    @Published var error = ""
    private var directory: URL?

    init(directory suppliedDirectory: URL? = nil) {
        do {
            let path: URL
            if let suppliedDirectory { path = suppliedDirectory }
            else {
                let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
                path = base.appendingPathComponent("PDF/Workflows", isDirectory: true)
            }
            try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: path.path)
            directory = path
            let urls = try FileManager.default.contentsOfDirectory(at: path, includingPropertiesForKeys: [.fileSizeKey]).filter { $0.pathExtension == "json" }
            for url in urls {
                do {
                    let preset = try Self.read(url)
                    guard preset.validation == nil else { throw WorkflowError.invalid(preset.validation ?? "Fluxo inválido.") }
                    guard !presets.contains(where: { $0.id == preset.id }) else { continue }
                    presets.append(preset)
                } catch {
                    self.error = "Não foi possível carregar \(url.lastPathComponent): \(error.localizedDescription)"
                }
            }
            presets.sort { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        } catch { self.error = "Não foi possível abrir a biblioteca de fluxos: \(error.localizedDescription)" }
    }

    static func read(_ url: URL) throws -> WorkflowPreset {
        // Open without following a final symlink and verify the descriptor before
        // reading. A .json-named FIFO/device must never block the UI or leak data.
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard descriptor >= 0 else { throw WorkflowError.invalid("Selecione um arquivo JSON comum e acessível, sem link simbólico.") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG) else {
            throw WorkflowError.invalid("O fluxo precisa ser um arquivo JSON comum.")
        }
        guard info.st_size >= 0, info.st_size <= 1_048_576 else { throw WorkflowError.invalid("O arquivo excede 1 MB.") }
        let data = try handle.read(upToCount: 1_048_577) ?? Data()
        guard data.count <= 1_048_576 else { throw WorkflowError.invalid("O arquivo excede 1 MB.") }
        if let object = try JSONSerialization.jsonObject(with: data) as? [String: Any], let stages = object["stages"] as? [[String: Any]] {
            for stage in stages {
                if let operation = stage["operation"] as? String, WorkflowOperation(rawValue: operation) == nil {
                    if operation.hasPrefix("form") {
                        throw WorkflowError.invalid("Esta etapa de formulários não é compatível com fluxos salvos. Use a ferramenta Formulários para revisar campos e valores antes de executar.")
                    }
                    throw WorkflowError.invalid("Etapa não compatível neste editor: \(operation.prefix(80)). Atualize o aplicativo ou revise o fluxo.")
                }
            }
        }
        return try JSONDecoder().decode(WorkflowPreset.self, from: data)
    }

    static func encode(_ preset: WorkflowPreset) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        var current = preset; current.version = 2
        return try encoder.encode(current)
    }

    func delete(_ preset: WorkflowPreset) throws {
        guard let directory else { throw WorkflowError.invalid("A biblioteca de fluxos não está disponível.") }
        let target = directory.appendingPathComponent(preset.id.uuidString).appendingPathExtension("json")
        try FileManager.default.trashItem(at: target, resultingItemURL: nil)
        presets.removeAll { $0.id == preset.id }
        error = ""
    }

    func save(_ preset: WorkflowPreset) throws {
        if let validation = preset.validation { throw WorkflowError.invalid(validation) }
        guard let directory else { throw WorkflowError.invalid("A biblioteca de fluxos não está disponível.") }
        let target = directory.appendingPathComponent(preset.id.uuidString).appendingPathExtension("json")
        try Self.encode(preset).write(to: target, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
        if let index = presets.firstIndex(where: { $0.id == preset.id }) { presets[index] = preset }
        else { presets.append(preset) }
        presets.sort { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        error = ""
    }
}

private enum WorkflowRequest {
    static func validation(preset: WorkflowPreset, sourcePassword: String, destinationPassword: String) -> String? {
        if let error = preset.validation { return error }
        if preset.stages.contains(where: { $0.operation == .protect }), !(8...40).contains(destinationPassword.unicodeScalars.count) {
            return "Use uma nova senha com 8 a 40 caracteres Unicode."
        }
        return nil
    }
    static func make(preset: WorkflowPreset, sourcePassword: String, destinationPassword: String) throws -> [String: Any] {
        if let error = validation(preset: preset, sourcePassword: sourcePassword, destinationPassword: destinationPassword) { throw WorkflowError.invalid(error) }
        let steps: [[String: Any]] = preset.stages.enumerated().map { index, stage in
            var options = stage.options
            if index == 0 && !sourcePassword.isEmpty { options["password"] = sourcePassword }
            if stage.operation == .protect { options["new_password"] = destinationPassword }
            return ["operation": stage.operation.rawValue, "options": options]
        }
        var options: [String: Any] = ["steps": steps]
        if !sourcePassword.isEmpty { options["password"] = sourcePassword }
        return options
    }
    static func make(preset: WorkflowPreset, sourcePasswords: [String], destinationPassword: String) throws -> [String: Any] {
        guard !sourcePasswords.isEmpty else { throw WorkflowError.invalid("Selecione ao menos um PDF.") }
        for password in sourcePasswords {
            if let error = validation(preset: preset, sourcePassword: password, destinationPassword: destinationPassword) { throw WorkflowError.invalid(error) }
        }
        var result = try make(preset: preset, sourcePassword: sourcePasswords[0], destinationPassword: destinationPassword)
        result["progress"] = true
        if sourcePasswords.count > 1 {
            result.removeValue(forKey: "password")
            var steps = result["steps"] as? [[String: Any]] ?? []
            if !steps.isEmpty {
                var options = steps[0]["options"] as? [String: Any] ?? [:]
                options.removeValue(forKey: "password"); steps[0]["options"] = options
            }
            result["steps"] = steps; result["batch"] = true; result["input_passwords"] = sourcePasswords
        }
        return result
    }

}

private enum WorkflowError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let text) = self { return text }; return nil }
}

/// A validated copy of a saved workflow. Automation never stores document passwords.
struct AutomationWorkflow: Codable, Identifiable {
    var id: UUID
    var name: String
    var data: Data
}
@MainActor enum AutomationWorkflowBridge {
    static func saved(directory:URL? = nil) throws -> [AutomationWorkflow] {
        let library = WorkflowLibrary(directory:directory)
        guard library.error.isEmpty else { throw WorkflowError.invalid(library.error) }
        return try library.presets.map { .init(id:$0.id,name:$0.name,data:try WorkflowLibrary.encode($0)) }
    }
    static func options(_ workflow:AutomationWorkflow) throws -> [String:Any] {
        guard workflow.data.count <= 1_048_576 else { throw WorkflowError.invalid("O fluxo excede 1 MB.") }
        let preset = try JSONDecoder().decode(WorkflowPreset.self,from:workflow.data)
        guard preset.id == workflow.id,preset.name == workflow.name else { throw WorkflowError.invalid("A identidade do fluxo não corresponde à configuração salva.") }
        if let message = preset.validation { throw WorkflowError.invalid(message) }
        guard !preset.stages.contains(where:{$0.operation == .protect || $0.operation == .unlock}) else { throw WorkflowError.invalid("Pastas monitoradas não guardam senhas. Execute fluxos de proteção/desbloqueio manualmente.") }
        var options = try WorkflowRequest.make(preset:preset,sourcePasswords:[""],destinationPassword:"")
        options["batch"] = true; options["input_passwords"] = [""]
        return options
    }
}

struct WorkflowView: View {
    @EnvironmentObject var model: Workspace
    @StateObject private var library: WorkflowLibrary
    @State private var preset = WorkflowPreset()
    @State private var inputs: [URL] = []
    @State private var output: URL?
    @State private var sourcePasswords: [String] = []
    @State private var destinationPassword = ""
    @State private var error = ""
    @State private var status = ""
    @State private var confirmDelete = false
    @State private var completed = 0
    @State private var total = 0
    @State private var running = false
    @State private var checkingDependencies = false
    @State private var dependencyError = ""
    @State private var dependencyTask: Task<Void, Never>?

    init(initialInputs: [URL] = [], finalExport: String? = nil, libraryDirectory: URL? = nil) {
        _library = StateObject(wrappedValue: WorkflowLibrary(directory: libraryDirectory))
        _inputs = State(initialValue: initialInputs)
        _sourcePasswords = State(initialValue: Array(repeating: "", count: initialInputs.count))
        var initial = WorkflowPreset()
        if let finalExport, let operation = WorkflowOperation(rawValue: finalExport), operation.isTerminal {
            initial.stages.append(WorkflowStage(operation: operation))
        }
        _preset = State(initialValue: initial)
    }

    private var terminal: WorkflowOperation { preset.stages.last?.operation ?? .rotate }
    private var outputIsDirectory: Bool { inputs.count > 1 || terminal.outputDirectory }
    private var outputKind: String { "\(outputIsDirectory)-\(terminal.outputSuffix)" }

    private var requiresDestinationPassword: Bool { preset.stages.contains { $0.operation == .protect } }
    private var validation: String? {
        if let error = preset.validation { return error }
        if checkingDependencies { return "Verificando dependências locais do fluxo…" }
        if !dependencyError.isEmpty { return dependencyError }
        if inputs.isEmpty { return "Escolha um ou mais PDFs de entrada." }
        if inputs.count > 1000 { return "Use no máximo 1.000 PDFs por lote." }
        if sourcePasswords.count != inputs.count { return "Selecione novamente os documentos de entrada." }
        for (index, input) in inputs.enumerated() {
            if let error = WorkflowRequest.validation(preset: preset, sourcePassword: sourcePasswords[index], destinationPassword: destinationPassword) { return "Arquivo \(index + 1): \(error)" }
            if !FileManager.default.isReadableFile(atPath: input.path) { return "O PDF \(input.lastPathComponent) não está acessível." }
        }
        guard let output else { return "Escolha onde salvar o resultado." }
        if inputs.contains(where: { $0.resolvingSymlinksInPath() == output.resolvingSymlinksInPath() }) { return "Escolha um novo destino para preservar os originais." }
        if FileManager.default.fileExists(atPath: output.path) { return "Já existe um arquivo no destino. Escolha outro nome." }
        if !outputIsDirectory && output.pathExtension.lowercased() != terminal.outputSuffix { return "Escolha um destino com extensão .\(terminal.outputSuffix)." }
        return nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Group {
                    header
                    documentSelection
                    stagesSection
                    passwordSection
                    footer
                }.disabled(model.busy)
                if running {
                    HStack {
                        ProgressView(value: Double(completed), total: Double(max(total, 1)))
                        VStack(alignment: .trailing, spacing: 2) {
                            Text("\(completed)/\(total) etapas")
                            Text("\(min(inputs.count, completed / max(preset.stages.count, 1)))/\(inputs.count) arquivos processados")
                        }.font(.caption.monospacedDigit())
                        Button("Cancelar") { model.cancel() }
                    }
                    Text(outputIsDirectory ? "A pasta final será publicada somente quando todos os arquivos terminarem." : "O resultado será publicado somente ao concluir todas as etapas.").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(28)
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .onAppear { verifyDependencies() }
        .onChange(of: outputKind) { _, _ in output = nil }
        .onChange(of: preset.stages.map { $0.operation.rawValue }) { _, _ in verifyDependencies() }
        .onDisappear { clearPasswords(); dependencyTask?.cancel(); checkingDependencies = false }
        .alert("Excluir este fluxo da biblioteca?", isPresented: $confirmDelete) {
            Button("Cancelar", role: .cancel) { }
            Button("Mover para o Lixo", role: .destructive) {
                do {
                    try library.delete(preset)
                    preset.id = UUID()
                    status = "Fluxo movido para o Lixo. As etapas continuam abertas neste editor."
                    error = ""
                } catch { self.error = error.localizedDescription }
            }
        } message: {
            Text("O arquivo do fluxo será movido para o Lixo. Seus documentos não serão alterados.")
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Seu fluxo, do seu jeito", systemImage: "point.3.connected.trianglepath.dotted")
                .font(.system(size: 30, weight: .semibold, design: .rounded))
            Text("Combine ferramentas e finalize em PDF, Word, Excel, PowerPoint, Markdown ou imagens. Processe um documento ou um lote privado.")
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                TextField("Nome do fluxo", text: $preset.name).textFieldStyle(.roundedBorder).frame(maxWidth: 350)
                Menu("Meus fluxos", systemImage: "folder") {
                    if library.presets.isEmpty { Text("Nenhum fluxo salvo") }
                    ForEach(library.presets) { item in
                        Button(item.name) { load(item) }
                    }
                }
                Button("Salvar", systemImage: "square.and.arrow.down") { savePreset() }
                Menu("Mais", systemImage: "ellipsis.circle") {
                    Button("Novo fluxo") { load(WorkflowPreset()) }
                    Button("Duplicar fluxo") {
                        preset.id = UUID(); preset.name += " — cópia"
                        status = "Cópia criada. Salve para adicioná-la à biblioteca."
                    }
                    Divider()
                    Button("Importar fluxo…") { importPreset() }
                    Button("Exportar fluxo…") { exportPreset() }
                    Divider()
                    Button("Excluir da biblioteca", role: .destructive) { confirmDelete = true }
                        .disabled(!library.presets.contains(where: { $0.id == preset.id }))
                }
            }
            Button("Verificar dependências", systemImage: "checkmark.shield") { verifyDependencies() }.font(.caption).disabled(checkingDependencies)
            if !library.error.isEmpty { Text(library.error).font(.caption).foregroundStyle(.red).textSelection(.enabled) }
        }
    }

    private var documentSelection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 16) {
                fileCard(title: "1. Documentos de entrada", filename: inputs.isEmpty ? "Escolha PDFs" : "\(inputs.count) documento(s) selecionado(s)", symbol: "doc.on.doc", action: chooseInput)
                Image(systemName: "arrow.right").foregroundStyle(.secondary).padding(.top, 42)
                fileCard(title: outputIsDirectory ? "2. Nova pasta de saída" : "2. Novo arquivo .\(terminal.outputSuffix)", filename: output?.lastPathComponent ?? "Escolha um novo destino", symbol: outputIsDirectory ? "folder" : "doc.badge.arrow.up", action: chooseOutput)
            }
            if inputs.count > 1 {
                Text("Cada PDF recebe a mesma sequência, com sua própria senha. Nomes numerados evitam colisões; uma falha cancela a publicação da pasta inteira.").font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func fileCard(title: String, filename: String, symbol: String, action: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(.headline)
            Button(action: action) {
                Label(filename, systemImage: symbol).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
            }.buttonStyle(.bordered).controlSize(.large)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private var stagesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Etapas").font(.title2.bold())
                Text("\(preset.stages.count)/24").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Menu("Adicionar etapa", systemImage: "plus") {
                    ForEach(WorkflowOperation.allCases) { operation in
                        Button(operation.title, systemImage: operation.symbol) {
                            preset.stages.append(WorkflowStage(operation: operation)); preset.version = 2
                        }
                    }
                }.disabled(preset.stages.count >= 24)
            }
            Text("Etapas recebem PDF. Exportações Word, Excel, PowerPoint, Markdown, JPG e PNG encerram o fluxo. Criação e preenchimento de formulários continuam nas ferramentas próprias, onde campos podem ser revisados.").font(.caption).foregroundStyle(.secondary)
            if preset.stages.isEmpty {
                ContentUnavailableView("Crie sua sequência", systemImage: "list.number", description: Text("Adicione uma ferramenta para começar."))
            }
            ForEach($preset.stages) { $stage in
                WorkflowStageEditor(
                    stage: $stage,
                    number: (preset.stages.firstIndex(where: { $0.id == stage.id }) ?? 0) + 1,
                    canMoveUp: preset.stages.first?.id != stage.id,
                    canMoveDown: preset.stages.last?.id != stage.id,
                    moveUp: { move(stage.id, delta: -1) },
                    moveDown: { move(stage.id, delta: 1) },
                    remove: { preset.stages.removeAll { $0.id == stage.id } }
                )
            }
        }
    }

    private var passwordSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Proteção do documento").font(.headline)
            ForEach(inputs.indices, id: \.self) { index in
                HStack {
                    Text("\(index + 1). \(inputs[index].lastPathComponent)").lineLimit(1).frame(maxWidth: 300, alignment: .leading)
                    SecureField("Senha deste PDF, se houver", text: Binding(get: { sourcePasswords.indices.contains(index) ? sourcePasswords[index] : "" }, set: { if sourcePasswords.indices.contains(index) { sourcePasswords[index] = $0 } }))
                        .textFieldStyle(.roundedBorder)
                }
            }
            if requiresDestinationPassword {
                SecureField("Nova senha do resultado, 8 a 40 caracteres", text: $destinationPassword).textFieldStyle(.roundedBorder)
            }
            Text("Senhas são usadas apenas nesta execução e nunca são salvas nos fluxos.").font(.caption).foregroundStyle(.secondary)
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let validation { Label(validation, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary) }
            if !error.isEmpty { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            if !status.isEmpty { Text(status).foregroundStyle(.secondary).textSelection(.enabled) }
            HStack {
                Text("O original permanece intacto. Etapas são executadas na ordem acima.").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(inputs.count > 1 ? "Executar lote" : "Executar fluxo", systemImage: "play.fill") { execute() }
                    .buttonStyle(.borderedProminent).controlSize(.large).disabled(validation != nil)
            }
        }
    }

    private func move(_ id: UUID, delta: Int) {
        guard let index = preset.stages.firstIndex(where: { $0.id == id }) else { return }
        let destination = index + delta
        guard preset.stages.indices.contains(destination) else { return }
        withAnimation { preset.stages.swapAt(index, destination) }
    }
    private func load(_ item: WorkflowPreset) {
        preset = item; clearPasswords(); error = ""; status = ""; dependencyError = ""; verifyDependencies()
    }
    private func clearPasswords() { sourcePasswords = Array(repeating: "", count: inputs.count); destinationPassword = "" }
    private func chooseInput() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]; panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
        if panel.runModal() == .OK { inputs = panel.urls; clearPasswords(); error = "" }
    }
    private func chooseOutput() {
        if let url = model.selectOutput(extension: terminal.outputSuffix, directory: outputIsDirectory, toolName: "Fluxo", originalURL: inputs.first) { output = url; error = "" }
    }
    private func savePreset() {
        do { try library.save(preset); error = ""; status = "Fluxo salvo na sua biblioteca." }
        catch { self.error = error.localizedDescription }
    }
    private func importPreset() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            var imported = try WorkflowLibrary.read(url)
            if let validation = imported.validation { throw WorkflowError.invalid(validation) }
            imported.id = UUID()
            load(imported)
            status = "Fluxo importado. Revise as etapas e salve na biblioteca."
        } catch { self.error = "Não foi possível importar: \(error.localizedDescription)" }
    }
    private func exportPreset() {
        if let validation = preset.validation { error = validation; return }
        guard let url = NativeOutput.destination(model: model, toolName: "Configuração de fluxo", extension: "json",
            originalName: "PDF-fluxo.json") else { return }
        do {
            try NativeOutput.write(WorkflowLibrary.encode(preset), to: url)
            error = ""; status = "Fluxo exportado sem senhas ou caminhos de documentos."
        } catch { self.error = "Não foi possível exportar em um arquivo novo: \(error.localizedDescription)" }
    }
    private func verifyDependencies() {
        dependencyTask?.cancel()
        let stages = preset.stages.map { ["operation": $0.operation.rawValue] }
        guard let data = try? JSONSerialization.data(withJSONObject: stages) else { return }
        checkingDependencies = true; dependencyError = ""
        dependencyTask = Task { @MainActor in
            do {
                try await Task.detached { try WorkflowDependencies.check(data) }.value
                guard !Task.isCancelled else { return }
                checkingDependencies = false
                status = "Fluxo validado; dependências das etapas disponíveis. Os dados e idiomas OCR serão verificados durante a execução."
            } catch {
                guard !Task.isCancelled else { return }
                checkingDependencies = false; dependencyError = error.localizedDescription
            }
        }
    }
    private func execute() {
        if let validation { error = validation; return }
        guard let output else { return }
        do {
            let options = try WorkflowRequest.make(preset: preset, sourcePasswords: sourcePasswords, destinationPassword: destinationPassword)
            error = ""; status = ""; completed = 0; total = inputs.count * preset.stages.count; running = true
            model.execute(operation: "workflow", inputs: inputs, output: output, options: options, title: preset.name, progress: { done, count in
                completed = done; total = count
            }, completion: { result in
                running = false
                switch result {
                case .success: status = "Fluxo concluído: \(output.lastPathComponent)."
                case .failure(let failure): error = "O fluxo foi interrompido. Nenhum resultado parcial foi publicado. \(failure.localizedDescription)"
                }
            })
        } catch { self.error = error.localizedDescription }
        clearPasswords()
    }

}

private struct WorkflowStageEditor: View {
    @Binding var stage: WorkflowStage
    let number: Int
    let canMoveUp: Bool
    let canMoveDown: Bool
    let moveUp: () -> Void
    let moveDown: () -> Void
    let remove: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Text("\(number)").font(.headline.monospacedDigit()).frame(width: 30, height: 30).background(Color.accentColor.opacity(0.12), in: Circle())
                Label(stage.operation.title, systemImage: stage.operation.symbol).font(.headline)
                Spacer()
                Button(action: moveUp) { Image(systemName: "arrow.up") }.disabled(!canMoveUp).help("Mover etapa para cima")
                Button(action: moveDown) { Image(systemName: "arrow.down") }.disabled(!canMoveDown).help("Mover etapa para baixo")
                Button(role: .destructive, action: remove) { Image(systemName: "trash") }.help("Remover etapa")
            }
            options
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.primary.opacity(0.08)))
    }

    @ViewBuilder private var options: some View {
        if stage.operation.acceptsPages {
            TextField(pagePlaceholder, text: $stage.pages)
                .textFieldStyle(.roundedBorder)
        }
        if stage.operation.hasText {
            TextField(stage.operation == .redact ? "Texto a remover permanentemente" : "Texto a inserir", text: $stage.text)
                .textFieldStyle(.roundedBorder)
        }
        if stage.operation.hasTypography {
            typography
        }
        if stage.operation == .rotate {
            Picker("Rotação", selection: $stage.degrees) { Text("90°").tag(90); Text("180°").tag(180); Text("270°").tag(270) }
                .pickerStyle(.segmented).frame(maxWidth: 300)
        }
        if stage.operation == .crop {
            HStack {
                Text("Margem em pontos")
                TextField("Margem", value: $stage.margin, format: .number).frame(width: 80).textFieldStyle(.roundedBorder)
                Text("O recorte altera a área visível, sem apagar o conteúdo oculto.").font(.caption).foregroundStyle(.secondary)
            }
        }
        if stage.operation == .ocr || stage.operation == .pdfa {
            Picker("Idioma", selection: $stage.language) {
                Text("Português + inglês").tag("por+eng"); Text("Português").tag("por"); Text("Inglês").tag("eng")
                Text("Espanhol").tag("spa"); Text("Francês").tag("fra"); Text("Alemão").tag("deu")
            }.frame(maxWidth: 350)
            Text("Requer o mecanismo OCR e os idiomas selecionados instalados no Mac.").font(.caption).foregroundStyle(.secondary)
        }
        if stage.operation.isTerminal {
            Text("Saída final: \(stage.operation.outputDirectory ? "pasta de imagens" : "." + stage.operation.outputSuffix). Esta etapa deve encerrar o fluxo.").font(.caption).foregroundStyle(.secondary)
            if stage.operation.hasStructuredOCR {
                Picker("Origem do texto", selection: $stage.source) {
                    Text("Texto vetorial existente").tag("vector")
                    Text("OCR das páginas").tag("ocr")
                    Text("Automática: OCR em digitalizações").tag("auto")
                }
                Picker("Reconhecimento de tabelas", selection: $stage.tableDetection) {
                    Text("Grades com linhas").tag("ruled")
                    Text("Incluir colunas alinhadas sem bordas").tag("aligned")
                }
                if stage.usesStructuredOCR { structuredOCROptions }
                Text("A reconstrução de texto, tabelas e layout depende do documento. A origem automática usa OCR apenas em páginas com imagem e sem texto selecionável; a origem OCR força o reconhecimento.").font(.caption).foregroundStyle(.secondary)
            }
        }
        if stage.operation == .powerpoint {
            Picker("Conteúdo dos slides", selection: $stage.exportMode) { Text("Objetos editáveis").tag("editable"); Text("Imagem de cada página").tag("image") }.frame(maxWidth: 420)
        }
        if stage.operation == .jpg || stage.operation == .png {
            HStack {
                Text("Resolução DPI")
                TextField("DPI", value: $stage.dpi, format: .number).frame(width: 90).textFieldStyle(.roundedBorder)
                if stage.operation == .png { Toggle("Fundo transparente", isOn: $stage.transparent) }
            }
        }
        if stage.operation == .redact { Text("A remoção é permanente no resultado. O original será preservado.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .protect { Text("Esta etapa deve ser a última. Informe a nova senha na seção Proteção do documento.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .unlock { Text("Esta etapa deve ser a primeira. PDFs protegidos exigem a senha atual; PDFs sem proteção também podem participar do lote.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .compress { Text("O motor reorganiza os dados do documento. A redução depende do conteúdo original.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .repair { Text("Tenta regravar documentos que o mecanismo consegue recuperar.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .flatten { Text("Incorpora anotações e valores dos formulários à página. Os campos deixam de ser editáveis no resultado.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .deletePages { Text("Exclui as páginas indicadas da cópia de saída. O documento precisa manter ao menos uma página.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .extractPages { Text("Mantém apenas as páginas indicadas, na ordem escolhida. Páginas podem ser repetidas.").font(.caption).foregroundStyle(.secondary) }
    }

    private var structuredOCROptions: some View {
        VStack(alignment: .leading, spacing: 10) {
            Picker("Idioma do OCR", selection: $stage.ocrLanguage) {
                Text("Português + inglês").tag("por+eng"); Text("Português").tag("por"); Text("Inglês").tag("eng")
                Text("Espanhol").tag("spa"); Text("Francês").tag("fra"); Text("Alemão").tag("deu")
            }.frame(maxWidth: 350)
            HStack(spacing: 16) {
                Text("OCR DPI (120–400)")
                TextField("DPI", value: $stage.ocrDPI, format: .number).frame(width: 80).textFieldStyle(.roundedBorder)
                Text("Confiança mínima (0–100)")
                TextField("Limiar", value: $stage.minConfidence, format: .number).frame(width: 80).textFieldStyle(.roundedBorder)
            }
            Toggle("Corrigir inclinação da imagem temporária de OCR", isOn: $stage.ocrDeskew)
            Text("A correção depende de linhas de grade e limita-se a ±7°. O PDF original não é alterado. Palavras abaixo do limiar continuam na exportação e são sinalizadas para revisão; o escore não mede a precisão factual.")
                .font(.caption).foregroundStyle(.secondary)
            Text("Requer Tesseract e os idiomas selecionados instalados. A disponibilidade dos dados de idioma é conferida ao executar.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private var pagePlaceholder: String {
        switch stage.operation {
        case .organize, .extractPages: return "Páginas na nova ordem: 3,1,2 ou 3-5,1"
        case .deletePages: return "Páginas a excluir: 1,3-5"
        default: return "Páginas: vazio para todas, ou 1,3-5"
        }
    }

    private var typography: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 20) {
                Picker("Posição", selection: $stage.position) {
                    Text("Superior esquerda").tag("top-left"); Text("Superior centro").tag("top-center"); Text("Superior direita").tag("top-right")
                    Text("Centro").tag("center")
                    Text("Inferior esquerda").tag("bottom-left"); Text("Inferior centro").tag("bottom-center"); Text("Inferior direita").tag("bottom-right")
                }.frame(maxWidth: 300)
                Text("Fonte")
                TextField("Pontos", value: $stage.fontSize, format: .number).frame(width: 60).textFieldStyle(.roundedBorder)
                Text("Margem")
                TextField("Pontos", value: $stage.margin, format: .number).frame(width: 60).textFieldStyle(.roundedBorder)
            }
            HStack {
                Text("Opacidade").font(.caption)
                Slider(value: $stage.opacity, in: 0...1).frame(maxWidth: 240)
                Text(stage.opacity, format: .percent.precision(.fractionLength(0))).font(.caption.monospacedDigit()).frame(width: 44)
            }
        }
    }
}

private enum WorkflowDependencies {
    static func check(_ data: Data) throws {
        let files = FileManager.default
        let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath: files.currentDirectoryPath)
        let project = URL(fileURLWithPath: files.currentDirectoryPath)
        let bundledPython = resources.appendingPathComponent("runtime/bin/python3")
        let python = files.isExecutableFile(atPath: bundledPython.path) ? bundledPython : project.appendingPathComponent(".venv/bin/python3")
        let bundledEngine = resources.appendingPathComponent("engine")
        let engine = files.fileExists(atPath: bundledEngine.appendingPathComponent("pdf_engine.py").path) ? bundledEngine : project.appendingPathComponent("engine")
        guard files.isExecutableFile(atPath: python.path) else { throw WorkflowError.invalid("Instale o motor local para verificar as dependências do fluxo.") }
        let process = Process(); process.executableURL = python
        process.arguments = [engine.appendingPathComponent("pdf_engine.py").path, "--check-workflow-dependencies"]
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = python.deletingLastPathComponent().path + ":/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin")
        process.environment = environment
        let input = try EngineInputTransport(data: data), log = Pipe()
        defer { input.close(); try? log.fileHandleForReading.close() }
        process.standardInput = input.handle; process.standardOutput = log; process.standardError = log
        let runtimeLease = try BundleRuntimeLease.configureRuntimeChild(process)
        defer { try? runtimeLease?.close() }
        try process.run()
        // Dependency checks only inspect installed modules/executables and produce
        // a bounded error. A timeout still protects against a broken Python runtime.
        let deadline = ProcessInfo.processInfo.systemUptime + 8
        while process.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.05) }
        if process.isRunning { process.terminate(); if process.processIdentifier > 0 { kill(process.processIdentifier, SIGKILL) } }
        process.waitUntilExit()
        let output = log.fileHandleForReading.readDataToEndOfFile()
        guard process.terminationStatus == 0 else {
            let detail = String(decoding: output, as: UTF8.self).split(separator: "\n").last.map(String.init) ?? "O motor local não respondeu."
            throw WorkflowError.invalid("Dependências do fluxo: \(detail)")
        }
    }
}

/// Exercises the same typed configuration, storage and request builder used by
/// the editor. These checks do not execute user workflows or use real secrets.
@MainActor enum WorkflowAuditChecks {
    static func run(in root: URL) throws {
        func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            guard condition() else { throw NSError(domain: "PDF.WorkflowAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        let directory = root.appendingPathComponent("workflow-audit", isDirectory: true)
        let library = WorkflowLibrary(directory: directory)
        var preset = WorkflowPreset()
        preset.name = "Auditoria de fluxo"
        preset.stages = [.init(operation: .unlock), .init(operation: .numbers), .init(operation: .protect)]
        try library.save(preset)
        let file = directory.appendingPathComponent(preset.id.uuidString).appendingPathExtension("json")
        let restored = try WorkflowLibrary.read(file)
        try require(restored.stages.map(\.operation) == [.unlock, .numbers, .protect], "A ordem das etapas não persistiu.")
        let folderPermissions = try FileManager.default.attributesOfItem(atPath: directory.path)[.posixPermissions] as? NSNumber
        let filePermissions = try FileManager.default.attributesOfItem(atPath: file.path)[.posixPermissions] as? NSNumber
        try require(folderPermissions?.intValue == 0o700 && filePermissions?.intValue == 0o600, "A biblioteca não preservou permissões privadas.")
        let request = try WorkflowRequest.make(preset: restored, sourcePassword: "input-audit-123", destinationPassword: "output-audit-123")
        let steps = request["steps"] as? [[String: Any]] ?? []
        try require(steps.count == 3 && request["password"] as? String == "input-audit-123", "A senha de origem não foi enviada ao motor.")
        try require((steps[0]["options"] as? [String: Any])?["password"] as? String == "input-audit-123", "A primeira etapa não recebeu a senha de origem.")
        try require((steps[1]["options"] as? [String: Any])?["password"] == nil, "Uma etapa intermediária substituiu a propagação da senha.")
        try require((steps[2]["options"] as? [String: Any])?["new_password"] as? String == "output-audit-123", "A etapa de proteção perdeu a senha do resultado.")
        let encoded = try WorkflowLibrary.encode(restored)
        let serialized = String(decoding: encoded, as: UTF8.self)
        try require(!serialized.contains("input-audit-123") && !serialized.contains("output-audit-123") && !serialized.contains("password"), "Uma senha foi persistida no fluxo.")
        try require(WorkflowRequest.validation(preset: preset, sourcePassword: "input-audit-123", destinationPassword: String(repeating: "😀", count: 41)) != nil, "A senha acima do limite foi aceita.")
        try require(WorkflowRequest.validation(preset: preset, sourcePassword: "input-audit-123", destinationPassword: String(repeating: "a\u{301}", count: 21)) != nil, "O limite Unicode da senha diverge do motor.")
        var invalid = preset
        invalid.stages[1].id = invalid.stages[0].id
        try require(invalid.validation != nil, "Identificadores duplicados foram aceitos.")
        invalid = preset
        invalid.stages = [.init(operation: .redact)]
        try require(invalid.validation != nil, "A remoção de texto sem alvo foi aceita.")
        var extraction = WorkflowStage(operation: .extractPages)
        for selector in ["0", "1,,2", "3-", "-1", "1.5"] {
            extraction.pages = selector
            try require(extraction.validation != nil, "Um seletor de páginas inválido foi aceito.")
        }
        extraction.pages = "4-2,1,1"
        try require(extraction.validation == nil, "Um intervalo reverso ou páginas repetidas válidas foram recusados.")
        // Version 1 documents have none of the terminal-export fields. Defaults
        // must be migrated without changing their PDF stages or page settings.
        var legacyObject = try JSONSerialization.jsonObject(with: encoded) as! [String: Any]
        legacyObject["version"] = 1
        var legacyStages = legacyObject["stages"] as! [[String: Any]]
        for index in legacyStages.indices {
            legacyStages[index].removeValue(forKey: "dpi")
            legacyStages[index].removeValue(forKey: "exportMode")
            legacyStages[index].removeValue(forKey: "transparent")
            legacyStages[index].removeValue(forKey: "tableDetection")
            for key in ["source", "ocrLanguage", "ocrDPI", "minConfidence", "ocrDeskew"] { legacyStages[index].removeValue(forKey: key) }
        }
        legacyObject["stages"] = legacyStages
        let legacy = try JSONDecoder().decode(WorkflowPreset.self, from: JSONSerialization.data(withJSONObject: legacyObject))
        try require(legacy.version == 1 && legacy.validation == nil && legacy.stages[0].dpi == 144 && legacy.stages[0].tableDetection == "ruled", "A migração do fluxo v1 falhou.")
        let upgraded = try JSONDecoder().decode(WorkflowPreset.self, from: WorkflowLibrary.encode(legacy))
        try require(upgraded.version == 2, "O fluxo legado não foi salvo como v2.")
        for terminal in [WorkflowOperation.word, .excel, .powerpoint, .markdown, .jpg, .png] {
            var typed = WorkflowPreset()
            typed.stages = [.init(operation: .numbers), .init(operation: terminal)]
            try require(typed.validation == nil, "Uma exportação terminal válida foi recusada.")
            typed.stages.reverse()
            try require(typed.validation != nil, "Uma etapa após exportação foi aceita.")
        }
        let batch = try WorkflowRequest.make(preset: restored, sourcePasswords: ["first-private", "second-private"], destinationPassword: "destination-private")
        var aligned = WorkflowStage(operation: .excel)
        aligned.tableDetection = "aligned"
        let alignedDecoded = try JSONDecoder().decode(WorkflowStage.self, from: JSONEncoder().encode(aligned))
        try require(alignedDecoded.options["table_detection"] as? String == "aligned" && alignedDecoded.validation == nil, "O modo de tabelas se perdeu ao salvar o fluxo.")
        aligned.tableDetection = "unsupported"
        try require(aligned.validation != nil, "Um modo de tabela desconhecido foi aceito.")
        for operation in [WorkflowOperation.word, .excel, .markdown] {
            let expectedSource = operation == .markdown ? "vector" : "auto"
            for version in [1, 2] {
                let oldPreset: [String: Any] = ["id": UUID().uuidString, "version": version, "name": "Exportação legada",
                    "stages": [["operation": operation.rawValue, "language": "por+eng", "tableDetection": "aligned"]]]
                let decoded = try JSONDecoder().decode(WorkflowPreset.self, from: JSONSerialization.data(withJSONObject: oldPreset))
                let old = decoded.stages[0]
                try require(decoded.validation == nil && old.source == expectedSource && old.ocrLanguage == "eng" && old.ocrDPI == 200 && old.minConfidence == 35 && !old.ocrDeskew, "A migração alterou a origem ou os parâmetros efetivos do OCR de um fluxo legado.")
                try require(old.options["source"] as? String == expectedSource && old.options["table_detection"] as? String == "aligned", "A migração perdeu opções de extração anteriores.")
                if operation == .markdown {
                    try require(old.options["language"] == nil && old.options["ocr_dpi"] == nil && old.options["ocr_deskew"] == nil, "O Markdown legado passou a fazer OCR implicitamente.")
                } else {
                    try require(old.options["language"] as? String == "eng", "O campo antigo de idioma inativo mudou os pacotes exigidos pela exportação legada.")
                }
            }
            var scan = WorkflowStage(operation: operation)
            scan.source = "ocr"; scan.ocrLanguage = "por+eng"; scan.ocrDPI = 300; scan.minConfidence = 47.5; scan.ocrDeskew = true; scan.tableDetection = "aligned"
            var scanPreset = WorkflowPreset(); scanPreset.name = "OCR " + operation.rawValue
            scanPreset.stages = [.init(operation: .numbers), scan]
            try library.save(scanPreset)
            let savedScan = try WorkflowLibrary.read(directory.appendingPathComponent(scanPreset.id.uuidString).appendingPathExtension("json"))
            let restoredScan = savedScan.stages[1]
            let scanRequest = try WorkflowRequest.make(preset: savedScan, sourcePassword: "", destinationPassword: "")
            let scanSteps = scanRequest["steps"] as? [[String: Any]] ?? []
            let scanOptions = scanSteps.last?["options"] as? [String: Any] ?? [:]
            try require(restoredScan.source == "ocr" && restoredScan.ocrLanguage == "por+eng" && restoredScan.ocrDPI == 300 && restoredScan.minConfidence == 47.5 && restoredScan.ocrDeskew && restoredScan.validation == nil, "Os controles de OCR não sobreviveram à gravação e releitura do preset.")
            try require(scanOptions["source"] as? String == "ocr" && scanOptions["language"] as? String == "por+eng" && scanOptions["ocr_dpi"] as? Double == 300 && scanOptions["min_confidence"] as? Double == 47.5 && scanOptions["ocr_deskew"] as? Bool == true && scanOptions["dpi"] == nil, "O fluxo não enviou os parâmetros corretos de OCR ao motor.")
            scan.source = "vector"
            try require(!scan.usesStructuredOCR && scan.options["language"] == nil && scan.options["ocr_dpi"] == nil && scan.options["min_confidence"] == nil && scan.options["ocr_deskew"] == nil, "A extração vetorial recebeu opções de processamento raster.")
            scan.source = "auto"
            try require(scan.usesStructuredOCR && scan.options["ocr_deskew"] as? Bool == true, "O modo automático perdeu a configuração de OCR quando uma página digitalizada a exigir.")
        }
        for operation in [WorkflowOperation.ocr, .pdfa] {
            var direct = WorkflowStage(operation: operation); direct.ocrDeskew = true
            try require(direct.options["language"] as? String == "por+eng" && direct.options["source"] == nil && direct.options["ocr_dpi"] == nil && direct.options["min_confidence"] == nil && direct.options["ocr_deskew"] == nil, "Opções de OCR estruturado vazaram para o contrato direto do OCRmyPDF.")
        }
        var boundedOCR = WorkflowStage(operation: .word)
        for value in [Double.nan, .infinity, -.infinity, 119, 120.5, 400.5, 401] {
            boundedOCR.ocrDPI = value
            try require(boundedOCR.validation != nil, "Uma resolução de OCR não finita, fracionária ou fora dos limites foi aceita.")
        }
        for value in [120.0, 400.0] {
            boundedOCR.ocrDPI = value
            try require(boundedOCR.validation == nil, "Um limite válido de DPI do OCR foi recusado.")
        }
        for value in [Double.nan, .infinity, -.infinity, -0.1, 100.1] {
            boundedOCR.minConfidence = value
            try require(boundedOCR.validation != nil, "Um limiar de confiança inválido foi aceito.")
        }
        for value in [0.0, 100.0] {
            boundedOCR.minConfidence = value
            try require(boundedOCR.validation == nil, "Um limite válido de confiança foi recusado.")
        }
        boundedOCR.source = "remote"; try require(boundedOCR.validation != nil, "Uma origem de texto desconhecida foi aceita.")
        boundedOCR.source = "auto"; boundedOCR.ocrLanguage = "eng;command"
        try require(boundedOCR.validation != nil, "Um idioma fora da lista foi aceito.")
        var deskewTypeRefused = false
        do { _ = try JSONDecoder().decode(WorkflowStage.self, from: Data("{\"operation\":\"word\",\"ocrDeskew\":\"true\"}".utf8)) }
        catch { deskewTypeRefused = true }
        try require(deskewTypeRefused, "Um parâmetro de correção de inclinação que não é booleano foi aceito.")
        try require(batch["batch"] as? Bool == true && batch["input_passwords"] as? [String] == ["first-private", "second-private"], "As senhas individuais do lote foram perdidas.")
        let batchSteps = batch["steps"] as? [[String: Any]] ?? []
        try require(batch["password"] == nil && (batchSteps[0]["options"] as? [String: Any])?["password"] == nil, "A senha do primeiro arquivo foi aplicada ao lote inteiro.")
        try require((batchSteps.last?["options"] as? [String: Any])?["new_password"] as? String == "destination-private", "A proteção final do lote perdeu a senha.")
        let link = directory.appendingPathComponent("linked.json")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: file)
        var refusedLink = false
        do { _ = try WorkflowLibrary.read(link) } catch { refusedLink = true }
        try require(refusedLink, "A importação seguiu um link simbólico.")
        let fifo = directory.appendingPathComponent("pipe.json")
        try require(mkfifo(fifo.path, 0o600) == 0, "Não foi possível preparar a verificação de arquivo especial.")
        var refusedFIFO = false
        do { _ = try WorkflowLibrary.read(fifo) } catch { refusedFIFO = true }
        try require(refusedFIFO, "A importação aceitou um arquivo especial.")
    }
}
