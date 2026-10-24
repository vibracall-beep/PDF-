import SwiftUI
import AppKit
import Darwin

struct WatchedFolderRule: Codable, Identifiable {
    var id = UUID()
    var name:String
    var input:URL
    var output:URL
    var workflow:AutomationWorkflow
    var enabled = false
}
struct AutomationFileStamp: Equatable, Sendable {
    var size: Int
    var modified: Double
    var inode: UInt64
    var device: UInt64 = 0
    var modifiedNanoseconds: Int64 = 0
}
enum AutomationFolderInspector {
    /// Resolve only the already-validated directory. A child name is appended
    /// below this root; a leaf is always inspected with lstat, never resolved.
    static func canonicalDirectory(_ url:URL) throws -> URL {
        try Task.checkCancellation()
        guard url.isFileURL else { throw PreferenceError.invalid("Escolha pastas locais do Mac.") }
        var path = url.path
        while path.count > 1 && path.hasSuffix("/") { path.removeLast() }
        var original = stat()
        guard lstat(path,&original) == 0,original.st_mode & S_IFMT == S_IFDIR else {
            throw PreferenceError.invalid("Escolha uma pasta real e acessível, sem link simbólico.")
        }
        guard let resolved = realpath(path,nil) else { throw POSIXError(POSIXErrorCode(rawValue:errno) ?? .EIO) }
        defer { free(resolved) }
        let canonical = String(cString:resolved)
        var final = stat()
        guard lstat(canonical,&final) == 0,final.st_mode & S_IFMT == S_IFDIR,
              original.st_dev == final.st_dev,original.st_ino == final.st_ino else {
            throw PreferenceError.invalid("A pasta mudou durante a verificação. Escolha-a novamente.")
        }
        return URL(fileURLWithPath:canonical,isDirectory:true)
    }
    static func validate(input:URL,output:URL) throws {
        let source = try canonicalDirectory(input).path
        let destination = try canonicalDirectory(output).path
        func contains(_ parent:String,_ child:String)->Bool { child == parent || child.hasPrefix(parent.hasSuffix("/") ? parent : parent+"/") }
        guard !contains(source,destination),!contains(destination,source) else { throw PreferenceError.invalid("As pastas de entrada e saída devem ser separadas e não podem conter uma à outra.") }
        guard FileManager.default.isReadableFile(atPath:source),FileManager.default.isWritableFile(atPath:destination) else { throw PreferenceError.invalid("O PDF precisa ler a entrada e gravar na pasta de saída escolhida.") }
    }
    static func scan(_ folder:URL) throws -> [String:AutomationFileStamp] {
        let root = try canonicalDirectory(folder)
        var rootIdentity = stat()
        guard lstat(root.path,&rootIdentity) == 0,rootIdentity.st_mode & S_IFMT == S_IFDIR else { throw PreferenceError.invalid("A pasta monitorada deixou de estar disponível.") }
        let files = try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil,options:[.skipsHiddenFiles])
        guard files.count <= 5_000 else { throw PreferenceError.invalid("A pasta excede 5.000 itens. Use uma pasta de entrada menor.") }
        var result:[String:AutomationFileStamp] = [:]
        for entry in files {
            try Task.checkCancellation()
            guard entry.pathExtension.lowercased() == "pdf" else { continue }
            // Foundation may return a different spelling for /var and
            // /private/var. Keys always use the canonical parent, not that URL.
            let file = root.appendingPathComponent(entry.lastPathComponent)
            if let stamp = try stamp(file) { result[file.path] = stamp }
        }
        var finalIdentity = stat()
        guard lstat(root.path,&finalIdentity) == 0,finalIdentity.st_mode & S_IFMT == S_IFDIR,
              rootIdentity.st_dev == finalIdentity.st_dev,rootIdentity.st_ino == finalIdentity.st_ino else {
            throw PreferenceError.invalid("A pasta mudou durante a leitura. Ative a regra novamente.")
        }
        try Task.checkCancellation()
        return result
    }
    static func stamp(_ file:URL) throws -> AutomationFileStamp? {
        try Task.checkCancellation()
        guard file.isFileURL else { return nil }
        var info = stat()
        if lstat(file.path,&info) != 0 {
            if errno == ENOENT || errno == ENOTDIR { return nil }
            throw POSIXError(POSIXErrorCode(rawValue:errno) ?? .EIO)
        }
        guard info.st_mode & S_IFMT == S_IFREG,info.st_size >= 0,let size = Int(exactly:info.st_size) else { return nil }
        return .init(size:size,modified:Double(info.st_mtimespec.tv_sec)+Double(info.st_mtimespec.tv_nsec)/1_000_000_000,
                     inode:UInt64(info.st_ino),device:UInt64(bitPattern:Int64(info.st_dev)),modifiedNanoseconds:Int64(info.st_mtimespec.tv_nsec))
    }
}

