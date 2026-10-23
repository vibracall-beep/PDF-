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
    .init(id:"sign-service", name:"Sign.com", icon:"signature", detail:"Abra o serviço externo de assinaturas no navegador.", category:"Compartilhar")
]

@main struct PDFApp: App {
    @StateObject private var model = Workspace()
    @NSApplicationDelegateAdaptor(PDFApplicationDelegate.self) private var applicationDelegate
    init() {
        if let index = CommandLine.arguments.firstIndex(of:"--render-preview"), CommandLine.arguments.indices.contains(index+1) {
            do { try MacPreview.render(to:URL(fileURLWithPath:CommandLine.arguments[index+1])); exit(0) }
            catch { FileHandle.standardError.write(Data("PDF preview failed: \(error)\n".utf8)); exit(1) }
        }
        if CommandLine.arguments.contains("--smoke-test") {
            do { try MacSmokeTests.run(); print("PDF native smoke tests passed"); exit(0) }
            catch { fputs("PDF native smoke tests failed: \(error)\n", stderr); exit(1) }
        }
    }
    var body: some Scene {
        WindowGroup {
            ContentView().environmentObject(model).frame(minWidth:1050, minHeight:720)
                .onOpenURL { model.open(url:$0) }
                .background(WorkspaceWindowGuard(model:model).frame(width:0,height:0))
                .onAppear { applicationDelegate.model = model }
        }
        .commands {
            CommandGroup(replacing:.newItem) {
                Button("Abrir PDF…") { model.open() }.keyboardShortcut("o")
                Menu("Abrir recente") {
                    ForEach(model.recentURLs, id:\.path) { url in Button(url.lastPathComponent) { model.open(url:url) } }
                    Divider()
                    Button("Limpar recentes") { model.clearRecent() }
                }
            }
            CommandGroup(replacing:.saveItem) {
                Button("Salvar cópia…") { model.save() }.keyboardShortcut("s", modifiers:[.command,.shift]).disabled(model.document == nil)
            }
            CommandGroup(replacing:.printItem) {
                Button("Imprimir…") { model.printDocument() }.keyboardShortcut("p").disabled(model.document == nil)
            }
            CommandMenu("Documento") {
                Button("Página anterior") { model.previousPage() }.keyboardShortcut(.leftArrow, modifiers:[.command])
                Button("Próxima página") { model.nextPage() }.keyboardShortcut(.rightArrow, modifiers:[.command])
                Divider()
                Button("Realçar seleção") { model.highlight() }.keyboardShortcut("h", modifiers:[.command,.shift])
                Button("Marcar página") { model.toggleBookmark() }.keyboardShortcut("d", modifiers:[.command,.shift])
                Button("Girar página atual") { model.rotatePage() }
            }
        }
        Settings { PreferencesView().environmentObject(model) }
    }
}

