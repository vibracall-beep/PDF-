import SwiftUI
import AppKit
import UniformTypeIdentifiers
import Darwin

private final class BenchmarkJob: @unchecked Sendable {
    private let lock = NSLock()
    private var process:OwnedChildProcess?
    private var cancelled = false
    private var timedOut = false
    func cancel(deadline:Bool = false) {
        lock.lock(); cancelled = true; timedOut = deadline || timedOut; let current = process; lock.unlock()
        current?.cancel(grace: 10, signal: SIGTERM)
    }
    func run(executable:URL,input:URL?,pages:Int,aiAudit:Bool = false) throws -> Data {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-benchmark-job-" + UUID().uuidString,isDirectory:true)
        try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
        defer { try? FileManager.default.removeItem(at:directory) }
        let output = directory.appendingPathComponent("report.json")
        let child = Process(), pipe = Pipe()
        child.executableURL = executable
        child.arguments = aiAudit ? ["--ai-audit",output.path] : ["--benchmark",output.path,"--benchmark-pages",String(pages)]
        if !aiAudit,let input { child.arguments! += ["--benchmark-input",input.path] }
        child.standardOutput = pipe; child.standardError = pipe
        child.standardInput = FileHandle.nullDevice
        let bundleLease = try BundleRuntimeLease.configureChild(child)
        defer { try? bundleLease?.close() }
        lock.lock()
        if cancelled { lock.unlock(); throw CancellationError() }
        let owned: OwnedChildProcess
        do { owned = try OwnedChildProcess(configuration: child); process = owned; lock.unlock() }
        catch { process = nil; lock.unlock(); throw error }
        defer {
            owned.cancel(grace: 10, signal: SIGTERM); _ = try? owned.waitUntilExit()
            try? pipe.fileHandleForReading.close()
            lock.lock(); process = nil; lock.unlock()
        }
        let deadline = DispatchWorkItem { [weak self] in self?.cancel(deadline: true) }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 600, execute: deadline)
        defer { deadline.cancel() }
        var diagnostic = Data()
        let exit = try owned.collectOutput(from: pipe.fileHandleForReading) { chunk in
            if diagnostic.count < 65_536 { diagnostic.append(chunk.prefix(65_536-diagnostic.count)) }
        }
        lock.lock(); let wasCancelled = cancelled, expired = timedOut; lock.unlock()
        if expired { throw NSError(domain:"PDF.Benchmark",code:2,userInfo:[NSLocalizedDescriptionKey:aiAudit ? "A avaliação de IA ultrapassou 10 minutos e foi encerrada. Nenhuma aprovação de qualidade foi produzida." : "O benchmark ultrapassou 10 minutos e foi encerrado."]) }
        if wasCancelled { throw CancellationError() }
        guard exit.status == 0, !exit.signalled else {
            throw NSError(domain:"PDF.Benchmark",code:Int(exit.status),userInfo:[NSLocalizedDescriptionKey:String(data:diagnostic,encoding:.utf8) ?? "O benchmark não pôde ser concluído."])
        }
        let attributes = try output.resourceValues(forKeys:[.isRegularFileKey,.fileSizeKey])
        guard attributes.isRegularFile == true,(attributes.fileSize ?? Int.max) <= 1_048_576 else { throw RecoveryError.invalidRecord }
        return try Data(contentsOf:output)
    }
}

@MainActor private final class BenchmarkController: ObservableObject {
    @Published var busy = false
    @Published var report:BenchmarkReport?
    @Published var message = ""
    private var job:BenchmarkJob?
    private var task:Task<Void,Never>?
    private var data:Data?
    func start(input:URL?,pages:Int) {
        guard !busy, ApplicationWork.isAcceptingWork, let executable = Bundle.main.executableURL else { return }
        busy = true; message = "Medindo abertura, busca, renderização, processamento e OCR…"; report = nil; data = nil
        let job = BenchmarkJob(); self.job = job
        task = ApplicationTask.start(cancel: { job.cancel() }) { [self] in
            do {
                try Task.checkCancellation()
                let bytes = try await Task.detached(priority:.userInitiated) { try job.run(executable:executable,input:input,pages:pages) }.value
                let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .iso8601
                let value = try decoder.decode(BenchmarkReport.self,from:bytes)
                guard value.schemaVersion == 1 else { throw RecoveryError.invalidRecord }
                data = bytes; report = value
                message = value.metrics.contains(where:{$0.error != nil}) ? "Medição concluída com operações indisponíveis. Confira o relatório." : "Medição concluída neste Mac."
            } catch is CancellationError { message = "Benchmark cancelado." }
            catch { message = error.localizedDescription }
            busy = false; self.job = nil; task = nil
        }
    }
    func cancel() { job?.cancel() }
    func export(model: Workspace) {
        guard let data else { return }
        guard let destination = NativeOutput.destination(model: model, toolName: "Desempenho", extension: "json",
            originalName: report?.sourceName ?? "PDF-desempenho.json") else { return }
        do { try NativeOutput.write(data,to:destination); message = "Relatório salvo." }
        catch { message = error.localizedDescription }
    }
}

