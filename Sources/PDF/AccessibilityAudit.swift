import AppKit
import Foundation

/// Reads the current process's own accessibility objects. This never uses AXUIElement,
/// requests Accessibility permission, enables VoiceOver, or inspects another application.
@MainActor enum AccessibilityAudit {
    struct Node:Codable {
        var index:Int
        var parent:Int?
        var role:String
        var identifier:String?
        var name:String
        var nativeClass:String
        var origin:String
    }
    struct Finding:Codable {
        var code:String
        var node:Int?
        var detail:String
    }
    struct Report:Codable {
        var version = 1
        var capturedAt = Date()
        var scope = "current-process-own-window"
        var windowTitle:String
        var nodes:[Node]
        var findings:[Finding]
        var missingRequiredIdentifiers:[String]
        var keyboardViewOrder:[String]
        var traversalLimited:Bool
        var traversal = "accessibility-children-and-own-window-native-view-providers"
        var manualChecks = ["VoiceOver spoken output and interaction", "Contrast in all user-selected colors", "Semantic correctness and reading order of the PDF", "Keyboard traversal through all lazy and off-screen content"]
        var passedRequiredIdentifiers:Bool { missingRequiredIdentifiers.isEmpty && !nodes.isEmpty && !traversalLimited }
    }
    static func inspect(window:NSWindow,requiredIdentifiers:[String] = []) -> Report {
        window.contentView?.layoutSubtreeIfNeeded()
        var nodes:[Node] = []
        var findings:[Finding] = []
        var indices:[ObjectIdentifier:Int] = [:]
        var nativeViews = Set<ObjectIdentifier>()
        var limited = false
        let actionable:Set<String> = ["AXButton","AXCheckBox","AXRadioButton","AXPopUpButton","AXComboBox","AXTextField","AXSlider","AXMenuButton"]
        @discardableResult func visit(_ object:NSObject,parent:Int?,depth:Int,origin:String) -> Int? {
            if let index = indices[ObjectIdentifier(object)] { return index }
            guard depth <= 60,nodes.count < 10_000 else { limited = true; return nil }
            let role = string(object,"accessibilityRole") ?? "unknown"
            let identifier = string(object,"accessibilityIdentifier")
            let label = accessibleName(object)
            let index = nodes.count
            indices[ObjectIdentifier(object)] = index
            nodes.append(Node(index:index,parent:parent,role:role,identifier:identifier,name:String(label.prefix(256)),nativeClass:NSStringFromClass(type(of:object)),origin:origin))
            if actionable.contains(role),label.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty {
                findings.append(Finding(code:identifier?.hasPrefix("pdf.") == true ? "unnamed-app-control" : "unnamed-control-review",node:index,detail:"Interactive element has no exposed label, title, placeholder, or text child."))
            }
            for item in children(of:object) { visit(item,parent:index,depth:depth+1,origin:"accessibility-child") }
            return index
        }
        func visitNativeView(_ view:NSView,parent:Int?,depth:Int) {
            guard depth <= 60,nodes.count < 10_000 else { limited = true; return }
            guard nativeViews.insert(ObjectIdentifier(view)).inserted else { return }
            let index = visit(view,parent:parent,depth:depth,origin:"native-view-provider") ?? parent
            for child in view.subviews { visitNativeView(child,parent:index,depth:depth+1) }
        }
        visit(window,parent:nil,depth:0,origin:"window")
        // NavigationSplitView nests column hosting views behind ignored AppKit wrappers.
        // A hosting root can expose no AX children until a system accessibility client is
        // attached. Inspect each actual in-process view's public AX provider as well; do
        // not enable private AX flags, synthesize labels or claim this is VoiceOver output.
        if let content = window.contentView { visitNativeView(content.superview ?? content,parent:0,depth:1) }
        let identifiers = Set(nodes.compactMap(\.identifier))
        let missing = requiredIdentifiers.filter { !identifiers.contains($0) }
        for value in missing { findings.append(Finding(code:"missing-required-identifier",node:nil,detail:value)) }
        if limited { findings.append(Finding(code:"traversal-limit",node:nil,detail:"Only the first 10,000 nodes and 60 levels were inspected.")) }
        return Report(windowTitle:window.title,nodes:nodes,findings:findings,missingRequiredIdentifiers:missing,keyboardViewOrder:keyViewOrder(window),traversalLimited:limited)
    }
    @discardableResult static func write(window:NSWindow,to destination:URL,requiredIdentifiers:[String] = []) throws -> Report {
        let report = inspect(window:window,requiredIdentifiers:requiredIdentifiers)
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted,.sortedKeys]; encoder.dateEncodingStrategy = .iso8601
        try NativeOutput.write(encoder.encode(report),to:destination)
        return report
    }
    private static func accessibleName(_ object:NSObject,depth:Int = 0) -> String {
        for property in ["accessibilityLabel","accessibilityTitle","accessibilityPlaceholderValue","accessibilityHelp"] {
            if let value = string(object,property),!value.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { return value }
        }
        guard depth < 3 else { return "" }
        if let title = attribute(object,"accessibilityTitleUIElement") as? NSObject,title !== object {
            let name = accessibleName(title,depth:depth+1); if !name.isEmpty { return name }
        }
        for item in children(of:object).prefix(12) {
            if string(item,"accessibilityRole") == "AXStaticText",let text = attribute(item,"accessibilityValue") as? String,!text.isEmpty { return text }
            let name = accessibleName(item,depth:depth+1); if !name.isEmpty { return name }
        }
        return ""
    }
    /// Only Objective-C object-returning getters are called through perform; no primitive
    /// or struct-returning selector is dynamically invoked.
    private static func attribute(_ object:NSObject,_ name:String) -> Any? {
        let selector = NSSelectorFromString(name)
        if object.responds(to:selector),let value = object.perform(selector)?.takeUnretainedValue() { return value }
        // AppKit can return cell/reparenting proxies that expose the public legacy
        // attribute protocol instead of modern getters. Query only advertised keys.
        let legacyNames = ["accessibilityRole":"AXRole","accessibilityIdentifier":"AXIdentifier",
                           "accessibilityLabel":"AXDescription","accessibilityTitle":"AXTitle",
                           "accessibilityPlaceholderValue":"AXPlaceholderValue","accessibilityHelp":"AXHelp",
                           "accessibilityTitleUIElement":"AXTitleUIElement","accessibilityValue":"AXValue",
                           "accessibilityChildren":"AXChildren"]
        guard let key = legacyNames[name] else { return nil }
        let namesSelector = NSSelectorFromString("accessibilityAttributeNames")
        let valueSelector = NSSelectorFromString("accessibilityAttributeValue:")
        guard object.responds(to:namesSelector),object.responds(to:valueSelector),
              let supported = object.perform(namesSelector)?.takeUnretainedValue() as? [String],supported.contains(key) else { return nil }
        return object.perform(valueSelector,with:key)?.takeUnretainedValue()
    }
    private static func string(_ object:NSObject,_ name:String) -> String? { attribute(object,name) as? String }
    private static func children(of object:NSObject) -> [NSObject] {
        var seen = Set<ObjectIdentifier>()
        return ["accessibilityChildren","accessibilityChildrenInNavigationOrder"].flatMap {
            (attribute(object,$0) as? [Any] ?? []).compactMap { $0 as? NSObject }
        }.filter { seen.insert(ObjectIdentifier($0)).inserted }
    }
    private static func keyViewOrder(_ window:NSWindow) -> [String] {
        var result:[String] = []
        var visited = Set<ObjectIdentifier>()
        var next = window.initialFirstResponder ?? window.contentView
        while let view = next,result.count < 500,visited.insert(ObjectIdentifier(view)).inserted {
            let identifier = string(view,"accessibilityIdentifier")
            result.append(identifier ?? NSStringFromClass(type(of:view)))
            next = view.nextKeyView
        }
        return result
    }
}
