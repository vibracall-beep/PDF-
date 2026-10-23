import AppKit
import SwiftUI

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
}
