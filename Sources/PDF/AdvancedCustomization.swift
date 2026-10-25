import SwiftUI
import AppKit

struct PDFKeyboardBinding: Codable, Equatable, Hashable {
    var key: String
    var modifiers: [String] = ["command"]
    var normalized: PDFKeyboardBinding {
        var normalizedKey = key.lowercased(),flags = Set(modifiers)
        let shifted = Dictionary(uniqueKeysWithValues:zip(Array("~!@#$%^&*()_+{}|:\"<>?"),Array("`1234567890-=[]\\;',./")).map { pair in (String(pair.0),String(pair.1)) })
        if let base = shifted[normalizedKey] { normalizedKey = base; flags.insert("shift") }
        return .init(key:normalizedKey,modifiers:Array(flags).sorted())
    }
    var eventModifiers: EventModifiers {
        var value: EventModifiers = []
        if modifiers.contains("command") { value.insert(.command) }
        if modifiers.contains("shift") { value.insert(.shift) }
        if modifiers.contains("option") { value.insert(.option) }
        if modifiers.contains("control") { value.insert(.control) }
        return value
    }
    var equivalent: KeyEquivalent {
        switch key { case "left": return .leftArrow; case "right": return .rightArrow; default: return KeyEquivalent(key.first ?? " ") }
    }
    var label: String {
        (modifiers.contains("control") ? "⌃" : "") + (modifiers.contains("option") ? "⌥" : "") +
        (modifiers.contains("shift") ? "⇧" : "") + (modifiers.contains("command") ? "⌘" : "") +
        (["left":"←", "right":"→"][key] ?? key.uppercased())
    }
    func validate() throws {
        let validKey = (key.count == 1 && key.unicodeScalars.allSatisfy { (33...126).contains(Int($0.value)) }) || ["left", "right"].contains(key)
        guard validKey, modifiers.contains("command"), Set(modifiers).isSubset(of: ["command", "shift", "option", "control"]), Set(modifiers).count == modifiers.count else {
            throw PreferenceError.invalid("Use uma letra, número, símbolo ou seta e inclua Command. Cada modificador deve aparecer uma única vez.")
        }
    }
}

struct PDFCommandDefinition: Identifiable {
    var id: String
    var title: String
    var category: String
    var icon: String
    var defaultBinding: PDFKeyboardBinding?
}

enum PDFCommandCatalog {
    static var all: [PDFCommandDefinition] {
        let definitions: [(String,String,String,String,[String])] = [
            ("palette","Buscar comandos e ferramentas","command","k",["command","shift"]),
            ("open","Abrir PDF","folder","o",["command"]), ("new-tab","Abrir PDF em nova aba","plus","t",["command"]),
            ("close-tab","Fechar aba atual","xmark","w",["command"]), ("save","Salvar cópia","square.and.arrow.down","s",["command","shift"]),
            ("print","Imprimir","printer","p",["command"]), ("search","Buscar no documento ou catálogo","magnifyingglass","f",["command"]),
            ("find-next","Próxima ocorrência","text.magnifyingglass","g",["command"]), ("page","Ir para página","number","l",["command"]),
            ("previous-tab","Aba anterior","chevron.left","[",["command","shift"]), ("next-tab","Próxima aba","chevron.right","]",["command","shift"]),
            ("recovery","Recuperar trabalho","clock.arrow.circlepath","t",["command","shift"]),
            ("previous-page","Página anterior","chevron.left","left",["command"]), ("next-page","Próxima página","chevron.right","right",["command"]),
            ("highlight","Realçar seleção","highlighter","h",["command","shift"]), ("bookmark","Marcar página","bookmark","d",["command","shift"]),
            ("inspector","Editar anotações","pencil","i",["command","shift"]),
            ("undo-annotation","Desfazer anotação","arrow.uturn.backward","z",["command","option"]),
            ("redo-annotation","Refazer anotação","arrow.uturn.forward","z",["command","option","shift"]),
            ("sidebar","Mostrar páginas e sumário","sidebar.left","s",["command","option"]),
            ("share","Compartilhar documento","square.and.arrow.up","s",["command","control"])
        ]
        return definitions.map { PDFCommandDefinition(id:"action:"+$0.0,title:$0.1,category:"Comandos",icon:$0.2,defaultBinding:.init(key:$0.3,modifiers:$0.4)) } +
            [PDFCommandDefinition(id:"action:rotate",title:"Girar página atual",category:"Comandos",icon:"rotate.right",defaultBinding:nil)] +
            tools.map { PDFCommandDefinition(id:"tool:"+$0.id,title:$0.name,category:$0.category,icon:$0.icon,defaultBinding:nil) }
    }
    static var reserved: Set<PDFKeyboardBinding> {
        var keys = ["q","h","m",",","z","y","x","c","v","a"].map { PDFKeyboardBinding(key:$0).normalized }
        keys += [PDFKeyboardBinding(key:"z",modifiers:["command","shift"]),PDFKeyboardBinding(key:"h",modifiers:["command","option"]),PDFKeyboardBinding(key:"m",modifiers:["command","option"])]
        return Set(keys.map(\.normalized))
    }
}

