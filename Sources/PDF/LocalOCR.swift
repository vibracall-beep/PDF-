import Foundation
import CoreGraphics

struct PageOCRResult: Sendable {
    let observations: [VisionTextObservation]
    let backend: String
    let fallbackReason: String?
}

struct OCRPageEvidence: Codable, Sendable {
    let page: Int
    let backend: String
    let fallbackReason: String?
}

struct OCRPDFResult: Sendable {
    let data: Data
    let pages: [OCRPageEvidence]
}

/// Prefer Apple's native recognizer. An alternate local engine is allowed only
/// after a classified Vision execution failure, including the isolated process.
/// Invalid inputs, language/DTO errors, cancellation and timeouts remain errors.
enum LocalOCR {
    static func recognize(_ image: CGImage, language: String, cancellation: NativeCancellation) throws -> PageOCRResult {
        try cancellation.check()
        do {
            let observations = try VisionRecognition.recognize(image, language: language, cancellation: cancellation)
            try cancellation.check()
            return PageOCRResult(observations: observations, backend: "apple-vision", fallbackReason: nil)
        } catch let failure as VisionRuntimeUnavailable {
            try cancellation.check()
            do {
                let result = try TesseractPageRecognizer.recognizePage(image, language: language, cancellation: cancellation)
                try cancellation.check()
                guard result.backend == "tesseract", result.language == language,
                      result.width == image.width, result.height == image.height else {
                    throw NSError(domain: "PDF.LocalOCR", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: "O resultado do reconhecimento local não corresponde à página solicitada."])
                }
                try VisionTextObservation.validate(result.observations)
                return PageOCRResult(observations: result.observations, backend: result.backend, fallbackReason: failure.detail)
            } catch {
                try cancellation.check()
                if error is CancellationError { throw error }
                throw NSError(domain: "PDF.LocalOCR", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "O reconhecimento nativo e a alternativa local falharam. Vision: \(failure.detail) Alternativa local: \(error.localizedDescription)",
                    NSUnderlyingErrorKey: error
                ])
            }
        }
    }
}

enum LocalOCRPDF {
    static func create(data: Data, language: String, enhanceContrast: Bool = false, cancellation: NativeCancellation,
                       progress: @escaping @Sendable (Int, Int) -> Void) throws -> OCRPDFResult {
        try SearchablePDFRenderer.create(data: data, enhanceContrast: enhanceContrast, cancellation: cancellation,
                                         progress: progress) { image in
            try LocalOCR.recognize(image, language: language, cancellation: cancellation)
        }
    }
}
