import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers

@MainActor final class Workspace: ObservableObject {
    @Published var document: PDFDocument?
    @Published var url: URL?
    @Published var message = ""
    @Published var busy = false
    @Published var section = "Início"
    @Published var recentURLs: [URL] = []
    @Published var lastOutput: URL?
    @Published var currentPage = 1
    @Published var bookmarks: Set<Int> = []
    @Published var needsPassword = false
    @Published var documentPassword = ""
    @Published var annotationRevision = 0
    @Published var inkMode = false
    @Published var hasEdits = false
    weak var pdfView: PDFView?
    private var pendingURL: URL?
    private var process: Process?
    private var cancelled = false
    private var activeJob: UUID?
    private var originalWidgetState = ""
    private let thumbnails = NSCache<NSNumber, NSImage>()

    init() {
        recentURLs = (UserDefaults.standard.stringArray(forKey:"recentDocuments") ?? []).map { URL(fileURLWithPath:$0) }
        thumbnails.countLimit = 150
    }
    func open() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        open(url:url)
    }
    func open(url:URL) {
        guard confirmDiscardEdits() else { return }
        guard let doc = PDFDocument(url:url) else { message = "Não foi possível ler este PDF. Verifique o arquivo e o acesso à pasta."; return }
        if doc.isLocked {
            pendingURL = url; documentPassword = ""; needsPassword = true; return
        }
        installDocument(doc, url:url)
    }
    func unlockPendingDocument() {
        defer { documentPassword = "" }
        guard let url = pendingURL, let doc = PDFDocument(url:url), doc.unlock(withPassword:documentPassword) else {
            message = "Senha incorreta ou documento indisponível. Abra o arquivo novamente para tentar outra senha."; return
        }
        pendingURL = nil; installDocument(doc, url:url)
    }
    private func installDocument(_ doc:PDFDocument, url:URL) {
        document = doc; self.url = url; section = "Leitor"; currentPage = 1; hasEdits = false
        originalWidgetState = widgetState()
        thumbnails.removeAllObjects()
        recentURLs.removeAll { $0.standardizedFileURL == url.standardizedFileURL }; recentURLs.insert(url, at:0)
        recentURLs = Array(recentURLs.prefix(20))
        UserDefaults.standard.set(recentURLs.map(\.path), forKey:"recentDocuments")
        bookmarks = Set(UserDefaults.standard.array(forKey:bookmarkKey) as? [Int] ?? [])
        message = "\(doc.pageCount) páginas · \(url.lastPathComponent)"
    }
    private var bookmarkKey:String { "bookmarks:" + (url?.standardizedFileURL.path ?? "") }
    func clearRecent() { recentURLs = []; UserDefaults.standard.removeObject(forKey:"recentDocuments") }
    var hasUnsavedChanges:Bool { hasEdits || widgetState() != originalWidgetState }
    private func widgetState() -> String {
        guard let document else { return "" }
        var state:[String] = []
        for index in 0..<document.pageCount {
            for annotation in document.page(at:index)?.annotations ?? [] {
                if let name = annotation.fieldName {
                    state.append("\(index):\(name):\(annotation.widgetStringValue ?? ""): \(annotation.buttonWidgetState.rawValue)")
                }
            }
        }
        return state.joined(separator:"\n")
    }
    func confirmDiscardEdits() -> Bool {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard hasUnsavedChanges else { return true }
        let alert = NSAlert(); alert.messageText = "Há alterações no documento aberto"
        alert.informativeText = "Salve uma cópia para conservar suas anotações antes de abrir outro arquivo."
        alert.addButton(withTitle:"Voltar"); alert.addButton(withTitle:"Descartar alterações")
        return alert.runModal() == .alertSecondButtonReturn
    }
    func selectOutput(extension suffix:String = "pdf", directory:Bool = false) -> URL? {
        let panel = NSSavePanel()
        let prefix = UserDefaults.standard.string(forKey:"outputPrefix") ?? "PDF-resultado"
        panel.nameFieldStringValue = directory ? prefix + "-paginas" : prefix + "." + suffix
        if !directory, let type = UTType(filenameExtension:suffix) { panel.allowedContentTypes = [type] }
        if let path = UserDefaults.standard.string(forKey:"outputDirectory"), !path.isEmpty { panel.directoryURL = URL(fileURLWithPath:path) }
        guard panel.runModal() == .OK, let target = panel.url else { return nil }
        guard !FileManager.default.fileExists(atPath:target.path) else {
            message = "O destino já existe. Escolha um novo nome para preservar os arquivos."; return nil
        }
        return target
    }
    func save() {
        NSApp.keyWindow?.makeFirstResponder(nil)
        guard let document else { return }
        let bytes:Data?
        if document.isEncrypted {
            let alert = NSAlert(); alert.messageText = "Salvar cópia protegida"
            alert.informativeText = "Defina a senha da nova cópia para manter o conteúdo protegido. Use pelo menos 8 caracteres."
            let first = NSSecureTextField(frame:NSRect(x:0,y:0,width:320,height:24)); first.placeholderString = "Nova senha"
            let second = NSSecureTextField(frame:NSRect(x:0,y:0,width:320,height:24)); second.placeholderString = "Confirmar nova senha"
            let stack = NSStackView(views:[first,second]); stack.orientation = .vertical; stack.spacing = 8; stack.frame = NSRect(x:0,y:0,width:320,height:56)
            alert.accessoryView = stack; alert.addButton(withTitle:"Salvar protegida"); alert.addButton(withTitle:"Cancelar")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            let secret = first.stringValue
            guard secret.count >= 8,secret == second.stringValue else { message = "Use senhas iguais, com pelo menos 8 caracteres."; return }
            first.stringValue = ""; second.stringValue = ""
            let options:[AnyHashable:Any] = [AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue):secret,AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue):secret]
            bytes = document.dataRepresentation(options:options)
            guard let data = bytes,let verification = PDFDocument(data:data),verification.isEncrypted,verification.isLocked,!verification.unlock(withPassword:""),verification.unlock(withPassword:secret) else {
                message = "Não foi possível confirmar a proteção da cópia. Nenhum arquivo foi salvo."; return
            }
        } else { bytes = document.dataRepresentation() }
        guard let target = selectOutput(),let bytes else { return }
        do {
            try bytes.write(to:target, options:.withoutOverwriting)
            lastOutput = target; hasEdits = false; originalWidgetState = widgetState(); message = "Cópia salva: \(target.lastPathComponent)"
        } catch { message = "Não foi possível salvar: \(error.localizedDescription)" }
    }
    func printDocument() {
        guard let document else { return }
        document.printOperation(for:NSPrintInfo.shared, scalingMode:.pageScaleDownToFit, autoRotate:true)?.run()
    }
    func highlight() {
        guard let selection = pdfView?.currentSelection else { message = "Selecione texto no documento para realçar."; return }
        for line in selection.selectionsByLine() {
            for page in line.pages {
                let annotation = PDFAnnotation(bounds:line.bounds(for:page), forType:.highlight, withProperties:nil)
                annotation.color = .systemYellow.withAlphaComponent(0.45); page.addAnnotation(annotation)
            }
        }
        didEdit(); message = "Realce adicionado. Salve uma cópia para conservar a alteração."
    }
    func addNote(_ text:String) {
        guard let page = pdfView?.currentPage, !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { return }
        let bounds = page.bounds(for:.cropBox)
        let annotation = PDFAnnotation(bounds:CGRect(x:bounds.minX + 30,y:bounds.maxY - 70,width:28,height:28),forType:.text,withProperties:nil)
        annotation.contents = text; annotation.color = .systemYellow; page.addAnnotation(annotation); didEdit()
    }
    func rotatePage() {
        guard let page = pdfView?.currentPage else { return }
        page.rotation = (page.rotation + 90) % 360; didEdit()
    }
    func didEdit() { hasEdits = true; annotationRevision += 1; thumbnails.removeAllObjects() }
    func goToPage(_ number:Int) {
        guard let document, let page = document.page(at:number - 1) else { return }
        pdfView?.go(to:page); currentPage = number
    }
    func nextPage() { pdfView?.goToNextPage(nil) }
    func previousPage() { pdfView?.goToPreviousPage(nil) }
    func toggleBookmark() {
        if bookmarks.contains(currentPage) { bookmarks.remove(currentPage) } else { bookmarks.insert(currentPage) }
        UserDefaults.standard.set(Array(bookmarks).sorted(), forKey:bookmarkKey)
    }
    func thumbnail(_ index:Int) -> NSImage? {
        let key = NSNumber(value:index)
        if let image = thumbnails.object(forKey:key) { return image }
        guard let page = document?.page(at:index) else { return nil }
        let image = page.thumbnail(of:CGSize(width:120,height:160), for:.cropBox)
        thumbnails.setObject(image, forKey:key); return image
    }
    func openResult(_ url:URL) {
        if url.pathExtension.lowercased() == "pdf" { open(url:url) } else { NSWorkspace.shared.open(url) }
    }
    func cancel() {
        guard let process, process.isRunning else { return }
        cancelled = true; message = "Cancelando…"; process.interrupt()
    }
    func executeBatch(operation:String, inputs:[URL], directory:URL, options:[String:Any], title:String) {
        guard !busy, !inputs.isEmpty else { return }
        do { try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:false) }
        catch { message = "Não foi possível criar a pasta de resultados: \(error.localizedDescription)"; return }
        func next(_ index:Int) {
            guard index < inputs.count else { lastOutput = directory; message = "Concluído: \(inputs.count) documentos em \(directory.lastPathComponent)"; return }
            let name = String(format:"%03d-",index+1) + inputs[index].deletingPathExtension().lastPathComponent + ".pdf"
            let target = directory.appendingPathComponent(name)
            execute(operation:operation,inputs:[inputs[index]],output:target,options:options,title:"\(title) · \(index+1)/\(inputs.count)") { result in
                switch result {
                case .success: next(index+1)
                case .failure(let error): self.lastOutput = directory; self.message = "Lote interrompido após \(index) documentos concluídos. \(error.localizedDescription)"
                }
            }
        }
        next(0)
    }
    func execute(operation:String, inputs:[URL], output:URL, options:[String:Any], title:String, completion:((Result<URL,Error>)->Void)? = nil) {
        func fail(_ detail:String) { message = detail; completion?(.failure(NSError(domain:"PDF.Engine",code:1,userInfo:[NSLocalizedDescriptionKey:detail]))) }
        guard !busy else { fail("Aguarde a operação atual terminar ou cancele-a."); return }
        guard !inputs.isEmpty else { fail("Selecione ao menos um arquivo de entrada."); return }
        guard !FileManager.default.fileExists(atPath:output.path) else { fail("O destino já existe. Escolha um novo nome."); return }
        guard let data = try? JSONSerialization.data(withJSONObject:options) else { fail("As opções da operação são inválidas."); return }
        let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath:FileManager.default.currentDirectoryPath)
        let bundledPython = resources.appendingPathComponent("runtime/bin/python3")
        let project = URL(fileURLWithPath:FileManager.default.currentDirectoryPath)
        let python = FileManager.default.isExecutableFile(atPath:bundledPython.path) ? bundledPython : project.appendingPathComponent(".venv/bin/python3")
        let bundledEngine = resources.appendingPathComponent("engine/pdf_engine.py")
        let engine = FileManager.default.fileExists(atPath:bundledEngine.path) ? bundledEngine : project.appendingPathComponent("engine/pdf_engine.py")
        guard FileManager.default.isExecutableFile(atPath:python.path), FileManager.default.fileExists(atPath:engine.path) else {
            fail("O motor local não foi instalado. Execute o instalador completo do PDF."); return
        }
        let job = UUID(); activeJob = job; busy = true; cancelled = false; lastOutput = nil; message = "\(title)…"
        let task = Process(); task.executableURL = python
        task.arguments = [engine.path,operation] + inputs.map { $0.isFileURL ? $0.path : $0.absoluteString } + ["--output",output.path]
        var environment = ProcessInfo.processInfo.environment
        environment["PDF_OPTIONS_STDIN"] = "1"
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin")
        task.environment = environment
        let input = Pipe(); let log = Pipe(); task.standardInput = input; task.standardError = log; task.standardOutput = log
        process = task
        do { try task.run() }
        catch { busy = false; process = nil; fail("Não foi possível iniciar o motor: \(error.localizedDescription)"); return }
        // Drain the pipe before waiting; external converters can emit enough logs to fill it.
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in
            input.fileHandleForWriting.write(data); try? input.fileHandleForWriting.close()
            let bytes = log.fileHandleForReading.readDataToEndOfFile(); task.waitUntilExit()
            let raw = String(data:bytes,encoding:.utf8) ?? "Falha sem detalhes."
            DispatchQueue.main.async {
                guard let self, self.activeJob == job else { return }
                self.busy = false; self.process = nil
                if self.cancelled {
                    self.message = "Operação cancelada. Os arquivos de origem foram preservados."
                    completion?(.failure(NSError(domain:NSCocoaErrorDomain,code:NSUserCancelledError)))
                    return
                }
                if task.terminationStatus == 0 && FileManager.default.fileExists(atPath:output.path) {
                    self.lastOutput = output; self.message = "Concluído: \(output.lastPathComponent)"
                    completion?(.success(output))
                } else {
                    let lastJSON = raw.split(separator:"\n").reversed().compactMap { line -> [String:Any]? in
                        guard let data = String(line).data(using:.utf8) else { return nil }
                        return (try? JSONSerialization.jsonObject(with:data)) as? [String:Any]
                    }.first
                    self.message = lastJSON?["error"] as? String ?? String(raw.suffix(2000))
                    completion?(.failure(NSError(domain:"PDF.Engine",code:Int(task.terminationStatus),userInfo:[NSLocalizedDescriptionKey:self.message])))
                }
            }
        }
    }
}

