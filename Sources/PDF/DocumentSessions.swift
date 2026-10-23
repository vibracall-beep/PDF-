import SwiftUI
import AppKit
import PDFKit

@MainActor final class PDFDocumentSession: ObservableObject, Identifiable {
    let id: UUID
    @Published var document: PDFDocument
    @Published var sourceURL: URL?
    @Published var savedURL: URL?
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
    let history = AnnotationHistory()
    var recoveryTask: Task<Void, Never>?
    var recoveryWrite: Task<Void, Error>?
    var recoveryFingerprint = ""
    var recoveryContentFingerprint = ""
    var lastRecoveryDate = Date.distantPast
    var title: String { (savedURL ?? sourceURL)?.lastPathComponent ?? "Documento sem título" }
    init(id: UUID = UUID(), document: PDFDocument, sourceURL: URL?, password: String? = nil) {
        self.id = id; self.document = document; self.sourceURL = sourceURL; self.password = password
        originalWidgetState = Self.widgetState(document)
    }
    static func widgetState(_ document: PDFDocument) -> String {
        var values: [String] = []
        for index in 0..<document.pageCount {
            for (position, annotation) in (document.page(at: index)?.annotations ?? []).enumerated() {
                if PDFAnnotationKind.matches(annotation, .widget) || annotation.fieldName != nil {
                    let value = annotation.widgetStringValue ?? ""
                    values.append("\(index):\(position):\(annotation.fieldName ?? ""): \(value.utf8.count):\(value):\(annotation.buttonWidgetState.rawValue)")
                }
            }
        }
        return values.joined(separator: "\n")
    }
    @discardableResult func refreshDirty() -> Bool {
        let value = hasEdits || Self.widgetState(document) != originalWidgetState
        if isDirty != value { isDirty = value }
        return value
    }
    func recoveryData() throws -> Data {
        guard !document.isLocked else { throw recoveryError("Desbloqueie o documento para manter uma recuperação das alterações.") }
        let result: Data?
        if document.isEncrypted {
            guard let password, !password.isEmpty else { throw recoveryError("Salve uma cópia protegida com senha para habilitar a recuperação deste PDF. Nenhuma cópia sem proteção será gravada.") }
            result = document.dataRepresentation(options: [AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): password,
                AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): password])
            guard let result, let verified = PDFDocument(data: result), verified.isEncrypted, verified.isLocked,
                  !verified.unlock(withPassword: ""), verified.unlock(withPassword: password) else {
                throw recoveryError("Não foi possível confirmar a criptografia da recuperação. O original permanece intacto.")
            }
        } else { result = document.dataRepresentation() }
        guard let result else { throw recoveryError("Não foi possível capturar o documento para recuperação.") }
        return result
    }
    private func recoveryError(_ description: String) -> NSError { NSError(domain: "PDF.Recovery", code: 20, userInfo: [NSLocalizedDescriptionKey: description]) }
}

/// Independent page/zoom state, while annotations and form values belong to the reference session.
struct SessionComparisonReader: NSViewRepresentable {
    @ObservedObject var session: PDFDocumentSession
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
        if view.document !== session.document { view.document = session.document; coordinator.page = nil; coordinator.zoom = nil }
        let display: PDFDisplayMode = mode == 1 ? .singlePage : mode == 2 ? .twoUpContinuous : .singlePageContinuous
        if view.displayMode != display { view.displayMode = display }
        if coordinator.autoScale != session.autoScale { view.autoScales = session.autoScale; coordinator.autoScale = session.autoScale }
        if !session.autoScale, coordinator.zoom != session.zoom { view.scaleFactor = CGFloat(min(8, max(0.1, session.zoom))); coordinator.zoom = session.zoom }
        if coordinator.page != session.page, let page = session.document.page(at: max(0, min(session.document.pageCount - 1, session.page - 1))) {
            view.go(to: page); coordinator.page = session.page
        }
    }
    final class Coordinator {
        var session: PDFDocumentSession
        var observers: [NSObjectProtocol] = []
        var page: Int?
        var zoom: Double?
        var autoScale: Bool?
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
                    self.zoom = Double(view.scaleFactor); self.session.zoom = self.zoom ?? 1; self.session.autoScale = view.autoScales
                }
            })
        }
        deinit { for observer in observers { NotificationCenter.default.removeObserver(observer) } }
    }
}
