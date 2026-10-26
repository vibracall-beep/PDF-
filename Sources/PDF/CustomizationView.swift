import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct CustomizationView:View {
    @EnvironmentObject var preferences:AppearancePreferences
    @EnvironmentObject var model:Workspace
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.dismiss) private var dismiss
    var closable = true
    @State private var tab = "Aparência"
    @State private var message = ""
    @State private var toolSearch = ""
    init(closable:Bool = true, initialTab:String = "Aparência") {
        self.closable = closable
        _tab = State(initialValue:["Aparência","Ferramentas","Navegação","Menus","Leitor","Arquivos","Atalhos","Perfis"].contains(initialTab) ? initialTab : "Aparência")
    }
    var body:some View {
        VStack(alignment:.leading,spacing:16) {
            HStack {
                VStack(alignment:.leading,spacing:4) { Text("Seu PDF, do seu jeito").font(.title2.bold()); Text("As alterações aparecem imediatamente e ficam salvas neste Mac.").font(.caption).foregroundStyle(.secondary) }
                Spacer()
                if closable { Button("Concluir") { dismiss() }.keyboardShortcut(.defaultAction) }
            }
            Picker("Personalização",selection:$tab) { ForEach(["Aparência","Ferramentas","Navegação","Menus","Leitor","Arquivos","Atalhos","Perfis"],id:\.self) { Text($0) } }.pickerStyle(.segmented).labelsHidden().accessibilityLabel("Seção da personalização")
            HStack(alignment:.top,spacing:22) {
                ScrollView {
                    VStack(alignment:.leading,spacing:20) {
                        switch tab {
                        case "Ferramentas": toolSettings
                        case "Navegação": navigationSettings
                        case "Menus": MenuCustomizationControls(store:preferences.advanced)
                        case "Leitor": ReaderCustomizationControls()
                        case "Arquivos": OutputCustomizationControls()
                        case "Atalhos": AdvancedShortcutControls(store:preferences.advanced)
                        case "Perfis": WorkspaceProfileControls(store:preferences.advanced,preferences:preferences)
                        default: appearanceSettings
                        }
                    }.padding(.trailing,4).padding(.bottom,12)
                }.frame(maxWidth:.infinity)
                if tab == "Aparência" {
                    VStack(alignment:.leading,spacing:12) {
                        Label("Prévia ao vivo",systemImage:"eye").font(.headline)
                        CustomizableToolCard(tool:tools[0],favorite:true,row:preferences.state.layout == "list",open:{},toggleFavorite:{}).fixedSize(horizontal:false,vertical:true).allowsHitTesting(false)
                        Text("O mesmo cartão usado no menu, com seus ajustes atuais.").font(.caption).foregroundStyle(.secondary)
                        Spacer()
                    }.frame(width:260).padding(16).background(Color(nsColor:.windowBackgroundColor),in:RoundedRectangle(cornerRadius:18))
                }
            }
            Divider()
            HStack {
                Menu("Restaurar") {
                    Button("Aparência e catálogo padrão") { preferences.reset() }
                    Button("Menus padrão") { do { try preferences.advanced.applyMenu(PDFMenuSnapshot()) } catch { message = error.localizedDescription } }
                    Button("Leitor padrão") { preferences.resetReader(); model.setReaderMagnification(zoom: 1, autoScale: true) }
                }
                Button("Importar…") { importSettings() }
                Button("Exportar…") { exportSettings() }
                Spacer()
                Text(message).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
        }.padding(24).frame(width:850,height:690)
            .tint(preferences.accent).applicationColorScheme(preferences.preferredScheme)
    }
    var appearanceSettings:some View {
        VStack(alignment:.leading,spacing:18) {
            GroupBox("Ponto de partida") {
                HStack { Button("Vidro") { preferences.applyPreset("glass") }; Button("Foco") { preferences.applyPreset("focus") }; Button("Conforto") { preferences.applyPreset("comfortable") } }.padding(6)
            }
            Picker("Tema",selection:$preferences.state.colorScheme) { Text("Sistema").tag("system"); Text("Claro").tag("light"); Text("Escuro").tag("dark") }.pickerStyle(.segmented)
            HStack {
                ColorPicker("Cor de destaque",selection:Binding(get:{ preferences.accent },set:{ preferences.state.accentHex = AppearanceColor.hex($0) }),supportsOpacity:false)
                Text(preferences.state.accentHex).font(.caption.monospaced()).foregroundStyle(.secondary)
            }
            HStack(spacing:9) {
                ForEach(["#007AFF","#AF52DE","#FF2D55","#D76B00","#248A3D","#008B8B","#5856D6","#A2845E","#444444"],id:\.self) { hex in
                    Button { preferences.state.accentHex = hex } label: { Circle().fill(AppearanceColor.color(hex)).frame(width:22,height:22).overlay(Circle().strokeBorder(Color.primary.opacity(preferences.state.accentHex == hex ? 0.8 : 0),lineWidth:2)) }.buttonStyle(.plain).accessibilityLabel("Usar cor " + hex)
                }
            }
            Picker("Organização",selection:$preferences.state.layout) { Text("Grade").tag("grid"); Text("Lista").tag("list") }.pickerStyle(.segmented)
            Picker("Espaçamento",selection:$preferences.state.density) { Text("Compacto").tag("compact"); Text("Equilibrado").tag("comfortable"); Text("Amplo").tag("spacious") }
            range("Largura mínima dos cartões",value:$preferences.state.cardWidth,in:180...380,suffix:"pt").disabled(preferences.state.layout == "list")
            range("Texto das ferramentas e navegação",value:$preferences.state.fontSize,in:11...20,suffix:"pt")
            range("Ícones das ferramentas",value:$preferences.state.iconSize,in:16...40,suffix:"pt")
            Toggle("Mostrar descrições das ferramentas",isOn:$preferences.state.showDetails)
            Toggle("Mostrar categoria em cada ferramenta",isOn:$preferences.state.showCategoryLabels)
            Toggle("Agrupar ferramentas por categoria",isOn:$preferences.state.groupByCategory)
            Toggle("Mostrar mensagem de boas-vindas",isOn:$preferences.state.showHero)
            Toggle("Mostrar documentos recentes",isOn:$preferences.state.showRecent)
            Picker("Fundo",selection:$preferences.state.backgroundStyle) { Text("Degradê suave").tag("gradient"); Text("Cor do sistema").tag("plain") }
            Divider()
            Picker("Superfícies",selection:$preferences.state.glassStyle) { Text("Liquid Glass").tag("glass"); Text("Fosco").tag("frosted"); Text("Opaco").tag("opaque") }.disabled(reduceTransparency)
            range("Transparência",value:$preferences.state.glassTransparency,in:0...0.9,suffix:"",multiplier:100).disabled(reduceTransparency || preferences.state.glassStyle == "opaque")
            if reduceTransparency { Text("Reduzir transparência está ativo no macOS. As superfícies são opacas enquanto essa preferência estiver ativa.").font(.caption).foregroundStyle(.secondary) }
            Divider()
            Toggle("Animar navegação, cartões e transições",isOn:$preferences.state.animationsEnabled).disabled(reduceMotion)
            if reduceMotion { Text("Reduzir movimento está ativo no macOS. As animações e a ampliação ao passar o mouse ficam desativadas.").font(.caption).foregroundStyle(.secondary) }
            Group {
                Picker("Movimento",selection:$preferences.state.animationStyle) { Text("Suave").tag("gentle"); Text("Elástico").tag("spring"); Text("Rápido").tag("quick") }
                range("Duração",value:$preferences.state.animationDuration,in:0.1...0.8,suffix:"ms",multiplier:1000)
                range("Ampliação ao passar o mouse",value:$preferences.state.hoverScale,in:1...1.07,suffix:"%",multiplier:100)
            }.disabled(reduceMotion || !preferences.state.animationsEnabled)
        }
    }
    var toolSettings:some View {
        VStack(alignment:.leading,spacing:14) {
            Text("Categorias visíveis").font(.headline)
            LazyVGrid(columns:[GridItem(.flexible()),GridItem(.flexible())],alignment:.leading) {
                ForEach(AppearanceState.categories,id:\.self) { category in
                    Toggle(category,isOn:Binding(get:{ !preferences.state.hiddenCategories.contains(category) },set:{ visible in setMembership(category,in:&preferences.state.hiddenCategories,included:!visible) }))
                }
            }
            Divider()
            TextField("Encontrar ferramenta para personalizar",text:$toolSearch).textFieldStyle(.roundedBorder)
            Text("Altere nomes, ícones, visibilidade e ordem. Arraste pela alça para reordenar ou use as setas. Os favoritos continuam disponíveis pela estrela no menu.").font(.caption).foregroundStyle(.secondary)
            let ordered = preferences.orderedTools()
            ForEach(Array(ordered.enumerated()).filter { toolSearch.isEmpty || preferences.title(for:$0.element).localizedCaseInsensitiveContains(toolSearch) },id:\.element.id) { index,tool in
                VStack(alignment:.leading,spacing:8) {
                    HStack {
                        Image(systemName:"line.3.horizontal").foregroundStyle(.secondary).draggable("pdf-customize-tool:"+tool.id).help("Arrastar para reordenar").accessibilityLabel("Arrastar "+preferences.title(for:tool))
                        Toggle("Mostrar",isOn:Binding(get:{ !preferences.state.hiddenTools.contains(tool.id) },set:{ visible in setMembership(tool.id,in:&preferences.state.hiddenTools,included:!visible) })).labelsHidden().accessibilityLabel("Mostrar " + preferences.title(for:tool))
                        PreferenceNameField("Nome de "+tool.name,value:Binding(get:{ preferences.title(for:tool) },set:{ value in
                            if value == tool.name { preferences.state.toolTitles.removeValue(forKey:tool.id) }
                            else { preferences.state.toolTitles[tool.id] = value }
                        }),maximum:60,fallback:tool.name)
                        iconPicker(value:Binding(get:{ preferences.icon(for:tool) },set:{ preferences.state.toolIcons[tool.id] = $0 }),original:tool.icon,label:"Ícone de " + preferences.title(for:tool))
                        Button { reorderTool(index,index-1) } label:{ Image(systemName:"arrow.up") }.disabled(index == 0).accessibilityLabel("Mover " + preferences.title(for:tool) + " para cima")
                        Button { reorderTool(index,index+1) } label:{ Image(systemName:"arrow.down") }.disabled(index == ordered.count-1).accessibilityLabel("Mover " + preferences.title(for:tool) + " para baixo")
                    }
                    Text(tool.name + " · " + tool.category).font(.caption2).foregroundStyle(.secondary)
                }.padding(10).background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:10))
                    .dropDestination(for:String.self) { items,_ in
                        guard items.count == 1,let value = items.first,value.hasPrefix("pdf-customize-tool:") else { return false }
                        let id = String(value.dropFirst("pdf-customize-tool:".count))
                        guard tools.contains(where:{$0.id == id}),id != tool.id else { return false }
                        withAnimation(preferences.animation(reduceMotion:reduceMotion)) { preferences.moveTool(id,before:tool.id) }; return true
                    }
            }
            Button("Restaurar nomes, ícones, ordem e visibilidade") { preferences.state.toolTitles = [:]; preferences.state.toolIcons = [:]; preferences.state.toolOrder = []; preferences.state.hiddenTools = []; preferences.state.hiddenCategories = [] }
        }
    }
    var navigationSettings:some View {
        VStack(alignment:.leading,spacing:16) {
            Picker("Aparência da navegação",selection:$preferences.state.sidebarStyle) { Text("Ícones e nomes").tag("both"); Text("Só ícones").tag("icons"); Text("Só nomes").tag("labels") }
            range("Largura da navegação",value:$preferences.state.sidebarWidth,in:190...320,suffix:"pt").disabled(preferences.state.sidebarStyle == "icons")
            Text("Arraste pela alça ou use as setas para mudar a ordem. Altere nomes e ícones das seções; Início permanece acessível para restaurar seus ajustes.").font(.caption).foregroundStyle(.secondary)
            ForEach(Array(preferences.state.sidebar.enumerated()),id:\.element.id) { index,item in
                HStack {
                    Image(systemName:"line.3.horizontal").foregroundStyle(.secondary).draggable("pdf-customize-sidebar:"+item.id).help("Arrastar para reordenar").accessibilityLabel("Arrastar "+item.label)
                    Toggle("Mostrar",isOn:Binding(get:{ preferences.state.sidebar[index].visible },set:{ preferences.state.sidebar[index].visible = $0 })).labelsHidden().disabled(item.id == "Início").accessibilityLabel("Mostrar " + item.label)
                    PreferenceNameField("Nome da seção "+item.id,value:Binding(get:{ preferences.state.sidebar[index].label },set:{ preferences.state.sidebar[index].label = $0 }),maximum:40,fallback:item.id)
                    iconPicker(value:Binding(get:{ preferences.state.sidebar[index].icon },set:{ preferences.state.sidebar[index].icon = $0 }),original:item.icon,label:"Ícone da seção " + item.label)
                    Button { preferences.state.sidebar.swapAt(index,index-1) } label:{ Image(systemName:"arrow.up") }.disabled(index == 0).accessibilityLabel("Mover " + item.label + " para cima")
                    Button { preferences.state.sidebar.swapAt(index,index+1) } label:{ Image(systemName:"arrow.down") }.disabled(index == preferences.state.sidebar.count-1).accessibilityLabel("Mover " + item.label + " para baixo")
                }.padding(.vertical,5)
                    .dropDestination(for:String.self) { items,_ in
                        guard items.count == 1,let value = items.first,value.hasPrefix("pdf-customize-sidebar:") else { return false }
                        let id = String(value.dropFirst("pdf-customize-sidebar:".count))
                        guard preferences.state.sidebar.contains(where:{$0.id == id}),id != item.id else { return false }
                        withAnimation(preferences.animation(reduceMotion:reduceMotion)) { preferences.moveSidebar(id,before:item.id) }; return true
                    }
            }
            Button("Restaurar navegação") { preferences.state.sidebar = AppearanceState.defaultSidebar; preferences.state.sidebarStyle = "both"; preferences.state.sidebarWidth = 210 }
        }
    }
    func range(_ title:String,value:Binding<Double>,in bounds:ClosedRange<Double>,suffix:String,multiplier:Double = 1) -> some View {
        VStack(alignment:.leading,spacing:5) { HStack { Text(title); Spacer(); Text("\(Int(value.wrappedValue*multiplier)) \(suffix)").font(.caption.monospacedDigit()).foregroundStyle(.secondary) }; Slider(value:value,in:bounds).accessibilityLabel(title).accessibilityValue("\(Int(value.wrappedValue*multiplier)) \(suffix)") }
    }
    func iconPicker(value:Binding<String>,original:String,label:String) -> some View {
        let icons = Array(Set([original,value.wrappedValue,"square.grid.2x2","doc.text","book","star","scanner","sparkles","arrow.triangle.branch","folder","house","pencil","signature","lock.shield","photo","tablecells","globe","list.bullet","tray","gearshape","bookmark","wand.and.stars"])).sorted()
        return Picker("Ícone",selection:value) { ForEach(icons,id:\.self) { icon in Image(systemName:icon).tag(icon).accessibilityLabel(icon) } }.labelsHidden().frame(width:62).accessibilityLabel(label)
    }
    func setMembership(_ value:String,in list:inout [String],included:Bool) { list.removeAll { $0 == value }; if included { list.append(value) } }
    func reorderTool(_ from:Int,_ to:Int) { var order = preferences.orderedTools().map(\.id); order.swapAt(from,to); preferences.state.toolOrder = order }
    func importSettings() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK,let url = panel.url else { return }
        do {
            let attributes = try url.resourceValues(forKeys:[.isRegularFileKey,.fileSizeKey])
            let limit = 1_048_576
            guard attributes.isRegularFile == true, let size = attributes.fileSize,size <= limit else { throw PreferenceError.invalid("Escolha um arquivo JSON de até 1 MB.") }
            let file = try FileHandle(forReadingFrom:url); defer { try? file.close() }
            let data = try file.read(upToCount:limit+1) ?? Data()
            try preferences.importData(data); message = "Personalização importada."
        } catch { message = error.localizedDescription }
    }
    func exportSettings() {
        guard let url = NativeOutput.destination(model: model, toolName: "Personalização", extension: "json",
            originalName: "PDF-personalizacao.json") else { return }
        do { try NativeOutput.write(preferences.exportData(),to:url); message = "Aparência, leitura, atalhos e preferências de saída exportados." } catch { message = error.localizedDescription }
    }
}

