import SwiftUI
import AppKit
import CryptoKit
import Darwin

struct ReadingSourceIdentity:Sendable {
    let url:URL
    let sha256:String
    let size:Int64
    let inode:UInt64
    let modifiedSeconds:Int
    let modifiedNanoseconds:Int
    func stillMatchesFile() -> Bool {
        var value = stat()
        guard lstat(url.path,&value) == 0,value.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG) else { return false }
        return value.st_size == size && UInt64(value.st_ino) == inode && value.st_mtimespec.tv_sec == modifiedSeconds && value.st_mtimespec.tv_nsec == modifiedNanoseconds
    }
    static func read(_ url:URL,cancellation:NativeCancellation) throws -> ReadingSourceIdentity {
        guard url.isFileURL else { throw PreferenceError.invalid("Escolha um PDF local salvo.") }
        let descriptor = Darwin.open(url.path,O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard descriptor >= 0 else { throw PreferenceError.invalid("Não foi possível ler o arquivo salvo sem seguir links.") }
        let handle = FileHandle(fileDescriptor:descriptor,closeOnDealloc:true); defer { try? handle.close() }
        var initial = stat()
        guard fstat(descriptor,&initial) == 0,initial.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG),initial.st_size > 0,initial.st_size <= 2_147_483_648 else { throw PreferenceError.invalid("A troca de marcadores aceita arquivos PDF regulares de até 2 GB.") }
        var hash = SHA256(),length:Int64 = 0
        while let chunk = try handle.read(upToCount:1_048_576),!chunk.isEmpty {
            try cancellation.check(); length += Int64(chunk.count)
            guard length <= initial.st_size else { throw PreferenceError.invalid("O arquivo mudou durante a leitura.") }
            hash.update(data:chunk)
        }
        let result = ReadingSourceIdentity(url:url.standardizedFileURL,sha256:hash.finalize().map{String(format:"%02x",$0)}.joined(),size:initial.st_size,inode:UInt64(initial.st_ino),modifiedSeconds:initial.st_mtimespec.tv_sec,modifiedNanoseconds:initial.st_mtimespec.tv_nsec)
        guard length == initial.st_size,result.stillMatchesFile() else { throw PreferenceError.invalid("O arquivo mudou durante a leitura. Tente novamente após terminar a gravação.") }
        return result
    }
}

struct PDFReadingExchangeSnapshot:Codable {
    var version = 1
    var documentHash:String
    var title:String
    var pageCount:Int
    var bookmarks:[Int]
    var page:Int
    var zoom:Double
    var autoScale:Bool
    func validate() throws {
        guard version == 1,LibraryFiles.validHash(documentHash),!title.isEmpty,title.count <= 300,(1...1_000_000).contains(pageCount),(1...pageCount).contains(page),zoom.isFinite,(0.1...8).contains(zoom),bookmarks.count <= pageCount,Set(bookmarks).count == bookmarks.count,bookmarks.allSatisfy({(1...pageCount).contains($0)}) else { throw PreferenceError.invalid("O estado de leitura recebido é inválido.") }
    }
}

