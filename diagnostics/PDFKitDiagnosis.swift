import AppKit
import CoreGraphics
import CoreText
import PDFKit
import Darwin

/// Standalone reproduction of the synthetic PDFKit fixture in MacSmokeTests.
/// This records framework behavior; it is not an application approval gate.
@main
struct PDFKitDiagnosis {
    private static let ownerPassword = "native-check-owner-123"
    private static let readerPassword = "native-check-reader-123"

    private struct Inspection: Encodable {
        var schemaVersion = 1
        var opened = false
        var pageCount = 0
        var knownTextPresent = false
        var annotationCount = 0
        var widgetValue: String?
        var isEncrypted = false
        var wasLocked = false
        var unlocked = false
        var unlockAttempted = false
        var emptyPasswordAccepted: Bool?
        var isLockedAfterUnlock = false
        var searchMatchCount = 0
        var highlightCount = 0
        var textWidgetCount = 0
        var failureCode: String?
    }

    @MainActor
    static func main() {
        do {
            _ = NSApplication.shared
            let arguments = CommandLine.arguments
            guard arguments.count >= 2 else { throw failure("invalid-arguments") }
            switch arguments[1] {
            case "generate":
                guard arguments.count == 3 else { throw failure("invalid-arguments") }
                try generate(URL(fileURLWithPath: arguments[2], isDirectory: true))
            case "inspect":
                guard arguments.count == 4 else { throw failure("invalid-arguments") }
                try inspect(URL(fileURLWithPath: arguments[2]), output: URL(fileURLWithPath: arguments[3]))
            case "annotations":
                guard arguments.count == 3 else { throw failure("invalid-arguments") }
                try annotationFixtures(URL(fileURLWithPath: arguments[2], isDirectory: true))
            case "inspect-annotations":
                guard arguments.count == 4 else { throw failure("invalid-arguments") }
                guard let document = PDFDocument(data: try readRegular(URL(fileURLWithPath: arguments[2]))) else { throw failure("annotation-reopen") }
                if document.isLocked { guard document.unlock(withPassword: readerPassword) else { throw failure("annotation-unlock") } }
                let output = URL(fileURLWithPath: arguments[3])
                try writeJSON(annotationSnapshot(document, progressPrefix: output), to: output)
            default:
                throw failure("invalid-arguments")
            }
        } catch {
            // Do not emit paths, PDF contents or password arguments. Framework
            // diagnostics remain available to the bounded, redacting launcher.
            let code = (error as NSError).userInfo["diagnosticCode"] as? String ?? "filesystem-or-framework-failure"
            FileHandle.standardError.write(Data(("PDFKit diagnosis failed: " + code + "\n").utf8))
            exit(1)
        }
    }

