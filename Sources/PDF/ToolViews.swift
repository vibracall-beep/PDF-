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
        var value:[String:Any] = ["name":name,"type":type,"page":page,"rect":[x,y,x+width,y+height],"value":self.value]
        if type == "choice" { value["choices"] = choices.split(separator:",").map { $0.trimmingCharacters(in:.whitespaces) } }
        return value
    }
}
private struct FormValueDraft: Identifiable { var id:String { name }; var name:String; var value:String }

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
    @State private var fields:[FormFieldDraft] = [FormFieldDraft()]
    @State private var values:[FormValueDraft] = []
    @State private var error = ""
    var operation:String {
        if tool.id == "edit" { return editMode }
        if tool.id == "forms" { return formMode == "create" ? "form-create" : formMode == "fill" ? "form-fill" : "forms" }
        if tool.id == "compare" { return compareMode == "visual" ? "compare-visual" : "compare" }
        return tool.operation
    }
    var multipleInputs:Bool { ["merge","images","compare"].contains(tool.id) }
    var typography:Bool { ["text","watermark","numbers","edit"].contains(operation) && !(operation == "watermark" && watermarkMode == "image") }
    var needsRectangle:Bool { ["image","shape","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image") }
    var hasPageSelection:Bool { !["merge","images","office","html","compare","compare-visual","forms","form-create","form-fill"].contains(operation) }
    var outputSuffix:String { ["word":"docx","powerpoint":"pptx","excel":"xlsx","markdown":"md","compare":"txt","compare-visual":"html","forms":"json"][operation] ?? "pdf" }
    var body: some View {
        VStack(alignment:.leading,spacing:0) {
            HStack { Label(tool.name,systemImage:tool.icon).font(.title2.bold()); Spacer(); Button { dismiss() } label: { Image(systemName:"xmark.circle.fill") }.buttonStyle(.plain).foregroundStyle(.secondary) }.padding(24)
            Divider()
            ScrollView {
                VStack(alignment:.leading,spacing:20) {
                    Text(tool.detail).foregroundStyle(.secondary)
                    inputSection
                    optionsSection
                    if hasPageSelection { TextField(operation == "organize" ? "Ordem das páginas: 3,1,4-6" : "Páginas (vazio = todas): 1,3-5",text:$pages).textFieldStyle(.roundedBorder) }
                    if typography { typographySection }
                    if needsRectangle { rectangleSection }
                    if operation != "images" && operation != "html" && operation != "office" { SecureField("Senha do PDF de origem, se houver",text:$password).textFieldStyle(.roundedBorder) }
                    if operation == "protect" { SecureField("Nova senha (mínimo 8 caracteres)",text:$newPassword).textFieldStyle(.roundedBorder) }
                    if !error.isEmpty { Text(error).foregroundStyle(.red).font(.callout) }
                    Text("O resultado será salvo em um novo destino. As coordenadas estão em pontos, a partir do canto superior esquerdo da página.").font(.caption).foregroundStyle(.secondary)
                }.padding(24)
            }
            Divider()
            HStack { Button("Cancelar") { dismiss() }; Spacer(); Button("Escolher destino e executar…") { perform() }.buttonStyle(.borderedProminent).disabled(model.busy) }.padding(20)
        }.frame(width:690,height:730)
        .onAppear {
            if let url = model.url, tool.id != "images", tool.operation != "office", tool.id != "html" { inputs = [url]; loadFormValues() }
            if tool.id == "watermark" { opacity = 0.35; position = "center"; fontSize = 32 }
            if tool.id == "numbers" { position = "bottom-center" }
        }
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
            if operation == "watermark" { Picker("Marca",selection:$watermarkMode) { Text("Texto").tag("text"); Text("Imagem").tag("image") }.pickerStyle(.segmented) }
            if operation != "watermark" || watermarkMode == "text" { TextField(operation == "edit" || operation == "redact" ? "Texto a localizar" : "Texto",text:$text).textFieldStyle(.roundedBorder) }
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
        if operation == "jpg" { Stepper("Resolução: \(dpi) DPI",value:$dpi,in:72...600,step:12) }
        if operation == "images" { Picker("Página",selection:$pageSize) { Text("Tamanho da imagem").tag("original"); Text("A4").tag("A4"); Text("Carta").tag("letter") }; numberField("Margem",value:$margin) }
        if operation == "powerpoint" { Picker("Conteúdo",selection:$presentationMode) { Text("Texto e imagens editáveis").tag("editable"); Text("Página como imagem").tag("image") }; Text("A conversão editável exige revisão da diagramação.").font(.caption).foregroundStyle(.secondary) }
        if operation == "crop" { numberField("Margem a recortar (pontos)",value:$margin); Text("O recorte altera a área visível; não remove dados ocultos.").font(.caption).foregroundStyle(.secondary) }
        if operation == "numbers" { Stepper("Começar em \(startNumber)",value:$startNumber,in:1...9999) }
        if operation == "ocr" || operation == "pdfa" {
            Picker("Idiomas",selection:$language) { Text("Português + inglês").tag("por+eng"); Text("Português").tag("por"); Text("Inglês").tag("eng"); Text("Espanhol").tag("spa"); Text("Francês").tag("fra"); Text("Alemão").tag("deu") }
            Text("Requer os componentes de OCR e os idiomas instalados. OCR nativo Apple também está disponível em Digitalizar.").font(.caption).foregroundStyle(.secondary)
        }
        if tool.id == "compare" { Picker("Comparação",selection:$compareMode) { Text("Visual (HTML)").tag("visual"); Text("Diferenças de texto").tag("text") }.pickerStyle(.segmented); Text("Selecione exatamente dois documentos.").font(.caption) }
        if tool.id == "forms" { formsSection }
    }
    var typographySection: some View {
        VStack(alignment:.leading,spacing:12) {
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
                ForEach($fields) { $field in
                    VStack(alignment:.leading,spacing:8) {
                        HStack { TextField("Nome único",text:$field.name); Picker("Tipo",selection:$field.type) { Text("Texto").tag("text"); Text("Caixa").tag("checkbox"); Text("Lista").tag("choice") }; Button { fields.removeAll { $0.id == field.id } } label: { Image(systemName:"trash") } }
                        Stepper("Página \(field.page)",value:$field.page,in:1...100000)
                        HStack { numberField("Esquerda",value:$field.x); numberField("Topo",value:$field.y) }
                        HStack { numberField("Largura",value:$field.width); numberField("Altura",value:$field.height) }
                        if field.type == "choice" { TextField("Opções separadas por vírgulas",text:$field.choices) }
                        TextField(field.type == "checkbox" ? "Valor: true ou false" : "Valor inicial",text:$field.value)
                    }.padding(12).background(.quaternary,in:RoundedRectangle(cornerRadius:10))
                }
                Button("Adicionar campo",systemImage:"plus") { var field = FormFieldDraft(); field.name = "campo\(fields.count+1)"; field.y += Double(fields.count)*40; fields.append(field) }
            } else if formMode == "fill" {
                Button("Ler campos do documento") { loadFormValues() }
                if values.isEmpty { Text("Escolha um PDF com campos existentes. Para documentos protegidos, preencha primeiro a senha de origem.").font(.caption).foregroundStyle(.secondary) }
                ForEach($values) { $field in TextField(field.name,text:$field.value).textFieldStyle(.roundedBorder) }
            }
        }
    }
    func numberField(_ label:String,value:Binding<Double>) -> some View { HStack { Text(label).font(.caption); TextField(label,value:value,format:.number).textFieldStyle(.roundedBorder).frame(minWidth:65) } }
    func chooseInputs() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = multipleInputs
        if tool.id == "images" { panel.allowedContentTypes = [.image] }
        else if tool.id == "html" { panel.allowedContentTypes = [.html] }
        else if tool.operation != "office" { panel.allowedContentTypes = [.pdf] }
        guard panel.runModal() == .OK else { return }
        if multipleInputs { inputs.append(contentsOf:panel.urls) } else { inputs = panel.urls }
        loadFormValues()
    }
    func chooseImage() { let panel = NSOpenPanel(); panel.allowedContentTypes = [.png,.jpeg,.tiff]; if panel.runModal() == .OK { imageURL = panel.url } }
    func loadFormValues() {
        guard tool.id == "forms", let source = inputs.first, let document = PDFDocument(url:source) else { return }
        if document.isLocked && !document.unlock(withPassword:password) { error = "Informe a senha para ler os campos deste PDF."; return }
        var seen = Set<String>(); var loaded:[FormValueDraft] = []
        for index in 0..<document.pageCount {
            for annotation in document.page(at:index)?.annotations ?? [] {
                if let name = annotation.fieldName, !seen.contains(name) { seen.insert(name); loaded.append(FormValueDraft(name:name,value:annotation.widgetStringValue ?? "")) }
            }
        }
        values = loaded
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
        if ["text","edit","redact"].contains(operation) && text.isEmpty { error = "Informe o texto da operação."; return }
        if operation == "organize" && pages.isEmpty { error = "Informe a ordem das páginas."; return }
        if (["image","signature"].contains(operation) || (operation == "watermark" && watermarkMode == "image")) && imageURL == nil { error = "Escolha a imagem."; return }
        var options:[String:Any] = ["password":password]
        if !pages.isEmpty { options["pages"] = pages }
        if typography { options.merge(["font_size":fontSize,"color":color.hexRGB,"position":position,"margin":margin,"opacity":opacity]) { _,new in new } }
        if ["text","watermark","redact"].contains(operation) { options["text"] = text }
        if operation == "edit" { options["search"] = text; options["replacement"] = replacement }
        if let imageURL { options["image"] = imageURL.path; options["opacity"] = opacity }
        if needsRectangle { options["rect"] = [x,y,x+width,y+height] }
        if operation == "shape" { options["shape"] = shape; options["color"] = color.hexRGB; options["fill"] = fill.hexRGB }
        if operation == "rotate" { options["degrees"] = degrees }
        if operation == "compress" && recompressImages { options["image_dpi"] = dpi; options["quality"] = quality }
        if operation == "jpg" { options["dpi"] = dpi }
        if operation == "images" && pageSize != "original" { options["page_size"] = pageSize; options["margin"] = margin }
        if operation == "powerpoint" { options["mode"] = presentationMode }
        if operation == "crop" { options["margin"] = margin }
        if operation == "numbers" { options["start"] = startNumber }
        if operation == "ocr" || operation == "pdfa" { options["language"] = language }
        if operation == "protect" { options["new_password"] = newPassword }
        if operation == "form-create" {
            guard !fields.isEmpty, Set(fields.map(\.name)).count == fields.count, fields.allSatisfy({ !$0.name.isEmpty }) else { error = "Adicione campos com nomes únicos."; return }
            options["fields"] = fields.map(\.options)
        }
        if operation == "form-fill" { guard !values.isEmpty else { error = "Leia os campos antes de preencher."; return }; options["values"] = Dictionary(uniqueKeysWithValues:values.map { ($0.name,$0.value) }) }
        guard let output = model.selectOutput(extension:outputSuffix,directory:["split","jpg"].contains(operation)) else { return }
        model.execute(operation:operation,inputs:selectedInputs,output:output,options:options,title:tool.name)
        password = ""; newPassword = ""; dismiss()
    }
}
private extension Color {
    var hexRGB:String {
        guard let value = NSColor(self).usingColorSpace(.sRGB) else { return "#000000" }
        return String(format:"#%02X%02X%02X",Int(value.redComponent*255),Int(value.greenComponent*255),Int(value.blueComponent*255))
    }
}
