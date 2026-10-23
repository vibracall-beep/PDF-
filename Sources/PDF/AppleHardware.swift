import AppKit
import CoreImage
import Metal

enum AppleHardware {
    static var graphicsDevice: String { MTLCreateSystemDefaultDevice()?.name ?? "Renderização do sistema" }
    static var processorCount: Int { ProcessInfo.processInfo.activeProcessorCount }
    static var memoryGiB: Int { Int(ProcessInfo.processInfo.physicalMemory / 1_073_741_824) }
    static var summary: String {
        "\(graphicsDevice) · \(processorCount) núcleos disponíveis · \(memoryGiB) GB de memória"
    }
}

/// Core Image schedules these filters on Metal when a compatible GPU is present.
/// Vision/Foundation Models independently choose their supported execution devices.
enum GPUImageProcessor {
    private static let context: CIContext = {
        if let device = MTLCreateSystemDefaultDevice() {
            return CIContext(mtlDevice: device, options: [.cacheIntermediates: false])
        }
        return CIContext(options: [.cacheIntermediates: false])
    }()

    static func enhance(_ image: CGImage, contrast: Double = 1.12) throws -> CGImage {
        guard contrast.isFinite, (0...4).contains(contrast) else {
            throw NSError(domain: "PDF.ImageProcessing", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "O contraste precisa estar entre 0 e 4."])
        }
        let input = CIImage(cgImage: image)
        guard let filter = CIFilter(name: "CIColorControls") else {
            throw NSError(domain: "PDF.ImageProcessing", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Filtro de imagem indisponível."])
        }
        filter.setValue(input, forKey: kCIInputImageKey)
        filter.setValue(contrast, forKey: kCIInputContrastKey)
        filter.setValue(0.0, forKey: kCIInputSaturationKey)
        filter.setValue(0.01, forKey: kCIInputBrightnessKey)
        // OCR receives a defined interleaved 8-bit RGB image rather than a
        // context-dependent floating-point or extended-range output format.
        guard let result = filter.outputImage, let outputSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let rendered = context.createCGImage(result, from: input.extent, format: .RGBA8, colorSpace: outputSpace) else {
            throw NSError(domain: "PDF.ImageProcessing", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Não foi possível melhorar a digitalização."])
        }
        return rendered
    }
}