@MainActor private final class LocalAIAuditController: ObservableObject {
    @Published private(set) var busy = false
    @Published private(set) var report: LocalAIReport?
    @Published private(set) var message = ""
    private var job: BenchmarkJob?
    private var data: Data?
    func start() {
        guard !busy, ApplicationWork.isAcceptingWork, let executable = Bundle.main.executableURL else { return }
        busy = true; report = nil; data = nil
        message = "Consultando o modelo local com cinco casos em português…"
        let job = BenchmarkJob(); self.job = job
        ApplicationTask.start(cancel: { job.cancel() }) { [self] in
            defer { busy = false; self.job = nil }
            do {
                try Task.checkCancellation()
                let bytes = try await Task.detached(priority: .userInitiated) { try job.run(executable: executable, input: nil, pages: 0, aiAudit: true) }.value
                let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .iso8601
                let value = try decoder.decode(LocalAIReport.self, from: bytes)
                guard value.schemaVersion == 1, value.items.count == 5,
                      ["sample_passed", "sample_failed", "unavailable"].contains(value.status) else { throw RecoveryError.invalidRecord }
                data = bytes; report = value
                switch value.status {
                case "unavailable": message = value.availabilityReason ?? "Modelo indisponível. A qualidade de geração não foi avaliada."
                case "sample_passed": message = "Os cinco casos desta amostra atenderam aos critérios. Isso não certifica a qualidade geral."
                default: message = "A amostra apresentou critérios não atendidos ou erros. Consulte cada resultado."
                }
            } catch is CancellationError { message = "Avaliação de IA cancelada. Nenhuma conclusão foi emitida." }
            catch { message = error.localizedDescription }
        }
    }
    func cancel() { job?.cancel() }
    func export(model: Workspace) {
        guard let data, let destination = NativeOutput.destination(model: model, toolName: "Avaliação IA português", extension: "json", originalName: "IA-portugues.json") else { return }
        do { try NativeOutput.write(data, to: destination); message = "Relatório de IA salvo com resultados e citações verificáveis." }
        catch { message = error.localizedDescription }
    }
}

