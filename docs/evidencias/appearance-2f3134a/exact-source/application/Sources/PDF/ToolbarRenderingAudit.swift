import AppKit
import CryptoKit
import Foundation

/// A deliberately narrow regression gate for the three real workspace toolbar
/// symbols. Reads the original WindowServer PNG; never draws, repairs, crops to
/// a fixed location, changes appearance, or substitutes a view bitmap.
@MainActor enum ToolbarRenderingAudit {
    nonisolated static let argument = "--render-appearance-preview"
    static let identifiers = ["autoSidebar", "pdf.commands.toolbar", "pdf.customize.toolbar"]
    static let minimumContrast = 3.0
    private final class ViewIdentity {
        weak var view:NSView?
        let token = UUID().uuidString
        init(_ view:NSView) { self.view = view }
    }
    private static var viewIdentities:[ObjectIdentifier:ViewIdentity] = [:]
    private static func token(for view:NSView) -> String {
        let key = ObjectIdentifier(view)
        if let record = viewIdentities[key], record.view === view { return record.token }
        let record = ViewIdentity(view); viewIdentities[key] = record
        return record.token
    }

    struct Rect: Codable, Equatable {
        let x: Double, y: Double, width: Double, height: Double
        init(_ value: CGRect) {
            x = value.minX; y = value.minY; width = value.width; height = value.height
        }
        var cgRect: CGRect { CGRect(x:x,y:y,width:width,height:height) }
    }
    struct Control: Codable, Equatable {
        let auditKey: String
        let identifier: String?
        let label: String
        let identity: String
        let screenFrame: Rect
        let windowFrame: Rect
        let effectiveAppearance: String
        let effectiveStyle: String
        let identification: String
    }
    struct Snapshot: Codable {
        let uptime: Double
        let windowNumber: Int
        let windowFrame: Rect
        let backingScale: Double
        let selection: String
        let applicationOverride: String?
        let applicationEffectiveAppearance: String
        let applicationEffectiveStyle: String
        let windowOverride: String?
        let windowEffectiveAppearance: String
        let windowEffectiveStyle: String
        let contentEffectiveAppearance: String?
        let contentEffectiveStyle: String?
        let toolbarEffectiveAppearances: [String]
        let toolbarEffectiveStyles: [String]
        let toolbarItemIdentifiers: [String]
        let windowToolbarPresent: Bool
        let windowToolbarVisible: Bool
        let workspaceToolbarProviderCount: Int
        let controls: [Control]
        let errors: [String]
    }
    struct Measurement: Codable {
        let auditKey: String
        let pixelBounds: Rect
        let centralPixelBounds: Rect
        let sampleCount: Int
        let minimumRGB: [Int]
        let maximumRGB: [Int]
        let luminanceP05: Double
        let luminanceP95: Double
        let centralContrast: Double
        let minimumContrast: Double
        let passed: Bool
    }
    struct Report: Codable {
        var schemaVersion = 1
        var scope = "three-own-window-toolbar-symbols-central-pixels"
        let before: Snapshot
        let after: Snapshot
        let measurements: [Measurement]
        let errors: [String]
        let passed: Bool
        var universalWCAGCertification = false
        var humanVisualReview = false
        var methodology = "Public AXToolbar direct AXButton children; typed NSView.accessibilityFrame in AppKit screen coordinates; window.convertFromScreen, top-left PNG conversion and observed scale. Central square is 60% of the smaller control dimension, excluding the platter border. sRGB relative luminance p95/p05 contrast must reach 3:1. No image editing, fixed screen coordinates, fallback rendering or visual retry."
    }
    struct Frame: Codable {
        let phase: String
        let selection: String
        let png: String
        let bytes: Int
        let sha256: String
        let width: Int
        let height: Int
        let windowSnapshot: Snapshot
        let toolbarReport: Report?
    }
    struct Check: Codable {
        let id: String
        let passed: Bool
    }
    struct SequenceReport: Codable {
        var schemaVersion = 1
        var scope = "appearance-only-real-window"
        var source = "WindowServer-ScreenCaptureKit"
        let createdAt: Date
        let status: String
        let frames: [Frame]
        let checks: [Check]
        let providersRecreatedAfterCustomization: Bool
        let failure: String?
        let operatingSystem: String
        var nativeDeadlineSeconds = 70
        var cleanupMaximumSeconds = 3
        var engineUsed = false
        var documentsOpened = false
        var humanVisualReview = false
        var universalWCAGCertification = false
    }

