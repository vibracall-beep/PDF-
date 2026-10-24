import SwiftUI
import AppKit
import PDFKit

struct DocumentTabStrip:View {
    @EnvironmentObject var model:Workspace
    @EnvironmentObject var preferences:AppearancePreferences
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body:some View {
        HStack(spacing:8) {
            ScrollView(.horizontal,showsIndicators:false) {
                HStack(spacing:6) {
                    ForEach(model.sessions) { session in
                        DocumentSessionTab(session:session,selected:model.activeSessionID == session.id,
                            activate:{ model.activateSession(session.id) },close:{ model.closeSession(session.id) })
                    }
                }.padding(.horizontal,10).padding(.vertical,8)
            }
            Button { model.open() } label: { Image(systemName:"plus") }
                .help("Abrir PDF em nova aba · ⌘T").accessibilityLabel("Abrir PDF em nova aba")
                .accessibilityIdentifier("pdf.tabs.open").padding(.trailing,12)
        }.accessibilityElement(children:.contain).accessibilityLabel("Documentos abertos")
            .animation(preferences.animation(reduceMotion:reduceMotion),value:model.sessions.map(\.id))
    }
}
private struct DocumentSessionTab:View {
    @ObservedObject var session:PDFDocumentSession
    @EnvironmentObject var preferences:AppearancePreferences
    var selected:Bool
    var activate:()->Void
    var close:()->Void
    var body:some View {
        HStack(spacing:4) {
            Button(action:activate) {
                HStack(spacing:7) {
                    Image(systemName:"doc.text").accessibilityHidden(true)
                    Text(session.title).lineLimit(1)
                    if session.isDirty { Circle().fill(preferences.accent).frame(width:6,height:6).accessibilityHidden(true) }
                }.padding(.leading,10).padding(.vertical,9).frame(minWidth:100,maxWidth:230,alignment:.leading)
            }.buttonStyle(.plain)
                .accessibilityLabel(session.title)
                .accessibilityValue((selected ? "Aba selecionada" : "Aba") + (session.isDirty ? ", com alterações" : ""))
                .accessibilityAddTraits(selected ? .isSelected : [])
                .accessibilityIdentifier("pdf.tab." + session.id.uuidString)
            Button(action:close) { Image(systemName:"xmark").font(.caption).frame(width:25,height:25).contentShape(Rectangle()) }
                .buttonStyle(.plain).help("Fechar " + session.title)
                .accessibilityLabel("Fechar aba " + session.title).padding(.trailing,4)
        }.background(selected ? preferences.accent.opacity(0.14) : Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:10))
            .overlay(RoundedRectangle(cornerRadius:10).strokeBorder(selected ? preferences.accent.opacity(0.4) : .clear,lineWidth:1))
            .help(session.sourceURL?.path ?? session.title)
            .accessibilityElement(children:.contain)
    }
}

struct ReferenceDocumentPane:View {
    @ObservedObject var session:PDFDocumentSession
    @EnvironmentObject var model:Workspace
    var mode:Int
    @State private var pageText = "1"
    var body:some View {
        VStack(spacing:0) {
            HStack(spacing:10) {
                Label(session.title,systemImage:"rectangle.split.2x1").font(.caption.weight(.medium)).lineLimit(1)
                Spacer(minLength:4)
                Button("Tornar principal") {
                    let previous = model.activeSessionID
                    model.activateSession(session.id)
                    model.comparisonSessionID = previous
                }.font(.caption).help("Mover este documento para o painel de edição principal")
                Button { model.comparisonSessionID = nil } label: { Image(systemName:"xmark") }
                    .help("Fechar painel de referência").accessibilityLabel("Fechar painel de referência")
            }.padding(10)
            SessionComparisonReader(session:session,mode:mode)
                .accessibilityIdentifier("pdf.reader.reference")
            HStack(spacing:6) {
                Button { session.page = max(1,session.page-1) } label: { Image(systemName:"chevron.left") }
                    .disabled(session.page <= 1).accessibilityLabel("Página anterior da referência")
                TextField("Página da referência",text:$pageText).frame(width:45).textFieldStyle(.roundedBorder)
                    .onSubmit { if let number = Int(pageText) { session.page = min(session.document.pageCount,max(1,number)) }; pageText = String(session.page) }
                Text("/ \(session.document.pageCount)").font(.caption)
                Button { session.page = min(session.document.pageCount,session.page+1) } label: { Image(systemName:"chevron.right") }
                    .disabled(session.page >= session.document.pageCount).accessibilityLabel("Próxima página da referência")
                Spacer(minLength:3)
                Menu {
                    Button("Ajustar à janela") { session.autoScale = true }
                    ForEach([0.5,0.75,1.0,1.25,1.5,2.0],id:\.self) { value in
                        Button("\(Int(value*100))%") { session.autoScale = false; session.zoom = value }
                    }
                } label: { Text(session.autoScale ? "Ajustado" : "\(Int(session.zoom*100))%") }
                    .accessibilityLabel("Zoom da referência")
            }.padding(9)
        }.frame(minWidth:170,minHeight:190)
            .accessibilityElement(children:.contain).accessibilityLabel("Documento de referência")
            .onAppear { pageText = String(session.page) }
            .onChange(of:session.page) { _,value in pageText = String(value) }
    }
}

