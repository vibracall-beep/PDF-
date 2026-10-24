import SwiftUI
import AppKit
import UniformTypeIdentifiers

@MainActor final class DocumentLibraryController: ObservableObject {
    @Published var catalog: LibraryCatalog?
    @Published var message = ""
    @Published var busy = false
    private(set) var openingReader = false
    @Published var result: LibrarySearchResult?
    @Published var answer: LibraryGeneratedAnswer?
    let store: DocumentLibraryStore
    let retrieval = LibraryRetrieval()
    private var task: Task<Void, Never>?
    private var cancellation: NativeCancellation?
    init(directory: URL? = nil) { store = DocumentLibraryStore(directory: directory ?? DocumentLibraryStore.defaultDirectory) }
    deinit { task?.cancel(); cancellation?.cancel() }
    func run(_ title: String, opensReader: Bool = false, action: @escaping @MainActor (NativeCancellation) async throws -> String) {
        guard !busy else { return }
        busy = true; message = title; openingReader = opensReader
        let cancellation = NativeCancellation(); self.cancellation = cancellation
        task = Task { [weak self] in
            guard let self else { return }
            defer { self.busy = false; self.task = nil; self.cancellation = nil; self.openingReader = false }
            do { self.message = try await action(cancellation) }
            catch is CancellationError { self.message = "Operação cancelada. A última versão completa continua disponível." }
            catch { self.message = error.localizedDescription }
        }
    }
    func load() { run("Carregando biblioteca…") { [self] _ in catalog = try await store.list(); return "Biblioteca local pronta." } }
    func cancel() { task?.cancel(); cancellation?.cancel() }
}

