import Foundation
import Darwin

/// An independent, strict check of the actual PDF bytes. qpdf may repair a file
/// in memory to inspect it, but warnings (exit 3) never count as a successful audit.
/// Neither a normalized PDF nor any converter output is accepted as evidence.
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
