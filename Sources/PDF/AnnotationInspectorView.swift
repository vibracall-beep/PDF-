import SwiftUI
import AppKit
import PDFKit

/// A keyboard-accessible counterpart to direct manipulation on the PDF page.
struct AnnotationInspectorView:View {
    @EnvironmentObject var model:Workspace
    @Binding var presented:Bool
    @State private var color = Color.blue
    @State private var strokeWidth = 2.5
    @State private var x = 0.0
    @State private var y = 0.0
    @State private var width = 100.0
    @State private var height = 40.0
    @State private var error = ""
    @State private var contents = ""
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                Label("Anotações",systemImage:"slider.horizontal.3").font(.headline)
                Spacer()
                Button { presented = false } label:{ Image(systemName:"xmark") }.accessibilityLabel("Fechar inspector de anotações")
            }
            Text("Selecione uma anotação na página ou nesta lista. Arraste sua seleção para mover; use as alças para redimensionar.").font(.caption).foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment:.leading,spacing:14) {
                    annotationList
                    if let selection = model.selectedAnnotation {
                        Divider()
                        Text(annotationTitle(selection)).font(.subheadline.bold())
                        if editsText(selection) {
                            Text("Texto da anotação").font(.caption.weight(.medium))
                            TextEditor(text:$contents).frame(minHeight:75,maxHeight:130).accessibilityLabel("Texto da anotação selecionada")
                        }
                        ColorPicker("Cor da anotação",selection:$color,supportsOpacity:false)
                        if editsStroke(selection) {
                            HStack { Text("Traço"); Slider(value:$strokeWidth,in:0.5...20,step:0.5).accessibilityLabel("Espessura do traço da anotação em pontos"); Text(strokeWidth,format:.number.precision(.fractionLength(1))).monospacedDigit(); Text("pt").foregroundStyle(.secondary) }
                        }
                        Text("Posição e tamanho em pontos PDF").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                        Grid(alignment:.leading,horizontalSpacing:10,verticalSpacing:9) {
                            GridRow { dimension("X",value:$x); dimension("Y",value:$y) }
                            GridRow { dimension("Largura",value:$width); dimension("Altura",value:$height) }
                        }
                        Button("Aplicar alterações",systemImage:"checkmark") { apply() }.buttonStyle(.borderedProminent).frame(maxWidth:.infinity)
                        if !error.isEmpty { Text(error).font(.caption).foregroundStyle(.red).accessibilityLabel("Erro: " + error) }
                        Button("Excluir anotação",systemImage:"trash",role:.destructive) { model.deleteSelectedAnnotation() }
                            .accessibilityIdentifier("pdf.annotation.delete")
                    } else {
                        Text(model.annotationsOnCurrentPage.isEmpty ? "Não há anotações editáveis nesta página." : "Selecione uma anotação para editar o estilo e a geometria.").font(.callout).foregroundStyle(.secondary)
                    }
                }.padding(.trailing,4)
            }
            Divider()
            HStack {
                Button("Desfazer",systemImage:"arrow.uturn.backward") { model.undoAnnotation() }.disabled(!model.canUndoAnnotation)
                Button("Refazer",systemImage:"arrow.uturn.forward") { model.redoAnnotation() }.disabled(!model.canRedoAnnotation)
            }
            Text("As alterações ficam na aba atual. Salve uma cópia para exportar o resultado.").font(.caption).foregroundStyle(.secondary)
        }.padding(18)
            .accessibilityElement(children:.contain).accessibilityLabel("Inspector de anotações")
            .accessibilityIdentifier("pdf.reader.inspector")
            .onAppear { loadSelection() }
            .onChange(of:model.selectedAnnotation) { _,_ in loadSelection() }
            .onChange(of:model.annotationRevision) { _,_ in loadSelection() }
    }
    var annotationList:some View {
        VStack(alignment:.leading,spacing:7) {
            Text("Página \(model.currentPage)").font(.subheadline.weight(.semibold))
            ForEach(Array(model.annotationsOnCurrentPage.enumerated()),id:\.offset) { index,item in
                Button { model.selectAnnotation(item) } label: {
                    HStack(alignment:.top,spacing:8) {
                        Image(systemName:model.selectedAnnotation === item ? "checkmark.circle.fill" : "circle").foregroundStyle(model.selectedAnnotation === item ? Color.accentColor : Color.secondary)
                        VStack(alignment:.leading,spacing:3) {
                            Text("\(index+1). " + annotationTitle(item)).font(.callout)
                            if let text = item.contents,!text.isEmpty { Text(text).lineLimit(2).font(.caption).foregroundStyle(.secondary) }
                        }.frame(maxWidth:.infinity,alignment:.leading)
                    }.padding(8).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:9))
                }.buttonStyle(.plain)
                    .accessibilityLabel("Selecionar anotação \(index+1), " + annotationTitle(item))
                    .accessibilityValue(model.selectedAnnotation === item ? "Selecionada" : "")
            }
        }
    }
    func dimension(_ title:String,value:Binding<Double>) -> some View {
        VStack(alignment:.leading,spacing:3) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            TextField(title,value:value,format:.number.precision(.fractionLength(0...2)))
                .textFieldStyle(.roundedBorder).accessibilityLabel(title + " da anotação em pontos")
        }
    }
    func annotationTitle(_ annotation:PDFAnnotation) -> String {
        let names:[(PDFAnnotationSubtype,String)] = [(.highlight,"Realce"),(.ink,"Desenho"),(.text,"Nota"),(.freeText,"Texto"),(.square,"Retângulo"),(.circle,"Elipse"),(.line,"Linha"),(.underline,"Sublinhado"),(.strikeOut,"Texto riscado")]
        return names.first(where:{ PDFAnnotationKind.matches(annotation,$0.0) })?.1 ?? annotation.type ?? "Anotação"
    }
    func loadSelection() {
        error = ""
        guard let item = model.selectedAnnotation else { return }
        color = Color(nsColor:PDFAnnotationKind.matches(item,.freeText) ? item.fontColor ?? item.color : item.color); contents = item.contents ?? ""
        strokeWidth = min(20,max(0.5,Double(item.border?.lineWidth ?? 2.5)))
        x = Double(item.bounds.origin.x); y = Double(item.bounds.origin.y)
        width = Double(item.bounds.width); height = Double(item.bounds.height)
    }
    func editsStroke(_ annotation:PDFAnnotation) -> Bool { [PDFAnnotationSubtype.ink,.square,.circle,.line].contains { PDFAnnotationKind.matches(annotation,$0) } }
    func editsText(_ annotation:PDFAnnotation) -> Bool { [PDFAnnotationSubtype.text,.freeText].contains { PDFAnnotationKind.matches(annotation,$0) } }
    func apply() {
        guard [x,y,width,height,strokeWidth].allSatisfy(\.isFinite),width > 0,height > 0 else { error = "Use dimensões positivas e valores numéricos válidos."; return }
        guard width <= 100_000,height <= 100_000,abs(x) <= 100_000,abs(y) <= 100_000 else { error = "A geometria excede o limite permitido."; return }
        guard let item = model.selectedAnnotation,let page = item.page else { return }
        let bounds = CGRect(x:x,y:y,width:width,height:height)
        do {
            try EditableAnnotations.validate(bounds,on:page)
            error = ""
            model.updateSelectedAnnotation(colorHex:AppearanceColor.hex(color),width:strokeWidth,bounds:bounds,contents:editsText(item) ? contents : nil)
        } catch { self.error = error.localizedDescription }
    }
}