/// Tracks only newly observed files; existing files are an explicit activation baseline.
struct AutomationArrivalTracker {
    private(set) var known:Set<String>
    private var candidates:[String:(stamp:AutomationFileStamp,stable:Int)] = [:]
    init(baseline:[String:AutomationFileStamp]) { known = Set(baseline.keys) }
    mutating func observe(_ files:[String:AutomationFileStamp]) -> [(String,AutomationFileStamp)] {
        candidates = candidates.filter { files[$0.key] != nil }
        var ready:[(String,AutomationFileStamp)] = []
        for path in files.keys.sorted() where !known.contains(path) {
            guard let stamp = files[path],stamp.size > 0 else { continue }
            let previous = candidates[path]
            let stable = previous?.stamp == stamp ? (previous?.stable ?? 0)+1 : 0
            candidates[path] = (stamp,stable)
            if stable >= 2 { ready.append((path,stamp)); known.insert(path); candidates.removeValue(forKey:path) }
        }
        return ready
    }
}

struct AutomationRunRecord:Identifiable {
    var id = UUID()
    var date = Date()
    var rule:String
    var input:String
    var result:String
    var output:URL?
}

@MainActor final class AutomationCoordinator:ObservableObject {
    static let shared = AutomationCoordinator()
    static let storageKey = "PDF.WatchedFolders.v1"
    @Published private(set) var rules:[WatchedFolderRule] = []
    @Published private(set) var history:[AutomationRunRecord] = []
    @Published private(set) var status = "Nenhuma pasta está ativa."
    @Published private(set) var activeRuleID:UUID?
    @Published private(set) var pendingCount = 0
    @Published private(set) var starting:Set<UUID> = []
    @Published private(set) var progress:Double = 0
    private let defaults:UserDefaults
    private weak var model:Workspace?
    private var timer:Timer?
    private var trackers:[UUID:AutomationArrivalTracker] = [:]
    private var generations:[UUID:UUID] = [:]
    private var queue:[(ruleID:UUID,path:String,stamp:AutomationFileStamp)] = []
    private var polling = false
    private var suspendedForTermination = false
    private var lifetimeObservers: [NSObjectProtocol] = []
    init(defaults:UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey:Self.storageKey),data.count <= 16_777_216 {
            do {
                let loaded = try JSONDecoder().decode([WatchedFolderRule].self,from:data)
                guard loaded.count <= 20,Set(loaded.map(\.id)).count == loaded.count else { throw PreferenceError.invalid("Configuração de automação inválida.") }
                for rule in loaded { guard !rule.name.isEmpty,rule.name.count <= 80,rule.input.isFileURL,rule.output.isFileURL else { throw PreferenceError.invalid("Regra de automação inválida.") }; _ = try AutomationWorkflowBridge.options(rule.workflow) }
                rules = loaded
            } catch { status = "Não foi possível carregar as regras: "+error.localizedDescription }
        }
        lifetimeObservers = [
            NotificationCenter.default.addObserver(forName: .applicationWorkStopping, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.suspendForTermination() }
            },
            NotificationCenter.default.addObserver(forName: .applicationWorkResumed, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.resumeAfterRefusedTermination() }
            }
        ]
    }
    deinit { for observer in lifetimeObservers { NotificationCenter.default.removeObserver(observer) }; timer?.invalidate() }
    func attach(model:Workspace) {
        guard self.model == nil else { return }; self.model = model
        startTimer()
        for rule in rules where rule.enabled { ApplicationTask.start { await setEnabled(true,id:rule.id) } }
    }
    private func startTimer() {
        guard timer == nil, model != nil, ApplicationWork.isAcceptingWork else { return }
        timer = Timer.scheduledTimer(withTimeInterval:3,repeats:true) { [weak self] _ in
            Task { @MainActor [weak self] in await self?.poll() }
        }
    }
    private func suspendForTermination() {
        suspendedForTermination = true
        timer?.invalidate(); timer = nil
        for id in starting { generations[id] = UUID() }
        starting.removeAll()
        // Keep enabled preferences, stable arrivals and the pending queue. A
        // refused quit must not silently disable rules or replay old files.
    }
    private func resumeAfterRefusedTermination() {
        guard ApplicationWork.isAcceptingWork else { return }
        suspendedForTermination = false
        startTimer()
        for rule in rules where rule.enabled && trackers[rule.id] == nil {
            ApplicationTask.start { await setEnabled(true, id: rule.id) }
        }
    }
    private func scan(_ folder: URL) async throws -> [String: AutomationFileStamp] {
        try await ApplicationTask.run {
            let worker = Task.detached(priority: .utility) { try AutomationFolderInspector.scan(folder) }
            return try await withTaskCancellationHandler(operation: { try await worker.value }, onCancel: { worker.cancel() })
        }
    }
    func add(name:String,input:URL,output:URL,workflow:AutomationWorkflow) throws {
        let name = name.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !name.isEmpty,name.count <= 80,rules.count < 20 else { throw PreferenceError.invalid("Use um nome de até 80 caracteres e no máximo 20 regras.") }
        try AutomationFolderInspector.validate(input:input,output:output); _ = try AutomationWorkflowBridge.options(workflow)
        let source = try AutomationFolderInspector.canonicalDirectory(input)
        guard !rules.contains(where:{$0.input.path == source.path || (try? AutomationFolderInspector.canonicalDirectory($0.input)) == source}) else { throw PreferenceError.invalid("Essa pasta já possui uma regra. Remova a anterior para substituí-la.") }
        let candidate = rules + [WatchedFolderRule(name:name,input:source,output:try AutomationFolderInspector.canonicalDirectory(output),workflow:workflow)]
        guard try JSONEncoder().encode(candidate).count < 16_000_000 else { throw PreferenceError.invalid("As regras excedem o limite de 16 MB. Remova uma regra antes de continuar.") }
        rules = candidate
        persist(); status = "Regra criada desativada. Ative quando estiver pronta para processar novos PDFs."
    }
    func setEnabled(_ enabled:Bool,id:UUID) async {
        guard ApplicationWork.isAcceptingWork, !Task.isCancelled else { return }
        guard let index = rules.firstIndex(where:{$0.id == id}) else { return }
        let generation = UUID(); generations[id] = generation
        if !enabled {
            rules[index].enabled = false; trackers.removeValue(forKey:id); starting.remove(id)
            queue.removeAll { $0.ruleID == id }; pendingCount = queue.count; persist()
            status = "Regra pausada. A execução já iniciada pode terminar; use Cancelar para interrompê-la."; return
        }
        let rule = rules[index]; starting.insert(id)
        do {
            try AutomationFolderInspector.validate(input:rule.input,output:rule.output); _ = try AutomationWorkflowBridge.options(rule.workflow)
            let baseline = try await scan(rule.input)
            guard ApplicationWork.isAcceptingWork, !Task.isCancelled, generations[id] == generation,let current = rules.firstIndex(where:{$0.id == id}) else { return }
            trackers[id] = AutomationArrivalTracker(baseline:baseline); rules[current].enabled = true; starting.remove(id)
            persist(); status = "\(rule.name) ativa. \(baseline.count) PDFs existentes foram ignorados; apenas novas chegadas serão processadas."
        } catch is CancellationError { if generations[id] == generation { starting.remove(id) } }
        catch { guard generations[id] == generation, ApplicationWork.isAcceptingWork else { return }; disable(id,error:error.localizedDescription) }
    }
    func remove(_ id:UUID) {
        guard activeRuleID != id else { status = "Cancele ou aguarde a execução antes de excluir a regra."; return }
        generations[id] = UUID(); trackers.removeValue(forKey:id); starting.remove(id)
        queue.removeAll { $0.ruleID == id }; rules.removeAll { $0.id == id }; pendingCount = queue.count; persist()
    }
    func cancelCurrent() { guard activeRuleID != nil else { return }; model?.cancel() }
    func scanNow() async { await poll() }
    private func persist() { if let data = try? JSONEncoder().encode(rules),data.count <= 16_777_216 { defaults.set(data,forKey:Self.storageKey) } }
    private func disable(_ id:UUID,error:String) {
        if let index = rules.firstIndex(where:{$0.id == id}) { rules[index].enabled = false }
        trackers.removeValue(forKey:id); starting.remove(id); queue.removeAll { $0.ruleID == id }; pendingCount = queue.count
        status = "Automação pausada: "+error; persist()
    }
    private func poll() async {
        guard !polling, !suspendedForTermination, ApplicationWork.isAcceptingWork, !Task.isCancelled else { return }; polling = true; defer { polling = false }
        for rule in rules where rule.enabled && trackers[rule.id] != nil {
            let generation = generations[rule.id]
            do {
                let files = try await scan(rule.input)
                guard ApplicationWork.isAcceptingWork, !suspendedForTermination, !Task.isCancelled else { return }
                guard generation == generations[rule.id],var tracker = trackers[rule.id] else { continue }
                let arrived = tracker.observe(files); trackers[rule.id] = tracker
                guard queue.count+arrived.count <= 200 else { disable(rule.id,error:"Fila acima de 200 PDFs; revise a pasta e reative a regra."); continue }
                for (path,stamp) in arrived { queue.append((rule.id,path,stamp)) }
            } catch is CancellationError { return }
            catch { if ApplicationWork.isAcceptingWork, generation == generations[rule.id] { disable(rule.id,error:error.localizedDescription) } }
        }
        pendingCount = queue.count; runNext()
    }
    private func runNext() {
        guard ApplicationWork.isAcceptingWork, !suspendedForTermination, let model,!model.busy,activeRuleID == nil,!queue.isEmpty else { return }
        let job = queue.removeFirst(); pendingCount = queue.count
        guard let rule = rules.first(where:{$0.id == job.ruleID && $0.enabled}) else { return }
        let input = URL(fileURLWithPath:job.path)
        do {
            try AutomationFolderInspector.validate(input:rule.input,output:rule.output)
            guard try AutomationFolderInspector.stamp(input) == job.stamp else { throw PreferenceError.invalid("O arquivo mudou depois da estabilização. Execute-o manualmente ou mova uma nova cópia para a entrada.") }
            let options = try AutomationWorkflowBridge.options(rule.workflow)
            let stem = OutputFilename.make(template:defaults.string(forKey:"outputFilenameTemplate"),
                prefix:defaults.string(forKey:"outputPrefix") ?? "PDF-resultado",original:input.lastPathComponent,
                tool:rule.name,suffix:"",directory:true)
            let output = rule.output.appendingPathComponent(stem+" · "+UUID().uuidString,isDirectory:true)
            activeRuleID = rule.id; progress = 0; status = "Executando \(rule.name): \(input.lastPathComponent)"
            model.execute(operation:"workflow",inputs:[input],output:output,options:options,title:"Automação · "+rule.name,progress:{ [weak self] completed,total in self?.progress = Double(completed)/Double(total) },completion:{ [weak self] result in
                guard let self else { return }; self.activeRuleID = nil
                switch result {
                case .success(let url): self.progress = 1; self.status = "Concluído: "+input.lastPathComponent; self.record(rule:rule,input:input,result:"Concluído",output:url)
                case .failure(let error):
                    self.record(rule:rule,input:input,result:error.localizedDescription,output:nil)
                    if self.suspendedForTermination || !ApplicationWork.isAcceptingWork {
                        self.status = "Automação interrompida para encerrar o aplicativo. A preferência da regra foi preservada."
                    } else { self.disable(rule.id,error:error.localizedDescription) }
                }
            })
        } catch { record(rule:rule,input:input,result:error.localizedDescription,output:nil); disable(rule.id,error:error.localizedDescription) }
    }
    private func record(rule:WatchedFolderRule,input:URL,result:String,output:URL?) {
        history.insert(.init(rule:rule.name,input:input.lastPathComponent,result:result,output:output),at:0)
        history = Array(history.prefix(100))
    }
}

