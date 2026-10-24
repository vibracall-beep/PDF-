import Foundation
import SwiftUI

/// A bounded policy for external workers. It changes scheduling, never document
/// quality, and makes no claim that Vision scheduled work on the Neural Engine.
struct PerformanceBudget: Codable, Equatable, Sendable {
    let mode: String
    let workerCount: Int
    let threadsPerWorker: Int
    let memoryBudgetBytes: UInt64
    let constrained: Bool

    static func make(mode: String, processors: Int, memory: UInt64,
                     lowPower: Bool, thermalLevel: Int) -> PerformanceBudget {
        let mode = ["balanced", "responsive", "throughput"].contains(mode) ? mode : "balanced"
        let cores = max(1, processors)
        let constrained = lowPower || thermalLevel >= 2
        let available = max(1, cores - (mode == "throughput" ? 0 : 1))
        let byMemory = max(1, Int(min(UInt64(16), memory / (2 * 1_073_741_824))))
        let ceiling = constrained ? 1 : (mode == "responsive" ? 2 : (mode == "throughput" ? 8 : 4))
        let workers = min(available, byMemory, ceiling)
        // Avoid nested OCR/OpenMP pools multiplying the page worker count.
        let threads = constrained ? 1 : min(2, max(1, available / workers))
        return PerformanceBudget(mode: mode, workerCount: workers, threadsPerWorker: threads,
                                 memoryBudgetBytes: min(memory / 3, 8 * 1_073_741_824), constrained: constrained)
    }
}

enum AdaptivePerformance {
    static let preferenceKey = "performanceMode"
    static var current: PerformanceBudget {
        let process = ProcessInfo.processInfo
        return PerformanceBudget.make(mode: UserDefaults.standard.string(forKey: preferenceKey) ?? "balanced",
                                      processors: process.activeProcessorCount, memory: process.physicalMemory,
                                      lowPower: process.isLowPowerModeEnabled, thermalLevel: process.thermalState.rawValue)
    }
    static func apply(to environment: inout [String: String]) {
        let budget = current
        environment["PDF_WORKERS"] = String(budget.workerCount)
        environment["PDF_MEMORY_BUDGET_BYTES"] = String(budget.memoryBudgetBytes)
        environment["OMP_THREAD_LIMIT"] = String(budget.threadsPerWorker)
        environment["OPENBLAS_NUM_THREADS"] = String(budget.threadsPerWorker)
        environment["VECLIB_MAXIMUM_THREADS"] = String(budget.threadsPerWorker)
    }
}

struct PerformancePolicyView: View {
    @AppStorage(AdaptivePerformance.preferenceKey) private var mode = "balanced"
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker("Uso do Mac", selection: $mode) {
                Text("Equilibrado").tag("balanced")
                Text("Priorizar resposta do Mac").tag("responsive")
                Text("Priorizar processamento").tag("throughput")
            }.pickerStyle(.segmented)
            Text("O limite de processos considera CPU, memória, modo de pouca energia e temperatura no início de cada tarefa. A qualidade dos arquivos é preservada.")
                .font(.caption).foregroundStyle(.secondary)
        }.accessibilityIdentifier("pdf.performance.policy")
    }
}

enum PerformancePolicyAuditChecks {
    static func run() throws {
        func require(_ condition: Bool) throws {
            if !condition { throw NSError(domain: "PDF.PerformancePolicy", code: 1,
                                          userInfo: [NSLocalizedDescriptionKey: "A política de recursos ultrapassou o limite seguro."]) }
        }
        // High-core/low-memory machines and thermal throttling must not fan out
        // a pool merely because the CPU exposes many cores.
        let small = PerformanceBudget.make(mode: "throughput", processors: 32, memory: 4 * 1_073_741_824, lowPower: false, thermalLevel: 0)
        try require(small.workerCount <= 2 && small.threadsPerWorker <= 2)
        for level in 2...3 {
            let hot = PerformanceBudget.make(mode: "throughput", processors: 32, memory: 128 * 1_073_741_824, lowPower: false, thermalLevel: level)
            try require(hot.workerCount == 1 && hot.threadsPerWorker == 1 && hot.constrained)
        }
        let battery = PerformanceBudget.make(mode: "throughput", processors: 12, memory: 32 * 1_073_741_824, lowPower: true, thermalLevel: 0)
        try require(battery.workerCount == 1)
        let fallback = PerformanceBudget.make(mode: "unknown", processors: 0, memory: 0, lowPower: false, thermalLevel: 0)
        try require(fallback.workerCount == 1 && fallback.mode == "balanced")
    }
}
