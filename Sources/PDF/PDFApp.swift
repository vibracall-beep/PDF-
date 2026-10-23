import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers

struct Tool: Identifiable, Hashable {
    let id: String
    let name: String
    let icon: String
    let detail: String
    let category: String
    var operation: String {
        switch id {
        case "word-pdf", "powerpoint-pdf", "excel-pdf": return "office"
        case "odt-pdf": return "odt"
        case "txt-pdf": return "txt"
        case "rtf-pdf": return "rtf"
        case "epub-pdf": return "epub"
        case "csv-pdf": return "csv"
        default: return id
        }
    }
}

let tools: [Tool] = [
    .init(id:"merge", name:"Juntar PDF", icon:"rectangle.stack", detail:"Combine documentos na ordem que escolher.", category:"Organizar"),
    .init(id:"split", name:"Dividir PDF", icon:"square.split.2x2", detail:"Separe páginas e intervalos em novos arquivos.", category:"Organizar"),
    .init(id:"compress", name:"Comprimir PDF", icon:"arrow.down.right.and.arrow.up.left", detail:"Otimize o arquivo com controle de qualidade.", category:"Organizar"),
    .init(id:"word", name:"PDF para Word", icon:"doc.text", detail:"Extraia conteúdo para um documento editável.", category:"Converter"),
    .init(id:"powerpoint", name:"PDF para PowerPoint", icon:"rectangle.on.rectangle", detail:"Exporte slides editáveis ou páginas como imagens.", category:"Converter"),
    .init(id:"excel", name:"PDF para Excel", icon:"tablecells", detail:"Extraia tabelas e organize os dados por página.", category:"Converter"),
    .init(id:"word-pdf", name:"Word para PDF", icon:"doc.badge.arrow.up", detail:"Converta documentos Word com LibreOffice.", category:"Converter"),
    .init(id:"powerpoint-pdf", name:"PowerPoint para PDF", icon:"rectangle.stack.badge.plus", detail:"Transforme apresentações em documentos PDF.", category:"Converter"),
    .init(id:"excel-pdf", name:"Excel para PDF", icon:"tablecells.badge.ellipsis", detail:"Converta planilhas com LibreOffice.", category:"Converter"),
    .init(id:"edit", name:"Editar PDF", icon:"pencil.and.outline", detail:"Adicione texto, imagens e formas ou substitua texto.", category:"Editar"),
    .init(id:"jpg", name:"PDF para JPG", icon:"photo", detail:"Exporte páginas como imagens na resolução desejada.", category:"Converter"),
    .init(id:"images", name:"JPG para PDF", icon:"photo.on.rectangle", detail:"Combine imagens em um documento.", category:"Converter"),
    .init(id:"signature", name:"Assinar PDF", icon:"signature", detail:"Posicione sua assinatura visual no documento.", category:"Editar"),
    .init(id:"watermark", name:"Marca d’água", icon:"drop", detail:"Insira texto ou imagem com transparência.", category:"Editar"),
    .init(id:"rotate", name:"Rodar PDF", icon:"rotate.right", detail:"Ajuste a orientação das páginas selecionadas.", category:"Organizar"),
    .init(id:"html", name:"HTML para PDF", icon:"globe", detail:"Converta páginas da web ou arquivos HTML.", category:"Converter"),
    .init(id:"unlock", name:"Desbloquear PDF", icon:"lock.open", detail:"Remova a proteção usando a senha conhecida.", category:"Proteger"),
    .init(id:"protect", name:"Proteger PDF", icon:"lock.shield", detail:"Proteja seu documento com criptografia AES-256.", category:"Proteger"),
    .init(id:"organize", name:"Organizar PDF", icon:"square.grid.2x2", detail:"Reordene, duplique ou remova páginas.", category:"Organizar"),
    .init(id:"pdfa", name:"PDF para PDF/A", icon:"archivebox", detail:"Prepare uma cópia para arquivamento.", category:"Converter"),
    .init(id:"repair", name:"Reparar PDF", icon:"wrench", detail:"Tente recuperar documentos parcialmente danificados.", category:"Organizar"),
    .init(id:"numbers", name:"Números de página", icon:"number", detail:"Escolha posição, tamanho e numeração inicial.", category:"Editar"),
    .init(id:"scan", name:"Digitalizar em PDF", icon:"scanner", detail:"Use um scanner conectado ou importe imagens.", category:"Capturar"),
    .init(id:"ocr", name:"OCR PDF", icon:"text.viewfinder", detail:"Reconheça texto e crie páginas pesquisáveis.", category:"Capturar"),
    .init(id:"compare", name:"Comparar PDF", icon:"rectangle.split.2x1", detail:"Compare diferenças textuais ou visuais.", category:"Organizar"),
    .init(id:"redact", name:"Ocultar PDF", icon:"eraser", detail:"Remova permanentemente ocorrências de texto.", category:"Proteger"),
    .init(id:"crop", name:"Recortar PDF", icon:"crop", detail:"Ajuste a área visível das páginas.", category:"Editar"),
    .init(id:"forms", name:"Formulários PDF", icon:"list.bullet.rectangle", detail:"Crie campos, preencha ou inspecione formulários.", category:"Editar"),
    .init(id:"summary", name:"Resumir com IA", icon:"sparkles", detail:"Explore o conteúdo com inteligência local.", category:"Inteligência"),
    .init(id:"translate", name:"Traduzir PDF", icon:"character.bubble", detail:"Traduza o texto com o modelo disponível no Mac.", category:"Inteligência"),
    .init(id:"markdown", name:"PDF para Markdown", icon:"text.alignleft", detail:"Exporte conteúdo para notas e documentos Markdown.", category:"Converter"),
    .init(id:"workflow", name:"Criar fluxo de trabalho", icon:"arrow.triangle.branch", detail:"Combine etapas, salve e reutilize suas rotinas.", category:"Automatizar"),
    .init(id:"png", name:"PDF para PNG", icon:"photo.stack", detail:"Exporte páginas ou imagens incorporadas no formato PNG.", category:"Converter"),
    .init(id:"odt-pdf", name:"ODT para PDF", icon:"doc.text", detail:"Converta documentos OpenDocument com LibreOffice.", category:"Converter"),
    .init(id:"txt-pdf", name:"TXT para PDF", icon:"text.page", detail:"Transforme texto em páginas com fonte e margens ajustáveis.", category:"Converter"),
    .init(id:"rtf-pdf", name:"RTF para PDF", icon:"doc.richtext", detail:"Converta texto formatado em um documento PDF.", category:"Converter"),
    .init(id:"epub-pdf", name:"EPUB para PDF", icon:"books.vertical", detail:"Organize o conteúdo do livro em páginas PDF.", category:"Converter"),
    .init(id:"csv-pdf", name:"CSV para PDF", icon:"tablecells", detail:"Escolha separador, codificação e orientação da tabela.", category:"Converter"),
    .init(id:"pages-pdf", name:"Pages para PDF", icon:"doc.badge.gearshape", detail:"Exporte usando o aplicativo Pages instalado no Mac.", category:"Converter"),
    .init(id:"flatten", name:"Achatar PDF", icon:"square.3.layers.3d.down.right", detail:"Incorpore anotações e campos preenchidos ao conteúdo das páginas.", category:"Editar"),
    .init(id:"delete-pages", name:"Excluir páginas", icon:"doc.badge.minus", detail:"Remova páginas selecionadas e salve uma nova cópia.", category:"Organizar"),
    .init(id:"extract-pages", name:"Extrair páginas", icon:"doc.on.doc", detail:"Crie um PDF com as páginas e intervalos que escolher.", category:"Organizar"),
    .init(id:"converter", name:"Conversor de PDF", icon:"arrow.left.arrow.right", detail:"Encontre os formatos de entrada e saída disponíveis.", category:"Converter"),
    .init(id:"share", name:"Compartilhar PDF", icon:"square.and.arrow.up", detail:"Escolha um arquivo e compartilhe pelos serviços do macOS.", category:"Compartilhar"),
    .init(id:"annotate", name:"Anotar PDF", icon:"pencil.tip.crop.circle", detail:"Abra o leitor para realçar, desenhar e adicionar notas.", category:"Editar"),
    .init(id:"fill-forms", name:"Preencher PDF", icon:"checklist", detail:"Preencha campos existentes e gere uma nova cópia.", category:"Editar"),
    .init(id:"chat", name:"Conversar com PDF", icon:"bubble.left.and.bubble.right", detail:"Faça perguntas sobre o documento com IA local.", category:"Inteligência"),
    .init(id:"quiz", name:"Gerar questionário", icon:"questionmark.bubble", detail:"Crie perguntas de estudo com base no documento.", category:"Inteligência"),
    .init(id:"sign-service", name:"Sign.com", icon:"signature", detail:"Abra o serviço externo de assinaturas no navegador.", category:"Compartilhar"),
    .init(id:"digital-sign", name:"Assinatura digital certificada", icon:"checkmark.seal", detail:"Assine com seu certificado digital e verifique a integridade.", category:"Proteger"),
    .init(id:"verify-signatures", name:"Verificar assinaturas", icon:"checkmark.shield", detail:"Examine certificados, integridade e evidências de validação.", category:"Proteger"),
    .init(id:"validate-pdfa", name:"Validar PDF/A", icon:"archivebox.fill", detail:"Verifique conformidade de arquivamento com validador independente.", category:"Proteger"),
    .init(id:"validate-pdfua", name:"Auditar PDF/UA", icon:"accessibility", detail:"Analise requisitos de acessibilidade e gere um relatório.", category:"Proteger"),
    .init(id:"benchmark", name:"Desempenho do Mac", icon:"gauge.with.dots.needle.67percent", detail:"Meça leitura, busca e processamento no hardware deste Mac.", category:"Automatizar")
]