struct AutomationView:View {
    @EnvironmentObject private var model:Workspace
    @ObservedObject var coordinator:AutomationCoordinator
    @State private var workflows:[AutomationWorkflow] = []
    @State private var workflowID:UUID?
    @State private var name = ""
    @State private var input:URL?
    @State private var output:URL?
    @State private var message = ""
    @MainActor init(coordinator: AutomationCoordinator? = nil) { self.coordinator = coordinator ?? .shared }
    var body:some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                Label("Automação no seu Mac",systemImage:"gearshape.2").font(.largeTitle.bold())
                Text("A automação só funciona enquanto o PDF está aberto. Cada ativação ignora os arquivos já presentes; novas cópias PDF são processadas após três leituras estáveis. Subpastas e links simbólicos são ignorados. Arquivos que exigem senha pausam a regra para tratamento manual.").foregroundStyle(.secondary)
                GroupBox("Nova pasta monitorada") {
                    VStack(alignment:.leading,spacing:12) {
                        TextField("Nome da regra",text:$name).textFieldStyle(.roundedBorder)
                        Picker("Fluxo salvo",selection:$workflowID) { Text("Escolha um fluxo").tag(UUID?.none); ForEach(workflows) { Text($0.name).tag(Optional($0.id)) } }
                        HStack { Button("Atualizar fluxos") { loadWorkflows() }; Text("O fluxo é copiado para a regra. Edições futuras no original não alteram uma automação já configurada.").font(.caption).foregroundStyle(.secondary) }
                        folderRow("Entrada",url:input) { input = chooseFolder() }
                        folderRow("Saída",url:output) { output = chooseFolder() }
                        Button("Criar regra desativada") { createRule() }.disabled(name.isEmpty || input == nil || output == nil || workflowID == nil)
                    }.padding(8)
                }
                if !message.isEmpty { Text(message).foregroundStyle(.secondary) }
                ForEach(coordinator.rules) { rule in
                    GroupBox {
                        VStack(alignment:.leading,spacing:10) {
                            HStack {
                                Text(rule.name).font(.headline); Spacer()
                                Toggle("Ativa",isOn:Binding(get:{rule.enabled},set:{ enabled in Task { await coordinator.setEnabled(enabled,id:rule.id) } })).disabled(coordinator.starting.contains(rule.id))
                                Button(role:.destructive) { coordinator.remove(rule.id) } label:{ Image(systemName:"trash") }.disabled(coordinator.activeRuleID == rule.id).accessibilityLabel("Excluir regra "+rule.name)
                            }
                            Text("Fluxo: "+rule.workflow.name).font(.callout)
                            Text("Entrada: "+rule.input.path+"\nSaída: "+rule.output.path).font(.caption).textSelection(.enabled)
                            if coordinator.starting.contains(rule.id) { ProgressView("Registrando arquivos existentes…") }
                        }.padding(8)
                    }
                }
                HStack { Text(coordinator.status).font(.callout); Spacer(); if coordinator.activeRuleID != nil { Button("Cancelar execução") { coordinator.cancelCurrent() } } }
                if coordinator.activeRuleID != nil { ProgressView(value:coordinator.progress) }
                Text("\(coordinator.pendingCount) arquivos na fila. Falhas pausam a regra; nada é tentado novamente sem reativação. Os resultados recebem uma pasta nova e os originais permanecem intactos.").font(.caption).foregroundStyle(.secondary)
                if !coordinator.history.isEmpty {
                    Text("Execuções desta sessão").font(.headline)
                    ForEach(coordinator.history) { item in
                        HStack {
                            VStack(alignment:.leading,spacing:4) { Text(item.rule+" · "+item.input).fontWeight(.medium); Text(item.result).font(.caption).foregroundStyle(.secondary) }
                            Spacer(); if let url = item.output { Button("Mostrar resultado") { NSWorkspace.shared.activateFileViewerSelecting([url]) } }
                        }.padding(10)
                    }
                }
                GroupBox("Serviços do Finder") {
                    Text("Selecione arquivos PDF no Finder e use Serviços → Abrir no PDF. Se o serviço não aparecer, ative-o em Ajustes do Sistema → Teclado → Atalhos de Teclado → Serviços. O serviço abre os arquivos para revisão; não executa fluxos automaticamente.").frame(maxWidth:.infinity,alignment:.leading).padding(8)
                }
            }.padding(28)
        }.onAppear { coordinator.attach(model:model); loadWorkflows() }
    }
    private func folderRow(_ title:String,url:URL?,choose:@escaping()->Void)->some View { HStack { Text(title).frame(width:60,alignment:.leading); Text(url?.path ?? "Nenhuma pasta escolhida").font(.caption).lineLimit(2); Spacer(); Button("Escolher…",action:choose).accessibilityLabel("Escolher pasta de "+title.lowercased()) } }
    private func chooseFolder()->URL? { let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; return panel.runModal() == .OK ? panel.url : nil }
    private func loadWorkflows() { do { workflows = try AutomationWorkflowBridge.saved(); if !workflows.contains(where:{$0.id == workflowID}) { workflowID = nil }; message = workflows.isEmpty ? "Crie e salve um fluxo em Fluxos antes de configurar a regra." : "" } catch { message = error.localizedDescription } }
    private func createRule() { guard let input,let output,let workflow = workflows.first(where:{$0.id == workflowID}) else { return }; do { try coordinator.add(name:name,input:input,output:output,workflow:workflow); name = ""; message = "Regra criada. A ativação é opcional e explícita." } catch { message = error.localizedDescription } }
}

