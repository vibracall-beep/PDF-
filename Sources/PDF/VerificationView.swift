import SwiftUI
import AppKit
import UniformTypeIdentifiers

private struct VerificationContext: Equatable {
    let mode: String
    let source: URL?
    let roots: [URL]
    let requireRevocation: Bool
    let crls: [URL]
    let ocspResponses: [URL]
    let endpoints: String
    let allowRevocationNetwork: Bool
    let validateLTA: Bool
    let archiveProfile: String
    let accessibilityProfile: String
}

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
    @State private var signatureProfile = "B-B"
    @State private var timestampURL = ""
    @State private var archiveProfile = "2b"
    @State private var accessibilityProfile = "ua1"
    @State private var report: VerificationReport?
    @State private var reportURL: URL?
    @State private var signedURL: URL?
    @State private var error = ""
    @State private var requireRevocation = false
    @State private var crls: [URL] = []
    @State private var ocspResponses: [URL] = []
    @State private var endpoints = ""
    @State private var allowRevocationNetwork = false
    @State private var validateLTA = false
    @State private var verificationGeneration = UUID()

    init(initialMode: String = "sign", sourceURL: URL? = nil) {
        _mode = State(initialValue: ["sign", "verify", "pdfa", "pdfua"].contains(initialMode) ? initialMode : "sign")
        _source = State(initialValue: sourceURL)
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
    private var validationContext: VerificationContext {
        VerificationContext(mode: mode, source: source, roots: roots, requireRevocation: requireRevocation,
            crls: crls, ocspResponses: ocspResponses, endpoints: endpoints,
            allowRevocationNetwork: allowRevocationNetwork, validateLTA: validateLTA,
            archiveProfile: archiveProfile, accessibilityProfile: accessibilityProfile)
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
            if source == nil && !model.hasUnsavedChanges { source = model.savedDocumentURL ?? model.url }
        }
        .onChange(of: mode) { _, value in
            report = nil; reportURL = nil; error = ""
            if value != "sign" { certificatePIN = "" }
        }
        .onChange(of: source) { _, _ in
            report = nil; reportURL = nil; signedURL = nil; error = ""
        }
        .onChange(of: validationContext) { _, _ in
            verificationGeneration = UUID()
            report = nil; reportURL = nil; error = ""
        }
        .onDisappear { certificatePIN = ""; verificationGeneration = UUID() }
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
            LabeledContent("PIN ou senha do certificado") {
                SecureField("PIN ou senha", text: $certificatePIN).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("PIN ou senha do certificado")
            }
            Text("O PIN segue somente pela entrada privada do processo e não é salvo em configurações ou histórico. A chave privada permanece no certificado local e na memória durante a assinatura.")
                .font(.caption).foregroundStyle(.secondary)
            LabeledContent("Motivo da assinatura") {
                TextField("Opcional", text: $reason).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Motivo da assinatura, opcional")
            }
            LabeledContent("Local") {
                TextField("Opcional", text: $location).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Local da assinatura, opcional")
            }
            LabeledContent("Nome único do campo") {
                TextField("Nome do campo", text: $fieldName).textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Nome único do campo de assinatura")
            }
            Picker("Perfil PAdES", selection: $signatureProfile) {
                Text("B-B · assinatura").tag("B-B")
                Text("B-T · carimbo do tempo").tag("B-T")
                Text("B-LT · evidências de validação").tag("B-LT")
                Text("B-LTA · preservação com carimbo documental").tag("B-LTA")
            }
            if signatureProfile != "B-B" {
                LabeledContent("URL do carimbo do tempo (TSA)") {
                    TextField("https://servidor-da-sua-tsa", text: $timestampURL).textFieldStyle(.roundedBorder)
                        .accessibilityLabel("URL do servidor de carimbo do tempo TSA")
                }
                Text("Somente o resumo criptográfico RFC 3161 será enviado ao endereço informado. A TSA pode exigir contratação; redirecionamentos e credenciais na URL são recusados. Nenhum documento ou PIN é enviado.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if ["B-LT", "B-LTA"].contains(signatureProfile) {
                trustOptions
                Text("LT/LTA exige uma cadeia confiável e OCSP/CRL válidos para todos os certificados não âncora, incluindo a TSA. A preservação de longo prazo exige renovação futura das provas de tempo.").font(.caption).foregroundStyle(.secondary)
            }
            Text("Certificado autoemitido não certifica identidade. A ferramenta não atribui assinatura qualificada nem validade jurídica.")
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
            if mode == "verify" { Toggle("Exigir prova OCSP/CRL válida de toda a cadeia", isOn: $requireRevocation) }
            if requireRevocation || (mode == "sign" && ["B-LT", "B-LTA"].contains(signatureProfile)) { revocationOptions }
            if mode == "verify" { Toggle("Avaliar provas AdES-LTA embutidas, sem rede", isOn: $validateLTA) }
            Text("Sem a exigência de revogação, uma cadeia confiável não comprova que o certificado continua não revogado. Nenhuma opção confirma identidade civil por si só.").font(.caption).foregroundStyle(.secondary)
        }.disabled(model.busy)
    }

    private var revocationOptions: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button("Adicionar CRL…") { selectRevocation(ocsp: false) }
                Button("Adicionar resposta OCSP…") { selectRevocation(ocsp: true) }
                Button("Limpar evidências") { crls = []; ocspResponses = [] }
            }
            Text("\(PortugueseCount.label(crls.count, "CRL", "CRLs")) · \(PortugueseCount.label(ocspResponses.count, "resposta OCSP local", "respostas OCSP locais"))").font(.caption)
            Toggle("Consultar somente os endpoints HTTPS abaixo", isOn: $allowRevocationNetwork)
            if allowRevocationNetwork {
                Text("Uma linha por endpoint: crl https://… ou ocsp https://…").font(.caption)
                TextEditor(text: $endpoints).font(.body.monospaced()).frame(height: 80).border(.quaternary)
                    .accessibilityLabel("Endpoints HTTPS autorizados, uma linha por CRL ou OCSP")
                Text("OCSP transmite identificadores do certificado; CRL baixa listas de revogação. URLs presentes no certificado não são consultadas sem sua seleção explícita. Não há redirecionamentos automáticos.").font(.caption).foregroundStyle(.secondary)
            }
        }
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
            if let count = value.signatureCount { Text("\(PortugueseCount.label(count, "assinatura digital encontrada", "assinaturas digitais encontradas"))").font(.caption) }
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
                    if let revocation = signature.revocation { Text("Revogação: \(revocation.label)").font(.caption) }
                    if let preservation = signature.longTermValidation {
                        Text("Preservação AdES-LTA: \(preservation.passed ? "provas validadas" : "não confirmada; consulte o relatório")").font(.caption)
                    }
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
    private func selectRevocation(ocsp: Bool) {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true
        if panel.runModal() == .OK {
            if ocsp { ocspResponses = Array(Set(ocspResponses + panel.urls)) }
            else { crls = Array(Set(crls + panel.urls)) }
        }
    }
    private func perform() {
        guard let source else { return }
        error = ""
        let signing = mode == "sign"
        var options: [String: Any] = [:]
        if signing {
            guard let certificate else { return }
            options = ["certificate": certificate.path, "certificate_password": certificatePIN,
                       "reason": reason, "location": location, "field_name": fieldName, "profile": signatureProfile]
            if signatureProfile != "B-B" { options["tsa_url"] = timestampURL.trimmingCharacters(in: .whitespacesAndNewlines) }
            if signatureProfile != "B-B" && timestampURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                error = "Informe o endereço HTTPS da TSA escolhida."; return
            }
        } else if mode == "verify" { options["validate_lta"] = validateLTA }
        else { options["flavour"] = mode == "pdfa" ? archiveProfile : accessibilityProfile }
        if mode == "verify" || (signing && ["B-LT", "B-LTA"].contains(signatureProfile)) {
            options["trust_roots"] = roots.map(\.path)
            let required = requireRevocation || signing
            options["revocation_mode"] = required ? "require" : "offline"
            if required {
                options["crls"] = crls.map(\.path); options["ocsp_responses"] = ocspResponses.map(\.path)
                options["allow_revocation_network"] = allowRevocationNetwork
                if allowRevocationNetwork {
                    var values: [[String: String]] = []
                    for line in endpoints.split(whereSeparator: \.isNewline) {
                        let parts = line.split(maxSplits: 1, whereSeparator: \.isWhitespace)
                        guard parts.count == 2, ["crl", "ocsp"].contains(String(parts[0])) else { error = "Use uma linha por endpoint: crl https://… ou ocsp https://…"; return }
                        values.append(["kind": String(parts[0]), "url": String(parts[1])])
                    }
                    options["revocation_endpoints"] = values
                }
            }
        }
        guard let output = NativeOutput.destination(model: model, toolName: title,
            extension: signing ? "pdf" : "json", originalURL: source) else { return }
        let submittedContext = validationContext
        let token = UUID(); verificationGeneration = token
        certificatePIN = ""; report = nil; reportURL = nil
        model.execute(operation: operation, inputs: [source], output: output, options: options, title: title, completion: { result in
            // A completed result remains a valid saved artifact, but belongs in
            // this view only while its source and validation options still match.
            guard verificationGeneration == token && validationContext == submittedContext else { return }
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
        let revocation: Revocation?
        let longTermValidation: LongTermValidation?
        enum CodingKeys: String, CodingKey {
            case trusted, coverage, certificate, revocation
            case fieldName = "field_name", integrityOK = "integrity_ok"
            case longTermValidation = "long_term_validation"
        }
    }
    struct Revocation: Decodable {
        let status: String
        var label: String {
            switch status {
            case "good": return "prova válida segundo a política escolhida"
            case "revoked": return "certificado revogado"
            case "not_required": return "não exigida nesta verificação"
            default: return "não confirmada"
            }
        }
    }
    struct LongTermValidation: Decodable { let status: String; let passed: Bool }
    struct Certificate: Decodable {
        let subject: String
        let notAfter: String
        let sha256: String
        let expired: Bool
        enum CodingKeys: String, CodingKey { case subject, sha256, expired; case notAfter = "not_after" }
    }
}
