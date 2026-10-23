import Foundation
import SwiftUI

/// Reusable operation parameters. Document content, paths and passwords are deliberately absent.
struct ToolStyleOptions: Codable, Equatable {
    var editMode = "text", compareMode = "visual", presentationMode = "editable"
    var watermarkMode = "text", redactMode = "text", cropMode = "margin"
    var imageExportMode = "pages", pageSize = "original", orientation = "portrait"
    var fontName = "helv", position = "top-left", shape = "rectangle"
    var encoding = "utf-8-sig", csvDelimiter = "", language = "por+eng"
    var color = "#000000", fill = "#FFFFFF", numberFormat = "{n} / {total}"
    var degrees = 90, dpi = 150, quality = 80, startNumber = 1
    var fontSize = 14.0, margin = 24.0, opacity = 1.0, lineWidth = 1.0
    var x = 36.0, y = 72.0, width = 220.0, height = 80.0
    var recompressImages = false, fitWidth = true, transparentPNG = false
    var flattenAnnotations = true, flattenWidgets = true, textBox = false

    static let supportedTools: Set<String> = ["edit","compare","powerpoint","watermark","redact","crop","jpg","png","images","txt-pdf","epub-pdf","csv-pdf","excel-pdf","rotate","compress","numbers","signature","ocr","pdfa","flatten"]

    func validate(toolID: String) throws {
        func check(_ condition: Bool) throws { if !condition { throw ToolPresetError.invalid } }
        try check(Self.supportedTools.contains(toolID))
        let enums: [(String, [String])] = [
            (editMode,["text","edit","image","shape"]),(compareMode,["visual","text"]),
            (presentationMode,["editable","image"]),(watermarkMode,["text","image"]),
            (redactMode,["text","area"]),(cropMode,["margin","area"]),
            (imageExportMode,["pages","embedded"]),(pageSize,["original","a4","letter"]),
            (orientation,["portrait","landscape"]),(fontName,["helv","hebo","heit","tiro","cour"]),
            (position,["top-left","top-center","top-right","center","bottom-left","bottom-center","bottom-right"]),
            (shape,["rectangle","ellipse","line"]),(encoding,["utf-8-sig","utf-16","cp1252","latin-1"]),
            (csvDelimiter,["",",",";","\t","|"]),(language,["por+eng","por","eng","spa","fra","deu"])
        ]
        for (value, choices) in enums { try check(choices.contains(value)) }
        for hex in [color,fill] { try check(hex.range(of:"^#[0-9a-fA-F]{6}$",options:.regularExpression) != nil) }
        try check([90,180,270].contains(degrees) && (72...600).contains(dpi) && (20...95).contains(quality) && (1...9999).contains(startNumber))
        try check([fontSize,margin,opacity,lineWidth,x,y,width,height].allSatisfy(\.isFinite))
        try check((4...300).contains(fontSize) && (0...10000).contains(margin) && (0...1).contains(opacity) && (0.1...50).contains(lineWidth))
        try check((0...100000).contains(x) && (0...100000).contains(y) && (1...100000).contains(width) && (1...100000).contains(height))
        try check(!numberFormat.isEmpty && numberFormat.count <= 120)
        if ["txt-pdf","epub-pdf"].contains(toolID) { try check(fontSize <= 72 && pageSize != "original") }
        if toolID == "compress" { try check(dpi <= 300) }
        if toolID == "flatten" { try check(flattenAnnotations || flattenWidgets) }
    }
}

enum ToolPresetError: LocalizedError {
    case invalid, tooMany, corruptedLibrary
    var errorDescription: String? {
        switch self {
        case .invalid: return "Configuração inválida ou incompatível com esta ferramenta. Confira nome, opções e limites numéricos."
        case .tooMany: return "Limite de 30 configurações por ferramenta ou 128 no total. Exclua uma configuração antes de criar outra."
        case .corruptedLibrary: return "A biblioteca de configurações não pôde ser lida. Exporte uma cópia dos dados ou restaure a biblioteca nas preferências antes de salvar."
        }
    }
}

