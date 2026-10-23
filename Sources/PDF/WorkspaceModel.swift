import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers

/// Literal token substitution only: user templates never become code or paths.
enum OutputFilename {
    static func make(template: String?, prefix: String, original: String, tool: String,
                     suffix: String, directory: Bool = false, date: Date = Date()) -> String {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"; let day = formatter.string(from: date)
        formatter.dateFormat = "HH-mm-ss"; let time = formatter.string(from: date)
        let originalName = URL(fileURLWithPath: original).deletingPathExtension().lastPathComponent
        let tokens = ["original": originalName.isEmpty ? "Documento" : originalName,
                      "ferramenta": tool, "data": day, "hora": time]
        let pattern = template?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        var name = pattern.isEmpty ? prefix + (directory ? "-paginas" : "") : pattern
        // One pass prevents token-shaped text in a filename being expanded again.
        if !pattern.isEmpty {
            let expression = try! NSRegularExpression(pattern: "\\{(original|ferramenta|data|hora)\\}")
            let source = pattern as NSString
            for match in expression.matches(in: pattern, range: NSRange(location: 0, length: source.length)).reversed() {
                let key = source.substring(with: match.range(at: 1))
                if let range = Range(match.range, in: name) { name.replaceSubrange(range, with: tokens[key] ?? "") }
            }
        }
        let forbidden = CharacterSet.controlCharacters.union(CharacterSet(charactersIn: "/\\:"))
        name = name.components(separatedBy: forbidden).joined(separator: "-")
            .trimmingCharacters(in: CharacterSet.whitespacesAndNewlines.union(CharacterSet(charactersIn: ".")))
        let cleanSuffix = suffix.lowercased().filter { $0.isASCII && ($0.isLetter || $0.isNumber) }
        if !directory, !cleanSuffix.isEmpty {
            while name.lowercased().hasSuffix("." + cleanSuffix) { name = String(name.dropLast(cleanSuffix.count + 1)) }
        }
        if name.isEmpty { name = "PDF-resultado" }
        // Leave space for the extension and common filesystem component limits.
        while name.utf8.count > 180 { name.removeLast() }
        return !directory && !cleanSuffix.isEmpty ? name + "." + cleanSuffix : name
    }
}

enum ReaderAnnotationStyle {
    static func color(_ hex: String, fallback: String) -> NSColor {
        let valid = hex.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil
        let value = UInt32((valid ? hex : fallback).dropFirst(), radix: 16) ?? 0x007AFF
        return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255,
                       green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
    }
    static func width(_ value: Double) -> CGFloat { CGFloat(value.isFinite ? min(20, max(0.5, value)) : 2.5) }
}

