import SwiftUI
import AppKit
import PDFKit
import CoreText
import UniformTypeIdentifiers
#if canImport(FoundationModels)
import FoundationModels
#endif

struct IntelligenceView: View {
    @EnvironmentObject var model: Workspace
    var initialMode = "summary"
    var body: some View {
        #if canImport(FoundationModels)
        if #available(macOS 26.0, *) { LocalIntelligenceView(initialMode: initialMode).environmentObject(model) }
        else { unavailable }
        #else
        unavailable
        #endif
    }
    private var unavailable: some View {
        ContentUnavailableView("IA local indisponível", systemImage: "sparkles", description: Text("Requer macOS 26 ou posterior, Apple Intelligence habilitada e aplicativo compilado com Xcode 26 ou posterior. Os documentos permanecem no Mac."))
    }
}

/// Character bounds limit input size; the model still enforces its token context limit.
/// Each segment gets its own session, and paragraph boundaries are preferred.
enum IntelligenceText {
    static func chunks(_ text: String, limit: Int = 4_500) -> [String] {
        guard limit > 0 else { return [] }
        var result: [String] = []
        var current = ""
        for paragraph in text.components(separatedBy: "\n") {
            let line = paragraph.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty else { continue }
            var remainder = line[...]
            while let end = remainder.index(remainder.startIndex, offsetBy: limit, limitedBy: remainder.endIndex), end < remainder.endIndex {
                if !current.isEmpty { result.append(current); current = "" }
                result.append(String(remainder[..<end]))
                remainder = remainder[end...]
            }
            let piece = String(remainder)
            if current.count + piece.count + 1 > limit, !current.isEmpty { result.append(current); current = "" }
            current += current.isEmpty ? piece : "\n" + piece
        }
        if !current.isEmpty { result.append(current) }
        return result
    }

    enum DocumentSource: Sendable {
        case file(URL)
        case snapshot(Data)
    }

    /// Uses a fresh PDFDocument exclusively on a worker, never the reader's mutable instance.
    /// The source file is read into immutable memory before extraction; unsaved reader edits
    /// use a captured in-memory representation instead. No decrypted temporary file is made.
    static func documentChunks(from source: DocumentSource,
                               progress: @escaping @Sendable (Int, Int) -> Void) async throws -> [String] {
        let extraction = Task.detached(priority: .userInitiated) { () throws -> [String] in
            try Task.checkCancellation()
            let data: Data
            switch source {
            case .file(let url): data = try Data(contentsOf: url)
            case .snapshot(let snapshot): data = snapshot
            }
            try Task.checkCancellation()
            guard let document = PDFDocument(data: data), document.pageCount > 0 else {
                throw NSError(domain: "PDF", code: 10, userInfo: [NSLocalizedDescriptionKey: "Não foi possível ler o documento para análise."])
            }
            guard !document.isLocked else {
                throw NSError(domain: "PDF", code: 11, userInfo: [NSLocalizedDescriptionKey: "A cópia em memória ainda está protegida. Desbloqueie uma cópia explicitamente antes de usar IA."])
            }
            var result: [String] = []
            for index in 0..<document.pageCount {
                try Task.checkCancellation()
                let pageChunks: [String] = try autoreleasepool {
                    guard let page = document.page(at: index) else {
                        throw NSError(domain: "PDF", code: 12, userInfo: [NSLocalizedDescriptionKey: "Não foi possível ler a página \(index + 1)."])
                    }
                    let fields = page.annotations.compactMap { annotation -> String? in
                        guard let name = annotation.fieldName else { return nil }
                        return "Campo \(name): \(annotation.widgetStringValue ?? "")"
                    }.joined(separator: "\n")
                    let text = (page.string ?? "") + (fields.isEmpty ? "" : "\n" + fields)
                    try Task.checkCancellation()
                    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return [] }
                    return chunks(text, limit: 4_200).map { "[Página \(index + 1)]\n" + $0 }
                }
                try Task.checkCancellation()
                result.append(contentsOf: pageChunks)
                progress(index + 1, document.pageCount)
            }
            return result
        }
        return try await withTaskCancellationHandler {
            try await extraction.value
        } onCancel: { extraction.cancel() }
    }

    struct RetrievedContext: Sendable {
        let text: String
        let pages: [Int]
    }

    /// Only the first generated line is metadata. A page label inside document text
    /// cannot change the citation assigned by the extractor.
    static func sourcePage(in chunk: String) -> Int? {
        guard let first = chunk.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false).first,
              first.hasPrefix("[Página "), first.hasSuffix("]") else { return nil }
        let number = first.dropFirst(8).dropLast()
        guard number.count <= 9, number.allSatisfy({ $0.isASCII && $0.isNumber }), let value = Int(number), value > 0 else { return nil }
        return value
    }

    static func validatedResponse(_ text: String) throws -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 60_000, !trimmed.contains("\0") else {
            throw NSError(domain: "PDF.Intelligence", code: 26,
                          userInfo: [NSLocalizedDescriptionKey: "A IA retornou um trecho vazio ou inválido. O trecho de origem foi preservado; tente novamente."])
        }
        return trimmed
    }

    /// Bounded local lexical retrieval. Every excerpt retains its original page label.
    static func retrieve(question: String, chunks: [String], budget: Int = 6_000) -> RetrievedContext {
        let stop = Set("a o as os um uma de da do das dos e é em no na nos nas para por com que qual quais como quando onde foi são the a an is are of to in and what when how where".split(separator: " ").map(String.init))
        func words(_ value: String) -> Set<String> {
            let plain = value.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "pt_BR"))
            return Set(plain.split { !$0.isLetter && !$0.isNumber }.map(String.init).filter { $0.count > 1 && !stop.contains($0) })
        }
        let terms = words(question)
        var ranked: [(Int, Int, String)] = []
        for (index, chunk) in chunks.enumerated() {
            if Task.isCancelled { return RetrievedContext(text: "", pages: []) }
            // Exclude our page marker from lexical scoring.
            let body = chunk.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false).dropFirst().joined(separator: "\n")
            ranked.append((words(body).intersection(terms).count, index, chunk))
        }
        ranked.sort { $0.0 == $1.0 ? $0.1 < $1.1 : $0.0 > $1.0 }
        let relevant = ranked.filter { $0.0 > 0 }
        if relevant.isEmpty {
            // General questions can use the whole document when it fits. Never silently
            // substitute an arbitrary sample from a longer document with no term matches.
            guard chunks.reduce(0, { $0 + $1.count + 2 }) <= budget else { return RetrievedContext(text: "", pages: []) }
            return context(from: chunks, budget: budget)
        }
        return context(from: relevant.prefix(4).map { $0.2 }, budget: budget)
    }

    static func context(from chunks: [String], budget: Int = 6_000) -> RetrievedContext {
        var output: [String] = [], pages: [Int] = [], remaining = max(0, budget)
        for chunk in chunks {
            guard remaining > 80 else { break }
            guard let page = sourcePage(in: chunk) else { continue }
            let excerpt = String(chunk.prefix(remaining))
            output.append(excerpt); remaining -= excerpt.count + 2
            if !pages.contains(page) { pages.append(page) }
        }
        return RetrievedContext(text: output.joined(separator: "\n\n"), pages: pages.sorted())
    }

    static func decodeJSON<T: Decodable>(_ value: String, as type: T.Type) throws -> T {
        guard let start = value.firstIndex(of: "{"), let end = value.lastIndex(of: "}"), start <= end else {
            throw NSError(domain: "PDF", code: 20, userInfo: [NSLocalizedDescriptionKey: "A IA retornou uma resposta fora do formato esperado. Tente novamente."])
        }
        return try JSONDecoder().decode(type, from: Data(value[start...end].utf8))
    }

    static func PDF(_ text: String, cancellation: NativeCancellation = NativeCancellation()) throws -> Data {
        try cancellation.check()
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw NSError(domain: "PDF.Intelligence", code: 27, userInfo: [NSLocalizedDescriptionKey: "Não há texto para exportar."])
        }
        let buffer = NSMutableData()
        guard let consumer = CGDataConsumer(data: buffer as CFMutableData),
              let context = CGContext(consumer: consumer, mediaBox: nil, nil) else {
            throw NSError(domain: "PDF", code: 1, userInfo: [NSLocalizedDescriptionKey: "Não foi possível criar o PDF."])
        }
        var closed = false
        defer { if !closed { context.closePDF() } }
        let style = NSMutableParagraphStyle(); style.lineSpacing = 4; style.paragraphSpacing = 8
        let attributed = NSAttributedString(string: text, attributes: [.font: NSFont.systemFont(ofSize: 12), .paragraphStyle: style])
        let framesetter = CTFramesetterCreateWithAttributedString(attributed as CFAttributedString)
        var offset = 0
        while offset < attributed.length {
            try cancellation.check()
            var bounds = CGRect(x: 0, y: 0, width: 595, height: 842)
            let media = Data(bytes: &bounds, count: MemoryLayout<CGRect>.size)
            context.beginPDFPage([kCGPDFContextMediaBox as String: media] as CFDictionary)
            let path = CGPath(rect: bounds.insetBy(dx: 42, dy: 42), transform: nil)
            let frame = CTFramesetterCreateFrame(framesetter, CFRange(location: offset, length: 0), path, nil)
            context.textMatrix = .identity
            CTFrameDraw(frame, context)
            let length = CTFrameGetVisibleStringRange(frame).length
            context.endPDFPage()
            guard length > 0 else {
                throw NSError(domain: "PDF", code: 2, userInfo: [NSLocalizedDescriptionKey: "O texto não coube na página de saída."])
            }
            offset += length
        }
        context.closePDF()
        closed = true
        try cancellation.check()
        return try NativePDFSerialization.normalize(data: buffer as Data, cancellation: cancellation)
    }
}

