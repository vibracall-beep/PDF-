import AppKit
import CoreGraphics
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
