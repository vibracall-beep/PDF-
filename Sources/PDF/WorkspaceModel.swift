import SwiftUI
import AppKit
import PDFKit
import UniformTypeIdentifiers
import Darwin

private enum ReaderOpenSource: Sendable, Equatable {
    case file(URL)
    case recovery(RecoveryRecord)
}
private struct ReaderNavigationTarget: Sendable {
    let page: Int?
    let displayTitle: String?
}
private struct ReaderOpenRequest: Sendable {
    let id = UUID()
    let source: ReaderOpenSource
    var data: Data?
    var password: String?
    var navigation: ReaderNavigationTarget?
    var verifiedSHA: String?
}
private struct PendingReaderPassword {
    let source: ReaderOpenSource
    let data: Data
    let navigation: ReaderNavigationTarget?
    let verifiedSHA: String?
}

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
    @Published var message = "" {
        didSet { showsDocumentIdentity = false }
    }
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
    @Published private(set) var sessions: [PDFDocumentSession] = []
    @Published private(set) var activeSessionID: UUID?
    @Published var comparisonSessionID: UUID?
    @Published var selectedAnnotation: PDFAnnotation?
    @Published private(set) var recoveryItems: [RecoveryRecord] = []
    @Published private(set) var recoveryWarnings: [String] = []
    weak var pdfView: PDFView?
    var externalCancellation:(()->Void)?
    private var pendingReaderPassword: PendingReaderPassword?
    private var openingQueue: [ReaderOpenRequest] = []
    private var activeOpening: ReaderOpenRequest?
    private var openingTask: Task<Void, Never>?
    private var retiredOpeningTasks: [UUID: Task<Void, Never>] = [:]
    private var openingWorker: Task<NativePDFSerialization.Opening, Error>?
    private var openingCancellation: NativeCancellation?
    private var ownsOpeningBusy = false
    private var process: OwnedChildProcess?
    private var executionTask: Task<Void, Never>?
    private var preparingForTermination = false
    private struct TerminationSessionState: Equatable {
        let id: UUID
        let document: ObjectIdentifier
        let pageCount: Int
        let revision: Int
        let edited: Bool
        let widgets: String
        let source: URL?
        let saved: URL?
        let title: Data
        let page: Int
        let zoom: Double
        let autoScale: Bool
        let bookmarks: [Int]
    }
    private struct TerminationState: Equatable {
        let sessions: [TerminationSessionState]
        let active: UUID?
        let comparison: UUID?
    }
    private var terminationDecision: TerminationState?
    private var cancelled = false
    private var activeJob: UUID?
    private var originalWidgetState = ""
    // Only identity messages follow tab changes. Progress, results, recovery
    // notices and errors keep their meaning until another action replaces them.
    private var showsDocumentIdentity = false
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
    private var recoveryTimer: Timer?
    private let defaults: UserDefaults
    private let recoveryStore: RecoveryStore
    private let automaticRecoveryPermitted: Bool
    private let transientDefaultsSuite: String?
    private let thumbnails = NSCache<NSNumber, NSImage>()

    init(defaults: UserDefaults = .standard, recoveryStore: RecoveryStore = .shared, enableRecoveryPolling: Bool = true) {
        let automation = CommandLine.arguments.contains { ["--smoke-test", "--render-preview", "--benchmark", "--vision-audit"].contains($0) }
        if automation, defaults === UserDefaults.standard {
            let suite = "PDF.Automation.\(UUID().uuidString)"
            self.defaults = UserDefaults(suiteName: suite)!; transientDefaultsSuite = suite
        } else { self.defaults = defaults; transientDefaultsSuite = nil }
        automaticRecoveryPermitted = !automation
        self.recoveryStore = automation && recoveryStore === RecoveryStore.shared
            ? RecoveryStore(directory: FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Automation-Recovery-\(UUID().uuidString)")) : recoveryStore
        recentURLs = (self.defaults.stringArray(forKey:"recentDocuments") ?? []).map { URL(fileURLWithPath:$0) }
        thumbnails.countLimit = 150
        if enableRecoveryPolling && !automation { recoveryTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.pollSessions() }
        } }
        if !automation { refreshRecovery() }
    }
    deinit {
        recoveryTimer?.invalidate(); openingCancellation?.cancel(); openingWorker?.cancel(); openingTask?.cancel()
        process?.cancel()
        if let transientDefaultsSuite { defaults.removePersistentDomain(forName: transientDefaultsSuite) }
    }
    func open() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.pdf]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        open(url:url)
    }
    func open(url:URL) {
        open(url: url, navigation: nil)
    }
    /// A citation's destination travels with this exact file request, including
    /// its password prompt. Cancellation drops the request and its destination.
    func open(url: URL, page: Int?, displayTitle: String?) {
        guard page.map({ (1...1_000_000).contains($0) }) ?? true,
              displayTitle.map({ !$0.isEmpty && $0.count <= 300 }) ?? true else {
            message = "A página ou o título da referência é inválido."; return
        }
        open(url: url, navigation: ReaderNavigationTarget(page: page, displayTitle: displayTitle))
    }
    /// Verify and open this immutable snapshot; the URL is only its identity.
    /// No URL-backed PDFKit path or file reread participates in this route.
    func openVerified(data: Data, url: URL, sha: String, page: Int?, title: String?) {
        guard url.isFileURL, !data.isEmpty, data.count <= LibraryFiles.maximumPDF, LibraryFiles.validHash(sha),
              page.map({ (1...1_000_000).contains($0) }) ?? true,
              title.map({ !$0.isEmpty && $0.count <= 300 }) ?? true else {
            message = "Os bytes, a impressão digital ou o destino da referência são inválidos."; return
        }
        (pdfView as? DrawingPDFView)?.finishStroke(); captureActiveSession()
        pendingReaderPassword = nil; documentPassword = ""; needsPassword = false
        enqueueOpening(ReaderOpenRequest(source: .file(url), data: data,
                                         navigation: ReaderNavigationTarget(page: page, displayTitle: title), verifiedSHA: sha))
    }
    private func open(url: URL, navigation: ReaderNavigationTarget?) {
        // A new explicit selection replaces an unanswered password prompt, but
        // does not discard distinct files already being opened in the queue.
        pendingReaderPassword = nil; documentPassword = ""; needsPassword = false
        if let existing = sessions.first(where: {
            ($0.savedURL ?? $0.sourceURL)?.standardizedFileURL == url.standardizedFileURL && (navigation == nil || !$0.refreshDirty())
        }) {
            if let page = navigation?.page, page > existing.document.pageCount { message = "A página citada não existe nesta versão."; startNextOpening(); return }
            activateSession(existing.id)
            if let navigation {
                if let title = navigation.displayTitle { existing.displayTitle = title }
                if let page = navigation.page {
                    existing.page = page; currentPage = page
                    if pdfView?.document === existing.document, let target = existing.document.page(at: page - 1) { pdfView?.go(to: target) }
                }
            }
            refreshDocumentIdentityMessage()
            startNextOpening(); return
        }
        var metadata = stat()
        guard url.path.withCString({ fstatat(AT_FDCWD, $0, &metadata, 0) }) == 0,
              metadata.st_mode & S_IFMT == S_IFREG else {
            message = "Escolha um arquivo PDF regular e acessível."; startNextOpening(); return
        }
        // PDFKit keeps ordinary PDFs backed by their URL. Only protected input
        // needs a bounded immutable byte snapshot and independent authentication.
        guard let doc = PDFDocument(url:url) else { message = "Não foi possível ler este PDF. Verifique o arquivo e o acesso à pasta."; startNextOpening(); return }
        if !doc.isEncrypted {
            guard doc.pageCount > 0 else { message = "O PDF não contém páginas legíveis."; startNextOpening(); return }
            if let page = navigation?.page, page > doc.pageCount { message = "A página citada não existe nesta versão."; startNextOpening(); return }
            installDocument(doc, url:url, navigation: navigation); startNextOpening(); return
        }
        enqueueOpening(ReaderOpenRequest(source: .file(url), navigation: navigation))
    }
    func unlockPendingDocument() {
        let password = documentPassword
        documentPassword = ""; needsPassword = false
        guard let pending = pendingReaderPassword, activeOpening == nil else { return }
        startOpening(ReaderOpenRequest(source: pending.source, data: pending.data, password: password, navigation: pending.navigation, verifiedSHA: pending.verifiedSHA))
    }
    func cancelPendingUnlock() {
        if let task = openingTask, let id = activeOpening?.id {
            retiredOpeningTasks[id] = task
            Task { @MainActor [weak self] in await task.value; self?.retiredOpeningTasks[id] = nil }
        }
        activeOpening = nil
        openingCancellation?.cancel(); openingWorker?.cancel(); openingTask?.cancel()
        openingCancellation = nil; openingWorker = nil; openingTask = nil
        pendingReaderPassword = nil; documentPassword = ""; needsPassword = false
        releaseOpeningBusy(); startNextOpening()
    }
    func cancelDocumentOpenings() {
        openingQueue.removeAll(); cancelPendingUnlock()
    }
    /// Await actual work, including queued files, without pumping the run loop.
    /// A password prompt is a stable waiting state; entering a password starts
    /// a new task that can be awaited with this same method.
    func waitForPendingOpen() async {
        while true {
            if let task = openingTask { await task.value; continue }
            guard !retiredOpeningTasks.isEmpty else { return }
            let tasks = retiredOpeningTasks
            for (id, task) in tasks { await task.value; retiredOpeningTasks[id] = nil }
        }
    }
    private func enqueueOpening(_ request: ReaderOpenRequest) {
        // A verified request has not had its supplied bytes checked yet. Never
        // deduplicate it by URL or trust another request's claimed fingerprint.
        if request.verifiedSHA == nil {
            guard !(activeOpening?.source == request.source && activeOpening?.verifiedSHA == nil),
                  !openingQueue.contains(where: { $0.source == request.source && $0.verifiedSHA == nil }) else { startNextOpening(); return }
        }
        openingQueue.append(request); startNextOpening()
    }
    private func startNextOpening() {
        guard activeOpening == nil, pendingReaderPassword == nil, !openingQueue.isEmpty else { return }
        startOpening(openingQueue.removeFirst())
    }
    private func releaseOpeningBusy() {
        if ownsOpeningBusy { busy = false; externalCancellation = nil; ownsOpeningBusy = false }
    }
    private func startOpening(_ request: ReaderOpenRequest) {
        let token = NativeCancellation(), store = recoveryStore
        activeOpening = request; openingCancellation = token
        // Do not replace another feature's cancellation handler or busy state.
        if !busy {
            ownsOpeningBusy = true; busy = true
            externalCancellation = { [weak self] in self?.cancelDocumentOpenings() }
        }
        message = "Abrindo e verificando o documento…"
        let worker = Task<NativePDFSerialization.Opening, Error>.detached(priority: .userInitiated) {
            try Task.checkCancellation(); try token.check()
            let data: Data
            if let supplied = request.data { data = supplied }
            else {
                switch request.source {
                case .file(let url): data = try Self.readerBytes(at: url, cancellation: token)
                case .recovery(let record): data = try store.load(record)
                }
            }
            try Task.checkCancellation(); try token.check()
            if let expected = request.verifiedSHA {
                guard LibraryFiles.hash(data) == expected else {
                    throw NSError(domain: "PDF.Reader", code: 5, userInfo: [NSLocalizedDescriptionKey: "Os bytes da referência não correspondem à impressão digital verificada."])
                }
                try Task.checkCancellation(); try token.check()
            }
            return try NativePDFSerialization.prepareOpen(data: data, password: request.password, cancellation: token)
        }
        openingWorker = worker
        openingTask = Task { @MainActor [weak self] in
            do {
                let opening = try await withTaskCancellationHandler { try await worker.value } onCancel: {
                    token.cancel(); worker.cancel()
                }
                try Task.checkCancellation(); try token.check()
                guard let self, self.activeOpening?.id == request.id else { return }
                let verifiedSession: PDFDocumentSession?
                if let sha = request.verifiedSHA, case .file(let url) = request.source {
                    (self.pdfView as? DrawingPDFView)?.finishStroke(); self.captureActiveSession()
                    verifiedSession = self.sessions.first {
                        $0.sourceFingerprint == sha && $0.savedURL == nil && $0.sourceURL?.standardizedFileURL == url.standardizedFileURL && !$0.refreshDirty()
                    }
                } else { verifiedSession = nil }
                if let existing = verifiedSession {
                    if let page = request.navigation?.page, page > existing.document.pageCount {
                        throw NSError(domain: "PDF.Reader", code: 4, userInfo: [NSLocalizedDescriptionKey: "A página citada não existe nesta versão."])
                    }
                    self.pendingReaderPassword = nil; self.needsPassword = false; self.documentPassword = ""
                    self.activateSession(existing.id)
                    if let title = request.navigation?.displayTitle { existing.displayTitle = title }
                    if let page = request.navigation?.page {
                        existing.page = page; self.currentPage = page
                        if self.pdfView?.document === existing.document, let target = existing.document.page(at: page - 1) { self.pdfView?.go(to: target) }
                    }
                    self.message = "Fonte verificada aberta na página \(self.currentPage)."
                } else if opening.requiresPassword {
                    self.pendingReaderPassword = PendingReaderPassword(source: request.source, data: opening.originalData, navigation: request.navigation, verifiedSHA: request.verifiedSHA)
                    self.documentPassword = ""; self.needsPassword = true
                    self.message = "Digite a senha para abrir o documento protegido."
                } else {
                    let document = try NativePDFSerialization.finishOpen(opening)
                    try token.check()
                    if let page = request.navigation?.page, page > document.pageCount {
                        throw NSError(domain: "PDF.Reader", code: 4, userInfo: [NSLocalizedDescriptionKey: "A página citada não existe nesta versão."])
                    }
                    self.pendingReaderPassword = nil; self.needsPassword = false
                    switch request.source {
                    case .file(let url): self.installDocument(document, url: url, password: request.password,
                                                           usedCompatibilityCopy: opening.usedCompatibilityCopy, navigation: request.navigation, sourceFingerprint: request.verifiedSHA)
                    case .recovery(let record): self.restore(document, from: record, password: request.password,
                                                            usedCompatibilityCopy: opening.usedCompatibilityCopy)
                    }
                }
            } catch is CancellationError { }
            catch {
                if let self, self.activeOpening?.id == request.id {
                    self.message = "Não foi possível abrir: \(error.localizedDescription)"
                    if self.pendingReaderPassword?.source == request.source { self.needsPassword = true }
                }
            }
            guard let self, self.activeOpening?.id == request.id else { return }
            self.activeOpening = nil; self.openingCancellation = nil; self.openingWorker = nil; self.openingTask = nil
            self.releaseOpeningBusy(); self.startNextOpening()
        }
    }
    private nonisolated static func readerBytes(at url: URL, cancellation: NativeCancellation) throws -> Data {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let descriptor = Darwin.open(url.path, O_RDONLY | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat()
        let limit = 1_073_741_824
        guard fstat(descriptor, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_size > 0, before.st_size <= Int64(limit) else {
            throw NSError(domain: "PDF.Reader", code: 1, userInfo: [NSLocalizedDescriptionKey: "O PDF protegido deve ser um arquivo regular de até 1 GiB."])
        }
        var data = Data()
        while true {
            try Task.checkCancellation(); try cancellation.check()
            guard let chunk = try handle.read(upToCount: min(1_048_576, limit - data.count + 1)), !chunk.isEmpty else { break }
            guard data.count <= limit - chunk.count else {
                throw NSError(domain: "PDF.Reader", code: 2, userInfo: [NSLocalizedDescriptionKey: "O PDF excedeu o limite de leitura de 1 GiB."])
            }
            data.append(chunk)
        }
        var after = stat()
        guard fstat(descriptor, &after) == 0, after.st_size == before.st_size, Int64(data.count) == before.st_size,
              after.st_mtimespec.tv_sec == before.st_mtimespec.tv_sec, after.st_mtimespec.tv_nsec == before.st_mtimespec.tv_nsec else {
            throw NSError(domain: "PDF.Reader", code: 3, userInfo: [NSLocalizedDescriptionKey: "O arquivo mudou durante a leitura. Abra-o novamente."])
        }
        try cancellation.check()
        return data
    }
    private func installDocument(_ doc:PDFDocument, url:URL, password: String? = nil, usedCompatibilityCopy: Bool = false,
                                 navigation: ReaderNavigationTarget? = nil, sourceFingerprint: String? = nil) {
        (pdfView as? DrawingPDFView)?.finishStroke()
        captureActiveSession()
        let session = PDFDocumentSession(document: doc, sourceURL: url, password: password, usedCompatibilityCopy: usedCompatibilityCopy, sourceFingerprint: sourceFingerprint)
        let preferredZoom = defaults.object(forKey: "readerZoom") as? Double ?? 1
        session.zoom = preferredZoom.isFinite ? min(8, max(0.1, preferredZoom)) : 1
        session.autoScale = defaults.object(forKey: "readerAutoScale") as? Bool ?? true
        session.page = min(max(1, defaults.integer(forKey: "readerPage:" + url.standardizedFileURL.path)), max(1, doc.pageCount))
        if let page = navigation?.page { session.page = page }
        session.displayTitle = navigation?.displayTitle
        session.bookmarks = Set((defaults.array(forKey: "bookmarks:" + url.standardizedFileURL.path) as? [Int] ?? []).filter { $0 > 0 && $0 <= doc.pageCount })
        configure(session); sessions.append(session); loadSession(session)
        needsPassword = false; pendingReaderPassword = nil; documentPassword = ""
        recentURLs.removeAll { $0.standardizedFileURL == url.standardizedFileURL }; recentURLs.insert(url, at:0)
        recentURLs = Array(recentURLs.prefix(20))
        defaults.set(recentURLs.map(\.path), forKey:"recentDocuments")
        refreshDocumentIdentityMessage(replacingPrevious: true)
        scheduleRecovery(session)
    }
    private var bookmarkKey:String { "bookmarks:" + (url?.standardizedFileURL.path ?? "") }
    func clearRecent() { recentURLs = []; defaults.removeObject(forKey:"recentDocuments") }
    var hasUnsavedChanges:Bool { hasEdits || widgetState() != originalWidgetState }
    private func widgetState() -> String {
        guard let document else { return "" }
        return PDFDocumentSession.widgetState(document)
    }
    func confirmDiscardEdits() -> Bool {
        NSApp.keyWindow?.makeFirstResponder(nil)
        (pdfView as? DrawingPDFView)?.finishStroke()
        captureActiveSession()
        let dirty = sessions.filter { $0.refreshDirty() }
        if dirty.isEmpty { return checkpointSynchronously() }
        let alert = NSAlert(); alert.messageText = "Há alterações em \(dirty.count) documento(s)"
        alert.informativeText = "Você pode manter cópias locais de recuperação para continuar depois. Os arquivos originais permanecem intactos."
        alert.addButton(withTitle: "Voltar"); alert.addButton(withTitle: "Sair mantendo recuperação"); alert.addButton(withTitle: "Descartar alterações")
        switch alert.runModal() {
        case .alertSecondButtonReturn: return checkpointSynchronously(force: true)
        case .alertThirdButtonReturn:
            for session in sessions { session.cancelRecoveryTask(); try? recoveryStore.delete(session.id) }
            return true
        default: return false
        }
    }
    var activeSession: PDFDocumentSession? { sessions.first { $0.id == activeSessionID } }
    private func configure(_ session: PDFDocumentSession) {
        session.history.onChange = { [weak self, weak session] in
            guard let self, let session else { return }
            AnnotationDiagnostics.trace("history.onChange: session state begin")
            session.hasEdits = true; session.isDirty = true; session.annotationRevision += 1
            AnnotationDiagnostics.trace("history.onChange: session state end; workspace state begin")
            if self.activeSessionID == session.id {
                self.hasEdits = true; self.annotationRevision = session.annotationRevision; self.thumbnails.removeAllObjects()
                if let selected = self.selectedAnnotation, selected.page == nil { self.selectedAnnotation = nil }
                self.pdfView?.needsDisplay = true
            }
            AnnotationDiagnostics.trace("history.onChange: workspace state end; recovery schedule begin")
            self.scheduleRecovery(session)
            AnnotationDiagnostics.trace("history.onChange: recovery schedule end")
        }
    }
    func captureActiveSession() {
        guard let document else { return }
        let session: PDFDocumentSession
        if let existing = activeSession { session = existing }
        else {
            session = PDFDocumentSession(document: document, sourceURL: url)
            configure(session); sessions.append(session); activeSessionID = session.id
        }
        session.document = document; session.sourceURL = url; session.savedURL = savedDocumentURL
        session.page = currentPage; session.bookmarks = bookmarks; session.hasEdits = hasEdits
        session.annotationRevision = annotationRevision; session.originalWidgetState = originalWidgetState
        if pdfView?.document === document, let view = pdfView {
            let zoom = Double(view.scaleFactor)
            if zoom.isFinite, zoom > 0 { session.zoom = min(8, max(0.1, zoom)) }
            session.autoScale = view.autoScales
        }
        session.refreshDirty()
    }
    private func loadSession(_ session: PDFDocumentSession) {
        cancelSearch(); selectedAnnotation = nil
        activeSessionID = session.id; document = session.document; url = session.sourceURL; savedDocumentURL = session.savedURL
        currentPage = min(max(1, session.page), max(1, session.document.pageCount)); bookmarks = session.bookmarks
        hasEdits = session.hasEdits; annotationRevision = session.annotationRevision; originalWidgetState = session.originalWidgetState
        thumbnails.removeAllObjects(); section = "Leitor"
        refreshDocumentIdentityMessage()
    }
    private func refreshDocumentIdentityMessage(replacingPrevious: Bool = false) {
        guard !busy || (replacingPrevious && ownsOpeningBusy),
              replacingPrevious || showsDocumentIdentity || message.isEmpty else { return }
        guard let session = activeSession else { message = ""; return }
        let count = session.document.pageCount
        message = "\(count) \(count == 1 ? "página" : "páginas") · \(session.title)"
        showsDocumentIdentity = true
    }
    func activateSession(_ id: UUID) {
        guard id != activeSessionID, let session = sessions.first(where: { $0.id == id }) else { return }
        NSApp.keyWindow?.makeFirstResponder(nil); (pdfView as? DrawingPDFView)?.finishStroke(); captureActiveSession(); loadSession(session)
    }
    func closeSession(_ id: UUID, discardChanges: Bool = false) {
        NSApp.keyWindow?.makeFirstResponder(nil); (pdfView as? DrawingPDFView)?.finishStroke(); captureActiveSession()
        guard let session = sessions.first(where: { $0.id == id }) else { return }
        if session.refreshDirty(), !discardChanges {
            let alert = NSAlert(); alert.messageText = "Fechar \(session.title)?"
            alert.informativeText = "Há alterações não salvas nesta aba. Salvar cópia conserva o documento antes de fechar."
            alert.addButton(withTitle: "Cancelar"); alert.addButton(withTitle: "Salvar cópia"); alert.addButton(withTitle: "Descartar alterações")
            switch alert.runModal() {
            case .alertSecondButtonReturn:
                activateSession(id); save(); guard !hasUnsavedChanges else { return }
            case .alertThirdButtonReturn: break
            default: return
            }
        }
        session.cancelRecoveryTask()
        do { try recoveryStore.delete(id) } catch { message = "Não foi possível remover a recuperação da aba: \(error.localizedDescription)"; return }
        sessions.removeAll { $0.id == id }
        if comparisonSessionID == id { comparisonSessionID = nil }
        if activeSessionID == id {
            activeSessionID = nil; selectedAnnotation = nil; cancelSearch()
            if let next = sessions.last { loadSession(next) }
            else {
                document = nil; url = nil; savedDocumentURL = nil; hasEdits = false; originalWidgetState = ""; currentPage = 1; bookmarks = []; section = "Início"
                refreshDocumentIdentityMessage()
            }
        }
        refreshRecovery()
    }
    private var recoveryEnabled: Bool { automaticRecoveryPermitted && (defaults.object(forKey: "recoveryEnabled") as? Bool ?? true) }
    private func pollSessions() {
        guard ApplicationWork.isAcceptingWork else { return }
        captureActiveSession()
        for session in sessions { session.refreshDirty(); scheduleRecovery(session) }
    }
    private func fingerprint(_ session: PDFDocumentSession) -> String {
        "\(contentFingerprint(session)):\(session.page):\(session.zoom):\(session.autoScale):\(session.bookmarks.sorted())"
    }
    private func contentFingerprint(_ session: PDFDocumentSession) -> String {
        "\(session.annotationRevision):\(session.hasEdits):\(session.savedURL?.path ?? ""):\(PDFDocumentSession.widgetState(session.document))"
    }
    private func recoveryState(_ session: PDFDocumentSession) -> RecoverySessionState {
        RecoverySessionState(page: session.page, zoom: session.zoom, autoScale: session.autoScale, bookmarks: Array(session.bookmarks).sorted())
    }
    private func scheduleRecovery(_ session: PDFDocumentSession) {
        guard recoveryEnabled else { session.cancelRecoveryTask(); return }
        let value = fingerprint(session)
        guard value != session.recoveryFingerprint else { return }
        // Navigation uses a small sidecar; debounce it while the user scrolls.
        if contentFingerprint(session) == session.recoveryContentFingerprint, Date().timeIntervalSince(session.lastRecoveryDate) < 15 { return }
        // The pending marker prevents the polling timer from perpetually resetting debounce.
        if session.recoveryTask != nil { return }
        let token = session.beginRecoveryTask()
        session.recoveryTask = ApplicationTask.start { [weak self, weak session] in
            defer { session?.finishRecoveryTask(token) }
            do {
                try await Task.sleep(for: .milliseconds(650)); try Task.checkCancellation()
                guard let self, let session, session.recoveryTaskID == token,
                      self.sessions.contains(where: { $0.id == session.id }), self.recoveryEnabled else { return }
                let captured = self.fingerprint(session), content = self.contentFingerprint(session), state = self.recoveryState(session)
                let previous = content == session.recoveryContentFingerprint ? session.recoveryRecord : nil
                let prepared = previous == nil ? try session.recoveryPrepared() : nil
                let source = session.savedURL ?? session.sourceURL
                let id = session.id, encrypted = session.document.isEncrypted, title = session.title
                let store = self.recoveryStore
                // Capture uses the reader's actor; structural normalization,
                // fidelity checks and atomic publication run on the worker.
                let write = Task<RecoveryRecord?, Error>.detached(priority: .utility) {
                    try Task.checkCancellation()
                    if let previous { return try store.updateState(record: previous, state: state) }
                    guard let prepared else { throw RecoveryError.invalidDocument }
                    let data = try NativePDFSerialization.finish(prepared)
                    try Task.checkCancellation()
                    return try store.save(documentData: data, sourceURL: source, sessionID: id, encrypted: encrypted, title: title, state: state)
                }
                session.recoveryWrite = write
                let record = try await withTaskCancellationHandler { try await write.value } onCancel: { write.cancel() }
                try Task.checkCancellation()
                guard session.recoveryTaskID == token else { return }
                guard let record else {
                    // The snapshot was removed/replaced. The next poll captures
                    // current content instead of attaching state to stale bytes.
                    session.recoveryRecord = nil; session.recoveryContentFingerprint = ""; return
                }
                session.recoveryRecord = record
                session.recoveryFingerprint = captured
                session.recoveryContentFingerprint = content; session.lastRecoveryDate = Date()
                self.refreshRecovery()
            } catch is CancellationError { }
            catch { if session?.recoveryTaskID == token { self?.message = "Recuperação: \(error.localizedDescription)" } }
        }
    }
    func checkpointRecovery() { captureActiveSession(); for session in sessions { session.recoveryFingerprint = ""; scheduleRecovery(session) } }
    private func checkpointSynchronously(force: Bool = false) -> Bool {
        guard recoveryEnabled || force else { return true }
        do {
            try checkpointRecoveryNow()
            return true
        } catch { message = "Não foi possível preservar a sessão: \(error.localizedDescription)"; return false }
    }
    func checkpointRecoveryNow() throws {
        NSApp.keyWindow?.makeFirstResponder(nil); (pdfView as? DrawingPDFView)?.finishStroke(); captureActiveSession()
        for session in sessions {
            session.cancelRecoveryTask()
            let state = recoveryState(session), content = contentFingerprint(session)
            var updated: RecoveryRecord?
            if content == session.recoveryContentFingerprint, let previous = session.recoveryRecord {
                updated = try recoveryStore.updateState(record: previous, state: state)
            }
            if updated == nil {
                updated = try recoveryStore.save(documentData: session.recoveryData(), sourceURL: session.savedURL ?? session.sourceURL,
                    sessionID: session.id, encrypted: session.document.isEncrypted, title: session.title, state: state)
            }
            session.recoveryRecord = updated
            session.recoveryFingerprint = fingerprint(session)
            session.recoveryContentFingerprint = contentFingerprint(session); session.lastRecoveryDate = Date()
        }
    }
    func refreshRecovery() {
        guard ApplicationWork.isAcceptingWork else { return }
        let store = recoveryStore
        ApplicationTask.start { [weak self] in
            do {
                try Task.checkCancellation()
                let worker = Task.detached(priority: .utility) { try Task.checkCancellation(); return try store.list() }
                let records = try await withTaskCancellationHandler { try await worker.value } onCancel: { worker.cancel() }
                try Task.checkCancellation()
                self?.recoveryItems = records; self?.recoveryWarnings = store.warnings
            }
            catch is CancellationError { }
            catch { self?.message = "Não foi possível listar recuperações: \(error.localizedDescription)" }
        }
    }
    func refreshRecoveryNow() throws { recoveryItems = try recoveryStore.list(); recoveryWarnings = recoveryStore.warnings }
    func restoreRecovery(id: UUID) {
        pendingReaderPassword = nil; documentPassword = ""; needsPassword = false
        if sessions.contains(where: { $0.id == id }) { activateSession(id); startNextOpening(); return }
        guard let record = recoveryItems.first(where: { $0.id == id }) else { startNextOpening(); return }
        enqueueOpening(ReaderOpenRequest(source: .recovery(record)))
    }
    private func restore(_ document: PDFDocument, from record: RecoveryRecord, password: String?, usedCompatibilityCopy: Bool = false) {
        captureActiveSession()
        let session = PDFDocumentSession(id: record.id, document: document, sourceURL: record.sourceURL, password: password,
                                         usedCompatibilityCopy: usedCompatibilityCopy)
        session.page = record.state.page; session.zoom = record.state.zoom; session.autoScale = record.state.autoScale
        session.bookmarks = Set(record.state.bookmarks); session.hasEdits = true; session.isDirty = true
        configure(session); sessions.append(session); loadSession(session)
        session.recoveryRecord = record; session.recoveryContentFingerprint = contentFingerprint(session)
        session.recoveryFingerprint = fingerprint(session); session.lastRecoveryDate = Date()
        message = "Sessão recuperada. Salve uma cópia para conservar esta versão; o original não foi substituído."
    }
    func deleteRecovery(id: UUID) {
        func matches(_ source: ReaderOpenSource) -> Bool {
            if case .recovery(let record) = source { return record.id == id }
            return false
        }
        openingQueue.removeAll { matches($0.source) }
        if activeOpening.map({ matches($0.source) }) == true || pendingReaderPassword.map({ matches($0.source) }) == true {
            cancelPendingUnlock()
        }
        if let session = sessions.first(where: { $0.id == id }) {
            session.cancelRecoveryTask(); session.recoveryRecord = nil; session.recoveryFingerprint = fingerprint(session)
        }
        do { try recoveryStore.delete(id); refreshRecovery() }
        catch { message = "Não foi possível excluir a recuperação: \(error.localizedDescription)" }
    }
    var annotationsOnCurrentPage: [PDFAnnotation] { (pdfView?.currentPage?.annotations ?? []).filter(EditableAnnotations.accepts) }
    var annotationUndoManager: UndoManager? { activeSession?.history.undoManager }
    var canUndoAnnotation: Bool { annotationUndoManager?.canUndo ?? false }
    var canRedoAnnotation: Bool { annotationUndoManager?.canRedo ?? false }
    func selectAnnotation(_ annotation: PDFAnnotation?) { selectedAnnotation = annotation.flatMap { EditableAnnotations.accepts($0) ? $0 : nil } }
    func updateSelectedAnnotation(colorHex: String, width: Double, bounds: CGRect, contents: String? = nil) {
        guard let annotation = selectedAnnotation, let page = annotation.page, EditableAnnotations.accepts(annotation) else { return }
        do {
            try EditableAnnotations.validate(bounds, on: page)
            let before = PDFAnnotationState(annotation)
            EditableAnnotations.resize(annotation, to: bounds)
            annotation.color = ReaderAnnotationStyle.color(colorHex, fallback: "#007AFF").withAlphaComponent(annotation.color.alphaComponent)
            if PDFAnnotationKind.matches(annotation, .freeText) { annotation.fontColor = ReaderAnnotationStyle.color(colorHex, fallback: "#007AFF") }
            let border = annotation.border ?? PDFBorder(); border.lineWidth = ReaderAnnotationStyle.width(width); annotation.border = border
            if let contents, PDFAnnotationKind.matchesAny(annotation, [.text, .freeText]) { annotation.contents = contents }
            ensureSession(); activeSession?.history.changed(annotation, before: before)
        } catch { message = error.localizedDescription }
    }
    func deleteSelectedAnnotation() {
        guard let annotation = selectedAnnotation, let page = annotation.page, EditableAnnotations.accepts(annotation) else { return }
        ensureSession(); activeSession?.history.remove(annotation, from: page); selectedAnnotation = nil
    }
    func undoAnnotation() { annotationUndoManager?.undo(); selectedAnnotation = nil }
    func redoAnnotation() { annotationUndoManager?.redo(); selectedAnnotation = nil }
    private func ensureSession() { if activeSession == nil { captureActiveSession() } }
    func selectOutput(extension suffix:String = "pdf", directory:Bool = false, toolName:String = "PDF", originalURL: URL? = nil, originalName: String? = nil) -> URL? {
        let panel = NSSavePanel()
        let prefix = defaults.string(forKey:"outputPrefix") ?? "PDF-resultado"
        panel.nameFieldStringValue = OutputFilename.make(template: defaults.string(forKey: "outputFilenameTemplate"),
            prefix: prefix, original: originalName ?? (originalURL ?? savedDocumentURL ?? url)?.lastPathComponent ?? "Documento.pdf", tool: toolName, suffix: suffix, directory: directory)
        if !directory, let type = UTType(filenameExtension:suffix) { panel.allowedContentTypes = [type] }
        if let path = defaults.string(forKey:"outputDirectory"), !path.isEmpty { panel.directoryURL = URL(fileURLWithPath:path) }
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
        var newPassword: String?
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
            newPassword = secret
        }
        guard let target = selectOutput(toolName: "Cópia") else { return }
        do {
            let prepared = try NativePDFSerialization.prepare(document: document, password: newPassword)
            let checked = try NativePDFSerialization.finish(prepared)
            try commitSavedCopy(checked, to: target, password: newPassword)
        } catch { message = "Não foi possível salvar: \(error.localizedDescription)" }
    }
    /// The destination is committed before the in-memory recovery password or
    /// saved/dirty state can change. Cancelled panels never reach this method.
    func publishSavedCopy(_ bytes: Data, to target: URL, password: String?) throws {
        let checked = try NativePDFSerialization.normalize(data: bytes, password: password)
        try commitSavedCopy(checked, to: target, password: password)
    }
    private func commitSavedCopy(_ checked: Data, to target: URL, password: String?) throws {
        try NativeOutput.write(checked, to: target)
        ensureSession()
        if let password { activeSession?.password = password }
        lastOutput = target; savedDocumentURL = target; hasEdits = false; originalWidgetState = widgetState()
        message = "Cópia salva: \(target.lastPathComponent)"
        captureActiveSession(); if let activeSession { scheduleRecovery(activeSession) }
    }
    func printDocument() {
        guard let document else { return }
        document.printOperation(for:NSPrintInfo.shared, scalingMode:.pageScaleDownToFit, autoRotate:true)?.run()
    }
    func highlight(colorHex: String? = nil) {
        guard let selection = pdfView?.currentSelection else { message = "Selecione texto no documento para realçar."; return }
        ensureSession(); let history = activeSession?.history
        history?.undoManager.beginUndoGrouping(); defer { history?.undoManager.endUndoGrouping() }
        let color = ReaderAnnotationStyle.color(colorHex ?? defaults.string(forKey: "readerHighlightColor") ?? "#FFE600", fallback: "#FFE600")
        for line in selection.selectionsByLine() {
            for page in line.pages {
                let annotation = PDFAnnotation(bounds:line.bounds(for:page), forType:.highlight, withProperties:nil)
                annotation.color = color.withAlphaComponent(0.45); page.addAnnotation(annotation)
                history?.inserted(annotation, on: page, name: "Realçar texto")
            }
        }
        message = "Realce adicionado. Salve uma cópia para conservar a alteração."
    }
    func addNote(_ text:String, colorHex: String? = nil) {
        AnnotationDiagnostics.trace("addNote: currentPage begin")
        guard let page = pdfView?.currentPage, !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else { return }
        AnnotationDiagnostics.trace("addNote: currentPage end; bounds begin")
        let bounds = page.bounds(for:.cropBox)
        AnnotationDiagnostics.trace("addNote: bounds end; annotation init begin")
        let annotation = PDFAnnotation(bounds:CGRect(x:bounds.minX + 30,y:bounds.maxY - 70,width:28,height:28),forType:.text,withProperties:nil)
        AnnotationDiagnostics.trace("addNote: annotation init end; contents begin")
        annotation.contents = text
        AnnotationDiagnostics.trace("addNote: contents end; color begin")
        annotation.color = ReaderAnnotationStyle.color(colorHex ?? defaults.string(forKey: "readerNoteColor") ?? "#FFCC00", fallback: "#FFCC00")
        AnnotationDiagnostics.trace("addNote: color end; page.addAnnotation begin")
        page.addAnnotation(annotation)
        AnnotationDiagnostics.trace("addNote: page.addAnnotation end; ensureSession begin")
        ensureSession()
        AnnotationDiagnostics.trace("addNote: ensureSession end; history.inserted begin")
        activeSession?.history.inserted(annotation, on: page, name: "Adicionar nota")
        AnnotationDiagnostics.trace("addNote: history.inserted end")
    }
    func rotatePage() {
        guard let page = pdfView?.currentPage else { return }
        page.rotation = (page.rotation + 90) % 360; didEdit()
    }
    func didEdit() {
        cancelSearch(); hasEdits = true; annotationRevision += 1; thumbnails.removeAllObjects()
        captureActiveSession(); if let activeSession { scheduleRecovery(activeSession) }
    }
    func goToPage(_ number:Int) {
        guard let document, number > 0, number <= document.pageCount, let page = document.page(at:number - 1) else { return }
        pdfView?.go(to:page); currentPage = number
    }
    /// Stored preferences are defaults for future documents. Only an explicit
    /// reader control changes the magnification of the current session.
    var currentReaderZoom: Double { activeSession?.zoom ?? (defaults.object(forKey: "readerZoom") as? Double ?? 1) }
    var currentReaderAutoScale: Bool { activeSession?.autoScale ?? (defaults.object(forKey: "readerAutoScale") as? Bool ?? true) }
    func setReaderMagnification(zoom requestedZoom: Double? = nil, autoScale requestedAutoScale: Bool? = nil) {
        let matchingView = pdfView?.document === document ? pdfView : nil
        let effectiveZoom = matchingView.map { Double($0.scaleFactor) } ?? currentReaderZoom
        let requested = requestedZoom ?? effectiveZoom
        let zoom = requested.isFinite ? min(8, max(0.1, requested)) : 1
        let autoScale = requestedAutoScale ?? currentReaderAutoScale
        defaults.set(zoom, forKey: "readerZoom"); defaults.set(autoScale, forKey: "readerAutoScale")
        objectWillChange.send()
        activeSession?.zoom = zoom; activeSession?.autoScale = autoScale
        if let view = matchingView {
            view.autoScales = autoScale
            if !autoScale { view.scaleFactor = min(view.maxScaleFactor, max(view.minScaleFactor, CGFloat(zoom))) }
        }
    }
    /// Native gestures and PDFKit keyboard actions update their own session,
    /// without replacing defaults imported by a workspace profile.
    func recordReaderMagnification(zoom: Double, autoScale: Bool, sessionID: UUID, document: PDFDocument) {
        guard activeSessionID == sessionID, self.document === document,
              let session = activeSession, zoom.isFinite, zoom > 0 else { return }
        let value = min(8, max(0.1, zoom))
        guard abs(session.zoom - value) > 0.001 || session.autoScale != autoScale else { return }
        objectWillChange.send(); session.zoom = value; session.autoScale = autoScale
    }
    func recordPage(_ page: PDFPage, in document: PDFDocument) {
        guard self.document === document else { return }
        let index = document.index(for: page)
        guard index != NSNotFound, index >= 0, index < document.pageCount else { return }
        currentPage = index + 1
        if selectedAnnotation?.page !== page { selectedAnnotation = nil }
        activeSession?.page = currentPage
        if let url { defaults.set(currentPage, forKey: "readerPage:" + url.standardizedFileURL.path) }
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
    /// Exposes ownership, not PDFKit's internal object lifetime, for the native
    /// close/cancellation regression and diagnostics.
    var hasSearchResources: Bool { searchDocument != nil || !searchMatches.isEmpty || !searchObservers.isEmpty }
    func cancelSearch() {
        searchID = UUID()
        for observer in searchObservers { NotificationCenter.default.removeObserver(observer) }
        searchObservers = []
        if searchDocument?.isFinding == true { searchDocument?.cancelFindString() }
        if searching { message = "Busca cancelada." }
        searching = false; searchQuery = ""; searchDocument = nil
        searchMatches = []; searchCursor = -1; searchRevision = -1
        searchAnchorPage = 0; searchAnchorCharacter = 0; searchLimited = false
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
        defaults.set(Array(bookmarks).sorted(), forKey:bookmarkKey)
        activeSession?.bookmarks = bookmarks
    }
    func applyImportedReadingState(bookmarks imported:Set<Int>,page:Int?,zoom:Double?,autoScale:Bool?,expectedSessionID:UUID,source:ReadingSourceIdentity,expectedHash:String) throws {
        NSApp.keyWindow?.makeFirstResponder(nil)
        (pdfView as? DrawingPDFView)?.finishStroke()
        guard activeSessionID == expectedSessionID,let session = activeSession,let document,!document.isLocked,
              (session.savedURL ?? session.sourceURL)?.standardizedFileURL == source.url,
              source.sha256 == expectedHash,LibraryFiles.validHash(expectedHash),source.stillMatchesFile(),!hasUnsavedChanges else {
            throw PreferenceError.invalid("A sessão ou os bytes salvos mudaram. Confira o documento antes de aplicar a leitura recebida.")
        }
        let count = document.pageCount
        guard imported.allSatisfy({(1...max(1,count)).contains($0)}),count > 0,
              page.map({(1...count).contains($0)}) ?? true,
              zoom.map({$0.isFinite && (0.1...8).contains($0)}) ?? true else {
            throw PreferenceError.invalid("Os marcadores, a página ou o zoom não pertencem a este documento.")
        }
        bookmarks = imported; session.bookmarks = imported
        defaults.set(Array(imported).sorted(),forKey:bookmarkKey)
        defaults.set(Array(imported).sorted(),forKey:"bookmarks:"+source.url.standardizedFileURL.path)
        defaults.set(Array(imported).sorted(),forKey:"bookmarksSHA256:"+expectedHash)
        if let zoom { session.zoom = zoom; defaults.set(zoom,forKey:"readerZoom") }
        if let autoScale { session.autoScale = autoScale; defaults.set(autoScale,forKey:"readerAutoScale") }
        if pdfView?.document === document,let view = pdfView {
            if let autoScale { view.autoScales = autoScale }
            if let zoom,!session.autoScale { view.scaleFactor = CGFloat(zoom) }
        }
        if let page { session.page = page; goToPage(page) }
        message = "Marcadores importados para a versão verificada do documento."
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
        guard let process else { return }
        cancelled = true; message = "Cancelando…"; process.cancel()
    }
    /// Called only after the existing save/discard/recovery decision. Do not
    /// reply to AppKit until the owned engine and document-open tasks finished.
    func captureTerminationDecision() {
        terminationDecision = currentTerminationState()
    }
    private func currentTerminationState() -> TerminationState {
        NSApp.keyWindow?.makeFirstResponder(nil)
        (pdfView as? DrawingPDFView)?.finishStroke()
        captureActiveSession()
        return TerminationState(sessions: sessions.map { session in
            TerminationSessionState(id: session.id, document: ObjectIdentifier(session.document),
                pageCount: session.document.pageCount, revision: session.annotationRevision, edited: session.hasEdits,
                widgets: PDFDocumentSession.widgetState(session.document), source: session.sourceURL,
                saved: session.savedURL, title: Data(session.title.utf8), page: session.page, zoom: session.zoom,
                autoScale: session.autoScale, bookmarks: session.bookmarks.sorted())
        }, active: activeSessionID, comparison: comparisonSessionID)
    }
    private func refuseTermination(_ detail: String) -> Bool {
        preparingForTermination = false; terminationDecision = nil
        ApplicationWork.resumeAcceptingWork()
        message = detail
        return false
    }
    /// Called again synchronously immediately before AppKit's final reply. A
    /// later widget edit, annotation, tab change or navigation requires a new
    /// save/recovery decision; the previous checkpoint cannot authorize it.
    func authorizeTerminationIfUnchanged() -> Bool {
        guard let terminationDecision, terminationDecision == currentTerminationState() else {
            return refuseTermination("A sessão mudou enquanto as operações eram encerradas. As alterações permanecem abertas; confira os documentos e solicite a saída novamente.")
        }
        return true
    }
    func prepareForTermination(externalDeadline: TimeInterval = 30) async -> Bool {
        if terminationDecision == nil { captureTerminationDecision() }
        preparingForTermination = true
        cancelDocumentOpenings()
        cancel()
        ApplicationWork.cancelAll()
        let interval = externalDeadline.isFinite ? min(30, max(0, externalDeadline)) : 30
        let deadline = ProcessInfo.processInfo.systemUptime + interval
        while ProcessInfo.processInfo.systemUptime < deadline {
            if executionTask == nil && openingTask == nil && retiredOpeningTasks.isEmpty && !busy && ApplicationWork.activeCount == 0 { break }
            try? await Task.sleep(for: .milliseconds(50))
        }
        guard !busy, executionTask == nil, process == nil, openingTask == nil,
              retiredOpeningTasks.isEmpty, ApplicationWork.activeCount == 0 else {
            if !PagesCleanupRegistry.shared.pending.isEmpty {
                return refuseTermination("O Pages ainda não confirmou o fechamento de uma cópia privada. Abra Pages para PDF e use Tentar encerrar cópia privada antes de sair. Os originais permanecem intactos.")
            }
            return refuseTermination("A operação auxiliar ainda não confirmou o encerramento. O PDF permanece aberto; aguarde sua conclusão antes de sair.")
        }
        return authorizeTerminationIfUnchanged()
    }
    func executeBatch(operation:String, inputs:[URL], directory:URL, options:[String:Any], title:String) {
        guard !preparingForTermination, !busy, !inputs.isEmpty else { return }
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
            execute(operation:operation,inputs:[inputs[index]],output:target,options:itemOptions,title:"\(title) · \(index+1)/\(inputs.count)",completion: { result in
                switch result {
                case .success: next(index+1)
                case .failure(let error): self.lastOutput = directory; self.message = "Lote interrompido após \(index) documentos concluídos. \(error.localizedDescription)"
                }
            })
        }
        next(0)
    }
    func execute(operation:String, inputs:[URL], output:URL, options:[String:Any], title:String, progress:((Int,Int)->Void)? = nil, completion:((Result<URL,Error>)->Void)? = nil) {
        func fail(_ detail:String) { message = detail; completion?(.failure(NSError(domain:"PDF.Engine",code:1,userInfo:[NSLocalizedDescriptionKey:detail]))) }
        guard !preparingForTermination else { fail("O PDF está encerrando as operações em andamento."); return }
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
        let input: EngineInputTransport
        do { input = try EngineInputTransport(data: data) }
        catch { fail("Não foi possível preparar as opções da operação: \(error.localizedDescription)"); return }
        let job = UUID(); activeJob = job; busy = true; cancelled = false; lastOutput = nil; message = "\(title)…"
        let task = Process(); task.executableURL = python
        task.arguments = [engine.path,operation] + inputs.map { $0.isFileURL ? $0.path : $0.absoluteString } + ["--output",output.path]
        var environment = ProcessInfo.processInfo.environment
        AdaptivePerformance.apply(to: &environment)
        environment["PDF_OPTIONS_STDIN"] = "1"
        environment["PATH"] = python.deletingLastPathComponent().path + ":/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin")
        task.environment = environment
        let log = Pipe(); task.standardInput = input.handle; task.standardError = log; task.standardOutput = log
        let runtimeLease: FileHandle?
        do { runtimeLease = try BundleRuntimeLease.configureRuntimeChild(task) }
        catch { input.close(); busy = false; fail("Não foi possível manter o bloqueio do motor: \(error.localizedDescription)"); return }
        let child: OwnedChildProcess
        do { child = try OwnedChildProcess(configuration: task) }
        catch { try? runtimeLease?.close(); input.close(); busy = false; process = nil; fail("Não foi possível iniciar o motor: \(error.localizedDescription)"); return }
        process = child
        // The worker is explicitly awaited during application termination.
        // Output is bounded and nonblocking, so an inherited pipe cannot delay
        // completion forever after this exact engine child has exited.
        let worker = Task.detached(priority: .userInitiated) { [weak self] () -> (OwnedChildProcess.Exit?, String, Error?) in
            defer { try? runtimeLease?.close(); input.close(); try? log.fileHandleForReading.close() }
            var tail = Data(), pending = Data()
            do {
                let exit = try child.collectOutput(from: log.fileHandleForReading) { chunk in
                    tail.append(chunk); if tail.count > 131_072 { tail = Data(tail.suffix(131_072)) }
                    pending.append(chunk)
                    while let end = pending.firstIndex(of: 10) {
                        let line = Data(pending[..<end]); pending.removeSubrange(...end)
                        guard let event = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any],
                              event["event"] as? String == "workflow_progress", let completed = event["completed"] as? Int,
                              let total = event["total"] as? Int, total > 0, completed >= 0, completed <= total else { continue }
                        DispatchQueue.main.async { [weak self] in
                            guard self?.activeJob == job, self?.cancelled == false else { return }
                            progress?(completed, total)
                        }
                    }
                    if pending.count > 262_144 { pending = Data(pending.suffix(262_144)) }
                }
                return (exit, String(data: tail, encoding: .utf8) ?? "Falha sem detalhes.", nil)
            } catch {
                child.cancel()
                do {
                    let exit = try child.waitUntilExit()
                    return (exit, "Não foi possível acompanhar o motor: \(error.localizedDescription)", error)
                } catch { return (nil, "Não foi possível confirmar o encerramento do motor.", error) }
            }
        }
        executionTask = Task { @MainActor [weak self] in
            let (exit, raw, executionError) = await worker.value
            guard let self, self.activeJob == job else { return }
            self.executionTask = nil; self.activeJob = nil
            // An ownership/reap failure must not turn into permission to quit.
            // Keep the blocker visible instead of losing the child reference.
            self.busy = exit == nil
            if exit != nil { self.process = nil }
            if executionError == nil, exit?.status == 0, exit?.signalled == false, FileManager.default.fileExists(atPath: output.path) {
                self.lastOutput = output; self.message = "Concluído: \(output.lastPathComponent)"
                completion?(.success(output))
            } else if self.cancelled && executionError == nil {
                if FileManager.default.fileExists(atPath: output.path) {
                    self.lastOutput = output; self.message = "Cancelamento solicitado. Há um resultado no destino; verifique o arquivo antes de continuar."
                } else { self.message = "Operação cancelada. Os arquivos de origem foram preservados." }
                completion?(.failure(NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError)))
            } else {
                let lastJSON = raw.split(separator: "\n").reversed().compactMap { line -> [String: Any]? in
                    guard let data = String(line).data(using: .utf8) else { return nil }
                    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                }.first
                self.message = lastJSON?["error"] as? String ?? String(raw.suffix(2000))
                completion?(.failure(NSError(domain: "PDF.Engine", code: Int(exit?.status ?? 1), userInfo: [NSLocalizedDescriptionKey: self.message])))
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
        view.setAccessibilityLabel("Documento PDF principal"); view.setAccessibilityIdentifier("pdf.reader.document")
        view.onSelection = { [weak model] in model?.selectAnnotation($0) }
        view.onInkInserted = { [weak model] annotation, page in
            model?.captureActiveSession(); model?.activeSession?.history.inserted(annotation, on: page, name: "Desenhar")
        }
        view.onAnnotationTransformed = { [weak model] annotation, before in model?.activeSession?.history.changed(annotation, before: before) }
        view.onDeleteAnnotation = { [weak model] in model?.deleteSelectedAnnotation() }
        model.pdfView = view
        let coordinator = context.coordinator
        coordinator.observers.append(NotificationCenter.default.addObserver(forName:.PDFViewPageChanged,object:view,queue:.main) { [weak view, weak model, weak coordinator] _ in
            guard coordinator?.applyingSettings == false, let view, let page = view.currentPage, let document = view.document else { return }
            Task { @MainActor in
                guard view.document === document, view.currentPage === page else { return }
                model?.recordPage(page, in: document)
            }
        })
        coordinator.observers.append(NotificationCenter.default.addObserver(forName:.PDFViewScaleChanged,object:view,queue:.main) { [weak view, weak model, weak coordinator] _ in
            guard coordinator?.applyingSettings == false, let sessionID = coordinator?.sessionID,
                  let view, let document = view.document else { return }
            let scale = Double(view.scaleFactor), automatic = view.autoScales
            Task { @MainActor in
                guard let model, model.activeSessionID == sessionID,
                      view.document === document, view.autoScales == automatic,
                      abs(Double(view.scaleFactor) - scale) < 0.001 else { return }
                model.recordReaderMagnification(zoom: scale, autoScale: automatic, sessionID: sessionID, document: document)
            }
        })
        return view
    }
    func updateNSView(_ view:PDFView, context:Context) {
        context.coordinator.applyingSettings = true
        defer { context.coordinator.applyingSettings = false }
        context.coordinator.sessionID = model.activeSessionID
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
            drawing.selectedAnnotation = model.selectedAnnotation
            drawing.documentUndoManager = model.annotationUndoManager
        }
        let settings = ReaderSettings(mode: mode, direction: direction, box: box, background: background,
                                      autoScale: model.activeSession?.autoScale ?? autoScale, zoom: model.activeSession?.zoom ?? zoom, pageBreaks: pageBreaks)
        let layoutChanged = settings.layoutDiffers(from: context.coordinator.settings)
        settings.apply(to: view, previous: context.coordinator.settings, changedDocument: changedDocument)
        context.coordinator.settings = settings
        if changedDocument || layoutChanged, let page = view.document?.page(at: max(0, previousPage - 1)) { view.go(to: page) }
    }
    final class Coordinator {
        weak var model:Workspace?
        var observers:[NSObjectProtocol] = []
        var settings: ReaderSettings?
        var applyingSettings = false
        var sessionID: UUID?
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
    func layoutDiffers(from previous: ReaderSettings?) -> Bool {
        previous == nil || previous?.mode != mode || previous?.direction != direction || previous?.box != box || previous?.pageBreaks != pageBreaks
    }
    @MainActor func apply(to view: PDFView, previous: ReaderSettings?, changedDocument: Bool) {
        let geometryChanged = layoutDiffers(from: previous)
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
    var onSelection: ((PDFAnnotation?) -> Void)?
    var onInkInserted: ((PDFAnnotation, PDFPage) -> Void)?
    var onAnnotationTransformed: ((PDFAnnotation, PDFAnnotationState) -> Void)?
    var onDeleteAnnotation: (() -> Void)?
    var documentUndoManager: UndoManager?
    override var undoManager: UndoManager? { documentUndoManager ?? super.undoManager }
    var selectedAnnotation: PDFAnnotation? { didSet { updateSelectionOverlay() } }
    private var annotationDrag: (annotation: PDFAnnotation, before: PDFAnnotationState, point: NSPoint, resizing: Bool)?
    private lazy var selectionOverlay = AnnotationSelectionOverlay(owner: self)
    private var drawingPage:PDFPage?
    private var path:NSBezierPath?
    private var preview:PDFAnnotation?
    override func mouseDown(with event:NSEvent) {
        let point = convert(event.locationInWindow,from:nil)
        guard let page = page(for:point,nearest:false) else { super.mouseDown(with: event); return }
        if !inkEnabled {
            let location = convert(point, to: page)
            if let annotation = page.annotation(at: location), EditableAnnotations.accepts(annotation) {
                selectedAnnotation = annotation; onSelection?(annotation); window?.makeFirstResponder(self)
                let radius = 9 / max(0.1, scaleFactor)
                let corner = NSPoint(x: annotation.bounds.maxX, y: annotation.bounds.minY)
                let resizing = abs(location.x - corner.x) <= radius && abs(location.y - corner.y) <= radius
                annotationDrag = (annotation, PDFAnnotationState(annotation), location, resizing)
                return
            }
            selectedAnnotation = nil; onSelection?(nil); super.mouseDown(with: event); return
        }
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
        if let drag = annotationDrag, let page = drag.annotation.page {
            let point = convert(convert(event.locationInWindow, from: nil), to: page)
            let dx = point.x - drag.point.x, dy = point.y - drag.point.y
            let crop = page.bounds(for: .cropBox), old = drag.before.bounds
            var rect = old
            if drag.resizing {
                rect.size.width = max(2, min(crop.maxX - old.minX, old.width + dx))
                rect.origin.y = min(old.maxY - 2, max(crop.minY, old.minY + dy)); rect.size.height = old.maxY - rect.minY
            } else {
                rect.origin.x = min(crop.maxX - old.width, max(crop.minX, old.minX + dx))
                rect.origin.y = min(crop.maxY - old.height, max(crop.minY, old.minY + dy))
            }
            drag.before.apply(to: drag.annotation); EditableAnnotations.resize(drag.annotation, to: rect)
            needsDisplay = true; updateSelectionOverlay(); return
        }
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
        if let drag = annotationDrag {
            annotationDrag = nil
            if drag.annotation.bounds != drag.before.bounds { onAnnotationTransformed?(drag.annotation, drag.before) }
            updateSelectionOverlay(); return
        }
        guard inkEnabled else { super.mouseUp(with:event); return }
        finishStroke()
    }
    override func viewWillMove(toWindow newWindow: NSWindow?) {
        if newWindow == nil { finishStroke() }
        super.viewWillMove(toWindow: newWindow)
    }
    func finishStroke() {
        let page = drawingPage, annotation = preview, stroke = path, count = path?.elementCount ?? 0
        drawingPage = nil; path = nil; preview = nil
        if let page, let annotation {
            if count < 2 { page.removeAnnotation(annotation) }
            else {
                // Tight bounds prevent an ink annotation from intercepting every click on the page.
                if let stroke {
                    let old = annotation.bounds
                    let padding = max(2, annotation.border?.lineWidth ?? 2.5)
                    let local = stroke.bounds.insetBy(dx: -padding, dy: -padding).intersection(CGRect(origin: .zero, size: old.size))
                    if !local.isNull, local.width > 0, local.height > 0 {
                        let transform = AffineTransform(translationByX: -local.minX, byY: -local.minY)
                        let paths = (annotation.paths ?? []).compactMap { $0.copy() as? NSBezierPath }
                        for existing in annotation.paths ?? [] { annotation.remove(existing) }
                        for path in paths { path.transform(using: transform); annotation.add(path) }
                        annotation.bounds = CGRect(x: old.minX + local.minX, y: old.minY + local.minY, width: local.width, height: local.height)
                    }
                }
                if let onInkInserted { onInkInserted(annotation, page) } else { onEdit?() }
            }
        }
    }
    override func keyDown(with event: NSEvent) {
        if selectedAnnotation != nil, [51, 117].contains(event.keyCode) { onDeleteAnnotation?(); return }
        super.keyDown(with: event)
    }
    override func cancelOperation(_ sender: Any?) {
        if let drag = annotationDrag { drag.before.apply(to: drag.annotation); annotationDrag = nil }
        selectedAnnotation = nil; onSelection?(nil); needsDisplay = true
    }
    private func updateSelectionOverlay() {
        if selectionOverlay.superview == nil { addSubview(selectionOverlay, positioned: .above, relativeTo: nil) }
        selectionOverlay.frame = bounds; selectionOverlay.autoresizingMask = [.width, .height]; selectionOverlay.needsDisplay = true
    }
}
