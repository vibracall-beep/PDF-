import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers

private struct FormFieldDraft: Identifiable {
    var id = UUID()
    var name = "campo"
    var type = "text"
    var page = 1
    var x = 36.0
    var y = 72.0
    var width = 220.0
    var height = 28.0
    var value = ""
    var choices = "Opção 1,Opção 2"
    var detectedLabel: String?
    var detectionSource: String?
    var confidence: Double?
    var lowConfidence = false
    var included = true
    var options:[String:Any] {
        var value:[String:Any] = ["name":name,"type":type,"page":page,"rect":[x,y,x+width,y+height],"value": type == "checkbox" ? (self.value.lowercased() == "true" || self.value.lowercased() == "yes" || self.value == "1") as Any : self.value as Any]
        let labels = choices.split(separator:",").map { $0.trimmingCharacters(in:.whitespaces) }
        if ["choice","list"].contains(type) { value["choices"] = labels }
        if type == "radio" {
            value["choices"] = labels.enumerated().map { index,label in
                ["value":label,"label":label,"rect":[x,y+Double(index)*(height+8),x+width,y+Double(index)*(height+8)+height]] as [String:Any]
            }
        }
        return value
    }
}
private struct FormValueDraft: Identifiable {
    var id:String { name }; var name:String; var value:String; var checkbox = false; var checked = false
    var choices:[String] = []
    var allowsEmpty = false
    var readOnly = false
    var originalValue = ""
    var originallyChecked = false
    var jsonValue:Any { checkbox ? checked as Any : value as Any }
    var changed:Bool { !readOnly && (checkbox ? checked != originallyChecked : value != originalValue) }
}

private struct DetectedTablePreview: Identifiable {
    var id: String
    var page: Int
    var rows: [[String]]
    var confidence: Double?
    var columns: Int { rows.map(\.count).max() ?? 0 }
}

