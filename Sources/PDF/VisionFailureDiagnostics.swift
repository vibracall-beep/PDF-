import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import Vision
import CoreML

/// Diagnostic-only comparisons for a failed CLI fixture. These probes cannot
/// publish a PDF, replace the production result, or make a failed audit pass.
enum VisionFailureDiagnostics {
    private final class State: @unchecked Sendable {
        let done = DispatchSemaphore(value: 0)
        let cancellation = NativeCancellation()
    }
    private struct Input: @unchecked Sendable { let image: CGImage }

    private static func log(_ message: String) {
        FileHandle.standardError.write(Data(("Vision diagnostic: " + message + "\n").utf8))
    }
    private static func failure(_ name: String, error: Error) {
        // NSError bridging can hide a Swift enum's case and associated runtime
        // code. Preserve both representations for this known CLI fixture only.
        log(name + " failed: " + VisionRecognition.description(error) + "; Swift=" + String(reflecting: error))
    }
    private static func result(_ name: String, texts: [String], expected: String) {
        let recovered = texts.joined(separator: "\n")
        log("\(name): observations=\(texts.count); recoveredExpectedText=\(recovered.localizedCaseInsensitiveContains(expected)); characters=\(recovered.count). Diagnostic only; original audit remains failed.")
    }

    static func run(image: CGImage, language: String, expectedText: String, cancellation: NativeCancellation) {
        guard CommandLine.arguments.contains("--vision-audit"), (try? cancellation.check()) != nil else { return }
        let state = State(), input = Input(image: image)
        log("begin; same normalized image=\(image.width)x\(image.height); bits=\(image.bitsPerComponent)/\(image.bitsPerPixel); bitmapInfo=\(image.bitmapInfo.rawValue); colorSpace=\(image.colorSpace?.name as String? ?? "unnamed"); alpha=\(image.alphaInfo.rawValue); language=\(language); accurate=true; totalLimitSeconds=90")
        let task = Task.detached(priority: .utility) {
            defer { state.done.signal() }
            do {
                try cancellation.check(); try state.cancellation.check(); try Task.checkCancellation()
                let png = NSMutableData()
                guard let encoder = CGImageDestinationCreateWithData(png as CFMutableData, UTType.png.identifier as CFString, 1, nil) else {
                    throw NSError(domain: "PDF.VisionDiagnostic", code: 1, userInfo: [NSLocalizedDescriptionKey: "PNG encoder unavailable"])
                }
                CGImageDestinationAddImage(encoder, input.image, nil)
                guard CGImageDestinationFinalize(encoder) else {
                    throw NSError(domain: "PDF.VisionDiagnostic", code: 2, userInfo: [NSLocalizedDescriptionKey: "PNG encoding failed"])
                }
                let data = png as Data
                log("same image encoded losslessly as PNG; bytes=\(data.count)")

                // The first comparison changes only the calling thread. The
                // others distinguish a language-correction asset from decoding.
                let legacyCases: [(String, Data?, Bool, Bool)] = [
                    ("legacy accurate CGImage detached", nil, true, false),
                    ("legacy accurate CGImage without language correction", nil, false, false),
                    ("legacy accurate PNG", data, true, false),
                    ("legacy accurate PNG usesCPUOnly", data, true, true)
                ]
                for (name, encoded, correction, cpuOnly) in legacyCases {
                    try cancellation.check(); try state.cancellation.check(); try Task.checkCancellation()
                    do {
                        let texts = try legacy(encoded, image: input.image, language: language, correction: correction, cpuOnly: cpuOnly, cancellation: state.cancellation)
                        result(name, texts: texts, expected: expectedText)
                    } catch { failure(name, error: error) }
                }

                let swiftCases: [(String, Bool, Bool)] = [
                    ("Swift accurate CGImage", false, false),
                    ("Swift accurate PNG", true, false),
                    ("Swift accurate PNG all stages CPU", true, true)
                ]
                for (name, encoded, cpuOnly) in swiftCases {
                    try cancellation.check(); try state.cancellation.check(); try Task.checkCancellation()
                    do {
                        var request = RecognizeTextRequest()
                        request.recognitionLevel = .accurate
                        request.automaticallyDetectsLanguage = false
                        request.usesLanguageCorrection = true
                        let supported = request.supportedRecognitionLanguages
                        let preferred = Locale.Language(identifier: language == "pt" ? "pt-BR" : "en-US")
                        guard let selected = supported.first(where: { $0 == preferred }) ?? supported.first(where: { $0.languageCode?.identifier == language }) else {
                            throw NSError(domain: "PDF.VisionDiagnostic", code: 3, userInfo: [NSLocalizedDescriptionKey: "Selected language unsupported by the Swift accurate request"])
                        }
                        request.recognitionLanguages = [selected]
                        var pinnedStages = 0
                        if cpuOnly {
                            let stages = request.supportedComputeStageDevices
                            guard !stages.isEmpty else {
                                throw NSError(domain: "PDF.VisionDiagnostic", code: 5, userInfo: [NSLocalizedDescriptionKey: "Swift request exposes no compute stages to pin to CPU"])
                            }
                            for (stage, devices) in stages {
                                guard let cpu = devices.first(where: { if case .cpu = $0 { return true }; return false }) else {
                                    throw NSError(domain: "PDF.VisionDiagnostic", code: 6, userInfo: [NSLocalizedDescriptionKey: "Swift request exposes a compute stage without a supported CPU device: \(stage)"])
                                }
                                request.setComputeDevice(cpu, for: stage)
                                pinnedStages += 1
                            }
                        }
                        log("\(name): revision=\(request.revision); accurate=true; languages=\(request.recognitionLanguages); orientation=up; CPUOnlyRequested=\(cpuOnly); stagesPinnedToCPU=\(pinnedStages)")
                        let observations: [RecognizedTextObservation]
                        if encoded { observations = try await request.perform(on: data, orientation: .up) }
                        else { observations = try await request.perform(on: input.image, orientation: .up) }
                        try cancellation.check(); try state.cancellation.check(); try Task.checkCancellation()
                        result(name, texts: observations.compactMap { $0.topCandidates(1).first?.string }, expected: expectedText)
                    } catch { failure(name, error: error) }
                }
            } catch { failure("probes stopped", error: error) }
        }
        // The request runs outside the main actor. This diagnostic entry point
        // exists only in a failing CLI run, never in the reader's user actions.
        if state.done.wait(timeout: .now() + 90) == .timedOut {
            state.cancellation.cancel(); task.cancel()
            log("90-second limit reached; probes cancelled. Original audit remains failed.")
        } else { log("end; original audit remains failed") }
    }

