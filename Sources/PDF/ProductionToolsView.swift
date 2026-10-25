import SwiftUI
import AppKit
import UniformTypeIdentifiers

enum ProductionMode: String, CaseIterable, Identifiable {
    case preflight = "print-preflight", prepare = "print-prepare", pdfx, bates, dossier, stamp, measure, conversion = "conversion-audit"
    var id: String { rawValue }
    var title: String {
        switch self {
        case .preflight: return "Diagnóstico de impressão"
        case .prepare: return "Corte e sangria"
        case .pdfx: return "Preparar PDF/X-3"
        case .bates: return "Numeração Bates"
        case .dossier: return "Conjunto de documentos"
        case .stamp: return "Carimbo personalizado"
        case .measure: return "Medir com escala"
        case .conversion: return "Auditar conversão Office"
        }
    }
    var report: Bool { self == .preflight || self == .measure }
}

struct MeasurementPoint: Identifiable {
    let id = UUID()
    var x: Double
    var y: Double
}

struct ProductionToolsView: View {
    @EnvironmentObject private var model: Workspace
    @State private var mode: ProductionMode
    @State private var inputs: [URL] = []
    @State private var password = ""
    @State private var pages = ""
    @State private var prefix = "DOC-"
    @State private var start = 1
    @State private var digits = 6
    @State private var stamp = "REVISADO"
    @State private var inset = 24.0
    @State private var bleed = 9.0
    @State private var minimumDPI = 200.0
    @State private var renderInks = false
    @State private var inkDPI = 72
    @State private var profile: URL?
    @State private var condition = "CMYK printing condition"
    @State private var page = 1
    @State private var scale = 100.0
    @State private var unit = "m"
    @State private var closed = false
    @State private var points = [MeasurementPoint(x: 72, y: 72), MeasurementPoint(x: 144, y: 72)]
    @State private var report = ""
    @State private var error = ""
    @State private var generation = UUID()
    init(initialMode: ProductionMode = .preflight) { _mode = State(initialValue: initialMode) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Produção de documentos").font(.largeTitle.bold())
                Text("Prepare cópias para gráfica, revisão jurídica e medições técnicas.").foregroundStyle(.secondary)
                Picker("Ferramenta", selection: $mode) {
                    ForEach(ProductionMode.allCases) { Text($0.title).tag($0) }
                }.disabled(model.busy).onChange(of: mode) { _, _ in generation = UUID(); report = ""; error = ""; if mode != .dossier { inputs = Array(inputs.prefix(1)) } }
                GroupBox("Documentos de origem") {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Button(mode == .dossier ? "Adicionar PDFs…" : "Escolher PDF…") { choosePDFs() }
                            Button("Usar versão salva do leitor") { useReader() }.disabled(model.url == nil)
                            if mode == .conversion { Button("Escolher resultado Office…") { chooseOffice() }.disabled(inputs.isEmpty) }
                            if !inputs.isEmpty { Button("Limpar lista") { inputs = [] } }
                        }
                        ForEach(Array(inputs.enumerated()), id: \.offset) { index, url in
                            HStack {
                                Text("\(index + 1). \(url.lastPathComponent)").lineLimit(1)
                                Spacer()
                                if mode == .dossier {
                                    Button("Subir", systemImage: "arrow.up") { inputs.swapAt(index, index - 1) }.disabled(index == 0)
                                    Button("Descer", systemImage: "arrow.down") { inputs.swapAt(index, index + 1) }.disabled(index == inputs.count - 1)
                                    Button("Remover", systemImage: "minus.circle") { inputs.remove(at: index) }
                                }
                            }
                        }
                        LabeledContent("Senha, se houver") { SecureField("Senha dos arquivos protegidos", text: $password).labelsHidden() }
                        if mode == .dossier { Text("Nesta tela, os PDFs protegidos precisam usar a mesma senha. O conjunto preserva a interseção das permissões e inclui índice com links e marcadores.").font(.caption).foregroundStyle(.secondary) }
                        else if !mode.report && mode != .pdfx && mode != .conversion {
                            LabeledContent("Páginas") { TextField("Todas ou, por exemplo, 1,3-5", text: $pages).labelsHidden() }
                        }
                    }.padding(10)
                }
                .disabled(model.busy)
                settings
                HStack {
                    Button(mode.report || mode == .conversion ? "Gerar relatório…" : "Criar cópia…") { execute() }
                        .buttonStyle(.borderedProminent).disabled(inputs.isEmpty || model.busy || (mode == .pdfx && profile == nil) || (mode == .conversion && inputs.count != 2))
                    if model.busy { ProgressView().controlSize(.small); Button("Cancelar") { model.cancel() } }
                }
                if !error.isEmpty { Text(error).foregroundStyle(.orange).textSelection(.enabled) }
                if !report.isEmpty { GroupBox("Resultado") { Text(report).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled).padding(12) } }
            }.padding(28).frame(maxWidth: 1100, alignment: .leading).frame(maxWidth: .infinity)
        }.accessibilityIdentifier("pdf.production.tools")
            .onChange(of: inputs) { _, _ in invalidateReport() }
            .onChange(of: reportSettings) { _, _ in invalidateReport() }
            .onDisappear { generation = UUID() }
    }
    private var reportSettings: [String] {
        [password, pages, prefix, String(start), String(digits), stamp, String(inset), String(bleed),
         String(minimumDPI), String(renderInks), String(inkDPI), profile?.path ?? "", condition, String(page), String(scale), unit, String(closed)]
        + points.flatMap { [String($0.x), String($0.y)] }
    }
    private func invalidateReport() { report = ""; error = "" }
    @ViewBuilder private var settings: some View {
        GroupBox(mode.title) {
            VStack(alignment: .leading, spacing: 12) {
                switch mode {
                case .preflight:
                    LabeledContent("Resolução mínima de imagens, em DPI") { TextField("Resolução mínima de imagens, em DPI", value: $minimumDPI, format: .number).labelsHidden() }
                    Toggle("Medir cobertura CMYK renderizada", isOn: $renderInks)
                        .accessibilityIdentifier("pdf.production.renderInks")
                    if renderInks {
                        Picker("Resolução da medição de tintas", selection: $inkDPI) {
                            Text("72 DPI").tag(72); Text("100 DPI").tag(100); Text("150 DPI").tag(150)
                        }
                        HStack {
                            Button(profile?.lastPathComponent ?? "Escolher perfil ICC CMYK da gráfica (opcional)…") { chooseProfile() }
                            if profile != nil { Button("Usar perfil padrão") { profile = nil } }
                        }
                        Text("Mede a fração de pixels com tinta por canal em todas as páginas. Tintas especiais são simuladas em CMYK. Não representa carga máxima de tinta; PDFs protegidos exigem uma cópia desbloqueada explicitamente.").font(.caption).foregroundStyle(.secondary)
                    }
                    Text("Inspeciona fontes, resolução, caixas, perfis ICC, tintas especiais, sobreimpressão e transparência nos recursos declarados. Verificações PDF/X-3 usam um parser separado do conversor; o relatório identifica a cobertura e não equivale à certificação ISO ou à prova de cor física.").font(.callout)
                case .prepare:
                    LabeledContent("Margem de corte em pontos") { TextField("Margem de corte em pontos", value: $inset, format: .number).labelsHidden() }
                    LabeledContent("Sangria em pontos") { TextField("Sangria em pontos", value: $bleed, format: .number).labelsHidden() }
                    Text("Define corte, sangria e marcas dentro da folha existente. O conteúdo não é reposicionado; confira se textos e imagens respeitam a área final. 72 pontos equivalem a uma polegada.").font(.callout)
                case .pdfx:
                    Button(profile?.lastPathComponent ?? "Escolher perfil ICC CMYK da gráfica…") { chooseProfile() }
                    LabeledContent("Condição de impressão (ASCII)") { TextField("Condição de impressão (ASCII)", text: $condition).labelsHidden() }
                    Text("Gera uma cópia candidata a PDF/X-3:2002 com Ghostscript e verifica o perfil incorporado, fontes e estrutura com um parser independente. Cores e transparências podem ser convertidas. Confirme o resultado com a gráfica; as verificações enumeradas não substituem uma certificação ISO completa.").font(.callout)
                case .bates:
                    LabeledContent("Prefixo") { TextField("Prefixo", text: $prefix).labelsHidden() }
                    LabeledContent("Número inicial") { TextField("Número inicial", value: $start, format: .number).labelsHidden() }
                    Stepper("Dígitos: \(digits)", value: $digits, in: 1...16)
                    Text("Identificadores consecutivos no rodapé direito das páginas selecionadas.").font(.caption)
                case .dossier:
                    Text("O índice respeita a ordem da lista. Os nomes dos arquivos tornam-se títulos; cada item leva à primeira página do documento correspondente.")
                case .conversion:
                    Text("Escolha primeiro o PDF original e depois o arquivo DOCX, XLSX, PPTX, ODT ou RTF convertido. O resultado inclui comparação visual HTML, PDF reexportado e relatório de texto, imagens, páginas e objetos editáveis. Diferenças são indicadores para revisão, sem promessa de equivalência perfeita.")
                case .stamp:
                    LabeledContent("Texto do carimbo") { TextField("Texto do carimbo", text: $stamp).labelsHidden() }
                    Text("O carimbo será inserido na região superior esquerda. Use o editor para posicionamentos e estilos adicionais.").font(.caption)
                case .measure:
                    LabeledContent("Página") { TextField("Página", value: $page, format: .number).labelsHidden() }
                    LabeledContent("Escala: 1 para…") { TextField("Escala: 1 para…", value: $scale, format: .number).labelsHidden() }
                    Picker("Unidade", selection: $unit) { Text("Milímetros").tag("mm"); Text("Centímetros").tag("cm"); Text("Metros").tag("m") }
                    Toggle("Fechar polígono e calcular área", isOn: $closed)
                    Text("Coordenadas em pontos, a partir do canto superior esquerdo da página sem rotação. Confira a escala usando uma distância conhecida.").font(.caption)
                    ForEach($points) { $point in
                        HStack {
                            LabeledContent("X") { TextField("X", value: $point.x, format: .number).labelsHidden() }
                            LabeledContent("Y") { TextField("Y", value: $point.y, format: .number).labelsHidden() }
                            Button("Remover") { points.removeAll { $0.id == point.id } }.disabled(points.count <= 2)
                        }
                    }
                    Button("Adicionar ponto") { points.append(MeasurementPoint(x: 144, y: 144)) }.disabled(points.count >= 1000)
                }
            }.textFieldStyle(.roundedBorder).padding(10)
        }.disabled(model.busy)
    }
    private func choosePDFs() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]; panel.allowsMultipleSelection = mode == .dossier
        if panel.runModal() == .OK { if mode == .dossier { inputs.append(contentsOf: panel.urls) } else { inputs = panel.urls } }
    }
    private func chooseProfile() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = ["icc", "icm"].compactMap { UTType(filenameExtension: $0) }
        if panel.runModal() == .OK { profile = panel.url }
    }
    private func chooseOffice() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = ["docx", "xlsx", "pptx", "odt", "rtf"].compactMap { UTType(filenameExtension: $0) }
        if panel.runModal() == .OK, let url = panel.url, let original = inputs.first { inputs = [original, url] }
    }
    private func useReader() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        (model.pdfView as? DrawingPDFView)?.finishStroke()
        guard let url = model.savedDocumentURL ?? model.url else { return }
        guard !model.hasUnsavedChanges else { error = "Salve uma cópia das alterações do leitor antes de usar este documento."; return }
        if mode == .dossier { inputs.append(url) } else { inputs = [url] }
        password = model.activeSession?.password ?? ""; error = ""
    }
    private func execute() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let first = inputs.first else { return }
        var options: [String: Any] = ["password": password]
        if !pages.isEmpty { options["pages"] = pages }
        switch mode {
        case .preflight:
            options["minimum_dpi"] = minimumDPI; options["render_inks"] = renderInks; options["ink_dpi"] = inkDPI
            if renderInks, let profile { options["icc_profile"] = profile.path }
        case .prepare: options["trim_inset"] = inset; options["bleed"] = bleed; options["crop_marks"] = true
        case .pdfx: options["icc_profile"] = profile?.path; options["output_condition"] = condition
        case .bates: options["prefix"] = prefix; options["start"] = start; options["digits"] = digits
        case .dossier, .conversion: break
        case .stamp: options["text"] = stamp
        case .measure:
            options["points"] = points.map { [$0.x, $0.y] }; options["scale"] = scale; options["unit"] = unit
            options["page"] = page; options["closed"] = closed
        }
        guard let output = model.selectOutput(extension: mode.report ? "json" : "pdf", directory: mode == .conversion, toolName: mode.title, originalURL: first) else { return }
        let selectedMode = mode
        let submittedInputs = inputs, submittedSettings = reportSettings
        let token = UUID(); generation = token
        error = ""; report = ""
        model.execute(operation: mode.rawValue, inputs: inputs, output: output, options: options, title: mode.title, completion: { result in
            guard generation == token, inputs == submittedInputs, reportSettings == submittedSettings else { return }
            switch result {
            case .failure(let failure): error = failure.localizedDescription
            case .success(let url):
                if selectedMode.report {
                    ApplicationTask.start {
                        guard !Task.isCancelled else { return }
                        let worker = Task.detached(priority: .utility) { Self.describeReport(url, mode: selectedMode) }
                        let message = await withTaskCancellationHandler(operation: { await worker.value }, onCancel: { worker.cancel() })
                        guard !Task.isCancelled else { return }
                        if generation == token, inputs == submittedInputs, reportSettings == submittedSettings { report = message }
                    }
                } else { report = selectedMode == .conversion ? "Relatório criado. Abra comparison.html na pasta do resultado para comparar os documentos." : "Cópia criada. Abra o resultado para revisar a aparência final." }
            }
        })
    }
    nonisolated private static func describeReport(_ url: URL, mode: ProductionMode) -> String {
        guard !Task.isCancelled else { return "" }
        guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size <= 64 * 1024 * 1024,
              let data = try? Data(contentsOf: url), let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return "Relatório salvo. Não foi possível carregar a prévia."
        }
        if mode == .measure, let distance = object["distance"] as? Double {
            var text = String(format: "Distância / perímetro: %.4f %@", distance, object["unit"] as? String ?? "")
            if let area = object["area"] as? Double { text += String(format: "\nÁrea: %.4f %@²", area, object["unit"] as? String ?? "") }
            return text
        }
        let findings = object["findings"] as? [[String: Any]] ?? []
        let codes = ["font-not-embedded": "Fonte não incorporada", "low-image-resolution": "Imagem abaixo da resolução escolhida", "no-distinct-trim": "Área de corte igual à folha",
                     "invalid-output-intents": "Condição de impressão inválida", "invalid-output-profile": "Perfil ICC de saída inválido", "missing-output-intent": "Condição de impressão ausente",
                     "invalid-color-profile": "Perfil de cor inválido", "registration-color": "Cor de registro em todas as chapas", "spot-inks-declared": "Tintas especiais declaradas",
                     "overprint-declared": "Sobreimpressão declarada", "transparency-declared": "Transparência declarada", "uninspected-print-resources": "Há recursos não inspecionados",
                     "direct-encryption-dictionary": "Criptografia legada: estrutura estrita não aprovada"]
        var summary = "\(PortugueseCount.label(object["page_count"] as? Int ?? 0, "página analisada", "páginas analisadas")) · \(PortugueseCount.label(findings.count, "observação", "observações"))."
        if let structure = object["structure"] as? [String: Any] {
            let pages = structure["pages"] as? [[String: Any]] ?? []
            let spots = Set(pages.flatMap { $0["spot_inks"] as? [String] ?? [] }).sorted()
            if !spots.isEmpty { summary += "\nTintas especiais nos recursos: " + spots.joined(separator: ", ") }
            if let checks = structure["pdfx_checks"] as? [String: Any], let rows = checks["checks"] as? [[String: Any]] {
                let passed = rows.filter { $0["status"] as? String == "passed" }.count
                summary += "\nPDF/X-3: \(passed)/\(rows.count) verificações estruturais aprovadas. Não é certificação completa."
            }
            for intent in structure["output_intents"] as? [[String: Any]] ?? [] {
                if let profile = intent["profile"] as? [String: Any], let description = profile["description"] as? String {
                    summary += "\nPerfil incorporado: " + description
                }
            }
        }
        if let coverage = object["ink_coverage"] as? [String: Any], let pages = coverage["pages"] as? [[String: Any]] {
            summary += "\n\nCobertura de pixels por canal — \(coverage["dpi"] as? Int ?? 0) DPI."
            for page in pages.prefix(20) {
                summary += String(format: "\nPágina %d: C %.2f%% · M %.2f%% · Y %.2f%% · K %.2f%%", page["page"] as? Int ?? 0,
                                  100 * (page["cyan"] as? Double ?? 0), 100 * (page["magenta"] as? Double ?? 0),
                                  100 * (page["yellow"] as? Double ?? 0), 100 * (page["black"] as? Double ?? 0))
            }
            if pages.count > 20 { summary += "\nA cobertura de todas as páginas está no relatório exportado." }
        }
        let rows = findings.prefix(200).map { finding in
            let location = (finding["page"] as? Int).map { "Página \($0)" } ?? "Documento"
            return "\(location): \(codes[finding["code"] as? String ?? ""] ?? "Revisão necessária")"
        }
        return summary + "\n\n" + rows.joined(separator: "\n") + (findings.count > 200 ? "\nAs demais observações estão no relatório exportado." : "")
    }
}