@MainActor final class Workspace: ObservableObject {
    @Published var document: PDFDocument?
    @Published var url: URL?
    @Published var message = ""
    @Published var busy = false
    @Published var section = "Início"
    @Published var recentURLs: [URL] = []
    @Published var lastOutput: URL?
    @Published var savedDocumentURL:URL?
    @Published var currentPage = 1
    @Published var bookmarks: Set<Int> = []
    @Published var needsPassword = false
    @Published var documentPassword = ""
    @Published var annotationRevision = 0
    @Published var inkMode = false
    @Published var hasEdits = false
    @Published private(set) var searching = false
    weak var pdfView: PDFView?
    var externalCancellation:(()->Void)?
    private var pendingURL: URL?
    private var process: Process?
    private var cancelled = false
    private var activeJob: UUID?
    private var originalWidgetState = ""
    private var searchDocument: PDFDocument?
    private var searchObservers: [NSObjectProtocol] = []
    private var searchID = UUID()
    private var searchQuery = ""
    private var searchRevision = -1
    private var searchMatches: [PDFSelection] = []
    private var searchCursor = -1
    private var searchAnchorPage = 0
    private var searchAnchorCharacter = 0
    private var searchLimited = false
    private var searchAnimate = true
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
        pendingURL = nil; needsPassword = false; installDocument(doc, url:url)
    }
    private func installDocument(_ doc:PDFDocument, url:URL) {
        cancelSearch(); searchQuery = ""; searchMatches = []; searchCursor = -1
        document = doc; self.url = url; section = "Leitor"; hasEdits = false; savedDocumentURL = nil
        needsPassword = false; pendingURL = nil; documentPassword = ""
        currentPage = min(max(1, UserDefaults.standard.integer(forKey: "readerPage:" + url.standardizedFileURL.path)), max(1, doc.pageCount))
        originalWidgetState = widgetState()
        thumbnails.removeAllObjects()
        recentURLs.removeAll { $0.standardizedFileURL == url.standardizedFileURL }; recentURLs.insert(url, at:0)
        recentURLs = Array(recentURLs.prefix(20))
        UserDefaults.standard.set(recentURLs.map(\.path), forKey:"recentDocuments")
        bookmarks = Set((UserDefaults.standard.array(forKey:bookmarkKey) as? [Int] ?? []).filter { $0 > 0 && $0 <= doc.pageCount })
        message = "\(doc.pageCount) páginas · \(url.lastPathComponent)"
    }
    private var bookmarkKey:String { "bookmarks:" + (url?.standardizedFileURL.path ?? "") }
    func clearRecent() { recentURLs = []; UserDefaults.standard.removeObject(forKey:"recentDocuments") }
    var hasUnsavedChanges:Bool { hasEdits || widgetState() != originalWidgetState }
    private func widgetState() -> String {
        guard let document else { return "" }
        var state:[String] = []
        for index in 0..<document.pageCount {
            for (position, annotation) in (document.page(at:index)?.annotations ?? []).enumerated() {
                if annotation.type == PDFAnnotationSubtype.widget.rawValue || annotation.fieldName != nil {
                    let value = annotation.widgetStringValue ?? ""
                    state.append("\(index):\(position):\(annotation.fieldName ?? ""): \(value.utf8.count):\(value):\(annotation.buttonWidgetState.rawValue)")
                }
            }
        }
        return state.joined(separator:"\n")
    }
    func confirmDiscardEdits() -> Bool {
        NSApp.keyWindow?.makeFirstResponder(nil)
        (pdfView as? DrawingPDFView)?.finishStroke()
        guard hasUnsavedChanges else { return true }
        let alert = NSAlert(); alert.messageText = "Há alterações no documento aberto"
        alert.informativeText = "Salve uma cópia para conservar suas anotações antes de abrir outro arquivo."
        alert.addButton(withTitle:"Voltar"); alert.addButton(withTitle:"Descartar alterações")
        return alert.runModal() == .alertSecondButtonReturn
    }
    func selectOutput(extension suffix:String = "pdf", directory:Bool = false, toolName:String = "PDF", originalURL: URL? = nil) -> URL? {
        let panel = NSSavePanel()
        let prefix = UserDefaults.standard.string(forKey:"outputPrefix") ?? "PDF-resultado"
        panel.nameFieldStringValue = OutputFilename.make(template: UserDefaults.standard.string(forKey: "outputFilenameTemplate"),
            prefix: prefix, original: (originalURL ?? savedDocumentURL ?? url)?.lastPathComponent ?? "Documento.pdf", tool: toolName, suffix: suffix, directory: directory)
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
        (pdfView as? DrawingPDFView)?.finishStroke()
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
        guard let bytes else { message = "Não foi possível criar uma cópia do documento. Nenhum arquivo foi salvo."; return }
        guard let target = selectOutput(toolName: "Cópia") else { return }
        do {
            try NativeOutput.write(bytes,to:target)
            lastOutput = target; savedDocumentURL = target; hasEdits = false; originalWidgetState = widgetState(); message = "Cópia salva: \(target.lastPathComponent)"
        } catch { message = "Não foi possível salvar: \(error.localizedDescription)" }
    }
    func printDocument() {
        guard let document else { return }
        document.printOperation(for:NSPrintInfo.shared, scalingMode:.pageScaleDownToFit, autoRotate:true)?.run()
    }
    func highlight(colorHex: String? = nil) {
        guard let selection = pdfView?.currentSelection else { message = "Selecione texto no documento para realçar."; return }
        let color = ReaderAnnotationStyle.color(colorHex ?? UserDefaults.standard.string(forKey: "readerHighlightColor") ?? "#FFE600", fallback: "#FFE600")
        for line in selection.selectionsByLine() {
            for page in line.pages {
                let annotation = PDFAnnotation(bounds:line.bounds(for:page), forType:.highlight, withProperties:nil)
                annotation.color = color.withAlphaComponent(0.45); page.addAnnotation(annotation)
            }
        }
        didEdit(); message = "Realce adicionado. Salve uma cópia para conservar a alteração."
    }
    func addNote(_ text:String, colorHex: String? = nil) {
        guard let page = pdfView?.currentPage, !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { return }
        let bounds = page.bounds(for:.cropBox)
        let annotation = PDFAnnotation(bounds:CGRect(x:bounds.minX + 30,y:bounds.maxY - 70,width:28,height:28),forType:.text,withProperties:nil)
        annotation.contents = text
        annotation.color = ReaderAnnotationStyle.color(colorHex ?? UserDefaults.standard.string(forKey: "readerNoteColor") ?? "#FFCC00", fallback: "#FFCC00")
        page.addAnnotation(annotation); didEdit()
    }
    func rotatePage() {
        guard let page = pdfView?.currentPage else { return }
        page.rotation = (page.rotation + 90) % 360; didEdit()
    }
    func didEdit() { cancelSearch(); hasEdits = true; annotationRevision += 1; thumbnails.removeAllObjects() }
    func goToPage(_ number:Int) {
        guard let document, let page = document.page(at:number - 1) else { return }
        pdfView?.go(to:page); currentPage = number
    }
    func recordPage(_ page: PDFPage, in document: PDFDocument) {
        guard self.document === document else { return }
        let index = document.index(for: page)
        guard index != NSNotFound, index >= 0, index < document.pageCount else { return }
        currentPage = index + 1
        if let url { UserDefaults.standard.set(currentPage, forKey: "readerPage:" + url.standardizedFileURL.path) }
    }
    func nextPage() { pdfView?.goToNextPage(nil) }
    func previousPage() { pdfView?.goToPreviousPage(nil) }
    /// PDFKit's asynchronous search keeps text extraction off the user interaction path.
    func search(_ text: String, animate: Bool = true) {
        searchAnimate = animate
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let document, !document.isLocked, !query.isEmpty else { cancelSearch(); return }
        guard query.count <= 1_000 else { message = "Use até 1.000 caracteres na busca."; return }
        if query == searchQuery, searchDocument === document, searchRevision == annotationRevision, !searchMatches.isEmpty {
            searchCursor = (searchCursor + 1) % searchMatches.count; selectSearchMatch(); return
        }
        if query == searchQuery, searching { return }
        cancelSearch(); searchDocument = document; searchQuery = query; searchRevision = annotationRevision
        searchMatches = []; searchCursor = -1; searchLimited = false
        searchAnchorPage = max(0, currentPage - 1); searchAnchorCharacter = 0
        if let selection = pdfView?.currentSelection, let page = selection.pages.last {
            let count = selection.numberOfTextRanges(on: page)
            let index = document.index(for: page)
            if index != NSNotFound { searchAnchorPage = index }
            if count > 0 { searchAnchorCharacter = NSMaxRange(selection.range(at: count - 1, on: page)) }
        }
        let id = UUID(); searchID = id; searching = true; message = "Buscando “\(query)”…"
        searchObservers.append(NotificationCenter.default.addObserver(forName: .PDFDocumentDidFindMatch, object: document, queue: .main) { [weak self] note in
            guard let selection = note.userInfo?["PDFDocumentFoundSelection"] as? PDFSelection else { return }
            MainActor.assumeIsolated { self?.receiveSearchMatch(selection, id: id) }
        })
        searchObservers.append(NotificationCenter.default.addObserver(forName: .PDFDocumentDidEndFind, object: document, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.finishSearch(id: id) }
        })
        document.beginFindString(query, withOptions: .caseInsensitive)
    }
    func cancelSearch() {
        searchID = UUID()
        for observer in searchObservers { NotificationCenter.default.removeObserver(observer) }
        searchObservers = []
        if searchDocument?.isFinding == true { searchDocument?.cancelFindString() }
        if searching { message = "Busca cancelada." }
        searching = false; searchQuery = ""
    }
    private func receiveSearchMatch(_ selection: PDFSelection, id: UUID) {
        guard id == searchID, searching, let document = searchDocument, self.document === document else { return }
        guard searchMatches.count < 20_000 else {
            searchLimited = true; document.cancelFindString(); finishSearch(id: id); return
        }
        searchMatches.append(selection)
        if searchCursor < 0, let page = selection.pages.first {
            let index = document.index(for: page)
            let character = selection.numberOfTextRanges(on: page) > 0 ? selection.range(at: 0, on: page).location : 0
            if index > searchAnchorPage || (index == searchAnchorPage && character >= searchAnchorCharacter) {
                searchCursor = searchMatches.count - 1; selectSearchMatch()
            }
        }
    }
    private func finishSearch(id: UUID) {
        guard id == searchID else { return }
        searching = false
        for observer in searchObservers { NotificationCenter.default.removeObserver(observer) }
        searchObservers = []
        if searchMatches.isEmpty { message = "Nenhuma ocorrência de “\(searchQuery)”." }
        else { if searchCursor < 0 { searchCursor = 0 }; selectSearchMatch() }
    }
    private func selectSearchMatch() {
        guard searchMatches.indices.contains(searchCursor) else { return }
        let selection = searchMatches[searchCursor]
        pdfView?.setCurrentSelection(selection, animate: searchAnimate); pdfView?.go(to: selection)
        message = "Ocorrência \(searchCursor + 1) de \(searchMatches.count)" + (searching ? " · busca em andamento…" : "") + (searchLimited ? " · limite de 20.000 resultados; refine a busca" : "")
    }
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
        if let externalCancellation { message = "Cancelando…"; externalCancellation(); return }
        guard let process, process.isRunning else { return }
        cancelled = true; message = "Cancelando…"; process.interrupt()
    }
    func executeBatch(operation:String, inputs:[URL], directory:URL, options:[String:Any], title:String) {
        guard !busy, !inputs.isEmpty else { return }
        let individualPasswords: [String]?
        if let raw = options["input_passwords"] {
            guard let values = raw as? [String], values.count == inputs.count else {
                message = "Informe uma senha por arquivo, mantendo a mesma ordem da lista. Nenhum resultado foi criado."; return
            }
            individualPasswords = values
        } else { individualPasswords = nil }
        do { try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:false) }
        catch { message = "Não foi possível criar a pasta de resultados: \(error.localizedDescription)"; return }
        func next(_ index:Int) {
            guard index < inputs.count else { lastOutput = directory; message = "Concluído: \(inputs.count) documentos em \(directory.lastPathComponent)"; return }
            let name = String(format:"%03d-",index+1) + inputs[index].deletingPathExtension().lastPathComponent + ".pdf"
            let target = directory.appendingPathComponent(name)
            var itemOptions = options; itemOptions.removeValue(forKey: "input_passwords")
            if let password = individualPasswords?[index], !password.isEmpty { itemOptions["password"] = password }
            execute(operation:operation,inputs:[inputs[index]],output:target,options:itemOptions,title:"\(title) · \(index+1)/\(inputs.count)") { result in
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
    @AppStorage("readerDirection") private var direction = "vertical"
    @AppStorage("readerDisplayBox") private var box = "crop"
    @AppStorage("readerPageBackground") private var background = "#E8E9EF"
    @AppStorage("readerAutoScale") private var autoScale = true
    @AppStorage("readerZoom") private var zoom = 1.0
    @AppStorage("readerDisplayPageBreaks") private var pageBreaks = true
    @AppStorage("readerInkColor") private var inkColor = "#007AFF"
    @AppStorage("readerInkWidth") private var inkWidth = 2.5
    var mode: Int
    func makeCoordinator() -> Coordinator { Coordinator(model:model) }
    func makeNSView(context:Context) -> PDFView {
        let view = DrawingPDFView(); view.onEdit = { [weak model] in model?.didEdit() }; view.autoScales = true; view.displayMode = .singlePageContinuous
        model.pdfView = view
        context.coordinator.observers.append(NotificationCenter.default.addObserver(forName:.PDFViewPageChanged,object:view,queue:.main) { [weak view, weak model] _ in
            guard let view, let page = view.currentPage, let document = view.document else { return }
            Task { @MainActor in model?.recordPage(page, in: document) }
        })
        let zoomBinding = $zoom
        context.coordinator.observers.append(NotificationCenter.default.addObserver(forName:.PDFViewScaleChanged,object:view,queue:.main) { [weak view] _ in
            guard let view, !view.autoScales else { return }
            let scale = Double(view.scaleFactor)
            if scale.isFinite, scale > 0, abs(zoomBinding.wrappedValue - scale) > 0.001 {
                zoomBinding.wrappedValue = scale
            }
        })
        return view
    }
    func updateNSView(_ view:PDFView, context:Context) {
        let changedDocument = view.document !== model.document
        let previousPage = model.currentPage
        if changedDocument {
            (view as? DrawingPDFView)?.finishStroke()
            view.document = model.document
        }
        if let drawing = view as? DrawingPDFView {
            drawing.inkEnabled = model.inkMode
            drawing.inkColor = ReaderAnnotationStyle.color(inkColor, fallback: "#007AFF")
            drawing.inkWidth = ReaderAnnotationStyle.width(inkWidth)
        }
        let settings = ReaderSettings(mode: mode, direction: direction, box: box, background: background,
                                      autoScale: autoScale, zoom: zoom, pageBreaks: pageBreaks)
        settings.apply(to: view, previous: context.coordinator.settings, changedDocument: changedDocument)
        context.coordinator.settings = settings
        if changedDocument, let page = view.document?.page(at: max(0, previousPage - 1)) { view.go(to: page) }
    }
    final class Coordinator {
        weak var model:Workspace?
        var observers:[NSObjectProtocol] = []
        var settings: ReaderSettings?
        init(model:Workspace) { self.model = model }
        deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }
    }
}