struct BenchmarkView: View {
    @EnvironmentObject private var model: Workspace
    @EnvironmentObject private var preferences:AppearancePreferences
    @StateObject private var controller = BenchmarkController()
    @StateObject private var aiController = LocalAIAuditController()
    @State private var input:URL?
    @State private var pages = 100
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                Label("Desempenho deste Mac",systemImage:"gauge.with.dots.needle.67percent").font(.largeTitle.bold())
                Text("Meça tempos e memória com uma amostra ou um PDF seu. O relatório identifica o hardware usado e registra as operações que não puderam ser executadas.").foregroundStyle(.secondary)
                GroupBox("Preferência de processamento") { PerformancePolicyView().padding(10) }.disabled(controller.busy || aiController.busy)
                GroupBox("Documento da medição") {
                    VStack(alignment:.leading,spacing:12) {
                        HStack {
                            Text(input?.lastPathComponent ?? "Amostra de texto e vetores").lineLimit(1)
                            Spacer()
                            Button("Escolher PDF…") { chooseInput() }
                            if input != nil { Button("Usar amostra") { input = nil } }
                        }
                        if input == nil {
                            Picker("Páginas da amostra",selection:$pages) { Text("100").tag(100); Text("500").tag(500); Text("1.000").tag(1000) }.pickerStyle(.segmented)
                        }
                        Text("A entrada é copiada para uma pasta temporária privada. Nenhum arquivo original é alterado e nenhum documento é enviado à rede.").font(.caption).foregroundStyle(.secondary)
                    }.padding(10)
                }.disabled(controller.busy || aiController.busy)
                HStack {
                    if controller.busy { ProgressView().controlSize(.small); Button("Cancelar") { controller.cancel() } }
                    else { Button("Medir desempenho") { controller.start(input:input,pages:pages) }.buttonStyle(.borderedProminent).disabled(aiController.busy) }
                    if controller.report != nil { Button("Exportar relatório…") { controller.export(model: model) } }
                    Text(controller.message).font(.callout).textSelection(.enabled)
                }
                if let report = controller.report { results(report) }
                aiEvaluation
            }.padding(28).frame(maxWidth:1000,alignment:.leading).frame(maxWidth:.infinity)
        }.tint(preferences.accent).onDisappear { controller.cancel(); aiController.cancel() }
    }
    private var aiEvaluation: some View {
        GroupBox("Avaliar respostas da IA em português") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Execute cinco perguntas controladas sobre dois PDFs sintéticos: fatos, falta de apoio e prazos contraditórios. O teste usa o mesmo modelo e as mesmas validações da biblioteca. Nenhum documento seu é usado.")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    if aiController.busy {
                        ProgressView().controlSize(.small)
                        Button("Cancelar avaliação") { aiController.cancel() }
                    } else {
                        Button("Avaliar IA local") { aiController.start() }.disabled(controller.busy)
                    }
                    if aiController.report != nil { Button("Exportar avaliação…") { aiController.export(model: model) } }
                }
                if !aiController.message.isEmpty { Text(aiController.message).font(.callout).textSelection(.enabled) }
                if let report = aiController.report {
                    ForEach(report.items) { item in
                        DisclosureGroup {
                            Text(item.expectation).font(.caption).foregroundStyle(.secondary)
                            if let text = item.response { Text(text).textSelection(.enabled) }
                            if let error = item.error { Text(error).foregroundStyle(.orange).textSelection(.enabled) }
                            ForEach(item.checks) { check in
                                Label(check.detail, systemImage: check.passed ? "checkmark.circle" : "xmark.circle").font(.caption)
                            }
                            Text("\(PortugueseCount.label(item.citations.count, "citação", "citações")) · \(Int(item.milliseconds)) ms. IDs, páginas, trechos e SHA-256 estão no relatório exportado.").font(.caption)
                        } label: {
                            Text("\(item.question) — \(aiStatus(item.status))").font(.callout)
                        }
                    }
                    Text("Amostra pequena, uma execução por pergunta. Respostas curtas não recebem classificação automática de idioma; não substitui avaliação humana ou um conjunto representativo de documentos.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.padding(10)
        }
    }
    private func aiStatus(_ status: String) -> String {
        switch status {
        case "passed": return "critérios atendidos"
        case "unavailable": return "modelo indisponível"
        case "failed": return "critério não atendido"
        case "cancelled": return "cancelado"
        default: return "erro na avaliação"
        }
    }
    private func results(_ report:BenchmarkReport) -> some View {
        VStack(alignment:.leading,spacing:16) {
            HStack {
                VStack(alignment:.leading,spacing:6) {
                    Text(report.processor).font(.title2.bold())
                    Text(report.operatingSystem + " · " + report.architecture).foregroundStyle(.secondary)
                    Text(report.graphicsDevice + " · \(PortugueseCount.label(report.activeProcessorCount, "núcleo disponível", "núcleos disponíveis"))").font(.callout)
                }
                Spacer()
                VStack(alignment:.trailing) {
                    Text(String(format:"%.0f MB",Double(report.processPeakMemoryBytes)/1_048_576)).font(.title2.bold())
                    Text("Pico de memória do processo").font(.caption).foregroundStyle(.secondary)
                }
            }
            Text(report.virtualization).font(.callout).foregroundStyle(.secondary)
            if !report.processorIdentifiesM4OrLater { Text("O processador informado pelo sistema não é identificado como M4 ou superior. Os resultados pertencem ao equipamento acima.").font(.callout).foregroundStyle(.secondary) }
            ForEach(report.metrics) { metric in
                VStack(alignment:.leading,spacing:6) {
                    HStack { Text(metric.name).font(.headline); Spacer(); Text(metric.error == nil ? metric.medianMilliseconds.map { String(format:"%.2f ms",$0) } ?? "Sem medição" : "Indisponível").monospacedDigit() }
                    Text(metric.error ?? metric.detail).font(.caption).foregroundStyle(metric.error == nil ? Color.secondary : Color.orange).textSelection(.enabled)
                    if let samples = metric.processCPUMilliseconds, !samples.isEmpty {
                        Text(String(format: "CPU do processo: %.2f ms por amostra, em média.", samples.reduce(0, +) / Double(samples.count)))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if let samples = metric.ocrSamples, !samples.isEmpty {
                        let apple = samples.filter { $0.backend == "apple-vision" }.count
                        let compatibility = samples.filter { $0.backend == "tesseract" }.count
                        Text("OCR medido: \(apple) amostras com Apple Vision · \(compatibility) com Tesseract local.").font(.caption)
                        if let cause = samples.compactMap(\.fallbackReason).first {
                            Text("Compatibilidade local: \(cause)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                }.padding(14).background(Color(nsColor:.controlBackgroundColor),in:RoundedRectangle(cornerRadius:12))
            }
            Text("\(PortugueseCount.label(report.pageCount, "página", "páginas")) · \(PortugueseCount.label(report.repetitions, "medição", "medições")) por operação após aquecimento · mediana em milissegundos.").font(.caption)
            Text(report.methodology).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            if let energy = report.energyMeasurement { Text(energy).font(.caption).foregroundStyle(.secondary) }
        }
    }
    private func chooseInput() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        if panel.runModal() == .OK { input = panel.url }
    }
}
