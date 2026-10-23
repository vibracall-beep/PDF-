import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// Certificate secrets deliberately have no AppStorage, preset or history model.
struct VerificationView: View {
    @EnvironmentObject private var model: Workspace
    @Environment(\.dismiss) private var dismiss
    @State private var mode: String
    @State private var source: URL?
    @State private var certificate: URL?
    @State private var certificatePIN = ""
    @State private var roots: [URL] = []
    @State private var reason = ""
    @State private var location = ""
    @State private var fieldName = "AssinaturaPDF"
    @State private var useTimestamp = false
    @State private var timestampURL = ""
    @State private var archiveProfile = "2b"
    @State private var accessibilityProfile = "ua1"
    @State private var report: VerificationReport?
    @State private var reportURL: URL?
    @State private var signedURL: URL?
    @State private var error = ""

    init(initialMode: String = "sign") {
        _mode = State(initialValue: ["sign", "verify", "pdfa", "pdfua"].contains(initialMode) ? initialMode : "sign")
    }

    private var title: String {
        switch mode {
        case "sign": return "Assinatura digital"
        case "verify": return "Verificar assinaturas"
        case "pdfa": return "Validar PDF/A"
        default: return "Acessibilidade PDF/UA"
        }
    }
    private var operation: String {
        ["sign": "digital-sign", "verify": "verify-signatures", "pdfa": "validate-pdfa", "pdfua": "validate-pdfua"][mode] ?? "verify-signatures"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Label(title, systemImage: mode == "sign" ? "signature" : "checkmark.shield").font(.title2.bold())
                Spacer()
                Button { model.section = "Início"; dismiss() } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain).accessibilityLabel("Fechar verificação").disabled(model.busy)
            }.padding(24)
            Picker("Ferramenta", selection: $mode) {
                Text("Assinar").tag("sign")
                Text("Assinaturas").tag("verify")
                Text("PDF/A").tag("pdfa")
                Text("PDF/UA").tag("pdfua")
            }.pickerStyle(.segmented).padding(.horizontal, 24).padding(.bottom, 18).disabled(model.busy)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    sourceSection
                    if mode == "sign" { signingOptions }
                    else if mode == "verify" { trustOptions }
                    else { standardsOptions }
                    if let signedURL {
                        Label("Cópia assinada: \(signedURL.lastPathComponent)", systemImage: "doc.badge.checkmark")
                            .foregroundStyle(.green)
                        HStack {
                            Button("Mostrar cópia") { NSWorkspace.shared.activateFileViewerSelecting([signedURL]) }
                            Button("Verificar esta cópia") { source = signedURL; mode = "verify" }
                        }
                    }
                    if let report { reportSection(report) }
                    if !error.isEmpty { Text(error).foregroundStyle(.red).textSelection(.enabled) }
                }.padding(24)
            }
            Divider()
            HStack {
                if model.busy {
                    ProgressView().controlSize(.small)
                    Text(model.message).font(.caption).lineLimit(2)
                    Spacer()
                    Button("Cancelar operação") { model.cancel() }
                } else {
                    Text(mode == "sign" ? "O original será preservado." : "Relatório local, sem alterar o documento.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button(mode == "sign" ? "Salvar cópia assinada…" : "Validar e salvar relatório…") { perform() }
                        .buttonStyle(.borderedProminent).disabled(source == nil || (mode == "sign" && certificate == nil))
                }
            }.padding(20)
        }
        .frame(minWidth: 680, idealWidth: 760, maxWidth: .infinity, minHeight: 560, idealHeight: 720, maxHeight: .infinity)
        .onAppear {
            if !model.hasUnsavedChanges { source = model.savedDocumentURL ?? model.url }
        }
        .onChange(of: mode) { _, value in
            report = nil; reportURL = nil; error = ""
            if value != "sign" { certificatePIN = "" }
        }
        .onChange(of: source) { _, _ in
            report = nil; reportURL = nil; signedURL = nil; error = ""
        }
        .onDisappear { certificatePIN = "" }
    }

    private var sourceSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Documento").font(.headline)
            HStack {
                Label(source?.lastPathComponent ?? "Selecione um PDF", systemImage: "doc.richtext")
                    .lineLimit(2).textSelection(.enabled)
                Spacer()
                Button("Escolher PDF…") { selectPDF() }
            }
            if model.hasUnsavedChanges {
                Text("O leitor tem alterações ainda não salvas. Escolha uma cópia salva para assinar ou verificar exatamente seus bytes.")
                    .font(.caption).foregroundStyle(.orange)
            }
        }.disabled(model.busy)
    }

    private var signingOptions: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Seu certificado local").font(.headline)
            Text("Assinatura criptográfica PAdES com SHA-256. Usa um novo campo invisível e preserva os bytes das revisões anteriores. Adicione uma marca visual antes de assinar, se desejar.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Text(certificate?.lastPathComponent ?? "PKCS#12 · .p12 ou .pfx").lineLimit(1)
                Spacer()
                Button("Escolher certificado…") { selectCertificate() }
            }
            SecureField("PIN ou senha do certificado", text: $certificatePIN).textFieldStyle(.roundedBorder)
            Text("O PIN segue somente pela entrada privada do processo e não é salvo em configurações ou histórico. A chave privada permanece no certificado local e na memória durante a assinatura.")
                .font(.caption).foregroundStyle(.secondary)
            TextField("Motivo da assinatura (opcional)", text: $reason).textFieldStyle(.roundedBorder)
            TextField("Local (opcional)", text: $location).textFieldStyle(.roundedBorder)
            TextField("Nome único do campo", text: $fieldName).textFieldStyle(.roundedBorder)
            Toggle("Adicionar carimbo do tempo de uma TSA escolhida por mim", isOn: $useTimestamp)
            if useTimestamp {
                TextField("https://servidor-da-sua-tsa", text: $timestampURL).textFieldStyle(.roundedBorder)
                Text("Somente o resumo criptográfico RFC 3161 será enviado ao endereço informado. A TSA pode exigir contratação; redirecionamentos e credenciais na URL são recusados. Nenhum documento ou PIN é enviado.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text("Certificado autoemitido não certifica identidade. Esta ferramenta não atribui assinatura qualificada, validade jurídica ou preservação PAdES-LT/LTA.")
                .font(.caption).foregroundStyle(.secondary)
        }.disabled(model.busy)
    }

    private var trustOptions: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Confiança explícita").font(.headline)
            Text("A integridade pode ser verificada sem escolher raízes. Para avaliar a cadeia, adicione certificados públicos PEM ou DER cuja autoridade você reconhece. O repositório de confiança do sistema não é usado automaticamente.")
                .font(.callout).foregroundStyle(.secondary)
            HStack {
                Button("Adicionar raízes de confiança…") { selectRoots() }
                if !roots.isEmpty { Button("Limpar") { roots = [] } }
            }
            ForEach(roots, id: \.path) { url in Label(url.lastPathComponent, systemImage: "checkmark.seal").font(.caption) }
            Text("Verificação offline: sem consulta OCSP, CRL ou de revogação. Uma cadeia confiável aqui não comprova que o certificado não foi revogado nem confirma a identidade civil do titular.")
                .font(.caption).foregroundStyle(.secondary)
        }.disabled(model.busy)
    }

    private var standardsOptions: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Validador independente veraPDF 1.30.3", systemImage: "checkmark.seal").font(.headline)
            if mode == "pdfa" {
                Picker("Perfil PDF/A", selection: $archiveProfile) {
                    ForEach(["1a", "1b", "2a", "2b", "2u", "3a", "3b", "3u", "4", "4f", "4e"], id: \.self) { Text("PDF/A-\($0)").tag($0) }
                }
                Text("A ferramenta PDF para PDF/A cria uma cópia para arquivamento. Esta validação examina todas as regras do perfil escolhido e relata as falhas encontradas.")
                    .font(.callout).foregroundStyle(.secondary)
            } else {
                Picker("Perfil PDF/UA", selection: $accessibilityProfile) {
                    Text("PDF/UA-1").tag("ua1")
                    Text("PDF/UA-2").tag("ua2")
                }
                Text("Verifica estrutura de tags, idioma, fontes e outras regras automáticas. Tags não são criadas automaticamente. Metadados ou a marca Marked=true isoladamente não tornam um documento acessível.")
                    .font(.callout).foregroundStyle(.secondary)
                Text("A revisão humana continua necessária: ordem de leitura, títulos, significado dos textos alternativos, tabelas, navegação e teste com leitor de tela.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text("O relatório JSON inclui a evidência XML original, regras, severidade e SHA-256 dos bytes examinados. O validador opera localmente.")
                .font(.caption).foregroundStyle(.secondary)
        }.disabled(model.busy)
    }

    private func reportSection(_ value: VerificationReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            Text("Resultado da verificação").font(.title3.bold())
            Text(value.summary).font(.headline).textSelection(.enabled)
            if let count = value.signatureCount { Text("\(count) assinatura(s) digital(is) encontrada(s)").font(.caption) }
            ForEach(Array((value.signatures ?? []).enumerated()), id: \.offset) { _, signature in
                VStack(alignment: .leading, spacing: 5) {
                    Text(signature.fieldName).font(.headline)
                    Text("Integridade: \(signature.integrityOK == true ? "confirmada" : "não confirmada") · Cadeia: \(signature.trusted == true ? "confiança local estabelecida" : "não confiável")")
                    if let certificate = signature.certificate {
                        Text(certificate.subject).textSelection(.enabled)
                        Text("Validade até \(certificate.notAfter)\(certificate.expired ? " · expirado" : "")")
                        Text("SHA-256: \(certificate.sha256)").font(.caption.monospaced()).textSelection(.enabled)
                    }
                    if let coverage = signature.coverage { Text("Cobertura: \(coverage)").font(.caption) }
                }.padding(12).background(.quaternary, in: RoundedRectangle(cornerRadius: 12))
            }
            ForEach(Array(value.findings.enumerated()), id: \.offset) { _, finding in
                VStack(alignment: .leading, spacing: 5) {
                    Label(finding.rule, systemImage: finding.severity == "error" ? "xmark.octagon" : "exclamationmark.triangle")
                        .font(.caption.bold()).foregroundStyle(finding.severity == "error" ? Color.red : Color.orange)
                    Text(finding.message).font(.callout).textSelection(.enabled)
                }
            }
            if let url = reportURL {
                HStack {
                    Button("Abrir relatório completo") { NSWorkspace.shared.open(url) }
                    Button("Mostrar no Finder") { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                }
            }
        }
    }

    private func selectPDF() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        if panel.runModal() == .OK { source = panel.url; report = nil; error = "" }
    }
    private func selectCertificate() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = ["p12", "pfx"].compactMap { UTType(filenameExtension: $0) }
        if panel.runModal() == .OK { certificate = panel.url; certificatePIN = "" }
    }
    private func selectRoots() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true
        panel.allowedContentTypes = ["pem", "cer", "crt", "der"].compactMap { UTType(filenameExtension: $0) }
        if panel.runModal() == .OK { roots = Array(Set(roots + panel.urls)).sorted { $0.path < $1.path } }
    }
    private func perform() {
        guard let source else { return }
        error = ""
        let signing = mode == "sign"
        var options: [String: Any] = [:]
        if signing {
            guard let certificate else { return }
            options = ["certificate": certificate.path, "certificate_password": certificatePIN,
                       "reason": reason, "location": location, "field_name": fieldName]
            if useTimestamp { options["tsa_url"] = timestampURL.trimmingCharacters(in: .whitespacesAndNewlines) }
            if useTimestamp && timestampURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                error = "Informe o endereço HTTPS da TSA escolhida."; return
            }
        } else if mode == "verify" { options["trust_roots"] = roots.map(\.path) }
        else { options["flavour"] = mode == "pdfa" ? archiveProfile : accessibilityProfile }
        let panel = NSSavePanel(); panel.allowedContentTypes = signing ? [.pdf] : [.json]
        panel.nameFieldStringValue = source.deletingPathExtension().lastPathComponent + (signing ? "-assinado.pdf" : "-verificacao.json")
        guard panel.runModal() == .OK, let output = panel.url else { return }
        guard !FileManager.default.fileExists(atPath: output.path) else { error = "Escolha um novo destino para preservar os arquivos existentes."; return }
        certificatePIN = ""; report = nil; reportURL = nil
        model.execute(operation: operation, inputs: [source], output: output, options: options, title: title, completion: { result in
            switch result {
            case .success(let url):
                if signing { signedURL = url }
                else {
                    do {
                        let data = try Data(contentsOf: url)
                        report = try JSONDecoder().decode(VerificationReport.self, from: data)
                        reportURL = url
                    } catch { self.error = "O relatório foi salvo, mas sua prévia não pôde ser exibida: \(error.localizedDescription)"; reportURL = url }
                }
            case .failure(let failure): error = failure.localizedDescription
            }
        })
    }
}

private struct VerificationReport: Decodable {
    let summary: String
    let findings: [Finding]
    let signatureCount: Int?
    let signatures: [Signature]?
    enum CodingKeys: String, CodingKey { case summary, findings, signatures; case signatureCount = "signature_count" }
    struct Finding: Decodable { let severity: String; let rule: String; let message: String }
    struct Signature: Decodable {
        let fieldName: String
        let integrityOK: Bool?
        let trusted: Bool?
        let coverage: String?
        let certificate: Certificate?
        enum CodingKeys: String, CodingKey {
            case trusted, coverage, certificate
            case fieldName = "field_name", integrityOK = "integrity_ok"
        }
    }
    struct Certificate: Decodable {
        let subject: String
        let notAfter: String
        let sha256: String
        let expired: Bool
        enum CodingKeys: String, CodingKey { case subject, sha256, expired; case notAfter = "not_after" }
    }
}