struct Reader: NSViewRepresentable {
    @EnvironmentObject var model: Workspace
    var mode: Int
    func makeCoordinator() -> Coordinator { Coordinator(model:model) }
    func makeNSView(context:Context) -> PDFView {
        let view = DrawingPDFView(); view.onEdit = { [weak model] in model?.didEdit() }; view.autoScales = true; view.displayMode = .singlePageContinuous
        view.backgroundColor = .clear; model.pdfView = view
        context.coordinator.observer = NotificationCenter.default.addObserver(forName:.PDFViewPageChanged,object:view,queue:.main) { [weak view, weak model] _ in
            guard let view, let page = view.currentPage, let document = view.document else { return }
            Task { @MainActor in model?.currentPage = document.index(for:page) + 1 }
        }
        return view
    }
    func updateNSView(_ view:PDFView, context:Context) {
        if view.document !== model.document { view.document = model.document }
        (view as? DrawingPDFView)?.inkEnabled = model.inkMode
        let display: PDFDisplayMode = mode == 1 ? .singlePage : mode == 2 ? .twoUpContinuous : .singlePageContinuous
        if view.displayMode != display { view.displayMode = display; view.autoScales = true }
    }
    final class Coordinator {
        weak var model:Workspace?
        var observer:NSObjectProtocol?
        init(model:Workspace) { self.model = model }
        deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }
    }
}


