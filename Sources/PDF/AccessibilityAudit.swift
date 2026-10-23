import AppKit
import ApplicationServices
import Foundation

/// Reads providers and the public accessibility client API for this process's own window.
/// It never requests permission, enables VoiceOver, or inspects another application.
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
        var client:AccessibilityClientDiagnostics?
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
    @discardableResult static func write(window:NSWindow,to destination:URL,requiredIdentifiers:[String] = []) async throws -> Report {
        // AX client requests can synchronously message this process's main run loop.
        // Keep all AXUIElement objects inside the worker and await only plain values.
        let title = window.title
        let width = Double(window.frame.width),height = Double(window.frame.height)
        let client = await Task.detached(priority:.utility) {
            OwnProcessAccessibilityClient.inspect(title:title,width:width,height:height)
        }.value
        try Task.checkCancellation()
        // A real client request can materialize SwiftUI's virtual providers. Inspect
        // providers afterwards as well, without private activation flags or fake IDs.
        var report = inspect(window:window,requiredIdentifiers:[])
        report.client = client.diagnostics
        report.traversal = "own-process-public-ax-client-and-own-window-native-view-providers"
        let offset = report.nodes.count
        for node in client.nodes.prefix(max(0,10_000-offset)) {
            report.nodes.append(Node(index:offset+node.index,parent:node.parent.map { offset+$0 },role:node.role,identifier:node.identifier,name:node.name,nativeClass:"AXUIElement",origin:"public-ax-client-own-process"))
            if node.identifier?.hasPrefix("pdf.") == true,OwnProcessAccessibilityClient.actionable.contains(node.role),node.name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty {
                report.findings.append(Finding(code:"unnamed-app-control",node:offset+node.index,detail:"Public AX client returned an interactive app element without an accessible name."))
            }
        }
        if client.nodes.count > max(0,10_000-offset) || client.diagnostics.traversalLimited {
            report.traversalLimited = true
            report.findings.append(Finding(code:"traversal-limit",node:nil,detail:"The public AX client or combined audit exceeded its bounded traversal."))
        }
        let identifiers = Set(report.nodes.compactMap(\.identifier))
        report.missingRequiredIdentifiers = requiredIdentifiers.filter { !identifiers.contains($0) }
        for value in report.missingRequiredIdentifiers { report.findings.append(Finding(code:"missing-required-identifier",node:nil,detail:value)) }
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

struct AccessibilityClientDiagnostics:Codable,Sendable {
    var status:String
    var processTrusted:Bool
    var processID:Int32
    var errorCode:Int32?
    var ownWindowCount = 0
    var matchingWindowCount = 0
    var traversalLimited = false
    var durationSeconds:Double = 0
    var attributeErrors:[String:Int] = [:]
}

private struct OwnAXSnapshot:Sendable {
    struct Node:Sendable {
        var index:Int
        var parent:Int?
        var role:String
        var identifier:String?
        var name:String
    }
    var diagnostics:AccessibilityClientDiagnostics
    var nodes:[Node] = []
}

/// Public API only. Runs away from MainActor so the app can service its own AX IPC.
private enum OwnProcessAccessibilityClient {
    static let actionable:Set<String> = ["AXButton","AXCheckBox","AXRadioButton","AXPopUpButton","AXComboBox","AXTextField","AXSlider","AXMenuButton"]
    static func inspect(title:String,width:Double,height:Double) -> OwnAXSnapshot {
        let started = ProcessInfo.processInfo.systemUptime
        let pid = getpid()
        var result = OwnAXSnapshot(diagnostics:AccessibilityClientDiagnostics(status:"starting",processTrusted:AXIsProcessTrusted(),processID:pid))
        let application = AXUIElementCreateApplication(pid)
        let deadline = started+12
        var seen:[CFHashCode:[AXUIElement]] = [:]
        func finish(_ status:String,error:AXError? = nil) -> OwnAXSnapshot {
            result.diagnostics.status = status
            result.diagnostics.errorCode = error?.rawValue
            result.diagnostics.durationSeconds = ProcessInfo.processInfo.systemUptime-started
            return result
        }
        func bounded() -> Bool {
            if result.diagnostics.traversalLimited || Task.isCancelled || ProcessInfo.processInfo.systemUptime >= deadline || result.nodes.count >= 6_000 {
                result.diagnostics.traversalLimited = true
                return false
            }
            return true
        }
        func attribute(_ element:AXUIElement,_ name:String) -> CFTypeRef? {
            guard bounded() else { return nil }
            // Messaging timeouts belong to each AXUIElement instance. A child's
            // label may be read before visit(child); never rely on inheritance.
            let timeoutStatus = AXUIElementSetMessagingTimeout(element,0.5)
            guard timeoutStatus == .success else {
                result.diagnostics.attributeErrors[String(timeoutStatus.rawValue),default:0] += 1
                result.diagnostics.traversalLimited = true
                return nil
            }
            var value:CFTypeRef?
            let status = AXUIElementCopyAttributeValue(element,name as CFString,&value)
            guard status == .success else {
                result.diagnostics.attributeErrors[String(status.rawValue),default:0] += 1
                if status == .cannotComplete { result.diagnostics.traversalLimited = true }
                return nil
            }
            return value
        }
        func string(_ element:AXUIElement,_ name:String) -> String? { attribute(element,name) as? String }
        func own(_ element:AXUIElement) -> Bool {
            var elementPID:pid_t = 0
            return AXUIElementGetPid(element,&elementPID) == .success && elementPID == pid
        }
        func elements(_ value:CFTypeRef?) -> [AXUIElement] {
            guard let array = value as? [AnyObject] else { return [] }
            return array.compactMap { object in
                guard CFGetTypeID(object) == AXUIElementGetTypeID() else { return nil }
                return Optional(object as! AXUIElement)
            }.filter { own($0) }
        }
        func children(_ element:AXUIElement) -> [AXUIElement] { elements(attribute(element,kAXChildrenAttribute)) }
        func name(_ element:AXUIElement,depth:Int = 0) -> String {
            for key in [kAXDescriptionAttribute,kAXTitleAttribute,kAXPlaceholderValueAttribute,kAXHelpAttribute] {
                if let value = string(element,key),!value.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { return String(value.prefix(256)) }
            }
            guard depth < 2 else { return "" }
            for child in children(element).prefix(12) {
                if string(child,kAXRoleAttribute) == "AXStaticText",let text = string(child,kAXValueAttribute),!text.isEmpty { return String(text.prefix(256)) }
            }
            return ""
        }
        func visit(_ element:AXUIElement,parent:Int?,depth:Int) {
            guard bounded() else { return }
            guard depth <= 60 else { result.diagnostics.traversalLimited = true; return }
            guard own(element) else { return }
            let hash = CFHash(element)
            if seen[hash,default:[]].contains(where: { CFEqual($0,element) }) { return }
            seen[hash,default:[]].append(element)
            let index = result.nodes.count
            let role = string(element,kAXRoleAttribute) ?? "unknown"
            let identifier = string(element,kAXIdentifierAttribute)
            let label = name(element)
            result.nodes.append(OwnAXSnapshot.Node(index:index,parent:parent,role:role,identifier:identifier,name:label))
            for child in children(element) { visit(child,parent:index,depth:depth+1) }
        }
        var rawWindows:CFTypeRef?
        let applicationTimeout = AXUIElementSetMessagingTimeout(application,0.5)
        guard applicationTimeout == .success else {
            result.diagnostics.traversalLimited = true
            return finish("own-process-timeout-unavailable",error:applicationTimeout)
        }
        let windowsStatus = AXUIElementCopyAttributeValue(application,kAXWindowsAttribute as CFString,&rawWindows)
        guard windowsStatus == .success else {
            if windowsStatus == .cannotComplete { result.diagnostics.traversalLimited = true }
            return finish("own-windows-unavailable",error:windowsStatus)
        }
        let windows = elements(rawWindows)
        result.diagnostics.ownWindowCount = windows.count
        let matches = windows.filter { window in
            guard string(window,kAXTitleAttribute) == title,
                  let rawSize = attribute(window,kAXSizeAttribute),CFGetTypeID(rawSize) == AXValueGetTypeID() else { return false }
            let value = rawSize as! AXValue
            guard AXValueGetType(value) == .cgSize else { return false }
            var size = CGSize.zero
            return AXValueGetValue(value,.cgSize,&size) && abs(Double(size.width)-width) < 2 && abs(Double(size.height)-height) < 2
        }
        result.diagnostics.matchingWindowCount = matches.count
        guard matches.count == 1,let selected = matches.first else { return finish(matches.isEmpty ? "own-window-not-matched" : "ambiguous-own-window") }
        visit(selected,parent:nil,depth:0)
        return finish(result.diagnostics.traversalLimited ? "own-window-traversal-limited" : "own-window-read")
    }
}