@MainActor final class PDFServiceProvider:NSObject {
    static let shared = PDFServiceProvider()
    weak var model:Workspace?
    static func install(model:Workspace) { shared.model = model; NSApp.servicesProvider = shared; NSUpdateDynamicServices() }
    @objc func openPDF(_ pasteboard:NSPasteboard,userData:String?,error:AutoreleasingUnsafeMutablePointer<NSString?>) {
        guard ApplicationWork.isAcceptingWork else { error.pointee = "O PDF está encerrando as operações em andamento."; return }
        guard let model else { error.pointee = "O PDF ainda não está pronto para abrir documentos."; return }
        var urls = (pasteboard.readObjects(forClasses:[NSURL.self],options:[.urlReadingFileURLsOnly:true]) as? [NSURL] ?? []).map { $0 as URL }
        if urls.isEmpty,let paths = pasteboard.propertyList(forType:NSPasteboard.PasteboardType("NSFilenamesPboardType")) as? [String] { urls = paths.map { URL(fileURLWithPath:$0) } }
        urls = urls.filter { $0.isFileURL && $0.pathExtension.lowercased() == "pdf" }
        guard !urls.isEmpty,urls.count <= 50 else { error.pointee = "Selecione entre 1 e 50 arquivos PDF no Finder."; return }
        NSApp.activate(ignoringOtherApps:true)
        ApplicationTask.start {
            for url in urls {
                guard !Task.isCancelled, ApplicationWork.isAcceptingWork else { break }
                model.open(url:url); await model.waitForPendingOpen()
                if model.needsPassword { model.message = "Informe a senha deste documento. Os arquivos restantes podem ser abertos depois."; break }
            }
        }
    }
}