struct PDFChatMessage: Identifiable {
    let id = UUID()
    let user: Bool
    let text: String
    var pages: [Int] = []
    var references: [SourceReference] = []
    var sourceKey = ""
}

struct PDFQuizQuestion: Codable, Identifiable {
    var id: String { question }
    let question: String
    let options: [String]
    let answer: String
    let explanation: String
    let pages: [Int]
    var citations: [ModelCitation]? = nil
    var references: [SourceReference] = []
    var sourceKey = ""
    enum CodingKeys: String, CodingKey { case question, options, answer, explanation, pages, citations }

    /// Structural validation independent of Foundation Models availability.
    func validate(allowedPages: [Int], multipleChoice: Bool) throws {
        func trimmed(_ value: String) -> String { value.trimmingCharacters(in: .whitespacesAndNewlines) }
        func reject(_ message: String) -> NSError {
            NSError(domain: "PDF.Quiz", code: 25, userInfo: [NSLocalizedDescriptionKey: message])
        }
        guard !trimmed(question).isEmpty, !trimmed(answer).isEmpty, !trimmed(explanation).isEmpty else {
            throw reject("A questão precisa de enunciado, resposta e explicação não vazios.")
        }
        guard !pages.isEmpty, pages.allSatisfy({ $0 > 0 }), Set(pages).isSubset(of: Set(allowedPages)) else {
            throw reject("A questão cita páginas que não pertencem às fontes consultadas.")
        }
        if multipleChoice {
            let normalized = options.map { value in
                value.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
                    .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "pt_BR"))
            }
            guard options.count == 4, normalized.allSatisfy({ !$0.isEmpty }), Set(normalized).count == 4 else {
                throw reject("Uma questão de múltipla escolha precisa de quatro alternativas distintas e não vazias.")
            }
            guard ["A", "B", "C", "D"].contains(trimmed(answer)) else {
                throw reject("O gabarito de múltipla escolha precisa indicar A, B, C ou D.")
            }
        } else if !options.isEmpty {
            throw reject("Uma questão aberta não pode conter alternativas de múltipla escolha.")
        }
    }
}

