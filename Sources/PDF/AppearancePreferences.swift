import SwiftUI
import AppKit

struct SidebarCustomization:Codable,Identifiable,Equatable {
    var id:String
    var label:String
    var icon:String
    var visible = true
}

struct AppearanceState:Codable,Equatable {
    var version = 1
    var layout = "grid"
    var density = "comfortable"
    var cardWidth = 220.0
    var fontSize = 13.0
    var iconSize = 22.0
    var showDetails = true
    var showCategoryLabels = false
    var groupByCategory = false
    var showHero = true
    var showRecent = true
    var accentHex = "#007AFF"
    var colorScheme = "system"
    var glassStyle = "glass"
    var glassTransparency = 0.65
    var backgroundStyle = "gradient"
    var animationsEnabled = true
    var animationStyle = "gentle"
    var animationDuration = 0.25
    var hoverScale = 1.025
    var sidebarStyle = "both"
    var sidebarWidth = 210.0
    var sidebar:[SidebarCustomization] = Self.defaultSidebar
    var toolOrder:[String] = []
    var hiddenTools:[String] = []
    var hiddenCategories:[String] = []
    var favorites:[String] = ["merge","ocr","word"]
    var toolTitles:[String:String] = [:]
    var toolIcons:[String:String] = [:]
    static let categories = ["Organizar","Converter","Editar","Proteger","Capturar","Inteligência","Automatizar","Compartilhar","Produção"]
    static let defaultSidebar = [
        SidebarCustomization(id:"Início",label:"Início",icon:"square.grid.2x2"),
        SidebarCustomization(id:"Leitor",label:"Leitor",icon:"book"),
        SidebarCustomization(id:"Favoritos",label:"Favoritos",icon:"star"),
        SidebarCustomization(id:"Digitalizar",label:"Digitalizar",icon:"scanner"),
        SidebarCustomization(id:"Inteligência",label:"Inteligência",icon:"sparkles"),
        SidebarCustomization(id:"Fluxos",label:"Fluxos",icon:"arrow.triangle.branch")
    ]
    var spacing:Double { density == "compact" ? 8 : density == "spacious" ? 22 : 14 }
    var padding:Double { density == "compact" ? 12 : density == "spacious" ? 24 : 18 }
    var cardMinHeight:Double { (showDetails ? 144 : 104) + padding + max(0,fontSize-13)*5 + max(0,iconSize-22) }
    mutating func validate() throws {
        guard version == 1 else { throw PreferenceError.invalid("Versão de personalização incompatível.") }
        let choices:[(String,[String])] = [(layout,["grid","list"]),(density,["compact","comfortable","spacious"]),(colorScheme,["system","light","dark"]),(glassStyle,["glass","frosted","opaque"]),(backgroundStyle,["gradient","plain"]),(animationStyle,["gentle","spring","quick"]),(sidebarStyle,["both","icons","labels"])]
        guard choices.allSatisfy({ $0.1.contains($0.0) }), AppearanceColor.isValid(accentHex) else { throw PreferenceError.invalid("A personalização contém uma opção ou cor inválida.") }
        let ranges:[(Double,ClosedRange<Double>)] = [(cardWidth,180...380),(fontSize,11...20),(iconSize,16...40),(glassTransparency,0...0.9),(animationDuration,0.1...0.8),(hoverScale,1...1.07),(sidebarWidth,190...320)]
        guard ranges.allSatisfy({ $0.0.isFinite && $0.1.contains($0.0) }) else { throw PreferenceError.invalid("Um ajuste visual está fora do intervalo permitido.") }
        let validSidebar = Set(Self.defaultSidebar.map(\.id))
        guard Set(sidebar.map(\.id)) == validSidebar,sidebar.count == validSidebar.count,sidebar.first(where:{$0.id == "Início"})?.visible == true else { throw PreferenceError.invalid("A navegação deve conter todas as seções e manter Início visível.") }
        guard sidebar.allSatisfy({ !$0.label.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && $0.label.count <= 40 && NSImage(systemSymbolName:$0.icon,accessibilityDescription:nil) != nil }) else { throw PreferenceError.invalid("Há um nome ou ícone de navegação inválido.") }
        let validTools = Set(tools.map(\.id))
        var seen = Set<String>()
        toolOrder = toolOrder.filter { validTools.contains($0) && seen.insert($0).inserted }
        func unique(_ values:[String],allowed:Set<String>) -> [String] {
            var seen = Set<String>()
            return values.filter { allowed.contains($0) && seen.insert($0).inserted }
        }
        hiddenTools = unique(hiddenTools,allowed:validTools)
        favorites = unique(favorites,allowed:validTools)
        hiddenCategories = unique(hiddenCategories,allowed:Set(Self.categories))
        toolTitles = toolTitles.filter { validTools.contains($0.key) && !$0.value.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && $0.value.count <= 60 }
        toolIcons = toolIcons.filter { validTools.contains($0.key) && NSImage(systemSymbolName:$0.value,accessibilityDescription:nil) != nil }
    }
}
enum PreferenceError:LocalizedError {
    case invalid(String)
    var errorDescription:String? { if case .invalid(let value) = self { return value }; return nil }
}

