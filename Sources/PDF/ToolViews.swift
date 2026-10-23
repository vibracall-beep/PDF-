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
    var options:[String:Any] {
        var value:[String:Any] = ["name":name,"type":type,"page":page,"rect":[x,y,x+width,y+height],"value": type == "checkbox" ? (self.value.lowercased() == "true" || self.value.lowercased() == "yes" || self.value == "1") as Any : self.value as Any]
        if type == "choice" { value["choices"] = choices.split(separator:",").map { $0.trimmingCharacters(in:.whitespaces) } }
        return value
    }
}
private struct FormValueDraft: Identifiable {
    var id:String { name }; var name:String; var value:String; var checkbox = false; var checked = false
    var jsonValue:Any { checkbox ? checked as Any : value as Any }
}

struct ToolConfigurationView: View {
    let tool: Tool
    @EnvironmentObject var model: Workspace
    @Environment(\.dismiss) private var dismiss
    @State private var inputs:[URL] = []
    @State private var text = ""
    @State private var replacement = ""
    @State private var password = ""
    @State private var newPassword = ""
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
    var isFormsTool:Bool { ["forms","fill-forms"].contains(tool.id) }
    var isSourceConversion:Bool { ["images","office","html","odt","txt","rtf","epub","csv"].contains(tool.operation) }
    var operation:String {
        if tool.id == "edit" { return editMode }
        if isFormsTool { return formMode == "create" ? "form-create" : formMode == "fill" ? "form-fill" : "forms" }
        if tool.id == "compare" { return compareMode == "visual" ? "compare-visual" : "compare" }
        return tool.operation
    }
    var multipleInputs:Bool { ["merge","images","compare","rotate"].contains(tool.id) }
    var typography:Bool { ["text","watermark","numbers","edit"].contains(operation) && !(operation == "watermark" && watermarkMode == "image") }
    var needsRectangle:Bool { ["image","shape","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image") || (operation == "redact" && redactMode == "area") }
    var hasPageSelection:Bool { !["merge","images","office","html","odt","txt","rtf","epub","csv","compare","compare-visual","forms","form-create","form-fill","flatten"].contains(operation) }
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
            HStack { Label(tool.name,systemImage:tool.icon).font(.title2.bold()); Spacer(); Button { dismiss() } label: { Image(systemName:"xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary) }.padding(24)
            Divider()
            ScrollView {
                VStack(alignment:.leading,spacing:20) {
                    Text(tool.detail).foregroundStyle(.secondary)
                    if !isSourceConversion && readerHasUnsavedChanges { unsavedReaderBanner }
                    inputSection
                    optionsSection
                    if hasPageSelection { TextField(pageSelectionPrompt,text:$pages).textFieldStyle(.roundedBorder) }
                    if typography { typographySection }
                    if needsRectangle { rectangleSection }
                    if !isSourceConversion { SecureField("Senha do PDF de origem, se houver",text:$password).textFieldStyle(.roundedBorder) }
                    if operation == "protect" { SecureField("Nova senha (mínimo 8 caracteres)",text:$newPassword).textFieldStyle(.roundedBorder) }
                    if !error.isEmpty { Text(error).foregroundStyle(.red).font(.callout) }
                    Text("O resultado será salvo em um novo destino. As coordenadas estão em pontos, a partir do canto superior esquerdo da página.").font(.caption).foregroundStyle(.secondary)
                }.padding(24)
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
        }
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
                            Button { inputs.swapAt(index,index-1) } label: { Image(systemName:"arrow.up") }.disabled(index == 0)
                            Button { inputs.swapAt(index,index+1) } label: { Image(systemName:"arrow.down") }.disabled(index == inputs.count-1)
                        }
                        Button { inputs.remove(at:index) } label: { Image(systemName:"minus.circle") }
                    }.font(.callout)
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
            Picker("Orientação",selection:$orientation) { Text("Retrato").tag("portrait"); Text("Paisagem").tag("landscape") }
            numberField("Margem",value:$margin)
        }
        if tool.id == "excel-pdf" {
            Toggle("Ajustar colunas à largura da página",isOn:$fitWidth)
            Picker("Orientação",selection:$orientation) { Text("Retrato").tag("portrait"); Text("Paisagem").tag("landscape") }
        }
        if operation == "powerpoint" { Picker("Conteúdo",selection:$presentationMode) { Text("Texto e imagens editáveis").tag("editable"); Text("Página como imagem").tag("image") }; Text("A conversão editável exige revisão da diagramação.").font(.caption).foregroundStyle(.secondary) }
        if operation == "crop" { numberField("Margem a recortar (pontos)",value:$margin); Text("O recorte altera a área visível; não remove dados ocultos.").font(.caption).foregroundStyle(.secondary) }
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
            Picker("Posição",selection:$position) {
                Text("Superior esquerda").tag("top-left"); Text("Superior central").tag("top-center"); Text("Superior direita").tag("top-right")
                Text("Centro").tag("center"); Text("Inferior esquerda").tag("bottom-left"); Text("Inferior central").tag("bottom-center"); Text("Inferior direita").tag("bottom-right")
            }
            numberField("Margem",value:$margin)
            HStack { Text("Opacidade"); Slider(value:$opacity,in:0.05...1); Text("\(Int(opacity*100))%") }
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
                Button("Detectar campos sugeridos no documento…") { detectFields() }.disabled(model.busy || inputs.isEmpty)
                Text("Sugestões de campos exigem revisão de nome, tipo, posição e página antes de criar.").font(.caption).foregroundStyle(.secondary)
                ForEach($fields) { $field in
                    VStack(alignment:.leading,spacing:8) {
                        HStack { TextField("Nome único",text:$field.name); Picker("Tipo",selection:$field.type) { Text("Texto").tag("text"); Text("Caixa").tag("checkbox"); Text("Lista").tag("choice") }; Button { fields.removeAll { $0.id == field.id } } label: { Image(systemName:"trash") } }
                        Stepper("Página \(field.page)",value:$field.page,in:1...100000)
                        HStack { numberField("Esquerda",value:$field.x); numberField("Topo",value:$field.y) }
                        HStack { numberField("Largura",value:$field.width); numberField("Altura",value:$field.height) }
                        if field.type == "choice" { TextField("Opções separadas por vírgulas",text:$field.choices) }
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
                    if field.checkbox { Toggle(field.name,isOn:$field.checked) }
                    else { TextField(field.name,text:$field.value).textFieldStyle(.roundedBorder) }
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
    func loadFormValues() {
        guard isFormsTool, let source = inputs.first, let document = PDFDocument(url:source) else { return }
        if document.isLocked && !document.unlock(withPassword:password) { error = "Informe a senha para ler os campos deste PDF."; return }
        var seen = Set<String>(); var loaded:[FormValueDraft] = []
        for index in 0..<document.pageCount {
            for annotation in document.page(at:index)?.annotations ?? [] {
                if let name = annotation.fieldName, !seen.contains(name) {
                    seen.insert(name)
                    let checkbox = annotation.widgetFieldType == .button && annotation.widgetControlType == .checkBoxControl
                    loaded.append(FormValueDraft(name:name,value:annotation.widgetStringValue ?? "",checkbox:checkbox,checked:checkbox && annotation.buttonWidgetState.rawValue == 1))
                }
            }
        }
        values = loaded
    }
    func detectFields() {
        guard let source = inputs.first else { return }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-fields-" + UUID().uuidString,isDirectory:true)
        do { try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700]) }
        catch { self.error = error.localizedDescription; return }
        let output = directory.appendingPathComponent("fields.json")
        model.execute(operation:"form-detect",inputs:[source],output:output,options:["password":password],title:"Detectando campos") { result in
            defer { try? FileManager.default.removeItem(at:directory); model.lastOutput = nil }
            do {
                let file = try result.get()
                guard let json = try JSONSerialization.jsonObject(with:Data(contentsOf:file)) as? [String:Any], let suggestions = json["fields"] as? [[String:Any]] else { throw NSError(domain:"PDF.Forms",code:1,userInfo:[NSLocalizedDescriptionKey:"Resposta de detecção inválida."]) }
                fields = suggestions.compactMap { item in
                    guard let name = item["name"] as? String, let rect = item["rect"] as? [Double], rect.count == 4 else { return nil }
                    var field = FormFieldDraft(); field.name = name; field.type = item["type"] as? String ?? "text"; field.page = item["page"] as? Int ?? 1
                    field.x = rect[0]; field.y = rect[1]; field.width = rect[2]-rect[0]; field.height = rect[3]-rect[1]; return field
                }
                error = fields.isEmpty ? "Nenhum campo sugerido. Adicione campos manualmente." : "Revise as \(fields.count) sugestões antes de criar o formulário."
            } catch { self.error = error.localizedDescription }
        }
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
        if operation == "protect" && newPassword.count < 8 { error = "A nova senha precisa ter ao menos 8 caracteres."; return }
        if (["text","edit"].contains(operation) || (operation == "redact" && redactMode == "text")) && text.isEmpty { error = "Informe o texto da operação."; return }
        if ["organize","delete-pages","extract-pages"].contains(operation) && pages.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { error = "Informe as páginas da operação."; return }
        if (["image","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image")) && imageURL == nil { error = "Escolha a imagem."; return }
        var options:[String:Any] = ["password":password]
        if !pages.isEmpty { options["pages"] = pages }
        if typography { options.merge(["font_size":fontSize,"font":fontName,"color":color.hexRGB,"position":position,"margin":margin,"opacity":opacity]) { _,new in new } }
        if ["text","watermark","redact"].contains(operation) { options["text"] = operation == "redact" && redactMode == "area" ? "" : text }
        if operation == "redact" && redactMode == "area" { options["rects"] = [[x,y,x+width,y+height]] }
        if operation == "edit" { options["search"] = text; options["replacement"] = replacement }
        if let imageURL { options["image"] = imageURL.path; options["opacity"] = opacity }
        if needsRectangle { options["rect"] = [x,y,x+width,y+height] }
        if operation == "shape" { options["shape"] = shape; options["color"] = color.hexRGB; options["fill"] = fill.hexRGB }
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
        if ["txt","epub"].contains(operation) {
            options["paper"] = pageSize; options["font_size"] = fontSize; options["margin"] = margin; options["landscape"] = orientation == "landscape"
            if operation == "txt" { options["encoding"] = encoding }
        }
        if operation == "csv" {
            if !csvDelimiter.isEmpty { options["delimiter"] = csvDelimiter }
            options["encoding"] = encoding; options["fit_width"] = fitWidth; options["orientation"] = orientation
        }
        if operation == "crop" { options["margin"] = margin }
        if operation == "numbers" { options["start"] = startNumber; options["format"] = numberFormat }
        if operation == "ocr" || operation == "pdfa" { options["language"] = language }
        if operation == "protect" { options["new_password"] = newPassword }
        if operation == "form-create" {
            guard !fields.isEmpty, Set(fields.map(\.name)).count == fields.count, fields.allSatisfy({ !$0.name.isEmpty }) else { error = "Adicione campos com nomes únicos."; return }
            options["fields"] = fields.map(\.options)
        }
        if operation == "form-fill" { guard !values.isEmpty else { error = "Leia os campos antes de preencher."; return }; options["values"] = Dictionary(uniqueKeysWithValues:values.map { ($0.name,$0.jsonValue) }) }
        let batch = operation == "rotate" && selectedInputs.count > 1
        guard let output = model.selectOutput(extension:outputSuffix,directory:batch || ["split","jpg","png"].contains(operation)) else { return }
        if batch { model.executeBatch(operation:operation,inputs:selectedInputs,directory:output,options:options,title:tool.name) }
        else { model.execute(operation:operation,inputs:selectedInputs,output:output,options:options,title:tool.name) }
        password = ""; newPassword = ""; dismiss()
    }
}
private extension Color {
    var hexRGB:String {
        guard let value = NSColor(self).usingColorSpace(.sRGB) else { return "#000000" }
        return String(format:"#%02X%02X%02X",Int(value.redComponent*255),Int(value.greenComponent*255),Int(value.blueComponent*255))
    }
}