/// Applying only changed preferences preserves a reader's manual zoom and scroll position.
struct ReaderSettings: Equatable {
    var mode: Int
    var direction: String
    var box: String
    var background: String
    var autoScale: Bool
    var zoom: Double
    var pageBreaks: Bool
    @MainActor func apply(to view: PDFView, previous: ReaderSettings?, changedDocument: Bool) {
        let geometryChanged = previous == nil || previous?.mode != mode || previous?.direction != direction || previous?.box != box || previous?.pageBreaks != pageBreaks
        if previous?.mode != mode { view.displayMode = mode == 1 ? .singlePage : mode == 2 ? .twoUpContinuous : .singlePageContinuous }
        if previous?.direction != direction { view.displayDirection = direction == "horizontal" ? .horizontal : .vertical }
        if previous?.box != box { view.displayBox = box == "media" ? .mediaBox : .cropBox }
        if previous?.pageBreaks != pageBreaks { view.displaysPageBreaks = pageBreaks }
        if previous?.background != background {
            let digits = background.hasPrefix("#") ? String(background.dropFirst()) : background
            if digits.count == 6, let value = UInt32(digits, radix: 16) {
                view.backgroundColor = NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255,
                    green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
            } else { view.backgroundColor = .windowBackgroundColor }
        }
        if changedDocument || geometryChanged || previous?.autoScale != autoScale { view.autoScales = autoScale }
        if !autoScale, changedDocument || geometryChanged || previous?.autoScale != autoScale || previous?.zoom != zoom {
            let requested = CGFloat(zoom.isFinite ? min(8, max(0.1, zoom)) : 1)
            view.scaleFactor = min(view.maxScaleFactor, max(view.minScaleFactor, requested))
        }
    }
}


