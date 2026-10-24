"""Run exact production audits using private, instrumented source copies only."""
import hashlib
import json
import os
from pathlib import Path

BASE_REVISION = "0910ad97614e53fd11becd65e173b6dbaff8cc7a"
SOURCE_HASHES = {
    "NativePDFSerialization.swift": "b255f3d2fa01ab431e170a4c5f95d060c6ddc3ca98d62dcfff7b18561c30b856",
    "NativePDFStringRepair.swift": "5bc7c33f2edee43a00e886e0514cd40cfbffc969c212696a096ba8a44cd69506",
    "QPDFStructuralAudit.swift": "baf04e241e49c06dbd10b44f48da85c3f7ba547efea5c3c1cd6bb062f5aa704c",
    "AnnotationEditing.swift": "bf1258ca54a1a0cab1601f6a904c52d7a649c6ea8a8e31978d349fdafe962a37",
}


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError("Diagnostic instrumentation anchor count changed: " + old[:100])
    return text.replace(old, new)


def private_write(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)


def annotation_metadata(objects):
    keys = {"/Type", "/Subtype", "/Open", "/F", "/Rect", "/Contents", "/Parent", "/Popup", "/NM",
            "/FT", "/T", "/V", "/DV", "/Opt", "/Ff", "/DA", "/C"}
    rows = []
    for reference, wrapped in objects.items():
        value = wrapped.get("value") if isinstance(wrapped, dict) else None
        if isinstance(value, dict) and value.get("/Subtype") in ("/Text", "/Popup", "/Widget", "/FreeText"):
            rows.append({"object": reference, "dictionary": {key: entry for key, entry in value.items() if key in keys}})
    if len(rows) > 256:
        raise ValueError("Synthetic annotation report exceeded 256 objects")
    return rows


