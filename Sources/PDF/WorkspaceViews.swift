import SwiftUI
import AppKit
import PDFKit

struct ReaderWorkspaceView: View {
    @EnvironmentObject var model: Workspace
    @AppStorage("readerMode") private var mode = 0
    @AppStorage("readerSidebar") private var showSidebar = true
    @AppStorage("readerShowAnnotations") private var showAnnotations = true
    @State private var sidebarTab = "Páginas"
    @State private var search = ""
    @State private var page = "1"
    @State private var note = ""
    @State private var showNote = false
    @State private var showSharing = false
    var body: some View {
        VStack(spacing:0) {
            HStack(spacing:10) {
                Button { showSidebar.toggle() } label: { Image(systemName:"sidebar.left") }.help("Mostrar páginas e sumário")
                Button("Abrir",systemImage:"folder") { model.open() }
                TextField("Buscar no documento",text:$search).textFieldStyle(.roundedBorder).frame(minWidth:120,maxWidth:210).onSubmit { find() }
                Button { find() } label: { Image(systemName:"magnifyingglass") }.help("Próxima ocorrência")
                Spacer()
                Button { model.pdfView?.zoomOut(nil) } label: { Image(systemName:"minus.magnifyingglass") }.help("Reduzir")
                Button { model.pdfView?.zoomIn(nil) } label: { Image(systemName:"plus.magnifyingglass") }.help("Ampliar")
                Button("Ajustar") { model.pdfView?.autoScales = true }
                Menu {
                    Picker("Leitura",selection:$mode) { Text("Contínua").tag(0); Text("Página única").tag(1); Text("Duas páginas").tag(2) }
                    Button("Girar página") { model.rotatePage() }
                    Button("Imprimir…") { model.printDocument() }
                    Button("Compartilhar…") { showSharing = true }
                } label: { Image(systemName:"ellipsis.circle") }
                Button("Salvar cópia",systemImage:"square.and.arrow.down") { model.save() }.disabled(model.document == nil)
            }.padding(12).background(.bar)
            if let document = model.document {
                if showAnnotations {
                    HStack {
                        Button("Realçar",systemImage:"highlighter") { model.highlight() }
                        Button("Nota",systemImage:"note.text") { showNote = true }
                        Toggle(isOn:$model.inkMode) { Label("Desenhar",systemImage:"pencil.tip") }.toggleStyle(.button)
                        Button(model.bookmarks.contains(model.currentPage) ? "Desmarcar página" : "Marcar página",systemImage:model.bookmarks.contains(model.currentPage) ? "bookmark.fill" : "bookmark") { model.toggleBookmark() }
                        Spacer()
                        if model.hasEdits { Label("Cópia ainda não salva",systemImage:"pencil").font(.caption).foregroundStyle(.secondary) }
                    }.padding(.horizontal,14).padding(.vertical,8)
                }
                HStack(spacing:0) {
                    if showSidebar {
                        VStack(spacing:12) {
                            Picker("Navegação",selection:$sidebarTab) { Text("Páginas").tag("Páginas"); Text("Sumário").tag("Sumário"); Text("Marcas").tag("Marcas") }.pickerStyle(.segmented).labelsHidden()
                            ScrollView {
                                if sidebarTab == "Páginas" {
                                    LazyVStack(spacing:14) {
                                        ForEach(0..<document.pageCount,id:\.self) { index in
                                            Button { model.goToPage(index+1) } label: {
                                                VStack(spacing:5) {
                                                    if let image = model.thumbnail(index) { Image(nsImage:image).resizable().scaledToFit().frame(width:120,height:160) }
                                                    Text("\(index+1)").font(.caption)
                                                }.padding(6).background(model.currentPage == index+1 ? Color.accentColor.opacity(0.15) : .clear,in:RoundedRectangle(cornerRadius:8))
                                            }.buttonStyle(.plain)
                                        }
                                    }.id(model.annotationRevision)
                                } else if sidebarTab == "Sumário" {
                                    if let root = document.outlineRoot { ForEach(0..<root.numberOfChildren,id:\.self) { index in if let child = root.child(at:index) { OutlineBranch(outline:child) } } }
                                    else { Text("Este PDF não possui sumário.").font(.caption).foregroundStyle(.secondary).padding() }
                                } else {
                                    if model.bookmarks.isEmpty { Text("Marque páginas para encontrá-las aqui.").font(.caption).foregroundStyle(.secondary).padding() }
                                    ForEach(model.bookmarks.sorted(),id:\.self) { number in Button("Página \(number)") { model.goToPage(number) }.frame(maxWidth:.infinity,alignment:.leading).padding(8) }
                                }
                            }
                        }.padding(10).frame(width:205).background(.regularMaterial)
                        Divider()
                    }
                    Reader(mode:mode)
                }
                HStack {
                    Button { model.previousPage() } label: { Image(systemName:"chevron.left") }.disabled(model.currentPage <= 1)
                    TextField("Página",text:$page).textFieldStyle(.roundedBorder).frame(width:55).onSubmit { if let number = Int(page) { model.goToPage(number) } }
                    Text("de \(document.pageCount)").font(.caption).foregroundStyle(.secondary)
                    Button { model.nextPage() } label: { Image(systemName:"chevron.right") }.disabled(model.currentPage >= document.pageCount)
                    Spacer()
                    Text("Selecione texto para copiar ou realçar. Campos existentes podem ser preenchidos diretamente.").font(.caption).foregroundStyle(.secondary)
                }.padding(10).background(.bar)
            } else {
                ContentUnavailableView("Abra um PDF",systemImage:"book.closed",description:Text("Leitura, busca, anotações e formulários em um espaço organizado.")).frame(maxWidth:.infinity,maxHeight:.infinity)
            }
        }.onChange(of:model.currentPage) { _,value in page = String(value) }
        .sheet(isPresented:$showSharing) { SharePDFView().environmentObject(model).frame(width:620,height:460) }
        .sheet(isPresented:$showNote) {
            VStack(alignment:.leading,spacing:16) { Text("Adicionar nota").font(.headline); TextEditor(text:$note).frame(width:360,height:150); HStack { Button("Cancelar") { showNote = false }; Spacer(); Button("Adicionar") { model.addNote(note); note = ""; showNote = false }.buttonStyle(.borderedProminent) } }.padding(24)
        }
    }
    func find() {
        guard !search.isEmpty else { return }
        let next = model.document?.findString(search,fromSelection:model.pdfView?.currentSelection,withOptions:.caseInsensitive)
        let result = next ?? model.document?.findString(search,fromSelection:nil,withOptions:.caseInsensitive)
        if let result { model.pdfView?.setCurrentSelection(result,animate:true); model.pdfView?.go(to:result) }
        else { model.message = "Nenhuma ocorrência de “\(search)”." }
    }
}
private struct OutlineBranch: View {
    let outline:PDFOutline
    @EnvironmentObject var model: Workspace
    var body: some View {
        VStack(alignment:.leading,spacing:6) {
            Button(outline.label ?? "Seção") { if let destination = outline.destination { model.pdfView?.go(to:destination) } }.buttonStyle(.plain).font(.callout)
            if outline.numberOfChildren > 0 {
                ForEach(0..<outline.numberOfChildren,id:\.self) { index in if let child = outline.child(at:index) { OutlineBranch(outline:child).padding(.leading,12) } }
            }
        }.frame(maxWidth:.infinity,alignment:.leading).padding(.vertical,4)
    }
}