@MainActor final class AppearancePreferences:ObservableObject {
    static let shared = AppearancePreferences()
    static let storageKey = "PDF.Appearance.v1"
    @Published var state:AppearanceState { didSet { persist() } }
    let advanced:AdvancedCustomizationStore
    init(defaults:UserDefaults = .standard) {
        self.defaults = defaults
        advanced = AdvancedCustomizationStore(defaults:defaults)
        if let data = defaults.data(forKey:Self.storageKey),var decoded = try? JSONDecoder().decode(AppearanceState.self,from:data),(try? decoded.validate()) != nil { state = decoded }
        else {
            var initial = AppearanceState()
            initial.showRecent = defaults.object(forKey:"showRecent") as? Bool ?? true
            if defaults.bool(forKey:"compact") { initial.density = "compact" }
            initial.colorScheme = ["Escuro":"dark","Claro":"light"][defaults.string(forKey:"appearance") ?? ""] ?? "system"
            initial.accentHex = ["Violeta":"#AF52DE","Verde":"#248A3D","Laranja":"#D76B00"][defaults.string(forKey:"accent") ?? ""] ?? "#007AFF"
            if let value = defaults.string(forKey:"favorites") { initial.favorites = value.split(separator:",").map(String.init) }
            initial.toolOrder = (defaults.string(forKey:"toolOrder") ?? "").split(separator:",").map(String.init)
            initial.hiddenTools = (defaults.string(forKey:"hiddenTools") ?? "").split(separator:",").map(String.init)
            try? initial.validate()
            state = initial
        }
    }
    private let defaults:UserDefaults
    private func persist() { if let data = try? JSONEncoder().encode(state) { defaults.set(data,forKey:Self.storageKey) } }
    var accent:Color { AppearanceColor.color(state.accentHex) }
    var preferredScheme:ColorScheme? { state.colorScheme == "dark" ? .dark : state.colorScheme == "light" ? .light : nil }
    func title(for tool:Tool) -> String { state.toolTitles[tool.id] ?? tool.name }
    func icon(for tool:Tool) -> String { state.toolIcons[tool.id] ?? tool.icon }
    func orderedTools() -> [Tool] {
        let lookup = Dictionary(uniqueKeysWithValues: tools.map { ($0.id, $0) })
        var seen = Set<String>()
        // Persisted IDs define a relative order. New catalog entries follow in
        // catalog order; removed/duplicate IDs never shift another tool's identity.
        return (state.toolOrder + tools.map(\.id)).compactMap { id in
            guard let tool = lookup[id], seen.insert(id).inserted else { return nil }
            return tool
        }
    }
    func moveTool(_ id:String,before target:String) {
        var order = orderedTools().map(\.id)
        guard id != target,order.contains(id),order.contains(target) else { return }
        order.removeAll { $0 == id }
        guard let index = order.firstIndex(of:target) else { return }
        order.insert(id,at:index); state.toolOrder = order
    }
    func moveSidebar(_ id:String,before target:String) {
        guard id != target,let item = state.sidebar.first(where:{$0.id == id}),state.sidebar.contains(where:{$0.id == target}) else { return }
        var order = state.sidebar.filter { $0.id != id }
        guard let index = order.firstIndex(where:{$0.id == target}) else { return }
        order.insert(item,at:index); state.sidebar = order
    }
    func animation(reduceMotion:Bool) -> Animation? {
        guard state.animationsEnabled,!reduceMotion else { return nil }
        switch state.animationStyle {
        case "spring": return .spring(response:state.animationDuration*1.8,dampingFraction:0.82)
        case "quick": return .easeOut(duration:state.animationDuration*0.7)
        default: return .easeInOut(duration:state.animationDuration)
        }
    }
    func reset() { state = AppearanceState() }
    func resetReader() {
        for key in ["readerMode","readerDirection","readerDisplayBox","readerPageBackground","readerAutoScale","readerZoom","readerDisplayPageBreaks","readerSidebar","readerShowAnnotations","readerHiddenToolbar","readerHiddenAnnotations","readerHighlightColor","readerNoteColor","readerInkColor","readerInkWidth","readerShowTabs","readerSplitDirection"] { defaults.removeObject(forKey:key) }
    }
    func exportData() throws -> Data {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted,.sortedKeys]
        return try encoder.encode(CustomizationSnapshot(appearance:state,reader:ReaderSettingsSnapshot(defaults:defaults),shortcuts:advanced.snapshot,output:PDFOutputPreferencesSnapshot(defaults:defaults)))
    }
    func importData(_ data:Data) throws {
        guard data.count <= 1_048_576 else { throw PreferenceError.invalid("O arquivo de personalização é muito grande.") }
        var snapshot = try JSONDecoder().decode(CustomizationSnapshot.self,from:data)
        try snapshot.appearance.validate(); try snapshot.reader.validate()
        if let shortcuts = snapshot.shortcuts { try AdvancedCustomizationStore.validate(shortcuts) }
        if let output = snapshot.output { try output.validate() }
        state = snapshot.appearance; snapshot.reader.apply(to:defaults)
        if let shortcuts = snapshot.shortcuts { try advanced.apply(shortcuts) }
        snapshot.output?.apply(to:defaults)
    }
    func applyPreset(_ preset:String) {
        var value = state
        switch preset {
        case "focus": value.layout = "list"; value.density = "compact"; value.showDetails = false; value.showHero = false; value.glassStyle = "opaque"; value.backgroundStyle = "plain"; value.animationsEnabled = false
        case "comfortable": value.layout = "grid"; value.density = "spacious"; value.fontSize = 16; value.iconSize = 28; value.cardWidth = 280; value.showDetails = true; value.showHero = true; value.glassStyle = "frosted"
        default: value.layout = "grid"; value.density = "comfortable"; value.fontSize = 13; value.iconSize = 22; value.cardWidth = 220; value.showDetails = true; value.showHero = true; value.glassStyle = "glass"; value.backgroundStyle = "gradient"; value.animationsEnabled = true
        }
        state = value
    }
}