    private static func attribute(_ object: NSObject, _ name: String) -> Any? {
        // Only object-returning public AX getters. In particular, never perform
        // accessibilityFrame: NSRect is read through the typed NSView API below.
        let selector = NSSelectorFromString(name)
        guard object.responds(to:selector) else { return nil }
        return object.perform(selector)?.takeUnretainedValue()
    }
    private static func string(_ object: NSObject, _ name: String) -> String? {
        attribute(object,name) as? String
    }
    private static func children(_ object: NSObject) -> [NSObject] {
        (attribute(object,"accessibilityChildren") as? [Any] ?? []).compactMap { $0 as? NSObject }
    }
    private static func name(_ object: NSObject) -> String {
        for key in ["accessibilityLabel","accessibilityTitle","accessibilityHelp"] {
            if let value = string(object,key), !value.isEmpty { return value }
        }
        return ""
    }
    private static func appearance(_ value: NSAppearance) -> String { value.name.rawValue }
    private static func style(_ value: NSAppearance) -> String {
        guard let match = value.bestMatch(from:[.aqua,.darkAqua]) else { return "unknown" }
        return match == .darkAqua ? "dark" : match == .aqua ? "light" : "unknown"
    }
    private static func frameIsValid(_ value: CGRect) -> Bool {
        [value.minX,value.minY,value.width,value.height].allSatisfy(\.isFinite)
            && value.width > 0 && value.height > 0
    }

    /// Uses the public provider tree already witnessed in the original AX
    /// reports: AXToolbar has the two identified app buttons and one named
    /// system sidebar button as direct children. Unknown/ambiguous providers
    /// fail closed; internal SwiftUI duplicates are never selected by ID alone.
    static func observe(window: NSWindow, selection: String, requiresWorkspaceToolbar:Bool = true) -> Snapshot {
        viewIdentities = viewIdentities.filter { $0.value.view != nil }
        var toolbars: [NSView] = []
        var seen = Set<ObjectIdentifier>()
        var errors: [String] = []
        var visited = 0
        if !window.isVisible || window.windowNumber <= 0 || window.contentView == nil {
            errors.append("The real application window/content is unavailable.")
        }
        if children(window).isEmpty { errors.append("The public own-window provider root exposed no children.") }
        func visit(_ object: NSObject, depth: Int) {
            guard seen.insert(ObjectIdentifier(object)).inserted else { return }
            visited += 1
            guard depth <= 60, visited <= 10_000 else {
                errors.append("Public provider traversal exceeded its bound."); return
            }
            if string(object,"accessibilityRole") == "AXToolbar",
               let view = object as? NSView, view.window === window {
                toolbars.append(view)
            }
            for child in children(object) { visit(child,depth:depth+1) }
            if let view = object as? NSView {
                for child in view.subviews { visit(child,depth:depth+1) }
            }
        }
        visit(window,depth:0)
        if let content = window.contentView { visit(content.superview ?? content,depth:1) }
        var controls: [Control] = []
        var workspaceToolbars = 0
        let sidebarNames: Set<String> = ["Hide Sidebar","Show Sidebar","Ocultar Barra Lateral",
            "Mostrar Barra Lateral","Ocultar barra lateral","Mostrar barra lateral"]
        for toolbar in toolbars {
            let buttons = children(toolbar).filter { string($0,"accessibilityRole") == "AXButton" }
            let ids = Set(buttons.compactMap { string($0,"accessibilityIdentifier") })
            guard ids.contains("pdf.commands.toolbar"), ids.contains("pdf.customize.toolbar") else { continue }
            workspaceToolbars += 1
            for object in buttons {
                let identifier = string(object,"accessibilityIdentifier")
                let label = name(object)
                let key: String
                if identifier == "pdf.commands.toolbar" || identifier == "pdf.customize.toolbar" {
                    key = identifier!
                } else if (identifier ?? "").isEmpty, sidebarNames.contains(label) {
                    key = "autoSidebar"
                } else { continue }
                guard let view = object as? NSView, view.window === window,
                      !view.isHiddenOrHasHiddenAncestor else {
                    errors.append("Required toolbar button is not a visible NSView provider: " + key); continue
                }
                let screenFrame = view.accessibilityFrame()
                let local = window.convertFromScreen(screenFrame)
                let fullWindow = CGRect(origin:.zero,size:window.frame.size)
                guard frameIsValid(screenFrame), frameIsValid(local), fullWindow.contains(local) else {
                    errors.append("Required toolbar provider has invalid/outside screen bounds: \(key); screen=\(screenFrame); window=\(local); full=\(fullWindow)"); continue
                }
                controls.append(Control(auditKey:key,identifier:identifier,label:label,
                    identity:token(for:view),screenFrame:Rect(screenFrame),windowFrame:Rect(local),
                    effectiveAppearance:appearance(view.effectiveAppearance),
                    effectiveStyle:style(view.effectiveAppearance),
                    identification:key == "autoSidebar" ? "direct-public-AXToolbar-button-observed-sidebar-label" : "direct-public-AXToolbar-button-identifier"))
            }
        }
        if requiresWorkspaceToolbar {
            for key in identifiers where controls.filter({ $0.auditKey == key }).count != 1 {
                errors.append("Expected exactly one direct toolbar control: " + key)
            }
            if window.toolbar == nil || window.toolbar?.isVisible != true { errors.append("The actual window toolbar is absent or hidden.") }
        }
        return Snapshot(uptime:ProcessInfo.processInfo.systemUptime,windowNumber:window.windowNumber,
            windowFrame:Rect(window.frame),backingScale:window.backingScaleFactor,selection:selection,
            applicationOverride:NSApp?.appearance?.name.rawValue,
            applicationEffectiveAppearance:NSApp.map { appearance($0.effectiveAppearance) } ?? "application-absent",
            applicationEffectiveStyle:NSApp.map { style($0.effectiveAppearance) } ?? "unknown",
            windowOverride:window.appearance?.name.rawValue,windowEffectiveAppearance:appearance(window.effectiveAppearance),
            windowEffectiveStyle:style(window.effectiveAppearance),
            contentEffectiveAppearance:window.contentView.map { appearance($0.effectiveAppearance) },
            contentEffectiveStyle:window.contentView.map { style($0.effectiveAppearance) },
            toolbarEffectiveAppearances:toolbars.map { appearance($0.effectiveAppearance) },
            toolbarEffectiveStyles:toolbars.map { style($0.effectiveAppearance) },
            toolbarItemIdentifiers:window.toolbar?.items.map { $0.itemIdentifier.rawValue } ?? [],
            windowToolbarPresent:window.toolbar != nil,windowToolbarVisible:window.toolbar?.isVisible == true,
            workspaceToolbarProviderCount:workspaceToolbars,
            controls:controls.sorted { $0.auditKey < $1.auditKey },errors:errors)
    }

