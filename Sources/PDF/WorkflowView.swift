import SwiftUI
import AppKit
import UniformTypeIdentifiers

private enum WorkflowOperation: String, Codable, CaseIterable, Identifiable {
    case rotate, numbers, compress, watermark, organize, crop, text, redact, protect, unlock, repair, ocr, pdfa, flatten
    case deletePages = "delete-pages"
    case extractPages = "extract-pages"
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
        }
    }
    var hasText: Bool { [.text, .watermark, .redact].contains(self) }
    var hasTypography: Bool { [.text, .watermark, .numbers].contains(self) }
    var acceptsPages: Bool { [.rotate, .numbers, .watermark, .organize, .crop, .text, .redact, .deletePages, .extractPages].contains(self) }
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

    init(operation: WorkflowOperation) {
        self.operation = operation
        if operation == .watermark { opacity = 0.35; position = "center"; fontSize = 32 }
        if operation == .text { position = "top-left" }
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
    var version = 1
    var name = "Meu fluxo"
    var stages: [WorkflowStage] = [WorkflowStage(operation: .rotate), WorkflowStage(operation: .numbers)]

    var validation: String? {
        if version != 1 { return "Esta versão de fluxo não é compatível." }
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Dê um nome ao fluxo." }
        if name.count > 120 { return "Use um nome com até 120 caracteres." }
        if stages.isEmpty { return "Adicione ao menos uma etapa." }
        if stages.count > 24 { return "Use no máximo 24 etapas por fluxo." }
        if Set(stages.map(\.id)).count != stages.count { return "O fluxo contém etapas com identificadores repetidos." }
        for (index, stage) in stages.enumerated() {
            if let error = stage.validation { return "Etapa \(index + 1): \(error)" }
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

    init() {
        do {
            let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
            let path = base.appendingPathComponent("PDF/Workflows", isDirectory: true)
            try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
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
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= 1_048_576 else { throw WorkflowError.invalid("O arquivo excede 1 MB.") }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: 1_048_577) ?? Data()
        guard data.count <= 1_048_576 else { throw WorkflowError.invalid("O arquivo excede 1 MB.") }
        return try JSONDecoder().decode(WorkflowPreset.self, from: data)
    }

    static func encode(_ preset: WorkflowPreset) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return try encoder.encode(preset)
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
        if let index = presets.firstIndex(where: { $0.id == preset.id }) { presets[index] = preset }
        else { presets.append(preset) }
        presets.sort { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
        error = ""
    }
}

private enum WorkflowError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let text) = self { return text }; return nil }
}

struct WorkflowView: View {
    @EnvironmentObject var model: Workspace
    @StateObject private var library = WorkflowLibrary()
    @State private var preset = WorkflowPreset()
    @State private var input: URL?
    @State private var output: URL?
    @State private var sourcePassword = ""
    @State private var destinationPassword = ""
    @State private var error = ""
    @State private var status = ""
    @State private var confirmDelete = false