    private static func legacy(_ data: Data?, image: CGImage, language: String, correction: Bool, cpuOnly: Bool, cancellation: NativeCancellation) throws -> [String] {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = correction
        request.automaticallyDetectsLanguage = false
        // Deliberately exercise this deprecated public switch separately from
        // setComputeDevice; it is a CLI diagnostic, never a production policy.
        if cpuOnly { request.usesCPUOnly = true }
        let supported = try request.supportedRecognitionLanguages()
        request.recognitionLanguages = (language == "pt" ? ["pt-BR", "pt-PT", "en-US"] : ["en-US"]).filter { supported.contains($0) }
        guard request.recognitionLanguages.contains(where: { $0.hasPrefix(language) }) else {
            throw NSError(domain: "PDF.VisionDiagnostic", code: 4, userInfo: [NSLocalizedDescriptionKey: "Selected language unsupported by the legacy accurate request"])
        }
        log("legacy \(data == nil ? "CGImage" : "PNG"): revision=\(request.revision); accurate=true; languageCorrection=\(correction); usesCPUOnlyRequested=\(cpuOnly); languages=\(request.recognitionLanguages.joined(separator: ",")); orientation=up; mainThread=\(Thread.isMainThread)")
        cancellation.install(request); defer { cancellation.install(nil) }
        try cancellation.check()
        if let data { try VNImageRequestHandler(data: data, orientation: .up, options: [:]).perform([request]) }
        else { try VNImageRequestHandler(cgImage: image, orientation: .up, options: [:]).perform([request]) }
        try cancellation.check()
        return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    }
}