struct PDFWorkspaceProfile: Codable, Identifiable {
    var id = UUID()
    var name: String
    var settings: Data
    var modified = Date()
}
struct PDFWorkspaceProfilesSnapshot:Codable {
    var version = 1
    var profiles:[PDFWorkspaceProfile]
}
enum PDFProfileConflictPolicy:Equatable { case keepBoth, replaceMatchingIdentifiers }

@MainActor final class AdvancedCustomizationStore: ObservableObject {
    static let bindingKey = "PDF.CommandBindings.v1"
    static let profileKey = "PDF.WorkspaceProfiles.v1"
    static let menuKey = "PDF.CommandMenus.v1"
    @Published private(set) var bindings: [String:PDFKeyboardBinding] = [:]
    @Published private(set) var disabled: [String] = []
    @Published private(set) var profiles: [PDFWorkspaceProfile] = []
    @Published private(set) var menu = PDFMenuSnapshot()
    @Published private(set) var recentCommands: [String] = []
    @Published private(set) var loadWarning = ""
    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey:Self.bindingKey) {
            do { let value = try JSONDecoder().decode(PDFShortcutSnapshot.self,from:data); try Self.validate(value); bindings = value.bindings; disabled = value.disabled }
            catch { loadWarning = "Os atalhos salvos não puderam ser carregados: " + error.localizedDescription }
        }
        if let data = defaults.data(forKey:Self.profileKey),data.count <= 8_388_608 {
            do {
                let values = try JSONDecoder().decode([PDFWorkspaceProfile].self,from:data)
                guard values.count <= 30,Set(values.map(\.id)).count == values.count else { throw PreferenceError.invalid("Biblioteca de perfis inválida.") }
                profiles = try values.map(Self.canonicalProfile)
            } catch { loadWarning = "Os perfis salvos não puderam ser carregados: " + error.localizedDescription }
        }
        if let data = defaults.data(forKey:Self.menuKey) {
            do {
                guard data.count <= 65_536 else { throw PreferenceError.invalid("A organização dos menus excede 64 KB.") }
                let value = try JSONDecoder().decode(PDFMenuSnapshot.self, from:data)
                try value.validate(); menu = value
            } catch { loadWarning = "Os menus salvos não puderam ser carregados: " + error.localizedDescription }
        }
    }
    var snapshot: PDFShortcutSnapshot { .init(bindings:bindings,disabled:disabled) }
    func binding(for id:String) -> PDFKeyboardBinding? {
        guard !disabled.contains(id) else { return nil }
        return bindings[id] ?? PDFCommandCatalog.all.first(where:{$0.id == id})?.defaultBinding
    }
    static func validate(_ snapshot: PDFShortcutSnapshot) throws {
        let catalog = PDFCommandCatalog.all, valid = Set(catalog.map(\.id))
        guard Set(snapshot.bindings.keys).isSubset(of:valid),Set(snapshot.disabled).isSubset(of:valid),Set(snapshot.disabled).count == snapshot.disabled.count else { throw PreferenceError.invalid("O arquivo contém um comando desconhecido ou repetido.") }
        for binding in snapshot.bindings.values { try binding.validate() }
        var owners: [PDFKeyboardBinding:String] = [:]
        for command in catalog where !snapshot.disabled.contains(command.id) {
            guard let binding = snapshot.bindings[command.id] ?? command.defaultBinding else { continue }
            try binding.validate()
            let key = binding.normalized
            guard !PDFCommandCatalog.reserved.contains(key) else { throw PreferenceError.invalid("\(binding.label) é reservado para o macOS ou a edição de texto.") }
            if let other = owners[key] { throw PreferenceError.invalid("\(binding.label) já está atribuído a \(other).") }
            owners[key] = command.title
        }
    }
    func apply(_ snapshot: PDFShortcutSnapshot) throws {
        try Self.validate(snapshot)
        bindings = snapshot.bindings.mapValues(\.normalized); disabled = snapshot.disabled
        persistBindings()
    }
    func assign(_ binding:PDFKeyboardBinding?,to id:String) throws {
        var candidate = snapshot
        candidate.bindings.removeValue(forKey:id); candidate.disabled.removeAll { $0 == id }
        if let binding { candidate.bindings[id] = binding.normalized } else { candidate.disabled.append(id) }
        try apply(candidate)
    }
    func restoreBindings() { bindings = [:]; disabled = []; persistBindings() }
    func applyMenu(_ value: PDFMenuSnapshot) throws {
        try value.validate()
        let data = try JSONEncoder().encode(value)
        guard data.count <= 65_536 else { throw PreferenceError.invalid("A organização dos menus excede 64 KB.") }
        defaults.set(data,forKey:Self.menuKey); menu = value
    }
    private func persistBindings() { if let data = try? JSONEncoder().encode(snapshot) { defaults.set(data,forKey:Self.bindingKey) } }
    func record(_ id:String) { recentCommands.removeAll { $0 == id }; recentCommands.insert(id,at:0); recentCommands = Array(recentCommands.prefix(20)) }
    private static func validateProfile(_ profile:PDFWorkspaceProfile) throws -> CustomizationSnapshot {
        guard !profile.name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,profile.name.count <= 80,profile.settings.count <= 1_048_576 else { throw PreferenceError.invalid("Use um nome de perfil com até 80 caracteres e ajustes de até 1 MB.") }
        var snapshot = try JSONDecoder().decode(CustomizationSnapshot.self,from:profile.settings)
        try snapshot.appearance.validate(); try snapshot.reader.validate()
        if let shortcuts = snapshot.shortcuts { try validate(shortcuts) }
        if let output = snapshot.output { try output.validate() }
        if let menu = snapshot.menu { try menu.validate() }
        return snapshot
    }
    private static func canonicalProfile(_ profile:PDFWorkspaceProfile) throws -> PDFWorkspaceProfile {
        let snapshot = try validateProfile(profile)
        var value = profile
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        value.settings = try encoder.encode(snapshot)
        return value
    }
    func saveProfile(name:String,settings:Data,replacing id:UUID? = nil) throws {
        var value = PDFWorkspaceProfile(name:name.trimmingCharacters(in:.whitespacesAndNewlines),settings:settings)
        if let id { value.id = id }
        value = try Self.canonicalProfile(value)
        guard !profiles.contains(where:{$0.id != value.id && $0.name.localizedCaseInsensitiveCompare(value.name) == .orderedSame}) else { throw PreferenceError.invalid("Já existe um perfil com esse nome.") }
        var candidate = profiles
        if let index = candidate.firstIndex(where:{$0.id == value.id}) { candidate[index] = value } else { candidate.append(value) }
        guard candidate.count <= 30 else { throw PreferenceError.invalid("Guarde no máximo 30 perfis. Remova um perfil para continuar.") }
        let data = try JSONEncoder().encode(candidate)
        guard data.count <= 8_388_608 else { throw PreferenceError.invalid("A biblioteca de perfis excede 8 MB.") }
        defaults.set(data,forKey:Self.profileKey); profiles = candidate
    }
    func deleteProfile(_ id:UUID) { profiles.removeAll { $0.id == id }; if let data = try? JSONEncoder().encode(profiles) { defaults.set(data,forKey:Self.profileKey) } }
    func exportProfiles() throws -> Data {
        try JSONEncoder().encode(PDFWorkspaceProfilesSnapshot(profiles:profiles.map(Self.canonicalProfile)))
    }
    static func decodeProfiles(_ data:Data) throws -> PDFWorkspaceProfilesSnapshot {
        guard data.count <= 8_388_608 else { throw PreferenceError.invalid("O arquivo de perfis excede 8 MB.") }
        var value = try JSONDecoder().decode(PDFWorkspaceProfilesSnapshot.self,from:data)
        guard value.version == 1,value.profiles.count <= 30,Set(value.profiles.map(\.id)).count == value.profiles.count else { throw PreferenceError.invalid("O conjunto de perfis é inválido.") }
        value.profiles = try value.profiles.map(Self.canonicalProfile)
        return value
    }
    func importProfiles(_ data:Data,policy:PDFProfileConflictPolicy) throws {
        let incoming = try Self.decodeProfiles(data)
        var candidate = profiles
        for var item in incoming.profiles {
            let match = candidate.firstIndex(where:{$0.id == item.id})
            if let match,candidate[match].settings == item.settings,candidate[match].name == item.name { continue }
            if match != nil && policy == .keepBoth { item.id = UUID() }
            let target = policy == .replaceMatchingIdentifiers ? match : nil
            let base = item.name
            var suffix = 1
            while candidate.enumerated().contains(where:{$0.offset != target && $0.element.name.localizedCaseInsensitiveCompare(item.name) == .orderedSame}) {
                item.name = String(base.prefix(60))+" (recebido \(suffix))"; suffix += 1
            }
            if let target { candidate[target] = item } else { candidate.append(item) }
        }
        guard candidate.count <= 30 else { throw PreferenceError.invalid("A união ultrapassa 30 perfis. Remova perfis locais ou escolha substituir os identificadores em conflito.") }
        let bytes = try JSONEncoder().encode(candidate)
        guard bytes.count <= 8_388_608 else { throw PreferenceError.invalid("A união de perfis excede 8 MB.") }
        defaults.set(bytes,forKey:Self.profileKey); profiles = candidate
    }
}