    @MainActor
    private static func annotationFixtures(_ directory: URL) throws {
        guard Darwin.mkdir(directory.path, mode_t(0o700)) == 0 else { throw failure("new-private-directory-required") }
        let previousMask = Darwin.umask(mode_t(0o077)); defer { _ = Darwin.umask(previousMask) }
        // Reuse the exact source-generation and unmodified PDFKit fixture path.
        let baseline = directory.appendingPathComponent("baseline", isDirectory: true)
        try generate(baseline)
        for scenario in ["smoke", "preview-note", "editable-defaults", "editable-materialized", "editable-resolved-font", "editable-helvetica15",
                         "editable-space-da-system13", "editable-space-da-helvetica15", "slash-string-values"] {
            guard let document = PDFDocument(url: baseline.appendingPathComponent("source.pdf")), let page = document.page(at: 0) else {
                throw failure("annotation-source")
            }
            if scenario == "smoke" {
                let highlight = PDFAnnotation(bounds: CGRect(x: 72, y: 700, width: 120, height: 24), forType: .highlight, withProperties: nil)
                highlight.color = .systemYellow; page.addAnnotation(highlight)
                let field = PDFAnnotation(bounds: CGRect(x: 72, y: 620, width: 200, height: 30), forType: .widget, withProperties: nil)
                field.widgetFieldType = .text; field.fieldName = "native-test"; field.widgetStringValue = "PDF"; page.addAnnotation(field)
            } else if scenario == "preview-note" {
                let bounds = page.bounds(for: .cropBox)
                let note = PDFAnnotation(bounds: CGRect(x: bounds.minX + 30, y: bounds.maxY - 70, width: 28, height: 28), forType: .text, withProperties: nil)
                note.contents = "Revisar esta passagem antes de concluir o documento."
                note.color = NSColor(srgbRed: 1, green: CGFloat(204) / 255, blue: 0, alpha: 1)
                page.addAnnotation(note)
            } else {
                let types: [PDFAnnotationSubtype] = [.highlight, .underline, .strikeOut, .text, .freeText, .square, .circle, .ink, .line]
                for (index, type) in types.enumerated() {
                    let annotation = PDFAnnotation(bounds: CGRect(x: 60, y: CGFloat(650 - index * 45), width: 140, height: 30), forType: type, withProperties: nil)
                    annotation.contents = "Annotation \(index)"
                    if ["editable-helvetica15", "editable-space-da-helvetica15"].contains(scenario), type == .freeText {
                        guard let font = NSFont(name: "Helvetica", size: 15) else { throw failure("control-font-missing") }
                        annotation.font = font
                    }
                    if scenario == "editable-space-da-system13", type == .freeText { annotation.font = NSFont.systemFont(ofSize: 13) }
                    if scenario == "slash-string-values" {
                        if type == .text { annotation.contents = "/Note text" }
                        if type == .freeText { annotation.contents = "/Text" }
                    }
                    if type == .ink {
                        let path = NSBezierPath(); path.move(to: CGPoint(x: 4, y: 5)); path.line(to: CGPoint(x: 35, y: 20))
                        path.curve(to: CGPoint(x: 120, y: 15), controlPoint1: CGPoint(x: 50, y: 25), controlPoint2: CGPoint(x: 90, y: 5)); annotation.add(path)
                    } else if type == .line {
                        annotation.startPoint = CGPoint(x: 5, y: 5); annotation.endPoint = CGPoint(x: 130, y: 25)
                    } else if [PDFAnnotationSubtype.highlight, .underline, .strikeOut].contains(type) {
                        annotation.quadrilateralPoints = [NSPoint(x: 0, y: 30), NSPoint(x: 140, y: 30), .zero, NSPoint(x: 140, y: 0)].map(NSValue.init(point:))
                    }
                    page.addAnnotation(annotation)
                }
                let text = PDFAnnotation(bounds: CGRect(x: 260, y: 610, width: 230, height: 35), forType: .widget, withProperties: nil)
                text.widgetFieldType = .text; text.fieldName = "roundtrip-text"; text.widgetStringValue = "Editable field"; page.addAnnotation(text)
                let choice = PDFAnnotation(bounds: CGRect(x: 260, y: 540, width: 230, height: 55), forType: .widget, withProperties: nil)
                choice.widgetFieldType = .choice; choice.fieldName = "roundtrip-choice"
                choice.choices = ["First label", "Second label"]; choice.values = ["first", "second"]
                choice.isListChoice = true; choice.widgetStringValue = "second"; page.addAnnotation(choice)
                let checkbox = PDFAnnotation(bounds: CGRect(x: 260, y: 480, width: 25, height: 25), forType: .widget, withProperties: nil)
                checkbox.widgetFieldType = .button; checkbox.widgetControlType = .checkBoxControl; checkbox.fieldName = "roundtrip-checkbox"
                checkbox.buttonWidgetStateString = "Yes"; checkbox.buttonWidgetState = PDFWidgetCellState(rawValue: 1)!; page.addAnnotation(checkbox)
                if scenario == "slash-string-values" {
                    text.fieldName = "/field"; text.widgetStringValue = "/value"; text.widgetDefaultStringValue = "/default"
                    choice.choices = ["/First label", "/Second label"]; choice.values = ["/first", "/second"]
                    choice.widgetStringValue = "/second"
                }
            }
            trace(scenario + " snapshot before")
            let before = directory.appendingPathComponent(scenario + ".before.json")
            try writeJSON(annotationSnapshot(document, progressPrefix: before), to: before)
            if ["editable-materialized", "editable-resolved-font", "editable-helvetica15",
                "editable-space-da-system13", "editable-space-da-helvetica15"].contains(scenario) {
                // Mirror only the setters currently used by the production
                // materializeWriterDefaults helper; keep the original above.
                for item in page.annotations {
                    let subtype = (item.type ?? "").replacingOccurrences(of: "/", with: "").lowercased()
                    if subtype == "freetext" {
                        let font = item.font, fontColor = item.fontColor
                        if let font {
                            if scenario == "editable-resolved-font" {
                                let graphics = CTFontCopyGraphicsFont(font as CTFont, nil)
                                let replacement = CTFontCreateWithGraphicsFont(graphics, font.pointSize, nil, nil) as NSFont
                                try writeJSON(["sameInstance": font === replacement, "before": fontIdentity(font),
                                               "replacement": fontIdentity(replacement)],
                                              to: directory.appendingPathComponent(scenario + ".font-assignment.json"))
                                item.font = replacement
                            } else { item.font = font }
                        }
                        if let fontColor { item.fontColor = fontColor }
                        if item.border == nil {
                            let border = PDFBorder(); border.lineWidth = 0; item.border = border
                        }
                        if scenario.hasPrefix("editable-space-da-") {
                            // Public PDFAnnotationKeyDefaultAppearance is /DA,
                            // a PDF string per PDFAnnotation.h. Test only the
                            // writer's leading-slash/name classification here.
                            let key = PDFAnnotationKey(rawValue: "/DA")
                            let previous = item.value(forAnnotationKey: key)
                            let original = previous as? String
                            guard let font = item.font else { throw failure("space-da-font-missing") }
                            let fallback = "/\(font.fontName) \(font.pointSize) Tf 0 g"
                            let literal = " " + (original ?? fallback).trimmingCharacters(in: .whitespacesAndNewlines)
                            let accepted = item.setValue(literal, forAnnotationKey: key)
                            try writeJSON(["setterAccepted": accepted, "usedFallback": original == nil,
                                           "before": jsonValue(previous), "requested": literal,
                                           "after": jsonValue(item.value(forAnnotationKey: key)), "fontBefore": fontIdentity(font),
                                           "fontAfter": item.font.map(fontIdentity) ?? ["absent": true]],
                                          to: directory.appendingPathComponent(scenario + ".da-assignment.json"))
                        }
                    }
                    if subtype == "widget", item.widgetFieldType == .text || item.widgetFieldType == .choice {
                        let current = item.widgetDefaultStringValue
                        item.widgetDefaultStringValue = current ?? ""
                    }
                }
                let materialized = directory.appendingPathComponent(scenario + ".materialized.json")
                try writeJSON(annotationSnapshot(document, progressPrefix: materialized), to: materialized)
            }
            guard let plain = document.dataRepresentation() else { throw failure("annotation-serialize") }
            try writeExclusive(plain, to: directory.appendingPathComponent(scenario + ".pdf"))
            let options: [AnyHashable: Any] = [AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): ownerPassword,
                AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): readerPassword]
            guard let protected = document.dataRepresentation(options: options) else { throw failure("annotation-protected-serialize") }
            try writeExclusive(protected, to: directory.appendingPathComponent(scenario + ".protected.pdf"))
            trace(scenario + " serialized")
        }
    }

    @MainActor
    private static func annotationSnapshot(_ document: PDFDocument, progressPrefix: URL) throws -> [String: Any] {
        // Only this diagnostic's known synthetic page is eligible for the
        // detailed report; ordinary documents are never dumped by inspect.
        guard !document.isLocked, document.pageCount == 1, (document.string ?? "").contains("PDF native verification"),
              let page = document.page(at: 0), page.annotations.count <= 20 else { throw failure("synthetic-fixture-required") }
        var records: [[String: Any]] = []
        for (index, annotation) in page.annotations.enumerated() {
            let record = annotationRecord(annotation, index: index)
            try writeJSON(record, to: progressPrefix.appendingPathExtension("annotation-\(index).json"))
            let event: [String: Any] = ["syntheticFixture": true, "phase": progressPrefix.lastPathComponent, "annotation": record]
            var bytes = try JSONSerialization.data(withJSONObject: diagnosticJSON(event), options: [.sortedKeys])
            bytes.append(10)
            // write() immediately preserves completed records in the launcher's
            // bounded stdout even if a later framework getter crashes.
            FileHandle.standardOutput.write(bytes)
            records.append(record)
        }
        return ["schemaVersion": 1, "syntheticFixture": true, "pageCount": document.pageCount,
            "knownTextPresent": true, "mediaBox": rectangle(page.bounds(for: .mediaBox)), "cropBox": rectangle(page.bounds(for: .cropBox)),
            "rotation": page.rotation, "isEncrypted": document.isEncrypted,
            "annotations": records]
    }

    @MainActor
    private static func annotationRecord(_ item: PDFAnnotation, index: Int) -> [String: Any] {
        let subtype = (item.type ?? "").replacingOccurrences(of: "/", with: "").lowercased()
        trace("annotation \(index) \(subtype) common color KVC begin")
        // PDFAnnotation's nonoptional Swift color declaration may conceal an
        // absent Objective-C value. KVC for this public getter preserves nil.
        let annotationColor = item.value(forKey: "color") as? NSColor
        trace("annotation \(index) \(subtype) common color KVC end; absent=\(annotationColor == nil)")
        var result: [String: Any] = ["index": index, "type": item.type ?? "", "bounds": rectangle(item.bounds),
            "contents": item.contents ?? "", "display": item.shouldDisplay, "print": item.shouldPrint,
            "flags": (item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/F")) as? NSNumber) as Any? ?? NSNull(),
            "color": annotationColor.map(colorRecord) ?? ["absent": true], "rawColor": jsonValue(item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/C"))),
            "borderPresent": item.border != nil, "width": item.border?.lineWidth as Any? ?? NSNull()]
        if subtype == "freetext" {
            result["rawDefaultAppearance"] = jsonValue(item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/DA")))
            result["fontSize"] = item.font?.pointSize as Any? ?? NSNull()
            result["fontName"] = item.font?.fontName as Any? ?? NSNull()
            if let font = item.font {
                let graphics = CTFontCopyGraphicsFont(font as CTFont, nil)
                result["fontCoreTextPostScriptName"] = CTFontCopyPostScriptName(font as CTFont) as String
                result["fontResolvedPostScriptName"] = graphics.postScriptName.map { $0 as String } as Any? ?? NSNull()
                result["fontIdentity"] = fontIdentity(font)
            }
            trace("annotation \(index) freeText fontColor KVC begin")
            let fontColor = item.value(forKey: "fontColor") as? NSColor
            trace("annotation \(index) freeText fontColor KVC end; absent=\(fontColor == nil)")
            result["fontColor"] = fontColor.map(colorRecord) ?? ["absent": true]
        }
        if ["highlight", "underline", "strikeout"].contains(subtype) {
            result["quadrilaterals"] = item.quadrilateralPoints?.map { [Double($0.pointValue.x), Double($0.pointValue.y)] } as Any? ?? NSNull()
        }
        if subtype == "line" {
            result["start"] = [Double(item.startPoint.x), Double(item.startPoint.y)]; result["end"] = [Double(item.endPoint.x), Double(item.endPoint.y)]
            result["startStyle"] = item.startLineStyle.rawValue; result["endStyle"] = item.endLineStyle.rawValue
        }
        if subtype == "ink" {
            result["pathElementCounts"] = item.paths?.map(\.elementCount) ?? []
        }
        if subtype == "widget" {
            result["field"] = item.fieldName ?? ""; result["fieldType"] = item.widgetFieldType.rawValue
            result["value"] = item.widgetStringValue ?? ""; result["default"] = item.widgetDefaultStringValue ?? ""
            result["defaultPresent"] = item.widgetDefaultStringValue != nil
            result["rawDefault"] = jsonValue(item.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/DV")))
            result["readOnly"] = item.isReadOnly
            if item.widgetFieldType == .text { result["multiline"] = item.isMultiline; result["maxLength"] = item.maximumLength }
            if item.widgetFieldType == .choice { result["choices"] = item.choices ?? []; result["choiceValues"] = item.values ?? []; result["list"] = item.isListChoice }
            if item.widgetFieldType == .button {
                result["buttonState"] = item.buttonWidgetState.rawValue; result["control"] = item.widgetControlType.rawValue
                result["buttonName"] = item.buttonWidgetStateString
            }
        }
        return result
    }

    private static func fontIdentity(_ font: NSFont) -> [String: Any] {
        let ct = font as CTFont, graphics = CTFontCopyGraphicsFont(ct, nil), matrix = CTFontGetMatrix(ct)
        var variation: [String: Any] = [:]
        if let entries = CTFontCopyVariation(ct) as? [NSNumber: NSNumber] {
            for (key, value) in entries { variation[key.stringValue] = value }
        }
        return ["fontName": font.fontName, "pointSize": font.pointSize,
            "coreTextPostScriptName": CTFontCopyPostScriptName(ct) as String,
            "graphicsPostScriptName": graphics.postScriptName.map { $0 as String } as Any? ?? NSNull(),
            "symbolicTraits": CTFontGetSymbolicTraits(ct).rawValue, "traits": CTFontCopyTraits(ct) as NSDictionary,
            "variation": variation, "matrix": [matrix.a, matrix.b, matrix.c, matrix.d, matrix.tx, matrix.ty].map { Double($0) }]
    }

    @MainActor
    private static func colorRecord(_ color: NSColor) -> [String: Any] {
        var result: [String: Any] = ["absent": false]
        trace("color class begin"); result["class"] = String(reflecting: type(of: color))
        trace("color type begin"); result["type"] = String(describing: color.type)
        trace("color description begin"); result["description"] = color.description
        trace("color colorSpaceName begin"); result["colorSpaceName"] = color.colorSpaceName.rawValue
        for (name, space) in [("sRGB", NSColorSpace.sRGB), ("deviceRGB", .deviceRGB), ("genericRGB", .genericRGB), ("extendedSRGB", .extendedSRGB)] {
            trace("color conversion " + name + " begin")
            if let converted = color.usingColorSpace(space) {
                result[name] = ["description": converted.description,
                    "rgba": [converted.redComponent, converted.greenComponent, converted.blueComponent, converted.alphaComponent].map { Double($0) }]
            } else { result[name] = NSNull() }
        }
        if color.type == .pattern {
            result["cgColor"] = ["attempted": false, "reason": "pattern color has no scalar RGBA representation"]
            return result
        }
        trace("color cgColor begin")
        let cg = color.cgColor
        var cgResult: [String: Any] = ["attempted": true, "components": cg.components?.map { Double($0) } ?? [],
            "space": cg.colorSpace?.name.map { $0 as String } ?? "", "model": cg.colorSpace?.model.rawValue as Any? ?? NSNull()]
        if let srgb = CGColorSpace(name: CGColorSpace.sRGB), let converted = cg.converted(to: srgb, intent: .defaultIntent, options: nil) {
            cgResult["convertedSRGB"] = converted.components?.map { Double($0) } ?? []
        } else { cgResult["convertedSRGB"] = NSNull() }
        result["cgColor"] = cgResult
        trace("color cgColor end")
        return result
    }

    private static func rectangle(_ rect: CGRect) -> [Double] { [rect.minX, rect.minY, rect.width, rect.height].map { Double($0) } }
    private static func jsonValue(_ value: Any?) -> Any {
        guard let value, JSONSerialization.isValidJSONObject([value]) else { return NSNull() }
        return value
    }
    private static func writeJSON(_ value: [String: Any], to output: URL) throws {
        try writeExclusive(JSONSerialization.data(withJSONObject: diagnosticJSON(value), options: [.prettyPrinted, .sortedKeys]), to: output)
    }
    private static func diagnosticJSON(_ value: Any) -> Any {
        if let number = value as? NSNumber, !number.doubleValue.isFinite { return "nonfinite:" + number.stringValue }
        if let array = value as? [Any] { return array.map(diagnosticJSON) }
        if let dictionary = value as? [String: Any] { return dictionary.mapValues(diagnosticJSON) }
        return value
    }

    @MainActor
    private static func generate(_ directory: URL) throws {
        // mkdir fails on every pre-existing entry, including a directory or
        // dangling link. No previous diagnostic result is overwritten.
        guard Darwin.mkdir(directory.path, mode_t(0o700)) == 0 else { throw failure("new-private-directory-required") }
        // Match the smoke fixture's initially absent PDF destinations while
        // keeping framework-created files private from their first write.
        let previousMask = Darwin.umask(mode_t(0o077))
        defer { _ = Darwin.umask(previousMask) }
        let source = directory.appendingPathComponent("source.pdf")
        let copy = directory.appendingPathComponent("copy.pdf")
        let protected = directory.appendingPathComponent("protected.pdf")
        trace("source CGContext begin")
        var bounds = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let context = CGContext(source as CFURL, mediaBox: &bounds, nil) else { throw failure("source-context") }
        context.beginPDFPage(nil)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        ("PDF native verification — ação" as NSString).draw(
            at: NSPoint(x: 72, y: 720),
            withAttributes: [.font: NSFont.systemFont(ofSize: 18), .foregroundColor: NSColor.black])
        NSGraphicsContext.restoreGraphicsState()
        context.endPDFPage()
        context.closePDF()
        try makePrivate(source)
        trace("source CGContext end")

        guard let document = PDFDocument(url: source), let page = document.page(at: 0) else { throw failure("source-reopen") }
        guard document.pageCount == 1, (document.string ?? "").contains("PDF native verification"),
              !document.findString("verification", withOptions: .caseInsensitive).isEmpty else { throw failure("source-content") }
        let annotation = PDFAnnotation(bounds: CGRect(x: 72, y: 700, width: 120, height: 24), forType: .highlight, withProperties: nil)
        annotation.color = .systemYellow
        page.addAnnotation(annotation)
        let field = PDFAnnotation(bounds: CGRect(x: 72, y: 620, width: 200, height: 30), forType: .widget, withProperties: nil)
        field.widgetFieldType = .text
        field.fieldName = "native-test"
        field.widgetStringValue = "PDF"
        page.addAnnotation(field)

        // Preserve the actual PDFKit write(to:) path under investigation.
        // Its initially absent destination belongs to our new private folder.
        trace("PDFKit write copy begin")
        guard document.write(to: copy) else { throw failure("copy-write") }
        try makePrivate(copy)
        trace("PDFKit write copy end")
        guard let restored = PDFDocument(url: copy), let restoredPage = restored.page(at: 0) else { throw failure("copy-reopen") }
        guard restoredPage.annotations.count == 2,
              restoredPage.annotations.contains(where: { $0.fieldName == "native-test" && $0.widgetStringValue == "PDF" }) else {
            throw failure("copy-annotations")
        }
        // These accesses also occur before protected serialization in the smoke
        // fixture; retain them in case framework cache state affects the writer.
        let thumbnail = restoredPage.thumbnail(of: NSSize(width: 120, height: 170), for: .mediaBox)
        guard thumbnail.size.width > 0, thumbnail.size.height > 0 else { throw failure("copy-thumbnail") }
        let reader = PDFView(frame: NSRect(x: 0, y: 0, width: 800, height: 600))
        reader.document = restored
        reader.autoScales = true

        let options: [AnyHashable: Any] = [
            AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): ownerPassword,
            AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): readerPassword,
        ]
        trace("protected dataRepresentation begin")
        guard let protectedData = restored.dataRepresentation(options: options) else { throw failure("protected-serialize") }
        try writeExclusive(protectedData, to: protected)
        trace("protected dataRepresentation end")
        // Retain all three original files, even if later inspection fails.
    }

    @MainActor
    private static func inspect(_ source: URL, output: URL) throws {
        let bytes = try readRegular(source)
        var result = Inspection()
        trace("inspect PDFDocument begin")
        if let document = PDFDocument(data: bytes) {
            result.opened = true
            result.isEncrypted = document.isEncrypted
            result.wasLocked = document.isLocked
            if result.wasLocked {
                result.unlockAttempted = true
                result.emptyPasswordAccepted = document.unlock(withPassword: "")
                result.unlocked = document.unlock(withPassword: readerPassword)
            } else {
                result.unlocked = true
            }
            result.isLockedAfterUnlock = document.isLocked
            if !document.isLocked {
                result.pageCount = document.pageCount
                result.knownTextPresent = (document.string ?? "").contains("PDF native verification")
                result.searchMatchCount = document.findString("verification", withOptions: .caseInsensitive).count
                for index in 0..<document.pageCount {
                    guard let page = document.page(at: index) else { result.failureCode = "missing-page"; continue }
                    result.annotationCount += page.annotations.count
                    for annotation in page.annotations {
                        let subtype = (annotation.type ?? "").replacingOccurrences(of: "/", with: "").lowercased()
                        if subtype == "highlight" { result.highlightCount += 1 }
                        if subtype == "widget" && annotation.widgetFieldType == .text { result.textWidgetCount += 1 }
                        if annotation.fieldName == "native-test" { result.widgetValue = annotation.widgetStringValue }
                    }
                }
            } else {
                result.failureCode = "unlock-failed"
            }
        } else {
            result.failureCode = "pdfdocument-rejected"
        }
        trace("inspect PDFDocument end")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try writeExclusive(encoder.encode(result), to: output)
    }

    private static func readRegular(_ url: URL) throws -> Data {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("input-open") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        let limit = 128 * 1_024 * 1_024
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_size > 0, info.st_size <= Int64(limit) else { throw failure("input-regular-bounded") }
        var bytes = Data()
        while let chunk = try handle.read(upToCount: min(65_536, limit + 1 - bytes.count)), !chunk.isEmpty {
            bytes.append(chunk)
            guard bytes.count <= limit else { throw failure("input-growth") }
        }
        return bytes
    }

    private static func writeExclusive(_ bytes: Data, to url: URL) throws {
        let descriptor = Darwin.open(url.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else { throw failure("new-output-required") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        try handle.write(contentsOf: bytes)
        try handle.synchronize()
    }

    private static func makePrivate(_ url: URL) throws {
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("generated-file-open") }
        defer { Darwin.close(descriptor) }
        var info = stat()
        guard fstat(descriptor, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), fchmod(descriptor, mode_t(0o600)) == 0 else { throw failure("generated-file-permissions") }
    }

    private static func trace(_ phase: String) {
        FileHandle.standardError.write(Data(("PDFKit diagnostic phase: " + phase + "\n").utf8))
    }

    private static func failure(_ code: String) -> NSError {
        NSError(domain: "PDFKitDiagnosis", code: 1, userInfo: ["diagnosticCode": code])
    }
}
