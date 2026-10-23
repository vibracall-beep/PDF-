import AppKit
import PDFKit

enum AnnotationDiagnostics {
    static func trace(_ phase: String) {
        guard CommandLine.arguments.contains("--render-preview") else { return }
        CIDiagnostics.record(phase, title: "PDF annotation preview")
    }
}

/// `PDFAnnotation.type` exposes names such as "Text"; subtype constants can
/// carry the PDF name prefix ("/Text"). Compare their names, not raw strings.
enum PDFAnnotationKind {
    static func normalizedName(_ value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        let name = value.hasPrefix("/") ? String(value.dropFirst()) : value
        return name.isEmpty ? nil : name
    }
    static func matches(_ annotation: PDFAnnotation, _ subtype: PDFAnnotationSubtype) -> Bool {
        guard let actual = normalizedName(annotation.type), let expected = normalizedName(subtype.rawValue) else { return false }
        return actual == expected
    }
    static func matchesAny(_ annotation: PDFAnnotation, _ subtypes: [PDFAnnotationSubtype]) -> Bool {
        subtypes.contains { matches(annotation, $0) }
    }
    static func hasQuadrilaterals(_ annotation: PDFAnnotation) -> Bool {
        matchesAny(annotation, [.highlight, .underline, .strikeOut])
    }
}

struct PDFAnnotationState {
    let bounds: CGRect
    let color: NSColor
    let width: CGFloat
    let contents: String?
    let paths: [NSBezierPath]
    let quadrilaterals: [NSValue]?
    let startPoint: NSPoint
    let endPoint: NSPoint
    let fontColor: NSColor?
    init(_ annotation: PDFAnnotation) {
        bounds = annotation.bounds; color = annotation.color; width = annotation.border?.lineWidth ?? 1
        contents = annotation.contents
        // These PDFKit properties belong to specific subtypes. Asking FreeText
        // or Line for QuadPoints can produce invalid dictionary values on newer
        // PDFKit versions even when an in-memory state check appears to pass.
        paths = PDFAnnotationKind.matches(annotation, .ink) ? (annotation.paths ?? []).compactMap { $0.copy() as? NSBezierPath } : []
        quadrilaterals = PDFAnnotationKind.hasQuadrilaterals(annotation) ? annotation.quadrilateralPoints : nil
        startPoint = PDFAnnotationKind.matches(annotation, .line) ? annotation.startPoint : .zero
        endPoint = PDFAnnotationKind.matches(annotation, .line) ? annotation.endPoint : .zero
        fontColor = PDFAnnotationKind.matches(annotation, .freeText) ? annotation.fontColor : nil
    }
    func apply(to annotation: PDFAnnotation) {
        annotation.bounds = bounds; annotation.color = color; annotation.contents = contents
        let border = annotation.border ?? PDFBorder(); border.lineWidth = width; annotation.border = border
        if PDFAnnotationKind.matches(annotation, .freeText) { annotation.fontColor = fontColor }
        if PDFAnnotationKind.hasQuadrilaterals(annotation) {
            if let quadrilaterals, !quadrilaterals.isEmpty { annotation.quadrilateralPoints = quadrilaterals }
            else {
                // Nil means the annotation uses its bounds, not an empty PDF
                // array. Remove a stale key instead of asking PDFKit to encode nil.
                annotation.removeValue(forAnnotationKey: PDFAnnotationKey(rawValue: "/QuadPoints"))
            }
        }
        if PDFAnnotationKind.matches(annotation, .line) { annotation.startPoint = startPoint; annotation.endPoint = endPoint }
        if PDFAnnotationKind.matches(annotation, .ink) {
            for existing in annotation.paths ?? [] { annotation.remove(existing) }
            for path in paths { if let copy = path.copy() as? NSBezierPath { annotation.add(copy) } }
        }
    }
}