struct SettingsExchangeView:View {
    let store:DocumentLibraryStore
    @EnvironmentObject private var model:Workspace
    @EnvironmentObject private var preferences:AppearancePreferences
    @Environment(\.dismiss) private var dismiss
    @State private var kind = "preferences"
    @State private var snapshots:[LibraryConfigurationSnapshot] = []
    @State private var selected:LibraryConfigurationSnapshot?
    @State private var payload:Data?
    @State private var summary = ""
    @State private var message = ""
    @State private var busy = false
    @State private var confirmApply = false
    @State private var replaceProfiles = false
    @State private var replaceBookmarks = false
    @State private var restorePosition = false
    @State private var cancellation = NativeCancellation()
    private var filteredSnapshots: [LibraryConfigurationSnapshot] { snapshots.filter { $0.kind == kind } }
    var body:some View {
        VStack(alignment:.leading,spacing:16) {
            header
            contentPicker
            actions
            if kind == "bookmarks" { Text("Abra o mesmo PDF salvo no leitor. A associação usa SHA-256 dos bytes do arquivo, incluindo a proteção original; nomes e caminhos de outro Mac não são usados para escolher documentos.").font(.caption).foregroundStyle(.secondary) }
            if !message.isEmpty { Text(message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
            snapshotList
            if selected != nil,payload != nil { review }
            Spacer(minLength:0)
        }.padding(24).frame(width:760,height:690)
            .onAppear { reload() }.onDisappear { cancellation.cancel() }
            .confirmationDialog("Aplicar a versão escolhida neste Mac?",isPresented:$confirmApply,titleVisibility:.visible) {
                Button("Aplicar") { applySelected() }
                Button("Cancelar",role:.cancel) { }
            } message: { Text(kind == "preferences" ? "As preferências visuais, de leitura, atalhos e saída serão substituídas. Perfis nomeados e documentos permanecem guardados." : "Serão usadas as opções de conflito e posição que você escolheu nesta tela.") }
    }
    private var header: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Ajustes entre seus Macs").font(.title2.bold())
                Spacer()
                Button("Concluir") { dismiss() }.disabled(busy)
            }
            Text("Guarde uma versão e use Sincronizar na biblioteca para trocá-la pela pasta escolhida. Versões recebidas ficam disponíveis para revisão; seus ajustes só mudam quando você aplicar uma delas.")
                .font(.callout).foregroundStyle(.secondary)
        }
    }
    private var contentPicker: some View {
        Picker("Conteúdo", selection: $kind) {
            Text("Preferências").tag("preferences")
            Text("Perfis nomeados").tag("profiles")
            Text("Marcadores e leitura").tag("bookmarks")
        }.pickerStyle(.segmented).disabled(busy)
            .onChange(of: kind) { selected = nil; payload = nil; summary = "" }
    }
    private var actions: some View {
        HStack {
            Button("Guardar versão deste Mac") { publish() }.disabled(busy)
            Button("Atualizar recebidas") { reload() }.disabled(busy)
            Spacer()
            if busy {
                ProgressView().controlSize(.small)
                Button("Cancelar leitura") { cancellation.cancel() }
            }
        }
    }
    private var snapshotList: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(filteredSnapshots) { item in
                    SettingsExchangeSnapshotRow(item: item, selected: selected?.id == item.id, busy: busy) { inspect(item) }
                }
                if filteredSnapshots.isEmpty {
                    Text("Nenhuma versão desta categoria está disponível na biblioteca local.")
                        .foregroundStyle(.secondary).padding(.vertical)
                }
            }
        }.frame(maxHeight: 220)
    }
    private var review: some View {
        VStack(alignment: .leading, spacing: 16) {
            Divider()
            Text("Revisão antes de aplicar").font(.headline)
            Text(summary).font(.callout).textSelection(.enabled)
            if kind == "profiles" {
                Toggle("Substituir perfis com o mesmo identificador", isOn: $replaceProfiles)
                Text("Desativado: conflitos são guardados como novas cópias com nomes distintos.").font(.caption).foregroundStyle(.secondary)
            }
            if kind == "bookmarks" {
                Toggle("Substituir os marcadores atuais", isOn: $replaceBookmarks)
                Toggle("Restaurar também página e zoom", isOn: $restorePosition)
                Text("Desativados: os marcadores são unidos e sua posição de leitura permanece atual.").font(.caption).foregroundStyle(.secondary)
            }
            Button("Aplicar versão escolhida…") { confirmApply = true }.buttonStyle(.borderedProminent).disabled(busy)
        }
    }
    private func reload() {
        guard !busy, ApplicationWork.isAcceptingWork else { return }; busy = true; cancellation = NativeCancellation()
        let token = cancellation
        ApplicationTask.start(cancel: { token.cancel() }) { defer { busy = false }; do { try Task.checkCancellation(); let values = try await store.configurationSnapshots(); try token.check(); snapshots = values; message = "\(PortugueseCount.label(snapshots.count, "versão local disponível", "versões locais disponíveis"))." } catch { message = error.localizedDescription } }
    }
    private func inspect(_ item:LibraryConfigurationSnapshot) {
        guard !busy, ApplicationWork.isAcceptingWork else { return }; busy = true; selected = nil; payload = nil; cancellation = NativeCancellation()
        let token = cancellation
        ApplicationTask.start(cancel: { token.cancel() }) { defer { busy = false }; do { try Task.checkCancellation();
            let bytes = try await store.loadConfiguration(item)
            try token.check()
            let detail:String
            switch item.kind {
            case "preferences":
                var settings = try JSONDecoder().decode(CustomizationSnapshot.self,from:bytes)
                try settings.appearance.validate(); try settings.reader.validate()
                if let shortcuts = settings.shortcuts { try AdvancedCustomizationStore.validate(shortcuts) }; try settings.output?.validate()
                detail = "Tema: \(settings.appearance.colorScheme) · destaque: \(settings.appearance.accentHex) · visualização: \(settings.appearance.layout).\n\(PortugueseCount.label(settings.appearance.hiddenTools.count, "ferramenta oculta", "ferramentas ocultas")); \(PortugueseCount.label(settings.shortcuts?.bindings.count ?? 0, "atalho personalizado", "atalhos personalizados")). Revise a pasta de saída depois de aplicar configurações de outro Mac."
            case "profiles":
                let value = try AdvancedCustomizationStore.decodeProfiles(bytes)
                let existing = Set(preferences.advanced.profiles.map(\.id)),conflicts = value.profiles.filter{existing.contains($0.id)}.count
                detail = "\(PortugueseCount.label(value.profiles.count, "perfil recebido", "perfis recebidos")); \(PortugueseCount.label(conflicts, "identificador já existe", "identificadores já existem")) neste Mac.\n"+value.profiles.map(\.name).joined(separator:", ")
            case "bookmarks":
                let value = try JSONDecoder().decode(PDFReadingExchangeSnapshot.self,from:bytes); try value.validate()
                detail = "\(value.title) · \(PortugueseCount.label(value.pageCount, "página", "páginas")) · \(PortugueseCount.label(value.bookmarks.count, "marcador", "marcadores")).\nPosição guardada: página \(value.page), zoom \(Int(value.zoom*100))%.\nSHA-256: \(value.documentHash)"
            default: throw PreferenceError.invalid("Tipo de configuração não reconhecido.")
            }
            selected = item; payload = bytes; summary = detail; message = "Integridade verificada. Confira as opções antes de aplicar."
        } catch { message = error.localizedDescription } }
    }
    private func publish() {
        guard !busy, ApplicationWork.isAcceptingWork else { return }; busy = true; cancellation = NativeCancellation()
        let chosenKind = kind, token = cancellation
        ApplicationTask.start(cancel: { token.cancel() }) { defer { busy = false }; do { try Task.checkCancellation();
            let bytes:Data
            switch chosenKind {
            case "preferences":bytes = try preferences.exportData()
            case "profiles":bytes = try preferences.advanced.exportProfiles()
            default:
                let reading = try currentReadingSource()
                let source = try await Task.detached(priority:.utility) { try ReadingSourceIdentity.read(reading.url,cancellation:token) }.value
                try token.check()
                try verifyCurrent(reading,source:source)
                let snapshot = PDFReadingExchangeSnapshot(documentHash:source.sha256,title:reading.title,pageCount:reading.pages,bookmarks:reading.bookmarks.sorted(),page:reading.page,zoom:reading.zoom,autoScale:reading.autoScale)
                try snapshot.validate(); bytes = try JSONEncoder().encode(snapshot)
            }
            try token.check(); _ = try await store.publishConfiguration(kind:chosenKind,payload:bytes)
            snapshots = try await store.configurationSnapshots(); message = "Versão guardada. Sincronize a biblioteca pela pasta escolhida para disponibilizá-la aos seus outros Macs."
        } catch { message = error.localizedDescription } }
    }
    private func applySelected() {
        guard !busy,ApplicationWork.isAcceptingWork,let item = selected,let bytes = payload else { return }; busy = true; cancellation = NativeCancellation()
        let token = cancellation, replaceProfiles = replaceProfiles,replaceBookmarks = replaceBookmarks,restorePosition = restorePosition
        ApplicationTask.start(cancel: { token.cancel() }) { defer { busy = false }; do { try Task.checkCancellation();
            // Re-read the immutable record rather than trusting a stale selection.
            guard try await store.loadConfiguration(item) == bytes else { throw PreferenceError.invalid("A versão mudou durante a revisão.") }
            try token.check()
            switch item.kind {
            case "preferences":try preferences.importData(bytes)
            case "profiles":try preferences.advanced.importProfiles(bytes,policy:replaceProfiles ? .replaceMatchingIdentifiers : .keepBoth)
            case "bookmarks":
                let incoming = try JSONDecoder().decode(PDFReadingExchangeSnapshot.self,from:bytes); try incoming.validate()
                let reading = try currentReadingSource()
                let source = try await Task.detached(priority:.utility) { try ReadingSourceIdentity.read(reading.url,cancellation:token) }.value
                try token.check()
                try verifyCurrent(reading,source:source)
                guard incoming.documentHash == source.sha256,incoming.pageCount == reading.pages else { throw PreferenceError.invalid("O PDF aberto tem bytes diferentes. Abra a mesma versão do documento para aplicar os marcadores.") }
                let marks = replaceBookmarks ? Set(incoming.bookmarks) : Set(incoming.bookmarks).union(model.bookmarks)
                try model.applyImportedReadingState(bookmarks:marks,page:restorePosition ? incoming.page : nil,zoom:restorePosition ? incoming.zoom : nil,autoScale:restorePosition ? incoming.autoScale : nil,expectedSessionID:reading.id,source:source,expectedHash:incoming.documentHash)
            default:throw PreferenceError.invalid("Tipo de configuração não reconhecido.")
            }
            message = "Versão aplicada neste Mac. Nenhum documento PDF foi substituído."
        } catch { message = error.localizedDescription } }
    }
    private struct ReadingSelection {
        var id:UUID; var url:URL; var title:String; var pages:Int; var bookmarks:Set<Int>; var page:Int; var zoom:Double; var autoScale:Bool
    }
    private func currentReadingSource() throws -> ReadingSelection {
        NSApp.keyWindow?.makeFirstResponder(nil); (model.pdfView as? DrawingPDFView)?.finishStroke(); model.captureActiveSession()
        guard let session = model.activeSession,let url = session.savedURL ?? session.sourceURL,!session.document.isLocked,!model.hasUnsavedChanges else { throw PreferenceError.invalid("Abra um documento salvo e salve suas alterações antes de trocar os marcadores.") }
        return .init(id:session.id,url:url.standardizedFileURL,title:session.title,pages:session.document.pageCount,bookmarks:model.bookmarks,page:model.currentPage,zoom:session.zoom,autoScale:session.autoScale)
    }
    private func verifyCurrent(_ selection:ReadingSelection,source:ReadingSourceIdentity) throws {
        guard model.activeSessionID == selection.id,let session = model.activeSession,(session.savedURL ?? session.sourceURL)?.standardizedFileURL == selection.url,session.document.pageCount == selection.pages,!model.hasUnsavedChanges,source.stillMatchesFile() else { throw PreferenceError.invalid("O documento ou a aba mudou durante a verificação. Selecione a versão novamente.") }
    }
}

private struct SettingsExchangeSnapshotRow: View {
    let item: LibraryConfigurationSnapshot
    let selected: Bool
    let busy: Bool
    let action: () -> Void
    private var sourceDescription: String {
        let device = String(item.device.uuidString.prefix(8))
        return "Mac \(device) · \(PortugueseCount.label(item.byteCount, "byte", "bytes"))"
    }
    var body: some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.created, style: .date)
                    Text(sourceDescription).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if selected { Image(systemName: "checkmark.circle.fill") }
            }.padding(12).contentShape(Rectangle())
                .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 12))
        }.buttonStyle(.plain).disabled(busy)
    }
}