struct PreferencesView: View {
    @EnvironmentObject var model:Workspace
    @AppStorage("accent") private var accent = "Azul"
    @AppStorage("appearance") private var appearance = "Sistema"
    @AppStorage("compact") private var compact = false
    @AppStorage("showRecent") private var showRecent = true
    @AppStorage("readerShowAnnotations") private var showAnnotations = true
    @AppStorage("outputPrefix") private var outputPrefix = "PDF-resultado"
    @AppStorage("outputDirectory") private var outputDirectory = ""
    @AppStorage("hiddenTools") private var hiddenTools = ""
    @AppStorage("toolOrder") private var toolOrder = ""
    @State private var tab = "Aparência"
    var ordered:[Tool] { let ids = toolOrder.split(separator:",").map(String.init); return tools.sorted { (ids.firstIndex(of:$0.id) ?? tools.firstIndex(of:$0) ?? 0) < (ids.firstIndex(of:$1.id) ?? tools.firstIndex(of:$1) ?? 0) } }
    var body: some View {
        VStack(alignment:.leading,spacing:20) {
            Picker("Preferências",selection:$tab) { Text("Aparência").tag("Aparência"); Text("Ferramentas").tag("Ferramentas"); Text("Arquivos").tag("Arquivos") }.pickerStyle(.segmented)
            if tab == "Aparência" {
                Form {
                    Picker("Aparência",selection:$appearance) { ForEach(["Sistema","Claro","Escuro"],id:\.self) { Text($0) } }
                    Picker("Cor",selection:$accent) { ForEach(["Azul","Violeta","Verde","Laranja"],id:\.self) { Text($0) } }
                    Toggle("Ferramentas compactas",isOn:$compact)
                    Toggle("Mostrar documentos recentes",isOn:$showRecent)
                    Toggle("Mostrar barra de anotações",isOn:$showAnnotations)
                    Text(AppleHardware.summary).font(.caption).foregroundStyle(.secondary)
                }
            } else if tab == "Ferramentas" {
                Text("Escolha as ferramentas visíveis e a ordem dos cartões.").font(.caption).foregroundStyle(.secondary)
                ScrollView {
                    ForEach(Array(ordered.enumerated()),id:\.element.id) { index,tool in
                        HStack {
                            Toggle(tool.name,isOn:Binding(get:{ !hiddenTools.split(separator:",").contains(Substring(tool.id)) },set:{ visible in var ids = hiddenTools.split(separator:",").map(String.init); ids.removeAll { $0 == tool.id }; if !visible { ids.append(tool.id) }; hiddenTools = ids.joined(separator:",") }))
                            Spacer()
                            Button { reorder(index,index-1) } label: { Image(systemName:"arrow.up") }.disabled(index == 0)
                            Button { reorder(index,index+1) } label: { Image(systemName:"arrow.down") }.disabled(index == ordered.count-1)
                        }.padding(.vertical,4)
                    }
                }
                Button("Restaurar todas as ferramentas") { hiddenTools = ""; toolOrder = "" }
            } else {
                TextField("Prefixo dos arquivos de saída",text:$outputPrefix).textFieldStyle(.roundedBorder)
                HStack { Text(outputDirectory.isEmpty ? "Usar última pasta do seletor" : outputDirectory).font(.caption).lineLimit(2); Spacer(); Button("Escolher pasta…") { let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; if panel.runModal() == .OK { outputDirectory = panel.url?.path ?? "" } } }
                Button("Limpar documentos recentes") { model.clearRecent() }
                Text("Os arquivos de origem são preservados. Cada operação usa um novo destino.").font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength:0)
        }.padding(24).frame(width:560,height:480)
    }
    func reorder(_ from:Int,_ to:Int) { var ids = ordered.map(\.id); ids.swapAt(from,to); toolOrder = ids.joined(separator:",") }
}