/// Ink is drawn in PDF page coordinates so it remains aligned at any zoom level.
final class DrawingPDFView:PDFView {
    var inkEnabled = false { didSet { if !inkEnabled { finishStroke() } } }
    var inkColor = ReaderAnnotationStyle.color("#007AFF", fallback: "#007AFF")
    var inkWidth: CGFloat = 2.5
    var onEdit:(()->Void)?
    private var drawingPage:PDFPage?
    private var path:NSBezierPath?
    private var preview:PDFAnnotation?
    override func mouseDown(with event:NSEvent) {
        guard inkEnabled else { super.mouseDown(with:event); return }
        let point = convert(event.locationInWindow,from:nil)
        guard let page = page(for:point,nearest:false) else { return }
        beginStroke(on: page, at: convert(point, to: page))
    }
    func beginStroke(on page: PDFPage, at pointOnPage: NSPoint) {
        finishStroke()
        drawingPage = page
        let bounds = page.bounds(for:.cropBox)
        let stroke = NSBezierPath()
        stroke.move(to:NSPoint(x:min(bounds.width, max(0, pointOnPage.x-bounds.minX)),y:min(bounds.height, max(0, pointOnPage.y-bounds.minY)))); path = stroke
        let annotation = PDFAnnotation(bounds:bounds,forType:.ink,withProperties:nil)
        annotation.color = inkColor
        let border = PDFBorder(); border.lineWidth = ReaderAnnotationStyle.width(Double(inkWidth)); annotation.border = border
        preview = annotation; page.addAnnotation(annotation)
    }
    override func mouseDragged(with event:NSEvent) {
        guard inkEnabled else { super.mouseDragged(with:event); return }
        guard let page = drawingPage else { return }
        let location = convert(convert(event.locationInWindow,from:nil),to:page)
        extendStroke(to: location)
    }
    func extendStroke(to location: NSPoint) {
        guard let page = drawingPage,let path,let preview else { return }
        let bounds = page.bounds(for:.cropBox)
        path.line(to:NSPoint(x:min(bounds.width, max(0, location.x-bounds.minX)),y:min(bounds.height, max(0, location.y-bounds.minY))))
        // A single path avoids adding a new segment to the document on every event.
        for existing in preview.paths ?? [] { preview.remove(existing) }
        preview.add(path)
        needsDisplay = true
    }
    override func mouseUp(with event:NSEvent) {
        guard inkEnabled else { super.mouseUp(with:event); return }
        finishStroke()
    }
    override func viewWillMove(toWindow newWindow: NSWindow?) {
        if newWindow == nil { finishStroke() }
        super.viewWillMove(toWindow: newWindow)
    }
    func finishStroke() {
        if let page = drawingPage,let preview {
            if (path?.elementCount ?? 0) < 2 { page.removeAnnotation(preview) } else { onEdit?() }
        }
        drawingPage = nil; path = nil; preview = nil
    }
}
