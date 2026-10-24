import SwiftUI
import AppKit
import PDFKit
import CryptoKit
import Darwin

struct ContentPageDescriptor: Codable, Identifiable, Sendable {
    let page: Int
    let width: Double
    let height: Double
    let rotation: Int
    var id: Int { page }
    var displayedSize: CGSize { abs(rotation) % 180 == 90 ? CGSize(width: height, height: width) : CGSize(width: width, height: height) }
    func displayRect(_ coordinates: [Double]) -> CGRect {
        let rect = CGRect(x: coordinates[0], y: coordinates[1], width: coordinates[2] - coordinates[0], height: coordinates[3] - coordinates[1])
        switch ((rotation % 360) + 360) % 360 {
        case 90: return CGRect(x: height - rect.maxY, y: rect.minX, width: rect.height, height: rect.width)
        case 180: return CGRect(x: width - rect.maxX, y: height - rect.maxY, width: rect.width, height: rect.height)
        case 270: return CGRect(x: rect.minY, y: width - rect.maxX, width: rect.height, height: rect.width)
        default: return rect
        }
    }
}
struct ContentObjectDescriptor: Codable, Identifiable, Sendable {
    let id: String
    let kind: String
    let page: Int
    let rect: [Double]
    let text: String?
    let font: String?
    let font_size: Double?
    let color: String?
    let editable: Bool
    let limitations: [String]
    let font_status: String?
    let substitution_font: String?
    var supported_actions: [String]? = nil
    var member_ids: [String]? = nil
    var line_spacing: Double? = nil
    var alignment: String? = nil
    var supportedActions: [String] { supported_actions ?? ["replace", "move", "delete"] }
    var isText: Bool { kind == "text" || kind == "paragraph" }
}
struct ContentInspection: Codable, Sendable {
    let version: Int
    let source_sha256: String
    let page_count: Int
    let pages: [ContentPageDescriptor]
    let objects: [ContentObjectDescriptor]
    func validate(digest: String) throws {
        try AdvancedDocumentValidation.pages(version: version, digest: source_sha256, expected: digest, count: page_count, pages: pages)
        guard objects.count <= 100_000, Set(objects.map(\.id)).count == objects.count else { throw AdvancedDocumentValidation.failure("A lista de objetos contém identificadores inválidos ou excede o limite de revisão.") }
        let indexed = Dictionary(uniqueKeysWithValues: objects.map { ($0.id, $0) })
        var grouped = Set<String>()
        for item in objects {
            try Task.checkCancellation()
            guard !item.id.isEmpty, item.id.utf8.count <= 256, ["text", "image", "paragraph"].contains(item.kind),
                  (item.text?.utf8.count ?? 0) <= 1_048_576,
                  !item.supportedActions.isEmpty, Set(item.supportedActions).count == item.supportedActions.count,
                  item.supportedActions.allSatisfy({ ["replace", "move", "delete"].contains($0) }),
                  item.alignment == nil || ["left", "center", "right", "justify"].contains(item.alignment!),
                  item.font_size == nil || (item.font_size!.isFinite && item.font_size! > 0 && item.font_size! <= 1000) else {
                throw AdvancedDocumentValidation.failure("Um objeto de conteúdo não pôde ser validado.")
            }
            try AdvancedDocumentValidation.rect(item.rect, page: item.page, pages: pages, withinPage: item.editable)
            if item.kind == "paragraph" {
                guard let members = item.member_ids, members.count >= 2, members.count <= objects.count,
                      Set(members).count == members.count, grouped.isDisjoint(with: members),
                      let spacing = item.line_spacing, spacing.isFinite, (1...3).contains(spacing) else {
                    throw AdvancedDocumentValidation.failure("O agrupamento de parágrafo não contém linhas e espaçamento válidos.")
                }
                grouped.formUnion(members)
                for id in members {
                    guard let member = indexed[id], member.kind == "text", member.page == item.page,
                          member.rect.count == 4, member.rect.allSatisfy(\.isFinite),
                          member.rect[0] >= item.rect[0] - 0.1, member.rect[1] >= item.rect[1] - 0.1,
                          member.rect[2] <= item.rect[2] + 0.1, member.rect[3] <= item.rect[3] + 0.1 else {
                        throw AdvancedDocumentValidation.failure("Um parágrafo referencia trechos ausentes ou fora de sua área original.")
                    }
                }
            } else if item.member_ids?.isEmpty == false {
                throw AdvancedDocumentValidation.failure("Somente parágrafos podem agrupar trechos originais.")
            }
        }
    }
    func validateEditSelection(_ selected: Set<String>) throws {
        guard !selected.isEmpty, selected.count <= 1000, Set(objects.map(\.id)).count == objects.count else { throw AdvancedDocumentValidation.failure("Prepare entre 1 e 1.000 alterações em objetos distintos por revisão.") }
        let indexed = Dictionary(uniqueKeysWithValues: objects.map { ($0.id, $0) })
        var covered = Set<String>()
        for id in selected {
            guard let item = indexed[id], item.editable else { throw AdvancedDocumentValidation.failure("Uma alteração não pertence aos objetos editáveis desta análise.") }
            let members = Set(item.kind == "paragraph" ? (item.member_ids ?? []) : [id])
            guard !members.isEmpty, covered.isDisjoint(with: members) else {
                throw AdvancedDocumentValidation.failure("Edite o parágrafo inteiro ou seus trechos individuais em uma revisão. Remova as alterações que usam o mesmo texto duas vezes.")
            }
            covered.formUnion(members)
        }
    }
}
struct OCRReviewWord: Codable, Identifiable, Sendable {
    let id: String
    let page: Int
    let rect: [Double]
    let text: String
    let confidence: Double
}
struct OCRReviewDocument: Codable, Sendable {
    let version: Int
    let source_sha256: String
    let page_count: Int
    let pages: [ContentPageDescriptor]
    let words: [OCRReviewWord]
    let backend: String
    let language: String
    func validate(digest: String) throws {
        try AdvancedDocumentValidation.pages(version: version, digest: source_sha256, expected: digest, count: page_count, pages: pages)
        guard words.count <= 50_000, Set(words.map(\.id)).count == words.count,
              !backend.isEmpty, !language.isEmpty else { throw AdvancedDocumentValidation.failure("O resultado OCR não contém uma identificação válida.") }
        for word in words {
            try Task.checkCancellation()
            guard !word.id.isEmpty, word.id.utf8.count <= 256, word.text.utf8.count <= 16_384,
                  word.confidence.isFinite, (0...1).contains(word.confidence) else {
                throw AdvancedDocumentValidation.failure("Uma palavra OCR não pôde ser validada.")
            }
            try AdvancedDocumentValidation.rect(word.rect, page: word.page, pages: pages)
        }
    }
}
enum AdvancedDocumentValidation {
    static func failure(_ text: String) -> NSError { NSError(domain: "PDF.AdvancedEditing", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
    static func pages(version: Int, digest: String, expected: String, count: Int, pages: [ContentPageDescriptor]) throws {
        guard version == 1, digest == expected, digest.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              (1...20_000).contains(count), pages.count == count,
              pages.map(\.page) == Array(1...count) else { throw failure("A análise não corresponde à cópia do documento em revisão.") }
        for page in pages {
            guard page.width.isFinite, page.height.isFinite, page.width > 0, page.height > 0,
                  page.width <= 100_000, page.height <= 100_000, page.rotation % 90 == 0 else { throw failure("A geometria de uma página não é válida.") }
        }
    }
    static func rect(_ value: [Double], page: Int, pages: [ContentPageDescriptor], withinPage: Bool = true) throws {
        guard value.count == 4, value.allSatisfy(\.isFinite), page > 0, page <= pages.count,
              value.allSatisfy({ abs($0) <= 1_000_000 }), value[2] > value[0], value[3] > value[1] else {
            throw failure("Um retângulo de conteúdo não contém uma geometria válida.")
        }
        if withinPage && (value[0] < -0.1 || value[1] < -0.1 || value[2] > pages[page - 1].width + 0.1 || value[3] > pages[page - 1].height + 0.1) {
            throw failure("Um retângulo de conteúdo está fora dos limites da página.")
        }
    }
    static func text(_ value: String, maximum: Int = 100_000) throws {
        guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              value.utf8.count <= maximum, !value.contains("\0") else { throw failure("Informe texto não vazio dentro do limite permitido.") }
    }
}

/// Captures immutable source bytes once. Protected inputs stay encrypted on disk;
/// the original password exists only in memory and in the engine's stdin options.
struct AdvancedSourceCapture: Sendable {
    let directory: URL
    let url: URL
    let digest: String
    let opening: NativePDFSerialization.Opening
    static func create(source: URL, password: String?, cancellation: NativeCancellation) throws -> AdvancedSourceCapture {
        try cancellation.check(); try Task.checkCancellation()
        let descriptor = Darwin.open(source.resolvingSymlinksInPath().path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)
        guard descriptor >= 0 else { throw AdvancedDocumentValidation.failure("Não foi possível ler a versão salva do documento.") }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? file.close() }
        var before = stat(), after = stat()
        guard fstat(descriptor, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_size > 0, before.st_size <= 268_435_456 else { throw AdvancedDocumentValidation.failure("A revisão de conteúdo aceita PDFs regulares de até 256 MiB.") }
        var data = Data()
        while let chunk = try file.read(upToCount: 1_048_576), !chunk.isEmpty {
            try cancellation.check(); try Task.checkCancellation()
            data.append(chunk)
            guard data.count <= 268_435_456 else { throw AdvancedDocumentValidation.failure("O PDF excedeu o limite de 256 MiB para revisão de conteúdo.") }
        }
        guard fstat(descriptor, &after) == 0, before.st_size == after.st_size, data.count == Int(after.st_size),
              before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else { throw AdvancedDocumentValidation.failure("O arquivo mudou durante a leitura. Carregue novamente.") }
        let opening = try NativePDFSerialization.prepareOpen(data: data, password: password, cancellation: cancellation)
        guard !opening.requiresPassword else { throw AdvancedDocumentValidation.failure("Abra e desbloqueie o PDF no leitor antes de revisá-lo.") }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-ContentReview-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        var success = false
        defer { if !success { try? FileManager.default.removeItem(at: directory) } }
        let target = directory.appendingPathComponent("source.pdf")
        try NativeOutput.write(data, to: target)
        try cancellation.check(); try Task.checkCancellation()
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        success = true
        return AdvancedSourceCapture(directory: directory, url: target, digest: digest, opening: opening)
    }
}

private enum AdvancedDecodedAnalysis: Sendable {
    case content(ContentInspection)
    case ocr(OCRReviewDocument)
    static func read(url: URL, digest: String, ocr: Bool) throws -> AdvancedDecodedAnalysis {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw AdvancedDocumentValidation.failure("Não foi possível ler a análise local.") }
        let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? file.close() }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_size > 0, info.st_size <= 33_554_432 else { throw AdvancedDocumentValidation.failure("A análise é inválida ou excedeu 32 MiB.") }
        var data = Data()
        while let chunk = try file.read(upToCount: 1_048_576), !chunk.isEmpty {
            try Task.checkCancellation(); data.append(chunk)
            guard data.count <= 33_554_432 else { throw AdvancedDocumentValidation.failure("A análise excedeu 32 MiB.") }
        }
        if ocr {
            let value = try JSONDecoder().decode(OCRReviewDocument.self, from: data)
            try value.validate(digest: digest); return .ocr(value)
        }
        let value = try JSONDecoder().decode(ContentInspection.self, from: data)
        try value.validate(digest: digest); return .content(value)
    }
}