struct ContentView: View {
    @EnvironmentObject var model: Workspace
    @AppStorage("accent") private var accent = "Azul"
    @AppStorage("appearance") private var appearance = "Sistema"
    @AppStorage("compact") private var compact = false
    @AppStorage("favorites") private var favorites = "merge,ocr,word"
    @AppStorage("toolOrder") private var toolOrder = ""
    @AppStorage("hiddenTools") private var hiddenTools = ""
    @AppStorage("showRecent") private var showRecent = true
    @State private var query = ""
    @State private var category = "Todas"
    @State private var selected: Tool?
    @State private var intelligenceMode = "summary"
    var tint: Color { accent == "Violeta" ? .purple : accent == "Verde" ? .green : accent == "Laranja" ? .orange : .blue }
    var hasToolFilters:Bool { !query.isEmpty || category != "Todas" }
    var hiddenFavoriteCount:Int {
        let hidden = Set(hiddenTools.split(separator:",").map(String.init))
        return tools.filter { isFavorite($0.id) && hidden.contains($0.id) }.count
    }
    var orderedTools: [Tool] {
        let order = toolOrder.split(separator:",").map(String.init)
        let hidden = hiddenTools.split(separator:",").map(String.init)
        return tools.filter { !hidden.contains($0.id) && (query.isEmpty || $0.name.localizedCaseInsensitiveContains(query)) && (category == "Todas" || $0.category == category) && (model.section != "Favoritos" || favorites.split(separator:",").contains(Substring($0.id))) }.sorted {
            (order.firstIndex(of:$0.id) ?? tools.firstIndex(of:$0) ?? 0) < (order.firstIndex(of:$1.id) ?? tools.firstIndex(of:$1) ?? 0)
        }
    }
    var body: some View {
        NavigationSplitView {
            VStack(alignment:.leading, spacing:18) {
                Label("PDF", systemImage:"doc.richtext").font(.system(size:32, weight:.bold, design:.rounded)).padding(.top,22)
                Text("SEU ESPAÇO DE DOCUMENTOS").font(.caption2).foregroundStyle(.secondary)
                ForEach(["Início","Leitor","Favoritos","Digitalizar","Inteligência","Fluxos"], id:\.self) { item in
                    Button { navigate(to:item) } label: {
                        Label(item, systemImage:sidebarIcon(item)).frame(maxWidth:.infinity, alignment:.leading).padding(12)
                            .background(model.section == item ? tint.opacity(0.15) : .clear, in:RoundedRectangle(cornerRadius:12))
                    }.buttonStyle(.plain).accessibilityAddTraits(model.section == item ? .isSelected : [])
                }
                Spacer()
                Label("Seus arquivos no seu Mac", systemImage:"lock.shield").font(.caption).foregroundStyle(.secondary)
                SettingsLink { Label("Personalizar", systemImage:"slider.horizontal.3") }
            }.padding(20).frame(minWidth:210).background(.ultraThinMaterial)
        } detail: {
            VStack(spacing:0) {
                switch model.section {
                case "Leitor": ReaderWorkspaceView()
                case "Inteligência": IntelligenceView(initialMode:intelligenceMode).id(intelligenceMode)
                case "Digitalizar": NativeFeaturesView()
                case "Fluxos": WorkflowView()
                case "Compartilhar": SharePDFView()
                case "Pages para PDF": PagesConversionView()
                case "Sign.com": ExternalSigningView()
                default: home
                }
                statusBar
            }.navigationTitle(model.section == "Leitor" ? model.url?.lastPathComponent ?? "Leitor" : model.section)
        }
        .tint(tint)
        .preferredColorScheme(appearance == "Escuro" ? .dark : appearance == "Claro" ? .light : nil)
        .sheet(item:$selected) { ToolConfigurationView(tool:$0).environmentObject(model) }
        .alert("Abrir documento protegido", isPresented:$model.needsPassword) {
            SecureField("Senha", text:$model.documentPassword)
            Button("Abrir") { model.unlockPendingDocument() }
            Button("Cancelar", role:.cancel) { model.documentPassword = "" }
        } message: { Text("Digite a senha para abrir este PDF.") }
    }
    var home: some View {
        ScrollView {
            VStack(alignment:.leading, spacing:24) {
                HStack {
                    VStack(alignment:.leading, spacing:10) {
                        Text("Clareza em cada página.").font(.system(size:36, weight:.semibold, design:.rounded))
                        Text("Leia, transforme e organize seus documentos.").foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Abrir documento", systemImage:"plus") { model.open() }.buttonStyle(.borderedProminent).controlSize(.large)
                }.padding(28).pdfGlass()
                if showRecent && model.section != "Favoritos" && !model.recentURLs.isEmpty {
                    VStack(alignment:.leading, spacing:12) {
                        HStack { Text("Continue de onde parou").font(.headline); Spacer(); Button("Limpar") { model.clearRecent() }.font(.caption) }
                        ScrollView(.horizontal, showsIndicators:false) {
                            HStack(spacing:12) {
                                ForEach(model.recentURLs.prefix(6), id:\.path) { url in
                                    Button { model.open(url:url) } label: {
                                        Label(url.lastPathComponent, systemImage:"doc.text").lineLimit(1).padding(12).frame(maxWidth:220).background(.regularMaterial, in:RoundedRectangle(cornerRadius:12))
                                    }.buttonStyle(.plain).help(url.path)
                                }
                            }
                        }
                    }
                }
                HStack {
                    TextField("Buscar ferramenta", text:$query).textFieldStyle(.roundedBorder)
                    Picker("Categoria", selection:$category) { ForEach(["Todas","Organizar","Converter","Editar","Proteger","Capturar","Inteligência","Automatizar","Compartilhar"], id:\.self) { Text($0) } }.frame(width:220)
                }
                if model.section == "Favoritos" && hiddenFavoriteCount > 0 {
                    HStack(spacing:8) {
                        Image(systemName:"eye.slash")
                        Text(hiddenFavoriteCount == 1 ? "1 favorito está oculto nas preferências." : "\(hiddenFavoriteCount) favoritos estão ocultos nas preferências.")
                        SettingsLink { Text("Personalizar") }
                    }.font(.caption).foregroundStyle(.secondary)
                }
                if orderedTools.isEmpty { emptyToolsState }
                HStack(alignment:.firstTextBaseline) {
                    Text(model.section == "Favoritos" ? "Suas ferramentas favoritas" : category == "Todas" ? "Todas as ferramentas" : category).font(.title3.weight(.semibold))
                    Spacer()
                    Text("\(orderedTools.count) \(hasToolFilters ? "resultados" : "ferramentas")").font(.caption).foregroundStyle(.secondary)
                }
                LazyVGrid(columns:[GridItem(.adaptive(minimum:compact ? 185 : 220), spacing:14)], spacing:14) {
                    ForEach(orderedTools) { tool in toolCard(tool) }
                }
            }.padding(28)
        }.background(LinearGradient(colors:[tint.opacity(0.1),Color(nsColor:.windowBackgroundColor),.purple.opacity(0.07)], startPoint:.topLeading, endPoint:.bottomTrailing))
    }
    @ViewBuilder var emptyToolsState: some View {
        if hasToolFilters {
            ContentUnavailableView {
                Label("Nenhum resultado para os filtros",systemImage:"magnifyingglass")
            } description: {
                Text("A busca e a categoria selecionadas não correspondem às ferramentas visíveis nesta seção.")
            } actions: {
                Button("Limpar filtros") { clearToolFilters() }
            }
        } else if model.section == "Favoritos" {
            ContentUnavailableView(
                hiddenFavoriteCount > 0 ? "Seus favoritos estão ocultos" : "Você ainda não tem favoritos",
                systemImage:hiddenFavoriteCount > 0 ? "eye.slash" : "star",
                description:Text(hiddenFavoriteCount > 0 ? "Abra Personalizar para escolher quais ferramentas aparecem." : "Use a estrela nos cartões do Início para adicionar suas ferramentas favoritas.")
            )
        } else {
            ContentUnavailableView {
                Label("Nenhuma ferramenta visível",systemImage:"eye.slash")
            } description: {
                Text("Abra Personalizar para escolher as ferramentas que aparecem no menu.")
            } actions: {
                SettingsLink { Text("Personalizar") }
            }
        }
    }
    func clearToolFilters() { query = ""; category = "Todas" }
    func navigate(to section:String) {
        if section == "Início" || section == "Favoritos" { clearToolFilters() }
        model.section = section
    }
    func toolCard(_ tool:Tool) -> some View {
        Button { activate(tool) } label: {
            VStack(alignment:.leading,spacing:12) {
                Image(systemName:tool.icon)
                    .font(.system(size:21,weight:.medium)).foregroundStyle(tint)
                    .frame(width:40,height:40)
                    .background(tint.opacity(0.12),in:RoundedRectangle(cornerRadius:12))
                VStack(alignment:.leading,spacing:7) {
                    Text(tool.name).font(.headline).foregroundStyle(.primary).lineLimit(2)
                    Text(tool.detail).font(.caption).foregroundStyle(.secondary).lineLimit(compact ? 2 : 3)
                }.frame(maxWidth:.infinity,alignment:.leading)
                Spacer(minLength:0)
            }
            .padding(18).frame(maxWidth:.infinity,alignment:.leading).frame(minHeight:compact ? 150 : 168,alignment:.top)
            .contentShape(RoundedRectangle(cornerRadius:20))
            .pdfGlass()
            .overlay(RoundedRectangle(cornerRadius:20).strokeBorder(Color.primary.opacity(0.07),lineWidth:0.75))
        }
        .buttonStyle(.plain)
        .overlay(alignment:.topTrailing) {
            Button { toggleFavorite(tool.id) } label: {
                Image(systemName:isFavorite(tool.id) ? "star.fill" : "star")
                    .foregroundStyle(isFavorite(tool.id) ? tint : Color.secondary)
                    .frame(width:28,height:28).contentShape(Rectangle())
            }.buttonStyle(.plain).padding(14)
                .help(isFavorite(tool.id) ? "Remover dos favoritos" : "Adicionar aos favoritos")
                .accessibilityLabel((isFavorite(tool.id) ? "Remover " : "Adicionar ") + tool.name + (isFavorite(tool.id) ? " dos favoritos" : " aos favoritos"))
        }
    }
    var statusBar: some View {
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
        }.padding(12).background(.bar)
    }
    func activate(_ tool:Tool) {
        switch tool.id {
        case "summary", "translate", "chat", "quiz": intelligenceMode = tool.id; model.section = "Inteligência"
        case "workflow": model.section = "Fluxos"
        case "scan": model.section = "Digitalizar"
        case "pages-pdf": model.section = "Pages para PDF"
        case "share": model.section = "Compartilhar"
        case "sign-service": model.section = "Sign.com"
        case "converter": category = "Converter"; query = ""; model.section = "Início"
        case "annotate":
            UserDefaults.standard.set(true,forKey:"readerShowAnnotations")
            if model.document == nil { model.open() } else { model.section = "Leitor" }
        default: selected = tool
        }
    }
    func isFavorite(_ id:String) -> Bool { favorites.split(separator:",").contains(Substring(id)) }
    func toggleFavorite(_ id:String) {
        var ids = favorites.split(separator:",").map(String.init)
        if ids.contains(id) { ids.removeAll { $0 == id } } else { ids.append(id) }
        favorites = ids.joined(separator:",")
    }
    func sidebarIcon(_ item:String) -> String {
        ["Início":"square.grid.2x2","Leitor":"book","Favoritos":"star","Digitalizar":"scanner","Inteligência":"sparkles","Fluxos":"arrow.triangle.branch"][item] ?? "folder"
    }
}

extension View {
    @ViewBuilder func pdfGlass() -> some View {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) { self.glassEffect(.regular, in:.rect(cornerRadius:20)) }
        else { self.background(.regularMaterial, in:RoundedRectangle(cornerRadius:20)) }
        #else
        self.background(.regularMaterial, in:RoundedRectangle(cornerRadius:20))
        #endif
    }
}
