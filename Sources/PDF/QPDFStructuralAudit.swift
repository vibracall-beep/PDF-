import Foundation
import AppKit
import PDFKit
import Darwin
import CryptoKit

/// An independent, strict check of the exact bytes the product will publish.
/// This auditor never rewrites its input. qpdf may recover data in memory while
/// checking it, but warnings (exit 3) never count as a successful output audit.
enum QPDFStructuralAudit {
    private static let executable = URL(fileURLWithPath: "/opt/homebrew/bin/qpdf")

    static func check(_ data: Data, password: String? = nil, phase: String) throws {
        log("\(phase): begin")
        let status = try run(data, password: password)
        guard status == 0 else {
            throw failure("\(phase): qpdf --check recusou os bytes gerados (status \(status); avisos também são falha).")
        }
        log("\(phase): passed; qpdf --check exit 0")
    }

    /// Keep the platform defect visible without confusing the raw framework
    /// bytes with the output returned by the application's serialization path.
    /// A status-3 raw fixture remains a failure in this diagnostic; only check()
    /// can approve final product bytes, and it requires status 0.
    @discardableResult
    static func recordRawPDFKit(_ data: Data, password: String? = nil, phase: String) throws -> Int32 {
        let status = try run(data, password: password)
        guard [0, 2, 3].contains(status) else {
            throw failure("\(phase): diagnóstico dos bytes PDFKit terminou com status inesperado \(status).")
        }
        log("raw PDFKit \(phase): \(status == 0 ? "valid" : "FAILED"); qpdf --check exit \(status); diagnostic only, not the product output")
        return status
    }

    /// Prove that the checker rejects the exact stream-length defect under
    /// investigation, with unchanged byte offsets and otherwise valid PDF data.
    static func verifyCorruptionDetection() throws {
        let fixture = streamFixture()
        try check(fixture.valid, phase: "stream-length control fixture")
        guard fixture.valid.count == fixture.corrupted.count else {
            throw failure("A amostra de comprimento inválido alterou os offsets do PDF.")
        }
        log("invalid stream-length control: begin")
        let status = try run(fixture.corrupted, password: nil)
        guard status == 2 || status == 3 else {
            throw failure("O verificador não recusou o stream com comprimento inválido (status \(status)).")
        }
        log("invalid stream-length control: correctly rejected with status \(status)")
        let repaired = try NativePDFSerialization.normalize(data: fixture.corrupted)
        try check(repaired, phase: "production normalization of recoverable stream length")
        guard let original = PDFDocument(data: fixture.valid), let result = PDFDocument(data: repaired),
              result.pageCount == original.pageCount, result.string == original.string,
              result.page(at: 0)?.bounds(for: .mediaBox) == original.page(at: 0)?.bounds(for: .mediaBox) else {
            throw failure("A normalização da amostra corrompida perdeu texto ou geometria.")
        }
    }

