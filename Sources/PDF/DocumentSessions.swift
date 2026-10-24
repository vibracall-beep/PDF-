import SwiftUI
import AppKit
import PDFKit
import CryptoKit

@MainActor final class PDFDocumentSession: ObservableObject, Identifiable {
    let id: UUID
    @Published var document: PDFDocument
    @Published var sourceURL: URL?
    @Published var savedURL: URL?
    @Published var displayTitle: String?
    @Published var page = 1
    @Published var zoom = 1.0
    @Published var autoScale = true
    @Published var bookmarks: Set<Int> = []
    @Published var isDirty = false
    var hasEdits = false
    var annotationRevision = 0
    var originalWidgetState: String
    /// Used solely in memory to encrypt recovery copies; never written into preferences or metadata.
    var password: String?
    /// The document retains its original protection proof internally. This flag
    /// records an encrypted reader compatibility copy without replacing its URL
    /// or the user's original in-memory password with an internal credential.
    let usedCompatibilityCopy: Bool
    /// SHA-256 of the immutable bytes used by a verified-source opening. This
    /// describes the initial source, not subsequent unsaved annotation edits.
    let sourceFingerprint: String?
    let history = AnnotationHistory()
    var recoveryTask: Task<Void, Never>?
    var recoveryWrite: Task<RecoveryRecord?, Error>?
    private(set) var recoveryTaskID: UUID?
    var recoveryRecord: RecoveryRecord?
    var recoveryFingerprint = ""
    var recoveryContentFingerprint = ""
    var lastRecoveryDate = Date.distantPast
    var title: String { savedURL?.lastPathComponent ?? displayTitle ?? sourceURL?.lastPathComponent ?? "Documento sem título" }
    @discardableResult func beginRecoveryTask() -> UUID {
        cancelRecoveryTask()
        let token = UUID(); recoveryTaskID = token; return token
    }
    func finishRecoveryTask(_ token: UUID) {
        guard recoveryTaskID == token else { return }
        recoveryTask = nil; recoveryWrite = nil; recoveryTaskID = nil
    }
    func cancelRecoveryTask() {
        recoveryTaskID = nil
        recoveryTask?.cancel(); recoveryWrite?.cancel()
        recoveryTask = nil; recoveryWrite = nil
    }
    init(id: UUID = UUID(), document: PDFDocument, sourceURL: URL?, password: String? = nil, usedCompatibilityCopy: Bool = false, sourceFingerprint: String? = nil) {
        self.id = id; self.document = document; self.sourceURL = sourceURL; self.password = password
        self.usedCompatibilityCopy = usedCompatibilityCopy
        self.sourceFingerprint = sourceFingerprint
        originalWidgetState = Self.widgetState(document)
    }
    static func widgetState(_ document: PDFDocument) -> String {
        // Swift String equality normalizes canonically equivalent sequences.
        // Frame the original UTF-8 bytes before hashing so field edits retain
        // their exact codepoints and embedded separators cannot collide.
        var digest = SHA256()
        func append(_ value: String) {
            let bytes = Data(value.utf8)
            var length = UInt64(bytes.count).bigEndian
            withUnsafeBytes(of: &length) { digest.update(bufferPointer: $0) }
            digest.update(data: bytes)
        }
        func appendOptional(_ value: String?) {
            append(value == nil ? "0" : "1"); append(value ?? "")
        }
        for index in 0..<document.pageCount {
            for (position, annotation) in (document.page(at: index)?.annotations ?? []).enumerated() {
                if PDFAnnotationKind.matches(annotation, .widget) || annotation.fieldName != nil {
                    append(String(index)); append(String(position))
                    appendOptional(annotation.fieldName); appendOptional(annotation.widgetStringValue)
                    append(String(annotation.buttonWidgetState.rawValue))
                }
            }
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }
    @discardableResult func refreshDirty() -> Bool {
        let value = hasEdits || Self.widgetState(document) != originalWidgetState
        if isDirty != value { isDirty = value }
        return value
    }
    func recoveryPrepared() throws -> NativePDFSerialization.Prepared {
        guard !document.isLocked else { throw recoveryError("Desbloqueie o documento para manter uma recuperação das alterações.") }
        if document.isEncrypted {
            guard let password, !password.isEmpty else { throw recoveryError("Salve uma cópia protegida com senha para habilitar a recuperação deste PDF. Nenhuma cópia sem proteção será gravada.") }
            return try NativePDFSerialization.prepare(document: document, password: password)
        }
        return try NativePDFSerialization.prepare(document: document)
    }
    func recoveryData() throws -> Data {
        try NativePDFSerialization.finish(recoveryPrepared())
    }
    private func recoveryError(_ description: String) -> NSError { NSError(domain: "PDF.Recovery", code: 20, userInfo: [NSLocalizedDescriptionKey: description]) }
}

/// Independent page/zoom state, while annotations and form values belong to the reference session.
struct SessionComparisonReader: NSViewRepresentable {
    @ObservedObject var session: PDFDocumentSession
    @AppStorage("readerDirection") private var direction = "vertical"
    @AppStorage("readerDisplayBox") private var box = "crop"
    @AppStorage("readerPageBackground") private var background = "#E8E9EF"
    @AppStorage("readerDisplayPageBreaks") private var pageBreaks = true
    var mode: Int
    func makeCoordinator() -> Coordinator { Coordinator(session: session) }
    func makeNSView(context: Context) -> PDFView {
        let view = PDFView(); view.setAccessibilityLabel("Documento de referência"); view.setAccessibilityIdentifier("pdf.reader.reference")
        view.displayMode = .singlePageContinuous; view.autoScales = session.autoScale
        context.coordinator.observe(view)
        return view
    }
    func updateNSView(_ view: PDFView, context: Context) {
        let coordinator = context.coordinator
        coordinator.session = session
        let changedDocument = view.document !== session.document
        if changedDocument { view.document = session.document; coordinator.page = nil }
        // Layout preferences are shared with the primary reader. Page, zoom and
        // automatic fitting continue to belong to this reference session.
        let settings = ReaderSettings(mode: mode, direction: direction, box: box, background: background,
                                      autoScale: session.autoScale, zoom: session.zoom, pageBreaks: pageBreaks)
        settings.apply(to: view, previous: coordinator.settings, changedDocument: changedDocument)
        coordinator.settings = settings
        if coordinator.page != session.page, let page = session.document.page(at: max(0, min(session.document.pageCount - 1, session.page - 1))) {
            view.go(to: page); coordinator.page = session.page
        }
    }
    final class Coordinator {
        var session: PDFDocumentSession
        var observers: [NSObjectProtocol] = []
        var page: Int?
        var settings: ReaderSettings?
        init(session: PDFDocumentSession) { self.session = session }
        func observe(_ view: PDFView) {
            observers.append(NotificationCenter.default.addObserver(forName: .PDFViewPageChanged, object: view, queue: .main) { [weak view, weak self] _ in
                guard let view, let page = view.currentPage else { return }
                Task { @MainActor in
                    guard let self, view.document === self.session.document else { return }
                    let index = self.session.document.index(for: page)
                    if index != NSNotFound { self.page = index + 1; self.session.page = index + 1 }
                }
            })
            observers.append(NotificationCenter.default.addObserver(forName: .PDFViewScaleChanged, object: view, queue: .main) { [weak view, weak self] _ in
                guard let view else { return }
                Task { @MainActor in
                    guard let self, view.document === self.session.document else { return }
                    let zoom = Double(view.scaleFactor)
                    if zoom.isFinite, zoom > 0 { self.session.zoom = min(8, max(0.1, zoom)) }
                    self.session.autoScale = view.autoScales
                }
            })
        }
        deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }
    }
}