struct PDFShortcutSnapshot: Codable { var bindings:[String:PDFKeyboardBinding]; var disabled:[String] }
struct PDFOutputPreferencesSnapshot: Codable {
    var filenameTemplate:String
    var prefix:String
    var directory:String
    init(defaults:UserDefaults) {
        filenameTemplate = defaults.string(forKey:"outputFilenameTemplate") ?? ""
        prefix = defaults.string(forKey:"outputPrefix") ?? "PDF-resultado"
        directory = defaults.string(forKey:"outputDirectory") ?? ""
    }
    func validate() throws {
        guard filenameTemplate.count <= 500,prefix.count <= 200,directory.count <= 4096,!filenameTemplate.contains("\0"),!prefix.contains("\0"),!directory.contains("\0") else { throw PreferenceError.invalid("As preferências de saída excedem os limites permitidos.") }
    }
    func apply(to defaults:UserDefaults) { defaults.set(filenameTemplate,forKey:"outputFilenameTemplate"); defaults.set(prefix,forKey:"outputPrefix"); defaults.set(directory,forKey:"outputDirectory") }
}

extension View {
    @ViewBuilder func configuredShortcut(_ id:String,store:AdvancedCustomizationStore) -> some View {
        if let binding = store.binding(for:id) { keyboardShortcut(binding.equivalent,modifiers:binding.eventModifiers) } else { self }
    }
}
