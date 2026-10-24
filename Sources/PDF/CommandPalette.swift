import SwiftUI

struct AdvancedCommandActions {
    var showPalette: () -> Void
    var execute: (String) -> Void
}
private struct AdvancedCommandKey: FocusedValueKey { typealias Value = AdvancedCommandActions }
extension FocusedValues {
    var advancedCommandActions: AdvancedCommandActions? {
        get { self[AdvancedCommandKey.self] }
        set { self[AdvancedCommandKey.self] = newValue }
    }
}

struct AdvancedCommandMenu: Commands {
    @ObservedObject private var store: AdvancedCustomizationStore
    @ObservedObject private var preferences:AppearancePreferences
    @FocusedValue(\.advancedCommandActions) private var actions
    init(preferences:AppearancePreferences) { store = preferences.advanced; self.preferences = preferences }
    var body: some Commands {
        CommandMenu("Ferramentas") {
            Button("Buscar comandos e ferramentas…") { actions?.showPalette() }
                .configuredShortcut("action:palette",store:store).disabled(actions == nil)
            Divider()
            ForEach(AppearanceState.categories,id:\.self) { category in
                Menu(category) {
                    ForEach(tools.filter { $0.category == category }) { tool in
                        Button(preferences.title(for:tool)) { actions?.execute("tool:"+tool.id) }
                            .configuredShortcut("tool:"+tool.id,store:store).disabled(actions == nil)
                    }
                }
            }
        }
    }
}

struct CommandPaletteView: View {
    @EnvironmentObject private var preferences:AppearancePreferences
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let onSelect:(String)->Void
    @State private var query = ""
    @State private var selected:String?
    @FocusState private var searching:Bool
    private var commands:[PDFCommandDefinition] {
        let words = query.folding(options:[.diacriticInsensitive,.caseInsensitive],locale:.current).split(separator:" ")
        let values = PDFCommandCatalog.all.filter { $0.id != "action:palette" }.filter { command in
            let search = (title(command)+" "+command.title+" "+command.category+" "+command.id).folding(options:[.diacriticInsensitive,.caseInsensitive],locale:.current)
            return words.allSatisfy { search.contains($0) }
        }
        let recent = preferences.advanced.recentCommands
        return values.sorted {
            let left = recent.firstIndex(of:$0.id) ?? Int.max,right = recent.firstIndex(of:$1.id) ?? Int.max
            return left == right ? title($0).localizedStandardCompare(title($1)) == .orderedAscending : left < right
        }
    }
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack { Label("Comandos e ferramentas",systemImage:"command").font(.title2.bold()); Spacer(); Button("Fechar") { dismiss() }.keyboardShortcut(.cancelAction) }
            TextField("Buscar por nome, categoria ou ação",text:$query).textFieldStyle(.roundedBorder).focused($searching)
                .accessibilityIdentifier("pdf.command-palette.search")
                .onSubmit { if let command = commands.first(where:{$0.id == selected}) ?? commands.first { execute(command.id) } }
                .onMoveCommand { direction in move(direction) }
            Text("Todo o catálogo está disponível aqui, inclusive ferramentas ocultas no menu. Use ↑ ↓ e Return.").font(.caption).foregroundStyle(.secondary)
            if commands.isEmpty {
                ContentUnavailableView.search(text:query).frame(maxWidth:.infinity,maxHeight:.infinity)
            } else {
                List(selection:$selected) {
                    ForEach(commands) { command in
                        Button { execute(command.id) } label: {
                            HStack(spacing:12) {
                                Image(systemName:icon(command)).frame(width:24).foregroundStyle(preferences.accent)
                                VStack(alignment:.leading,spacing:3) {
                                    Text(title(command)).fontWeight(.medium)
                                    Text(command.category + (isHidden(command) ? " · Oculta no menu" : "")).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if let shortcut = preferences.advanced.binding(for:command.id) { Text(shortcut.label).font(.caption.monospaced()).foregroundStyle(.secondary) }
                            }.contentShape(Rectangle()).padding(.vertical,4)
                        }.buttonStyle(.plain).tag(command.id)
                            .accessibilityLabel(title(command)).accessibilityHint("Abrir " + command.category)
                            .accessibilityIdentifier("pdf.command."+command.id)
                    }
                }.listStyle(.inset).accessibilityLabel("Resultados de comandos")
            }
            Text("\(commands.count) comandos encontrados").font(.caption).foregroundStyle(.secondary)
        }.padding(22).frame(width:650,height:550).tint(preferences.accent)
            .onAppear { searching = true; selected = commands.first?.id }
            .onChange(of:query) { selected = commands.first?.id }
            .animation(preferences.animation(reduceMotion:reduceMotion),value:query)
    }
    private func title(_ command:PDFCommandDefinition)->String {
        guard command.id.hasPrefix("tool:"),let tool = tools.first(where:{"tool:"+$0.id == command.id}) else { return command.title }
        return preferences.title(for:tool)
    }
    private func icon(_ command:PDFCommandDefinition)->String {
        guard let tool = tools.first(where:{"tool:"+$0.id == command.id}) else { return command.icon }
        return preferences.icon(for:tool)
    }
    private func isHidden(_ command:PDFCommandDefinition)->Bool {
        guard let tool = tools.first(where:{"tool:"+$0.id == command.id}) else { return false }
        return preferences.state.hiddenTools.contains(tool.id) || preferences.state.hiddenCategories.contains(tool.category)
    }
    private func execute(_ id:String) { preferences.advanced.record(id); dismiss(); onSelect(id) }
    private func move(_ direction:MoveCommandDirection) {
        guard direction == .up || direction == .down,!commands.isEmpty else { return }
        let index = commands.firstIndex(where:{$0.id == selected}) ?? 0
        selected = commands[min(commands.count-1,max(0,index+(direction == .up ? -1 : 1)))].id
    }
}

