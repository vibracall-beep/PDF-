import AppKit
import SwiftUI
import PDFKit

/// A deterministic native rendering artifact for reviewing the macOS build in CI.
@MainActor
enum MacPreview {
    static func render(to destination: URL) throws {
        _ = NSApplication.shared
        NSApplication.shared.setActivationPolicy(.accessory)
        let model = Workspace()
        let view = ContentView().environmentObject(model)
        let host = NSHostingView(rootView: view)
        let rectangle = NSRect(x: 0, y: 0, width: 1280, height: 860)
        let window = NSWindow(contentRect: rectangle, styleMask: [.titled, .resizable],
                              backing: .buffered, defer: false)
        window.title = "PDF"
        window.contentView = host
        window.setContentSize(rectangle.size)
        window.orderFrontRegardless()
        defer { window.orderOut(nil) }
        try capture(host, to: destination)

        // Review the actual reader layout as well as the tool catalogue, using
        // generated sample content and without modifying the recent-file list.
        model.document = try sampleDocument()
        model.url = URL(fileURLWithPath: "/Amostras/Guia do PDF.pdf")
        model.section = "Leitor"
        let readerDestination = destination.deletingPathExtension()
            .appendingPathExtension("leitor.png")
        try capture(host, to: readerDestination)
    }

    private static func capture(_ host: NSView, to destination: URL) throws {
        host.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(2))
        host.layoutSubtreeIfNeeded()
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
            throw NSError(domain: "PDF.Preview", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "A interface não pôde ser renderizada."])
        }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "PDF.Preview", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Não foi possível exportar a renderização."])
        }
        try NativeOutput.write(data, to: destination)
    }

    private static func sampleDocument() throws -> PDFDocument {
        let data = NSMutableData()
        var pageBounds = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let consumer = CGDataConsumer(data: data as CFMutableData),
              let context = CGContext(consumer: consumer, mediaBox: &pageBounds, nil) else {
            throw NSError(domain: "PDF.Preview", code: 3)
        }
        for index in 1...2 {
            context.beginPDFPage(nil)
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
            ((index == 1 ? "Um espaço para seus documentos." : "Cada detalhe, no seu ritmo.") as NSString)
                .draw(at: NSPoint(x: 48, y: 746), withAttributes: [.font: NSFont.systemFont(ofSize: 23, weight: .semibold), .foregroundColor: NSColor.systemBlue])
            let lines = index == 1
                ? ["Leia com clareza, encontre informações e marque o que importa.",
                   "O PDF reúne leitura, organização, conversão e inteligência local.",
                   "", "Selecione texto para realçar. Adicione notas ou desenhe na página.",
                   "Use as miniaturas, o sumário e os marcadores para navegar.",
                   "", "Salve uma nova cópia para preservar seu documento original."]
                : ["Escolha seus favoritos e organize as ferramentas como preferir.",
                   "Converta formatos, prepare formulários e automatize tarefas.",
                   "", "Busque evidências no documento e consulte as páginas citadas."]
            for (line, text) in lines.enumerated() {
                (text as NSString).draw(at: NSPoint(x: 48, y: CGFloat(690 - line * 27)),
                                       withAttributes: [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: NSColor.black])
            }
            ("PDF · Documento de demonstração · \(index) / 2" as NSString).draw(
                at: NSPoint(x: 48, y: 38), withAttributes: [.font: NSFont.systemFont(ofSize: 10), .foregroundColor: NSColor.gray])
            NSGraphicsContext.restoreGraphicsState()
            context.endPDFPage()
        }
        context.closePDF()
        guard let document = PDFDocument(data: data as Data), document.pageCount == 2 else {
            throw NSError(domain: "PDF.Preview", code: 4)
        }
        return document
    }
}