def stage_sources(repository, directory):
    directory.mkdir(mode=0o700)
    original = {}
    for name, expected in SOURCE_HASHES.items():
        data = (repository / "Sources" / "PDF" / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Exact diagnostic requires unchanged " + BASE_REVISION + " source: " + name)
        original[name] = data.decode()

    text = original["NativePDFSerialization.swift"]
    text = replace(text, "FileManager.default.temporaryDirectory", "ExactAuditCapture.currentDirectory", 2)
    text = replace(text, "defer { try? FileManager.default.removeItem(at: directory) }", "// Synthetic diagnostic retains its private staging directory.", 2)
    text = replace(text, "let baseline = try snapshot(document)", "let baseline = try snapshot(document)\n        try ExactAuditCapture.snapshot(document, label: \"prepare-before\")")
    text = replace(text, "try materializeWriterDefaults(document)", "try materializeWriterDefaults(document)\n        try ExactAuditCapture.snapshot(document, label: \"prepare-materialized\")")
    text = replace(text, "let actual = try snapshot(reopened, cancellation: cancellation)", "try ExactAuditCapture.snapshot(reopened, label: \"reopened-final\")\n        let actual = try snapshot(reopened, cancellation: cancellation)")
    text = replace(text, "process.standardInput = stdin; process.standardOutput = stdout ?? FileHandle.nullDevice; process.standardError = FileHandle.nullDevice",
        "process.standardInput = stdin\n        let capture = try ExactAuditCapture.attach(process, directory: directory, stdout: stdout)\n        defer { capture.close() }")
    text = replace(text, "        while process.isRunning {\n", "        while process.isRunning {\n            try capture.check()\n")
    text = replace(text, "        return process.terminationStatus", "        try capture.check(); capture.record(process)\n        return process.terminationStatus")
    private_write(directory / "NativePDFSerialization.swift", text.encode())

    text = original["NativePDFStringRepair.swift"]
    text = replace(text, "private static func failure() -> NSError", "private static func failure(_ diagnosticLine: Int = #line) -> NSError")
    text = replace(text, 'NSError(domain: "PDF.NativeStringRepair", code: 1, userInfo: [NSLocalizedDescriptionKey:',
        'NSError(domain: "PDF.NativeStringRepair", code: 1, userInfo: ["diagnosticLine": diagnosticLine, NSLocalizedDescriptionKey:')
    private_write(directory / "NativePDFStringRepair.swift", text.encode())

    text = original["QPDFStructuralAudit.swift"]
    text = replace(text, "FileManager.default.temporaryDirectory", "ExactAuditCapture.currentDirectory", 2)
    text = replace(text, "defer { try? FileManager.default.removeItem(at: directory) }", "// Synthetic diagnostic retains its private staging directory.", 2)
    text = replace(text, "process.standardOutput = outputPDF ? FileHandle.nullDevice : stdout\n        process.standardError = FileHandle.nullDevice",
        "let capture = try ExactAuditCapture.attach(process, directory: directory, stdout: outputPDF ? nil : stdout)\n        defer { capture.close() }")
    text = replace(text, "process.standardOutput = FileHandle.nullDevice\n        process.standardError = FileHandle.nullDevice",
        "let capture = try ExactAuditCapture.attach(process, directory: directory, stdout: nil)\n        defer { capture.close() }")
    text = replace(text, "        while process.isRunning {\n", "        while process.isRunning {\n            try capture.check()\n", 2)
    text = replace(text, "        try require(process.terminationReason == .exit && process.terminationStatus == 0,",
        "        try capture.check(); capture.record(process)\n        try require(process.terminationReason == .exit && process.terminationStatus == 0,")
    text = replace(text, "        return process.terminationStatus", "        try capture.check(); capture.record(process)\n        return process.terminationStatus")
    text = replace(text, "if password == nil { plainBytes = bytes }", "if password == nil { plainBytes = bytes; ExactAuditCapture.lastEditablePlain = bytes }")
    text = replace(text, 'guard let restored = result.page(at: 0) else { throw failure("A cópia de anotações perdeu sua página.") }',
        'try ExactAuditCapture.snapshot(result, label: password == nil ? "audit-result-plain" : "audit-result-protected")\n            guard let restored = result.page(at: 0) else { throw failure("A cópia de anotações perdeu sua página.") }')
    text = replace(text, "private static func verifyExplicitAnnotationGuards(base:", "static func verifyExplicitAnnotationGuards(base:")
    private_write(directory / "QPDFStructuralAudit.swift", text.encode())

    text = original["AnnotationEditing.swift"]
    marker = "/// Undo belongs to a document session; switching tabs never redirects an undo to another PDF."
    if text.count(marker) != 1:
        raise ValueError("Annotation helper boundary changed")
    private_write(directory / "AnnotationEditing.swift", text[:text.index(marker)].encode())
    text = (repository / "diagnostics" / "PDFKitDiagnosis.swift").read_text()
    text = replace(text, "@main\nstruct PDFKitDiagnosis", "struct PDFKitDiagnosis")
    text = replace(text, "private static func annotationSnapshot", "static func annotationSnapshot")
    text = replace(text, "private static func diagnosticJSON", "static func diagnosticJSON")
    text = replace(text, '(document.string ?? "").contains("PDF native verification"),\n              let page',
        '((document.string ?? "").contains("PDF native verification") || (document.string ?? "").contains("PDF structural verification")),\n              let page')
    text = replace(text, "FileHandle.standardOutput.write(bytes)", "// Incremental records remain in private files; avoid huge diagnostic stdout.")
    private_write(directory / "PDFKitDiagnosis.swift", text.encode())
    private_write(directory / "ExactSerializationDiagnosis.swift", (repository / "diagnostics" / "ExactSerializationDiagnosis.swift").read_bytes())
    manifest = {"baseRevision": BASE_REVISION, "originalSHA256": SOURCE_HASHES,
                "instrumentedSHA256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.glob("*.swift")},
                "scope": "synthetic audits only; original product sources unchanged"}
    private_write(directory / "source-manifest.json", json.dumps(manifest, indent=2).encode())
    return sorted(directory.glob("*.swift"))


def run_exact(repository, output, qpdf):
    from run_pdfkit_diagnostics import run, completed, object_relations
    output.mkdir(mode=0o700)
    sources = stage_sources(repository, output / "instrumented-sources")
    executable = output / "ExactSerializationDiagnosis"
    compiler = run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-parse-as-library", *map(str, sources),
                    "-o", str(executable), "-framework", "AppKit", "-framework", "PDFKit", "-framework", "CoreText"], seconds=180, output_limit=1024 * 1024)
    private_write(output / "compiler.json", json.dumps(compiler, indent=2).encode())
    if not completed(compiler) or compiler["exitCode"] != 0:
        print(compiler["stderr"], flush=True)
        raise ValueError("Exact synthetic diagnostic compilation failed")
    result = run([str(executable), str(output / "captures")], seconds=300, output_limit=1024 * 1024)
    # Capture credentials only belong to the generated synthetic fixtures.
    # Keep their files private for local reproduction; never print their values.
    secrets = set()
    jobs = []
    for path in (output / "captures").rglob("*.json"):
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("Exact diagnostic JSON exceeded 64 MiB")
        try:
            value = json.loads(path.read_bytes())
        except (ValueError, OSError):
            continue
        if isinstance(value, dict) and "inputFile" in value:
            jobs.append((path, value))
            for key in ("password", "userPassword", "ownerPassword"):
                for container in (value, value.get("encrypt", {})):
                    if isinstance(container.get(key), str) and container[key]:
                        secrets.add(container[key])
        if isinstance(value, dict) and isinstance(value.get("qpdf"), list) and len(value["qpdf"]) == 2:
            private_write(path.with_suffix(".relations.json"), json.dumps(object_relations(value["qpdf"][1]), indent=2).encode())
            annotations = annotation_metadata(value["qpdf"][1])
            private_write(path.with_suffix(".annotations.json"), json.dumps(annotations, indent=2).encode())
            if annotations:
                print("EXACT RAW ANNOTATIONS " + str(path.relative_to(output)) + ": " + json.dumps(annotations, ensure_ascii=False), flush=True)
    for path in (output / "captures").rglob("password.txt"):
        if path.stat().st_size <= 4096:
            secret = path.read_text().rstrip("\n")
            if secret:
                secrets.add(secret)
    def redact(text):
        for secret in sorted(secrets, key=len, reverse=True):
            text = text.replace(secret, "[synthetic-credential]")
        return text
    result = {key: redact(value) if isinstance(value, str) else value for key, value in result.items()}
    private_write(output / "execution.json", json.dumps(result, indent=2).encode())
    print(result["stdout"], flush=True)
    print(result["stderr"], flush=True)
    warnings = []
    for path in (output / "captures").rglob("trace-*.stderr"):
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Exact diagnostic stderr exceeded 1 MiB")
        message = redact(path.read_text(errors="replace"))
        if message.strip():
            warnings.append({"file": str(path.relative_to(output)), "stderr": message})
            print("EXACT QPDF STDERR " + str(path.relative_to(output)) + "\n" + message, flush=True)
    private_write(output / "qpdf-warnings.json", json.dumps(warnings, indent=2).encode())
    # Export final object dictionaries too, preserving original PDFs and each
    # writer's random synthetic staging credential in its existing private job.
    exported = set()
    for job_path, job in jobs:
        target = job.get("outputFile")
        if not isinstance(target, str) or target in exported or not target.endswith(".pdf") or not Path(target).is_file():
            continue
        exported.add(target)
        password = job.get("encrypt", {}).get("userPassword", job.get("password", ""))
        inspection = run([str(qpdf), "--password-file=-", "--json", "--json-key=qpdf", "--json-key=pages", "--json-stream-data=none", target],
                         password, output_limit=64 * 1024 * 1024)
        status = {key: redact(value) if isinstance(value, str) else value for key, value in inspection.items() if key != "stdout"}
        destination = Path(target).with_suffix(".qpdf-after.json")
        private_write(destination.with_suffix(".status.json"), json.dumps(status, indent=2).encode())
        if completed(inspection) and inspection["exitCode"] in (0, 3):
            value = json.loads(inspection["stdout"])
            private_write(destination, inspection["stdout"].encode())
            private_write(destination.with_suffix(".relations.json"), json.dumps(object_relations(value["qpdf"][1]), indent=2).encode())
            annotations = annotation_metadata(value["qpdf"][1])
            private_write(destination.with_suffix(".annotations.json"), json.dumps(annotations, indent=2).encode())
            if annotations:
                print("EXACT FINAL ANNOTATIONS " + str(destination.relative_to(output)) + ": " + json.dumps(annotations, ensure_ascii=False), flush=True)
    if not completed(result) or result["exitCode"] != 0:
        raise ValueError("Exact synthetic diagnostic process did not complete")