struct AdvancedShortcutControls: View {
    @ObservedObject var store:AdvancedCustomizationStore
    @State private var query = ""
    @State private var editing:String?
    @State private var key = ""
    @State private var shift = false
    @State private var option = false
    @State private var control = false
    @State private var message = ""
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            Text("Atalhos de comandos e ferramentas").font(.headline)
            Text("As alterações valem nos menus e na paleta. Command é obrigatório; os atalhos de edição de texto e do macOS permanecem reservados. Um atalho não pode ter duas ações.").font(.caption).foregroundStyle(.secondary)
            TextField("Encontrar ação",text:$query).textFieldStyle(.roundedBorder)
            if !message.isEmpty { Text(message).font(.callout).foregroundStyle(.secondary).accessibilityIdentifier("pdf.shortcuts.feedback") }
            ForEach(PDFCommandCatalog.all.filter { query.isEmpty || $0.title.localizedStandardContains(query) || $0.category.localizedStandardContains(query) }) { command in
                VStack(alignment:.leading,spacing:9) {
                    HStack { Label(command.title,systemImage:command.icon); Spacer(); Text(store.binding(for:command.id)?.label ?? "Sem atalho").font(.callout.monospaced()); Button("Editar") { edit(command.id) }.accessibilityLabel("Editar atalho de "+command.title) }
                    if editing == command.id {
                        HStack {
                            Text("⌘").font(.title3)
                            Toggle("Shift",isOn:$shift); Toggle("Option",isOn:$option); Toggle("Control",isOn:$control)
                            TextField("Tecla",text:$key).frame(width:90).textFieldStyle(.roundedBorder)
                        }
                        HStack {
                            Text("Use left ou right para as setas.").font(.caption).foregroundStyle(.secondary)
                            Spacer(); Button("Remover") { assign(nil,id:command.id) }
                            Button("Salvar atalho") { var mods = ["command"]; if shift { mods.append("shift") }; if option { mods.append("option") }; if control { mods.append("control") }; assign(.init(key:key.trimmingCharacters(in:.whitespacesAndNewlines),modifiers:mods),id:command.id) }
                        }
                    }
                }.padding(12).background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12))
            }
            Button("Restaurar todos os atalhos padrão") { store.restoreBindings(); editing = nil; message = "Atalhos padrão restaurados." }
            if !store.loadWarning.isEmpty { Text(store.loadWarning).font(.caption).foregroundStyle(.secondary) }
        }
    }
    private func edit(_ id:String) { editing = id; let value = store.binding(for:id); key = value?.key ?? ""; shift = value?.modifiers.contains("shift") ?? false; option = value?.modifiers.contains("option") ?? false; control = value?.modifiers.contains("control") ?? false; message = "" }
    private func assign(_ value:PDFKeyboardBinding?,id:String) { do { try store.assign(value,to:id); editing = nil; message = value == nil ? "Atalho removido." : "Atalho atualizado." } catch { message = error.localizedDescription } }
}

struct WorkspaceProfileControls:View {
    @ObservedObject var store:AdvancedCustomizationStore
    @ObservedObject var preferences:AppearancePreferences
    @State private var name = ""
    @State private var message = ""
    @State private var replacing:PDFWorkspaceProfile?
    var body:some View {
        VStack(alignment:.leading,spacing:16) {
            Text("Espaços de trabalho para cada tarefa").font(.headline)
            Text("Guarde aparência, menus, ordem das ferramentas, atalhos, opções do leitor e preferências de saída. Aplicar um perfil mantém os documentos, páginas de leitura, zoom, histórico e cópias de recuperação. O zoom do perfil vale para novas abas; os controles do leitor ajustam a aba ativa.").font(.caption).foregroundStyle(.secondary)
            HStack { TextField("Nome do novo perfil",text:$name).textFieldStyle(.roundedBorder); Button("Guardar ajustes atuais") { save(name:name) }.disabled(name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty) }
            if !message.isEmpty { Text(message).font(.callout).foregroundStyle(.secondary) }
            ForEach(store.profiles) { profile in
                HStack {
                    VStack(alignment:.leading,spacing:4) { Text(profile.name).fontWeight(.semibold); Text(profile.modified,style:.date).font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                    Button("Aplicar") { do { try preferences.importData(profile.settings); message = "Perfil \(profile.name) aplicado." } catch { message = error.localizedDescription } }.accessibilityLabel("Aplicar perfil "+profile.name)
                    Menu { Button("Atualizar com os ajustes atuais") { replacing = profile }; Button("Excluir perfil",role:.destructive) { store.deleteProfile(profile.id) } } label:{ Image(systemName:"ellipsis.circle") }.accessibilityLabel("Opções do perfil "+profile.name)
                }.padding(12).background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12))
            }
            if store.profiles.isEmpty { Text("Crie, por exemplo, perfis para leitura, revisão, digitalização e produção.").foregroundStyle(.secondary) }
        }.confirmationDialog("Substituir os ajustes do perfil?",isPresented:Binding(get:{replacing != nil},set:{if !$0 { replacing = nil }}),titleVisibility:.visible) {
            if let profile = replacing { Button("Atualizar \(profile.name)") { save(name:profile.name,id:profile.id); replacing = nil } }
            Button("Cancelar",role:.cancel) { replacing = nil }
        }
    }
    private func save(name:String,id:UUID? = nil) { do { try store.saveProfile(name:name,settings:preferences.exportData(),replacing:id); self.name = ""; message = "Perfil guardado neste Mac." } catch { message = error.localizedDescription } }
}
