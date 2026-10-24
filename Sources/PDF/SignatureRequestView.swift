import SwiftUI
import AppKit
import UniformTypeIdentifiers
import CryptoKit
import Security

enum SignatureServiceCredential {
    private static let service = "PDF.DropboxSign.API"
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "api-key"]
    }
    static func save(_ value: String) throws {
        guard !value.isEmpty, value.utf8.count <= 4096 else { throw failure("Informe uma chave válida.") }
        let data = Data(value.utf8)
        let update = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if update == errSecItemNotFound {
            var item = query; item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw failure("Não foi possível guardar a chave no Chaves do macOS.") }
        } else if update != errSecSuccess { throw failure("Não foi possível atualizar a chave no Chaves do macOS.") }
    }
    static func load() throws -> String? {
        var request = query; request[kSecReturnData as String] = true; request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?; let status = SecItemCopyMatching(request as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data, let value = String(data: data, encoding: .utf8) else { throw failure("A chave não pôde ser lida no Chaves do macOS.") }
        return value
    }
    static func remove() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw failure("Não foi possível remover a chave.") }
    }
    private static func failure(_ text: String) -> NSError { NSError(domain: "PDF.SignatureService", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
}

private struct RequestRecipient: Identifiable {
    let id = UUID()
    var name = ""
    var email = ""
    var page = 1
    var x = 50
    var y = 100
    var width = 200
    var height = 40
}
struct SignatureRequestView: View {
    @EnvironmentObject private var model: Workspace
    @State private var source: URL?
    @State private var recipients = [RequestRecipient()]
    @State private var title = "Documento para assinatura"
    @State private var subject = "Solicitação de assinatura"
    @State private var message = ""
    @State private var testMode = true
    @State private var apiKey = ""
    @State private var draft: URL?
    @State private var draftHash = ""
    @State private var sourceHash = ""
    @State private var reviewedSummary = ""
    @State private var attemptRecord: URL?
    @State private var requestID = ""
    @State private var resultText = ""
    @State private var resultURL: URL?
    @State private var error = ""
    @State private var credentialNotice = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Label("Solicitar assinaturas", systemImage: "signature").font(.title2.bold())
                Text("Prepare localmente, revise o documento e os destinatários e envie pelo Dropbox Sign somente quando decidir. Requer uma conta e uma chave de API do serviço.").foregroundStyle(.secondary)
                GroupBox("Conexão com Dropbox Sign") {
                    VStack(alignment: .leading, spacing: 10) {
                        SecureField("Chave da API (ou use a chave já guardada)", text: $apiKey).textFieldStyle(.roundedBorder)
                        HStack {
                            Button("Guardar no Chaves…") { storeCredential() }
                            Button("Remover chave guardada") { do { try SignatureServiceCredential.remove(); credentialNotice = "Chave removida." } catch { self.error = error.localizedDescription } }
                            Link("Documentação oficial", destination: URL(string: "https://developers.hellosign.com/api/reference/operation/signatureRequestSend/")!)
                        }
                        Text(credentialNotice.isEmpty ? "A chave não é salva em preferências, rascunhos nem histórico. PDF_DROPBOX_SIGN_API_KEY também pode ser configurada no ambiente." : credentialNotice).font(.caption).foregroundStyle(.secondary)
                    }
                }
                HStack {
                    Label(source?.lastPathComponent ?? "Escolha um PDF salvo", systemImage: "doc.richtext")
                    Spacer(); Button("Escolher PDF…") { choose() }
                }
                TextField("Título no serviço", text: $title).textFieldStyle(.roundedBorder)
                TextField("Assunto do email", text: $subject).textFieldStyle(.roundedBorder)
                TextField("Mensagem aos destinatários", text: $message, axis: .vertical).lineLimit(2...5).textFieldStyle(.roundedBorder)
                Toggle("Modo de teste do provedor", isOn: $testMode)
                Text("O modo de teste não produz assinatura juridicamente vinculante segundo o provedor, mas ainda pode enviar emails reais aos destinatários.").font(.caption).foregroundStyle(.secondary)
                ForEach($recipients) { $recipient in
                    GroupBox("Destinatário e campo de assinatura") {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                TextField("Nome", text: $recipient.name).textFieldStyle(.roundedBorder)
                                TextField("Email", text: $recipient.email).textFieldStyle(.roundedBorder)
                                Button(role: .destructive) { recipients.removeAll { $0.id == recipient.id } } label: { Image(systemName: "minus.circle") }.disabled(recipients.count == 1)
                            }
                            HStack {
                                coordinate("Página", value: $recipient.page)
                                coordinate("X", value: $recipient.x)
                                coordinate("Y", value: $recipient.y)
                                coordinate("Largura", value: $recipient.width)
                                coordinate("Altura", value: $recipient.height)
                            }
                        }
                    }
                }
                Button("Adicionar destinatário") { recipients.append(RequestRecipient()) }.disabled(recipients.count >= 20)
                Text("Posições usam pixels a 72 DPI (um ponto PDF por pixel), por página, com origem superior esquerda. O campo inteiro deve caber na página visível. Revise as posições no documento; a preparação não redimensiona o PDF.").font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Preparar rascunho local…") { prepare() }.buttonStyle(.borderedProminent).disabled(source == nil)
                    if let draft { Button("Abrir rascunho") { NSWorkspace.shared.open(draft) } }
                }
                if draft != nil {
                    GroupBox("Preparação que será enviada") {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(reviewedSummary).textSelection(.enabled)
                            Text("SHA-256 do PDF: \(sourceHash)").font(.caption.monospaced()).textSelection(.enabled)
                            Text("Alterações nos controles acima exigem preparar um novo rascunho. O envio usa exatamente o rascunho revisado.").font(.caption).foregroundStyle(.secondary)
                            Button("Revisar e enviar ao Dropbox Sign…") { send() }.buttonStyle(.borderedProminent)
                        }
                    }
                }
                Divider()
                HStack {
                    TextField("Identificador de solicitação", text: $requestID).textFieldStyle(.roundedBorder)
                    Button("Consultar estado…") { status() }.disabled(requestID.isEmpty)
                }
                if let attemptRecord, FileManager.default.fileExists(atPath: attemptRecord.path) {
                    Button("Abrir registro local da tentativa") { NSWorkspace.shared.open(attemptRecord) }
                }
                if !resultText.isEmpty { Text(resultText).textSelection(.enabled) }
                if let resultURL { Button("Abrir relatório completo") { NSWorkspace.shared.open(resultURL) } }
                if !error.isEmpty { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            }.padding(24).disabled(model.busy)
        }.safeAreaInset(edge: .bottom) {
            if model.busy { HStack { ProgressView().controlSize(.small); Text(model.message); Spacer(); Button("Cancelar") { model.cancel() } }.padding() }
        }.frame(minWidth: 760, minHeight: 620)
            .onAppear { if !model.hasUnsavedChanges { source = model.savedDocumentURL ?? model.url } }
            .onDisappear { apiKey = "" }
    }
    private func coordinate(_ label: String, value: Binding<Int>) -> some View {
        VStack(alignment: .leading) { Text(label).font(.caption); TextField(label, value: value, format: .number).textFieldStyle(.roundedBorder).frame(width: 80) }
    }
    private func choose() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        if panel.runModal() == .OK { source = panel.url; draft = nil; attemptRecord = nil; resultText = ""; resultURL = nil; error = "" }
    }
    private func storeCredential() {
        do { try SignatureServiceCredential.save(apiKey); apiKey = ""; credentialNotice = "Chave guardada no Chaves deste Mac." }
        catch { self.error = error.localizedDescription }
    }
    private func credential() throws -> String? { apiKey.isEmpty ? try SignatureServiceCredential.load() : apiKey }
    private func prepare() {
        guard let source, let output = NativeOutput.destination(model: model, toolName: "Preparação de assinatura", extension: "json", originalURL: source) else { return }
        let signers = recipients.map { ["name": $0.name, "email_address": $0.email] }
        let fields: [[String: Any]] = recipients.enumerated().map { index, item in
            ["signer": index, "type": "signature", "page": item.page, "x": item.x, "y": item.y, "width": item.width, "height": item.height]
        }
        let options: [String: Any] = ["title": title, "subject": subject, "message": message, "test_mode": testMode, "signers": signers, "fields": fields]
        error = ""; draft = nil
        model.execute(operation: "signature-request-prepare", inputs: [source], output: output, options: options, title: "Preparando solicitação local", completion: { outcome in
            do {
                let url = try outcome.get(); let data = try Data(contentsOf: url)
                guard data.count <= 2 * 1024 * 1024, let value = try JSONSerialization.jsonObject(with: data) as? [String: Any], let digest = value["input_sha256"] as? String,
                      let draftID = value["draft_id"] as? String, draftID.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil,
                      let configuration = value["configuration"] as? [String: Any], let people = configuration["signers"] as? [[String: Any]] else { throw NSError(domain: "PDF.SignatureRequest", code: 1) }
                draft = url; draftHash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined(); sourceHash = digest
                attemptRecord = url.deletingLastPathComponent().appendingPathComponent(".pdf-signature-attempt-" + draftID + ".json")
                reviewedSummary = "\(source.lastPathComponent)\n\(configuration["subject"] as? String ?? "")\n" + people.map { "\($0["name"] as? String ?? "") <\($0["email_address"] as? String ?? "")>" }.joined(separator: "\n") + "\nModo de teste: \((configuration["test_mode"] as? Bool) == true ? "sim" : "não")"
            } catch { self.error = error.localizedDescription }
        })
    }
    private func send() {
        guard let source, let draft else { return }
        let alert = NSAlert(); alert.messageText = "Enviar PDF e solicitar assinaturas?"
        alert.informativeText = reviewedSummary + "\n\nO PDF, os campos, nomes, emails e mensagem serão enviados ao Dropbox Sign. O serviço pode enviar emails reais, inclusive em modo de teste."
        alert.addButton(withTitle: "Enviar solicitação"); alert.addButton(withTitle: "Cancelar")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        guard let output = NativeOutput.destination(model: model, toolName: "Solicitação enviada", extension: "json", originalURL: source) else { return }
        do {
            var options: [String: Any] = ["draft": draft.path, "confirm_send": true, "confirmed_sha256": sourceHash, "confirmed_draft_sha256": draftHash]
            if let key = try credential() { options["api_key"] = key }
            apiKey = ""; error = ""
            model.execute(operation: "signature-request-send", inputs: [source], output: output, options: options, title: "Enviando solicitação", completion: { outcome in
                handle(outcome, sending: true)
            })
        } catch { self.error = error.localizedDescription }
    }
    private func status() {
        guard let output = NativeOutput.destination(model: model, toolName: "Estado de assinatura", extension: "json", originalURL: source) else { return }
        do {
            var options: [String: Any] = ["request_id": requestID]
            if let key = try credential() { options["api_key"] = key }
            apiKey = ""; error = ""
            model.execute(operation: "signature-request-status", inputs: [source ?? URL(fileURLWithPath: "/dev/null")], output: output, options: options, title: "Consultando solicitação", completion: { outcome in handle(outcome, sending: false) })
        } catch { self.error = error.localizedDescription }
    }
    private func handle(_ outcome: Result<URL, Error>, sending: Bool) {
        do {
            let url = try outcome.get(); let data = try Data(contentsOf: url)
            guard data.count <= 2 * 1024 * 1024, let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw NSError(domain: "PDF.SignatureRequest", code: 2) }
            requestID = result["signature_request_id"] as? String ?? requestID
            let completed = result["is_complete"] as? Bool == true
            let failed = result["has_error"] as? Bool == true
            let heading = failed ? "O serviço informou um erro na solicitação." : completed ? "Solicitação concluída no Dropbox Sign." : sending ? "Solicitação enviada ao Dropbox Sign." : "Solicitação em andamento."
            let people = result["signatures"] as? [[String: Any]] ?? []
            let lines = people.map { person -> String in
                let name = person["signer_name"] as? String ?? "Destinatário"
                let status = person["status_code"] as? String ?? ""
                let label = ["signed": "assinou", "awaiting_signature": "aguardando assinatura", "declined": "recusou", "error": "erro informado pelo serviço" ][status] ?? "estado disponível no relatório"
                return "\(name): \(label)"
            }
            resultText = ([heading] + lines + ["A integridade criptográfica do PDF final deve ser verificada separadamente."]).joined(separator: "\n")
            resultURL = url
            if sending { draft = nil }
        } catch {
            if sending, let attemptRecord,
               let size = (try? FileManager.default.attributesOfItem(atPath: attemptRecord.path)[.size] as? NSNumber)?.intValue,
               size <= 8192, let data = try? Data(contentsOf: attemptRecord),
               let record = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let identifier = record["signature_request_id"] as? String {
                requestID = identifier
            }
            self.error = error.localizedDescription + (sending ? "\nUm envio pode ter ocorrido. Consulte a conta ou o identificador recebido antes de repetir; o aplicativo não repete envios automaticamente." : "")
        }
    }
}