struct ToolPreset: Identifiable, Codable, Equatable {
    var id: UUID
    var toolID: String
    var name: String
    var options: ToolStyleOptions
    func validate() throws {
        guard !name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty, name.count <= 64 else { throw ToolPresetError.invalid }
        try options.validate(toolID:toolID)
    }
}

@MainActor final class ToolPresetStore: ObservableObject {
    static let shared = ToolPresetStore()
    private struct Library: Codable {
        var version = 1
        var presets: [ToolPreset] = []
        var defaults: [String:UUID] = [:]
    }
    private let storage: UserDefaults
    private let key = "PDF.toolPresets.v1"
    @Published private(set) var presets: [ToolPreset] = []
    @Published private(set) var defaultIDs: [String:UUID] = [:]
    @Published private(set) var loadFailed = false
    init(defaults: UserDefaults = .standard) {
        storage = defaults
        guard let data = storage.data(forKey:key) else { return }
        do {
            guard data.count <= 1_048_576 else { throw ToolPresetError.invalid }
            let library = try JSONDecoder().decode(Library.self,from:data)
            guard library.version == 1, library.presets.count <= 128,
                  Set(library.presets.map(\.id)).count == library.presets.count else { throw ToolPresetError.invalid }
            for item in library.presets { try item.validate() }
            for toolID in Set(library.presets.map(\.toolID)) {
                guard library.presets.filter({ $0.toolID == toolID }).count <= 30 else { throw ToolPresetError.invalid }
            }
            for (toolID,id) in library.defaults {
                guard library.presets.contains(where: { $0.id == id && $0.toolID == toolID }) else { throw ToolPresetError.invalid }
            }
            presets = library.presets; defaultIDs = library.defaults
        } catch { loadFailed = true }
    }
    func entries(for toolID:String) -> [ToolPreset] { presets.filter { $0.toolID == toolID }.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending } }
    func defaultOptions(for toolID:String) -> ToolStyleOptions? { presets.first { $0.id == defaultIDs[toolID] && $0.toolID == toolID }?.options }
    @discardableResult func save(name:String, toolID:String, options:ToolStyleOptions) throws -> UUID {
        guard !loadFailed else { throw ToolPresetError.corruptedLibrary }
        let name = name.trimmingCharacters(in:.whitespacesAndNewlines)
        let existing = presets.firstIndex { $0.toolID == toolID && $0.name.localizedCaseInsensitiveCompare(name) == .orderedSame }
        let value = ToolPreset(id:existing.map { presets[$0].id } ?? UUID(),toolID:toolID,name:name,options:options)
        try value.validate()
        if let existing { presets[existing] = value }
        else {
            guard presets.count < 128, entries(for:toolID).count < 30 else { throw ToolPresetError.tooMany }
            presets.append(value)
        }
        try persist(); return value.id
    }
    func setDefault(_ id:UUID?, for toolID:String) throws {
        guard !loadFailed, id == nil || presets.contains(where: { $0.id == id && $0.toolID == toolID }) else { throw ToolPresetError.invalid }
        defaultIDs[toolID] = id; try persist()
    }
    func remove(_ id:UUID) throws {
        guard !loadFailed else { throw ToolPresetError.corruptedLibrary }
        presets.removeAll { $0.id == id }; defaultIDs = defaultIDs.filter { $0.value != id }; try persist()
    }
    func exported(_ id:UUID) throws -> Data {
        guard let preset = presets.first(where:{ $0.id == id }) else { throw ToolPresetError.invalid }
        return try JSONEncoder().encode(preset)
    }
    @discardableResult func importPreset(_ data:Data, for toolID:String) throws -> UUID {
        guard data.count <= 64_000 else { throw ToolPresetError.invalid }
        let preset = try JSONDecoder().decode(ToolPreset.self,from:data)
        guard preset.toolID == toolID else { throw ToolPresetError.invalid }
        try preset.validate()
        return try save(name:preset.name,toolID:toolID,options:preset.options)
    }
    func originalData() -> Data? { storage.data(forKey:key) }
    func resetLibrary() { storage.removeObject(forKey:key); presets = []; defaultIDs = [:]; loadFailed = false }
    private func persist() throws {
        let data = try JSONEncoder().encode(Library(presets:presets,defaults:defaultIDs))
        storage.set(data,forKey:key)
    }
}