/// Ink is drawn in PDF page coordinates so it remains aligned at any zoom level.
final class DrawingPDFView:PDFView {
    var inkEnabled = false
    var onEdit:(()->Void)?
    private var drawingPage:PDFPage?
    private var path:NSBezierPath?
    private var preview:PDFAnnotation?
    override func mouseDown(with event:NSEvent) {
        guard inkEnabled else { super.mouseDown(with:event); return }
        let point = convert(event.locationInWindow,from:nil)
        guard let page = page(for:point,nearest:false) else { return }
        drawingPage = page
        let bounds = page.bounds(for:.cropBox)
        let pointOnPage = convert(point,to:page)
        let stroke = NSBezierPath(); stroke.move(to:NSPoint(x:pointOnPage.x-bounds.minX,y:pointOnPage.y-bounds.minY)); path = stroke
        let annotation = PDFAnnotation(bounds:bounds,forType:.ink,withProperties:nil)
        annotation.color = .systemBlue
        let border = PDFBorder(); border.lineWidth = 2; annotation.border = border
        preview = annotation; page.addAnnotation(annotation)
    }
    override func mouseDragged(with event:NSEvent) {
        guard inkEnabled else { super.mouseDragged(with:event); return }
        guard let page = drawingPage,let path,let preview else { return }
        let location = convert(convert(event.locationInWindow,from:nil),to:page)
        let bounds = page.bounds(for:.cropBox)
        path.line(to:NSPoint(x:location.x-bounds.minX,y:location.y-bounds.minY))
        // A single path avoids adding a new segment to the document on every event.
        for existing in preview.paths ?? [] { preview.remove(existing) }
        preview.add(path)
        needsDisplay = true
    }
    override func mouseUp(with event:NSEvent) {
        guard inkEnabled else { super.mouseUp(with:event); return }
        if let page = drawingPage,let preview {
            if (path?.elementCount ?? 0) < 2 { page.removeAnnotation(preview) } else { onEdit?() }
        }
        drawingPage = nil; path = nil; preview = nil
    }
}