@main struct PDFApp: App {
    @StateObject private var model = Workspace()
    @StateObject private var appearancePreferences = AppearancePreferences.shared
    @NSApplicationDelegateAdaptor(PDFApplicationDelegate.self) private var applicationDelegate
    init() {
        if let index = CommandLine.arguments.firstIndex(of:"--render-preview"), CommandLine.arguments.indices.contains(index+1) {
            do { try MacPreview.render(to:URL(fileURLWithPath:CommandLine.arguments[index+1])); exit(0) }
            catch { FileHandle.standardError.write(Data("PDF preview failed: \(error)\n".utf8)); exit(1) }
        }
        if let index = CommandLine.arguments.firstIndex(of:"--benchmark") {
            do {
                let args = CommandLine.arguments
                guard args.indices.contains(index+1),!args[index+1].hasPrefix("--") else { throw NSError(domain:"PDF.Benchmark",code:1,userInfo:[NSLocalizedDescriptionKey:"Informe o caminho JSON após --benchmark."]) }
                var input:URL?
                if let inputIndex = args.firstIndex(of:"--benchmark-input") {
                    guard args.indices.contains(inputIndex+1),!args[inputIndex+1].hasPrefix("--") else { throw NSError(domain:"PDF.Benchmark",code:1,userInfo:[NSLocalizedDescriptionKey:"Informe um PDF após --benchmark-input."]) }
                    input = URL(fileURLWithPath:args[inputIndex+1])
                }
                var pages = 100
                if let pagesIndex = args.firstIndex(of:"--benchmark-pages") {
                    guard args.indices.contains(pagesIndex+1),let parsed = Int(args[pagesIndex+1]),parsed > 0 else { throw NSError(domain:"PDF.Benchmark",code:1,userInfo:[NSLocalizedDescriptionKey:"Use um número positivo em --benchmark-pages."]) }
                    pages = parsed
                }
                try MacBenchmark.run(input:input,output:URL(fileURLWithPath:args[index+1]),pages:pages); exit(0)
            } catch { FileHandle.standardError.write(Data("PDF benchmark failed: \(error)\n".utf8)); exit(1) }
        }
        if CommandLine.arguments.contains("--smoke-test") {
            do { try MacSmokeTests.run(); print("PDF native smoke tests passed"); exit(0) }
            catch { fputs("PDF native smoke tests failed: \(error)\n", stderr); exit(1) }
        }
    }
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(model).environmentObject(appearancePreferences).frame(minWidth:1050, minHeight:720)
                .onOpenURL { model.open(url:$0) }
                .background(WorkspaceWindowGuard(model:model).frame(width:0,height:0))
                .onAppear { applicationDelegate.model = model }
        }
        .commands { PDFMenuCommands(model:model) }
        Settings { PreferencesView().environmentObject(model).environmentObject(appearancePreferences) }
    }

}