    private static func png(_ path: URL) throws -> (Data, NSBitmapImageRep) {
        let size = try path.resourceValues(forKeys:[.fileSizeKey,.isRegularFileKey])
        guard size.isRegularFile == true, let bytes = size.fileSize, bytes > 0, bytes <= 80 * 1024 * 1024 else {
            throw failure("Original PNG is not a bounded regular file.")
        }
        let raw = try Data(contentsOf:path,options:.mappedIfSafe)
        guard raw.count == bytes, Array(raw.prefix(8)) == [137,80,78,71,13,10,26,10],
              let bitmap = NSBitmapImageRep(data:raw), bitmap.pixelsWide > 100, bitmap.pixelsHigh > 100 else {
            throw failure("Original WindowServer PNG could not be decoded.")
        }
        return (raw,bitmap)
    }
    private static func linear(_ value: Double) -> Double {
        value <= 0.04045 ? value / 12.92 : pow((value + 0.055)/1.055,2.4)
    }

    static func inspect(window: NSWindow, png path: URL, before: Snapshot, selection: String) throws -> Report {
        let after = observe(window:window,selection:selection)
        let (_,bitmap) = try png(path)
        var errors = before.errors + after.errors
        if before.selection != selection || after.selection != selection
            || !["light","dark","system"].contains(selection) {
            errors.append("Requested appearance selection changed during capture or is unknown.")
        }
        for snapshot in [before,after] {
            let expected = selection == "system" ? snapshot.applicationEffectiveStyle : selection
            let styles = [snapshot.applicationEffectiveStyle,snapshot.windowEffectiveStyle,
                snapshot.contentEffectiveStyle ?? "unknown"] + snapshot.toolbarEffectiveStyles + snapshot.controls.map(\.effectiveStyle)
            if !["light","dark"].contains(expected) || snapshot.toolbarEffectiveStyles.isEmpty
                || !styles.allSatisfy({ $0 == expected }) {
                errors.append("App/window/content/toolbar effective appearance does not match the requested theme.")
            }
            if selection == "system", snapshot.applicationOverride != nil || snapshot.windowOverride != nil {
                errors.append("System selection retained an AppKit application/window appearance override.")
            }
        }
        if before.applicationOverride != after.applicationOverride || before.windowOverride != after.windowOverride
            || before.applicationEffectiveAppearance != after.applicationEffectiveAppearance
            || before.windowEffectiveAppearance != after.windowEffectiveAppearance
            || before.contentEffectiveAppearance != after.contentEffectiveAppearance
            || before.toolbarEffectiveAppearances != after.toolbarEffectiveAppearances {
            errors.append("Effective appearance changed during the original capture.")
        }
        let stableGeometry = before.windowNumber == after.windowNumber && before.windowFrame == after.windowFrame
            && before.backingScale == after.backingScale && before.controls == after.controls
        if !stableGeometry {
            errors.append("Toolbar identity, appearance or geometry changed during the original capture.")
        }
        let scaleX = Double(bitmap.pixelsWide) / before.windowFrame.width
        let scaleY = Double(bitmap.pixelsHigh) / before.windowFrame.height
        let validScale = scaleX.isFinite && scaleY.isFinite && abs(scaleX-scaleY) <= 0.01 && abs(scaleX-before.backingScale) <= 0.01
        if !validScale {
            errors.append("PNG/window/backing scales disagree.")
        }
        var measurements: [Measurement] = []
        // Incorrect traits remain a failure but do not hide pixel evidence when
        // the original PNG and public control geometry are safely aligned.
        if before.errors.isEmpty && after.errors.isEmpty && stableGeometry && validScale {
            for control in before.controls {
                let local = control.windowFrame
                let pixel = CGRect(x:local.x*scaleX,y:(before.windowFrame.height-local.y-local.height)*scaleY,
                    width:local.width*scaleX,height:local.height*scaleY)
                let side = min(pixel.width,pixel.height)*0.60
                let central = CGRect(x:ceil(pixel.midX-side/2),y:ceil(pixel.midY-side/2),
                    width:floor(pixel.midX+side/2)-ceil(pixel.midX-side/2),
                    height:floor(pixel.midY+side/2)-ceil(pixel.midY-side/2))
                guard frameIsValid(pixel), frameIsValid(central), central.width >= 6, central.height >= 6,
                      CGRect(x:0,y:0,width:CGFloat(bitmap.pixelsWide),height:CGFloat(bitmap.pixelsHigh)).contains(central) else {
                    errors.append("Central symbol sample has invalid/outside bounds: " + control.auditKey); continue
                }
                var luminances: [Double] = []
                var minimum = [255,255,255], maximum = [0,0,0]
                for y in Int(central.minY)..<Int(central.maxY) {
                    for x in Int(central.minX)..<Int(central.maxX) {
                        guard let color = bitmap.colorAt(x:x,y:y)?.usingColorSpace(.sRGB), color.alphaComponent >= 0.99 else {
                            throw failure("A central symbol pixel is not opaque sRGB-convertible data.")
                        }
                        let values = [Double(color.redComponent),Double(color.greenComponent),Double(color.blueComponent)]
                        guard values.allSatisfy({ $0.isFinite && $0 >= 0 && $0 <= 1 }) else { throw failure("Invalid PNG color component.") }
                        for index in 0..<3 {
                            let value = Int((values[index]*255).rounded())
                            minimum[index] = min(minimum[index],value); maximum[index] = max(maximum[index],value)
                        }
                        luminances.append(0.2126*linear(values[0])+0.7152*linear(values[1])+0.0722*linear(values[2]))
                    }
                }
                luminances.sort()
                let low = luminances[Int(Double(luminances.count-1)*0.05)]
                let high = luminances[Int(Double(luminances.count-1)*0.95)]
                let contrast = (high+0.05)/(low+0.05)
                let passed = contrast >= minimumContrast
                measurements.append(Measurement(auditKey:control.auditKey,pixelBounds:Rect(pixel),centralPixelBounds:Rect(central),
                    sampleCount:luminances.count,minimumRGB:minimum,maximumRGB:maximum,luminanceP05:low,luminanceP95:high,
                    centralContrast:contrast,minimumContrast:minimumContrast,passed:passed))
                if !passed { errors.append("Central toolbar symbol contrast is below 3:1: " + control.auditKey) }
            }
        }
        return Report(before:before,after:after,measurements:measurements,errors:errors,
            passed:errors.isEmpty && measurements.count == 3 && measurements.allSatisfy(\.passed))
    }

    static func frame(window:NSWindow,path: URL, phase: String, selection: String, report: Report?) throws -> Frame {
        let (raw,bitmap) = try png(path)
        return Frame(phase:phase,selection:selection,png:path.lastPathComponent,bytes:raw.count,
            sha256:SHA256.hash(data:raw).map { String(format:"%02x",$0) }.joined(),
            width:bitmap.pixelsWide,height:bitmap.pixelsHigh,
            windowSnapshot:report?.after ?? observe(window:window,selection:selection,requiresWorkspaceToolbar:false),toolbarReport:report)
    }
    static func log(_ report: Report, phase: String) throws {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let payload = try encoder.encode(report)
        FileHandle.standardError.write(Data(("PDF toolbar rendering ["+phase+"]: ").utf8))
        FileHandle.standardError.write(payload); FileHandle.standardError.write(Data("\n".utf8))
    }
    static func failure(_ detail: String) -> NSError {
        NSError(domain:"PDF.ToolbarRenderingAudit",code:1,userInfo:[NSLocalizedDescriptionKey:detail])
    }
}
