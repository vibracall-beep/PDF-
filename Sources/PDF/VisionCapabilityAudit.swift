import AppKit
import CoreGraphics
import PDFKit

/// An Apple-only capability report. A successfully written report is not a
/// passing product test: each actual recognition attempt has its own status.
/// The mandatory product smoke test separately requires working local OCR.
@MainActor
enum VisionCapabilityAudit {
    struct Check: Encodable {
        let id: String
        let status: String
        let errorDomain: String?
        let errorCode: Int?
        let message: String
    }

    struct Report: Encodable {
        struct Summary: Encodable { let appleVisionPassed: Bool }
        let schemaVersion = 1
        let fixture = "image-only-verification-v1"
        let checks: [Check]
        let summary: Summary
    }

    private struct Fixture {
        let image: CGImage
        let scannedData: Data
    }

    /// Recognition failures remain explicit in JSON. File publication failures
    /// still throw, so CI cannot treat a missing or stale report as evidence.
    static func run(output: URL) throws {
        _ = NSApplication.shared
        var checks: [Check] = []
        let ids = ["searchable-pdf", "isolated-process"]
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("PDF-VisionAudit-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
            let sample = try fixture(in: directory)
            checks.append(check(ids[0]) {
                let data = try VisionPDF.create(data: sample.scannedData, language: "en", enhanceContrast: true,
                                                cancellation: NativeCancellation()) { _, _ in }
                let document = PDFDocument(data: data)
                try require(document?.pageCount == 1 &&
                            (document?.string ?? "").localizedCaseInsensitiveContains("verification"),
                            "Vision não criou texto pesquisável na página digitalizada.")
            })
            checks.append(check(ids[1]) {
                let normalized = try VisionRecognition.canonicalImage(sample.image)
                let observations = try VisionWorker.recognize(normalized, language: "en", cancellation: NativeCancellation())
                try require(observations.contains { $0.string.localizedCaseInsensitiveContains("verification") },
                            "O processo isolado do Vision não reconheceu o texto real da amostra.")
            })
        } catch {
            // A broken fixture or private directory is not evidence about the
            // Apple recognizer. Fail the CLI rather than approving a report
            // which could be mistaken for a measured framework failure.
            throw error
        }

        let report = Report(checks: checks,
                            summary: .init(appleVisionPassed: checks.count == 2 && checks.allSatisfy { $0.status == "passed" }))
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try NativeOutput.write(encoder.encode(report), to: output)
        for result in checks {
            FileHandle.standardOutput.write(Data(("Apple Vision capability \(result.id): \(result.status)\n").utf8))
        }
    }

    private static func check(_ id: String, operation: () throws -> Void) -> Check {
        FileHandle.standardOutput.write(Data(("Apple Vision capability starting: \(id)\n").utf8))
        do {
            try operation()
            return Check(id: id, status: "passed", errorDomain: nil, errorCode: nil,
                         message: "Reconhecimento real da amostra sintética confirmado.")
        } catch { return failed(id, error) }
    }

    private static func failed(_ id: String, _ error: Error) -> Check {
        let detail = error as NSError
        // Never serialize a PDF, recognized observations or source text. Only
        // bounded error diagnostics from this fixed synthetic fixture are kept.
        let message = String(VisionRecognition.description(error).prefix(16_000))
        return Check(id: id, status: "failed", errorDomain: detail.domain,
                     errorCode: detail.code, message: message)
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        guard condition else {
            throw NSError(domain: "PDF.VisionCapabilityAudit", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: message])
        }
    }

    private static func fixture(in directory: URL) throws -> Fixture {
        let source = directory.appendingPathComponent("source.pdf")
        var bounds = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let context = CGContext(source as CFURL, mediaBox: &bounds, nil) else {
            throw NSError(domain: "PDF.VisionCapabilityAudit", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Não foi possível criar a amostra de OCR."])
        }
        context.beginPDFPage(nil)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        ("PDF native verification — ação" as NSString).draw(
            at: NSPoint(x: 72, y: 720),
            withAttributes: [.font: NSFont.systemFont(ofSize: 18), .foregroundColor: NSColor.black])
        NSGraphicsContext.restoreGraphicsState()
        context.endPDFPage()
        context.closePDF()
        guard let sourceDocument = PDFDocument(url: source), let page = sourceDocument.page(at: 0) else {
            throw NSError(domain: "PDF.VisionCapabilityAudit", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "A amostra PDF não pôde ser aberta."])
        }
        // Match the original native smoke fixture, including its annotations,
        // then discard all source text by rasterizing before recognition.
        let highlight = PDFAnnotation(bounds: CGRect(x: 72, y: 700, width: 120, height: 24),
                                      forType: .highlight, withProperties: nil)
        highlight.color = .systemYellow
        page.addAnnotation(highlight)
        let field = PDFAnnotation(bounds: CGRect(x: 72, y: 620, width: 200, height: 30),
                                  forType: .widget, withProperties: nil)
        field.widgetFieldType = .text
        field.fieldName = "native-test"
        field.widgetStringValue = "PDF"
        page.addAnnotation(field)
        let raster = page.thumbnail(of: NSSize(width: 1190, height: 1684), for: .mediaBox)
        guard let image = raster.cgImage(forProposedRect: nil, context: nil, hints: nil),
              let scannedPage = PDFPage(image: raster) else {
            throw NSError(domain: "PDF.VisionCapabilityAudit", code: 4,
                          userInfo: [NSLocalizedDescriptionKey: "A amostra digitalizada não pôde ser criada."])
        }
        let scanned = PDFDocument()
        scanned.insert(scannedPage, at: 0)
        try require((scanned.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                    "A amostra de OCR precisa conter apenas imagem.")
        guard let scannedData = scanned.dataRepresentation(), let reopened = PDFDocument(data: scannedData) else {
            throw NSError(domain: "PDF.VisionCapabilityAudit", code: 5,
                          userInfo: [NSLocalizedDescriptionKey: "A amostra digitalizada não pôde ser serializada."])
        }
        try require(reopened.pageCount == 1 &&
                    (reopened.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                    "A amostra serializada precisa conter uma página sem camada de texto.")
        return Fixture(image: image, scannedData: scannedData)
    }
}
