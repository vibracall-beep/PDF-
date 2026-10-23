import AppKit
import Foundation

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: make-icon.swift <iconset-directory>\n", stderr)
    exit(2)
}
_ = NSApplication.shared
let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)

func drawIcon(pixels: Int) throws -> Data {
    let size = CGFloat(pixels)
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                       bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                       isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
          let graphics = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw NSError(domain: "PDF.Icon", code: 1)
    }
    bitmap.size = NSSize(width: size, height: size)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = graphics
    defer { NSGraphicsContext.restoreGraphicsState() }
    graphics.cgContext.clear(CGRect(x: 0, y: 0, width: size, height: size))
    graphics.cgContext.scaleBy(x: size / 1024, y: size / 1024)
    let tile = NSBezierPath(roundedRect: NSRect(x: 62, y: 62, width: 900, height: 900), xRadius: 205, yRadius: 205)
    NSGradient(starting: NSColor(srgbRed: 0.12, green: 0.48, blue: 0.98, alpha: 1),
               ending: NSColor(srgbRed: 0.32, green: 0.17, blue: 0.72, alpha: 1))?.draw(in: tile, angle: -65)
    let glow = NSBezierPath(ovalIn: NSRect(x: 120, y: 570, width: 780, height: 320))
    NSColor.white.withAlphaComponent(0.09).setFill(); glow.fill()
    let back = NSBezierPath(roundedRect: NSRect(x: 280, y: 190, width: 500, height: 650), xRadius: 54, yRadius: 54)
    NSColor.white.withAlphaComponent(0.20).setFill(); back.fill()
    let page = NSBezierPath(roundedRect: NSRect(x: 226, y: 224, width: 500, height: 650), xRadius: 54, yRadius: 54)
    NSGradient(starting: NSColor.white.withAlphaComponent(0.98), ending: NSColor(srgbRed: 0.82, green: 0.88, blue: 1, alpha: 0.92))?.draw(in: page, angle: -90)
    NSColor.white.withAlphaComponent(0.8).setStroke(); page.lineWidth = 3; page.stroke()
    for (y, width) in [(720.0, 280.0), (654.0, 350.0), (588.0, 220.0)] {
        let line = NSBezierPath(roundedRect: NSRect(x: 292, y: y, width: width, height: 21), xRadius: 10, yRadius: 10)
        NSColor(srgbRed: 0.27, green: 0.37, blue: 0.66, alpha: 0.25).setFill(); line.fill()
    }
    ("PDF" as NSString).draw(at: NSPoint(x: 283, y: 319), withAttributes: [
        .font: NSFont.systemFont(ofSize: 148, weight: .bold),
        .foregroundColor: NSColor(srgbRed: 0.19, green: 0.27, blue: 0.61, alpha: 1)
    ])
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "PDF.Icon", code: 2)
    }
    return png
}

for pointSize in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let suffix = scale == 2 ? "@2x" : ""
        let output = destination.appendingPathComponent("icon_\(pointSize)x\(pointSize)\(suffix).png")
        try drawIcon(pixels: pointSize * scale).write(to: output)
    }
}