@MainActor final class IntelligenceMemory: ObservableObject {
    static let shared = IntelligenceMemory()
    @Published var messages: [PDFChatMessage] = []
    @Published var quiz: [PDFQuizQuestion] = []
    var sourceKey = ""
    var chunks: [String] = []
    func prepare(key: String) {
        guard sourceKey != key else { return }
        sourceKey = key; chunks = []; messages = []; quiz = []
    }
}

#if canImport(FoundationModels)
@available(macOS 26.0, *)
struct LocalIntelligenceView: View {
    @EnvironmentObject var model: Workspace
    @State private var result = ""
    @State private var status = ""
    @State private var working = false
    @State private var language = "inglês"
    @State private var progress = 0.0
    @State private var operation: Task<Void, Never>?
    @State private var translation = false
    @State private var preserveLayout = true
    @State private var saved: URL?
    @State private var mode: String
    @State private var question = ""
    @State private var quizCount = 5
    @State private var quizStyle = "Múltipla escolha"
    @State private var quizDifficulty = "Intermediário"
    @State private var quizTopic = ""
    @State private var retrievalMethod = ""
    @State private var foundSources: [SourceExcerpt] = []
    @State private var foundSourceKey = ""
    @State private var resultReferences: [SourceReference] = []
    @State private var resultSourceKey = ""
    @StateObject private var memory = IntelligenceMemory.shared
    init(initialMode: String = "summary") { _mode = State(initialValue: initialMode) }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("Inteligência no seu Mac", systemImage: "sparkles").font(.largeTitle.bold())
            Text((model.savedDocumentURL ?? model.url)?.lastPathComponent ?? "Nenhum documento aberto").font(.headline)
            Picker("Ferramenta de IA", selection: $mode) {
                Text("Resumo").tag("summary"); Text("Tradução").tag("translate")
                Text("Chat com PDF").tag("chat"); Text("Questões").tag("quiz")
            }.pickerStyle(.segmented).disabled(working)
            Text("Busca e IA locais. As citações são conferidas contra os trechos originais; isso não comprova a interpretação da IA. Confira as fontes.").font(.caption).foregroundStyle(.secondary)
            if mode == "chat" { chatControls }
            else if mode == "quiz" { quizControls }
            else { documentControls }
            if working {
                HStack { ProgressView(value: progress); Button("Cancelar") { operation?.cancel() } }
            }
            if !status.isEmpty { Text(status).font(.caption).textSelection(.enabled) }
            if !retrievalMethod.isEmpty { Text(retrievalMethod).font(.caption).foregroundStyle(.secondary) }
            if mode == "chat" { chatResults }
            else if mode == "quiz" { quizResults }
            else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(result.isEmpty ? "Abra um PDF no leitor e escolha uma ação." : result).textSelection(.enabled)
                        references(resultReferences, sourceKey: resultSourceKey)
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(18)
                }.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }
            HStack {
                Text("O contexto do chat é uma seleção de trechos encontrados por busca local. Perguntas específicas produzem referências mais úteis.").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Menu("Exportar…") {
                    Button("Texto (.txt)") { export(type: .plainText, fileExtension: "txt") }
                    Button("Markdown (.md)") { export(type: .plainText, fileExtension: "md") }
                    Button("PDF (.pdf)") { export(type: .pdf, fileExtension: "pdf") }
                }.disabled(exportText.isEmpty || working)
            }
            if let saved { Button("Mostrar arquivo exportado") { NSWorkspace.shared.activateFileViewerSelecting([saved]) } }
        }.padding(28).onAppear { memory.prepare(key: documentKey) }
            .onChange(of: documentKey) { _, key in operation?.cancel(); memory.prepare(key: key); result = ""; status = ""; foundSources = []; resultReferences = []; retrievalMethod = "" }
            .onDisappear { operation?.cancel() }
    }

    private var documentControls: some View {
        VStack(alignment: .leading, spacing: 12) {
            if mode == "summary" {
                Button("Resumir documento") { generate(translation: false) }.disabled(working || model.document == nil)
            } else {
                HStack {
                    TextField("Idioma de destino", text: $language).textFieldStyle(.roundedBorder).frame(maxWidth: 260)
                    Button(preserveLayout ? "Traduzir PDF" : "Traduzir texto") { if preserveLayout { translateLayout() } else { generate(translation: true) } }
                        .disabled(working || model.busy || model.document == nil || language.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                Toggle("Preservar posições dos blocos e imagens", isOn: $preserveLayout).disabled(working)
                if preserveLayout { Text("Fontes podem ser substituídas. O tamanho é reduzido até 8 pontos para caber; o arquivo não é criado se um bloco não couber. Revise o layout final.").font(.caption).foregroundStyle(.secondary) }
            }
        }
    }

    private var chatControls: some View {
        HStack {
            TextField("Pergunte sobre o documento…", text: $question).textFieldStyle(.roundedBorder).onSubmit { askDocument() }
            Button("Buscar fontes") { searchSources() }.disabled(working || model.document == nil || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button("Enviar", systemImage: "arrow.up.circle.fill") { askDocument() }.disabled(working || model.document == nil || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button("Limpar conversa") { memory.messages = [] }.disabled(working || memory.messages.isEmpty)
        }
    }

    private var chatResults: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                if memory.messages.isEmpty { Text("Busque trechos relacionados à pergunta, inclusive por significado quando houver embeddings no Mac. Buscar fontes funciona sem o modelo gerador.").foregroundStyle(.secondary) }
                if !foundSources.isEmpty {
                    DisclosureGroup("Trechos encontrados (\(foundSources.count))") {
                        ForEach(foundSources) { excerpt in
                            VStack(alignment: .leading, spacing: 6) {
                                Button("Abrir página \(excerpt.page) · \(excerpt.id)") { openReference(SourceReference(excerpt: excerpt.id, page: excerpt.page, quote: String(excerpt.text.prefix(240))), sourceKey: foundSourceKey) }
                                Text(excerpt.text).font(.callout).textSelection(.enabled)
                            }.padding(.vertical, 6)
                        }
                    }
                }
                ForEach(memory.messages) { message in
                    VStack(alignment: .leading, spacing: 8) {
                        Label(message.user ? "Você" : "PDF", systemImage: message.user ? "person.crop.circle" : "sparkles").font(.headline)
                        Text(message.text).textSelection(.enabled)
                        references(message.references, sourceKey: message.sourceKey)
                    }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(message.user ? Color.accentColor.opacity(0.08) : .clear, in: RoundedRectangle(cornerRadius: 12))
                }
            }.padding(16)
        }.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private var quizControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Picker("Quantidade", selection: $quizCount) { Text("3").tag(3); Text("5").tag(5); Text("10").tag(10) }.frame(width: 150)
                Picker("Formato", selection: $quizStyle) { Text("Múltipla escolha").tag("Múltipla escolha"); Text("Abertas").tag("Abertas") }
                Picker("Nível", selection: $quizDifficulty) { Text("Básico").tag("Básico"); Text("Intermediário").tag("Intermediário"); Text("Avançado").tag("Avançado") }
            }
            HStack {
                TextField("Tema ou palavras-chave (opcional)", text: $quizTopic).textFieldStyle(.roundedBorder)
                Button("Gerar questões") { generateQuiz() }.disabled(working || model.document == nil)
            }
        }.disabled(working)
    }

    private var quizResults: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                if memory.quiz.isEmpty { Text("Gere questões com respostas comentadas e referências às páginas. O gabarito pode ser aberto individualmente e será incluído na exportação.").foregroundStyle(.secondary) }
                ForEach(Array(memory.quiz.enumerated()), id: \.offset) { index, item in
                    VStack(alignment: .leading, spacing: 9) {
                        Text("\(index + 1). \(item.question)").font(.headline).textSelection(.enabled)
                        ForEach(Array(item.options.enumerated()), id: \.offset) { option, text in Text("\(["A", "B", "C", "D"][min(option, 3)]). \(text)").textSelection(.enabled) }
                        DisclosureGroup("Gabarito e explicação") { Text(item.answer + "\n\n" + item.explanation).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                        references(item.references, sourceKey: item.sourceKey)
                    }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
            }.padding(16)
        }
    }

    private var documentKey: String {
        ((model.savedDocumentURL ?? model.url)?.standardizedFileURL.path ?? "memory") + ":" + String(model.annotationRevision) + ":" + (model.document.map { String(describing: ObjectIdentifier($0)) } ?? "none")
    }
    @ViewBuilder private func references(_ items: [SourceReference], sourceKey: String) -> some View {
        if !items.isEmpty {
            DisclosureGroup("Conferir \(items.count) referência(s)") {
                ForEach(items) { reference in
                    VStack(alignment: .leading, spacing: 5) {
                        Button("Abrir página \(reference.page) · \(reference.excerpt)") { openReference(reference, sourceKey: sourceKey) }
                            .accessibilityLabel("Abrir fonte na página \(reference.page): \(reference.quote.prefix(80))")
                        Text("“" + reference.quote + "”").font(.callout).textSelection(.enabled)
                    }.padding(.vertical, 5)
                }
            }.font(.caption)
        }
    }
    private func openReference(_ reference: SourceReference, sourceKey: String) {
        guard sourceKey == documentKey, let page = model.document?.page(at: reference.page - 1) else {
            status = "O documento de origem mudou. Execute a busca novamente antes de abrir esta referência."; return
        }
        let fields = page.annotations.compactMap { annotation -> String? in
            guard let name = annotation.fieldName else { return nil }
            return "Campo \(name): \(annotation.widgetStringValue ?? "")"
        }.joined(separator: "\n")
        guard SemanticEvidence.normalized((page.string ?? "") + "\n" + fields).contains(SemanticEvidence.normalized(reference.quote)) else {
            status = "O trecho citado mudou no documento aberto. A referência anterior foi preservada para revisão; gere uma nova resposta."; return
        }
        model.goToPage(reference.page); model.section = "Leitor"
    }
    private func referenceText(_ items: [SourceReference]) -> String {
        items.map { "- Página \($0.page), trecho \($0.excerpt): “\($0.quote)”" }.joined(separator: "\n")
    }
    private var exportText: String {
        if mode == "chat" { return memory.messages.map { "## " + ($0.user ? "Você" : "PDF") + "\n\n" + $0.text + ($0.references.isEmpty ? "" : "\n\nFontes:\n" + referenceText($0.references)) }.joined(separator: "\n\n") }
        if mode == "quiz" {
            let questions = memory.quiz.enumerated().map { index, item in
                "## Questão \(index + 1)\n\n" + item.question + "\n\n" + item.options.enumerated().map { "\(["A", "B", "C", "D"][min($0.offset, 3)]). \($0.element)" }.joined(separator: "\n")
            }.joined(separator: "\n\n")
            let answers = memory.quiz.enumerated().map { index, item in "\(index + 1). " + item.answer + " — " + item.explanation + "\n" + referenceText(item.references) }.joined(separator: "\n\n")
            return memory.quiz.isEmpty ? "" : questions + "\n\n# Gabarito\n\n" + answers
        }
        return result + (resultReferences.isEmpty ? "" : "\n\n# Fontes verificáveis\n\n" + referenceText(resultReferences))
    }

    private func export(type: UTType, fileExtension: String) {
        guard !working else { return }
        let toolName = mode == "chat" ? "Conversa com IA" : mode == "quiz" ? "Questões com IA" : translation ? "Tradução" : "Resumo"
        guard let destination = NativeOutput.destination(model: model, toolName: toolName, extension: fileExtension) else { return }
        let text = exportText
        let cancellation = NativeCancellation()
        working = true; progress = 0; status = "Preparando exportação…"
        operation = Task { @MainActor in
            defer { working = false; operation = nil }
            do {
                try await withTaskCancellationHandler {
                    let worker = Task.detached(priority: .userInitiated) {
                        try cancellation.check()
                        let data = fileExtension == "pdf" ? try IntelligenceText.PDF(text, cancellation: cancellation) : Data(text.utf8)
                        try cancellation.check()
                        try NativeOutput.write(data, to: destination)
                    }
                    try await worker.value
                } onCancel: { cancellation.cancel() }
                // Publication is atomic. A cancellation arriving after the link
                // committed must not hide the successfully exported file.
                saved = destination; progress = 1; status = "Exportado: \(destination.lastPathComponent)"
            } catch is CancellationError { status = "Exportação cancelada. Nenhum resultado foi publicado." }
            catch { status = "Falha na exportação: \(error.localizedDescription)" }
        }
    }

    private func modelAvailable() -> Bool {
        switch SystemLanguageModel.default.availability {
        case .available: return true
        case .unavailable(let reason): status = "Apple Intelligence indisponível: \(reason). Verifique as configurações do macOS."; return false
        }
    }

    @MainActor private func preparedChunks(document: PDFDocument, url: URL?, snapshot: Bool, key: String) async throws -> [String] {
        memory.prepare(key: key)
        if !snapshot, !memory.chunks.isEmpty { return memory.chunks }
        await Task.yield(); try Task.checkCancellation()
        // Use the reader's exact document snapshot: a file changed externally
        // must not produce citations for a different version than the reader.
        // Keep this representation exclusively in memory, including unlocked
        // encrypted documents. Normalizing it through an external process would
        // create a decrypted temporary file. Only final user-requested exports
        // pass through the output serializer.
        guard let data = document.dataRepresentation() else {
            throw NSError(domain: "PDF", code: 21, userInfo: [NSLocalizedDescriptionKey: "Não foi possível capturar o documento aberto."])
        }
        let source = IntelligenceText.DocumentSource.snapshot(data)
        let chunks = try await IntelligenceText.documentChunks(from: source) { completed, total in
            DispatchQueue.main.async {
                progress = 0.1 * Double(completed) / Double(max(total, 1))
                status = "Lendo página \(completed) de \(total)…"
            }
        }
        try Task.checkCancellation()
        guard memory.sourceKey == key else { throw CancellationError() }
        guard !chunks.isEmpty else {
            throw NSError(domain: "PDF", code: 22, userInfo: [NSLocalizedDescriptionKey: "O PDF não contém texto selecionável. Execute OCR antes de usar esta ferramenta."])
        }
        memory.chunks = chunks
        return chunks
    }

    private func askDocument() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        let questionText = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !working, !questionText.isEmpty, let document = model.document, modelAvailable() else { return }
        guard questionText.count <= 800 else { status = "Use até 800 caracteres por pergunta."; return }
        guard !document.isLocked else { status = "Desbloqueie o documento no leitor."; return }
        let key = documentKey, source = model.savedDocumentURL ?? model.url, snapshot = model.hasUnsavedChanges || document.isEncrypted
        memory.prepare(key: key)
        let previousQuestion = memory.messages.last(where: { $0.user })?.text ?? ""
        let history = String(memory.messages.suffix(4).map { ($0.user ? "Usuário: " : "PDF: ") + String($0.text.prefix(250)) }.joined(separator: "\n").suffix(1_000))
        memory.messages.append(PDFChatMessage(user: true, text: questionText))
        question = ""; working = true; progress = 0; status = "Buscando evidências no documento…"; saved = nil
        operation = Task { @MainActor in
            defer { working = false; operation = nil }
            do {
                let chunks = try await preparedChunks(document: document, url: source, snapshot: snapshot, key: key)
                let lookup = questionText + " " + String(previousQuestion.suffix(300))
                let context = try await LocalSemanticIndex.shared.retrieve(question: lookup, chunks: chunks, source: key)
                try Task.checkCancellation()
                retrievalMethod = context.method; foundSources = context.excerpts; foundSourceKey = key
                guard !context.isEmpty else {
                    memory.messages.append(PDFChatMessage(user: false, text: "Não encontrei trechos com evidências suficientes para essa pergunta. Tente incluir palavras ou nomes presentes no documento."))
                    status = "Nenhuma fonte correspondente encontrada."; return
                }
                progress = 0.5; status = "Preparando resposta com referências…"
                let session = LanguageModelSession(instructions: GroundedPrompt.trust + "\nResponda somente com base nas fontes desta solicitação. Cada afirmação factual precisa estar sustentada pelas citações. Retorne apenas JSON válido: {\"supported\":true,\"answer\":\"resposta em português\",\"citations\":[{\"excerpt\":\"ID exato de um trecho fornecido\",\"quote\":\"cópia literal de frase que sustenta a resposta\"}]}. Não cite apenas uma página: use o ID e uma frase de pelo menos 12 caracteres do trecho. Se faltar apoio, supported deve ser false, citations deve ser [] e answer deve explicar a insuficiência.")
                let prompt = "Pergunta do usuário: \(questionText)\n" + (try GroundedPrompt.data(context.excerpts, history: history))
                let response = try await session.respond(to: prompt)
                try Task.checkCancellation()
                let answer = try IntelligenceText.decodeJSON(response.content, as: GroundedAnswer.self)
                let (text, citations) = try answer.validated(in: context)
                guard documentKey == key else { throw CancellationError() }
                memory.messages.append(PDFChatMessage(user: false, text: text, pages: Array(Set(citations.map(\.page))).sorted(), references: citations, sourceKey: key))
                progress = 1; status = citations.isEmpty ? "Sem apoio suficiente nos trechos consultados." : "Citações conferidas no texto original. Abra as fontes para revisar a interpretação."
            } catch is CancellationError { status = "Pergunta cancelada." }
            catch { status = "Não foi possível responder: \(error.localizedDescription)" }
        }
    }

    private func searchSources() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        let lookup = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !working, !lookup.isEmpty, let document = model.document, !document.isLocked else { return }
        guard lookup.count <= 800 else { status = "Use até 800 caracteres por busca."; return }
        let key = documentKey, source = model.savedDocumentURL ?? model.url
        let snapshot = model.hasUnsavedChanges || document.isEncrypted
        working = true; status = "Buscando fontes locais…"; progress = 0; foundSources = []
        operation = Task { @MainActor in
            defer { working = false; operation = nil }
            do {
                let chunks = try await preparedChunks(document: document, url: source, snapshot: snapshot, key: key)
                let context = try await LocalSemanticIndex.shared.retrieve(question: lookup, chunks: chunks, source: key)
                try Task.checkCancellation()
                guard documentKey == key else { throw CancellationError() }
                foundSources = context.excerpts; foundSourceKey = key; retrievalMethod = context.method; progress = 1
                status = context.isEmpty ? "Nenhum trecho correspondente encontrado. Tente uma pergunta mais específica." : "\(context.excerpts.count) trechos encontrados. A busca não gerou uma resposta nem avaliou sua veracidade."
            } catch is CancellationError { status = "Busca cancelada." }
            catch { status = "Não foi possível buscar: \(error.localizedDescription)" }
        }
    }

    private func generateQuiz() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard !working, let document = model.document, modelAvailable() else { return }
        guard !document.isLocked else { status = "Desbloqueie o documento no leitor."; return }
        let key = documentKey, source = model.savedDocumentURL ?? model.url, snapshot = model.hasUnsavedChanges || document.isEncrypted
        let count = quizCount, style = quizStyle, difficulty = quizDifficulty, topic = String(quizTopic.prefix(500))
        memory.prepare(key: key); memory.quiz = []
        working = true; progress = 0; status = "Preparando fontes das questões…"; saved = nil
        operation = Task { @MainActor in
            defer { working = false; operation = nil }
            do {
                let chunks = try await preparedChunks(document: document, url: source, snapshot: snapshot, key: key)
                for index in 0..<count {
                    try Task.checkCancellation()
                    let context: SemanticContext
                    if topic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        let position = min(chunks.count - 1, index * chunks.count / count)
                        context = SemanticEvidence.bounded(SemanticEvidence.excerpts(from: chunks).filter { $0.id.contains("-t\(position + 1)-") }, budget: 5_000, method: "Seleção distribuída pelo documento")
                    } else {
                        context = try await LocalSemanticIndex.shared.retrieve(question: topic, chunks: chunks, source: key)
                    }
                    try Task.checkCancellation()
                    retrievalMethod = context.method
                    guard !context.isEmpty else {
                        throw NSError(domain: "PDF", code: 24, userInfo: [NSLocalizedDescriptionKey: "Não foram encontrados trechos para esse tema. Use termos do documento ou deixe o tema em branco."])
                    }
                    status = "Gerando questão \(index + 1) de \(count)…"
                    let instructions = GroundedPrompt.trust + "\nCrie uma questão cuja resposta possa ser confirmada nas fontes. Retorne somente JSON: {\"question\":\"enunciado\",\"options\":[\"opções, se aplicável\"],\"answer\":\"resposta\",\"explanation\":\"justificativa\",\"pages\":[páginas das fontes citadas],\"citations\":[{\"excerpt\":\"ID exato do trecho consultado\",\"quote\":\"frase literal da fonte que comprova o gabarito\"}]}. A citação deve ter pelo menos 12 caracteres."
                    let format = style == "Múltipla escolha" ? "Forneça exatamente quatro options, sem prefixo A/B/C/D. answer deve ser somente A, B, C ou D. Apenas uma opção correta." : "Forneça uma pergunta aberta. options deve ser []. answer deve conter a resposta esperada."
                    let previous = String(memory.quiz.map(\.question).joined(separator: "\n").suffix(800))
                    let prompt = "Idioma português. Nível: \(difficulty). \(format)\nEvite repetir questões presentes no histórico. Páginas permitidas: \(context.pages).\n" + (try GroundedPrompt.data(context.excerpts, history: previous))
                    let session = LanguageModelSession(instructions: instructions)
                    let response = try await session.respond(to: prompt)
                    try Task.checkCancellation()
                    var item = try IntelligenceText.decodeJSON(response.content, as: PDFQuizQuestion.self)
                    try item.validate(allowedPages: context.pages, multipleChoice: style == "Múltipla escolha")
                    item.references = try SemanticEvidence.validate(item.citations ?? [], in: context)
                    guard Set(item.pages) == Set(item.references.map(\.page)) else { throw SemanticEvidence.failure("As páginas da questão não correspondem aos trechos citados.") }
                    item.sourceKey = key
                    guard documentKey == key else { throw CancellationError() }
                    guard !memory.quiz.contains(where: { $0.question.caseInsensitiveCompare(item.question) == .orderedSame }) else {
                        throw NSError(domain: "PDF", code: 25, userInfo: [NSLocalizedDescriptionKey: "A IA retornou uma questão sem estrutura ou referências válidas. As questões anteriores foram preservadas; gere novamente para tentar outra seleção."])
                    }
                    memory.quiz.append(item)
                    progress = 0.1 + 0.9 * Double(index + 1) / Double(count)
                }
                status = "\(memory.quiz.count) questões geradas com gabarito e páginas de origem. Revise antes de aplicar."
            } catch is CancellationError { status = "Geração cancelada. Questões concluídas permanecem disponíveis." }
            catch { status = "Geração interrompida: \(error.localizedDescription)" }
        }
    }

    private func translateLayout() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let document = model.document, let source = model.savedDocumentURL ?? model.url else { return }
        guard !document.isEncrypted, !document.isLocked else { status = "Desbloqueie uma cópia explicitamente antes de traduzir um PDF protegido."; return }
        guard !model.hasUnsavedChanges else { status = "Salve e abra uma cópia das alterações do leitor antes de traduzir o layout."; return }
        guard case .available = SystemLanguageModel.default.availability else { status = "Apple Intelligence não está disponível neste Mac."; return }
        guard let destination = NativeOutput.destination(model: model, toolName: "Tradução", originalURL: source) else { return }
        let targetLanguage = String(language.prefix(80))
        let key = documentKey
        working = true; translation = true; progress = 0; result = ""; status = "Lendo blocos do documento…"; saved = nil; resultReferences = []; resultSourceKey = key
        operation = Task { @MainActor in
            defer { working = false; operation = nil }
            do {
                let blocks = try await LayoutExtraction.blocks(from: source)
                guard !blocks.isEmpty else { status = "Nenhum bloco de texto encontrado. Execute OCR primeiro."; return }
                var edits: [[String: Any]] = []
                var completed: [String] = []
                for (index, block) in blocks.enumerated() {
                    try Task.checkCancellation()
                    status = "Traduzindo bloco \(index + 1) de \(blocks.count), página \(block.page)…"
                    var translated: [String] = []
                    for chunk in IntelligenceText.chunks(block.text) {
                        let session = LanguageModelSession(instructions: GroundedPrompt.trust + "\nTraduza somente o texto das fontes, sem comentários nem formatação Markdown adicional. Preserve nomes, números, códigos e unidades.")
                        let excerpt = SourceExcerpt(id: block.id, page: block.page, text: chunk)
                        let response = try await session.respond(to: "Traduza integralmente para \(targetLanguage).\n" + (try GroundedPrompt.data([excerpt])))
                        try Task.checkCancellation()
                        translated.append(try IntelligenceText.validatedResponse(response.content))
                    }
                    let text = translated.joined(separator: "\n")
                    edits.append(["id": block.id, "page": block.page, "rect": block.rect, "text": text,
                                  "font_size": block.font_size, "color": block.color, "source_text": block.text])
                    completed.append("### Página \(block.page) · bloco \(index + 1)\n\n" + text)
                    resultReferences.append(SourceReference(excerpt: block.id, page: block.page, quote: String(block.text.prefix(240))))
                    result = completed.joined(separator: "\n\n")
                    progress = Double(index + 1) / Double(blocks.count)
                }
                try Task.checkCancellation()
                guard documentKey == key else { throw CancellationError() }
                guard !model.busy else { status = "Outro processamento está em curso. As traduções de texto foram preservadas para exportação; execute novamente quando terminar."; return }
                model.execute(operation: "translate-layout", inputs: [source], output: destination,
                              options: ["edits": edits, "min_font_size": 8], title: "Gerando PDF traduzido")
                status = "Tradução concluída. O motor está aplicando os blocos e verificando o encaixe; acompanhe o resultado na barra de estado."
            } catch is CancellationError { status = "Tradução cancelada. Nenhum PDF foi publicado; os blocos concluídos continuam disponíveis para exportação." }
            catch { status = "Tradução interrompida: \(error.localizedDescription). Os blocos concluídos foram preservados." }
        }
    }

    private func generate(translation: Bool) {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let document = model.document else { return }
        switch SystemLanguageModel.default.availability {
        case .available: break
        case .unavailable(let reason):
            status = "Modelo indisponível: \(reason). Verifique Apple Intelligence nas configurações do macOS."
            return
        }
        guard !document.isLocked else { status = "Desbloqueie o documento no leitor antes de usar IA."; return }
        let sourceURL = model.savedDocumentURL ?? model.url
        let needsSnapshot = model.hasUnsavedChanges || document.isEncrypted || sourceURL == nil
        let targetLanguage = String(language.prefix(80))
        let key = documentKey
        self.translation = translation
        working = true; result = ""; status = "Preparando leitura do documento…"; progress = 0; saved = nil; resultReferences = []; resultSourceKey = key
        operation = Task { @MainActor in
            defer { working = false; operation = nil }
            do {
                // Let the UI display progress/cancellation before capturing an edited document.
                await Task.yield()
                try Task.checkCancellation()
                let chunks = try await preparedChunks(document: document, url: sourceURL, snapshot: needsSnapshot, key: key)
                try Task.checkCancellation()
                guard !chunks.isEmpty else { status = "Documento sem texto selecionável. Execute OCR primeiro."; return }
                status = "Preparando \(chunks.count) trechos…"
                var responses: [String] = []
                for (index, chunk) in chunks.enumerated() {
                    try Task.checkCancellation()
                    status = "\(translation ? "Traduzindo" : "Resumindo") trecho \(index + 1) de \(chunks.count)…"
                    let page = IntelligenceText.sourcePage(in: chunk) ?? 1
                    let body = chunk.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false).dropFirst().joined(separator: "\n")
                    let excerpt = SourceExcerpt(id: "p\(page)-resumo\(index + 1)", page: page, text: body)
                    let instructions = GroundedPrompt.trust + (translation ? "\nRetorne apenas a tradução completa do texto das fontes." : "\nRetorne somente JSON: {\"supported\":true,\"answer\":\"resumo em até cinco tópicos curtos\",\"citations\":[{\"excerpt\":\"ID exato da fonte\",\"quote\":\"frase literal de pelo menos 12 caracteres que sustenta o resumo\"}]}. Se não houver conteúdo factual suficiente, supported deve ser false e citations vazio.")
                    let session = LanguageModelSession(instructions: instructions)
                    let prompt = translation
                        ? "Traduza integralmente este trecho para \(targetLanguage). Preserve marcações de página. Retorne somente a tradução."
                        : "Resuma o trecho em português. Preserve fatos, conclusões e valores; cite somente a fonte fornecida."
                    let response = try await session.respond(to: prompt + (try GroundedPrompt.data([excerpt])))
                    try Task.checkCancellation()
                    guard documentKey == key else { throw CancellationError() }
                    if translation {
                        responses.append(try IntelligenceText.validatedResponse(response.content))
                        resultReferences.append(SourceReference(excerpt: excerpt.id, page: page, quote: String(body.prefix(240))))
                    } else {
                        let answer = try IntelligenceText.decodeJSON(response.content, as: GroundedAnswer.self)
                        let context = SemanticContext(excerpts: [excerpt], method: "Leitura sequencial")
                        let (text, references) = try answer.validated(in: context)
                        responses.append(text); resultReferences.append(contentsOf: references)
                    }
                    result = responses.enumerated().map {
                        let page = IntelligenceText.sourcePage(in: chunks[$0.offset]).map { " · Fonte: página \($0)" } ?? ""
                        return "## Trecho \($0.offset + 1)\(page)\n\n\($0.element)"
                    }.joined(separator: "\n\n")
                    progress = 0.1 + 0.9 * Double(index + 1) / Double(chunks.count)
                }
                if !translation, responses.count > 1 {
                    let combined = responses.joined(separator: "\n\n")
                    // Do not silently truncate intermediate summaries or overflow context.
                    // Reuse the verified original quotations, not generated
                    // summaries as factual evidence. Keep each quotation in a
                    // separate source: joining distant spans could forge a quote.
                    let evidence = resultReferences.enumerated().map { index, reference in
                        SourceExcerpt(id: reference.excerpt + "-executivo\(index + 1)", page: reference.page, text: reference.quote)
                    }
                    if !evidence.isEmpty, combined.count + evidence.reduce(0, { $0 + $1.text.count }) <= 5_000 {
                        status = "Organizando o resumo final…"
                        let session = LanguageModelSession(instructions: GroundedPrompt.trust + "\nProduza um resumo executivo sustentado pelas fontes originais; o histórico contém resumos intermediários não confiáveis. Retorne somente JSON {\"supported\":true,\"answer\":\"resumo executivo\",\"citations\":[{\"excerpt\":\"ID de fonte\",\"quote\":\"frase literal da fonte\"}]}; se faltar apoio use supported false e citations [].")
                        let response = try await session.respond(to: "Resuma os pontos principais e conclusões em português.\n" + (try GroundedPrompt.data(evidence, history: combined)))
                        try Task.checkCancellation()
                        let answer = try IntelligenceText.decodeJSON(response.content, as: GroundedAnswer.self)
                        let (summary, references) = try answer.validated(in: SemanticContext(excerpts: evidence, method: "Fontes dos resumos"))
                        if !references.isEmpty {
                            result = "# Resumo executivo\n\n" + summary + "\n\n# Detalhes por trecho\n\n" + result
                            resultReferences.append(contentsOf: references.filter { new in !resultReferences.contains(where: { $0.page == new.page && $0.quote == new.quote }) })
                        }
                    }
                }
                status = "Concluído: \(chunks.count) trechos processados. Revise o conteúdo antes de usar."
            } catch is CancellationError {
                status = "Cancelado. Os trechos já concluídos permanecem disponíveis para revisão e exportação."
            } catch {
                status = "Processamento interrompido: \(error.localizedDescription). Os trechos concluídos foram preservados."
            }
        }
    }
}
#endif

