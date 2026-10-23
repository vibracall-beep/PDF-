import SwiftUI
import AppKit
import PDFKit

struct ReaderWorkspaceView: View {
    @EnvironmentObject var model: Workspace
    @EnvironmentObject var preferences: AppearancePreferences
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @AppStorage("readerMode") private var mode = 0
    @AppStorage("readerSidebar") private var showSidebar = true
    @AppStorage("readerShowAnnotations") private var showAnnotations = true
    @AppStorage("readerHiddenToolbar") private var hiddenToolbar = ""
    @AppStorage("readerHiddenAnnotations") private var hiddenAnnotations = ""
    @AppStorage("readerAutoScale") private var autoScale = true
    @AppStorage("readerZoom") private var zoom = 1.0
    @AppStorage("readerHighlightColor") private var highlightColor = "#FFE600"
    @AppStorage("readerNoteColor") private var noteColor = "#FFCC00"
    @AppStorage("readerShowTabs") private var showTabs = true
    @AppStorage("readerSplitDirection") private var splitDirection = "horizontal"
    @FocusState private var focusedField:ReaderFocus?
    private enum ReaderFocus:Hashable { case search, page }
    @State private var sidebarTab = "Páginas"
    @State private var search = ""
    @State private var page = "1"
    @State private var note = ""
    @State private var showNote = false
    @State private var showSharing = false
    @State private var showReaderSettings = false
    @State private var showInspector = false
    init(initialInspectorPresented:Bool = false) {
        _showInspector = State(initialValue:initialInspectorPresented)
    }
    var surface:AnyShapeStyle {
        reduceTransparency || preferences.state.glassStyle == "opaque" ? AnyShapeStyle(Color(nsColor:.controlBackgroundColor)) : AnyShapeStyle(.regularMaterial)
    }
    var body: some View {
        VStack(spacing:0) {
            if showTabs && !model.sessions.isEmpty { DocumentTabStrip() }
            readerToolbar
            if let document = model.document {
                if showAnnotations { annotationToolbar }
                HStack(spacing:0) {
                    if showSidebar { readerSidebar(document); Divider() }
                    readerDocuments
                }
                pageNavigation(document)
            } else {
                ContentUnavailableView("Abra um PDF",systemImage:"book.closed",description:Text("Leitura, busca, anotações e formulários em um espaço organizado.")).frame(maxWidth:.infinity,maxHeight:.infinity)
            }
        }
        .onAppear {
            page = String(model.currentPage)
            if !showAnnotations || !visible("ink",in:hiddenAnnotations) { model.inkMode = false }
        }
        .onChange(of:model.currentPage) { _,value in
            page = String(value)
            if let selected = model.selectedAnnotation,let current = model.document?.page(at:value-1),selected.page !== current { model.selectAnnotation(nil) }
        }
        .onChange(of:model.activeSessionID) { _,_ in page = String(model.currentPage); search = "" }
        .focusedSceneValue(\.readerCommandActions,ReaderCommandActions(focusSearch:focusDocumentSearch,findNext:find,focusPage:{ focusedField = .page },toggleSidebar:{ showSidebar.toggle() },toggleInspector:{ model.inkMode = false; showInspector.toggle() },share:{ showSharing = true }))
        .inspector(isPresented:$showInspector) {
            AnnotationInspectorView(presented:$showInspector).environmentObject(model)
                .inspectorColumnWidth(min:250,ideal:290,max:400)
        }
        .onChange(of:showAnnotations) { _,visible in if !visible { model.inkMode = false } }
        .onChange(of:hiddenAnnotations) { _,hidden in if hidden.split(separator:",").contains("ink") { model.inkMode = false } }
        .onChange(of:hiddenToolbar) { _,hidden in if hidden.split(separator:",").contains("search") { model.cancelSearch() } }
        .animation(preferences.animation(reduceMotion:reduceMotion),value:showSidebar)
        .animation(preferences.animation(reduceMotion:reduceMotion),value:showAnnotations)
        .sheet(isPresented:$showSharing) { SharePDFView().environmentObject(model).frame(width:620,height:460) }
        .sheet(isPresented:$showNote) {
            VStack(alignment:.leading,spacing:16) {
                Text("Adicionar nota").font(.headline)
                TextEditor(text:$note).frame(width:360,height:150).accessibilityLabel("Texto da nova nota")
                HStack {
                    Button("Cancelar") { showNote = false }.keyboardShortcut(.cancelAction); Spacer()
                    Button("Adicionar") { model.addNote(note,colorHex:noteColor); note = ""; showNote = false }.buttonStyle(.borderedProminent)
                }
            }.padding(24)
        }
    }
    @ViewBuilder var readerDocuments:some View {
        if let comparison = model.sessions.first(where: { $0.id == model.comparisonSessionID && $0.id != model.activeSessionID }) {
            if splitDirection == "vertical" {
                VSplitView { primaryDocument; ReferenceDocumentPane(session:comparison,mode:mode) }
            } else {
                HSplitView { primaryDocument; ReferenceDocumentPane(session:comparison,mode:mode) }
            }
        } else {
            Reader(mode:mode).accessibilityIdentifier("pdf.reader.document")
        }
    }
    var primaryDocument:some View {
        VStack(spacing:0) {
            HStack { Label(model.activeSession?.title ?? model.url?.lastPathComponent ?? "Documento principal",systemImage:"pencil.and.outline").font(.caption.weight(.medium)).lineLimit(1); Spacer(); Text("Principal").font(.caption).foregroundStyle(.secondary) }.padding(10)
            Reader(mode:mode).accessibilityIdentifier("pdf.reader.document")
        }.frame(minWidth:170,minHeight:190).accessibilityElement(children:.contain).accessibilityLabel("Documento principal")
    }
    var readerToolbar:some View {
        GeometryReader { geometry in
            ScrollView(.horizontal,showsIndicators:false) {
                toolbarContent.frame(minWidth:geometry.size.width,alignment:.leading)
            }
        }.frame(height:34).padding(.horizontal,12).padding(.vertical,7).background(surface)
            .popover(isPresented:$showReaderSettings) { readerSettingsPanel }
    }
    var readerSettingsPanel:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:16) {
                HStack { Text("Seu modo de leitura").font(.headline); Spacer(); Button("Concluir") { showReaderSettings = false } }
                ReaderCustomizationControls()
            }.padding(22)
        }.frame(width:420,height:580)
    }
    var toolbarContent:some View {
        HStack(spacing:10) {
            Button { showSidebar.toggle() } label: { Image(systemName:"sidebar.left") }
                .help("Mostrar páginas e sumário").accessibilityLabel(showSidebar ? "Ocultar páginas e sumário" : "Mostrar páginas e sumário")
            if visible("open",in:hiddenToolbar) { Button("Abrir",systemImage:"folder") { model.open() } }
            if visible("search",in:hiddenToolbar) {
                TextField("Buscar no documento",text:$search).textFieldStyle(.roundedBorder).frame(minWidth:110,maxWidth:200).focused($focusedField,equals:.search).onSubmit { find() }.accessibilityIdentifier("pdf.reader.search")
                if model.searching {
                    Button { model.cancelSearch() } label: { Image(systemName:"xmark.circle") }.help("Cancelar busca").accessibilityLabel("Cancelar busca")
                    ProgressView().controlSize(.small).accessibilityLabel("Busca em andamento")
                } else {
                    Button { find() } label: { Image(systemName:"magnifyingglass") }.help("Próxima ocorrência").accessibilityLabel("Buscar próxima ocorrência")
                }
            }
            Spacer(minLength:0)
            if visible("zoom",in:hiddenToolbar) {
                Button { changeZoom(increase:false) } label: { Image(systemName:"minus.magnifyingglass") }.help("Reduzir").accessibilityLabel("Reduzir zoom")
                Button { changeZoom(increase:true) } label: { Image(systemName:"plus.magnifyingglass") }.help("Ampliar").accessibilityLabel("Ampliar zoom")
            }
            if visible("compare",in:hiddenToolbar) { comparisonMenu }
            if visible("fit",in:hiddenToolbar) { Button("Ajustar") { autoScale = true; model.pdfView?.autoScales = true }.help("Ajustar à janela") }
            Menu {
                Picker("Leitura",selection:$mode) { Text("Contínua").tag(0); Text("Página única").tag(1); Text("Duas páginas").tag(2) }
                Toggle("Barra de anotações",isOn:$showAnnotations)
                Toggle("Mostrar abas",isOn:$showTabs)
                Menu("Documentos abertos") {
                    ForEach(model.sessions) { session in Button(session.title) { model.activateSession(session.id) } }
                }
                Divider()
                Button("Girar página") { model.rotatePage() }
                Button("Imprimir…") { model.printDocument() }
                Button("Compartilhar…") { showSharing = true }
                Button("Salvar cópia…") { model.save() }
                Divider()
                Button("Personalizar leitor…") { showReaderSettings = true }
            } label: { Image(systemName:"ellipsis.circle") }.help("Opções do documento").accessibilityLabel("Opções do documento")
            Button { showReaderSettings = true } label: { Image(systemName:"slider.horizontal.3") }
                .help("Personalizar visualização e barras do leitor").accessibilityLabel("Personalizar leitor")
            if visible("save",in:hiddenToolbar) { Button("Salvar cópia",systemImage:"square.and.arrow.down") { model.save() }.disabled(model.document == nil) }
        }
    }
    var annotationToolbar:some View {
        ScrollView(.horizontal,showsIndicators:false) {
            HStack {
                if visible("highlight",in:hiddenAnnotations) { Button("Realçar",systemImage:"highlighter") { model.highlight(colorHex:highlightColor) } }
                if visible("note",in:hiddenAnnotations) { Button("Nota",systemImage:"note.text") { showNote = true } }
                if visible("ink",in:hiddenAnnotations) { Toggle(isOn:$model.inkMode) { Label("Desenhar",systemImage:"pencil.tip") }.toggleStyle(.button) }
                if visible("editor",in:hiddenAnnotations) {
                    Button("Editar anotações",systemImage:"cursorarrow.rays") { model.inkMode = false; showInspector.toggle() }
                        .accessibilityIdentifier("pdf.annotation.inspector")
                }
                if visible("history",in:hiddenAnnotations) {
                    Button { model.undoAnnotation() } label:{ Image(systemName:"arrow.uturn.backward") }.disabled(!model.canUndoAnnotation).help("Desfazer anotação").accessibilityLabel("Desfazer anotação")
                    Button { model.redoAnnotation() } label:{ Image(systemName:"arrow.uturn.forward") }.disabled(!model.canRedoAnnotation).help("Refazer anotação").accessibilityLabel("Refazer anotação")
                }
                if visible("bookmark",in:hiddenAnnotations) { Button(model.bookmarks.contains(model.currentPage) ? "Desmarcar página" : "Marcar página",systemImage:model.bookmarks.contains(model.currentPage) ? "bookmark.fill" : "bookmark") { model.toggleBookmark() } }
                Spacer()
                if model.hasEdits {
                    Label("Anotações ainda não salvas",systemImage:"pencil").font(.caption).foregroundStyle(.secondary)
                        .help("Campos de formulário são verificados ao salvar, fechar ou abrir outro documento.")
                }
            }.padding(.horizontal,14).padding(.vertical,8)
        }
    }
    func readerSidebar(_ document:PDFDocument) -> some View {
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
                                }.padding(6).background(model.currentPage == index+1 ? preferences.accent.opacity(0.15) : .clear,in:RoundedRectangle(cornerRadius:8))
                            }.buttonStyle(.plain).accessibilityLabel("Ir à página \(index+1)")
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
        }.padding(10).frame(width:205).background(surface)
    }
    func pageNavigation(_ document:PDFDocument) -> some View {
        HStack {
            Button { model.previousPage() } label: { Image(systemName:"chevron.left") }.disabled(model.currentPage <= 1).accessibilityLabel("Página anterior").help("Página anterior")
            TextField("Página",text:$page).textFieldStyle(.roundedBorder).frame(width:55).focused($focusedField,equals:.page).accessibilityLabel("Número da página principal").accessibilityIdentifier("pdf.reader.page").onSubmit { if let number = Int(page) { model.goToPage(number) }; page = String(model.currentPage) }
            Text("de \(document.pageCount)").font(.caption).foregroundStyle(.secondary)
            Button { model.nextPage() } label: { Image(systemName:"chevron.right") }.disabled(model.currentPage >= document.pageCount).accessibilityLabel("Próxima página").help("Próxima página")
            Spacer()
            Text("Selecione texto para copiar ou realçar. Preencha campos diretamente na página.").font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }.padding(10).background(surface)
    }
    var comparisonMenu:some View {
        Menu {
            Button("Sem referência") { model.comparisonSessionID = nil }
            Divider()
            ForEach(model.sessions.filter { $0.id != model.activeSessionID }) { session in
                Button { model.comparisonSessionID = session.id } label:{ Label(session.title,systemImage:model.comparisonSessionID == session.id ? "checkmark" : "doc.text") }
            }
            Divider()
            Button("Abrir outro PDF…") { model.open() }
            Picker("Disposição",selection:$splitDirection) { Text("Lado a lado").tag("horizontal"); Text("Empilhados").tag("vertical") }
        } label: { Image(systemName:"rectangle.split.2x1") }
            .help("Ler dois documentos simultaneamente").accessibilityLabel("Escolher documento de referência")
            .accessibilityIdentifier("pdf.reader.compare")
    }
    func focusDocumentSearch() {
        hiddenToolbar = hiddenToolbar.split(separator:",").filter { $0 != "search" }.joined(separator:",")
        DispatchQueue.main.async { focusedField = .search }
    }
    func visible(_ id:String,in values:String) -> Bool { !values.split(separator:",").contains(Substring(id)) }
    func changeZoom(increase:Bool) {
        guard let view = model.pdfView else { return }
        autoScale = false; view.autoScales = false
        if increase { view.zoomIn(nil) } else { view.zoomOut(nil) }
        zoom = min(8,max(0.1,Double(view.scaleFactor)))
    }
    func find() { model.search(search, animate:preferences.state.animationsEnabled && !reduceMotion) }
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

struct PreferencesView:View {
    var body:some View { CustomizationView(closable:false) }
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