struct SharePDFView: View {
    @EnvironmentObject var model:Workspace
    @State private var selected:URL?
    var body:some View {
        VStack(alignment:.leading,spacing:22) {
            Label("Compartilhar PDF",systemImage:"square.and.arrow.up").font(.largeTitle.bold())
            Text("Escolha o arquivo e o serviço do macOS. O compartilhamento só ocorre após sua escolha no menu do sistema.").foregroundStyle(.secondary)
            if model.hasUnsavedChanges {
                Text("O documento aberto tem alterações. Salve uma cópia para compartilhar a versão atual.").font(.callout)
                Button("Salvar cópia atual…") {
                    model.save()
                    if !model.hasUnsavedChanges { selected = model.savedDocumentURL ?? model.url }
                }
            }
            HStack { Button("Escolher PDF…") { choose() }; Spacer() }
            if let selected {
                Label(selected.lastPathComponent,systemImage:"doc.richtext").font(.headline)
                Text(selected.deletingLastPathComponent().path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                ShareLink(item:selected) { Label("Compartilhar arquivo…",systemImage:"square.and.arrow.up") }.buttonStyle(.borderedProminent).controlSize(.large)
            } else { Text("Nenhum arquivo selecionado.").foregroundStyle(.secondary) }
            Spacer()
        }.padding(32).frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
        .onAppear {
            NSApp.keyWindow?.makeFirstResponder(nil)
            if !model.hasUnsavedChanges { selected = model.savedDocumentURL ?? model.url }
        }
    }
    private func choose() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        if panel.runModal() == .OK { selected = panel.url }
    }
}

struct ExternalSigningView:View {
    var body:some View {
        VStack(alignment:.leading,spacing:22) {
            Label("Sign.com",systemImage:"signature").font(.largeTitle.bold())
            Text("Serviço externo de assinatura eletrônica").font(.title3).foregroundStyle(.secondary)
            Text("A conta, o envio dos documentos, os pedidos de assinatura e o acompanhamento são administrados pelo Sign.com no navegador. O serviço pode exigir cadastro ou pagamento.")
            Text("O envio de documentos acontece somente após sua ação no site.").font(.callout).foregroundStyle(.secondary)
            Link(destination:URL(string:"https://www.sign.com/")!) { Label("Abrir Sign.com no navegador",systemImage:"arrow.up.right.square") }.buttonStyle(.borderedProminent).controlSize(.large)
            Spacer()
        }.padding(32).frame(maxWidth:720,maxHeight:.infinity,alignment:.topLeading)
    }
}