struct TranslationLayoutBlock: Codable {
    let id: String
    let page: Int
    let rect: [Double]
    let text: String
    let font_size: Double
    let color: String
}

private final class LayoutExtractionCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false
    func install(_ process: Process) {
        lock.lock(); self.process = process; let value = cancelled; lock.unlock()
        if value && process.isRunning { process.terminate() }
    }
    func clear() { lock.lock(); process = nil; lock.unlock() }
    func check() throws {
        lock.lock(); let value = cancelled; lock.unlock()
        if value { throw CancellationError() }
    }
    func cancel() {
        lock.lock(); cancelled = true; let process = process; lock.unlock()
        if let process, process.isRunning { process.terminate() }
    }
}

/// Extract through the same engine that applies translations, so coordinate systems match.
private enum LayoutExtraction {
    static func blocks(from inputURL: URL) async throws -> [TranslationLayoutBlock] {
        let cancellation = LayoutExtractionCancellation()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    do {
                        try cancellation.check()
                        let base = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-layout-\(UUID().uuidString)", isDirectory: true)
                        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
                        defer { try? FileManager.default.removeItem(at: base) }
                        let output = base.appendingPathComponent("blocks.json")
                        let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                        let project = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                        let bundledPython = resources.appendingPathComponent("runtime/bin/python3")
                        let python = FileManager.default.isExecutableFile(atPath: bundledPython.path) ? bundledPython : project.appendingPathComponent(".venv/bin/python3")
                        let bundledEngine = resources.appendingPathComponent("engine/pdf_engine.py")
                        let engine = FileManager.default.fileExists(atPath: bundledEngine.path) ? bundledEngine : project.appendingPathComponent("engine/pdf_engine.py")
                        guard FileManager.default.isExecutableFile(atPath: python.path), FileManager.default.fileExists(atPath: engine.path) else {
                            throw NSError(domain: "PDF", code: 3, userInfo: [NSLocalizedDescriptionKey: "O motor local não está instalado."])
                        }
                        let process = Process(); process.executableURL = python
                        process.arguments = [engine.path, "layout-extract", inputURL.path, "--output", output.path]
                        var environment = ProcessInfo.processInfo.environment; environment["PDF_OPTIONS_STDIN"] = "1"
                        environment["PATH"] = python.deletingLastPathComponent().path + ":/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin")
                        process.environment = environment
                        let input = try EngineInputTransport(data: Data("{}".utf8)), log = Pipe()
                        defer { input.close(); try? log.fileHandleForReading.close() }
                        process.standardInput = input.handle; process.standardOutput = log; process.standardError = log
                        let runtimeLease = try BundleRuntimeLease.configureRuntimeChild(process)
                        defer { try? runtimeLease?.close() }
                        try cancellation.check(); try process.run(); cancellation.install(process)
                        defer { cancellation.clear() }
                        let bytes = log.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
                        try cancellation.check()
                        guard process.terminationStatus == 0 else {
                            let raw = String(data: bytes, encoding: .utf8) ?? "Falha na extração de blocos."
                            throw NSError(domain: "PDF", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: String(raw.suffix(2_000))])
                        }
                        let blocks = try JSONDecoder().decode([TranslationLayoutBlock].self, from: Data(contentsOf: output))
                        continuation.resume(returning: blocks)
                    } catch { continuation.resume(throwing: error) }
                }
            }
        } onCancel: { cancellation.cancel() }
    }
}