struct ReaderCustomizationControls:View {
    @EnvironmentObject var model: Workspace
    @AppStorage("readerAutoScale") private var defaultAutoScale = true
    @AppStorage("readerZoom") private var defaultZoom = 1.0
    @AppStorage("readerMode") private var mode = 0
    @AppStorage("readerDirection") private var direction = "vertical"
    @AppStorage("readerDisplayBox") private var box = "crop"
    @AppStorage("readerPageBackground") private var background = "#E8E9EF"
    @AppStorage("readerDisplayPageBreaks") private var pageBreaks = true
    @AppStorage("readerSidebar") private var sidebar = true
    @AppStorage("readerShowAnnotations") private var annotations = true
    @AppStorage("readerHiddenToolbar") private var hiddenToolbar = ""
    @AppStorage("readerHiddenAnnotations") private var hiddenAnnotations = ""
    @AppStorage("readerHighlightColor") private var highlightColor = "#FFE600"
    @AppStorage("readerNoteColor") private var noteColor = "#FFCC00"
    @AppStorage("readerInkColor") private var inkColor = "#007AFF"
    @AppStorage("readerInkWidth") private var inkWidth = 2.5
    @AppStorage("readerShowTabs") private var showTabs = true
    @AppStorage("readerSplitDirection") private var splitDirection = "horizontal"
    private var effectiveZoom: Double { model.activeSession?.zoom ?? defaultZoom }
    private var effectiveAutoScale: Bool { model.activeSession?.autoScale ?? defaultAutoScale }
    var body:some View {
        VStack(alignment:.leading,spacing:16) {
            Picker("Modo de leitura",selection:$mode) { Text("Contínuo").tag(0); Text("Página única").tag(1); Text("Duas páginas").tag(2) }
            Picker("Direção",selection:$direction) { Text("Vertical").tag("vertical"); Text("Horizontal").tag("horizontal") }
            Picker("Área da página",selection:$box) { Text("Área recortada").tag("crop"); Text("Página inteira").tag("media") }
            ColorPicker("Fundo da área de leitura",selection:Binding(get:{ AppearanceColor.color(background) },set:{ background = AppearanceColor.hex($0) }),supportsOpacity:false)
            Toggle("Separar visualmente as páginas",isOn:$pageBreaks)
            Toggle("Ajustar zoom à janela",isOn:Binding(get:{ effectiveAutoScale },set:{ model.setReaderMagnification(autoScale: $0) }))
            HStack {
                Text("Zoom")
                Slider(value:Binding(get:{ effectiveZoom },set:{ model.setReaderMagnification(zoom: $0, autoScale: false) }),in:0.1...8)
                    .accessibilityLabel("Zoom de leitura").accessibilityValue("\(Int(effectiveZoom*100)) por cento")
                Text("\(Int(effectiveZoom*100))%").monospacedDigit()
            }.disabled(effectiveAutoScale)
            Text("Estes controles ajustam a aba ativa e o padrão para novos documentos. Cada aba mantém seu zoom ao alternar perfis.").font(.caption).foregroundStyle(.secondary)
            Toggle("Mostrar abas dos documentos",isOn:$showTabs)
            Picker("Leitura simultânea",selection:$splitDirection) { Text("Lado a lado").tag("horizontal"); Text("Empilhada").tag("vertical") }
            Toggle("Mostrar miniaturas e sumário",isOn:$sidebar)
            Toggle("Mostrar barra de anotações",isOn:$annotations)
            Divider()
            Text("Estilo de novas anotações").font(.headline)
            ColorPicker("Cor do realce",selection:colorBinding($highlightColor),supportsOpacity:false)
            ColorPicker("Cor das notas",selection:colorBinding($noteColor),supportsOpacity:false)
            ColorPicker("Cor do desenho",selection:colorBinding($inkColor),supportsOpacity:false)
            HStack {
                Text("Espessura do traço")
                Slider(value:$inkWidth,in:0.5...20,step:0.5).accessibilityLabel("Espessura do desenho em pontos")
                Text(inkWidth,format:.number.precision(.fractionLength(1))).monospacedDigit()
                Text("pt").foregroundStyle(.secondary)
            }
            Text("Os ajustes são usados nas próximas anotações. As anotações existentes mantêm o estilo original.").font(.caption).foregroundStyle(.secondary)
            Divider()
            ReaderBarCustomizationControls()
        }
    }
    func colorBinding(_ binding:Binding<String>) -> Binding<Color> { Binding(get:{ AppearanceColor.color(binding.wrappedValue) },set:{ binding.wrappedValue = AppearanceColor.hex($0) }) }
    func visibility(_ id:String,in binding:Binding<String>) -> Binding<Bool> { Binding(get:{ !binding.wrappedValue.split(separator:",").contains(Substring(id)) },set:{ visible in var values = binding.wrappedValue.split(separator:",").map(String.init); values.removeAll { $0 == id }; if !visible { values.append(id) }; binding.wrappedValue = values.joined(separator:",") }) }
}