struct RecoveryDocumentsView:View {
    @EnvironmentObject var model:Workspace
    @Environment(\.dismiss) private var dismiss
    @AppStorage("recoveryEnabled") private var recoveryEnabled = true
    @State private var pendingRestore:UUID?
    @State private var pendingDelete:UUID?
    @State private var confirmDelete = false
    var body:some View {
        VStack(alignment:.leading,spacing:18) {
            HStack {
                Label("Recuperar trabalho",systemImage:"clock.arrow.circlepath").font(.title2.bold())
                Spacer()
                Button("Concluir") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            Text("As cópias locais de recuperação preservam os arquivos originais. Documentos protegidos exigem a senha do documento ao serem reabertos.").font(.callout).foregroundStyle(.secondary)
            Toggle("Guardar automaticamente cópias locais",isOn:$recoveryEnabled)
            if !model.recoveryWarnings.isEmpty {
                DisclosureGroup {
                    ScrollView {
                        VStack(alignment:.leading,spacing:6) {
                            ForEach(Array(model.recoveryWarnings.enumerated()),id:\.offset) { _,warning in Text(warning).font(.caption).textSelection(.enabled) }
                        }.frame(maxWidth:.infinity,alignment:.leading)
                    }.frame(maxHeight:120)
                } label: { Label("\(PortugueseCount.label(model.recoveryWarnings.count, "aviso", "avisos")): arquivos preservados para revisão",systemImage:"exclamationmark.triangle").foregroundStyle(.orange) }
                Button("Abrir o armazenamento de recuperação",systemImage:"folder") { NSWorkspace.shared.open(RecoveryStore.shared.directory) }
            }
            if model.recoveryItems.isEmpty {
                ContentUnavailableView(model.recoveryWarnings.isEmpty ? "Nenhuma cópia de recuperação" : "Nenhuma cópia pronta para recuperar",systemImage:model.recoveryWarnings.isEmpty ? "clock.arrow.circlepath" : "exclamationmark.triangle",description:Text(model.recoveryWarnings.isEmpty ? "Quando houver trabalho recuperável, ele aparecerá aqui." : "Revise os avisos acima. Os arquivos que exigem atenção foram preservados no armazenamento local."))
            } else {
                List(model.recoveryItems) { item in
                    HStack(spacing:12) {
                        Image(systemName:item.encrypted ? "lock.doc" : "doc.badge.clock").font(.title2).foregroundStyle(.secondary).accessibilityHidden(true)
                        VStack(alignment:.leading,spacing:4) {
                            Text(item.title).font(.headline).lineLimit(2)
                            Text(item.modifiedAt,format:.dateTime.day().month().year().hour().minute()).font(.caption).foregroundStyle(.secondary)
                            if let source = item.sourceURL { Text(source.path).font(.caption2).foregroundStyle(.secondary).lineLimit(1) }
                        }
                        Spacer()
                        Button("Recuperar") { pendingRestore = item.id; dismiss() }.accessibilityLabel("Recuperar " + item.title)
                        Button(role:.destructive) { pendingDelete = item.id; confirmDelete = true } label: { Image(systemName:"trash") }
                            .accessibilityLabel("Excluir cópia de recuperação de " + item.title)
                    }.padding(.vertical,6)
                }.listStyle(.inset)
            }
            HStack { Button("Atualizar lista",systemImage:"arrow.clockwise") { model.refreshRecovery() }; Spacer(); Text("\(PortugueseCount.label(model.recoveryItems.count, "cópia local", "cópias locais"))").font(.caption).foregroundStyle(.secondary) }
        }.padding(24).frame(width:720,height:510)
            .onAppear { model.refreshRecovery() }
            .onDisappear { if let id = pendingRestore { model.restoreRecovery(id:id) } }
            .confirmationDialog("Excluir esta cópia de recuperação?",isPresented:$confirmDelete,titleVisibility:.visible) {
                Button("Excluir cópia",role:.destructive) { if let id = pendingDelete { model.deleteRecovery(id:id) }; pendingDelete = nil }
                Button("Cancelar",role:.cancel) { pendingDelete = nil }
            } message: { Text("O arquivo original permanece no local de origem.") }
    }
}