enum AppearanceColor {
    static func isValid(_ string:String) -> Bool { string.range(of:"^#[0-9a-fA-F]{6}$",options:.regularExpression) != nil }
    static func color(_ string:String) -> Color {
        guard isValid(string),let number = UInt32(string.dropFirst(),radix:16) else { return .accentColor }
        return Color(red:Double((number >> 16) & 255)/255,green:Double((number >> 8) & 255)/255,blue:Double(number & 255)/255)
    }
    static func hex(_ color:Color) -> String {
        guard let rgb = NSColor(color).usingColorSpace(.sRGB) else { return "#007AFF" }
        func byte(_ component:CGFloat) -> Int { Int((min(1,max(0,component))*255).rounded()) }
        return String(format:"#%02X%02X%02X",byte(rgb.redComponent),byte(rgb.greenComponent),byte(rgb.blueComponent))
    }
}

struct AdaptiveSurface:ViewModifier {
    @EnvironmentObject private var preferences:AppearancePreferences
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    func body(content:Content) -> some View {
        let state = preferences.state
        if reduceTransparency || state.glassStyle == "opaque" {
            content.background(Color(nsColor:.controlBackgroundColor),in:RoundedRectangle(cornerRadius:20))
        } else if state.glassStyle == "frosted" {
            content.background(Color(nsColor:.controlBackgroundColor).opacity(1-state.glassTransparency),in:RoundedRectangle(cornerRadius:20))
                .background(.ultraThinMaterial,in:RoundedRectangle(cornerRadius:20))
        } else {
            content.background(Color(nsColor:.controlBackgroundColor).opacity(1-state.glassTransparency),in:RoundedRectangle(cornerRadius:20))
                .glassEffect(.regular,in:.rect(cornerRadius:20))
        }
    }
}