struct OutputCustomizationControls:View {
    @EnvironmentObject var model:Workspace
    @AppStorage("outputPrefix") private var outputPrefix = "PDF-resultado"
    @AppStorage("outputDirectory") private var outputDirectory = ""
    @AppStorage("outputFilenameTemplate") private var template = ""
    @AppStorage("recoveryEnabled") private var recoveryEnabled = true
    var body:some View {
        VStack(alignment:.leading,spacing:16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Modelo do nome dos resultados").font(.callout)
                TextField("Ex.: {original} · {ferramenta}", text: $template).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Modelo do nome dos resultados")
                    .accessibilityIdentifier("pdf.output.filenameTemplate")
            }
            Text("Use {original}, {ferramenta}, {data} e {hora} para formar o nome automaticamente. Deixe vazio para usar o nome alternativo.").font(.caption).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 6) {
                Text("Nome alternativo").font(.callout)
                TextField("Nome alternativo", text: $outputPrefix).textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("pdf.output.filenamePrefix")
            }
            HStack {
                Text(outputDirectory.isEmpty ? "Usar a última pasta do seletor" : outputDirectory).font(.caption).lineLimit(3)
                Spacer(); Button("Escolher pasta…") { let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; if panel.runModal() == .OK { outputDirectory = panel.url?.path ?? "" } }
            }
            if !outputDirectory.isEmpty { Button("Usar a última pasta novamente") { outputDirectory = "" } }
            Divider()
            Toggle("Guardar automaticamente cópias locais",isOn:$recoveryEnabled)
            Text("Cópias de trabalho ficam neste Mac, sem substituir os originais. As cópias existentes podem ser revisadas em Recuperar trabalho.").font(.caption).foregroundStyle(.secondary)
            Button("Limpar documentos recentes") { model.clearRecent() }
            Text("Os originais são preservados e o destino final pode ser ajustado antes de cada operação.").font(.caption).foregroundStyle(.secondary)
            Text(AppleHardware.summary).font(.caption).foregroundStyle(.secondary)
        }
    }
}
