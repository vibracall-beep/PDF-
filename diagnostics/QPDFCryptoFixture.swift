import AppKit
import CoreGraphics
import CryptoKit
import Darwin
import PDFKit

/// Synthetic inputs for the isolated qpdf relocation diagnosis. This does not
/// call the product serializer, repair a PDF, or approve a distribution.
@main
struct QPDFCryptoFixture {
    private static let knownText = "PDF qpdf crypto verification"
    private enum Failure: String, Error {
        case arguments, credential, directory, drawing, serialization, inspection, publication
    }

    private struct FileEvidence: Encodable {
        let filename: String
        let sha256: String
        let bytes: Int
        let encrypted: Bool
        let lockedBeforeAuthentication: Bool
        let passwordAccepted: Bool
        let emptyPasswordAccepted: Bool
        let wrongPasswordAccepted: Bool
        let pageCount: Int
        let knownTextMatched: Bool
    }

    private struct Evidence: Encodable {
        let schemaVersion = 1
        let kind = "synthetic-pdfkit-qpdf-crypto-inputs"
        let files: [FileEvidence]
    }

    @MainActor
    static func main() {
        do {
            if CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--inspect" {
                let password = try readCredential()
                let bytes = try readCandidate(URL(fileURLWithPath: CommandLine.arguments[2]))
                let evidence = try inspect(bytes, filename: "candidate.pdf", password: password)
                let encoder = JSONEncoder()
                encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                try publish(encoder.encode(evidence), to: URL(fileURLWithPath: CommandLine.arguments[3]))
                print("Synthetic protected PDF independently reopened with the expected text.")
                return
            }
            guard CommandLine.arguments.count == 2 else { throw Failure.arguments }
            let password = try readCredential()
            let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
            var info = stat()
            guard lstat(directory.path, &info) == 0, info.st_mode & S_IFMT == S_IFDIR,
                  info.st_uid == getuid(), info.st_mode & 0o777 == 0o700 else { throw Failure.directory }
            _ = NSApplication.shared
            let original = try draw()
            guard let document = PDFDocument(data: original), document.pageCount == 1,
                  document.string?.contains(knownText) == true else { throw Failure.drawing }
            guard let plain = document.dataRepresentation(),
                  let protected = document.dataRepresentation(options: [
                    AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): password,
                    AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): password
                  ]) else { throw Failure.serialization }
            let files = [
                try inspect(plain, filename: "plain.pdf", password: nil),
                try inspect(protected, filename: "protected.pdf", password: password)
            ]
            try publish(plain, to: directory.appendingPathComponent("plain.pdf"))
            try publish(protected, to: directory.appendingPathComponent("protected.pdf"))
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try publish(encoder.encode(Evidence(files: files)), to: directory.appendingPathComponent("fixture.json"))
            // No PDF content, credential, argument or framework error is logged.
            print("Synthetic PDFKit crypto inputs created and independently reopened.")
        } catch {
            let code = (error as? Failure)?.rawValue ?? "filesystem-or-framework"
            fputs("Synthetic PDFKit crypto fixture failed: \(code).\n", stderr)
            exit(1)
        }
    }

    private static func readCredential() throws -> String {
        var bytes = Data()
        while let chunk = try FileHandle.standardInput.read(upToCount: 65 - bytes.count), !chunk.isEmpty {
            bytes.append(chunk)
            guard bytes.count <= 64 else { throw Failure.credential }
        }
        if bytes.last == 10 { bytes.removeLast() }
        guard !bytes.isEmpty, bytes.count <= 32,
              bytes.allSatisfy({ $0 >= 33 && $0 <= 126 }),
              let password = String(data: bytes, encoding: .ascii) else { throw Failure.credential }
        return password
    }

    @MainActor
    private static func draw() throws -> Data {
        let bytes = NSMutableData()
        var box = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let consumer = CGDataConsumer(data: bytes as CFMutableData),
              let context = CGContext(consumer: consumer, mediaBox: &box, nil) else { throw Failure.drawing }
        context.beginPDFPage(nil)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        (knownText as NSString).draw(at: NSPoint(x: 72, y: 720), withAttributes: [
            .font: NSFont.systemFont(ofSize: 18), .foregroundColor: NSColor.black
        ])
        NSGraphicsContext.restoreGraphicsState()
        context.endPDFPage()
        context.closePDF()
        return bytes as Data
    }

    private static func inspect(_ bytes: Data, filename: String, password: String?) throws -> FileEvidence {
        guard !bytes.isEmpty, bytes.count <= 1_048_576,
              let document = PDFDocument(data: bytes),
              let emptyAttempt = PDFDocument(data: bytes),
              let wrongAttempt = PDFDocument(data: bytes) else { throw Failure.inspection }
        let encrypted = document.isEncrypted, locked = document.isLocked
        var accepted = false, emptyAccepted = false, wrongAccepted = false
        if let password {
            emptyAccepted = emptyAttempt.unlock(withPassword: "")
            let wrong = password == "incorrect-fixture-credential" ? "other-incorrect-credential" : "incorrect-fixture-credential"
            wrongAccepted = wrongAttempt.unlock(withPassword: wrong)
            accepted = document.unlock(withPassword: password)
            guard encrypted, locked, accepted, !document.isLocked,
                  !emptyAccepted, !wrongAccepted else { throw Failure.inspection }
        } else {
            guard !encrypted, !locked else { throw Failure.inspection }
        }
        let matches = document.string?.contains(knownText) == true
        guard document.pageCount == 1, matches else { throw Failure.inspection }
        return FileEvidence(filename: filename, sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
                            bytes: bytes.count, encrypted: encrypted, lockedBeforeAuthentication: locked,
                            passwordAccepted: accepted, emptyPasswordAccepted: emptyAccepted,
                            wrongPasswordAccepted: wrongAccepted, pageCount: document.pageCount,
                            knownTextMatched: matches)
    }

    private static func publish(_ bytes: Data, to destination: URL) throws {
        let descriptor = Darwin.open(destination.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw Failure.publication }
        defer { Darwin.close(descriptor) }
        try bytes.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { throw Failure.publication }
            var offset = 0
            while offset < raw.count {
                let written = Darwin.write(descriptor, base.advanced(by: offset), raw.count - offset)
                if written < 0 && errno == EINTR { continue }
                guard written > 0 else { throw Failure.publication }
                offset += written
            }
        }
        guard fsync(descriptor) == 0 else { throw Failure.publication }
    }

    private static func readCandidate(_ source: URL) throws -> Data {
        let descriptor = Darwin.open(source.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw Failure.inspection }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        var before = stat()
        guard fstat(descriptor, &before) == 0, before.st_mode & S_IFMT == S_IFREG,
              before.st_size > 0, before.st_size <= 1_048_576 else { throw Failure.inspection }
        var bytes = Data()
        while let chunk = try handle.read(upToCount: 1_048_577 - bytes.count), !chunk.isEmpty {
            bytes.append(chunk)
            guard bytes.count <= 1_048_576 else { throw Failure.inspection }
        }
        var after = stat()
        guard fstat(descriptor, &after) == 0, Int64(bytes.count) == before.st_size,
              before.st_size == after.st_size,
              before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec else { throw Failure.inspection }
        return bytes
    }
}