struct CustomizableToolCard:View {
    let tool:Tool
    var favorite:Bool
    var row = false
    var open:()->Void
    var toggleFavorite:()->Void
    @EnvironmentObject private var preferences:AppearancePreferences
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovered = false
    var body:some View {
        let state = preferences.state
        ZStack(alignment:row ? .trailing : .topTrailing) {
            Button(action:open) {
                Group {
                    if row {
                        HStack(spacing:state.spacing+6) { symbol; copy; Spacer(minLength:35) }.padding(state.padding)
                    } else {
                        VStack(alignment:.leading,spacing:12) { symbol; copy; Spacer(minLength:0) }
                            .padding(state.padding).frame(maxWidth:.infinity,alignment:.leading).frame(minHeight:state.cardMinHeight,alignment:.top)
                    }
                }.contentShape(RoundedRectangle(cornerRadius:20)).modifier(AdaptiveSurface())
                    .overlay(RoundedRectangle(cornerRadius:20).strokeBorder(hovered ? preferences.accent.opacity(0.4) : Color.primary.opacity(0.08),lineWidth:hovered ? 1.25 : 0.75))
            }.buttonStyle(.plain)
                .accessibilityLabel(preferences.title(for:tool)).accessibilityHint(tool.detail)
                .accessibilityIdentifier("pdf.tool." + tool.id)
            Button(action:toggleFavorite) { Image(systemName:favorite ? "star.fill" : "star").foregroundStyle(favorite ? preferences.accent : Color.secondary).frame(width:30,height:30).contentShape(Rectangle()) }
                .buttonStyle(.plain).padding(12)
                .accessibilityLabel((favorite ? "Remover " : "Adicionar ") + preferences.title(for:tool) + (favorite ? " dos favoritos" : " aos favoritos"))
                .accessibilityIdentifier("pdf.favorite." + tool.id)
                .help(favorite ? "Remover dos favoritos" : "Adicionar aos favoritos")
        }.accessibilityElement(children:.contain)
        .scaleEffect(hovered && state.animationsEnabled && !reduceMotion ? state.hoverScale : 1)
        .onHover { hovered = $0 }
        .animation(preferences.animation(reduceMotion:reduceMotion),value:hovered)
    }
    var symbol:some View {
        let size = preferences.state.iconSize
        return Image(systemName:preferences.icon(for:tool)).font(.system(size:size,weight:.medium)).foregroundStyle(preferences.accent)
            .frame(width:size+18,height:size+18).background(preferences.accent.opacity(0.12),in:RoundedRectangle(cornerRadius:12)).accessibilityHidden(true)
    }
    var copy:some View {
        VStack(alignment:.leading,spacing:7) {
            Text(preferences.title(for:tool)).font(.system(size:preferences.state.fontSize,weight:.semibold)).foregroundStyle(.primary).fixedSize(horizontal:false,vertical:true)
            if preferences.state.showDetails { Text(tool.detail).font(.system(size:max(10,preferences.state.fontSize-2))).foregroundStyle(.secondary).fixedSize(horizontal:false,vertical:true) }
            if preferences.state.showCategoryLabels { Text(tool.category).font(.system(size:max(9,preferences.state.fontSize-3),weight:.medium)).foregroundStyle(preferences.accent) }
        }.frame(maxWidth:.infinity,alignment:.leading)
    }
}


