import Foundation
import AppKit
import PDFKit
import Darwin

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
        guard let widgetBytes = changedWidget.dataRepresentation(),
              PDFDocument(data: widgetBytes)?.page(at: 0)?.annotations.contains(where: {
                  $0.fieldName == "native-test" && $0.widgetStringValue == "Altered audit value"
              }) == true else { throw failure("A amostra adulterada não persistiu a mudança real de formulário.") }
        try require(rejects { try NativePDFSerialization.verifyFidelity(data: widgetBytes, prepared: prepared) },
                    "A verificação de fidelidade aceitou alterar um campo preenchido.")

        guard let changedGeometry = PDFDocument(data: copy), let changedPage = changedGeometry.page(at: 0) else {
            throw failure("A amostra de geometria não pôde ser aberta.")
        }
        let crop = changedPage.bounds(for: .cropBox).insetBy(dx: 10, dy: 10)
        changedPage.setBounds(crop, for: .cropBox)
        guard let geometryBytes = changedGeometry.dataRepresentation(),
              PDFDocument(data: geometryBytes)?.page(at: 0)?.bounds(for: .cropBox) == crop else {
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
                path.curve(to: CGPoint(x: 120, y: 15), controlPoint1: CGPoint(x: 50, y: 25), controlPoint2: CGPoint(x: 90, y: 5))
                annotation.add(path)
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

        let passwords: [String?] = [nil, "roundtrip-protected-123"]
        for password in passwords {
            let prepared = try NativePDFSerialization.prepare(document: document, password: password)
            try recordRawPDFKit(prepared.data, password: password,
                                phase: password == nil ? "editable defaults unencrypted" : "editable defaults protected")
            let bytes = try NativePDFSerialization.finish(prepared)
            try check(bytes, password: password, phase: "published editable annotations and fields")
            guard let result = PDFDocument(data: bytes) else { throw failure("A cópia de anotações não pôde ser reaberta.") }
            if let password {
                try require(result.isEncrypted && result.isLocked && !result.unlock(withPassword: "") && result.unlock(withPassword: password),
                            "O roundtrip de anotações perdeu a proteção por senha.")
            }
            guard let restored = result.page(at: 0) else { throw failure("A cópia de anotações perdeu sua página.") }
            try require(result.pageCount == 1 && restored.annotations.count == types.count + 3,
                        "O roundtrip perdeu ou duplicou anotações/campos.")
            for (index, type) in types.enumerated() {
                try require(restored.annotations.contains {
                    PDFAnnotationKind.matches($0, type) && $0.contents == "Annotation \(index)"
                }, "O roundtrip perdeu um tipo editável ou seu conteúdo.")
            }
            try require(restored.annotations.contains { $0.fieldName == "roundtrip-text" && $0.widgetStringValue == "Editable field" },
                        "O roundtrip perdeu o valor do campo de texto.")
            try require(restored.annotations.contains {
                $0.fieldName == "roundtrip-choice" && $0.widgetStringValue == "second" &&
                    $0.choices == ["First label", "Second label"] && $0.values == ["first", "second"] && $0.isListChoice
            }, "O roundtrip perdeu seleção, rótulos ou valores da lista.")
            try require(restored.annotations.contains {
                $0.fieldName == "roundtrip-checkbox" && $0.widgetControlType == .checkBoxControl &&
                    $0.buttonWidgetState.rawValue == 1 && $0.buttonWidgetStateString == "Yes"
            }, "O roundtrip perdeu o estado marcado do checkbox.")
        }
        log("editable roundtrip: all \(types.count) supported annotation types and text/choice/checkbox preserved, plain and encrypted")
    }

    static func verifyProcessGuards(prepared: NativePDFSerialization.Prepared, password: String) throws {
        var privacyErrors: [String] = [], directories: [URL] = [], launches = 0
        _ = try NativePDFSerialization.finish(prepared, onLaunch: { process, directory in
            launches += 1; directories.append(directory)
            do { try inspectPrivacy(process, directory: directory, password: password) }
            catch { privacyErrors.append("O processo de validação não preservou os limites privados exigidos.") }
        })
        try require(launches > 0 && privacyErrors.isEmpty, "Senha, argumentos ou temporários do verificador não ficaram privados.")
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

    private static func inspectPrivacy(_ process: Process, directory: URL, password: String) throws {
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
        try require(arguments.contains("--password-file=-") && !arguments.contains(where: { $0.contains(password) }),
                    "O processo não usou o canal privado de senha.")
        guard let input = process.standardInput as? FileHandle else { throw failure("O processo não recebeu stdin privado.") }
        var metadata = stat()
        try require(fstat(input.fileDescriptor, &metadata) == 0 && metadata.st_mode & S_IFMT == S_IFREG &&
                    metadata.st_mode & 0o777 == 0o600 && metadata.st_uid == getuid(),
                    "O descritor da senha não é um arquivo regular privado do usuário.")
        var buffer = [UInt8](repeating: 0, count: password.utf8.count + 2)
        let count = buffer.withUnsafeMutableBytes { bytes in
            Darwin.pread(input.fileDescriptor, bytes.baseAddress, bytes.count, 0)
        }
        try require(count == password.utf8.count + 1 &&
                    String(decoding: buffer.prefix(max(0, count)), as: UTF8.self) == password + "\n",
                    "O canal privado não transportou a senha esperada.")
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw failure(message) }
    }
    private static func rejects(_ operation: () throws -> Void) -> Bool {
        do { try operation(); return false } catch { return true }
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