    private var requiresDestinationPassword: Bool { preset.stages.contains { $0.operation == .protect } }
    private var validation: String? {
        if let error = preset.validation { return error }
        guard let input else { return "Escolha um PDF de entrada." }
        if !FileManager.default.isReadableFile(atPath: input.path) { return "O PDF de entrada não está acessível." }
        guard let output else { return "Escolha onde salvar o resultado." }
        if input.resolvingSymlinksInPath() == output.resolvingSymlinksInPath() { return "Escolha um novo arquivo de saída para preservar o original." }
        if FileManager.default.fileExists(atPath: output.path) { return "Já existe um arquivo no destino. Escolha outro nome." }
        if requiresDestinationPassword && destinationPassword.count < 8 { return "Use uma nova senha de pelo menos 8 caracteres." }
        if preset.stages.first?.operation == .unlock && sourcePassword.isEmpty { return "Informe a senha atual para remover a proteção." }
        return nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                documentSelection
                stagesSection
                passwordSection
                footer
            }
            .padding(28)
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .disabled(model.busy)
        .onDisappear { sourcePassword = ""; destinationPassword = "" }
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
            Text("Combine ferramentas, organize as etapas e reutilize sua rotina. Cada execução cria um novo PDF.")
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
            if !library.error.isEmpty { Text(library.error).font(.caption).foregroundStyle(.red).textSelection(.enabled) }
        }
    }

    private var documentSelection: some View {
        HStack(alignment: .top, spacing: 16) {
            fileCard(title: "1. Documento de entrada", filename: input?.lastPathComponent ?? "Escolha um PDF", symbol: "doc", action: chooseInput)
            Image(systemName: "arrow.right").foregroundStyle(.secondary).padding(.top, 42)
            fileCard(title: "2. Arquivo de saída", filename: output?.lastPathComponent ?? "Escolha um novo destino", symbol: "doc.badge.arrow.up", action: chooseOutput)
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
                            preset.stages.append(WorkflowStage(operation: operation))
                        }
                    }
                }.disabled(preset.stages.count >= 24)
            }
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
            SecureField("Senha do PDF de entrada, se houver", text: $sourcePassword).textFieldStyle(.roundedBorder)
            if requiresDestinationPassword {
                SecureField("Nova senha do resultado, mínimo 8 caracteres", text: $destinationPassword).textFieldStyle(.roundedBorder)
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
                Button("Executar fluxo", systemImage: "play.fill") { execute() }
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
        preset = item; sourcePassword = ""; destinationPassword = ""; error = ""; status = ""
    }
    private func chooseInput() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        if panel.runModal() == .OK { input = panel.url; error = "" }
    }
    private func chooseOutput() {
        let panel = NSSavePanel(); panel.allowedContentTypes = [.pdf]; panel.nameFieldStringValue = "PDF-fluxo.pdf"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        guard !FileManager.default.fileExists(atPath: url.path) else { error = "Escolha um nome novo: o fluxo não sobrescreve arquivos."; return }
        output = url; error = ""
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
        let panel = NSSavePanel(); panel.allowedContentTypes = [.json]; panel.nameFieldStringValue = "PDF-fluxo.json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try WorkflowLibrary.encode(preset).write(to: url, options: .withoutOverwriting)
            error = ""; status = "Fluxo exportado sem senhas ou caminhos de documentos."
        } catch { self.error = "Não foi possível exportar em um arquivo novo: \(error.localizedDescription)" }
    }
    private func execute() {
        if let validation { error = validation; return }
        guard let input, let output else { return }
        let steps: [[String: Any]] = preset.stages.enumerated().map { index, stage in
            var options = stage.options
            if index == 0 && !sourcePassword.isEmpty { options["password"] = sourcePassword }
            if stage.operation == .protect { options["new_password"] = destinationPassword }
            return ["operation": stage.operation.rawValue, "options": options]
        }
        var options: [String: Any] = ["steps": steps]
        if !sourcePassword.isEmpty { options["password"] = sourcePassword }
        error = ""; status = ""
        model.execute(operation: "workflow", inputs: [input], output: output, options: options, title: preset.name)
        sourcePassword = ""; destinationPassword = ""
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
        if stage.operation == .redact { Text("A remoção é permanente no resultado. O original será preservado.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .protect { Text("Esta etapa deve ser a última. Informe a nova senha na seção Proteção do documento.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .unlock { Text("Esta etapa exige a senha atual e deve ser a primeira.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .compress { Text("O motor reorganiza os dados do documento. A redução depende do conteúdo original.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .repair { Text("Tenta regravar documentos que o mecanismo consegue recuperar.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .flatten { Text("Incorpora anotações e valores dos formulários à página. Os campos deixam de ser editáveis no resultado.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .deletePages { Text("Exclui as páginas indicadas da cópia de saída. O documento precisa manter ao menos uma página.").font(.caption).foregroundStyle(.secondary) }
        if stage.operation == .extractPages { Text("Mantém apenas as páginas indicadas, na ordem escolhida. Páginas podem ser repetidas.").font(.caption).foregroundStyle(.secondary) }
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
