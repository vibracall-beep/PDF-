import Foundation
import PDFKit
import CoreFoundation

/// Repairs PDFKit's known NSString -> PDF Name serialization defect. The
/// caller owns private IPC, structural checks, encryption and final fidelity.
/// No value is guessed from a malformed PDF: every replacement must match an
/// exact string captured from the live document before its writer runs.
enum NativePDFStringRepair {
    struct Baseline: Sendable {
        fileprivate var strings: [String: Set<Data>] = [:]
        fileprivate var buttonStates: Set<Data> = [Data("Off".utf8)]
        fileprivate var terminalFields: [TerminalField] = []
        fileprivate var fieldNameCounts: [Data: Int] = [:]
        fileprivate var popups: [PopupWitness] = []
        fileprivate var needsInspection = false
    }

    fileprivate struct TerminalField: Sendable {
        let page: Int
        let name: Data
        let type: String
        let bounds: [Double]
        var checkedBoxValue: Data? = nil
    }

    fileprivate struct PopupWitness: Sendable {
        let page: Int
        let bounds: [Double]
        let contents: Data
        let isOpen: Bool
    }

    private static let maximumJSONBytes = 64 * 1024 * 1024
    private static let maximumObjects = 100_000
    private static let maximumTextBytes = 8 * 1024 * 1024