struct DocumentLibraryView: View {
    @EnvironmentObject private var model: Workspace
    @EnvironmentObject private var preferences: AppearancePreferences
    @StateObject private var library: DocumentLibraryController
    @State private var selected = Set<UUID>()
    @State private var filter = LibrarySmartFilter()
    @State private var question = ""
    @State private var passwords: [UUID: String] = [:]
    @State private var searchSelectedOnly = true
    @State private var useEmbeddings = true
    @State private var editing: LibraryDocument?
    @State private var showSync = false
    @State private var showSettingsExchange = false
    @State private var title = ""
    @State private var collection = ""
    @State private var tags = ""
    init(directory: URL? = nil) { _library = StateObject(wrappedValue: DocumentLibraryController(directory: directory)) }
    private var documents: [LibraryDocument] { library.catalog?.documents ?? [] }
    private var displayed: [LibraryDocument] { filter.apply(documents) }
    private var single: LibraryDocument? { selected.count == 1 ? documents.first { selected.contains($0.id) } : nil }
    private var unavailable: Bool { library.busy || model.busy }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            HSplitView {
                VStack(alignment: .leading, spacing: 12) {
                    filters
                    documentList
                }.padding(18).frame(minWidth: 290, idealWidth: 370)
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        if let document = single { detail(document) }
                        else { ContentUnavailableView("Sua coleção de PDFs", systemImage: "books.vertical", description: Text("Selecione um documento para consultar versões ou vários para pesquisar nas fontes.")) }
                        retrievalPanel
                    }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
                }.frame(minWidth: 330)
            }
            Divider()
            HStack(spacing: 10) {
                if library.busy { ProgressView().controlSize(.small) }
                Text(library.message).font(.caption).lineLimit(3).textSelection(.enabled)
                Spacer()
                if library.busy { Button("Cancelar", action: library.cancel) }
            }.padding(12)
        }
        .task { if library.catalog == nil { library.load() } }
        .onDisappear {
            if !library.openingReader { library.cancel() }
            passwords = [:]; library.result = nil; library.answer = nil
            Task { await library.store.clearSearchCache() }
        }
        .sheet(item: $editing) { document in metadataSheet(document) }
        .sheet(isPresented: $showSync) { syncSheet }
        .sheet(isPresented: $showSettingsExchange) {
            SettingsExchangeView(store: library.store).environmentObject(model).environmentObject(preferences)
        }
        .accessibilityIdentifier("pdf.library")
    }
    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Biblioteca", systemImage: "books.vertical.fill").font(.largeTitle.bold())
                Spacer()
                Button(action: importDocuments) { Label("Importar PDFs", systemImage: "plus") }.buttonStyle(.borderedProminent).disabled(unavailable)
                Button { showSync = true } label: { Label("Sincronizar…", systemImage: "arrow.triangle.2.circlepath") }.disabled(unavailable)
                Button { showSettingsExchange = true } label: { Image(systemName: "slider.horizontal.3") }.help("Trocar ajustes, perfis e marcadores").disabled(unavailable)
                Button(action: library.load) { Image(systemName: "arrow.clockwise") }.help("Recarregar catálogo").disabled(unavailable)
            }
            Text("Cópias locais, coleções e versões verificadas. Seus arquivos originais permanecem intactos.")
                .foregroundStyle(.secondary)
            HStack(spacing: 16) {
                Label("\(documents.count) documentos", systemImage: "doc.on.doc")
                Label("\(documents.reduce(0) { $0 + $1.revisions.count }) versões", systemImage: "clock.arrow.circlepath")
                Text("\(selected.count) selecionados")
            }.font(.caption).foregroundStyle(.secondary)
        }.padding(22).background(.regularMaterial)
    }
    private var filters: some View {
        VStack(spacing: 10) {
            TextField("Buscar título, coleção ou etiquetas", text: $filter.text).textFieldStyle(.roundedBorder)
            Picker("Filtro inteligente", selection: $filter.mode) {
                ForEach(LibrarySmartFilter.Mode.allCases) { Text($0.title).tag($0) }
            }
            Picker("Coleção", selection: $filter.collection) {
                Text("Todas as coleções").tag("")
                ForEach(Array(Set(documents.map { $0.current.labels.collection }.filter { !$0.isEmpty })).sorted(), id: \.self) { Text($0).tag($0) }
            }
            Picker("Etiqueta", selection: $filter.tag) {
                Text("Todas as etiquetas").tag("")
                ForEach(Array(Set(documents.flatMap { $0.current.labels.tags })).sorted(), id: \.self) { Text($0).tag($0) }
            }
            if !displayed.isEmpty {
                HStack { Button("Selecionar exibidos") { selected = Set(displayed.map(\.id)) }; Spacer(); Button("Limpar") { selected = [] } }.font(.caption)
            }
        }
    }
    private var documentList: some View {
        List(selection: $selected) {
            ForEach(displayed) { document in
                VStack(alignment: .leading, spacing: 6) {
                    Label(document.current.labels.title, systemImage: document.current.encrypted ? "lock.doc" : "doc.richtext").font(.headline)
                    Text(document.current.labels.collection.isEmpty ? "Sem coleção" : document.current.labels.collection).font(.caption).foregroundStyle(.secondary)
                    if !document.current.labels.tags.isEmpty { Text(document.current.labels.tags.joined(separator: " · ")).font(.caption).foregroundStyle(.tint) }
                    HStack {
                        Text(document.current.pages > 0 ? "\(document.current.pages) páginas" : "Protegido")
                        Spacer()
                        if document.heads.count > 1 { Label("\(document.heads.count) ramificações", systemImage: "exclamationmark.triangle") }
                        else { Text("\(document.revisions.count) versões") }
                    }.font(.caption2).foregroundStyle(.secondary)
                }.padding(.vertical, 5).tag(document.id)
            }
        }.listStyle(.inset).overlay {
            if displayed.isEmpty { ContentUnavailableView("Nenhum documento", systemImage: "tray", description: Text(documents.isEmpty ? "Importe PDFs para começar." : "Ajuste os filtros da coleção.")) }
        }
    }
    private func detail(_ document: LibraryDocument) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(document.current.labels.title).font(.title2.bold()).textSelection(.enabled)
            Text("SHA-256 · " + document.current.fingerprint).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
            ViewThatFits(in: .horizontal) {
                HStack { documentActions(document) }
                VStack(alignment: .leading) { documentActions(document) }
            }.disabled(unavailable)
            if document.heads.count > 1 {
                Label("Há versões independentes. Elas foram preservadas; compare antes de restaurar a desejada. As cópias de conflito também ficam na pasta de sincronização.", systemImage: "arrow.triangle.branch")
                    .font(.callout).foregroundStyle(.orange)
            }
            Divider()
            Label("Histórico de versões", systemImage: "clock.arrow.circlepath").font(.headline)
            ForEach(document.revisions.sorted { $0.created > $1.created }) { revision in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(revision.created.formatted(date: .abbreviated, time: .shortened)).font(.subheadline.weight(.medium))
                        Spacer()
                        if revision.id == document.preferred { Text("Atual").font(.caption).foregroundStyle(.tint) }
                        else if document.heads.contains(where: { $0.id == revision.id }) { Text("Ramificação").font(.caption).foregroundStyle(.orange) }
                    }
                    Text(revision.note).font(.caption).foregroundStyle(.secondary)
                    Text(String(revision.fingerprint.prefix(16)) + "… · " + ByteCountFormatter.string(fromByteCount: Int64(revision.byteCount), countStyle: .file)).font(.caption.monospaced()).foregroundStyle(.secondary)
                    HStack {
                        Button("Abrir") { open(document, revision: revision) }
                        Button("Exportar cópia") { export(document, revision: revision) }
                        if revision.id != document.preferred {
                            Button("Comparar com atual") { compare(document, revision: revision) }
                            Button("Restaurar como nova versão") {
                                library.run("Restaurando versão…") { _ in
                                    library.catalog = try await library.store.restore(document: document.id, revision: revision.id)
                                    return "Nova versão criada. Todas as versões anteriores continuam no histórico."
                                }
                            }
                        }
                    }.controlSize(.small).disabled(unavailable)
                    if document.heads.count > 1 && document.heads.contains(where: { $0.id == revision.id }) {
                        Button("Usar esta cópia e reunir ramificações") {
                            library.run("Registrando resolução explícita…") { _ in
                                library.catalog = try await library.store.resolve(document: document.id, revision: revision.id)
                                return "Ramificações reunidas. Todas as cópias anteriores permanecem no histórico."
                            }
                        }.controlSize(.small).disabled(unavailable)
                    }
                }.padding(12).background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }
    @ViewBuilder private func documentActions(_ document: LibraryDocument) -> some View {
        Button { open(document) } label: { Label("Ler PDF", systemImage: "book") }.buttonStyle(.borderedProminent)
        Button("Adicionar versão…") { addVersion(document) }
        Button("Organizar…") {
            title = document.current.labels.title; collection = document.current.labels.collection
            tags = document.current.labels.tags.joined(separator: ", "); editing = document
        }
    }
    private var retrievalPanel: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Consultar documentos", systemImage: "text.magnifyingglass").font(.title3.bold())
            Text("Busca local em português, com trechos, página e impressão digital da versão. O texto extraído e as senhas permanecem apenas na memória durante a consulta.")
                .font(.callout).foregroundStyle(.secondary)
            TextField("Ex.: prazo de pagamento e reajuste do contrato", text: $question).textFieldStyle(.roundedBorder).onSubmit(search)
            Toggle("Consultar somente documentos selecionados", isOn: $searchSelectedOnly)
            Toggle("Usar NaturalLanguage instalado para ordenar os trechos", isOn: $useEmbeddings)
            if documents.contains(where: { $0.current.encrypted && (!searchSelectedOnly || selected.contains($0.id)) }) {
                DisclosureGroup("Incluir fontes protegidas nesta consulta") {
                    ForEach(documents.filter { $0.current.encrypted && (!searchSelectedOnly || selected.contains($0.id)) }) { document in
                        SecureField(document.current.labels.title, text: Binding(get: { passwords[document.id] ?? "" }, set: { passwords[document.id] = $0 }))
                            .textFieldStyle(.roundedBorder)
                    }
                    Text("Senhas individuais, somente em memória. Sem a senha, essa fonte será listada como não consultada.").font(.caption).foregroundStyle(.secondary)
                }
            }
            Button(action: search) { Label("Buscar nas fontes", systemImage: "magnifyingglass") }
                .buttonStyle(.borderedProminent).disabled(unavailable || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || (searchSelectedOnly && selected.isEmpty))
            if let result = library.result {
                Text("Consulta: " + result.question).font(.caption.weight(.medium))
                Text(result.response).font(.callout)
                Text(result.method).font(.caption).foregroundStyle(.secondary)
                if !result.sources.isEmpty {
                    Button("Responder em português com IA local") {
                        library.answer = nil
                        library.run("Elaborando resposta com as fontes desta consulta…") { _ in
                            library.answer = try await LibraryAnswering.respond(to: result)
                            return "Citações conferidas nos trechos fornecidos. Revise a interpretação nas fontes."
                        }
                    }.disabled(unavailable || LibraryAnswering.availabilityMessage != nil || result.question.count > 800)
                    if result.question.count > 800 { Text("Para a resposta com IA, use uma pergunta de até 800 caracteres.").font(.caption).foregroundStyle(.secondary) }
                    if let reason = LibraryAnswering.availabilityMessage { Text(reason).font(.caption).foregroundStyle(.secondary) }
                }
                if let answer = library.answer {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Resposta local", systemImage: "sparkles").font(.headline)
                        Text(answer.text).textSelection(.enabled)
                        ForEach(answer.citations) { citation in
                            VStack(alignment: .leading, spacing: 5) {
                                Button(citation.source.title + " · página \(citation.source.page)") { openCitation(citation.source) }
                                Text("“" + citation.quote + "”").font(.callout).textSelection(.enabled)
                                Text(citation.source.fingerprint).font(.caption2.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                            }
                        }
                        Text("A conferência valida a origem literal das citações, não garante a interpretação do modelo.").font(.caption).foregroundStyle(.secondary)
                    }.padding(16).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                }
                ForEach(result.sources) { source in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(source.title).font(.headline)
                            Spacer()
                            Button("Página \(source.page)") { openCitation(source) }
                        }
                        Text(source.text).textSelection(.enabled)
                        Text("Fonte SHA-256: " + source.fingerprint).font(.caption2.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                    }.padding(14).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                }
                ForEach(Array(result.skipped.enumerated()), id: \.offset) { _, notice in Text(notice).font(.caption).foregroundStyle(.secondary) }
                Button("Limpar trechos da memória") {
                    library.result = nil; library.answer = nil; question = ""; passwords = [:]
                    Task { await library.store.clearSearchCache() }
                }.controlSize(.small).disabled(library.busy)
            }
        }
    }
    private func metadataSheet(_ document: LibraryDocument) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Organizar documento").font(.title2.bold())
            TextField("Título", text: $title)
            TextField("Coleção", text: $collection)
            TextField("Etiquetas separadas por vírgulas", text: $tags)
            Text("A mudança fica registrada como uma versão dos metadados. O PDF permanece idêntico.").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Cancelar") { editing = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                Button("Salvar") {
                    let title = title, collection = collection, labels = tags.split(separator: ",").map(String.init)
                    editing = nil
                    library.run("Atualizando coleção…") { _ in
                        library.catalog = try await library.store.updateLabels(document: document.id, title: title, collection: collection, tags: labels)
                        return "Título, coleção e etiquetas atualizados."
                    }
                }.buttonStyle(.borderedProminent)
            }
        }.textFieldStyle(.roundedBorder).padding(26).frame(width: 490)
    }
    private var syncSheet: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("Levar sua biblioteca a outro Mac", systemImage: "externaldrive.badge.icloud").font(.title2.bold())
            Text("Escolha uma pasta local, unidade externa ou pasta de um provedor de sincronização configurado por você. No outro Mac, escolha a mesma pasta e sincronize.")
            Text("Todos os PDFs e os metadados da biblioteca serão copiados para ‘PDF Library Exchange’. Um provedor poderá enviar essa pasta à nuvem conforme suas configurações. As senhas e os índices de texto não são exportados; PDFs protegidos permanecem criptografados.").font(.callout)
            Text("Snapshots de ajustes, perfis ou marcadores preparados por você também são transferidos. No outro Mac, revise e aplique cada snapshot em ‘Trocar ajustes’; receber um arquivo nunca altera automaticamente suas preferências.").font(.callout)
            Text("A sincronização ocorre somente ao acionar este comando. Versões divergentes são mantidas no histórico e em cópias separadas na pasta ‘conflicts’. Não há exclusão automática nem substituição silenciosa. Aguarde o provedor concluir a transferência antes de abrir no outro Mac.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Cancelar") { showSync = false }.keyboardShortcut(.cancelAction)
                Spacer()
                Button("Escolher pasta e sincronizar…") { chooseSync() }.buttonStyle(.borderedProminent)
            }
        }.padding(28).frame(width: 600)
    }
    private func importDocuments() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]; panel.allowsMultipleSelection = true
        guard panel.runModal() == .OK else { return }
        let urls = panel.urls
        library.run("Importando PDFs e verificando duplicados…") { _ in
            let report = try await library.store.importFiles(urls, collection: filter.collection)
            library.catalog = report.catalog
            return "\(report.imported) importados · \(report.duplicate) cópias idênticas já presentes."
        }
    }
    private func addVersion(_ document: LibraryDocument) {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]; panel.message = "Escolha o PDF salvo que será registrado como nova versão."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        library.run("Registrando versão…") { _ in
            library.catalog = try await library.store.addVersion(document: document.id, source: url)
            return "Versão adicionada. O arquivo escolhido e as versões anteriores foram preservados."
        }
    }
    private func chooseSync() {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        showSync = false
        library.run("Verificando manifestos e sincronizando cópias…") { _ in
            let report = try await library.store.synchronize(with: url); library.catalog = report.catalog
            return "\(report.received) versões e \(report.configurationsReceived) ajustes recebidos · \(report.conflicts) documentos com ramificações preservadas."
        }
    }
    private func export(_ document: LibraryDocument, revision: LibraryRevision) {
        guard let target = NativeOutput.destination(model: model, toolName: "Versão", originalName: document.current.labels.title + ".pdf") else { return }
        library.run("Verificando e exportando cópia…") { _ in
            try await library.store.export(document: document.id, revision: revision.id, to: target)
            model.lastOutput = target; return "Cópia verificada exportada: " + target.lastPathComponent
        }
    }
    private func open(_ document: LibraryDocument, revision: LibraryRevision? = nil) {
        guard !unavailable else { return }
        library.run("Verificando versão…", opensReader: true) { _ in
            let url = try await library.store.verifiedURL(document: document.id, revision: revision?.id)
            model.open(url: url, page: nil, displayTitle: revisionTitle(document, revision: revision ?? document.current)); await model.waitForPendingOpen()
            guard model.needsPassword || model.activeSession?.sourceURL == url else { throw SemanticEvidence.failure(model.message) }
            model.section = "Leitor"
            return model.needsPassword ? "Digite a senha no leitor para abrir a versão protegida." : "Versão aberta no leitor. Salve as alterações em uma nova cópia."
        }
    }
    private func compare(_ document: LibraryDocument, revision: LibraryRevision) {
        guard revision.fingerprint != document.current.fingerprint else { library.message = "As duas versões contêm exatamente os mesmos bytes PDF; somente os metadados mudaram."; return }
        library.run("Abrindo versões para comparação…", opensReader: true) { _ in
            let old = try await library.store.verifiedURL(document: document.id, revision: revision.id)
            let current = try await library.store.verifiedURL(document: document.id)
            model.open(url: old, page: nil, displayTitle: revisionTitle(document, revision: revision)); await model.waitForPendingOpen()
            guard !model.needsPassword, let reference = model.activeSession, reference.sourceURL == old else { model.section = "Leitor"; return "Desbloqueie a primeira versão no leitor e repita a comparação." }
            model.open(url: current, page: nil, displayTitle: revisionTitle(document, revision: document.current)); await model.waitForPendingOpen()
            guard !model.needsPassword, model.activeSession?.sourceURL == current else { model.section = "Leitor"; return "Desbloqueie a versão atual no leitor e repita a comparação." }
            model.comparisonSessionID = reference.id
            model.section = "Leitor"
            return "Versão atual e histórica abertas lado a lado."
        }
    }
    private func search() {
        guard !unavailable else { return }
        let ids = searchSelectedOnly ? selected : Set(documents.map(\.id)), query = question, semantic = useEmbeddings
        let secrets = passwords.filter { ids.contains($0.key) && !$0.value.isEmpty }
        passwords = [:]; library.result = nil; library.answer = nil
        library.run("Consultando texto das fontes selecionadas…") { cancellation in
            let source = try await library.store.excerpts(documentIDs: ids, passwords: secrets, cancellation: cancellation)
            library.result = try await library.retrieval.search(question: query, source: source, useEmbeddings: semantic)
            return "Consulta concluída. Nenhum texto foi enviado a um serviço remoto."
        }
    }
    private func openCitation(_ source: LibraryExcerpt) {
        guard !unavailable else { return }
        library.run("Verificando fonte citada…", opensReader: true) { _ in
            let url = try await library.store.verifiedURL(document: source.documentID, revision: source.revisionID)
            model.open(url: url, page: source.page, displayTitle: source.title + " · fonte " + String(source.fingerprint.prefix(8)))
            await model.waitForPendingOpen()
            guard model.needsPassword || (model.activeSession?.sourceURL == url && model.currentPage == source.page) else { throw SemanticEvidence.failure(model.message) }
            model.section = "Leitor"
            return model.needsPassword ? "Digite a senha no leitor; a página \(source.page) será aberta após a autenticação." : "Fonte original da citação aberta na página \(source.page)."
        }
    }
    private func revisionTitle(_ document: LibraryDocument, revision: LibraryRevision) -> String {
        revision.labels.title + " · versão " + revision.created.formatted(date: .numeric, time: .shortened)
    }
}