struct CustomizationSnapshot:Codable {
    var appearance:AppearanceState
    var reader:ReaderSettingsSnapshot
    var shortcuts:PDFShortcutSnapshot? = nil
    var output:PDFOutputPreferencesSnapshot? = nil
}
struct ReaderSettingsSnapshot:Codable {
    var mode:Int
    var direction:String
    var displayBox:String
    var background:String
    var autoScale:Bool
    var zoom:Double
    var pageBreaks:Bool
    var sidebar:Bool
    var annotations:Bool
    var hiddenToolbar:String
    var hiddenAnnotations:String
    // Optional fields preserve decoding of version-1 exports made before annotation styling.
    var highlightColor:String?
    var noteColor:String?
    var inkColor:String?
    var inkWidth:Double?
    var showTabs:Bool?
    var splitDirection:String?
    init(defaults:UserDefaults = .standard) {
        mode = defaults.integer(forKey:"readerMode")
        direction = defaults.string(forKey:"readerDirection") ?? "vertical"
        displayBox = defaults.string(forKey:"readerDisplayBox") ?? "crop"
        background = defaults.string(forKey:"readerPageBackground") ?? "#E8E9EF"
        autoScale = defaults.object(forKey:"readerAutoScale") as? Bool ?? true
        zoom = defaults.object(forKey:"readerZoom") as? Double ?? 1
        pageBreaks = defaults.object(forKey:"readerDisplayPageBreaks") as? Bool ?? true
        sidebar = defaults.object(forKey:"readerSidebar") as? Bool ?? true
        annotations = defaults.object(forKey:"readerShowAnnotations") as? Bool ?? true
        hiddenToolbar = defaults.string(forKey:"readerHiddenToolbar") ?? ""
        hiddenAnnotations = defaults.string(forKey:"readerHiddenAnnotations") ?? ""
        highlightColor = defaults.string(forKey:"readerHighlightColor") ?? "#FFE600"
        noteColor = defaults.string(forKey:"readerNoteColor") ?? "#FFCC00"
        inkColor = defaults.string(forKey:"readerInkColor") ?? "#007AFF"
        inkWidth = defaults.object(forKey:"readerInkWidth") as? Double ?? 2.5
        showTabs = defaults.object(forKey:"readerShowTabs") as? Bool ?? true
        splitDirection = defaults.string(forKey:"readerSplitDirection") ?? "horizontal"
    }
    func validate() throws {
        try validateAnnotationStyle()
        guard ["horizontal","vertical"].contains(splitDirection ?? "horizontal") else { throw PreferenceError.invalid("A disposição dos documentos é inválida.") }
        guard (0...2).contains(mode),["vertical","horizontal"].contains(direction),["crop","media"].contains(displayBox),AppearanceColor.isValid(background),zoom.isFinite,(0.1...8).contains(zoom) else { throw PreferenceError.invalid("Há uma opção de leitura inválida.") }
        guard Set(hiddenToolbar.split(separator:",").map(String.init)).isSubset(of:["open","search","zoom","fit","save","compare"]),Set(hiddenAnnotations.split(separator:",").map(String.init)).isSubset(of:["highlight","note","ink","bookmark","editor","history"]) else { throw PreferenceError.invalid("A barra de ferramentas contém uma ação desconhecida.") }
    }
    func validateAnnotationStyle() throws {
        let colors = [highlightColor ?? "#FFE600",noteColor ?? "#FFCC00",inkColor ?? "#007AFF"]
        let width = inkWidth ?? 2.5
        guard colors.allSatisfy(AppearanceColor.isValid),width.isFinite,(0.5...20).contains(width) else { throw PreferenceError.invalid("A cor ou espessura da anotação é inválida.") }
    }
    func apply(to defaults:UserDefaults = .standard) {
        let values:[String:Any] = ["readerMode":mode,"readerDirection":direction,"readerDisplayBox":displayBox,"readerPageBackground":background,"readerAutoScale":autoScale,"readerZoom":zoom,"readerDisplayPageBreaks":pageBreaks,"readerSidebar":sidebar,"readerShowAnnotations":annotations,"readerHiddenToolbar":hiddenToolbar,"readerHiddenAnnotations":hiddenAnnotations,"readerHighlightColor":highlightColor ?? "#FFE600","readerNoteColor":noteColor ?? "#FFCC00","readerInkColor":inkColor ?? "#007AFF","readerInkWidth":inkWidth ?? 2.5,"readerShowTabs":showTabs ?? true,"readerSplitDirection":splitDirection ?? "horizontal"]
        for (key,value) in values { defaults.set(value,forKey:key) }
    }
}