    @MainActor
    static func verifyFidelityGuards(copy: Data, prepared: NativePDFSerialization.Prepared,
                                     protected: Data, protectedPrepared: NativePDFSerialization.Prepared) throws {
        // Positive controls use the same immutable baseline as production.
        try NativePDFSerialization.verifyFidelity(data: copy, prepared: prepared)
        try NativePDFSerialization.verifyFidelity(data: protected, prepared: protectedPrepared)
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: copy, prepared: protectedPrepared) },
                    "A verificação de fidelidade aceitou remover a criptografia.")
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: protected, prepared: prepared) },
                    "A verificação de fidelidade aceitou mudar a proteção sem solicitação.")

        guard let changedWidget = PDFDocument(data: copy),
              let widget = changedWidget.page(at: 0)?.annotations.first(where: { $0.fieldName == "native-test" }) else {
            throw failure("A amostra de formulário para auditoria não pôde ser aberta.")
        }
        widget.widgetStringValue = "Altered audit value"
        let widgetBytes = try NativePDFSerialization.serialize(document: changedWidget)
        try check(widgetBytes, phase: "valid PDF with deliberately changed widget")
        guard PDFDocument(data: widgetBytes)?.page(at: 0)?.annotations.contains(where: {
                  $0.fieldName == "native-test" && $0.widgetStringValue == "Altered audit value"
              }) == true else { throw failure("A amostra adulterada não persistiu a mudança real de formulário.") }
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: widgetBytes, prepared: prepared) },
                    "A verificação de fidelidade aceitou alterar um campo preenchido.")

        guard let changedGeometry = PDFDocument(data: copy), let changedPage = changedGeometry.page(at: 0) else {
            throw failure("A amostra de geometria não pôde ser aberta.")
        }
        let crop = changedPage.bounds(for: .cropBox).insetBy(dx: 10, dy: 10)
        changedPage.setBounds(crop, for: .cropBox)
        let geometryBytes = try NativePDFSerialization.serialize(document: changedGeometry)
        try check(geometryBytes, phase: "valid PDF with deliberately changed CropBox")
        guard PDFDocument(data: geometryBytes)?.page(at: 0)?.bounds(for: .cropBox) == crop else {
            throw failure("A amostra adulterada não persistiu a mudança real de CropBox.")
        }
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: geometryBytes, prepared: prepared) },
                    "A verificação de fidelidade aceitou alterar a área visível da página.")

        // Change only an equal-length word in a structurally valid, uncompressed
        // PDF. This checks text loss independently of fields or page geometry.
        let fixture = streamFixture().valid
        guard let textDocument = PDFDocument(data: fixture) else { throw failure("A amostra textual é inválida.") }
        let textPrepared = try NativePDFSerialization.prepare(document: textDocument)
        try NativePDFSerialization.verifyFidelity(data: fixture, prepared: textPrepared)
        let alteredText = Data(String(decoding: fixture, as: UTF8.self)
            .replacingOccurrences(of: "PDF structural verification", with: "PDF fabricated verification").utf8)
        try require(alteredText.count == fixture.count &&
                    (PDFDocument(data: alteredText)?.string ?? "").contains("fabricated"),
                    "A amostra de alteração textual não mudou o texto mantendo os offsets.")
        try check(alteredText, phase: "valid PDF with deliberately changed text")
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: alteredText, prepared: textPrepared) },
                    "A verificação de fidelidade aceitou texto diferente em um PDF estruturalmente válido.")
        log("fidelity guards: changed text, CropBox, widget and encryption correctly rejected")
    }

    /// Real PDFKit objects cover the defaults that a strict semantic snapshot
    /// can otherwise mistake for data loss when the writer materializes them.
    @MainActor
    static func verifyEditableRoundTrips() throws {
        guard let document = PDFDocument(data: streamFixture().valid), let page = document.page(at: 0) else {
            throw failure("A amostra de anotações não pôde ser criada.")
        }
        let types = EditableAnnotations.types
        for (index, type) in types.enumerated() {
            let annotation = PDFAnnotation(bounds: CGRect(x: 60, y: CGFloat(650 - index * 45), width: 140, height: 30),
                                           forType: type, withProperties: nil)
            annotation.contents = "Annotation \(index)"
            if type == .ink {
                let path = NSBezierPath()
                path.move(to: CGPoint(x: 4, y: 5)); path.line(to: CGPoint(x: 35, y: 20))
                path.line(to: CGPoint(x: 50, y: 25)); path.line(to: CGPoint(x: 90, y: 5)); path.line(to: CGPoint(x: 120, y: 15))
                annotation.add(path)
                let second = NSBezierPath()
                second.move(to: CGPoint(x: 10, y: 25)); second.line(to: CGPoint(x: 40, y: 8)); second.line(to: CGPoint(x: 80, y: 22))
                annotation.add(second)
            } else if type == .line {
                annotation.startPoint = CGPoint(x: 5, y: 5); annotation.endPoint = CGPoint(x: 130, y: 25)
            } else if [PDFAnnotationSubtype.highlight, .underline, .strikeOut].contains(type) {
                annotation.quadrilateralPoints = [NSPoint(x: 0, y: 30), NSPoint(x: 140, y: 30),
                                                   .zero, NSPoint(x: 140, y: 0)].map(NSValue.init(point:))
            }
            // Leave font/border/control defaults implicit where the public UI
            // and imported annotations legitimately permit them.
            page.addAnnotation(annotation)
        }
        let text = PDFAnnotation(bounds: CGRect(x: 260, y: 610, width: 230, height: 35), forType: .widget, withProperties: nil)
        text.widgetFieldType = .text; text.fieldName = "roundtrip-text"; text.widgetStringValue = "Editable field"
        page.addAnnotation(text)
        let choice = PDFAnnotation(bounds: CGRect(x: 260, y: 540, width: 230, height: 55), forType: .widget, withProperties: nil)
        choice.widgetFieldType = .choice; choice.fieldName = "roundtrip-choice"
        choice.choices = ["First label", "Second label"]; choice.values = ["first", "second"]
        choice.isListChoice = true; choice.widgetStringValue = "second"
        page.addAnnotation(choice)
        let checkbox = PDFAnnotation(bounds: CGRect(x: 260, y: 480, width: 25, height: 25), forType: .widget, withProperties: nil)
        checkbox.widgetFieldType = .button; checkbox.widgetControlType = .checkBoxControl
        checkbox.fieldName = "roundtrip-checkbox"; checkbox.buttonWidgetStateString = "Yes"
        checkbox.buttonWidgetState = PDFWidgetCellState(rawValue: 1)!
        page.addAnnotation(checkbox)

        let originalNote = try findAnnotation(page, .text)
        let noteAnchor = CGPoint(x: originalNote.bounds.minX, y: originalNote.bounds.maxY)
        let originalText = try findAnnotation(page, .freeText)
        guard let originalFont = originalText.font else { throw failure("A anotação de texto não expôs a fonte efetiva.") }
        let originalFontColor = originalText.fontColor
        let textColor = text.value(forKey: "color") as? NSColor
        let choiceColor = choice.value(forKey: "color") as? NSColor
        try require((text.widgetDefaultStringValue ?? "").isEmpty && (choice.widgetDefaultStringValue ?? "").isEmpty,
                    "A amostra precisa começar com valores de redefinição vazios e valores atuais preenchidos.")
        var plainBytes: Data?
        let passwords: [String?] = [nil, "roundtrip-protected-123"]
        for password in passwords {
            let prepared = try NativePDFSerialization.prepare(document: document, password: password)
            try recordRawPDFKit(prepared.data, password: prepared.inputPassword,
                                phase: password == nil ? "editable defaults unencrypted" : "editable defaults protected")
            let bytes = try NativePDFSerialization.finish(prepared)
            try check(bytes, password: password, phase: "published editable annotations and fields")
            if let password {
                try require(PDFDocument(data: bytes)?.isLocked == true && rejects {
                    _ = try NativePDFSerialization.open(data: bytes, password: "")
                },
                            "O roundtrip de anotações perdeu a proteção por senha.")
                try verifyAES256(bytes, password: password)
            }
            let result = try NativePDFSerialization.open(data: bytes, password: password)
            guard let restored = result.page(at: 0) else { throw failure("A cópia de anotações perdeu sua página.") }
            // PDFKit may create/omit the note's closed, inherited popup. It
            // must not hide any independently authored or open annotation.
            let editable = restored.annotations.filter { item in
                types.contains { PDFAnnotationKind.matches(item, $0) } || PDFAnnotationKind.matches(item, .widget)
            }
            let extras = restored.annotations.filter { item in !editable.contains { $0 === item } }
            try require(result.pageCount == 1 && editable.count == types.count + 3 && extras.allSatisfy { popup in
                PDFAnnotationKind.matches(popup, .popup) && !popup.isOpen && restored.annotations.contains { parent in
                    PDFAnnotationKind.matches(parent, .text) && parent.popup === popup &&
                        ((popup.contents ?? "").isEmpty || (popup.contents ?? "").utf8.elementsEqual((parent.contents ?? "").utf8))
                }
            },
                        "O roundtrip perdeu ou duplicou anotações/campos.")
            for (index, type) in types.enumerated() {
                try require(restored.annotations.filter {
                    PDFAnnotationKind.matches($0, type) && $0.contents == "Annotation \(index)"
                }.count == 1, "O roundtrip perdeu ou duplicou um tipo editável ou seu conteúdo.")
            }
            try require(restored.annotations.contains { $0.fieldName == "roundtrip-text" && $0.widgetStringValue == "Editable field" },
                        "O roundtrip perdeu o valor do campo de texto.")
            // macOS 26 returns "Second label" from widgetStringValue for this
            // encrypted fixture while the actual /V remains the export
            // "second". Check the persisted export independently with qpdf;
            // retain PDFKit checks for labels, exports and the list control.
            let restoredList = try findAnnotation(restored, .widget, field: "roundtrip-choice")
            try require(restoredList.choices == ["First label", "Second label"] &&
                        restoredList.values == ["first", "second"] && restoredList.isListChoice,
                        "O roundtrip perdeu rótulos, valores ou o tipo de controle da lista.")
            try verifyChoiceExport(bytes, password: password, expected: "second")
            try require(restored.annotations.contains {
                $0.fieldName == "roundtrip-checkbox" && $0.widgetControlType == .checkBoxControl &&
                    $0.buttonWidgetState.rawValue == 1 && $0.buttonWidgetStateString == "Yes"
            }, "O roundtrip perdeu o estado marcado do checkbox.")
            let restoredNote = try findAnnotation(restored, .text)
            try require(restoredNote.bounds.minX == noteAnchor.x && restoredNote.bounds.maxY == noteAnchor.y,
                        "O roundtrip deslocou a âncora da nota ao materializar o ícone PDFKit.")
            let restoredText = try findAnnotation(restored, .freeText)
            try require(restoredText.font?.fontName == originalFont.fontName && restoredText.font?.pointSize == originalFont.pointSize &&
                        sameColor(restoredText.fontColor, originalFontColor),
                        "O roundtrip alterou a fonte efetiva, seu tamanho ou sua cor.")
            let restoredField = try findAnnotation(restored, .widget, field: "roundtrip-text")
            let restoredChoice = try findAnnotation(restored, .widget, field: "roundtrip-choice")
            try require((restoredField.widgetDefaultStringValue ?? "").isEmpty &&
                        (restoredChoice.widgetDefaultStringValue ?? "").isEmpty,
                        "O roundtrip substituiu a redefinição vazia pelo valor atualmente preenchido.")
            try require(sameColor(restoredField.value(forKey: "color") as? NSColor, textColor) &&
                        sameColor(restoredChoice.value(forKey: "color") as? NSColor, choiceColor),
                        "O roundtrip alterou a ausência ou o valor da cor de um campo.")
            try require((text.widgetDefaultStringValue ?? "").isEmpty && (choice.widgetDefaultStringValue ?? "").isEmpty &&
                        originalText.font?.fontName == originalFont.fontName && originalText.font?.pointSize == originalFont.pointSize,
                        "Preparar a cópia modificou a semântica dos valores ou da fonte no documento aberto.")
            let changedSelection = try NativePDFSerialization.open(data: bytes, password: password)
            guard let changedPage = changedSelection.page(at: 0) else { throw failure("A amostra de seleção perdeu a página.") }
            try findAnnotation(changedPage, .widget, field: "roundtrip-choice").widgetStringValue = "first"
            let changedBytes = try NativePDFSerialization.serialize(document: changedSelection, password: password)
            try check(changedBytes, password: password, phase: "changed exported list selection")
            try verifyChoiceExport(changedBytes, password: password, expected: "first")
            try require(rejects { try NativePDFSerialization.verifyFidelity(data: changedBytes, prepared: prepared) },
                        "A verificação aceitou uma alteração real da seleção exportada da lista.")
            if password == nil { plainBytes = bytes }
        }
        guard let plainBytes else { throw failure("A amostra editável sem senha não foi exercitada.") }
        try verifyExplicitAnnotationGuards(base: plainBytes)
        log("editable roundtrip: all \(types.count) supported annotation types and text/choice/checkbox preserved, plain and encrypted")
    }

    @MainActor
    private static func verifyExplicitAnnotationGuards(base: Data) throws {
        guard let document = PDFDocument(data: base), let page = document.page(at: 0),
              let font = NSFont(name: "Helvetica", size: 17), let otherFont = NSFont(name: "Courier", size: 17) else {
            throw failure("A amostra de propriedades explícitas não pôde ser criada.")
        }
        let annotation = try findAnnotation(page, .freeText)
        annotation.font = font
        annotation.fontColor = NSColor(srgbRed: 0.2, green: 0.4, blue: 0.6, alpha: 1)
        let border = PDFBorder(); border.lineWidth = 2; annotation.border = border
        let note = try findAnnotation(page, .text)
        note.color = NSColor(srgbRed: 0.1, green: 0.7, blue: 0.3, alpha: 1)
        try findAnnotation(page, .widget, field: "roundtrip-text").widgetDefaultStringValue = "Reset field"
        try findAnnotation(page, .widget, field: "roundtrip-choice").widgetDefaultStringValue = "first"
        let popup = PDFAnnotation(bounds: CGRect(x: 330, y: 100, width: 140, height: 90), forType: .popup, withProperties: nil)
        popup.contents = "Independent popup contents"; popup.isOpen = true
        try require(popup.setValue(NSNumber(value: 4), forAnnotationKey: PDFAnnotationKey(rawValue: "/F")),
                    "A amostra de Popup não aceitou o flag de impressão explícito.")
        page.addAnnotation(popup)
        let prepared = try NativePDFSerialization.prepare(document: document)
        let bytes = try NativePDFSerialization.finish(prepared)
        try check(bytes, phase: "explicit font, reset defaults and independent popup")
        guard let reopened = PDFDocument(data: bytes), let restored = reopened.page(at: 0) else {
            throw failure("A amostra explícita não pôde ser reaberta.")
        }
        let restoredText = try findAnnotation(restored, .freeText)
        try require(restoredText.font?.fontName == font.fontName && restoredText.font?.pointSize == 17 &&
                    sameColor(restoredText.fontColor, annotation.fontColor) && restoredText.border?.lineWidth == 2,
                    "A cópia alterou fonte, cor ou borda explicitamente definidas.")
        let restoredField = try findAnnotation(restored, .widget, field: "roundtrip-text")
        let restoredChoice = try findAnnotation(restored, .widget, field: "roundtrip-choice")
        try require(restoredField.widgetDefaultStringValue == "Reset field" && restoredChoice.widgetDefaultStringValue == "first",
                    "A cópia alterou os valores explícitos de redefinição dos campos.")
        try require(restored.annotations.contains { PDFAnnotationKind.matches($0, .popup) &&
            $0.contents == "Independent popup contents" && $0.isOpen }, "A cópia perdeu o popup independente aberto.")
        try verifyPopupOpen(bytes, expected: true)
        try require(restored.annotations.contains { PDFAnnotationKind.matches($0, .popup) &&
            $0.contents == "Independent popup contents" &&
                ($0.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/F")) as? NSNumber)?.intValue == 4 },
                    "A cópia alterou os flags brutos do Popup independente.")

        try mutatedCandidate(bytes, prepared: prepared, name: "changed text reset default", mutate: { page in
            try findAnnotation(page, .widget, field: "roundtrip-text").widgetDefaultStringValue = "Different reset"
        }, persisted: { page in
            try findAnnotation(page, .widget, field: "roundtrip-text").widgetDefaultStringValue == "Different reset"
        })
        try mutatedCandidate(bytes, prepared: prepared, name: "changed choice reset default", mutate: { page in
            try findAnnotation(page, .widget, field: "roundtrip-choice").widgetDefaultStringValue = "second"
        }, persisted: { page in
            try findAnnotation(page, .widget, field: "roundtrip-choice").widgetDefaultStringValue == "second"
        })
        try mutatedCandidate(bytes, prepared: prepared, name: "changed font family at same size", mutate: { page in
            try findAnnotation(page, .freeText).font = otherFont
        }, persisted: { page in
            let item = try findAnnotation(page, .freeText)
            return item.font?.fontName == otherFont.fontName && item.font?.pointSize == 17
        })
        // PDFKit immediately converts named colors such as NSColor.red into
        // its annotation color space. Capture the actual setter result before
        // writing, require a real change, then compare that same color after
        // reopening; do not mistake the conversion for a serialization loss.
        var changedFontColor: NSColor?
        try mutatedCandidate(bytes, prepared: prepared, name: "changed font color", mutate: { page in
            let item = try findAnnotation(page, .freeText)
            item.fontColor = NSColor(srgbRed: 0.6, green: 0.2, blue: 0.3, alpha: 1)
            guard let effective = item.fontColor else { throw failure("O setter de cor não retornou uma cor de texto efetiva.") }
            try require(!sameColor(effective, annotation.fontColor), "O controle de cor não alterou a cor efetiva da anotação.")
            changedFontColor = effective
        }, persisted: { page in
            guard let changedFontColor else { return false }
            return sameColor(try findAnnotation(page, .freeText).fontColor, changedFontColor)
        }, serialized: { try verifyChangedFontColor(baseline: bytes, changed: $0) })
        try mutatedCandidate(bytes, prepared: prepared, name: "changed explicit border", mutate: { page in
            let changed = PDFBorder(); changed.lineWidth = 4
            try findAnnotation(page, .freeText).border = changed
        }, persisted: { page in try findAnnotation(page, .freeText).border?.lineWidth == 4 })
        let oldAnchor = CGPoint(x: note.bounds.minX, y: note.bounds.maxY)
        try mutatedCandidate(bytes, prepared: prepared, name: "moved note anchor", mutate: { page in
            let item = try findAnnotation(page, .text); item.bounds = item.bounds.offsetBy(dx: 11, dy: 7)
        }, persisted: { page in
            let item = try findAnnotation(page, .text)
            return item.bounds.minX == oldAnchor.x + 11 && item.bounds.maxY == oldAnchor.y + 7
        })
        try mutatedCandidate(bytes, prepared: prepared, name: "changed note color", mutate: { page in
            try findAnnotation(page, .text).color = .blue
        }, persisted: { page in sameColor(try findAnnotation(page, .text).value(forKey: "color") as? NSColor, .blue) })
        try mutatedCandidate(bytes, prepared: prepared, name: "changed ink vertex", mutate: { page in
            let ink = try findAnnotation(page, .ink)
            guard var paths = ink.paths, paths.count == 2 else { throw failure("A amostra não manteve os dois traços de tinta.") }
            let changed = NSBezierPath()
            changed.move(to: CGPoint(x: 4, y: 5)); changed.line(to: CGPoint(x: 35, y: 23))
            changed.line(to: CGPoint(x: 50, y: 25)); changed.line(to: CGPoint(x: 90, y: 5)); changed.line(to: CGPoint(x: 120, y: 15))
            for path in paths { ink.remove(path) }
            paths[0] = changed
            for path in paths { ink.add(path) }
        }, persisted: { page in
            guard let paths = try findAnnotation(page, .ink).paths, paths.count == 2, paths[0].elementCount == 5 else { return false }
            var points = [NSPoint](repeating: .zero, count: 3)
            let element = points.withUnsafeMutableBufferPointer { paths[0].element(at: 1, associatedPoints: $0.baseAddress!) }
            return element == .lineTo && points[0] == NSPoint(x: 35, y: 23)
        })
        try mutatedCandidate(bytes, prepared: prepared, name: "removed independent popup", mutate: { page in
            guard let item = page.annotations.first(where: { PDFAnnotationKind.matches($0, .popup) && $0.contents == "Independent popup contents" }) else {
                throw failure("O cenário de remoção não encontrou o popup independente.")
            }
            page.removeAnnotation(item)
        }, persisted: { page in !page.annotations.contains { $0.contents == "Independent popup contents" } })
        try mutatedCandidate(bytes, prepared: prepared, name: "closed independent popup", mutate: { page in
            guard let item = page.annotations.first(where: { PDFAnnotationKind.matches($0, .popup) && $0.contents == "Independent popup contents" }) else {
                throw failure("O cenário de fechamento não encontrou o popup independente.")
            }
            item.isOpen = false
        }, persisted: { page in page.annotations.contains { PDFAnnotationKind.matches($0, .popup) &&
            $0.contents == "Independent popup contents" && !$0.isOpen } },
           serialized: { try verifyPopupOpen($0, expected: false) })
        try mutatedCandidate(bytes, prepared: prepared, name: "changed independent popup raw flags", mutate: { page in
            guard let item = page.annotations.first(where: { PDFAnnotationKind.matches($0, .popup) && $0.contents == "Independent popup contents" }) else {
                throw failure("O cenário de flags não encontrou o Popup independente.")
            }
            try require(item.setValue(NSNumber(value: 0), forAnnotationKey: PDFAnnotationKey(rawValue: "/F")),
                        "O cenário não conseguiu alterar os flags brutos do Popup.")
        }, persisted: { page in page.annotations.contains { PDFAnnotationKind.matches($0, .popup) &&
            $0.contents == "Independent popup contents" &&
                ($0.value(forAnnotationKey: PDFAnnotationKey(rawValue: "/F")) as? NSNumber)?.intValue == 0 } })
        log("explicit fidelity guards: real changed defaults, font family/color, border, note anchor/color, ink vertex and independent popup rejected")
    }

    /// /InkList stores polylines. The app's pen tool creates move/line strokes;
    /// an unsupported Bézier must never become a silently simplified drawing.
    @MainActor
    static func verifyUnsupportedInkCurveRefusal() throws {
        guard let document = PDFDocument(data: streamFixture().valid), let page = document.page(at: 0) else {
            throw failure("A amostra de curva de tinta não pôde ser criada.")
        }
        let ink = PDFAnnotation(bounds: CGRect(x: 60, y: 180, width: 140, height: 30), forType: .ink, withProperties: nil)
        let curve = NSBezierPath()
        curve.move(to: CGPoint(x: 4, y: 5)); curve.line(to: CGPoint(x: 35, y: 20))
        curve.curve(to: CGPoint(x: 120, y: 15), controlPoint1: CGPoint(x: 50, y: 25), controlPoint2: CGPoint(x: 90, y: 5))
        ink.add(curve); page.addAnnotation(ink)
        let prepared = try NativePDFSerialization.prepare(document: document)
        // Inspect what PDFKit actually encoded. Normalizing these already
        // serialized bytes is only a negative fixture, never the product save.
        let changed = try NativePDFSerialization.normalize(data: prepared.data)
        try check(changed, phase: "structurally valid PDFKit ink curve loss control")
        guard let reopened = PDFDocument(data: changed), let restored = reopened.page(at: 0),
              let paths = try findAnnotation(restored, .ink).paths else {
            throw failure("A amostra de perda de curva não pôde ser reaberta.")
        }
        let retainedCurve = paths.contains { path in
            (0..<path.elementCount).contains { path.element(at: $0) == .curveTo }
        }
        try require(!retainedCurve, "O controle de perda de curva não reproduziu a limitação de InkList esperada.")
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: changed, prepared: prepared) },
                    "A verificação aceitou perder os controles da curva de tinta.")
        do {
            _ = try NativePDFSerialization.finish(prepared)
            throw failure("A publicação aceitou uma curva de tinta com geometria perdida.")
        } catch {
            let issue = error as NSError
            try require(issue.domain == "PDF.NativeSerialization" && issue.localizedDescription.contains("anotação.paths"),
                        "A recusa da curva não foi causada pela perda real da geometria do traço.")
        }
        log("ink curve guard: real PDFKit control-point loss rejected; pen polylines remain strictly preserved")
    }

    @MainActor
    private static func mutatedCandidate(_ baseline: Data, prepared: NativePDFSerialization.Prepared, name: String,
                                         mutate: (PDFPage) throws -> Void, persisted: (PDFPage) throws -> Bool,
                                         serialized: ((Data) throws -> Void)? = nil) throws {
        guard let document = PDFDocument(data: baseline), let page = document.page(at: 0) else {
            throw failure("A amostra de adulteração não pôde ser aberta.")
        }
        try mutate(page)
        let bytes = try NativePDFSerialization.serialize(document: document)
        try check(bytes, phase: name)
        try serialized?(bytes)
        guard let reopened = PDFDocument(data: bytes), let result = reopened.page(at: 0), try persisted(result) else {
            throw failure("\(name): a alteração solicitada não persistiu; cenário inválido.")
        }
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: bytes, prepared: prepared) },
                    "\(name): a verificação aceitou uma mudança real em PDF estruturalmente válido.")
    }

    private static func findAnnotation(_ page: PDFPage, _ type: PDFAnnotationSubtype, field: String? = nil) throws -> PDFAnnotation {
        guard let annotation = page.annotations.first(where: { PDFAnnotationKind.matches($0, type) && (field == nil || $0.fieldName == field) }) else {
            throw failure("Uma anotação exigida pela amostra está ausente.")
        }
        return annotation
    }

    private static func sameColor(_ lhs: NSColor?, _ rhs: NSColor?) -> Bool {
        guard let lhs, let rhs else { return lhs == nil && rhs == nil }
        guard let left = lhs.usingColorSpace(.sRGB), let right = rhs.usingColorSpace(.sRGB) else { return false }
        let tolerance: CGFloat = 1 / 255
        return abs(left.redComponent - right.redComponent) <= tolerance &&
            abs(left.greenComponent - right.greenComponent) <= tolerance &&
            abs(left.blueComponent - right.blueComponent) <= tolerance &&
            abs(left.alphaComponent - right.alphaComponent) <= tolerance
    }

    /// Inspect only live page annotations from the independent qpdf JSON, not
    /// an orphaned dictionary or the same canonicalizer used by production.
    private static func liveAnnotations(_ data: Data, password: String? = nil) throws -> [[String: Any]] {
        var options: [String: Any] = ["json": "2", "jsonKey": ["qpdf", "pages"], "jsonStreamData": "none"]
        if let password { options["password"] = password }
        let report = try auditJob(data, options: options, outputPDF: false)
        guard let root = try JSONSerialization.jsonObject(with: report) as? [String: Any],
              let qpdf = root["qpdf"] as? [Any], qpdf.count == 2,
              let objects = qpdf[1] as? [String: [String: Any]],
              let pages = root["pages"] as? [[String: Any]], pages.count == 1 else {
            throw failure("A amostra não produziu a árvore independente de uma página esperada.")
        }
        func value(_ source: Any?) -> Any? {
            if let reference = source as? String, reference.hasSuffix(" R") {
                return objects["obj:" + reference]?["value"]
            }
            return source
        }
        guard let page = value(pages[0]["object"]) as? [String: Any],
              let references = value(page["/Annots"]) as? [Any] else {
            throw failure("A página não contém a lista de anotações esperada pela auditoria.")
        }
        return try references.map { reference in
            guard let annotation = value(reference) as? [String: Any] else {
                throw failure("Uma anotação da amostra não pôde ser inspecionada independentemente.")
            }
            return annotation
        }
    }

    private static func verifyChoiceExport(_ data: Data, password: String?, expected: String) throws {
        let matches = try liveAnnotations(data, password: password).filter { $0["/T"] as? String == "u:roundtrip-choice" }
        guard matches.count == 1, let field = matches.first,
              field["/FT"] as? String == "/Ch", field["/Subtype"] as? String == "/Widget",
              field["/V"] as? String == "u:" + expected,
              field["/Opt"] as? [[String]] == [["u:first", "u:First label"], ["u:second", "u:Second label"]],
              let flags = field["/Ff"] as? NSNumber, CFGetTypeID(flags) != CFBooleanGetTypeID(), flags.intValue == 0 else {
            throw failure("O valor exportado, as opções ou o tipo da lista diferem nos objetos PDF publicados.")
        }
    }

    private static func verifyPopupOpen(_ data: Data, expected: Bool) throws {
        let matches = try liveAnnotations(data).filter {
            $0["/Subtype"] as? String == "/Popup" && $0["/Contents"] as? String == "u:Independent popup contents"
        }
        guard matches.count == 1, let flag = matches.first?["/Open"] as? NSNumber,
              CFGetTypeID(flag) == CFBooleanGetTypeID(), flag.boolValue == expected else {
            throw failure("O Popup independente não preservou /Open como booleano PDF com o estado esperado.")
        }
    }

    private static func verifyChangedFontColor(baseline: Data, changed: Data) throws {
        func RGB(_ data: Data) throws -> [Double] {
            let matches = try liveAnnotations(data).filter {
                $0["/Subtype"] as? String == "/FreeText" && $0["/Contents"] as? String == "u:Annotation 4"
            }
            guard matches.count == 1, let appearance = matches.first?["/DA"] as? String,
                  appearance.hasPrefix("u:") else { throw failure("A aparência textual não contém uma string PDF independente.") }
            let tokens = appearance.dropFirst(2).split(whereSeparator: { $0.isWhitespace })
            let operators = tokens.indices.filter { tokens[$0] == "rg" }
            guard operators.count == 1, let index = operators.first, index >= 3 else {
                throw failure("A aparência da amostra não contém a única cor RGB esperada.")
            }
            let components = tokens[(index - 3)..<index].compactMap { Double($0) }
            guard components.count == 3, components.allSatisfy({ $0.isFinite && (0...1).contains($0) }) else {
                throw failure("A aparência da amostra contém componentes de cor inválidos.")
            }
            return components
        }
        try require(try RGB(baseline) != RGB(changed),
                    "O controle de cor não alterou os componentes RGB serializados em /DA.")
    }


    @MainActor
    static func verifyUnicodeFieldIdentity() throws {
        // Swift String equality intentionally treats these forms as equivalent.
        // PDF field identity and the saved values must retain the actual bytes.
        let suffixes = ["\u{00E9}", "e\u{0301}"]
        try require(suffixes[0] == suffixes[1] && !suffixes[0].utf8.elementsEqual(suffixes[1].utf8),
                    "A amostra Unicode não contém formas canonicamente equivalentes e distintas em bytes.")
        guard let document = PDFDocument(data: streamFixture().valid), let page = document.page(at: 0) else {
            throw failure("A amostra de identidade Unicode não pôde ser criada.")
        }
        for (index, suffix) in suffixes.enumerated() {
            let field = PDFAnnotation(bounds: CGRect(x: 80, y: CGFloat(500 - index * 70), width: 200, height: 35),
                                      forType: .widget, withProperties: nil)
            field.widgetFieldType = .text
            field.fieldName = "/" + suffix
            field.widgetStringValue = "/valor-" + suffix
            field.widgetDefaultStringValue = "/default-" + suffix
            page.addAnnotation(field)
        }
        try assertUnicodeFields(page, suffixes: suffixes)
        var plain: (Data, NativePDFSerialization.Prepared)?
        let passwords: [String?] = [nil, "unicode-audit-reader-123"]
        for password in passwords {
            let prepared = try NativePDFSerialization.prepare(document: document, password: password)
            let bytes = try NativePDFSerialization.finish(prepared)
            try check(bytes, password: password, phase: "byte-exact Unicode field identities")
            if let password { try verifyAES256(bytes, password: password) }
            let result = try NativePDFSerialization.open(data: bytes, password: password)
            guard let restored = result.page(at: 0) else { throw failure("A cópia Unicode perdeu sua página.") }
            try assertUnicodeFields(restored, suffixes: suffixes)
            if password == nil { plain = (bytes, prepared) }
        }
        guard let (bytes, prepared) = plain else { throw failure("A amostra Unicode sem senha não foi executada.") }
        let composedName = "/" + suffixes[0]
        let decomposedValue = "/valor-" + suffixes[1]
        try mutatedCandidate(bytes, prepared: prepared, name: "Unicode value decomposition changed", mutate: { page in
            try exactUnicodeField(page, named: composedName).widgetStringValue = decomposedValue
        }, persisted: { page in
            try exactUnicodeField(page, named: composedName).widgetStringValue?.utf8.elementsEqual(decomposedValue.utf8) == true
        })
        let decomposedDefault = "/default-" + suffixes[1]
        try mutatedCandidate(bytes, prepared: prepared, name: "Unicode reset decomposition changed", mutate: { page in
            try exactUnicodeField(page, named: composedName).widgetDefaultStringValue = decomposedDefault
        }, persisted: { page in
            try exactUnicodeField(page, named: composedName).widgetDefaultStringValue?.utf8.elementsEqual(decomposedDefault.utf8) == true
        })
        log("Unicode field guard: NFC/NFD names, values and defaults preserved byte-for-byte; real decomposition changes rejected")
    }

    private static func exactUnicodeField(_ page: PDFPage, named name: String) throws -> PDFAnnotation {
        let fields = page.annotations.filter {
            PDFAnnotationKind.matches($0, .widget) && $0.fieldName?.utf8.elementsEqual(name.utf8) == true
        }
        guard fields.count == 1, let field = fields.first else {
            throw failure("A cópia uniu, perdeu ou duplicou campos Unicode de identidade distinta.")
        }
        return field
    }

    private static func assertUnicodeFields(_ page: PDFPage, suffixes: [String]) throws {
        let widgets = page.annotations.filter { PDFAnnotationKind.matches($0, .widget) }
        try require(widgets.count == 2 && Set(widgets.compactMap { $0.fieldName.map { Data($0.utf8) } }).count == 2,
                    "Os nomes NFC/NFD foram unidos ou normalizados durante a gravação.")
        for suffix in suffixes {
            let field = try exactUnicodeField(page, named: "/" + suffix)
            try require(field.widgetStringValue?.utf8.elementsEqual(("/valor-" + suffix).utf8) == true &&
                        field.widgetDefaultStringValue?.utf8.elementsEqual(("/default-" + suffix).utf8) == true,
                        "A cópia alterou os bytes do valor ou da redefinição de um campo Unicode.")
        }
    }

    /// Inspect the final cipher independently, including the distinction
    /// between a reader password and the randomly generated owner credential.
    static func verifyAES256(_ data: Data, password: String, permissions: [String: Bool]? = nil) throws {
        try check(data, password: password, phase: "AES-256 output structure")
        let evidence = try encryptionEvidence(data, password: password)
        try require(evidence.bits == 256 && evidence.revision == 6 && evidence.version == 5 &&
                    evidence.methods.allSatisfy { $0 == "AESv3" } && evidence.userMatched && !evidence.ownerMatched,
                    "O PDF final não usa AES-256/R6 com senha de proprietário distinta da senha de leitura.")
        if let permissions {
            try require(evidence.permissions == permissions, "O PDF protegido alterou as permissões originais.")
        }
        guard let envelope = PDFDocument(data: data), envelope.isEncrypted, envelope.isLocked,
              !envelope.unlock(withPassword: ""), !envelope.unlock(withPassword: "incorrect-audit-credential") else {
            throw failure("A proteção final não rejeitou senhas incorretas ou não aceitou a senha completa.")
        }
        try require(try run(data, password: "") == 2 && run(data, password: "incorrect-audit-credential") == 2,
                    "A autenticação independente aceitou uma senha vazia ou incorreta.")
        try require(rejects { _ = try NativePDFSerialization.open(data: data, password: "") } &&
                    rejects { _ = try NativePDFSerialization.open(data: data, password: "incorrect-audit-credential") },
                    "A abertura do aplicativo aceitou uma senha vazia ou incorreta.")
        let pending = try NativePDFSerialization.prepareOpen(data: data)
        try require(pending.isEncrypted && pending.requiresPassword && pending.originalData == data,
                    "A abertura sem credencial não preservou os bytes protegidos ou a solicitação de senha.")
        let document = try NativePDFSerialization.open(data: data, password: password)
        try require(document.isEncrypted && !document.isLocked,
                    "A abertura autenticada não entregou um documento protegido legível.")
    }

    @MainActor
    static func verifyCredentialGuards() throws {
        // Both are exactly 127 UTF-8 bytes. The Unicode case detects character
        // counting and truncation mistakes that an ASCII-only test cannot.
        for password in [String(repeating: "a", count: 127), String(repeating: "🔑", count: 31) + "abc"] {
            guard let document = PDFDocument(data: streamFixture().valid) else { throw failure("A amostra de senha é inválida.") }
            try require(password.utf8.count == 127, "A amostra de limite de senha está incorreta.")
            let prepared = try NativePDFSerialization.prepare(document: document, password: password)
            guard let stagingPassword = prepared.inputPassword, stagingPassword != password,
                  stagingPassword.utf8.count == 32, stagingPassword.utf8.allSatisfy({ $0 < 128 }),
                  let staging = PDFDocument(data: prepared.data), staging.isEncrypted, staging.isLocked,
                  !staging.unlock(withPassword: ""), !staging.unlock(withPassword: password),
                  staging.unlock(withPassword: stagingPassword) else {
                throw failure("O estágio PDFKit não manteve criptografia com credencial temporária ASCII distinta.")
            }
            let result = try NativePDFSerialization.finish(prepared)
            try verifyAES256(result, password: password)
            try require(try run(result, password: stagingPassword) == 2 && rejects {
                _ = try NativePDFSerialization.open(data: result, password: stagingPassword)
            },
                        "A senha temporária do estágio foi aceita pelo documento final.")
            let reopened = try NativePDFSerialization.open(data: result, password: password)
            guard (reopened.string ?? "").contains("PDF structural verification") else {
                throw failure("A senha no limite UTF-8 não preservou o acesso ao conteúdo.")
            }
        }
        for password in [String(repeating: "a", count: 128), String(repeating: "🔑", count: 32)] {
            guard let document = PDFDocument(data: streamFixture().valid) else { throw failure("A amostra de limite inválido está ausente.") }
            try require(password.utf8.count == 128 && rejects {
                _ = try NativePDFSerialization.prepare(document: document, password: password)
            }, "O escritor aceitou uma senha acima de 127 bytes UTF-8, sujeita a truncamento.")
        }
        log("AES-256 credential guards: cipher, distinct owner and 127-byte Unicode boundary verified")
    }

    @MainActor
    static func verifyPermissionGuards() throws {
        let password = "restricted-audit-reader"
        let permissions: [String: Bool] = ["accessibility": true, "extract": false, "modify": false,
            "modifyannotations": false, "modifyassembly": false, "modifyforms": false, "modifyother": false,
            "printhigh": false, "printlow": true]
        let settings = ["useAes": "y", "accessibility": "y", "annotate": "n", "assemble": "n",
                        "extract": "n", "form": "n", "modifyOther": "n", "print": "low"]
        let sourceOwner = "audit-owner-" + UUID().uuidString
        let restricted = try auditJob(streamFixture().valid, options: ["encrypt": [
            "userPassword": password, "ownerPassword": sourceOwner, "128bit": settings]], outputPDF: true)
        let sourceEvidence = try encryptionEvidence(restricted, password: password)
        try require(sourceEvidence.bits == 128 && sourceEvidence.permissions == permissions,
                    "A amostra de permissões não contém as restrições que a auditoria exige.")
        let normalized = try NativePDFSerialization.normalize(data: restricted, password: password)
        try verifyAES256(normalized, password: password, permissions: permissions)
        for unlockCredential in [password, sourceOwner] {
            let document = try NativePDFSerialization.open(data: restricted, password: unlockCredential)
            let rewritten = try NativePDFSerialization.serialize(document: document, password: password)
            try verifyAES256(rewritten, password: password, permissions: permissions)
        }
        guard let unproven = PDFDocument(data: restricted), unproven.unlock(withPassword: password) else {
            throw failure("O controle sem prova de origem não pôde ser aberto pelo PDFKit.")
        }
        try require(rejects { _ = try NativePDFSerialization.prepare(document: unproven, password: password) },
                    "Publicar um documento protegido sem metadados verificados permitiu confiar em permissões derivadas.")

        // A legacy file may set the high-quality bit while denying all print
        // access. That bit alone must not become permission to print after R6.
        let noPrintSource = try highPrintWithoutLowFixture()
        var noPrintPermissions = permissions
        noPrintPermissions["printlow"] = false
        let noPrintEvidence = try encryptionEvidence(noPrintSource, password: password)
        try require(noPrintEvidence.permissions == noPrintPermissions,
                    "A amostra de bits de impressão não representa a proibição esperada.")
        let noPrintOutput = try NativePDFSerialization.normalize(data: noPrintSource, password: password)
        try verifyAES256(noPrintOutput, password: password, permissions: noPrintPermissions)
        let noPrintDocument = try NativePDFSerialization.open(data: noPrintSource, password: password)
        let noPrintRewrite = try NativePDFSerialization.serialize(document: noPrintDocument, password: password)
        try verifyAES256(noPrintRewrite, password: password, permissions: noPrintPermissions)

        // qpdf itself ignores accessibility=n when creating current encryption.
        // This independently generated AES-128 fixture retains that legacy
        // restriction, so upgrading must fail instead of silently granting it.
        let inaccessible = try inaccessibleFixture()
        let legacyPassword = "accessibility-audit-user"
        let legacyEvidence = try encryptionEvidence(inaccessible, password: legacyPassword)
        try require(legacyEvidence.bits == 128 && legacyEvidence.permissions["accessibility"] == false,
                    "A amostra legada não contém a restrição de acessibilidade exigida.")
        try require(rejects { _ = try NativePDFSerialization.normalize(data: inaccessible, password: legacyPassword) },
                    "A normalização removeu uma restrição que AES-256/R6 não consegue representar.")
        let legacyDocument = try NativePDFSerialization.open(data: inaccessible, password: legacyPassword)
        try require(rejects { _ = try NativePDFSerialization.serialize(document: legacyDocument, password: legacyPassword) },
                    "A gravação editável removeu a restrição legada de acessibilidade.")
        log("AES-256 permission guards: user/owner access, intrinsic flags and incompatible legacy restriction verified")
    }

    private struct EncryptionEvidence {
        let bits: Int, revision: Int, version: Int
        let methods: [String]
        let userMatched: Bool, ownerMatched: Bool
        let permissions: [String: Bool]
    }
    private static func encryptionEvidence(_ data: Data, password: String) throws -> EncryptionEvidence {
        let report = try auditJob(data, options: ["password": password, "json": "2", "jsonKey": ["encrypt"]], outputPDF: false)
        guard let root = try JSONSerialization.jsonObject(with: report) as? [String: Any],
              let encryption = root["encrypt"] as? [String: Any],
              encryption["encrypted"] as? Bool == true,
              let parameters = encryption["parameters"] as? [String: Any],
              let bits = parameters["bits"] as? Int, let revision = parameters["R"] as? Int,
              let version = parameters["V"] as? Int,
              let user = encryption["userpasswordmatched"] as? Bool, let owner = encryption["ownerpasswordmatched"] as? Bool,
              let permissions = encryption["capabilities"] as? [String: Bool] else {
            throw failure("O relatório independente de criptografia é inválido.")
        }
        let methods = ["method", "streammethod", "stringmethod", "filemethod"].compactMap { parameters[$0] as? String }
        try require(methods.count == 4, "O relatório omitiu os algoritmos de criptografia.")
        // Never return or log recovereduserpassword/parameters.key from qpdf.
        return EncryptionEvidence(bits: bits, revision: revision, version: version, methods: methods,
                                  userMatched: user, ownerMatched: owner, permissions: permissions)
    }

    static func verifyProcessGuards(prepared: NativePDFSerialization.Prepared, password: String) throws {
        guard let inputPassword = prepared.inputPassword, inputPassword != password else {
            throw failure("A amostra de privacidade não separou senha temporária e senha final.")
        }
        var privacyErrors: [String] = [], directories: [URL] = [], launches = 0, ownerDigests: [Data] = []
        for _ in 0..<2 {
            _ = try NativePDFSerialization.finish(prepared, onLaunch: { process, directory in
                launches += 1; directories.append(directory)
                do {
                    if let digest = try inspectPrivacy(process, directory: directory, password: password, inputPassword: inputPassword) {
                        ownerDigests.append(digest)
                    }
                } catch { privacyErrors.append("O processo de validação não preservou os limites privados exigidos.") }
            })
        }
        try require(launches > 0 && privacyErrors.isEmpty && ownerDigests.count == 2 && Set(ownerDigests).count == 2,
                    "Senha, proprietário aleatório, argumentos ou temporários do verificador não ficaram privados.")
        try require(directories.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) },
                    "A gravação concluída deixou temporários privados no disco.")

        let before = NativeCancellation(); before.cancel()
        var unexpectedLaunch = false
        do {
            _ = try NativePDFSerialization.finish(prepared, cancellation: before, onLaunch: { _, _ in unexpectedLaunch = true })
            throw failure("A gravação ignorou cancelamento anterior ao processo.")
        } catch is CancellationError { /* Required: no subprocess is started. */ }
        try require(!unexpectedLaunch, "A gravação cancelada iniciou um processo externo.")

        // Exercise cancellation both after spawn and after the real checker has
        // completed. The latter proves no successful child can override a token
        // cancelled before returning publishable bytes.
        for waitForExit in [false, true] {
            let token = NativeCancellation()
            var child: Int32 = 0, launchCount = 0, folder: URL?, completed = false
            let started = ProcessInfo.processInfo.systemUptime
            do {
                _ = try NativePDFSerialization.finish(prepared, cancellation: token, onLaunch: { process, directory in
                    child = process.processIdentifier; launchCount += 1; folder = directory
                    if waitForExit {
                        let deadline = ProcessInfo.processInfo.systemUptime + 5
                        while process.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.01) }
                        completed = !process.isRunning
                    }
                    token.cancel()
                })
                throw failure("O cancelamento durante a verificação retornou bytes publicáveis.")
            } catch is CancellationError { /* Cancellation must remain cancellation. */ }
            try require(launchCount == 1 && child > 0 && (!waitForExit || completed),
                        "O cenário de cancelamento não atingiu a fase real do processo esperada.")
            try require(ProcessInfo.processInfo.systemUptime - started < 8,
                        "O cancelamento da gravação não encerrou o processo no prazo limitado.")
            try require(Darwin.kill(child, 0) == -1 && errno == ESRCH,
                        "O cancelamento deixou o processo de verificação em execução.")
            try require(folder.map { !FileManager.default.fileExists(atPath: $0.path) } == true,
                        "O cancelamento deixou temporários de gravação no disco.")
        }

        // Pause only the child owned by this test. A short test-only deadline
        // proves that timeout escalates to termination and reap, without waiting
        // the production 60-second limit in every installer smoke run.
        var timedChild: Int32 = 0, timedFolder: URL?, paused = false, timedOut = false
        let timeoutStarted = ProcessInfo.processInfo.systemUptime
        do {
            _ = try NativePDFSerialization.finish(prepared, onLaunch: { process, directory in
                timedChild = process.processIdentifier; timedFolder = directory
                paused = Darwin.kill(timedChild, SIGSTOP) == 0
            }, timeout: 0.1)
        } catch {
            timedOut = !(error is CancellationError) &&
                (error as NSError).domain == "PDF.NativeSerialization" && error.localizedDescription.contains("excedeu")
        }
        try require(timedOut && paused && timedChild > 0, "O processo suspenso não foi recusado pelo prazo de execução.")
        try require(ProcessInfo.processInfo.systemUptime - timeoutStarted < 5 &&
                    Darwin.kill(timedChild, 0) == -1 && errno == ESRCH,
                    "O timeout não encerrou e recolheu o filho pertencente à gravação.")
        try require(timedFolder.map { !FileManager.default.fileExists(atPath: $0.path) } == true,
                    "O timeout deixou temporários de gravação no disco.")
        log("private process guards: password on stdin, permissions, cancellation and timeout verified")
    }

    @MainActor
    static func verifyRepairProcessGuards() throws {
        // Both SDKs encode these leading-slash strings as PDF Names. This is
        // a real defect requiring updateFromJson, not a forced no-op patch.
        guard let document = PDFDocument(data: streamFixture().valid), let page = document.page(at: 0) else {
            throw failure("A amostra de reparo de strings não pôde ser criada.")
        }
        let field = PDFAnnotation(bounds: CGRect(x: 80, y: 500, width: 180, height: 30), forType: .widget, withProperties: nil)
        field.widgetFieldType = .text; field.fieldName = "/field"; field.widgetStringValue = "/value"
        field.widgetDefaultStringValue = "/default"; page.addAnnotation(field)
        let password = "repair-audit-reader-123"
        let prepared = try NativePDFSerialization.prepare(document: document, password: password)
        guard let inputPassword = prepared.inputPassword else { throw failure("O reparo protegido não definiu senha de estágio.") }
        var patchCount = 0, privacyFailed = false, folders: [URL] = []
        let result = try NativePDFSerialization.finish(prepared, onLaunch: { process, directory in
            folders.append(directory)
            do {
                _ = try inspectPrivacy(process, directory: directory, password: password, inputPassword: inputPassword)
                if try observedJob(process)["updateFromJson"] is String { patchCount += 1 }
            } catch { privacyFailed = true }
        })
        try require(patchCount == 1 && !privacyFailed,
                    "A correção real das strings não usou exatamente um patch privado e limitado.")
        try require(folders.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) },
                    "O reparo concluído deixou JSON ou PDFs temporários na pasta privada.")
        try verifyAES256(result, password: password)
        let reopened = try NativePDFSerialization.open(data: result, password: password)
        guard let repaired = reopened.page(at: 0)?.annotations.first(where: { $0.fieldName == "/field" }),
              repaired.widgetStringValue == "/value", repaired.widgetDefaultStringValue == "/default" else {
            throw failure("O reparo não preservou as strings literais com barra inicial.")
        }

        for enforceTimeout in [false, true] {
            let cancellation = NativeCancellation()
            var child: Int32 = 0, directory: URL?, patchFile: URL?, reachedPatch = 0
            var suspended = false, expectedFailure = false, observerFailed = false
            let start = ProcessInfo.processInfo.systemUptime
            do {
                _ = try NativePDFSerialization.finish(prepared, cancellation: cancellation, onLaunch: { process, folder in
                    do {
                        guard let path = try observedJob(process)["updateFromJson"] as? String else { return }
                        reachedPatch += 1; child = process.processIdentifier; directory = folder
                        patchFile = URL(fileURLWithPath: path)
                        try inspectPrivatePatch(URL(fileURLWithPath: path))
                        if enforceTimeout { suspended = Darwin.kill(child, SIGSTOP) == 0 }
                        else { cancellation.cancel() }
                    } catch { observerFailed = true; cancellation.cancel() }
                }, timeout: enforceTimeout ? 2 : 60)
            } catch {
                if reachedPatch == 0 { throw error }
                if enforceTimeout {
                    let issue = error as NSError
                    expectedFailure = !(error is CancellationError) && issue.domain == "PDF.NativeSerialization" &&
                        issue.localizedDescription.contains("excedeu")
                } else { expectedFailure = error is CancellationError }
            }
            try require(expectedFailure && !observerFailed && reachedPatch == 1 && child > 0 && (!enforceTimeout || suspended),
                        "O cenário não interrompeu a etapa real de patch pelo motivo esperado.")
            try require(ProcessInfo.processInfo.systemUptime - start < 12 && Darwin.kill(child, 0) == -1 && errno == ESRCH,
                        "A interrupção do patch não encerrou e recolheu o processo no prazo limitado.")
            try require(directory.map { !FileManager.default.fileExists(atPath: $0.path) } == true &&
                        patchFile.map { !FileManager.default.fileExists(atPath: $0.path) } == true,
                        "Cancelamento ou timeout deixaram o patch JSON privado no disco.")
        }
        log("typed-string patch guards: real repair, encrypted PDFs, private bounded JSON, cancellation/timeout cleanup verified")
    }

    private static func inspectPrivacy(_ process: Process, directory: URL, password: String, inputPassword: String) throws -> Data? {
        let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        try require((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o700,
                    "A pasta temporária da gravação não é privada.")
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        try require(!files.isEmpty, "O teste não encontrou os arquivos privados da gravação.")
        for file in files {
            let metadata = try FileManager.default.attributesOfItem(atPath: file.path)
            try require((metadata[.type] as? FileAttributeType) == .typeRegular &&
                        (metadata[.posixPermissions] as? NSNumber)?.intValue == 0o600,
                        "Um arquivo temporário não é regular e privado.")
        }
        let arguments = process.arguments ?? []
        try require(arguments == ["--job-json-file=/dev/stdin"] &&
                    !arguments.contains(where: { $0.contains(password) || $0.contains(inputPassword) }),
                    "O processo não usou o canal privado de senha.")
        let job = try observedJob(process)
        guard let inputPath = job["inputFile"] as? String, let credential = job["password"] as? String else {
            throw failure("O canal JSON privado não transportou a senha esperada.")
        }
        let isStagingInput = URL(fileURLWithPath: inputPath).lastPathComponent != "checked.pdf"
        try require(credential == (isStagingInput ? inputPassword : password),
                    "O job confundiu a credencial temporária do estágio e a senha final.")
        for key in ["inputFile", "outputFile", "updateFromJson"] {
            if let path = job[key] as? String {
                try require(URL(fileURLWithPath: path).standardizedFileURL.deletingLastPathComponent() == directory.standardizedFileURL,
                            "O job de publicação saiu da pasta privada da cópia.")
            }
        }
        try require(PDFDocument(url: URL(fileURLWithPath: inputPath))?.isEncrypted == true,
                    "Uma etapa da cópia protegida recebeu um PDF temporário sem criptografia.")
        if let patch = job["updateFromJson"] as? String { try inspectPrivatePatch(URL(fileURLWithPath: patch)) }
        guard let encryption = job["encrypt"] as? [String: Any] else { return nil }
        guard isStagingInput, encryption["userPassword"] as? String == password,
              let owner = encryption["ownerPassword"] as? String, owner != password, owner.utf8.count == 64,
              owner.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              encryption["256bit"] is [String: Any] else {
            throw failure("O job não usou AES-256 e uma credencial independente para o proprietário.")
        }
        try require(!arguments.contains(where: { $0.contains(owner) }) &&
                    !(process.environment?.values.contains(where: {
                        $0.contains(password) || $0.contains(inputPassword) || $0.contains(owner)
                    }) ?? false),
                    "Uma credencial de publicação foi exposta por argumentos ou ambiente.")
        return Data(SHA256.hash(data: Data(owner.utf8)))
    }

    /// pread leaves the offset shared with qpdf untouched, even if the child
    /// has already consumed the job. Never log or interpolate parsed values.
    private static func observedJob(_ process: Process) throws -> [String: Any] {
        guard process.arguments == ["--job-json-file=/dev/stdin"], let input = process.standardInput as? FileHandle else {
            throw failure("O processo não recebeu o job pelo descritor privado esperado.")
        }
        var metadata = stat()
        try require(fstat(input.fileDescriptor, &metadata) == 0 && metadata.st_mode & S_IFMT == S_IFREG &&
                    metadata.st_mode & 0o777 == 0o600 && metadata.st_uid == getuid() &&
                    metadata.st_size > 0 && metadata.st_size <= 64 * 1_024,
                    "O job não é um arquivo regular privado e limitado do usuário.")
        var buffer = [UInt8](repeating: 0, count: Int(metadata.st_size))
        let count = buffer.withUnsafeMutableBytes { Darwin.pread(input.fileDescriptor, $0.baseAddress, $0.count, 0) }
        guard count == buffer.count, let job = try JSONSerialization.jsonObject(with: Data(buffer)) as? [String: Any] else {
            throw failure("O job privado não contém JSON válido e completo.")
        }
        return job
    }

    private static func inspectPrivatePatch(_ patch: URL) throws {
        let descriptor = Darwin.open(patch.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw failure("O patch privado não pôde ser inspecionado sem seguir links.") }
        defer { _ = Darwin.close(descriptor) }
        var metadata = stat()
        try require(fstat(descriptor, &metadata) == 0 && metadata.st_mode & S_IFMT == S_IFREG &&
                    metadata.st_uid == getuid() && metadata.st_mode & 0o777 == 0o600 &&
                    metadata.st_size > 0 && metadata.st_size <= 64 * 1_024 * 1_024,
                    "O patch JSON não é regular, privado e limitado a 64 MiB.")
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw failure(message) }
    }
    private static func rejects(_ operation: () throws -> Void) -> Bool {
        do { try operation(); return false } catch { return true }
    }

    /// Small independent qpdf jobs used only for synthetic audit fixtures and
    /// encryption inspection. Job input and captured output can contain secrets;
    /// both stay in bounded, private regular files and never enter diagnostics.
    private static func auditJob(_ data: Data, options: [String: Any], outputPDF: Bool) throws -> Data {
        guard !data.isEmpty, data.count <= 4 * 1_024 * 1_024,
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw failure("A amostra criptográfica ou o verificador não está disponível.")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-crypto-audit-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let input = directory.appendingPathComponent("input.pdf")
        let jobFile = directory.appendingPathComponent("job.json")
        let output = directory.appendingPathComponent(outputPDF ? "result.pdf" : "result.json")
        try NativeOutput.write(data, to: input)
        try NativeOutput.write(Data(), to: output)
        var job = options
        job["inputFile"] = input.path
        if outputPDF { job["outputFile"] = output.path }
        let jobBytes = try JSONSerialization.data(withJSONObject: job)
        try require(jobBytes.count <= 64 * 1_024, "O job sintético excedeu o limite privado.")
        try NativeOutput.write(jobBytes, to: jobFile)
        let stdin = try FileHandle(forReadingFrom: jobFile)
        defer { try? stdin.close() }
        let stdout = try FileHandle(forWritingTo: output)
        defer { try? stdout.close() }
        let process = Process()
        process.executableURL = executable
        process.arguments = ["--job-json-file=/dev/stdin"]
        process.currentDirectoryURL = directory
        process.standardInput = stdin
        process.standardOutput = outputPDF ? FileHandle.nullDevice : stdout
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { throw failure("Não foi possível iniciar a auditoria criptográfica independente.") }
        defer { stopAndReap(process) }
        let deadline = ProcessInfo.processInfo.systemUptime + 15
        while process.isRunning {
            let size = (try FileManager.default.attributesOfItem(atPath: output.path)[.size] as? NSNumber)?.intValue ?? Int.max
            guard size <= 4 * 1_024 * 1_024, ProcessInfo.processInfo.systemUptime < deadline else {
                throw failure("A auditoria criptográfica excedeu o limite de tamanho ou tempo.")
            }
            Thread.sleep(forTimeInterval: 0.02)
        }
        process.waitUntilExit()
        try require(process.terminationReason == .exit && process.terminationStatus == 0,
                    "O job criptográfico independente terminou com erro ou aviso.")
        let metadata = try FileManager.default.attributesOfItem(atPath: output.path)
        try require((metadata[.type] as? FileAttributeType) == .typeRegular &&
                    (metadata[.posixPermissions] as? NSNumber)?.intValue == 0o600 &&
                    ((metadata[.size] as? NSNumber)?.intValue ?? Int.max) <= 4 * 1_024 * 1_024,
                    "O resultado da auditoria deixou de ser um arquivo regular privado e limitado.")
        let result = try Data(contentsOf: output)
        try require(!result.isEmpty, "O resultado da auditoria criptográfica está vazio.")
        return result
    }

    private static func run(_ data: Data, password: String?) throws -> Int32 {
        guard !data.isEmpty, data.count <= 128 * 1_024 * 1_024,
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw failure("qpdf não está instalado ou a amostra estrutural está fora do limite.")
        }
        let secret = password ?? ""
        guard !secret.contains("\n"), !secret.contains("\r"), !secret.contains("\0"), secret.utf8.count <= 4096 else {
            throw failure("A senha da amostra não pode ser transmitida pelo canal privado do verificador.")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-QPDF-audit-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                               attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let input = directory.appendingPathComponent("input.pdf")
        let credential = directory.appendingPathComponent("password.txt")
        try NativeOutput.write(data, to: input)
        try NativeOutput.write(Data((secret + "\n").utf8), to: credential)
        let stdin = try FileHandle(forReadingFrom: credential)
        defer { try? stdin.close() }
        let process = Process()
        process.executableURL = executable
        process.arguments = ["--password-file=-", "--check", input.path]
        process.currentDirectoryURL = directory
        process.standardInput = stdin
        // qpdf diagnostics can reveal passwords and document content. They are
        // discarded; only the exit status and fixed audit phase are reported.
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do { try process.run() }
        catch { throw failure("Não foi possível iniciar qpdf para a auditoria estrutural.") }
        defer { stopAndReap(process) }
        let deadline = ProcessInfo.processInfo.systemUptime + 15
        while process.isRunning {
            guard ProcessInfo.processInfo.systemUptime < deadline else {
                throw failure("qpdf excedeu o prazo de 15 segundos; a auditoria estrutural falhou.")
            }
            Thread.sleep(forTimeInterval: 0.02)
        }
        process.waitUntilExit()
        guard process.terminationReason == .exit else {
            throw failure("qpdf terminou por sinal; a auditoria estrutural falhou.")
        }
        return process.terminationStatus
    }

    private static func stopAndReap(_ process: Process) {
        if process.isRunning {
            process.terminate()
            let deadline = ProcessInfo.processInfo.systemUptime + 1
            while process.isRunning && ProcessInfo.processInfo.systemUptime < deadline { Thread.sleep(forTimeInterval: 0.02) }
            if process.isRunning { _ = Darwin.kill(process.processIdentifier, SIGKILL) }
        }
        process.waitUntilExit()
    }

    // Independently generated with PyMuPDF: one page, AES-128/R4, print only,
    // accessibility=false. Credentials are synthetic audit constants. Current
    // qpdf deliberately ignores accessibility=n when producing encryption, so
    // generating this control with the same qpdf under test would be invalid.
    private static func inaccessibleFixture() throws -> Data {
        let encoded = """
            JVBERi0xLjcKJcK1wrYKCjEgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIgMCBSPj4KZW5kb2JqCgoyIDAgb2JqCjw8L1R5
            cGUvUGFnZXMvQ291bnQgMS9LaWRzWzQgMCBSXT4+CmVuZG9iagoKMyAwIG9iago8PC9Gb250PDwvaGVsdiA1IDAgUj4+Pj4KZW5k
            b2JqCgo0IDAgb2JqCjw8L1R5cGUvUGFnZS9NZWRpYUJveFswIDAgMzAwIDQwMF0vUm90YXRlIDAvUmVzb3VyY2VzIDMgMCBSL1Bh
            cmVudCAyIDAgUi9Db250ZW50c1s2IDAgUl0+PgplbmRvYmoKCjUgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvQmFz
            ZUZvbnQvSGVsdmV0aWNhL0VuY29kaW5nL1dpbkFuc2lFbmNvZGluZz4+CmVuZG9iagoKNiAwIG9iago8PC9MZW5ndGggMTI4L0Zp
            bHRlci9GbGF0ZURlY29kZT4+CnN0cmVhbQraU/0PFnCzH4rXJSxBCQw1K7ywu/56KnLOXGbbOYOyFAWidPu8crWI8gVFfyaQ/zqq
            iVM2cgoSrvLP6WqULYlq7vKb9S0JxBhmDZXqym/HZctK75rTIy5G24GBC1wztQG0YBzLBqpM5fRajO/2yn6QcHvr8LG3AKV9sHlp
            izTQfAplbmRzdHJlYW0KZW5kb2JqCgp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTYgMDAwMDAgbiAKMDAw
            MDAwMDA2MiAwMDAwMCBuIAowMDAwMDAwMTE0IDAwMDAwIG4gCjAwMDAwMDAxNTUgMDAwMDAgbiAKMDAwMDAwMDI2MiAwMDAwMCBu
            IAowMDAwMDAwMzUxIDAwMDAwIG4gCgp0cmFpbGVyCjw8L1NpemUgNy9Sb290IDEgMCBSL0lEWzwwRDczNDFDM0JDNUZDMzk1MTBD
            Mzg5MzlDMzg3NUYwNj48RTJGNEJGNDBBMTVDOTA1ODc5NTAzMTVGOTIyQ0QyNTk+XS9FbmNyeXB0PDwvRmlsdGVyL1N0YW5kYXJk
            L1IgNC9WIDQvTGVuZ3RoIDEyOC9QIC0zOTAwL0VuY3J5cHRNZXRhZGF0YSB0cnVlL1N0bUYvU3RkQ0YvU3RyRi9TdGRDRi9DRjw8
            L1N0ZENGPDwvQXV0aEV2ZW50L0RvY09wZW4vQ0ZNL0FFU1YyL0xlbmd0aCAxNj4+Pj4vTzxEQjNFQkE5NzBBOERCMUNGMTgyNkMw
            Qjg3MjlDQjdEQzM1MDhDQTM5NEUxMTI3MUE1RDlDRkExRkY2RjM2MkI5Pi9VPERDNTJDQzg3OUQzQTZDRDRENkQxNjIzN0EwNTRD
            RkJGMjhCRjRFNUU0RTc1OEE0MTY0MDA0RTU2RkZGQTAxMDg+Pj4+PgpzdGFydHhyZWYKNTQ4CiUlRU9GCg==
            """
        guard let bytes = Data(base64Encoded: encoded, options: .ignoreUnknownCharacters) else {
            throw failure("A amostra independente de restrição legada está inválida.")
        }
        return bytes
    }

    // AES-128/R4 with permission bits 12 and 10, but without print bit 3.
    // Generated independently with PyMuPDF; both effective print rights are off.
    private static func highPrintWithoutLowFixture() throws -> Data {
        let encoded = """
            JVBERi0xLjcKJcK1wrYKCjEgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIgMCBSPj4KZW5kb2JqCgoyIDAgb2JqCjw8L1R5
            cGUvUGFnZXMvQ291bnQgMS9LaWRzWzQgMCBSXT4+CmVuZG9iagoKMyAwIG9iago8PC9Gb250PDwvaGVsdiA1IDAgUj4+Pj4KZW5k
            b2JqCgo0IDAgb2JqCjw8L1R5cGUvUGFnZS9NZWRpYUJveFswIDAgMzAwIDQwMF0vUm90YXRlIDAvUmVzb3VyY2VzIDMgMCBSL1Bh
            cmVudCAyIDAgUi9Db250ZW50c1s2IDAgUl0+PgplbmRvYmoKCjUgMCBvYmoKPDwvVHlwZS9Gb250L1N1YnR5cGUvVHlwZTEvQmFz
            ZUZvbnQvSGVsdmV0aWNhL0VuY29kaW5nL1dpbkFuc2lFbmNvZGluZz4+CmVuZG9iagoKNiAwIG9iago8PC9MZW5ndGggMTI4L0Zp
            bHRlci9GbGF0ZURlY29kZT4+CnN0cmVhbQr9OljOace+zg2e4Mv0QHfEzr9lyNiLaLDhNizLvGCcqpX3sl6d2iFmBazGPNQgJDkN
            PosrU+NytjpjGXnYpIRsKRjVGu8t4H4BpEIRa0jRxOGPEDuXbxl1WMpww0Dz2wSWfIR9MPjxIbcqFrRXJFl+BACn8LmnEro5Nyl/
            Z06XkQplbmRzdHJlYW0KZW5kb2JqCgp4cmVmCjAgNwowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTYgMDAwMDAgbiAKMDAw
            MDAwMDA2MiAwMDAwMCBuIAowMDAwMDAwMTE0IDAwMDAwIG4gCjAwMDAwMDAxNTUgMDAwMDAgbiAKMDAwMDAwMDI2MiAwMDAwMCBu
            IAowMDAwMDAwMzUxIDAwMDAwIG4gCgp0cmFpbGVyCjw8L1NpemUgNy9Sb290IDEgMCBSL0lEWzxDMkIwQzM5QTFDM0IzMkMyQUND
            MjlCQzNCODNDMEVDMj4oRVwwMzNaPzRcMzYzXDMzM0c8Vyw+XDIwNVwyNDN9XCgpXS9FbmNyeXB0PDwvRmlsdGVyL1N0YW5kYXJk
            L1IgNC9WIDQvTGVuZ3RoIDEyOC9QIC0xMzQ0L0VuY3J5cHRNZXRhZGF0YSB0cnVlL1N0bUYvU3RkQ0YvU3RyRi9TdGRDRi9DRjw8
            L1N0ZENGPDwvQXV0aEV2ZW50L0RvY09wZW4vQ0ZNL0FFU1YyL0xlbmd0aCAxNj4+Pj4vTzw4RDIwNkM0ODI4RUFBMUJENDhGRUFB
            MDk4RTU3QTg4MUZFRUVDODI5REY3QkNEMThBRDBGRjdGMDVCQjg1MjVDPi9VPDNGRTMxRkNDNjkxNTRDQTk1MDNBNDI0RjUwNkIy
            RTEzMjhCRjRFNUU0RTc1OEE0MTY0MDA0RTU2RkZGQTAxMDg+Pj4+PgpzdGFydHhyZWYKNTQ4CiUlRU9GCg==
            """
        guard let bytes = Data(base64Encoded: encoded, options: .ignoreUnknownCharacters) else {
            throw failure("A amostra independente de bits de impressão está inválida.")
        }
        return bytes
    }

    private static func streamFixture() -> (valid: Data, corrupted: Data) {
        let stream = "BT /F1 12 Tf 72 720 Td (PDF structural verification) Tj ET\n"
        let length = String(format: "%06d", stream.utf8.count)
        let objects = [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            "<< /Length \(length) >>\nstream\n" + stream + "endstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        ]
        var pdf = "%PDF-1.7\n"
        var offsets = [0]
        for (index, object) in objects.enumerated() {
            offsets.append(pdf.utf8.count)
            pdf += "\(index + 1) 0 obj\n\(object)\nendobj\n"
        }
        let xref = pdf.utf8.count
        pdf += "xref\n0 \(objects.count + 1)\n0000000000 65535 f \n"
        for offset in offsets.dropFirst() { pdf += String(format: "%010d 00000 n \n", offset) }
        pdf += "trailer\n<< /Size \(objects.count + 1) /Root 1 0 R >>\nstartxref\n\(xref)\n%%EOF\n"
        let damaged = pdf.replacingOccurrences(of: "/Length \(length)", with: "/Length 000000")
        return (Data(pdf.utf8), Data(damaged.utf8))
    }

    private static func log(_ message: String) {
        FileHandle.standardError.write(Data(("PDF structure audit: " + message + "\n").utf8))
    }
    private static func failure(_ message: String) -> NSError {
        NSError(domain: "PDF.QPDFStructuralAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