struct ToolConfigurationView: View {
    let tool: Tool
    @EnvironmentObject var model: Workspace
    @EnvironmentObject private var appearance: AppearancePreferences
    @Environment(\.dismiss) private var dismiss
    @State private var inputs:[URL] = []
    @State private var text = ""
    @State private var replacement = ""
    @State private var password = ""
    @State private var newPassword = ""
    @State private var secondPassword = ""
    @State private var inputPasswords: [String:String] = [:]
    @State private var outputPassword = ""
    @State private var cropMode = "margin"
    @State private var textBox = false
    @State private var lineWidth = 1.0
    @State private var fontFile: URL?
    @State private var presetID: UUID?
    @State private var presetMessage = ""
    @ObservedObject private var presetStore:ToolPresetStore
    @State private var pages = ""
    @State private var editMode = "text"
    @State private var formMode = "create"
    @State private var compareMode = "visual"
    @State private var presentationMode = "editable"
    @State private var watermarkMode = "text"
    @State private var sourceMode = "file"
    @State private var webURL = "https://"
    @State private var imageURL:URL?
    @State private var degrees = 90
    @State private var dpi = 150
    @State private var quality = 80
    @State private var recompressImages = false
    @State private var fontSize = 14.0
    @State private var fontName = "helv"
    @State private var numberFormat = "{n} / {total}"
    @State private var redactMode = "text"
    @State private var margin = 24.0
    @State private var opacity = 1.0
    @State private var position = "top-left"
    @State private var color = Color.black
    @State private var fill = Color.white
    @State private var shape = "rectangle"
    @State private var x = 36.0
    @State private var y = 72.0
    @State private var width = 220.0
    @State private var height = 80.0
    @State private var startNumber = 1
    @State private var language = "por+eng"
    @State private var structureSource = "auto"
    @State private var structureDPI = 200
    @State private var structureMinimumConfidence = 35.0
    @State private var detectionSummary = ""
    @State private var detectionSettingsChanged = false
    @State private var detectedTables: [DetectedTablePreview] = []
    @State private var pageSize = "original"
    @State private var orientation = "portrait"
    @State private var imageExportMode = "pages"
    @State private var splitGroups = ""
    @State private var fitWidth = true
    @State private var encoding = "utf-8-sig"
    @State private var csvDelimiter = ""
    @State private var transparentPNG = false
    @State private var flattenAnnotations = true
    @State private var flattenWidgets = true
    @State private var fields:[FormFieldDraft] = [FormFieldDraft()]
    @State private var values:[FormValueDraft] = []
    @State private var error = ""
    @State private var readerHasUnsavedChanges = false
    init(tool:Tool,presetStore:ToolPresetStore? = nil) {
        self.tool = tool
        _presetStore = ObservedObject(wrappedValue:presetStore ?? ToolPresetStore.shared)
    }
    var isFormsTool:Bool { ["forms","fill-forms"].contains(tool.id) }
    var isSourceConversion:Bool { ["images","office","html","odt","txt","rtf","epub","csv"].contains(tool.operation) }
    var operation:String {
        if tool.id == "edit" { return editMode }
        if isFormsTool { return formMode == "create" ? "form-create" : formMode == "fill" ? "form-fill" : "forms" }
        if tool.id == "compare" { return compareMode == "visual" ? "compare-visual" : "compare" }
        return tool.operation
    }
    var multipleInputs:Bool { ["merge","images","compare","rotate","organize"].contains(tool.id) }
    var typography:Bool { ["text","watermark","numbers","edit"].contains(operation) && !(operation == "watermark" && watermarkMode == "image") }
    var needsRectangle:Bool { ["image","shape","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image") || (operation == "redact" && redactMode == "area") || (operation == "crop" && cropMode == "area") || (["text","watermark"].contains(operation) && textBox) }
    var hasPageSelection:Bool { ["split","jpg","png","word","powerpoint","excel","markdown","rotate","organize","delete-pages","extract-pages","text","image","shape","signature","watermark","numbers","crop","redact","edit"].contains(operation) }
    var pageSelectionPrompt:String {
        switch operation {
        case "organize": return "Ordem das páginas: 3,1,4-6"
        case "delete-pages": return "Páginas a excluir: 2,5-7"
        case "extract-pages": return "Páginas a extrair: 1,3-5"
        default: return "Páginas (vazio = todas): 1,3-5"
        }
    }
    var outputSuffix:String { ["word":"docx","powerpoint":"pptx","excel":"xlsx","markdown":"md","compare":"txt","compare-visual":"html","forms":"json"][operation] ?? "pdf" }
    var body: some View {
        VStack(alignment:.leading,spacing:0) {
            HStack { Label(appearance.title(for:tool),systemImage:appearance.icon(for:tool)).font(.title2.bold()); Spacer(); Button { dismiss() } label: { Image(systemName:"xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("Fechar ferramenta") }.padding(24)
            Divider()
            ScrollView {
                VStack(alignment:.leading,spacing:20) {
                    Text(tool.detail).foregroundStyle(.secondary)
                    if ToolStyleOptions.supportedTools.contains(tool.id) { presetsSection }
                    if !isSourceConversion && readerHasUnsavedChanges { unsavedReaderBanner }
                    inputSection
                    optionsSection
                    if hasPageSelection { TextField(pageSelectionPrompt,text:$pages).textFieldStyle(.roundedBorder) }
                    if typography { typographySection }
                    if needsRectangle { rectangleSection }
                    if !isSourceConversion { SecureField("Senha do PDF de origem, se houver",text:$password).textFieldStyle(.roundedBorder) }
                    if tool.id == "compare" { SecureField("Senha do segundo PDF (vazio = mesma senha do primeiro)",text:$secondPassword).textFieldStyle(.roundedBorder) }
                    if ["merge","organize"].contains(operation) { SecureField("Senha da cópia combinada, se as origens usam senhas diferentes",text:$outputPassword).textFieldStyle(.roundedBorder) }
                    if operation == "organize" { Text("Adicione PDFs na ordem desejada. A numeração considera todas as páginas dos arquivos em sequência; use a ordem abaixo para incluir, repetir ou excluir páginas.").font(.caption).foregroundStyle(.secondary) }
                    if operation == "protect" { SecureField("Nova senha (8 a 40 caracteres)",text:$newPassword).textFieldStyle(.roundedBorder) }
                    if ["protect","unlock","repair","ocr","pdfa","compress"].contains(operation) { Text("Esta operação se aplica ao documento inteiro.").font(.caption).foregroundStyle(.secondary) }
                    if !error.isEmpty { Text(error).foregroundStyle(.red).font(.callout) }
                    Text("O resultado será salvo em um novo destino. As coordenadas estão em pontos, a partir do canto superior esquerdo da página.").font(.caption).foregroundStyle(.secondary)
                }.padding(24).disabled(model.busy)
            }
            Divider()
            HStack { Button("Cancelar") { dismiss() }; Spacer(); Button("Escolher destino e executar…") { perform() }.buttonStyle(.borderedProminent).disabled(model.busy) }.padding(20)
        }.frame(width:690,height:730)
        .onAppear {
            if tool.id == "fill-forms" { formMode = "fill" }
            if ["txt","epub"].contains(operation) { pageSize = "a4" }
            NSApp.keyWindow?.makeFirstResponder(nil)
            readerHasUnsavedChanges = model.hasUnsavedChanges
            if let url = model.savedDocumentURL ?? model.url, !isSourceConversion && !readerHasUnsavedChanges {
                inputs = [url]; loadFormValues()
            }
            if tool.id == "watermark" { opacity = 0.35; position = "center"; fontSize = 32 }
            if tool.id == "numbers" { position = "bottom-center" }
            if let saved = presetStore.defaultOptions(for:tool.id) { apply(saved); presetID = presetStore.defaultIDs[tool.id] }
        }
        .onChange(of:formMode) { _, mode in if mode == "fill" { loadFormValues() } }
        .onChange(of:inputs) { _, _ in
            fields.removeAll { $0.detectionSource != nil }
            detectionSummary = ""; detectedTables = []; detectionSettingsChanged = false
        }
        .onChange(of:structureSettingsIdentity) { _, _ in if !detectionSummary.isEmpty { detectionSettingsChanged = true } }
        .onDisappear { password = ""; newPassword = ""; secondPassword = ""; outputPassword = ""; inputPasswords = [:] }
    }
    var presetsSection: some View {
        VStack(alignment:.leading,spacing:10) {
            Label("Suas configurações desta ferramenta",systemImage:"slider.horizontal.3").font(.headline)
            if presetStore.loadFailed {
                Text("A biblioteca de configurações está inválida. Os documentos não foram alterados.").foregroundStyle(.orange)
                HStack { Button("Exportar dados para recuperação…") { exportRawPresets() }; Button("Restaurar biblioteca…") { resetPresetLibrary() } }
            } else {
                HStack {
                    Picker("Configuração",selection:$presetID) {
                        Text("Parâmetros atuais").tag(Optional<UUID>.none)
                        ForEach(presetStore.entries(for:tool.id)) { preset in
                            Text(preset.name + (presetStore.defaultIDs[tool.id] == preset.id ? " · padrão" : "")).tag(Optional(preset.id))
                        }
                    }.onChange(of:presetID) { _, id in
                        if let value = presetStore.presets.first(where:{ $0.id == id && $0.toolID == tool.id }) { apply(value.options) }
                    }
                    Button("Salvar como…") { savePreset() }
                    Menu("Gerenciar") {
                        Button("Usar ao abrir esta ferramenta") { do { try presetStore.setDefault(presetID,for:tool.id); presetMessage = "Configuração padrão atualizada." } catch { self.error = error.localizedDescription } }.disabled(presetID == nil)
                        Button("Usar parâmetros originais ao abrir") { do { try presetStore.setDefault(nil,for:tool.id) } catch { self.error = error.localizedDescription } }
                        Divider()
                        Button("Exportar configuração selecionada…") { exportPreset() }.disabled(presetID == nil)
                        Button("Importar configuração…") { importPreset() }
                        Button("Excluir configuração selecionada") {
                            guard let id = presetID else { return }
                            do { try presetStore.remove(id); presetID = nil } catch { self.error = error.localizedDescription }
                        }.disabled(presetID == nil)
                        Divider()
                        Button("Restaurar parâmetros originais") { apply(factoryOptions); fontFile = nil; presetID = nil; presetMessage = "Parâmetros originais restaurados." }
                    }
                }
                Text("Guarda somente parâmetros de formato e apresentação. Senhas, textos, campos preenchidos, páginas selecionadas e caminhos de arquivos não são guardados.").font(.caption).foregroundStyle(.secondary)
                if !presetMessage.isEmpty { Text(presetMessage).font(.caption).foregroundStyle(.secondary) }
            }
        }.padding(14).background(.quaternary,in:RoundedRectangle(cornerRadius:12))
    }
    var factoryOptions: ToolStyleOptions {
        var value = ToolStyleOptions()
        if ["txt-pdf","epub-pdf"].contains(tool.id) { value.pageSize = "a4" }
        if tool.id == "watermark" { value.opacity = 0.35; value.position = "center"; value.fontSize = 32 }
        if tool.id == "numbers" { value.position = "bottom-center" }
        return value
    }
    var currentOptions: ToolStyleOptions {
        var v = ToolStyleOptions()
        v.editMode = editMode; v.compareMode = compareMode; v.presentationMode = presentationMode
        v.watermarkMode = watermarkMode; v.redactMode = redactMode; v.cropMode = cropMode
        v.imageExportMode = imageExportMode; v.pageSize = pageSize; v.orientation = orientation
        v.fontName = fontName; v.position = position; v.shape = shape; v.encoding = encoding
        v.csvDelimiter = csvDelimiter; v.language = language; v.color = color.hexRGB; v.fill = fill.hexRGB
        v.numberFormat = numberFormat; v.degrees = degrees; v.dpi = dpi; v.quality = quality; v.startNumber = startNumber
        v.fontSize = fontSize; v.margin = margin; v.opacity = opacity; v.lineWidth = lineWidth
        v.x = x; v.y = y; v.width = width; v.height = height; v.recompressImages = recompressImages
        v.fitWidth = fitWidth; v.transparentPNG = transparentPNG; v.flattenAnnotations = flattenAnnotations
        v.flattenWidgets = flattenWidgets; v.textBox = textBox
        v.structureSource = structureSource; v.structureDPI = structureDPI; v.structureMinimumConfidence = structureMinimumConfidence
        return v
    }
    func apply(_ v:ToolStyleOptions) {
        editMode = v.editMode; compareMode = v.compareMode; presentationMode = v.presentationMode
        watermarkMode = v.watermarkMode; redactMode = v.redactMode; cropMode = v.cropMode
        imageExportMode = v.imageExportMode; pageSize = v.pageSize; orientation = v.orientation
        fontName = v.fontName; position = v.position; shape = v.shape; encoding = v.encoding
        csvDelimiter = v.csvDelimiter; language = v.language; color = styleColor(v.color); fill = styleColor(v.fill)
        numberFormat = v.numberFormat; degrees = v.degrees; dpi = v.dpi; quality = v.quality; startNumber = v.startNumber
        fontSize = v.fontSize; margin = v.margin; opacity = v.opacity; lineWidth = v.lineWidth
        x = v.x; y = v.y; width = v.width; height = v.height; recompressImages = v.recompressImages
        fitWidth = v.fitWidth; transparentPNG = v.transparentPNG; flattenAnnotations = v.flattenAnnotations
        flattenWidgets = v.flattenWidgets; textBox = v.textBox
        structureSource = v.structureSource ?? "auto"; structureDPI = v.structureDPI ?? 200
        structureMinimumConfidence = v.structureMinimumConfidence ?? 35
    }
    func styleColor(_ hex:String) -> Color {
        let number = UInt64(hex.dropFirst(),radix:16) ?? 0
        return Color(red:Double((number >> 16) & 255)/255,green:Double((number >> 8) & 255)/255,blue:Double(number & 255)/255)
    }
    func savePreset() {
        let alert = NSAlert(); alert.messageText = "Salvar configuração de " + tool.name
        alert.informativeText = "Escolha um nome. Reutilizar o nome atualiza os parâmetros dessa configuração."
        let name = NSTextField(frame:NSRect(x:0,y:0,width:340,height:24))
        name.stringValue = presetStore.presets.first(where:{ $0.id == presetID })?.name ?? "Minha configuração"
        alert.accessoryView = name; alert.addButton(withTitle:"Salvar"); alert.addButton(withTitle:"Cancelar")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        do { presetID = try presetStore.save(name:name.stringValue,toolID:tool.id,options:currentOptions); presetMessage = "Configuração salva neste Mac." }
        catch { self.error = error.localizedDescription }
    }
    func importPreset() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK,let url = panel.url else { return }
        do {
            let info = try url.resourceValues(forKeys:[.fileSizeKey,.isRegularFileKey])
            guard info.isRegularFile == true,(info.fileSize ?? Int.max) <= 64_000 else { throw ToolPresetError.invalid }
            presetID = try presetStore.importPreset(Data(contentsOf:url),for:tool.id)
            if let preset = presetStore.presets.first(where:{ $0.id == presetID }) { apply(preset.options) }
            presetMessage = "Configuração importada e aplicada."
        } catch { self.error = error.localizedDescription }
    }
    func writePresetData(_ data:Data,name:String) throws {
        let panel = NSSavePanel(); panel.allowedContentTypes = [.json]; panel.nameFieldStringValue = name
        guard panel.runModal() == .OK,let url = panel.url else { return }
        try NativeOutput.write(data,to:url)
        presetMessage = "Configuração exportada."
    }
    func exportPreset() {
        guard let id = presetID else { return }
        do { try writePresetData(presetStore.exported(id),name:"PDF-configuracao-" + tool.id + ".json") }
        catch { self.error = error.localizedDescription }
    }
    func exportRawPresets() {
        guard let data = presetStore.originalData() else { return }
        do { try writePresetData(data,name:"PDF-configuracoes-recuperacao.json") } catch { self.error = error.localizedDescription }
    }
    func resetPresetLibrary() {
        let alert = NSAlert(); alert.messageText = "Restaurar biblioteca de configurações?"
        alert.informativeText = "Remove as configurações salvas de todas as ferramentas. Exporte os dados primeiro se quiser preservá-los. Os documentos não serão alterados."
        alert.addButton(withTitle:"Cancelar"); alert.addButton(withTitle:"Restaurar")
        if alert.runModal() == .alertSecondButtonReturn { presetStore.resetLibrary(); presetID = nil }
    }
    var unsavedReaderBanner: some View {
        VStack(alignment:.leading,spacing:10) {
            Label("O PDF aberto tem alterações não salvas",systemImage:"pencil.circle").font(.headline)
            Text("Salve uma cópia para usar a versão atual nesta ferramenta. Você também pode escolher outro arquivo de entrada.").font(.callout)
            Button("Salvar e usar a cópia atual…") { saveReaderCopy() }
        }.padding(14).frame(maxWidth:.infinity,alignment:.leading)
            .background(Color.orange.opacity(0.12),in:RoundedRectangle(cornerRadius:12))
    }
    private func saveReaderCopy() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        let previousSource = model.savedDocumentURL ?? model.url
        model.save()
        readerHasUnsavedChanges = model.hasUnsavedChanges
        guard !readerHasUnsavedChanges,let source = model.savedDocumentURL ?? model.url else { return }
        if multipleInputs {
            if let index = inputs.firstIndex(where:{ $0 == previousSource }) { inputs[index] = source }
            else if !inputs.contains(source) { inputs.append(source) }
        } else { inputs = [source] }
        loadFormValues()
    }
    var inputSection: some View {
        VStack(alignment:.leading,spacing:10) {
            if tool.id == "html" {
                Picker("Origem",selection:$sourceMode) { Text("Arquivo HTML").tag("file"); Text("Endereço da web").tag("url") }.pickerStyle(.segmented)
            }
            if tool.id == "html" && sourceMode == "url" { TextField("https://exemplo.com",text:$webURL).textFieldStyle(.roundedBorder) }
            else {
                HStack { Text("Arquivos de entrada").font(.headline); Spacer(); Button(multipleInputs ? "Adicionar arquivos…" : "Escolher arquivo…") { chooseInputs() } }
                if inputs.isEmpty { Text("Nenhum arquivo selecionado.").foregroundStyle(.secondary).font(.callout) }
                ForEach(Array(inputs.enumerated()),id:\.offset) { index,url in
                    HStack {
                        Image(systemName:"doc"); Text(url.lastPathComponent).lineLimit(1).help(url.path); Spacer()
                        if multipleInputs {
                            Button { inputs.swapAt(index,index-1) } label: { Image(systemName:"arrow.up") }.disabled(index == 0).accessibilityLabel("Mover " + url.lastPathComponent + " para cima")
                            Button { inputs.swapAt(index,index+1) } label: { Image(systemName:"arrow.down") }.disabled(index == inputs.count-1).accessibilityLabel("Mover " + url.lastPathComponent + " para baixo")
                        }
                        Button { inputs.remove(at:index); values = []; if !inputs.contains(url) { inputPasswords[url.path] = nil } } label: { Image(systemName:"minus.circle") }.accessibilityLabel("Remover " + url.lastPathComponent)
                    }.font(.callout)
                    if ["merge","rotate","organize"].contains(operation) {
                        SecureField("Senha de " + url.lastPathComponent + " (opcional)",text:Binding(get:{ inputPasswords[url.path] ?? "" },set:{ inputPasswords[url.path] = $0 })).textFieldStyle(.roundedBorder)
                    }
                }
            }
        }
    }
    @ViewBuilder var optionsSection: some View {
        if tool.id == "edit" {
            Picker("Editar",selection:$editMode) { Text("Adicionar texto").tag("text"); Text("Substituir texto").tag("edit"); Text("Inserir imagem").tag("image"); Text("Desenhar forma").tag("shape") }
        }
        if ["text","watermark","redact","edit"].contains(operation) {
            if operation == "redact" { Picker("Remover",selection:$redactMode) { Text("Ocorrências de texto").tag("text"); Text("Área com texto e gráficos").tag("area") }.pickerStyle(.segmented) }
            if operation == "watermark" { Picker("Marca",selection:$watermarkMode) { Text("Texto").tag("text"); Text("Imagem").tag("image") }.pickerStyle(.segmented) }
            if (operation != "watermark" || watermarkMode == "text") && (operation != "redact" || redactMode == "text") { TextField(operation == "edit" || operation == "redact" ? "Texto a localizar" : "Texto",text:$text).textFieldStyle(.roundedBorder) }
            if operation == "edit" { TextField("Substituir por",text:$replacement).textFieldStyle(.roundedBorder); Text("A substituição pode alterar a diagramação. Revise a cópia gerada.").font(.caption).foregroundStyle(.secondary) }
            if operation == "redact" { Text("As ocorrências encontradas serão removidas permanentemente da cópia. Revise também imagens e outros dados antes de compartilhá-la.").font(.caption).foregroundStyle(.secondary) }
        }
        if ["signature","image"].contains(operation) || (operation == "watermark" && watermarkMode == "image") {
            HStack { Button("Escolher imagem…") { chooseImage() }; Text(imageURL?.lastPathComponent ?? "Nenhuma imagem").foregroundStyle(.secondary).lineLimit(1) }
            if operation == "signature" {
                Text("Insere uma assinatura visual. Não cria uma assinatura digital com certificado.").font(.caption).foregroundStyle(.secondary)
                Button("Preparar solicitação por e-mail…") { if let url = inputs.first { NSSharingService(named:.composeEmail)?.perform(withItems:["Por favor, assine o documento PDF em anexo.",url]) } }.disabled(inputs.isEmpty)
            }
            HStack { Text("Opacidade"); Slider(value:$opacity,in:0.05...1); Text("\(Int(opacity*100))%") }
        }
        if operation == "shape" {
            Picker("Forma",selection:$shape) { Text("Retângulo").tag("rectangle"); Text("Elipse").tag("ellipse"); Text("Linha").tag("line") }
            HStack { ColorPicker("Contorno",selection:$color,supportsOpacity:false); ColorPicker("Preenchimento",selection:$fill,supportsOpacity:false) }
            numberField("Espessura do traço",value:$lineWidth)
            HStack { Text("Opacidade"); Slider(value:$opacity,in:0.05...1) }
        }
        if operation == "rotate" { Picker("Rotação",selection:$degrees) { Text("90°").tag(90); Text("180°").tag(180); Text("270°").tag(270) }.pickerStyle(.segmented) }
        if operation == "compress" {
            Toggle("Reduzir resolução das imagens",isOn:$recompressImages)
            if recompressImages { Stepper("Resolução: \(dpi) DPI",value:$dpi,in:72...300,step:12); Stepper("Qualidade JPEG: \(quality)%",value:$quality,in:20...95,step:5) }
            Text("Sem redução de imagens, a otimização preserva a qualidade. O tamanho final depende do conteúdo.").font(.caption).foregroundStyle(.secondary)
        }
        if ["jpg","png"].contains(operation) {
            Picker("Exportar",selection:$imageExportMode) { Text("Páginas completas").tag("pages"); Text("Imagens incorporadas").tag("embedded") }
            if imageExportMode == "pages" { Stepper("Resolução: \(dpi) DPI",value:$dpi,in:72...600,step:12) }
            if operation == "png" && imageExportMode == "pages" { Toggle("Fundo transparente",isOn:$transparentPNG) }
        }
        if operation == "split" { TextField("Grupos opcionais separados por ponto e vírgula: 1-3;4,6",text:$splitGroups).textFieldStyle(.roundedBorder); Text("Sem grupos, cada página selecionada gera um arquivo.").font(.caption).foregroundStyle(.secondary) }
        if operation == "images" {
            Picker("Página",selection:$pageSize) { Text("Tamanho da imagem").tag("original"); Text("A4").tag("a4"); Text("Carta").tag("letter") }
            if pageSize != "original" {
                Picker("Orientação",selection:$orientation) { Text("Retrato").tag("portrait"); Text("Paisagem").tag("landscape") }
                numberField("Margem",value:$margin)
            } else { Text("Para definir margens e orientação, escolha um tamanho de papel.").font(.caption).foregroundStyle(.secondary) }
        }
        if tool.id == "excel-pdf" {
            Toggle("Ajustar colunas à largura da página",isOn:$fitWidth)
            Picker("Orientação",selection:$orientation) { Text("Retrato").tag("portrait"); Text("Paisagem").tag("landscape") }
        }
        if operation == "powerpoint" { Picker("Conteúdo",selection:$presentationMode) { Text("Texto e imagens editáveis").tag("editable"); Text("Página como imagem").tag("image") }; Text("A conversão editável exige revisão da diagramação.").font(.caption).foregroundStyle(.secondary) }
        if operation == "crop" {
            Picker("Recortar por",selection:$cropMode) { Text("Margens iguais").tag("margin"); Text("Área específica").tag("area") }.pickerStyle(.segmented)
            if cropMode == "margin" { numberField("Margem a recortar (pontos)",value:$margin) }
            Text("O recorte altera a área visível; não remove dados ocultos. Para remoção permanente, use Ocultar PDF.").font(.caption).foregroundStyle(.secondary)
        }
        if operation == "numbers" {
            Stepper("Começar em \(startNumber)",value:$startNumber,in:1...9999)
            TextField("Formato: {n} / {total}",text:$numberFormat).textFieldStyle(.roundedBorder)
            Text("Use {n} para o número e {total} para o total de páginas.").font(.caption).foregroundStyle(.secondary)
        }
        if operation == "ocr" || operation == "pdfa" {
            Picker("Idiomas",selection:$language) { Text("Português + inglês").tag("por+eng"); Text("Português").tag("por"); Text("Inglês").tag("eng"); Text("Espanhol").tag("spa"); Text("Francês").tag("fra"); Text("Alemão").tag("deu") }
            Text("Requer os componentes de OCR e os idiomas instalados. OCR nativo Apple também está disponível em Digitalizar.").font(.caption).foregroundStyle(.secondary)
        }
        if tool.id == "compare" { Picker("Comparação",selection:$compareMode) { Text("Visual (HTML)").tag("visual"); Text("Diferenças de texto").tag("text") }.pickerStyle(.segmented); Text("Selecione exatamente dois documentos.").font(.caption) }
        if ["word","excel"].contains(operation) { structuredOCRSection }
        if isFormsTool { formsSection }
        if ["txt","epub"].contains(operation) { documentLayoutSection }
        if operation == "csv" { csvOptionsSection }
        if operation == "flatten" {
            Toggle("Incorporar anotações",isOn:$flattenAnnotations)
            Toggle("Incorporar campos de formulário",isOn:$flattenWidgets)
            Text("A operação se aplica ao documento inteiro. Os campos incorporados deixam de ser preenchíveis na cópia resultante.").font(.caption).foregroundStyle(.secondary)
        }
        if operation == "delete-pages" { Text("Informe as páginas a excluir. O documento precisa conservar ao menos uma página.").font(.caption).foregroundStyle(.secondary) }
        if operation == "extract-pages" { Text("Informe as páginas que devem aparecer na nova cópia, na ordem desejada.").font(.caption).foregroundStyle(.secondary) }
    }
    var structureSettingsIdentity: String { "\(structureSource)|\(language)|\(structureDPI)|\(structureMinimumConfidence)|\(pages)" }
    var structuredOptions: [String:Any] {
        ["source":structureSource,"language":language,"ocr_dpi":structureDPI,"min_confidence":structureMinimumConfidence]
    }
    var structuredOCRSection: some View {
        VStack(alignment:.leading,spacing:12) {
            Label("Leitura da estrutura",systemImage:"text.viewfinder").font(.headline)
            Picker("Origem do conteúdo",selection:$structureSource) {
                Text("Automática").tag("auto")
                Text("Texto e formas existentes").tag("vector")
                Text("Reconhecer a imagem com OCR").tag("ocr")
            }
            if structureSource != "vector" {
                Picker("Idioma do reconhecimento",selection:$language) {
                    Text("Português + inglês").tag("por+eng"); Text("Português").tag("por"); Text("Inglês").tag("eng")
                    Text("Espanhol").tag("spa"); Text("Francês").tag("fra"); Text("Alemão").tag("deu")
                }
                Stepper("Resolução do OCR: \(structureDPI) DPI",value:$structureDPI,in:120...400,step:10)
                HStack {
                    Text("Sinalizar confiança abaixo de")
                    Slider(value:$structureMinimumConfidence,in:0...100,step:1)
                    Text("\(Int(structureMinimumConfidence))%").monospacedDigit().frame(width:45,alignment:.trailing)
                }
                Text("O indicador ajuda a priorizar a revisão; não representa uma taxa de acerto. O texto reconhecido é mantido mesmo abaixo do limite.").font(.caption).foregroundStyle(.secondary)
            }
            Text("Automática reconhece páginas digitalizadas sem texto pesquisável. Grades retas ajudam a separar tabelas; revise a estrutura e os rótulos. Os idiomas escolhidos precisam estar instalados.").font(.caption).foregroundStyle(.secondary)
        }.padding(14).background(.quaternary,in:RoundedRectangle(cornerRadius:12))
    }
    var detectionReviewSection: some View {
        VStack(alignment:.leading,spacing:10) {
            if !detectionSummary.isEmpty {
                Label(detectionSummary,systemImage:"checklist").font(.callout)
                if detectionSettingsChanged { Text("Os resultados abaixo pertencem à análise anterior. Use Detectar e revisar campos para aplicar os novos parâmetros.").font(.caption).foregroundStyle(.orange) }
                Text("Revise o nome, tipo, página e posição de cada sugestão. Desmarque os campos que não deseja criar.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(detectedTables) { table in
                DisclosureGroup("Tabela da página \(table.page) · \(table.rows.count) linhas × \(table.columns) colunas") {
                    VStack(alignment:.leading,spacing:8) {
                        if let confidence = table.confidence { Text("Evidência do OCR: \(Int((confidence*100).rounded()))% · requer revisão").font(.caption).foregroundStyle(.secondary) }
                        ScrollView(.horizontal) {
                            VStack(alignment:.leading,spacing:1) {
                                ForEach(Array(table.rows.prefix(5).enumerated()),id:\.offset) { _, row in
                                    HStack(alignment:.top,spacing:1) {
                                        ForEach(Array(row.enumerated()),id:\.offset) { _, value in
                                            Text(value.isEmpty ? "—" : value).font(.caption).lineLimit(3).frame(width:125,alignment:.leading).padding(6).background(.quaternary)
                                        }
                                    }
                                }
                            }
                        }
                        Text("Prévia de até cinco linhas. Use PDF para Excel ou Word para extrair a tabela completa.").font(.caption).foregroundStyle(.secondary)
                    }.padding(.top,8)
                }
            }
        }
    }
    var documentLayoutSection: some View {
        VStack(alignment:.leading,spacing:12) {
            Picker("Papel",selection:$pageSize) { Text("A4").tag("a4"); Text("Carta").tag("letter") }
            Picker("Orientação",selection:$orientation) { Text("Retrato").tag("portrait"); Text("Paisagem").tag("landscape") }
            numberField("Tamanho da fonte",value:$fontSize)
            numberField("Margem",value:$margin)
            if operation == "txt" {
                Picker("Codificação",selection:$encoding) { Text("UTF-8").tag("utf-8-sig"); Text("UTF-16").tag("utf-16"); Text("Windows-1252").tag("cp1252"); Text("ISO-8859-1").tag("latin-1") }
            }
            Text("O conteúdo é reorganizado para o tamanho de página escolhido.").font(.caption).foregroundStyle(.secondary)
        }
    }
    var csvOptionsSection: some View {
        VStack(alignment:.leading,spacing:12) {
            Picker("Separador",selection:$csvDelimiter) { Text("Automático").tag(""); Text("Vírgula").tag(","); Text("Ponto e vírgula").tag(";"); Text("Tabulação").tag("\t"); Text("Barra vertical").tag("|") }
            Picker("Codificação",selection:$encoding) { Text("UTF-8").tag("utf-8-sig"); Text("Windows-1252").tag("cp1252"); Text("ISO-8859-1").tag("latin-1") }
            Toggle("Ajustar colunas à largura da página",isOn:$fitWidth)
            Picker("Orientação",selection:$orientation) { Text("Retrato").tag("portrait"); Text("Paisagem").tag("landscape") }
        }
    }
    var typographySection: some View {
        VStack(alignment:.leading,spacing:12) {
            Picker("Fonte",selection:$fontName) { Text("Helvetica").tag("helv"); Text("Helvetica negrito").tag("hebo"); Text("Helvetica itálico").tag("heit"); Text("Times").tag("tiro"); Text("Courier").tag("cour") }
            HStack { numberField("Tamanho da fonte",value:$fontSize); ColorPicker("Cor",selection:$color,supportsOpacity:false) }
            if operation != "edit" {
                HStack {
                    Button("Usar fonte TTF/OTF…") { chooseFont() }
                    if let fontFile { Text(fontFile.lastPathComponent).lineLimit(1); Button("Usar fonte padrão") { self.fontFile = nil } }
                }
                if ["text","watermark"].contains(operation) { Toggle("Definir área exata do texto",isOn:$textBox) }
                if !textBox || operation == "numbers" {
                    Picker("Posição",selection:$position) {
                        Text("Superior esquerda").tag("top-left"); Text("Superior central").tag("top-center"); Text("Superior direita").tag("top-right")
                        Text("Centro").tag("center"); Text("Inferior esquerda").tag("bottom-left"); Text("Inferior central").tag("bottom-center"); Text("Inferior direita").tag("bottom-right")
                    }
                    numberField("Margem",value:$margin)
                }
                HStack { Text("Opacidade"); Slider(value:$opacity,in:0.05...1); Text("\(Int(opacity*100))%") }
            }
        }
    }
    var rectangleSection: some View {
        VStack(alignment:.leading,spacing:10) {
            Text("Posição e dimensões").font(.headline)
            HStack { numberField("Esquerda",value:$x); numberField("Topo",value:$y) }
            HStack { numberField("Largura",value:$width); numberField("Altura",value:$height) }
        }
    }
    var formsSection: some View {
        VStack(alignment:.leading,spacing:14) {
            Picker("Formulário",selection:$formMode) { Text("Criar campos").tag("create"); Text("Preencher").tag("fill"); Text("Inspecionar JSON").tag("inspect") }.pickerStyle(.segmented)
            if formMode == "create" {
                structuredOCRSection
                TextField("Páginas a analisar (vazio = todas): 1,3-5",text:$pages).textFieldStyle(.roundedBorder)
                Button("Detectar e revisar campos…") { detectFields() }.disabled(model.busy || inputs.isEmpty)
                detectionReviewSection
                ForEach($fields) { $field in
                    VStack(alignment:.leading,spacing:8) {
                        if let source = field.detectionSource {
                            Toggle("Incluir esta sugestão",isOn:$field.included)
                            if let label = field.detectedLabel, !label.isEmpty { Text("Rótulo reconhecido: " + label).font(.callout).textSelection(.enabled) }
                            HStack {
                                Text(source == "vector" ? "Formas existentes no PDF" : "Imagem analisada com OCR")
                                if source != "vector", let confidence = field.confidence { Text("· evidência \(Int((confidence*100).rounded()))%") }
                                if field.lowConfidence { Label("Revisão prioritária",systemImage:"exclamationmark.circle").foregroundStyle(.orange) }
                            }.font(.caption).foregroundStyle(.secondary)
                        }
                        HStack { TextField("Nome único",text:$field.name); Picker("Tipo",selection:$field.type) { Text("Texto").tag("text"); Text("Caixa de seleção").tag("checkbox"); Text("Menu de opções").tag("choice"); Text("Lista").tag("list"); Text("Escolha única").tag("radio") }.onChange(of:field.type) { _, kind in if kind == "radio" { field.width = 20; field.height = 20 } }; Button { fields.removeAll { $0.id == field.id } } label: { Image(systemName:"trash") }.accessibilityLabel("Excluir campo " + field.name) }
                        Stepper("Página \(field.page)",value:$field.page,in:1...100000)
                        HStack { numberField("Esquerda",value:$field.x); numberField("Topo",value:$field.y) }
                        HStack { numberField("Largura",value:$field.width); numberField("Altura",value:$field.height) }
                        if ["choice","list","radio"].contains(field.type) { TextField("Opções separadas por vírgulas",text:$field.choices) }
                        if field.type == "radio" { Text("Os botões são posicionados de cima para baixo, com 8 pontos de espaço. Use largura e altura de 18 a 24 pontos. O valor inicial deve corresponder a uma opção; vazio deixa o grupo sem seleção.").font(.caption).foregroundStyle(.secondary) }
                        if field.type == "checkbox" {
                            Toggle("Marcado inicialmente",isOn:Binding(get:{ field.value == "true" },set:{ field.value = $0 ? "true" : "false" }))
                        } else { TextField("Valor inicial",text:$field.value) }
                    }.padding(12).background(.quaternary,in:RoundedRectangle(cornerRadius:10))
                }
                Button("Adicionar campo",systemImage:"plus") { var field = FormFieldDraft(); field.name = "campo\(fields.count+1)"; field.y += Double(fields.count)*40; fields.append(field) }
            } else if formMode == "fill" {
                Button("Ler campos do documento") { loadFormValues() }
                if values.isEmpty { Text("Escolha um PDF com campos existentes. Para documentos protegidos, preencha primeiro a senha de origem.").font(.caption).foregroundStyle(.secondary) }
                ForEach($values) { $field in
                    VStack(alignment:.leading,spacing:4) {
                        if field.checkbox { Toggle(field.name,isOn:$field.checked) }
                        else if !field.choices.isEmpty {
                            Picker(field.name,selection:$field.value) {
                                if field.allowsEmpty || field.value.isEmpty { Text("Sem seleção").tag("") }
                                ForEach(field.choices,id:\.self) { Text($0).tag($0) }
                            }
                        }
                        else { TextField(field.name,text:$field.value).textFieldStyle(.roundedBorder) }
                        if field.readOnly { Text("Somente leitura").font(.caption).foregroundStyle(.secondary) }
                    }.disabled(field.readOnly)
                }
            }
        }
    }
    func numberField(_ label:String,value:Binding<Double>) -> some View { HStack { Text(label).font(.caption); TextField(label,value:value,format:.number).textFieldStyle(.roundedBorder).frame(minWidth:65) } }
    func chooseInputs() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = multipleInputs
        if tool.id == "images" { panel.allowedContentTypes = [.image] }
        else if tool.id == "html" { panel.allowedContentTypes = [.html] }
        else if isSourceConversion {
            let extensions:[String] = ["word-pdf":["doc","docx"],"powerpoint-pdf":["ppt","pptx"],"excel-pdf":["xls","xlsx"],"odt-pdf":["odt"],"txt-pdf":["txt"],"rtf-pdf":["rtf"],"epub-pdf":["epub"],"csv-pdf":["csv","tsv"]][tool.id] ?? []
            let contentTypes = extensions.compactMap { UTType(filenameExtension:$0) }
            if !contentTypes.isEmpty { panel.allowedContentTypes = contentTypes }
        } else { panel.allowedContentTypes = [.pdf] }
        guard panel.runModal() == .OK else { return }
        if multipleInputs { inputs.append(contentsOf:panel.urls) } else { inputs = panel.urls }
        loadFormValues()
    }
    func chooseImage() { let panel = NSOpenPanel(); panel.allowedContentTypes = [.png,.jpeg,.tiff]; if panel.runModal() == .OK { imageURL = panel.url } }
    func chooseFont() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = ["ttf","otf"].compactMap { UTType(filenameExtension:$0) }
        if panel.runModal() == .OK { fontFile = panel.url }
    }
    func loadFormValues() {
        guard isFormsTool else { return }
        values = []; error = ""
        guard formMode == "fill", let source = inputs.first, !model.busy else { return }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-form-values-" + UUID().uuidString,isDirectory:true)
        do { try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700]) }
        catch { self.error = error.localizedDescription; return }
        let output = directory.appendingPathComponent("fields.json")
        model.execute(operation:"forms",inputs:[source],output:output,options:["password":password],title:"Lendo campos",completion: { result in
            defer { try? FileManager.default.removeItem(at:directory); if model.lastOutput == output { model.lastOutput = nil } }
            do {
                let file = try result.get()
                guard let records = try JSONSerialization.jsonObject(with:Data(contentsOf:file)) as? [[String:Any]] else {
                    throw NSError(domain:"PDF.Forms",code:2,userInfo:[NSLocalizedDescriptionKey:"A leitura dos campos retornou uma resposta inválida."])
                }
                var seen = Set<String>()
                values = records.compactMap { item in
                    guard let name = item["name"] as? String, !name.isEmpty, seen.insert(name).inserted else { return nil }
                    let kind = item["type"] as? String ?? ""
                    guard ["Text","CheckBox","ComboBox","ListBox","RadioButton"].contains(kind) else { return nil }
                    let value = item["value"] as? String ?? ""
                    let checked = !value.isEmpty && value != "Off"
                    return FormValueDraft(name:name,value:value,checkbox:kind == "CheckBox",checked:checked,choices:item["choices"] as? [String] ?? [],allowsEmpty:true,readOnly:item["readonly"] as? Bool ?? false,originalValue:value,originallyChecked:checked)
                }
            } catch { values = []; self.error = error.localizedDescription }
        })
    }
    func detectFields() {
        guard let source = inputs.first else { return }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-fields-" + UUID().uuidString,isDirectory:true)
        do { try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700]) }
        catch { self.error = error.localizedDescription; return }
        let output = directory.appendingPathComponent("fields.json")
        var detectionOptions = structuredOptions
        detectionOptions["password"] = password
        if !pages.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { detectionOptions["pages"] = pages }
        error = ""
        model.execute(operation:"form-detect",inputs:[source],output:output,options:detectionOptions,title:"Analisando campos e tabelas",completion: { result in
            defer { try? FileManager.default.removeItem(at:directory); if model.lastOutput == output { model.lastOutput = nil } }
            do {
                let file = try result.get()
                guard let json = try JSONSerialization.jsonObject(with:Data(contentsOf:file)) as? [String:Any], let suggestions = json["fields"] as? [[String:Any]] else { throw NSError(domain:"PDF.Forms",code:1,userInfo:[NSLocalizedDescriptionKey:"Resposta de detecção inválida."]) }
                guard inputs.first == source, formMode == "create" else { return }
                let reviewed = suggestions.compactMap { item -> FormFieldDraft? in
                    guard let name = item["name"] as? String, let rect = item["rect"] as? [Double], rect.count == 4,
                          rect.allSatisfy(\.isFinite), rect[2] > rect[0], rect[3] > rect[1] else { return nil }
                    var field = FormFieldDraft(); field.name = name; field.type = item["type"] as? String ?? "text"; field.page = item["page"] as? Int ?? 1
                    field.x = rect[0]; field.y = rect[1]; field.width = rect[2]-rect[0]; field.height = rect[3]-rect[1]
                    field.detectedLabel = item["label"] as? String; field.detectionSource = item["source"] as? String ?? "vector"
                    if let confidence = item["confidence"] as? Double, confidence.isFinite, (0...1).contains(confidence) { field.confidence = confidence }
                    field.lowConfidence = item["low_confidence"] as? Bool ?? false
                    return field
                }
                guard reviewed.count == suggestions.count else { throw NSError(domain:"PDF.Forms",code:3,userInfo:[NSLocalizedDescriptionKey:"A análise retornou coordenadas inválidas. Os campos anteriores foram mantidos."]) }
                let reports = json["pages"] as? [[String:Any]] ?? []
                var previews: [DetectedTablePreview] = []
                for report in reports {
                    let page = report["page"] as? Int ?? 1
                    for (index,table) in (report["tables"] as? [[String:Any]] ?? []).enumerated() {
                        guard let rawRows = table["rows"] as? [[Any]] else { continue }
                        let rows = rawRows.map { row in row.map { value in value is NSNull ? "" : String(describing:value) } }
                        let score = table["confidence"] as? Double
                        previews.append(DetectedTablePreview(id:"\(page)-\(index)",page:page,rows:rows,confidence:score.flatMap { $0.isFinite && (0...1).contains($0) ? $0 : nil }))
                    }
                }
                fields = reviewed; detectedTables = previews; detectionSettingsChanged = false
                let ocrPages = reports.filter { ($0["source"] as? String) == "ocr" }.count
                let lowWords = reports.reduce(0) { $0 + ($1["low_confidence_words"] as? Int ?? 0) }
                detectionSummary = "\(reports.count) páginas analisadas · \(ocrPages) com OCR · \(reviewed.count) campos · \(previews.count) tabelas"
                if lowWords > 0 { detectionSummary += " · \(lowWords) palavras para revisão prioritária" }
                if fields.isEmpty { detectionSummary += ". Nenhum campo sugerido; você pode adicionar campos manualmente." }
            } catch { self.error = error.localizedDescription }
        })
    }
    func perform() {
        error = ""
        var selectedInputs = inputs
        if tool.id == "html" && sourceMode == "url" {
            guard let url = URL(string:webURL), ["http","https"].contains(url.scheme ?? ""), url.host != nil else { error = "Informe um endereço HTTP ou HTTPS válido."; return }
            selectedInputs = [url]
        }
        guard !selectedInputs.isEmpty else { error = "Escolha os arquivos de entrada."; return }
        if tool.id == "compare" && selectedInputs.count != 2 { error = "Selecione exatamente dois PDFs."; return }
        if operation == "protect" && !(8...40).contains(newPassword.unicodeScalars.count) { error = "A nova senha precisa ter de 8 a 40 caracteres Unicode."; return }
        if !outputPassword.isEmpty && !(8...40).contains(outputPassword.unicodeScalars.count) { error = "A senha da cópia combinada precisa ter de 8 a 40 caracteres Unicode."; return }
        if (["text","edit"].contains(operation) || (operation == "watermark" && watermarkMode == "text") || (operation == "redact" && redactMode == "text")) && text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { error = "Informe o texto da operação."; return }
        if ["organize","delete-pages","extract-pages"].contains(operation) && pages.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { error = "Informe as páginas da operação."; return }
        if (["image","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image")) && imageURL == nil { error = "Escolha a imagem."; return }
        var options:[String:Any] = ["password":password]
        if hasPageSelection && !pages.isEmpty { options["pages"] = pages }
        if tool.id == "compare" && !secondPassword.isEmpty { options["second_password"] = secondPassword }
        if ["merge","rotate","organize"].contains(operation) { options["input_passwords"] = selectedInputs.map { inputPasswords[$0.path].flatMap { $0.isEmpty ? nil : $0 } ?? password } }
        if operation == "rotate", selectedInputs.count == 1, let source = selectedInputs.first {
            options["password"] = inputPasswords[source.path].flatMap { $0.isEmpty ? nil : $0 } ?? password
            options.removeValue(forKey:"input_passwords")
        }
        if ["merge","organize"].contains(operation) && !outputPassword.isEmpty { options["output_password"] = outputPassword }
        if typography {
            options.merge(["font_size":fontSize,"font":fontName,"color":color.hexRGB]) { _,new in new }
            if operation != "edit" {
                options.merge(["position":position,"margin":margin,"opacity":opacity]) { _,new in new }
                if let fontFile { options["font_file"] = fontFile.path }
            }
        }
        if ["text","watermark","redact"].contains(operation) { options["text"] = operation == "redact" && redactMode == "area" ? "" : text }
        if operation == "redact" && redactMode == "area" { options["rects"] = [[x,y,x+width,y+height]] }
        if operation == "edit" { options["search"] = text; options["replacement"] = replacement }
        if let imageURL, ["image","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image") { options["image"] = imageURL.path; options["opacity"] = opacity }
        if needsRectangle { options["rect"] = [x,y,x+width,y+height] }
        if operation == "shape" { options["shape"] = shape; options["color"] = color.hexRGB; options["fill"] = fill.hexRGB; options["line_width"] = lineWidth; options["opacity"] = opacity }
        if operation == "rotate" { options["degrees"] = degrees }
        if operation == "compress" && recompressImages { options["image_dpi"] = dpi; options["quality"] = quality }
        if ["jpg","png"].contains(operation) { options["dpi"] = dpi; options["mode"] = imageExportMode }
        if operation == "png" { options["alpha"] = transparentPNG }
        if operation == "flatten" {
            guard flattenAnnotations || flattenWidgets else { error = "Selecione anotações ou campos para incorporar."; return }
            options["annotations"] = flattenAnnotations; options["widgets"] = flattenWidgets
        }
        if operation == "split" && !splitGroups.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { options["groups"] = splitGroups.split(separator:";").map { $0.trimmingCharacters(in:.whitespaces) } }
        if operation == "images" && pageSize != "original" { options["paper"] = pageSize; options["margin"] = margin; options["orientation"] = orientation }
        if tool.id == "excel-pdf" { options["fit_width"] = fitWidth; options["orientation"] = orientation }
        if operation == "powerpoint" { options["mode"] = presentationMode }
        if ["word","excel"].contains(operation) { options.merge(structuredOptions) { _,new in new } }
        if ["txt","epub"].contains(operation) {
            options["paper"] = pageSize; options["font_size"] = fontSize; options["margin"] = margin; options["landscape"] = orientation == "landscape"
            if operation == "txt" { options["encoding"] = encoding }
        }
        if operation == "csv" {
            if !csvDelimiter.isEmpty { options["delimiter"] = csvDelimiter }
            options["encoding"] = encoding; options["fit_width"] = fitWidth; options["orientation"] = orientation
        }
        if operation == "crop" && cropMode == "margin" { options["margin"] = margin }
        if operation == "numbers" { options["start"] = startNumber; options["format"] = numberFormat }
        if operation == "ocr" || operation == "pdfa" { options["language"] = language }
        if operation == "protect" { options["new_password"] = newPassword }
        if operation == "form-create" {
            let included = fields.filter(\.included)
            guard !included.isEmpty, Set(included.map(\.name)).count == included.count, included.allSatisfy({ !$0.name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty }) else { error = "Inclua ao menos um campo e use nomes únicos."; return }
            options["fields"] = included.map(\.options)
        }
        if operation == "form-fill" {
            guard !values.isEmpty else { error = "Leia os campos antes de preencher."; return }
            let changes = values.filter(\.changed)
            guard !changes.isEmpty else { error = "Nenhum campo editável foi alterado."; return }
            options["values"] = Dictionary(uniqueKeysWithValues:changes.map { ($0.name,$0.jsonValue) })
        }
        let batch = operation == "rotate" && selectedInputs.count > 1
        guard let output = model.selectOutput(extension:outputSuffix,directory:batch || ["split","jpg","png"].contains(operation),toolName:appearance.title(for:tool),originalURL:selectedInputs.first) else { return }
        if batch { model.executeBatch(operation:operation,inputs:selectedInputs,directory:output,options:options,title:tool.name) }
        else { model.execute(operation:operation,inputs:selectedInputs,output:output,options:options,title:tool.name) }
        password = ""; newPassword = ""; secondPassword = ""; outputPassword = ""; inputPasswords = [:]; dismiss()
    }
}
private extension Color {
    var hexRGB:String {
        guard let value = NSColor(self).usingColorSpace(.sRGB) else { return "#000000" }
        return String(format:"#%02X%02X%02X",Int(min(1,max(0,value.redComponent))*255),Int(min(1,max(0,value.greenComponent))*255),Int(min(1,max(0,value.blueComponent))*255))
    }
}