@MainActor final class AdvancedDocumentController: ObservableObject {
    @Published private(set) var content: ContentInspection?
    @Published private(set) var review: OCRReviewDocument?
    @Published private(set) var preview: PDFDocument?
    @Published private(set) var working = false
    @Published private(set) var status = "Abra um PDF no leitor e carregue sua versão salva para revisão."
    @Published private(set) var output: URL?
    @Published private(set) var sourceName = ""
    private var source: AdvancedSourceCapture?
    private var originalURL: URL?
    private var password: String?
    private var task: Task<Void, Never>?
    private var cancellation: NativeCancellation?
    private var assetCancellations: [UUID: NativeCancellation] = [:]
    private var ownsEngine = false
    private var closed = false
    private var generation = UUID()
    private var ocrReviewURL: URL?
    deinit { cancellation?.cancel(); assetCancellations.values.forEach { $0.cancel() }; task?.cancel(); if let source { try? FileManager.default.removeItem(at: source.directory) } }
    @discardableResult func load(model: Workspace, ocr: Bool, language: String = "por+eng", deskew: Bool = false) -> Bool {
        guard !working, !model.busy else { return false }
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let document = model.document, let url = model.savedDocumentURL ?? model.url, !document.isLocked else {
            status = "Abra e desbloqueie um PDF no leitor primeiro."; return false
        }
        guard !model.hasUnsavedChanges else { status = "Salve uma cópia das alterações do leitor antes de carregar esta revisão."; return false }
        clear(); closed = false; working = true; status = "Preparando uma cópia privada da versão salva…"
        let token = NativeCancellation(), current = UUID(), secret = model.activeSession?.password
        cancellation = token; generation = current; originalURL = url; sourceName = url.lastPathComponent; password = secret
        task = Task { [weak self] in
            do {
                let captured = try await withTaskCancellationHandler(operation: {
                    try await Task.detached(priority: .userInitiated) { try AdvancedSourceCapture.create(source: url, password: secret, cancellation: token) }.value
                }, onCancel: { token.cancel() })
                guard let self else { try? FileManager.default.removeItem(at: captured.directory); return }
                guard self.generation == current, !self.closed else { try? FileManager.default.removeItem(at: captured.directory); return }
                self.source = captured
                self.preview = try NativePDFSerialization.finishOpen(captured.opening)
                self.task = nil; self.cancellation = nil
                self.inspect(model: model, ocr: ocr, language: language, deskew: deskew, generation: current)
            } catch {
                guard let self, self.generation == current else { return }
                self.working = false; self.task = nil; self.cancellation = nil
                self.status = error is CancellationError ? "Carregamento cancelado." : error.localizedDescription
                self.clearSource()
            }
        }
        return true
    }
    private func inspect(model: Workspace, ocr: Bool, language: String, deskew: Bool, generation current: UUID) {
        guard let source else { working = false; return }
        let metadata = source.directory.appendingPathComponent("analysis-" + UUID().uuidString + ".json")
        var options: [String: Any] = [:]
        if let password { options["password"] = password }
        if ocr { options["language"] = language; options["min_confidence"] = 0; options["ocr_deskew"] = deskew }
        status = ocr ? "Reconhecendo palavras e posições com OCR local…" : "Identificando objetos de texto e imagem…"
        ownsEngine = true
        model.execute(operation: ocr ? "ocr-review" : "content-inspect", inputs: [source.url], output: metadata, options: options,
                      title: ocr ? "Analisando OCR para revisão" : "Analisando conteúdo original", completion: { [self, weak model] result in
            ownsEngine = false
            if model?.lastOutput == metadata { model?.lastOutput = nil; model?.message = "Validando a análise local do documento…" }
            guard generation == current, !closed else { working = false; clearSource(); return }
            switch result {
            case .failure(let error): status = error.localizedDescription; working = false
            case .success(let url):
                task = Task {
                    defer { working = false; task = nil }
                    do {
                        let decoding = Task.detached(priority: .userInitiated) {
                            try AdvancedDecodedAnalysis.read(url: url, digest: source.digest, ocr: ocr)
                        }
                        let decoded = try await withTaskCancellationHandler(operation: { try await decoding.value }, onCancel: { decoding.cancel() })
                        guard generation == current, !closed else { clearSource(); return }
                        switch decoded {
                        case .ocr(let value):
                            review = value; ocrReviewURL = url
                            status = "\(value.words.count) palavras reconhecidas por \(value.backend). Confira a imagem antes de exportar."
                        case .content(let value):
                            content = value; status = "\(value.objects.count) objetos identificados. Selecione um objeto na página ou na lista."
                            try? FileManager.default.removeItem(at: metadata)
                        }
                        model?.message = status
                    } catch { if !closed { status = error is CancellationError ? "Análise cancelada." : error.localizedDescription } }
                }
            }
        })
    }
    func apply(model: Workspace, edits: [[String: Any]], corrections: [[String: Any]]? = nil) {
        guard !working, !model.busy, let source, let originalURL else { return }
        let ocr = corrections != nil
        guard ocr ? review != nil : content != nil else { return }
        guard let destination = NativeOutput.destination(model: model, toolName: ocr ? "OCR revisado" : "Conteúdo editado", originalURL: originalURL) else { return }
        var options: [String: Any] = ["source_sha256": source.digest]
        if let password { options["password"] = password }
        if let corrections, let ocrReviewURL { options["review_path"] = ocrReviewURL.path; options["corrections"] = corrections }
        else { options["edits"] = edits }
        working = true; ownsEngine = true; status = "Aplicando e validando a cópia…"
        model.execute(operation: ocr ? "ocr-apply" : "content-apply", inputs: [source.url], output: destination, options: options,
                      title: ocr ? "Exportando OCR revisado" : "Editando conteúdo original", completion: { [self] result in
            ownsEngine = false; working = false
            switch result {
            case .success(let url): output = url; status = "Cópia concluída: \(url.lastPathComponent). Abra o resultado para revisar a apresentação."
            case .failure(let error): status = error.localizedDescription
            }
            if closed { clearSource() }
        })
    }
    func stop(model: Workspace) {
        cancellation?.cancel(); task?.cancel()
        if ownsEngine { model.cancel() }
    }
    func stageAsset(_ origin: URL, maximumBytes: Int) async throws -> URL {
        guard let source, !closed else { throw AdvancedDocumentValidation.failure("Carregue o documento antes de selecionar um recurso.") }
        guard (1...67_108_864).contains(maximumBytes) else { throw AdvancedDocumentValidation.failure("O limite do recurso é inválido.") }
        let current = generation
        let assetID = UUID(), assetCancellation = NativeCancellation()
        assetCancellations[assetID] = assetCancellation
        defer { assetCancellations.removeValue(forKey: assetID) }
        let suffix = origin.pathExtension.lowercased().filter { $0.isASCII && $0.isLetter }
        let target = source.directory.appendingPathComponent("asset-" + UUID().uuidString + (suffix.isEmpty ? "" : "." + suffix))
        try await Task.detached(priority: .userInitiated) {
            let descriptor = Darwin.open(origin.resolvingSymlinksInPath().path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            guard descriptor >= 0 else { throw AdvancedDocumentValidation.failure("Não foi possível ler o recurso selecionado.") }
            let file = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
            defer { try? file.close() }
            var info = stat(), after = stat()
            guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_size > 0, info.st_size <= maximumBytes else {
                throw AdvancedDocumentValidation.failure("Selecione um arquivo regular de até \(maximumBytes / 1_048_576) MiB.")
            }
            var data = Data()
            while let chunk = try file.read(upToCount: 1_048_576), !chunk.isEmpty {
                try assetCancellation.check(); try Task.checkCancellation(); data.append(chunk)
                guard data.count <= maximumBytes else { throw AdvancedDocumentValidation.failure("O recurso excedeu o limite permitido.") }
            }
            guard fstat(descriptor, &after) == 0, info.st_size == after.st_size, data.count == Int(after.st_size),
                  info.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec, info.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else {
                throw AdvancedDocumentValidation.failure("O recurso mudou durante a leitura. Selecione-o novamente.")
            }
            try assetCancellation.check()
            try NativeOutput.write(data, to: target)
        }.value
        guard generation == current, !closed else { try? FileManager.default.removeItem(at: target); throw CancellationError() }
        return target
    }
    func close(model: Workspace) {
        closed = true; generation = UUID(); assetCancellations.values.forEach { $0.cancel() }; stop(model: model)
        if !ownsEngine { clearSource() }
    }
    private func clearSource() { if let source { try? FileManager.default.removeItem(at: source.directory) }; source = nil; password = nil; preview = nil; ocrReviewURL = nil }
    private func clear() { assetCancellations.values.forEach { $0.cancel() }; clearSource(); content = nil; review = nil; output = nil }
}

struct ContentPreviewRegion: Identifiable {
    let id: String
    let rect: [Double]
    let label: String
    var changed = false
    var warning = false
}
/// The preview is the actual source PDF page. Rectangles use the engine's
/// crop-relative unrotated coordinates and rotate with the displayed page.
struct ContentPagePreview: View {
    let document: PDFDocument
    let page: ContentPageDescriptor
    let regions: [ContentPreviewRegion]
    @Binding var selection: String?
    @State private var zoom = 1.0
    @State private var thumbnail: NSImage?
    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Text("Página \(page.page)").font(.headline)
                Spacer()
                Button { zoom = max(0.4, zoom - 0.2) } label: { Image(systemName: "minus.magnifyingglass") }.accessibilityLabel("Reduzir prévia")
                Text(zoom, format: .percent.precision(.fractionLength(0))).monospacedDigit().frame(width: 48)
                Button { zoom = min(3, zoom + 0.2) } label: { Image(systemName: "plus.magnifyingglass") }.accessibilityLabel("Ampliar prévia")
            }.padding(.horizontal)
            ScrollView([.horizontal, .vertical]) {
                let size = page.displayedSize
                let scale = min(1.2, 700 / max(size.width, size.height)) * zoom
                ZStack(alignment: .topLeading) {
                    if let image = thumbnail {
                        Image(nsImage: image).resizable().frame(width: size.width * scale, height: size.height * scale)
                            .accessibilityLabel("Imagem original da página \(page.page)")
                    }
                    ForEach(regions) { region in
                        let rect = page.displayRect(region.rect)
                        Button { selection = region.id } label: {
                            Rectangle().fill(selection == region.id ? Color.accentColor.opacity(0.22) : .clear)
                                .overlay(Rectangle().stroke(region.warning ? Color.orange : region.changed ? Color.green : Color.accentColor,
                                                            lineWidth: selection == region.id ? 2.5 : 1))
                                .contentShape(Rectangle())
                        }.buttonStyle(.plain)
                            .frame(width: max(3, rect.width * scale), height: max(3, rect.height * scale))
                            .offset(x: rect.minX * scale, y: rect.minY * scale)
                            .accessibilityLabel(region.label).accessibilityAddTraits(selection == region.id ? .isSelected : [])
                    }
                }.frame(width: size.width * scale, height: size.height * scale).background(.white).clipped().padding(18)
            }.background(Color(nsColor: .underPageBackgroundColor))
        }.task(id: "\(ObjectIdentifier(document))-\(page.page)") {
            let size = page.displayedSize
            let factor = min(2, 1600 / max(size.width, size.height))
            thumbnail = document.page(at: page.page - 1)?.thumbnail(of: CGSize(width: size.width * factor, height: size.height * factor), for: .cropBox)
        }
    }
}