enum EditableAnnotations {
    static let types: [PDFAnnotationSubtype] = [.highlight, .underline, .strikeOut, .text, .freeText, .square, .circle, .ink, .line]
    static func accepts(_ annotation: PDFAnnotation) -> Bool { PDFAnnotationKind.matchesAny(annotation, types) }
    static func validate(_ bounds: CGRect, on page: PDFPage) throws {
        let values = [bounds.minX, bounds.minY, bounds.width, bounds.height]
        guard values.allSatisfy(\.isFinite), bounds.width >= 2, bounds.height >= 2,
              page.bounds(for: .cropBox).insetBy(dx: -0.01, dy: -0.01).contains(bounds) else {
            throw NSError(domain: "PDF.Annotation", code: 1, userInfo: [NSLocalizedDescriptionKey: "Mantenha a anotação dentro da página, com largura e altura de ao menos 2 pontos."])
        }
    }
    static func resize(_ annotation: PDFAnnotation, to bounds: CGRect) {
        let previous = annotation.bounds
        let markup = PDFAnnotationKind.hasQuadrilaterals(annotation)
        let line = PDFAnnotationKind.matches(annotation, .line)
        let ink = PDFAnnotationKind.matches(annotation, .ink)
        // Capture relative geometry before changing bounds. Write transformed
        // points only after the new origin is in place so PDFKit can serialize
        // them into the correct absolute page-space coordinates.
        let points = markup ? annotation.quadrilateralPoints : nil
        let start = line ? annotation.startPoint : .zero
        let end = line ? annotation.endPoint : .zero
        let paths = ink ? (annotation.paths ?? []).compactMap { $0.copy() as? NSBezierPath } : []
        annotation.bounds = bounds
        guard previous.width > 0, previous.height > 0 else { return }
        func scaled(_ point: NSPoint) -> NSPoint { NSPoint(x: point.x * bounds.width / previous.width, y: point.y * bounds.height / previous.height) }
        if let points, !points.isEmpty { annotation.quadrilateralPoints = points.map { NSValue(point: scaled($0.pointValue)) } }
        if line { annotation.startPoint = scaled(start); annotation.endPoint = scaled(end) }
        if ink {
            let transform = AffineTransform(scaleByX: bounds.width / previous.width, byY: bounds.height / previous.height)
            for existing in annotation.paths ?? [] { annotation.remove(existing) }
            for path in paths { path.transform(using: transform); annotation.add(path) }
        }
    }
}

/// Undo belongs to a document session; switching tabs never redirects an undo to another PDF.
@MainActor final class AnnotationHistory: NSObject {
    let undoManager = UndoManager()
    var onChange: (() -> Void)?
    override init() { super.init(); undoManager.levelsOfUndo = 100; undoManager.groupsByEvent = false }
    private func registration(name: String, _ body: () -> Void) {
        let ownGroup = undoManager.groupingLevel == 0 && !undoManager.isUndoing && !undoManager.isRedoing
        if ownGroup { undoManager.beginUndoGrouping() }
        body()
        // With groupsByEvent disabled, name the active registration group before closing it.
        // An enclosing selection operation or UndoManager itself owns all other groups.
        AnnotationDiagnostics.trace("history.registration: active group action name begin")
        undoManager.setActionName(name)
        AnnotationDiagnostics.trace("history.registration: active group action name end")
        if ownGroup { undoManager.endUndoGrouping() }
    }
    func inserted(_ annotation: PDFAnnotation, on page: PDFPage, name: String) {
        AnnotationDiagnostics.trace("history.inserted: undo registration begin")
        registration(name: name) { undoManager.registerUndo(withTarget: self) { target in MainActor.assumeIsolated { target.remove(annotation, from: page, name: name) } } }
        AnnotationDiagnostics.trace("history.inserted: undo registration end; onChange begin")
        onChange?()
        AnnotationDiagnostics.trace("history.inserted: onChange end")
    }
    func remove(_ annotation: PDFAnnotation, from page: PDFPage, name: String = "Excluir anotação") {
        page.removeAnnotation(annotation)
        registration(name: name) { undoManager.registerUndo(withTarget: self) { target in
            MainActor.assumeIsolated { page.addAnnotation(annotation); target.inserted(annotation, on: page, name: name) }
        } }
        onChange?()
    }
    func changed(_ annotation: PDFAnnotation, before: PDFAnnotationState, name: String = "Editar anotação") {
        registration(name: name) { undoManager.registerUndo(withTarget: self) { target in MainActor.assumeIsolated { target.restore(annotation, state: before, name: name) } } }
        onChange?()
    }
    private func restore(_ annotation: PDFAnnotation, state: PDFAnnotationState, name: String) {
        let current = PDFAnnotationState(annotation); state.apply(to: annotation)
        changed(annotation, before: current, name: name)
    }
}

/// A transparent overlay displays selection without intercepting PDFKit text or form input.
final class AnnotationSelectionOverlay: NSView {
    weak var owner: DrawingPDFView?
    init(owner: DrawingPDFView) { self.owner = owner; super.init(frame: owner.bounds) }
    required init?(coder: NSCoder) { super.init(coder: coder) }
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func draw(_ dirtyRect: NSRect) {
        guard let owner, let annotation = owner.selectedAnnotation, let page = annotation.page else { return }
        let rect = owner.convert(annotation.bounds, from: page)
        NSColor.controlAccentColor.setStroke()
        let border = NSBezierPath(rect: rect); border.lineWidth = 1.5; border.stroke()
        NSColor.controlAccentColor.setFill()
        NSBezierPath(rect: NSRect(x: rect.maxX - 4, y: rect.minY - 4, width: 8, height: 8)).fill()
    }
}