struct ContentView: View {
    @EnvironmentObject var model:Workspace
    @EnvironmentObject var preferences:AppearancePreferences
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @State private var query = ""
    @State private var category = "Todas"
    @State private var selected:Tool?
    @State private var intelligenceMode = "summary"
    @State private var verificationMode = "verify"
    @State private var showRecovery = false
    @FocusState private var toolSearchFocused:Bool
    @State private var showCustomization = false
    @AppStorage("readerShowAnnotations") private var readerShowAnnotations = true
    private let initialReaderInspector:Bool
    init(initialReaderInspector:Bool = false) { self.initialReaderInspector = initialReaderInspector }
    var tint:Color { preferences.accent }
    var hasToolFilters:Bool { !query.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || category != "Todas" }
    var hiddenFavoriteCount:Int { tools.filter { isFavorite($0.id) && (preferences.state.hiddenTools.contains($0.id) || preferences.state.hiddenCategories.contains($0.category)) }.count }
    var orderedTools:[Tool] {
        let search = query.trimmingCharacters(in:.whitespacesAndNewlines)
        return preferences.orderedTools().filter {
            !preferences.state.hiddenTools.contains($0.id) && !preferences.state.hiddenCategories.contains($0.category) &&
            (search.isEmpty || preferences.title(for:$0).localizedStandardContains(search) || $0.name.localizedStandardContains(search)) &&
            (category == "Todas" || $0.category == category) && (model.section != "Favoritos" || isFavorite($0.id))
        }
    }
    var sidebarWidth:Double { preferences.state.sidebarStyle == "icons" ? 84 : preferences.state.sidebarWidth }
    var body:some View {
        NavigationSplitView {
            sidebar.navigationSplitViewColumnWidth(min:sidebarWidth,ideal:sidebarWidth,max:sidebarWidth)
        } detail: {
            VStack(spacing:0) {
                destination.id(model.section).transition(!preferences.state.animationsEnabled || reduceMotion ? .identity : .opacity)
                statusBar
            }.navigationTitle(model.section == "Leitor" ? model.url?.lastPathComponent ?? "Leitor" : preferences.state.sidebar.first(where:{$0.id == model.section})?.label ?? model.section)
                .animation(preferences.animation(reduceMotion:reduceMotion),value:model.section)
        }
        .tint(tint).preferredColorScheme(preferences.preferredScheme)
        .sheet(item:$selected) { ToolConfigurationView(tool:$0).environmentObject(model).environmentObject(preferences) }
        .sheet(isPresented:$showCustomization) { CustomizationView().environmentObject(model).environmentObject(preferences) }
        .sheet(isPresented:$showRecovery) { RecoveryDocumentsView().environmentObject(model).environmentObject(preferences) }
        .focusedSceneValue(\.catalogSearchAction,{ model.section = "Início"; DispatchQueue.main.async { toolSearchFocused = true } })
        .focusedSceneValue(\.recoveryAction,{ showRecovery = true })
        .onAppear { model.refreshRecovery() }
        .toolbar { ToolbarItem(placement:.primaryAction) { Button { showCustomization = true } label:{ Label("Personalizar",systemImage:"slider.horizontal.3") }.help("Personalizar aparência, menus e leitura").accessibilityIdentifier("pdf.customize.toolbar") } }
        .alert("Abrir documento protegido",isPresented:$model.needsPassword) {
            SecureField("Senha",text:$model.documentPassword)
            Button("Abrir") { model.unlockPendingDocument() }
            Button("Cancelar",role:.cancel) { model.cancelPendingUnlock() }
        } message: { Text("Digite a senha para abrir este PDF.") }
    }
    var sidebar:some View {
        VStack(alignment:preferences.state.sidebarStyle == "icons" ? .center : .leading,spacing:14) {
            Button { navigate(to:"Início") } label: {
                HStack(spacing:10) {
                    Image(systemName:"doc.richtext").font(.system(size:28,weight:.semibold))
                    if preferences.state.sidebarStyle != "icons" { Text("PDF").font(.system(size:30,weight:.bold,design:.rounded)) }
                }
            }.buttonStyle(.plain).accessibilityLabel("PDF — Início").padding(.top,18)
            if preferences.state.sidebarStyle != "icons" { Text("SEU ESPAÇO DE DOCUMENTOS").font(.system(size:10)).foregroundStyle(.secondary) }
            ScrollView {
                VStack(spacing:preferences.state.spacing) {
                    ForEach(preferences.state.sidebar.filter(\.visible)) { item in
                        Button { navigate(to:item.id) } label: {
                            HStack(spacing:10) {
                                if preferences.state.sidebarStyle != "labels" { Image(systemName:item.icon).frame(width:20) }
                                if preferences.state.sidebarStyle != "icons" { Text(item.label).font(.system(size:preferences.state.fontSize)).frame(maxWidth:.infinity,alignment:.leading) }
                            }.padding(preferences.state.density == "compact" ? 9 : 12)
                                .frame(maxWidth:.infinity)
                                .background(model.section == item.id ? tint.opacity(0.15) : .clear,in:RoundedRectangle(cornerRadius:12))
                        }.buttonStyle(.plain).accessibilityLabel(item.label).help(item.label).accessibilityIdentifier("pdf.sidebar." + item.id)
                            .accessibilityAddTraits(model.section == item.id ? .isSelected : [])
                    }
                }.padding(.vertical,6)
            }
            if preferences.state.sidebarStyle != "icons" { Label("Seus arquivos no seu Mac",systemImage:"lock.shield").font(.caption).foregroundStyle(.secondary) }
            Button { showCustomization = true } label: {
                if preferences.state.sidebarStyle == "icons" { Image(systemName:"slider.horizontal.3") }
                else { Label("Personalizar",systemImage:"slider.horizontal.3") }
            }.accessibilityLabel("Personalizar o PDF").help("Personalizar o PDF")
        }.padding(preferences.state.sidebarStyle == "icons" ? 12 : 20)
            .background(reduceTransparency || preferences.state.glassStyle == "opaque" ? AnyShapeStyle(Color(nsColor:.controlBackgroundColor)) : AnyShapeStyle(.ultraThinMaterial))
            .animation(preferences.animation(reduceMotion:reduceMotion),value:preferences.state.sidebar)
    }
    @ViewBuilder var destination:some View {
        switch model.section {
        case "Leitor": ReaderWorkspaceView(initialInspectorPresented:initialReaderInspector)
        case "Inteligência": IntelligenceView(initialMode:intelligenceMode).id(intelligenceMode)
        case "Digitalizar": NativeFeaturesView()
        case "Fluxos": WorkflowView()
        case "Compartilhar": SharePDFView()
        case "Pages para PDF": PagesConversionView()
        case "Sign.com": ExternalSigningView()
        case "Desempenho": BenchmarkView()
        case "Verificação": VerificationView(initialMode:verificationMode).id(verificationMode)
        default: home
        }
    }
    var home:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:preferences.state.spacing+10) {
                HStack {
                    Text(model.section == "Favoritos" ? "Favoritos" : "Seu espaço de trabalho").font(.title3.weight(.semibold))
                    Spacer()
                    Picker("Visualização",selection:$preferences.state.layout) {
                        Label("Grade",systemImage:"square.grid.2x2").tag("grid")
                        Label("Lista",systemImage:"list.bullet").tag("list")
                    }.pickerStyle(.segmented).labelsHidden().accessibilityLabel("Visualização das ferramentas").frame(width:145).fixedSize(horizontal:true,vertical:false)
                    Button("Personalizar",systemImage:"slider.horizontal.3") { showCustomization = true }.buttonStyle(.bordered)
                }
                if preferences.state.showHero {
                    HStack {
                        VStack(alignment:.leading,spacing:10) {
                            Text("Clareza em cada página.").font(.system(size:32,weight:.semibold,design:.rounded))
                            Text("Leia, transforme e organize seus documentos.").foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Abrir documento",systemImage:"plus") { model.open() }.buttonStyle(.borderedProminent)
                    }.padding(24).pdfGlass()
                }
                if (!model.recoveryItems.isEmpty || !model.recoveryWarnings.isEmpty) && model.section != "Favoritos" {
                    HStack(spacing:12) {
                        Image(systemName:"clock.arrow.circlepath").accessibilityHidden(true)
                        Text(model.recoveryItems.isEmpty ? "Há avisos sobre as cópias de recuperação." : "Há \(model.recoveryItems.count) cópias locais de recuperação.").font(.callout)
                        Spacer()
                        Button("Revisar cópias…") { showRecovery = true }.accessibilityIdentifier("pdf.recovery.review")
                    }.padding(14).pdfGlass()
                }
                if preferences.state.showRecent && model.section != "Favoritos" && !model.recentURLs.isEmpty { recentDocuments }
                HStack {
                    TextField("Buscar ferramenta",text:$query).textFieldStyle(.roundedBorder).focused($toolSearchFocused).accessibilityIdentifier("pdf.catalog.search")
                    Picker("Categoria",selection:$category) { Text("Todas").tag("Todas"); ForEach(AppearanceState.categories.filter { !preferences.state.hiddenCategories.contains($0) },id:\.self) { Text($0).tag($0) } }.frame(width:220)
                }
                if model.section == "Favoritos" && hiddenFavoriteCount > 0 {
                    HStack(spacing:8) { Image(systemName:"eye.slash"); Text("\(hiddenFavoriteCount) favoritos estão ocultos nas preferências."); Button("Personalizar") { showCustomization = true } }.font(.caption).foregroundStyle(.secondary)
                }
                if orderedTools.isEmpty { emptyToolsState }
                HStack(alignment:.firstTextBaseline) {
                    Text(model.section == "Favoritos" ? "Suas ferramentas favoritas" : category == "Todas" ? "Todas as ferramentas" : category).font(.title3.weight(.semibold))
                    Spacer(); Text("\(orderedTools.count) \(hasToolFilters ? "resultados" : "ferramentas")").font(.caption).foregroundStyle(.secondary)
                }
                if preferences.state.groupByCategory && category == "Todas" {
                    ForEach(AppearanceState.categories,id:\.self) { group in
                        let items = orderedTools.filter { $0.category == group }
                        if !items.isEmpty { VStack(alignment:.leading,spacing:12) { Text(group).font(.headline).foregroundStyle(.secondary); catalogue(items) } }
                    }
                } else { catalogue(orderedTools) }
            }.padding(preferences.state.padding+10)
        }
        .background(homeBackground)
        .animation(preferences.animation(reduceMotion:reduceMotion),value:preferences.state.layout)
        .animation(preferences.animation(reduceMotion:reduceMotion),value:orderedTools.map(\.id))
        .onChange(of:preferences.state.hiddenCategories) { _,hidden in if hidden.contains(category) { category = "Todas" } }
    }
    @ViewBuilder var homeBackground:some View {
        if preferences.state.backgroundStyle == "plain" { Color(nsColor:.windowBackgroundColor) }
        else { LinearGradient(colors:[tint.opacity(0.1),Color(nsColor:.windowBackgroundColor),tint.opacity(0.06)],startPoint:.topLeading,endPoint:.bottomTrailing) }
    }
    var recentDocuments:some View {
        VStack(alignment:.leading,spacing:12) {
            HStack { Text("Continue de onde parou").font(.headline); Spacer(); Button("Limpar recentes") { model.clearRecent() }.font(.caption) }
            ScrollView(.horizontal,showsIndicators:false) {
                HStack(spacing:12) { ForEach(model.recentURLs.prefix(6),id:\.path) { url in Button { model.open(url:url) } label:{ Label(url.lastPathComponent,systemImage:"doc.text").lineLimit(1).padding(12).frame(maxWidth:220).pdfGlass() }.buttonStyle(.plain).help(url.path) } }
            }
        }
    }
    @ViewBuilder func catalogue(_ items:[Tool]) -> some View {
        if preferences.state.layout == "list" {
            LazyVStack(spacing:preferences.state.spacing) { ForEach(items) { tool in CustomizableToolCard(tool:tool,favorite:isFavorite(tool.id),row:true,open:{ activate(tool) },toggleFavorite:{ toggleFavorite(tool.id) }) } }
        } else {
            LazyVGrid(columns:[GridItem(.adaptive(minimum:preferences.state.cardWidth),spacing:preferences.state.spacing)],spacing:preferences.state.spacing) { ForEach(items) { tool in CustomizableToolCard(tool:tool,favorite:isFavorite(tool.id),open:{ activate(tool) },toggleFavorite:{ toggleFavorite(tool.id) }) } }
        }
    }
    @ViewBuilder var emptyToolsState:some View {
        if hasToolFilters {
            ContentUnavailableView { Label("Nenhum resultado para os filtros",systemImage:"magnifyingglass") } description:{ Text("A busca e a categoria não correspondem às ferramentas visíveis nesta seção.") } actions:{ Button("Limpar filtros") { clearToolFilters() } }
        } else if model.section == "Favoritos" && hiddenFavoriteCount == 0 {
            ContentUnavailableView("Você ainda não tem favoritos",systemImage:"star",description:Text("Use a estrela nos cartões do Início para adicionar ferramentas."))
        } else {
            ContentUnavailableView { Label("Nenhuma ferramenta visível",systemImage:"eye.slash") } description:{ Text("As ferramentas ou categorias desta seção estão ocultas. Ajuste a visibilidade em Personalizar.") } actions:{ Button("Personalizar") { showCustomization = true } }
        }
    }
    var statusBar:some View {
        HStack(spacing:12) {
            if model.busy {
                ProgressView().controlSize(.small)
                Text(model.message).font(.caption).lineLimit(2)
                Spacer()
                Button("Cancelar") { model.cancel() }
            } else {
                Text(model.message.isEmpty ? "Pronto" : model.message).font(.caption).textSelection(.enabled).lineLimit(3)
                Spacer()
                if let output = model.lastOutput {
                    Button("Abrir resultado") { model.openResult(output) }
                    Button("Mostrar no Finder") { NSWorkspace.shared.activateFileViewerSelecting([output]) }
                }
            }
        }.padding(12).background(reduceTransparency || preferences.state.glassStyle == "opaque" ? AnyShapeStyle(Color(nsColor:.controlBackgroundColor)) : AnyShapeStyle(.bar))
    }
    func clearToolFilters() { query = ""; category = "Todas" }
    func navigate(to section:String) { if section == "Início" || section == "Favoritos" { clearToolFilters() }; model.section = section }
    func activate(_ tool:Tool) {
        switch tool.id {
        case "summary","translate","chat","quiz": intelligenceMode = tool.id; model.section = "Inteligência"
        case "workflow": model.section = "Fluxos"
        case "scan": model.section = "Digitalizar"
        case "pages-pdf": model.section = "Pages para PDF"
        case "share": model.section = "Compartilhar"
        case "sign-service": model.section = "Sign.com"
        case "benchmark": model.section = "Desempenho"
        case "digital-sign": verificationMode = "sign"; model.section = "Verificação"
        case "verify-signatures": verificationMode = "verify"; model.section = "Verificação"
        case "validate-pdfa": verificationMode = "pdfa"; model.section = "Verificação"
        case "validate-pdfua": verificationMode = "pdfua"; model.section = "Verificação"
        case "converter": category = "Converter"; query = ""; model.section = "Início"
        case "annotate": readerShowAnnotations = true; if model.document == nil { model.open() } else { model.section = "Leitor" }
        default: selected = tool
        }
    }
    func isFavorite(_ id:String) -> Bool { preferences.state.favorites.contains(id) }
    func toggleFavorite(_ id:String) { if isFavorite(id) { preferences.state.favorites.removeAll { $0 == id } } else { preferences.state.favorites.append(id) } }
}

extension View {
    func pdfGlass() -> some View { modifier(AdaptiveSurface()) }
}