    static func capture(document: PDFDocument) throws -> Baseline? {
        guard !document.isLocked else { throw failure() }
        var result = Baseline()
        var annotationCount = 0
        func remember(_ role: String, _ value: String?) throws {
            guard let value else { return }
            guard value.utf8.count <= maximumTextBytes else { throw failure() }
            result.strings[role, default: []].insert(Data(value.utf8))
            if value.hasPrefix("/") { result.needsInspection = true }
        }
        for index in 0..<document.pageCount {
            if Task.isCancelled { throw CancellationError() }
            guard let page = document.page(at: index) else { throw failure() }
            for item in page.annotations {
                annotationCount += 1
                guard annotationCount <= maximumObjects else { throw failure() }
                try remember("contents", item.contents)
                if PDFAnnotationKind.matchesAny(item, [.text, .popup]) || item.popup != nil { result.needsInspection = true }
                if PDFAnnotationKind.matches(item, .popup) {
                    if let raw = item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/Open")) {
                        guard let number = raw as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID(),
                              number.boolValue == item.isOpen else { throw failure() }
                    } else if item.isOpen { throw failure() }
                    result.popups.append(PopupWitness(page: index,
                        bounds: try geometry([Double(item.bounds.origin.x), Double(item.bounds.origin.y),
                                              Double(item.bounds.width), Double(item.bounds.height)]),
                        contents: Data((item.contents ?? "").utf8), isOpen: item.isOpen))
                }
                for (key, value) in try annotationTextFields(item) {
                    try remember("annotation:" + key, value)
                }
                guard isWidget(item) else { continue }
                result.needsInspection = true
                if let name = item.fieldName {
                    try remember("field:T", name)
                    result.fieldNameCounts[Data(name.utf8), default: 0] += 1
                    // A field's fully qualified name joins partial /T values.
                    // Dots are separators in the PDF field-name specification.
                    for component in name.split(separator: ".", omittingEmptySubsequences: false) {
                        try remember("field:T", String(component))
                    }
                    if item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/Parent")) == nil,
                       item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/Kids")) == nil,
                       !name.contains("."), [.text, .choice, .button].contains(item.widgetFieldType) {
                        let type = item.widgetFieldType == .text ? "/Tx" : item.widgetFieldType == .choice ? "/Ch" : "/Btn"
                        var witness = TerminalField(page: index, name: Data(name.utf8), type: type,
                            bounds: try geometry([Double(item.bounds.origin.x), Double(item.bounds.origin.y),
                                                  Double(item.bounds.width), Double(item.bounds.height)]))
                        if item.widgetFieldType == .button, item.widgetControlType == .checkBoxControl,
                           item.buttonWidgetState.rawValue == 1,
                           let value = item.widgetStringValue, !value.isEmpty,
                           exact(value, item.buttonWidgetStateString) {
                            witness.checkedBoxValue = Data(value.utf8)
                        }
                        result.terminalFields.append(witness)
                    }
                }
                switch item.widgetFieldType {
                case .text:
                    try remember("text:V", item.widgetStringValue ?? "")
                    try remember("text:DV", item.widgetDefaultStringValue ?? "")
                case .choice:
                    for value in try choiceSelection(item) { try remember("choice:V", value) }
                    let labels = item.choices ?? []
                    let exports = item.values ?? []
                    guard exports.isEmpty || exports.count == labels.count else { throw failure() }
                    for label in labels { try remember("choice:label", label) }
                    for value in exports.isEmpty ? labels : exports { try remember("choice:export", value) }
                    if let value = item.widgetDefaultStringValue, !value.isEmpty {
                        try remember("choice:DV", canonicalChoice(value, labels: labels, exports: exports, preferExport: true, allowsCustom: allowsCustomChoice(item)))
                    } else { try remember("choice:DV", "") }
                case .button:
                    // macOS 27 can emit a string /V for a button, the inverse
                    // of the text-field bug. The appearance states must agree.
                    result.needsInspection = true
                    result.buttonStates.insert(Data(item.buttonWidgetStateString.utf8))
                    if let value = item.widgetStringValue, !value.isEmpty { result.buttonStates.insert(Data(value.utf8)) }
                default: break
                }
            }
        }
        return result.needsInspection ? result : nil
    }

    /// Canonical PDF export values, rather than a possibly display-oriented
    /// PDFKit widgetStringValue. Duplicate labels with different exports are
    /// ambiguous unless the raw /V identifies the export value directly.
    static func choiceSelection(_ item: PDFAnnotation) throws -> [String] {
        let labels = item.choices ?? []
        let exports = item.values ?? []
        guard exports.isEmpty || exports.count == labels.count else { throw failure() }
        let raw = item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/V"))
        if let values = raw as? [String] {
            return try values.filter { !$0.isEmpty }.map {
                try canonicalChoice($0, labels: labels, exports: exports, preferExport: true, allowsCustom: allowsCustomChoice(item))
            }
        }
        if let value = raw as? String, !value.isEmpty {
            return [try canonicalChoice(value, labels: labels, exports: exports, preferExport: true, allowsCustom: allowsCustomChoice(item))]
        }
        guard let value = item.widgetStringValue, !value.isEmpty else { return [] }
        return [try canonicalChoice(value, labels: labels, exports: exports, preferExport: false, allowsCustom: allowsCustomChoice(item))]
    }

    private static func allowsCustomChoice(_ item: PDFAnnotation) -> Bool {
        guard let flags = item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/Ff")) as? NSNumber else { return false }
        return flags.intValue & (1 << 16) != 0 && flags.intValue & (1 << 17) != 0
    }

    private static func canonicalChoice(_ value: String, labels: [String], exports: [String], preferExport: Bool, allowsCustom: Bool) throws -> String {
        let actualExports = exports.isEmpty ? labels : exports
        if preferExport, actualExports.contains(where: { exact($0, value) }) { return value }
        var candidates = Set<Data>()
        if actualExports.contains(where: { exact($0, value) }) { candidates.insert(Data(value.utf8)) }
        for (index, label) in labels.enumerated() where exact(label, value) { candidates.insert(Data(actualExports[index].utf8)) }
        if candidates.isEmpty, allowsCustom { return value }
        guard candidates.count == 1, let result = candidates.first, let text = String(data: result, encoding: .utf8) else { throw failure() }
        return text
    }

    /// Shared with the final fidelity snapshot. These are observed strings,
    /// not fabricated defaults; their contents never appear in diagnostics.
    static func annotationTextFields(_ item: PDFAnnotation) throws -> [String: String] {
        let keys = isWidget(item) ? ["/NM", "/Subj", "/TU", "/TM"] : ["/NM", "/Subj", "/T"]
        var result: [String: String] = [:]
        for key in keys {
            if let value = item.value(forAnnotationKey: PDFAnnotationKey(rawValue: key)) as? String {
                guard value.utf8.count <= maximumTextBytes else { throw failure() }
                result[key] = value
            }
        }
        return result
    }

    static func patch(jsonData: Data, baseline: Baseline) throws -> Data? {
        guard jsonData.count <= maximumJSONBytes,
              let rawDocument = try? JSONSerialization.jsonObject(with: jsonData) else { throw failure() }
        try validateDictionaryKeys(rawDocument)
        guard let document = rawDocument as? [String: Any],
              let qpdf = document["qpdf"] as? [Any], qpdf.count == 2,
              let header = qpdf[0] as? [String: Any], header["jsonversion"] as? Int == 2,
              let originalObjects = qpdf[1] as? [String: [String: Any]], originalObjects.count <= maximumObjects else { throw failure() }
        let rebound = try repairReferences(originalObjects, pages: document["pages"])
        let objects = try restoreOmittedFields(rebound, pages: document["pages"], baseline: baseline)
        let graph = Graph(objects: objects)
        let visible = try graph.visibleAnnotations(document["pages"])
        let annotationKeys = try graph.linkedAnnotations(visible)
        var fieldKeys = Set<String>()
        let (_, catalog) = try graph.catalog()
        if let form = try graph.dictionary(catalog["/AcroForm"]) {
            try graph.collectFields(form["/Fields"], into: &fieldKeys)
        }
        for key in visible where graph.value(key)?["/Subtype"] as? String == "/Widget" {
            fieldKeys.insert(key)
        }
        // Include parent field dictionaries and duplicated widget objects. The
        // macOS 26 writer can keep both /Fields and /Annots copies. Type repairs
        // are identical for duplicates; we never rely on unstable object IDs.
        for key in Array(fieldKeys) {
            var cursor: String? = key
            var visited = Set<String>()
            while let current = cursor {
                guard visited.insert(current).inserted, visited.count <= 128 else { throw failure() }
                fieldKeys.insert(current)
                cursor = graph.reference(graph.value(current)?["/Parent"])
            }
        }
        var updates: [String: Any] = [:]
        for (key, record) in objects {
            if let original = originalObjects[key], !NSDictionary(dictionary: record).isEqual(to: original) { updates[key] = record }
        }
        for (key, record) in objects {
            if Task.isCancelled { throw CancellationError() }
            guard var value = record["value"] as? [String: Any] else { continue }
            var changed = false
            func repair(_ field: String, role: String, arrays: Bool = false) throws {
                guard let existing = value[field] else { return }
                let fixed = try repairStrings(existing, allowed: baseline.strings[role] ?? [], arrays: arrays)
                if fixed.changed { value[field] = fixed.value; changed = true }
            }
            let annotation = annotationKeys.contains(key)
            if annotation {
                try repair("/Contents", role: "contents")
                if value["/Subtype"] as? String == "/Popup", let rawOpen = value["/Open"] {
                    let fixed = try repairPopupOpen(rawOpen, key: key, value: value, graph: graph,
                        pages: document["pages"], baseline: baseline)
                    if fixed.changed { value["/Open"] = fixed.value; changed = true }
                }
                for field in ["/NM", "/Subj"] { try repair(field, role: "annotation:" + field) }
                if !fieldKeys.contains(key) { try repair("/T", role: "annotation:/T") }
            }
            if fieldKeys.contains(key) {
                try repair("/T", role: "field:T")
                for field in ["/TU", "/TM"] { try repair(field, role: "annotation:" + field) }
                switch try graph.fieldType(key) {
                case "/Tx":
                    try repair("/V", role: "text:V")
                    try repair("/DV", role: "text:DV")
                case "/Ch":
                    try repair("/V", role: "choice:V", arrays: true)
                    try repair("/DV", role: "choice:DV", arrays: true)
                    if let options = value["/Opt"] {
                        let fixed = try repairOptions(options, baseline: baseline)
                        if fixed.changed { value["/Opt"] = fixed.value; changed = true }
                    }
                case "/Btn":
                    let needsStates = ["/V", "/DV", "/AS"].contains { (value[$0] as? String)?.hasPrefix("u:") == true }
                    let states = needsStates ? try graph.buttonAppearanceStates(key) : []
                    for field in ["/V", "/DV", "/AS"] {
                        guard let current = value[field] as? String, current.hasPrefix("u:") else { continue }
                        let text = String(current.dropFirst(2)), name = "/" + text
                        let singleAppearance = field == "/V" && states.isEmpty
                            ? try witnessedCheckedBox(key, value: text, graph: graph, pages: document["pages"], baseline: baseline) : false
                        guard baseline.buttonStates.contains(Data(text.utf8)), text == "Off" || states.contains(Data(name.utf8)) || singleAppearance else { throw failure() }
                        value[field] = name; changed = true
                    }
                default: break // Signature dictionaries and unknown field types stay untouched.
                }
            }
            if changed {
                var updated = record
                updated["value"] = value
                updates[key] = updated
            }
        }
        guard !updates.isEmpty else { return nil }
        // updateFromJson replaces whole objects, not individual dictionary
        // entries. Keep every other key and reference exactly as qpdf returned it.
        let data = try JSONSerialization.data(withJSONObject: ["qpdf": [["jsonversion": 2], updates]], options: [.sortedKeys])
        guard data.count <= maximumJSONBytes else { throw failure() }
        return data
    }

    private static func validateDictionaryKeys(_ value: Any, depth: Int = 0) throws {
        guard depth <= 128 else { throw failure() }
        if let dictionary = value as? NSDictionary {
            var canonicalKeys = Set<String>(), count = 0
            for (key, value) in dictionary {
                guard let key = key as? String else { throw failure() }
                canonicalKeys.insert(key); count += 1
                try validateDictionaryKeys(value, depth: depth + 1)
            }
            // Swift Dictionary otherwise merges distinct PDF names such as
            // NFC/NFD spellings. Refuse rather than silently losing a key.
            guard canonicalKeys.count == count else { throw failure() }
        } else if let array = value as? [Any] {
            for item in array { try validateDictionaryKeys(item, depth: depth + 1) }
        }
    }

    /// PDFKit 26 can serialize a widget twice, leaving /Fields pointing to one
    /// copy while /Annots points to the other. Text/Popup backlinks exhibit the
    /// same defect. Match the ENTIRE dictionary, including unknown keys and
    /// appearance references, and only bind to a unique visible annotation.
    /// No fields/popups are deleted, appended or inferred from similar names.
    private static func repairReferences(_ original: [String: [String: Any]], pages: Any?) throws -> [String: [String: Any]] {
        let graph = Graph(objects: original)
        guard let pages = pages as? [[String: Any]] else { throw failure() }
        var visible = Set<String>()
        var pageMembership: [String: Set<Int>] = [:]
        for (index, page) in pages.enumerated() {
            guard let key = graph.reference(page["object"]), let dictionary = graph.value(key),
                  dictionary["/Type"] as? String == "/Page" else { throw failure() }
            for item in try graph.array(dictionary["/Annots"]) ?? [] {
                guard let key = graph.reference(item), graph.value(key) != nil else { throw failure() }
                visible.insert(key); pageMembership[key, default: []].insert(index)
            }
        }
        // Sorted JSON is a complete dictionary identity, not a lossy subset.
        // Store bytes as keys; this avoids relying on randomized Swift hashes
        // or assuming two objects with matching geometry have matching actions.
        var identities: [Data: [String]] = [:]
        func identity(_ value: [String: Any]) throws -> Data {
            try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        }
        for key in visible {
            guard let value = graph.value(key) else { throw failure() }
            identities[try identity(value), default: []].append(key)
        }
        var aliases: [String: String] = [:], ambiguous = Set<String>()
        for (key, record) in original where !visible.contains(key) {
            guard let value = record["value"] as? [String: Any],
                  value["/Subtype"] != nil, value["/Rect"] != nil,
                  let matches = identities[try identity(value)] else { continue }
            if matches.count == 1 { aliases[key] = matches[0] }
            else { ambiguous.insert(key) }
        }
        guard !aliases.isEmpty || !ambiguous.isEmpty else { return original }
        var objects = original
        func rebound(_ item: Any) throws -> Any {
            guard let key = graph.reference(item) else { return item }
            guard !ambiguous.contains(key) else { throw failure() }
            if let alias = aliases[key] { return String(alias.dropFirst(4)) }
            return item
        }
        func storeValue(_ key: String, _ value: Any) throws {
            guard var record = objects[key], record["value"] != nil else { throw failure() }
            record["value"] = value; objects[key] = record
        }
        // Update only the field-tree slots reached from the actual catalog.
        // Hidden fields, signature fields and all unrelated Kids arrays remain.
        var visitedFields = Set<String>()
        func updateFields(_ container: Any?, depth: Int) throws -> Any? {
            guard depth <= 128 else { throw failure() }
            guard let container else { return nil }
            if let arrayKey = graph.reference(container), let array = original[arrayKey]?["value"] as? [Any] {
                if let updated = try updateFields(array, depth: depth + 1) { try storeValue(arrayKey, updated) }
                return container
            }
            guard let array = container as? [Any] else { throw failure() }
            var output: [Any] = [], resultingReferences = Set<String>()
            for element in array {
                let target = try rebound(element)
                guard let key = graph.reference(target), var value = (objects[key]?["value"] as? [String: Any]) else { throw failure() }
                // Never collapse two independent field slots into one object.
                guard resultingReferences.insert(key).inserted else { throw failure() }
                output.append(target)
                if visitedFields.insert(key).inserted {
                    if let kids = value["/Kids"] { value["/Kids"] = try updateFields(kids, depth: depth + 1) }
                    // Parent is structural for widgets and nonterminal fields.
                    if let parent = value["/Parent"] { value["/Parent"] = try rebound(parent) }
                    try storeValue(key, value)
                }
            }
            return output
        }
        let (catalogKey, originalCatalog) = try graph.catalog()
        var catalog = originalCatalog
        if let rawForm = catalog["/AcroForm"], var form = try graph.dictionary(rawForm) {
            if let fields = form["/Fields"] { form["/Fields"] = try updateFields(fields, depth: 0) }
            if let formKey = graph.reference(rawForm) { try storeValue(formKey, form) }
            else { catalog["/AcroForm"] = form; try storeValue(catalogKey, catalog) }
        }
        // Rebind visible popup pairs only when both endpoints land on the same
        // page and both backlinks already identify the exact cloned pair.
        for key in visible {
            guard var parent = objects[key]?["value"] as? [String: Any],
                  let oldPopup = parent["/Popup"], let oldPopupKey = graph.reference(oldPopup) else { continue }
            guard !ambiguous.contains(oldPopupKey) else { throw failure() }
            guard let popupKey = aliases[oldPopupKey],
                  var popup = objects[popupKey]?["value"] as? [String: Any], popup["/Subtype"] as? String == "/Popup",
                  let oldParentKey = graph.reference(popup["/Parent"]), aliases[oldParentKey] == key,
                  let parentPages = pageMembership[key], let popupPages = pageMembership[popupKey],
                  parentPages == popupPages, parentPages.count == 1 else { continue }
            parent["/Popup"] = String(popupKey.dropFirst(4))
            popup["/Parent"] = String(key.dropFirst(4))
            try storeValue(key, parent); try storeValue(popupKey, popup)
        }
        return objects
    }

    /// A second PDFKit write can drop otherwise intact terminal widgets from
    /// /Fields. Restore only a unique, flat field witnessed before the writer;
    /// never manufacture a field or guess how to rebuild a complex hierarchy.
    private static func restoreOmittedFields(_ original: [String: [String: Any]], pages: Any?, baseline: Baseline) throws -> [String: [String: Any]] {
        let graph = Graph(objects: original)
        let visible = try graph.visibleAnnotations(pages)
        let widgets = visible.filter { graph.value($0)?["/Subtype"] as? String == "/Widget" }
        guard !widgets.isEmpty else { return original }
        let (catalogKey, catalog) = try graph.catalog()
        let rawForm = catalog["/AcroForm"]
        // First writes legitimately seen in the exact fixtures have page
        // widgets but no AcroForm and already pass qpdf. Do not invent a form
        // tree while repairing omissions from an existing one.
        guard rawForm != nil else { return original }
        let originalForm = try graph.dictionary(rawForm)
        var fieldKeys = Set<String>()
        try graph.collectFields(originalForm?["/Fields"], into: &fieldKeys)
        let omitted = widgets.subtracting(fieldKeys)
        guard !omitted.isEmpty else { return original }
        guard var form = originalForm, let rawFields = form["/Fields"], var fields = try graph.array(rawFields),
              let pages = pages as? [[String: Any]] else { throw failure() }
        var membership: [String: Set<Int>] = [:]
        for (index, page) in pages.enumerated() {
            guard let pageKey = graph.reference(page["object"]), let value = graph.value(pageKey) else { throw failure() }
            for entry in try graph.array(value["/Annots"]) ?? [] {
                guard let key = graph.reference(entry) else { throw failure() }
                membership[key, default: []].insert(index)
            }
        }
        func fieldName(_ key: String) throws -> Data? {
            var cursor: String? = key, visited = Set<String>(), parts: [String] = []
            while let current = cursor {
                guard visited.insert(current).inserted, visited.count <= 128, let value = graph.value(current) else { throw failure() }
                if let rawName = value["/T"] {
                    let fixed = try repairStrings(rawName, allowed: baseline.strings["field:T"] ?? [])
                    guard let text = fixed.value as? String, text.hasPrefix("u:") else { throw failure() }
                    parts.insert(String(text.dropFirst(2)), at: 0)
                }
                cursor = graph.reference(value["/Parent"])
            }
            return parts.isEmpty ? nil : Data(parts.joined(separator: ".").utf8)
        }
        var existingNames = Set<Data>(), visibleNames: [Data: Int] = [:]
        for key in fieldKeys { if let name = try fieldName(key) { existingNames.insert(name) } }
        for key in widgets { if let name = try fieldName(key) { visibleNames[name, default: 0] += 1 } }
        for key in omitted.sorted() {
            guard let value = graph.value(key), value["/Parent"] == nil, value["/Kids"] == nil,
                  let type = value["/FT"] as? String, ["/Tx", "/Ch", "/Btn"].contains(type),
                  value["/T"] != nil, let name = try fieldName(key), !name.isEmpty,
                  !existingNames.contains(name), visibleNames[name] == 1,
                  let pageSet = membership[key], pageSet.count == 1, let page = pageSet.first,
                  let rawRectangle = value["/Rect"] as? [NSNumber], rawRectangle.count == 4 else { throw failure() }
            let rectangle = rawRectangle.map(\.doubleValue)
            guard rectangle.allSatisfy(\.isFinite), rectangle[2] >= rectangle[0], rectangle[3] >= rectangle[1] else { throw failure() }
            let bounds = try geometry([rectangle[0], rectangle[1], rectangle[2] - rectangle[0], rectangle[3] - rectangle[1]])
            let captured = baseline.terminalFields.filter { $0.name == name }
            guard baseline.fieldNameCounts[name] == 1, captured.count == 1, let witness = captured.first,
                  witness.page == page, witness.type == type, witness.bounds == bounds else { throw failure() }
            // Keep the original dictionary/AP/actions intact. This changes only
            // one structural slot and leaves hidden/signature fields in order.
            fields.append(String(key.dropFirst(4)))
            existingNames.insert(name)
        }
        var objects = original
        if let key = graph.reference(rawFields) {
            guard var record = objects[key] else { throw failure() }
            record["value"] = fields; objects[key] = record
        } else {
            form["/Fields"] = fields
            if let key = graph.reference(rawForm) {
                guard var record = objects[key] else { throw failure() }
                record["value"] = form; objects[key] = record
            } else {
                var updated = catalog; updated["/AcroForm"] = form
                guard var record = objects[catalogKey] else { throw failure() }
                record["value"] = updated; objects[catalogKey] = record
            }
        }
        return objects
    }

    /// PDFKit 27 writes a checked checkbox's /V as a String even when its
    /// normal appearance is one Form XObject, not a state dictionary. The
    /// exact pre-writer checkbox is the witness; no /AS or AP states are made.
    private static func witnessedCheckedBox(_ key: String, value text: String, graph: Graph, pages: Any?, baseline: Baseline) throws -> Bool {
        guard let value = graph.value(key), value["/FT"] as? String == "/Btn",
              value["/Parent"] == nil, value["/Kids"] == nil, value["/AS"] == nil,
              let rawName = value["/T"], let rawRectangle = value["/Rect"] as? [NSNumber], rawRectangle.count == 4,
              let appearance = try graph.dictionary(value["/AP"]), let normalKey = graph.reference(appearance["/N"]),
              let stream = graph.objects[normalKey]?["stream"] as? [String: Any],
              let dictionary = stream["dict"] as? [String: Any], dictionary["/Subtype"] as? String == "/Form",
              let pages = pages as? [[String: Any]] else { return false }
        let flags = (value["/Ff"] as? NSNumber)?.intValue ?? 0
        guard flags & ((1 << 15) | (1 << 16)) == 0 else { return false } // Radio/pushbutton are not this case.
        let fixedName = try repairStrings(rawName, allowed: baseline.strings["field:T"] ?? [])
        guard let nameString = fixedName.value as? String, nameString.hasPrefix("u:") else { return false }
        let name = Data(nameString.dropFirst(2).utf8)
        let captured = baseline.terminalFields.filter { $0.name == name }
        guard baseline.fieldNameCounts[name] == 1, captured.count == 1, let witness = captured.first,
              witness.type == "/Btn", witness.checkedBoxValue == Data(text.utf8) else { return false }
        let rectangle = rawRectangle.map(\.doubleValue)
        guard rectangle.allSatisfy(\.isFinite), rectangle[2] >= rectangle[0], rectangle[3] >= rectangle[1],
              try geometry([rectangle[0], rectangle[1], rectangle[2] - rectangle[0], rectangle[3] - rectangle[1]]) == witness.bounds else { return false }
        var locations: [Int] = []
        for (index, page) in pages.enumerated() {
            guard let pageKey = graph.reference(page["object"]), let page = graph.value(pageKey) else { throw failure() }
            for entry in try graph.array(page["/Annots"]) ?? [] where graph.reference(entry) == key { locations.append(index) }
        }
        return locations == [witness.page]
    }

    private static func geometry(_ values: [Double]) throws -> [Double] {
        // Match the publication boundary's existing 0.001-point fidelity
        // precision; no geometric search or nearest-neighbour matching occurs.
        try values.map { value in
            let scaled = value * 1000
            guard value.isFinite, scaled.isFinite else { throw failure() }
            let rounded = scaled.rounded() / 1000
            return rounded == 0 ? 0 : rounded
        }
    }

    /// macOS 27 can serialize a Popup's CFBoolean as the PDF number 0/1.
    /// Only an exact pre-writer popup can prove the intended Boolean. Valid
    /// Boolean values are not broadly coerced, and no other key is changed.
    private static func repairPopupOpen(_ raw: Any, key: String, value: [String: Any], graph: Graph,
                                        pages: Any?, baseline: Baseline) throws -> (value: Any, changed: Bool) {
        guard let number = raw as? NSNumber else { throw failure() }
        let isBoolean = CFGetTypeID(number) == CFBooleanGetTypeID()
        guard number.doubleValue == 0 || number.doubleValue == 1 else { throw failure() }
        guard let rectangle = value["/Rect"] as? [NSNumber], rectangle.count == 4,
              let pages = pages as? [[String: Any]] else { throw failure() }
        let coordinates = rectangle.map(\.doubleValue)
        guard coordinates.allSatisfy(\.isFinite), coordinates[2] >= coordinates[0], coordinates[3] >= coordinates[1] else { throw failure() }
        let bounds = try geometry([coordinates[0], coordinates[1], coordinates[2] - coordinates[0], coordinates[3] - coordinates[1]])
        let contents: Data
        if let rawContents = value["/Contents"] {
            guard let string = rawContents as? String, string.hasPrefix("u:") else { throw failure() }
            contents = Data(string.dropFirst(2).utf8)
        } else { contents = Data() }
        var locations: [Int] = []
        for (index, page) in pages.enumerated() {
            guard let pageKey = graph.reference(page["object"]), let page = graph.value(pageKey) else { throw failure() }
            for entry in try graph.array(page["/Annots"]) ?? [] where graph.reference(entry) == key { locations.append(index) }
        }
        let matches = baseline.popups.filter { locations == [$0.page] && $0.bounds == bounds && $0.contents == contents }
        // A valid Boolean on an automatically generated popup needs no type
        // repair. Its semantics remain covered by the final fidelity check.
        if isBoolean, matches.count != 1 { return (raw, false) }
        guard matches.count == 1, let witness = matches.first, witness.isOpen == number.boolValue else { throw failure() }
        return isBoolean ? (raw, false) : (witness.isOpen, true)
    }

    private static func repairStrings(_ value: Any, allowed: Set<Data>, arrays: Bool = false) throws -> (value: Any, changed: Bool) {
        if arrays, let values = value as? [Any] {
            var output: [Any] = [], changed = false
            for item in values {
                let fixed = try repairStrings(item, allowed: allowed)
                output.append(fixed.value); changed = changed || fixed.changed
            }
            return (output, changed)
        }
        guard let name = value as? String, name.hasPrefix("/") else { return (value, false) }
        guard name.utf8.count <= maximumTextBytes else { throw failure() }
        var candidates = Set<Data>()
        let raw = Data(name.utf8)
        if allowed.contains(raw) { candidates.insert(raw) }
        if let decoded = decodeNameOnce(name) {
            let bytes = Data(decoded.utf8)
            if allowed.contains(bytes) { candidates.insert(bytes) }
        }
        guard candidates.count == 1, let exact = candidates.first, let text = String(data: exact, encoding: .utf8) else { throw failure() }
        return ("u:" + text, true)
    }

    private static func repairOptions(_ value: Any, baseline: Baseline) throws -> (value: Any, changed: Bool) {
        guard let items = value as? [Any], items.count <= maximumObjects else { throw failure() }
        var output: [Any] = [], changed = false
        for item in items {
            if let pair = item as? [Any] {
                guard pair.count == 2 else { throw failure() }
                let export = try repairStrings(pair[0], allowed: baseline.strings["choice:export"] ?? [])
                let label = try repairStrings(pair[1], allowed: baseline.strings["choice:label"] ?? [])
                output.append([export.value, label.value]); changed = changed || export.changed || label.changed
            } else {
                let allowed = (baseline.strings["choice:export"] ?? []).union(baseline.strings["choice:label"] ?? [])
                let fixed = try repairStrings(item, allowed: allowed)
                output.append(fixed.value); changed = changed || fixed.changed
            }
        }
        return (output, changed)
    }

    private static func decodeNameOnce(_ value: String) -> String? {
        let input = Array(value.utf8)
        var output = [UInt8](), index = 0
        func hex(_ value: UInt8) -> UInt8? {
            switch value {
            case 48...57: return value - 48
            case 65...70: return value - 55
            case 97...102: return value - 87
            default: return nil
            }
        }
        while index < input.count {
            if input[index] == 35, index + 2 < input.count, let first = hex(input[index + 1]), let second = hex(input[index + 2]) {
                output.append(first * 16 + second); index += 3
            } else { output.append(input[index]); index += 1 }
        }
        return String(bytes: output, encoding: .utf8)
    }

    private struct Graph {
        let objects: [String: [String: Any]]
        func reference(_ value: Any?) -> String? {
            guard let text = value as? String,
                  text.range(of: "^[0-9]+ [0-9]+ R$", options: .regularExpression) != nil else { return nil }
            return "obj:" + text
        }
        func value(_ key: String) -> [String: Any]? { objects[key]?["value"] as? [String: Any] }
        func catalog() throws -> (String, [String: Any]) {
            guard let trailer = value("trailer"), let key = reference(trailer["/Root"]),
                  let catalog = value(key), catalog["/Type"] as? String == "/Catalog" else { throw NativePDFStringRepair.failure() }
            return (key, catalog)
        }
        func visibleAnnotations(_ pages: Any?) throws -> Set<String> {
            guard let pages = pages as? [[String: Any]] else { throw NativePDFStringRepair.failure() }
            var result = Set<String>()
            for page in pages {
                guard let pageKey = reference(page["object"]), let page = value(pageKey), page["/Type"] as? String == "/Page" else { throw NativePDFStringRepair.failure() }
                for item in try array(page["/Annots"]) ?? [] {
                    guard let key = reference(item), value(key) != nil else { throw NativePDFStringRepair.failure() }
                    result.insert(key)
                }
            }
            return result
        }
        func linkedAnnotations(_ visible: Set<String>) throws -> Set<String> {
            var result = visible, pending = Array(visible)
            while let key = pending.popLast() {
                guard result.count <= NativePDFStringRepair.maximumObjects, let annotation = value(key) else { throw NativePDFStringRepair.failure() }
                var links: [Any] = []
                if let popup = annotation["/Popup"] { links.append(popup) }
                if annotation["/Subtype"] as? String == "/Popup", let parent = annotation["/Parent"] { links.append(parent) }
                for link in links {
                    guard let target = reference(link), let linked = value(target), linked["/Subtype"] != nil else { throw NativePDFStringRepair.failure() }
                    if result.insert(target).inserted { pending.append(target) }
                }
            }
            return result
        }
        func dictionary(_ item: Any?) throws -> [String: Any]? {
            if let reference = reference(item) {
                guard let result = value(reference) else { throw NativePDFStringRepair.failure() }
                return result
            }
            return item as? [String: Any]
        }
        func array(_ item: Any?) throws -> [Any]? {
            if let key = reference(item) {
                guard let result = objects[key]?["value"] as? [Any] else { throw NativePDFStringRepair.failure() }
                return result
            }
            return item as? [Any]
        }
        func collectFields(_ item: Any?, into result: inout Set<String>, depth: Int = 0) throws {
            guard depth <= 128 else { throw NativePDFStringRepair.failure() }
            guard let items = try array(item) else { return }
            for item in items {
                guard let key = reference(item), let field = value(key) else { throw NativePDFStringRepair.failure() }
                guard result.count < NativePDFStringRepair.maximumObjects else { throw NativePDFStringRepair.failure() }
                if result.insert(key).inserted { try collectFields(field["/Kids"], into: &result, depth: depth + 1) }
            }
        }
        func fieldType(_ key: String) throws -> String? {
            var current: String? = key, visited = Set<String>()
            while let item = current {
                guard visited.insert(item).inserted, visited.count <= 128, let field = value(item) else { throw NativePDFStringRepair.failure() }
                if let type = field["/FT"] as? String { return type }
                current = reference(field["/Parent"])
            }
            return nil
        }
        func buttonAppearanceStates(_ key: String) throws -> Set<Data> {
            var result = Set<Data>(), visited = Set<String>()
            func visit(_ key: String, depth: Int) throws {
                guard depth <= 128, visited.count <= NativePDFStringRepair.maximumObjects else { throw NativePDFStringRepair.failure() }
                guard visited.insert(key).inserted, let field = value(key) else { return }
                if let appearance = try dictionary(field["/AP"]) {
                    let normalValue = appearance["/N"]
                    let stream = reference(normalValue).flatMap { objects[$0]?["stream"] } != nil
                    if !stream, let normal = try dictionary(normalValue) {
                        result.formUnion(normal.keys.filter { $0.hasPrefix("/") }.map { Data($0.utf8) })
                    }
                }
                for child in try array(field["/Kids"]) ?? [] {
                    if let reference = reference(child) { try visit(reference, depth: depth + 1) }
                }
                if let parent = reference(field["/Parent"]) { try visit(parent, depth: depth + 1) }
            }
            try visit(key, depth: 0)
            return result
        }
    }

    /// Regression fixtures follow the actual qpdf JSON emitted by the macOS
    /// diagnostics. These checks exercise typed values and structural aliases
    /// independently of PDFKit's reader accepting a malformed representation.
    static func runAuditChecks() throws {
        func require(_ value: Bool, line: Int = #line) throws {
            if !value {
                // Only a fixed source location reaches diagnostics, never a
                // PDF value or the contents of a rejected fixture.
                throw NSError(domain: "PDF.NativeStringRepair.Audit", code: 1, userInfo: [NSLocalizedDescriptionKey:
                    "A auditoria interna do reparo PDF falhou no ponto \(line)."])
            }
        }
        func record(_ value: [String: Any]) -> [String: Any] { ["value": value] }
        var baseline = Baseline()
        let expectedStrings: [String: [String]] = ["contents": ["/Note text"], "field:T": ["/field", "choice"],
            "text:V": ["/value"], "text:DV": ["/default"],
            "choice:V": ["/second"], "choice:export": ["/first", "/second"],
            "choice:label": ["/First label", "/Second label"]]
        baseline.strings = expectedStrings.mapValues { Set($0.map { Data($0.utf8) }) }
        baseline.buttonStates = [Data("Off".utf8), Data("Yes".utf8)]
        baseline.needsInspection = true
        let widget: [String: Any] = ["/Type": "/Annot", "/Subtype": "/Widget", "/FT": "/Tx",
            "/T": "/field", "/V": "/value", "/DV": "/default", "/Rect": [20, 20, 120, 40],
            "/CustomName": "/value", "/AP": ["/N": "40 0 R"]]
        let text: [String: Any] = ["/Type": "/Annot", "/Subtype": "/Text", "/Rect": [10, 70, 34, 94],
            "/Contents": "/Note#20text", "/Popup": "23 0 R"]
        let popup: [String: Any] = ["/Type": "/Annot", "/Subtype": "/Popup", "/Rect": [50, 60, 200, 160],
            "/Parent": "22 0 R", "/Open": false]
        var objects: [String: [String: Any]] = [:]
        objects["trailer"] = record(["/Root": "1 0 R"])
        objects["obj:1 0 R"] = record(["/Type": "/Catalog", "/AcroForm": "2 0 R"])
        objects["obj:2 0 R"] = record(["/Fields": ["6 0 R", "7 0 R", "8 0 R", "9 0 R", "11 0 R"]])
        objects["obj:3 0 R"] = record(["/Type": "/Page", "/Annots": "4 0 R"])
        objects["obj:4 0 R"] = ["value": ["5 0 R", "20 0 R", "21 0 R"]]
        objects["obj:5 0 R"] = record(widget); objects["obj:6 0 R"] = record(widget)
        objects["obj:7 0 R"] = record(["/FT": "/Sig", "/T": "u:hidden-signature", "/V": "41 0 R"])
        // A legitimate pushbutton's normal appearance is a stream, not a map
        // of states. No /V exists, so its appearance must remain untouched.
        objects["obj:8 0 R"] = record(["/Subtype": "/Widget", "/FT": "/Btn", "/T": "u:button",
            "/Rect": [20, 50, 80, 70], "/AP": ["/N": "40 0 R"]])
        objects["obj:9 0 R"] = record(["/Subtype": "/Widget", "/FT": "/Ch", "/T": "u:choice",
            "/Rect": [20, 90, 140, 120], "/V": ["/second"],
            "/Opt": [["/first", "/First#20label"], ["/second", "/Second#20label"]]])
        objects["obj:11 0 R"] = record(["/FT": "/Btn", "/T": "u:checkbox", "/V": "u:Yes", "/Kids": "12 0 R"])
        objects["obj:12 0 R"] = ["value": ["13 0 R"]]
        objects["obj:13 0 R"] = record(["/Subtype": "/Widget", "/Parent": "11 0 R", "/Rect": [150, 90, 170, 110],
            "/AS": "u:Yes", "/AP": ["/N": ["/Off": "40 0 R", "/Yes": "40 0 R"]]])
        objects["obj:20 0 R"] = record(text); objects["obj:22 0 R"] = record(text)
        objects["obj:21 0 R"] = record(popup); objects["obj:23 0 R"] = record(popup)
        objects["obj:40 0 R"] = ["stream": ["dict": ["/Type": "/XObject", "/Subtype": "/Form"]]]
        objects["obj:41 0 R"] = record(["/Type": "/Sig", "/Contents": "b:00112233"])
        // An old incremental catalog and its invalid/unrelated fields are not
        // part of the trailer's live tree and must not be examined or rewritten.
        objects["obj:50 0 R"] = record(["/Type": "/Catalog", "/AcroForm": ["/Fields": ["51 0 R"]]])
        objects["obj:51 0 R"] = record(["/Type": "/Annot", "/Subtype": "/Widget", "/Rect": [90, 90, 100, 100],
            "/FT": "/Tx", "/T": "/unrelated-old-field", "/Kids": ["51 0 R"]])
        func data(_ records: [String: [String: Any]]) throws -> Data {
            try JSONSerialization.data(withJSONObject: ["qpdf": [["jsonversion": 2], records],
                "pages": [["object": "3 0 R"]]])
        }
        guard let changed = try patch(jsonData: data(objects), baseline: baseline),
              let parsed = try JSONSerialization.jsonObject(with: changed) as? [String: Any],
              let qpdf = parsed["qpdf"] as? [Any], let updates = qpdf[1] as? [String: [String: Any]] else { throw failure() }
        func updated(_ key: String) -> [String: Any] { updates[key]?["value"] as? [String: Any] ?? [:] }
        try require(updated("obj:2 0 R")["/Fields"] as? [String] == ["5 0 R", "7 0 R", "8 0 R", "9 0 R", "11 0 R"])
        try require(updated("obj:5 0 R")["/T"] as? String == "u:/field")
        try require(updated("obj:5 0 R")["/V"] as? String == "u:/value")
        try require(updated("obj:5 0 R")["/DV"] as? String == "u:/default")
        try require(updated("obj:5 0 R")["/CustomName"] as? String == "/value")
        try require(updated("obj:9 0 R")["/V"] as? [String] == ["u:/second"])
        try require(updated("obj:9 0 R")["/Opt"] as? [[String]] == [["u:/first", "u:/First label"], ["u:/second", "u:/Second label"]])
        try require(updated("obj:11 0 R")["/V"] as? String == "/Yes")
        try require(updated("obj:13 0 R")["/AS"] as? String == "/Yes")
        try require(updated("obj:20 0 R")["/Popup"] as? String == "21 0 R")
        try require(updated("obj:21 0 R")["/Parent"] as? String == "20 0 R")
        try require(updates["obj:7 0 R"] == nil && updates["obj:8 0 R"] == nil && updates["obj:40 0 R"] == nil && updates["obj:41 0 R"] == nil)
        try require(updates["obj:50 0 R"] == nil && updates["obj:51 0 R"] == nil)
        var applied = objects
        for (key, value) in updates { applied[key] = value }
        try require(try patch(jsonData: data(applied), baseline: baseline) == nil)
        func rejects(_ records: [String: [String: Any]], _ captured: Baseline, line: Int = #line) throws {
            var refused = false
            do { _ = try patch(jsonData: data(records), baseline: captured) } catch { refused = true }
            try require(refused, line: line)
        }
        // The second write in the real macOS 26 fixture keeps only the button
        // in /Fields, while text/choice widgets remain intact on the page.
        var omitted = objects, omittedBaseline = baseline
        omitted["obj:2 0 R"] = record(["/Fields": ["7 0 R", "8 0 R", "11 0 R"]])
        omitted["obj:4 0 R"] = ["value": ["5 0 R", "9 0 R", "20 0 R", "21 0 R"]]
        omittedBaseline.terminalFields = [TerminalField(page: 0, name: Data("/field".utf8), type: "/Tx", bounds: [20, 20, 100, 20]),
            TerminalField(page: 0, name: Data("choice".utf8), type: "/Ch", bounds: [20, 90, 120, 30])]
        omittedBaseline.fieldNameCounts = [Data("/field".utf8): 1, Data("choice".utf8): 1]
        guard let restored = try patch(jsonData: data(omitted), baseline: omittedBaseline),
              let restoredRoot = try JSONSerialization.jsonObject(with: restored) as? [String: Any],
              let restoredQPDF = restoredRoot["qpdf"] as? [Any],
              let restoredUpdates = restoredQPDF[1] as? [String: [String: Any]],
              let restoredForm = restoredUpdates["obj:2 0 R"]?["value"] as? [String: Any] else { throw failure() }
        try require(restoredForm["/Fields"] as? [String] == ["7 0 R", "8 0 R", "11 0 R", "5 0 R", "9 0 R"])
        try require(restoredUpdates["obj:7 0 R"] == nil && restoredUpdates["obj:8 0 R"] == nil)
        var restoredObjects = omitted
        for (key, value) in restoredUpdates { restoredObjects[key] = value }
        try require(try patch(jsonData: data(restoredObjects), baseline: omittedBaseline) == nil)
        for change in ["name", "bounds", "parent", "kids", "existing-name", "duplicate-baseline"] {
            var invalid = omitted, witness = omittedBaseline, candidate = widget
            switch change {
            case "name": candidate["/T"] = "u:unrecorded-name"
            case "bounds": candidate["/Rect"] = [21, 20, 120, 40]
            case "parent": candidate["/Parent"] = "7 0 R"
            case "kids": candidate["/Kids"] = [Any]()
            case "existing-name": invalid["obj:8 0 R"] = record(["/FT": "/Tx", "/T": "u:/field"])
            default: witness.terminalFields.append(witness.terminalFields[0])
            }
            invalid["obj:5 0 R"] = record(candidate)
            try rejects(invalid, witness)
        }
        // First writes with no AcroForm already pass qpdf in both exact
        // fixtures. They must not be rejected or gain an invented form tree.
        var noForm = objects
        noForm["obj:1 0 R"] = record(["/Type": "/Catalog"])
        guard let noFormPatch = try patch(jsonData: data(noForm), baseline: baseline),
              let noFormRoot = try JSONSerialization.jsonObject(with: noFormPatch) as? [String: Any],
              let noFormQPDF = noFormRoot["qpdf"] as? [Any],
              let noFormUpdates = noFormQPDF[1] as? [String: [String: Any]] else { throw failure() }
        try require(noFormUpdates["obj:1 0 R"] == nil)
        // The exact macOS 27 checkbox has /V=u:Yes, no /AS, and a single
        // normal Form stream. Require its own pre-writer checked-box witness.
        var single = noForm, singleBaseline = baseline
        let singleName = Data("single-checkbox".utf8)
        let singleBox: [String: Any] = ["/Type": "/Annot", "/Subtype": "/Widget", "/FT": "/Btn",
            "/T": "u:single-checkbox", "/V": "u:Yes", "/Rect": [150, 140, 175, 165], "/AP": ["/N": "40 0 R"]]
        single["obj:14 0 R"] = record(singleBox)
        single["obj:4 0 R"] = ["value": ["5 0 R", "14 0 R", "20 0 R", "21 0 R"]]
        var boxWitness = TerminalField(page: 0, name: singleName, type: "/Btn", bounds: [150, 140, 25, 25])
        boxWitness.checkedBoxValue = Data("Yes".utf8)
        singleBaseline.terminalFields = [boxWitness]; singleBaseline.fieldNameCounts[singleName] = 1
        guard let singlePatch = try patch(jsonData: data(single), baseline: singleBaseline),
              let singleRoot = try JSONSerialization.jsonObject(with: singlePatch) as? [String: Any],
              let singleQPDF = singleRoot["qpdf"] as? [Any],
              let singleUpdates = singleQPDF[1] as? [String: [String: Any]],
              let singleValue = singleUpdates["obj:14 0 R"]?["value"] as? [String: Any] else { throw failure() }
        try require(singleValue["/V"] as? String == "/Yes" && singleValue["/AS"] == nil)
        try require(NSDictionary(dictionary: singleValue["/AP"] as? [String: Any] ?? [:]).isEqual(to: singleBox["/AP"] as? [String: Any] ?? [:]))
        try require(singleUpdates["obj:40 0 R"] == nil && singleUpdates["obj:1 0 R"] == nil)
        for change in ["name", "bounds", "state", "page", "duplicate-name", "radio", "pushbutton", "parent"] {
            var invalid = single, candidate = singleBox, witnessed = singleBaseline
            switch change {
            case "name": candidate["/T"] = "u:another-checkbox"
            case "bounds": candidate["/Rect"] = [151, 140, 175, 165]
            case "state": witnessed.terminalFields[0].checkedBoxValue = Data("Other".utf8)
            case "page": witnessed.terminalFields = [TerminalField(page: 1, name: singleName, type: "/Btn", bounds: [150, 140, 25, 25], checkedBoxValue: Data("Yes".utf8))]
            case "duplicate-name": witnessed.fieldNameCounts[singleName] = 2
            case "radio": candidate["/Ff"] = 1 << 15
            case "pushbutton": candidate["/Ff"] = 1 << 16
            default:
                // Object 11 has a valid /Yes state through its other child.
                // Reusing it would test inherited AP evidence, not the flat
                // single-appearance witness that this negative isolates.
                candidate["/Parent"] = "15 0 R"
                invalid["obj:15 0 R"] = record(["/FT": "/Btn", "/T": "u:parent-without-states", "/Kids": ["14 0 R"]])
            }
            invalid["obj:14 0 R"] = record(candidate)
            try rejects(invalid, witnessed)
        }
        // Conversely, a real parent/child group may prove the value using its
        // appearance states. Preserve that supported path with valid backlinks.
        var inherited = single, inheritedBox = singleBox
        inherited["obj:1 0 R"] = objects["obj:1 0 R"]
        inheritedBox["/Parent"] = "11 0 R"
        inherited["obj:14 0 R"] = record(inheritedBox)
        inherited["obj:12 0 R"] = ["value": ["13 0 R", "14 0 R"]]
        guard let inheritedPatch = try patch(jsonData: data(inherited), baseline: singleBaseline),
              let inheritedRoot = try JSONSerialization.jsonObject(with: inheritedPatch) as? [String: Any],
              let inheritedQPDF = inheritedRoot["qpdf"] as? [Any],
              let inheritedUpdates = inheritedQPDF[1] as? [String: [String: Any]],
              let inheritedValue = inheritedUpdates["obj:14 0 R"]?["value"] as? [String: Any] else { throw failure() }
        try require(inheritedValue["/V"] as? String == "/Yes")
        try require(inheritedValue["/Parent"] as? String == "11 0 R")
        // Actual macOS 27 qpdf JSON contains /Open:1 for an independently
        // authored popup whose pre-writer raw value and getter were true.
        let popupText = "Independent popup contents"
        let independentPopup: [String: Any] = ["/Type": "/Annot", "/Subtype": "/Popup", "/F": 4,
            "/Rect": [330, 100, 470, 190], "/Contents": "u:" + popupText, "/Open": 1]
        var openRecords = objects, openBaseline = baseline
        openRecords["obj:24 0 R"] = record(independentPopup)
        openRecords["obj:4 0 R"] = ["value": ["5 0 R", "20 0 R", "21 0 R", "24 0 R"]]
        openBaseline.popups = [PopupWitness(page: 0, bounds: [330, 100, 140, 90], contents: Data(popupText.utf8), isOpen: true)]
        for opened in [true, false] {
            var records = openRecords, captured = openBaseline, popupValue = independentPopup
            popupValue["/Open"] = opened ? 1 : 0; records["obj:24 0 R"] = record(popupValue)
            captured.popups = [PopupWitness(page: 0, bounds: [330, 100, 140, 90], contents: Data(popupText.utf8), isOpen: opened)]
            guard let corrected = try patch(jsonData: data(records), baseline: captured),
                  let root = try JSONSerialization.jsonObject(with: corrected) as? [String: Any],
                  let qpdf = root["qpdf"] as? [Any], let correctedRecords = qpdf[1] as? [String: [String: Any]],
                  var restoredPopup = correctedRecords["obj:24 0 R"]?["value"] as? [String: Any],
                  let state = restoredPopup["/Open"] as? NSNumber else { throw failure() }
            try require(CFGetTypeID(state) == CFBooleanGetTypeID() && state.boolValue == opened)
            restoredPopup.removeValue(forKey: "/Open"); popupValue.removeValue(forKey: "/Open")
            try require(NSDictionary(dictionary: restoredPopup).isEqual(to: popupValue))
            for (key, value) in correctedRecords { records[key] = value }
            try require(try patch(jsonData: data(records), baseline: captured) == nil)
        }
        for change in ["state", "boolean-state", "number", "fraction", "string", "page", "bounds", "contents", "duplicate", "duplicate-page-reference"] {
            var invalid = openRecords, captured = openBaseline, popupValue = independentPopup
            switch change {
            case "state": popupValue["/Open"] = 0
            case "boolean-state": popupValue["/Open"] = false
            case "number": popupValue["/Open"] = 2
            case "fraction": popupValue["/Open"] = 0.5
            case "string": popupValue["/Open"] = "u:true"
            case "page": captured.popups = [PopupWitness(page: 1, bounds: [330, 100, 140, 90], contents: Data(popupText.utf8), isOpen: true)]
            case "bounds": popupValue["/Rect"] = [331, 100, 470, 190]
            case "contents": popupValue["/Contents"] = "u:Different contents"
            case "duplicate": captured.popups.append(captured.popups[0])
            default: invalid["obj:4 0 R"] = ["value": ["5 0 R", "20 0 R", "21 0 R", "24 0 R", "24 0 R"]]
            }
            invalid["obj:24 0 R"] = record(popupValue)
            try rejects(invalid, captured)
        }
        // Two distinct visible objects cannot be merged merely because their
        // dictionaries currently happen to be equal.
        var ambiguous = objects
        ambiguous["obj:10 0 R"] = record(widget)
        ambiguous["obj:4 0 R"] = ["value": ["5 0 R", "10 0 R", "20 0 R", "21 0 R"]]
        try rejects(ambiguous, baseline)
        var ambiguousText = baseline
        ambiguousText.strings["contents", default: []].insert(Data("/Note#20text".utf8))
        try rejects(objects, ambiguousText)
        var unknown = objects
        var badWidget = widget; badWidget["/V"] = "/unproven-value"
        unknown["obj:5 0 R"] = record(badWidget); unknown["obj:6 0 R"] = record(badWidget)
        try rejects(unknown, baseline)
        var cycle = objects
        var cyclicWidget = widget; cyclicWidget.removeValue(forKey: "/FT"); cyclicWidget["/Parent"] = "5 0 R"
        cycle["obj:5 0 R"] = record(cyclicWidget); cycle["obj:6 0 R"] = record(cyclicWidget)
        try rejects(cycle, baseline)
        var parserRefused = false
        do {
            _ = try patch(jsonData: Data("{private-document-sentinel".utf8), baseline: baseline)
        } catch {
            parserRefused = true
            try require(!error.localizedDescription.contains("private-document-sentinel"))
        }
        try require(parserRefused)
        // Editable-combo custom values are permitted only with explicit flags;
        // a display label shared by different exports remains ambiguous.
        try require(try canonicalChoice("custom", labels: ["Label"], exports: ["export"], preferExport: true, allowsCustom: true) == "custom")
        var refused = false
        do { _ = try canonicalChoice("Same", labels: ["Same", "Same"], exports: ["one", "two"], preferExport: false, allowsCustom: false) }
        catch { refused = true }
        try require(refused)
        // PDF strings are byte-exact even though Swift String equality uses
        // Unicode canonical equivalence. Both values must survive distinctly.
        let composed = "/\u{00e9}", decomposed = "/e\u{0301}"
        let values: Set<Data> = [Data(composed.utf8), Data(decomposed.utf8)]
        try require(values.count == 2)
        let first = try repairStrings(composed, allowed: values).value as? String
        let second = try repairStrings(decomposed, allowed: values).value as? String
        try require(first.map { exact($0, "u:" + composed) } == true)
        try require(second.map { exact($0, "u:" + decomposed) } == true)
    }

    private static func exact(_ left: String, _ right: String) -> Bool { left.utf8.elementsEqual(right.utf8) }

    private static func isWidget(_ item: PDFAnnotation) -> Bool { PDFAnnotationKind.matches(item, .widget) }
    private static func failure() -> NSError {
        NSError(domain: "PDF.NativeStringRepair", code: 1, userInfo: [NSLocalizedDescriptionKey:
            "Não foi possível comprovar os tipos e valores de texto preservados pelo escritor PDF. Nenhuma cópia foi publicada."])
    }
}
