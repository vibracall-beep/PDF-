#!/usr/bin/env python3
"""Measure synthetic PDFKit output; this is not an application validation gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time

OWNER = "native-check-owner-123"
READER = "native-check-reader-123"
STAGING = "native-stage-only-456"
OUTPUT_LIMIT = 128 * 1024


def redacted(text):
    for secret in (OWNER, READER, STAGING):
        text = text.replace(secret, "[redacted]")
    return re.sub(r"(?im)^(\s*(?:user|owner)\s+password\s*=).*$", r"\1 [redacted]", text)


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run(arguments, password="", seconds=30, verbose=False, output_limit=OUTPUT_LIMIT):
    environment = dict(os.environ)
    environment["CG_PDF_VERBOSE"] = "1" if verbose else "0"
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True, env=environment)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = exceeded = False
    started = time.monotonic()
    try:
        try:
            process.stdin.write((password + "\n").encode())
            process.stdin.close()
        except BrokenPipeError:
            # --version and a rejected invocation can close stdin immediately.
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                if time.monotonic() - started > seconds:
                    timed_out = True
                    break
                for key, _ in selector.select(0.05):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = buffers[key.data]
                    available = output_limit - len(buffer)
                    buffer.extend(data[:available])
                    if len(data) > available:
                        exceeded = True
                        break
                if exceeded:
                    break
        if not (timed_out or exceeded):
            try:
                process.wait(timeout=max(0.01, seconds - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        stop(process)
        for name in buffers:
            getattr(process, name).close()
    return {"exitCode": process.returncode, "timedOut": timed_out,
            "outputLimitExceeded": exceeded,
            **{name: redacted(bytes(data).decode("utf-8", "replace")) for name, data in buffers.items()}}


def read_regular(path, limit=128 * 1024 * 1024):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Diagnostic file must be regular and within its size limit")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Diagnostic file exceeded its size limit")
        return data
    finally:
        os.close(descriptor)


def write_json(path, report):
    with path.open("x", encoding="utf-8") as destination:
        json.dump(report, destination, ensure_ascii=False, indent=2)
        destination.write("\n")


def completed(result):
    return not result["timedOut"] and not result["outputLimitExceeded"] and result["exitCode"] >= 0


def run_job(qpdf, job, directory):
    # qpdf's --job-json-file does not accept stdin. Match its documented file
    # interface, keeping credentials in a private file removed after reap.
    with tempfile.TemporaryDirectory(prefix=".qpdf-cycle-job-", dir=directory) as temporary:
        path = Path(temporary) / "job.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(job, output)
        return run([str(qpdf), "--job-json-file=" + str(path)])


def raw_appearance_token(object_text):
    """Return only /DA's PDF token, never unrelated AAPL archived metadata."""
    match = re.search(r"/DA\s+", object_text)
    if not match:
        return None
    start = match.end()
    if start >= len(object_text):
        return None
    if object_text[start] == "(":
        depth, escaped = 1, False
        for end in range(start + 1, len(object_text)):
            char = object_text[end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if not depth:
                    return object_text[start:end + 1][:4096]
        return None
    if object_text[start] == "<" and not object_text.startswith("<<", start):
        end = object_text.find(">", start + 1)
        return object_text[start:end + 1][:4096] if end >= 0 else None
    end = start + 1
    while end < len(object_text) and object_text[end] not in " \t\r\n()<>[]{}/%":
        end += 1
    return object_text[start:end][:4096]


def object_relations(objects):
    """Whitelist the field/page/annotation graph, including disconnected widgets."""
    edges = {"/Root", "/AcroForm", "/Fields", "/Kids", "/Parent", "/Pages", "/Annots", "/Popup"}
    scalar_keys = {"/Type", "/Subtype", "/FT", "/T", "/V", "/DV", "/Rect", "/Ff", "/F", "/Open", "/NM", "/Count"}
    allowed = edges | scalar_keys
    root = objects.get("trailer", {}).get("value", {}).get("/Root")
    result = {"root": root, "objects": {}}
    pending, seen = [], set()

    def visit(value):
        if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]* [0-9]+ R", value):
            pending.append(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key in edges:
                if key in value:
                    visit(value[key])

    def filtered(value):
        if isinstance(value, dict):
            return {key: filtered(child) for key, child in value.items() if key in allowed}
        if isinstance(value, list):
            return [filtered(child) for child in value]
        return value

    visit(root)
    for key, record in objects.items():
        value = record.get("value")
        if isinstance(value, dict) and (value.get("/Type") in ("/Catalog", "/Pages", "/Page", "/Annot")
                                     or "/FT" in value or ("/Subtype" in value and "/Rect" in value)):
            visit(key.removeprefix("obj:"))
    while pending and len(seen) < 1000:
        reference = pending.pop()
        if reference in seen:
            continue
        seen.add(reference)
        record = objects.get("obj:" + reference, {})
        # No stream dictionaries or bodies, including fonts/AP/AAPL archives.
        if "value" not in record:
            result["objects"][reference] = {"unavailableOrStream": True}
            continue
        value = record["value"]
        result["objects"][reference] = filtered(value)
        visit(value)
    result["objects"] = dict(sorted(result["objects"].items()))
    result["limitReached"] = bool(pending)
    return result


def free_text_details(qpdf, source, password):
    """Inspect only synthetic annotation metadata and Form appearance commands.

    qpdf JSON excludes every stream body. Only /AP /N Form streams are then
    decoded individually; FontFile*, ToUnicode and other streams are never read.
    """
    query = run([str(qpdf), "--password-file=-", "--json", "--json-key=qpdf",
                 "--json-stream-data=none", str(source)], password, output_limit=512 * 1024)
    report = {"jsonProcess": {key: value for key, value in query.items() if key != "stdout"},
              "fontProgramsIncluded": False, "annotations": [], "annotationScalarKeys": []}
    if not completed(query) or query["exitCode"] not in (0, 3):
        report["extractionError"] = "qpdf metadata query did not complete"
        return report
    try:
        payload = json.loads(query["stdout"])
        objects = payload["qpdf"][1]
        if not isinstance(objects, dict) or len(objects) > 10_000:
            raise ValueError("Invalid or excessive diagnostic object table")
    except (ValueError, KeyError, IndexError, TypeError):
        report["extractionError"] = "qpdf metadata response was invalid"
        return report
    report["objectCount"] = len(objects)
    report["objectRelations"] = object_relations(objects)

    def reference(value):
        match = re.fullmatch(r"([1-9][0-9]*) ([0-9]+) R", value) if isinstance(value, str) else None
        return (match[1] + "," + match[2]) if match else None

    def entry(value):
        return objects.get("obj:" + value, {}) if reference(value) else {}

    def resolved(value):
        record = entry(value)
        return record.get("value", record.get("stream", {}).get("dict", value))

    def dictionary(value):
        value = resolved(value)
        return value if isinstance(value, dict) else {}

    def font(value, depth=0):
        data = dictionary(value)
        result = {key: data[key] for key in ("/Type", "/Subtype", "/BaseFont", "/Encoding", "/FirstChar", "/LastChar") if key in data}
        result["reference"] = value if reference(value) else None
        descriptor = dictionary(data.get("/FontDescriptor"))
        result["descriptor"] = {key: descriptor[key] for key in (
            "/FontName", "/Flags", "/FontBBox", "/ItalicAngle", "/Ascent", "/Descent", "/CapHeight", "/StemV",
            "/FontFile", "/FontFile2", "/FontFile3") if key in descriptor}
        descendants = resolved(data.get("/DescendantFonts"))
        if depth < 2 and isinstance(descendants, list):
            result["descendants"] = [font(item, depth + 1) for item in descendants[:8]]
        return result

    def resources(value):
        data = dictionary(value)
        fonts = dictionary(data.get("/Font"))
        return {"reference": value if reference(value) else None,
                "fontCount": len(fonts), "fonts": {name: font(value) for name, value in sorted(fonts.items())[:32]}}

    catalog = next((record.get("value", {}) for record in objects.values()
                    if isinstance(record.get("value"), dict) and record["value"].get("/Type") == "/Catalog"), {})
    acro = dictionary(catalog.get("/AcroForm"))
    report["acroForm"] = {"DA": acro.get("/DA"), "DS": acro.get("/DS"), "DR": resources(acro.get("/DR"))}
    report["pageResources"] = [resources(record["value"].get("/Resources")) for record in objects.values()
                               if isinstance(record.get("value"), dict) and record["value"].get("/Type") == "/Page"][:4]
    for object_name, record in objects.items():
        annotation = record.get("value", {})
        if isinstance(annotation, dict) and (annotation.get("/Type") == "/Annot" or ("/Rect" in annotation and "/Subtype" in annotation)):
            report["annotationScalarKeys"].append({"object": object_name, **{key: annotation[key] for key in
                ("/Subtype", "/Contents", "/T", "/V", "/DV", "/Opt", "/DA", "/DS", "/Parent", "/Popup", "/Open", "/NM", "/Rect") if key in annotation}})
        if not isinstance(annotation, dict) or annotation.get("/Subtype") != "/FreeText":
            continue
        if len(report["annotations"]) >= 20:
            report["extractionError"] = "Too many synthetic FreeText annotations"
            break
        item = {"object": object_name, "DA": annotation.get("/DA"), "DS": annotation.get("/DS"),
                "DR": resources(annotation.get("/DR")), "appearance": []}
        # This is the known synthetic FreeText dictionary, never a stream.
        # Preserve qpdf's PDF token spelling to distinguish #20 from #2320;
        # JSON's decoded name alone cannot establish the original escaping.
        object_reference = reference(object_name.removeprefix("obj:"))
        if object_reference:
            raw = run([str(qpdf), "--password-file=-",
                "--show-object=" + object_reference, str(source)], password, output_limit=16 * 1024)
            token = raw_appearance_token(raw["stdout"])
            item["rawObjectByteCount"] = len(raw["stdout"].encode())
            raw["stdout"] = "/DA " + token if token is not None else ""
            item["rawObjectProcess"] = raw
            item["rawDefaultAppearanceToken"] = token
        report["annotations"].append(item)
        normal = dictionary(annotation.get("/AP")).get("/N")
        states = [("normal", normal)] if reference(normal) else list(dictionary(normal).items())[:8]
        for state, target in states:
            stream = entry(target).get("stream", {}).get("dict", {})
            appearance = {"state": state, "reference": target, "dictionary": stream,
                          "resources": resources(stream.get("/Resources"))}
            item["appearance"].append(appearance)
            # Never use --filtered-stream-data on a font program or unknown
            # object: the permitted target must be the annotation's /AP /N Form.
            if reference(target) and stream.get("/Subtype") == "/Form":
                command = run([str(qpdf), "--password-file=-", "--show-object=" + reference(target),
                               "--filtered-stream-data", str(source)], password, output_limit=32 * 1024)
                appearance["commandsProcess"] = command
            else:
                appearance["commandsSkipped"] = "AP/N is not an indirect Form appearance stream"
    return report


def serialization_cycles(executable, qpdf, directory, source, report):
    report["serializationCycles"] = []
    original_hash = hashlib.sha256(read_regular(source)).hexdigest()
    for name in ("altered-widget-plain", "existing-aes256"):
        cycle = {"name": name, "sourceSHA256": original_hash, "rewrites": []}
        report["serializationCycles"].append(cycle)
        input_path = source
        if name == "altered-widget-plain":
            cycle["inputCheck"] = run([str(qpdf), "--password-file=-", "--check", str(input_path)])
        if name == "existing-aes256":
            input_path = directory / "cycle-input-aes256.pdf"
            job = {"inputFile": str(source), "outputFile": str(input_path),
                   "encrypt": {"userPassword": READER, "ownerPassword": OWNER, "256bit": {}}}
            cycle["encryptInput"] = run_job(qpdf, job, directory)
            if not input_path.exists():
                cycle["error"] = "AES256 fixture was not generated"
                continue
            cycle["inputCheck"] = run([str(qpdf), "--password-file=-", "--check", str(input_path)], READER)
            cycle["inputEncryption"] = run([str(qpdf), "--password-file=-", "--show-encryption", str(input_path)], READER)
        private = directory / (name + "-swift")
        command = "reserialize-edited" if name == "altered-widget-plain" else "reserialize-protected"
        cycle["nativeReserialization"] = run([str(executable), command, str(input_path), str(private)], verbose=True)
        raw = private / ("edited.pdf" if name == "altered-widget-plain" else "protected.pdf")
        password = "" if name == "altered-widget-plain" else STAGING
        for key, filename in (("before", "before.json"), ("expected", "expected.json"), ("rawReopened", "after.json"), ("nativeStatus", "status.json")):
            if (private / filename).exists():
                cycle[key] = json.loads(read_regular(private / filename, 1024 * 1024))
        if not raw.exists():
            cycle["error"] = "Native reserialization did not create a result"
            print("SERIALIZATION CYCLE " + name + ": " + json.dumps(cycle, ensure_ascii=False, sort_keys=True), flush=True)
            continue
        raw_hash = hashlib.sha256(read_regular(raw)).hexdigest()
        cycle["rawSHA256"] = raw_hash
        cycle["rawCheck"] = run([str(qpdf), "--password-file=-", "--check", str(raw)], password)
        raw_details = free_text_details(qpdf, raw, password)
        cycle["rawRelations"] = {key: raw_details[key] for key in ("jsonProcess", "objectRelations", "extractionError") if key in raw_details}
        cycle["rawEncryption"] = run([str(qpdf), "--password-file=-", "--show-encryption", str(raw)], password)
        for mode in ("preserve", "default"):
            normalized = directory / (name + "-" + mode + ".pdf")
            record = {"mode": mode}
            cycle["rewrites"].append(record)
            settings = {"objectStreams": "preserve", "streamData": "preserve"} if mode == "preserve" else {"objectStreams": "disable"}
            job = {"inputFile": str(raw), "password": password, "outputFile": str(normalized), **settings}
            if password:
                job["encrypt"] = {"userPassword": READER, "ownerPassword": OWNER, "256bit": {}}
            record["rewrite"] = run_job(qpdf, job, directory)
            if not normalized.exists():
                continue
            target_password = READER if password else ""
            record["check"] = run([str(qpdf), "--password-file=-", "--check", str(normalized)], target_password)
            details = free_text_details(qpdf, normalized, target_password)
            record["relations"] = {key: details[key] for key in ("jsonProcess", "objectRelations", "extractionError") if key in details}
            record["encryption"] = run([str(qpdf), "--password-file=-", "--show-encryption", str(normalized)], target_password)
            inspection = directory / (name + "-" + mode + ".json")
            record["inspectionProcess"] = run([str(executable), "inspect-annotations", str(normalized), str(inspection)], verbose=True)
            if inspection.exists():
                record["snapshot"] = json.loads(read_regular(inspection, 1024 * 1024))
                record["snapshotExactlyEqualsRaw"] = record["snapshot"] == cycle.get("rawReopened")
                if "expected" in cycle:
                    record["snapshotExactlyEqualsExpected"] = record["snapshot"] == cycle["expected"]
        cycle["rawUnchanged"] = hashlib.sha256(read_regular(raw)).hexdigest() == raw_hash
        cycle["sourceUnchanged"] = hashlib.sha256(read_regular(source)).hexdigest() == original_hash
        if not cycle["rawUnchanged"] or not cycle["sourceUnchanged"]:
            raise ValueError("A serialization-cycle original was modified")
        print("SERIALIZATION CYCLE " + name + ": " + json.dumps(cycle, ensure_ascii=False, sort_keys=True), flush=True)


def process_results(value):
    if isinstance(value, dict):
        if "exitCode" in value and "timedOut" in value and "outputLimitExceeded" in value:
            yield value
        for child in value.values():
            yield from process_results(child)
    elif isinstance(value, list):
        for child in value:
            yield from process_results(child)


def annotation_measurements(executable, qpdf, directory, report):
    fixtures = directory / "annotation-fixtures"
    # Nine fixed synthetic scenarios, including before/after font identity,
    # legitimately exceed the ordinary 128 KiB per-process log bound.
    generated = run([str(executable), "annotations", str(fixtures)], verbose=True, output_limit=1024 * 1024)
    report["annotationGeneration"] = generated
    report["annotationRecords"] = []
    if generated["stdout"]:
        print("ANNOTATION INCREMENTAL RECORDS\n" + generated["stdout"], flush=True)
    if not completed(generated) or generated["exitCode"] != 0:
        print("Annotation generation did not complete: " + generated["stderr"], flush=True)
        raise ValueError("Synthetic annotation generation did not complete successfully")
    for scenario in ("smoke", "preview-note", "editable-defaults", "editable-materialized", "editable-resolved-font", "editable-helvetica15",
                     "editable-space-da-system13", "editable-space-da-helvetica15", "slash-string-values"):
        before = json.loads(read_regular(fixtures / (scenario + ".before.json"), 1024 * 1024))
        materialized = None
        if scenario in ("editable-materialized", "editable-resolved-font", "editable-helvetica15",
                        "editable-space-da-system13", "editable-space-da-helvetica15"):
            materialized = json.loads(read_regular(fixtures / (scenario + ".materialized.json"), 1024 * 1024))
            print("ANNOTATIONS MATERIALIZED " + scenario + ": " + json.dumps(materialized, ensure_ascii=False, sort_keys=True), flush=True)
        # Every value printed here originates exclusively from our generated
        # fixture. The regular inspect mode does not dump annotation contents.
        print("ANNOTATIONS BEFORE " + scenario + ": " + json.dumps(before, ensure_ascii=False, sort_keys=True), flush=True)
        for protected in (False, True):
            name = scenario + (".protected" if protected else "")
            source = fixtures / (name + ".pdf")
            password = READER if protected else ""
            original_hash = hashlib.sha256(read_regular(source)).hexdigest()
            record = {"name": name, "before": before, "originalSHA256": original_hash}
            if materialized is not None:
                record["afterMaterialization"] = materialized
            if scenario == "editable-resolved-font":
                record["fontAssignment"] = json.loads(read_regular(fixtures / (scenario + ".font-assignment.json"), 1024 * 1024))
                print("FONT ASSIGNMENT " + name + ": " + json.dumps(record["fontAssignment"], ensure_ascii=False, sort_keys=True), flush=True)
            if scenario.startswith("editable-space-da-"):
                record["appearanceAssignment"] = json.loads(read_regular(fixtures / (scenario + ".da-assignment.json"), 1024 * 1024))
                print("DA ASSIGNMENT " + name + ": " + json.dumps(record["appearanceAssignment"], ensure_ascii=False, sort_keys=True), flush=True)
            report["annotationRecords"].append(record)
            record["originalCheck"] = run([str(qpdf), "--password-file=-", "--check", str(source)], password)
            if scenario.startswith("editable-") or scenario == "slash-string-values":
                record["originalFreeText"] = free_text_details(qpdf, source, password)
                print("FREETEXT ORIGINAL " + name + ": " + json.dumps(record["originalFreeText"], ensure_ascii=False, sort_keys=True), flush=True)
            original_json = directory / (name + ".annotations-original.json")
            record["originalInspection"] = run([str(executable), "inspect-annotations", str(source), str(original_json)], verbose=True)
            if completed(record["originalInspection"]) and record["originalInspection"]["exitCode"] == 0:
                record["original"] = json.loads(read_regular(original_json, 1024 * 1024))
                print("ANNOTATIONS ORIGINAL " + name + ": " + json.dumps(record["original"], ensure_ascii=False, sort_keys=True), flush=True)
            normalized = directory / (name + ".annotations-normalized.pdf")
            record["normalization"] = run([str(qpdf), "--password-file=-", "--object-streams=disable", str(source), str(normalized)], password)
            if normalized.exists():
                record["normalizedCheck"] = run([str(qpdf), "--password-file=-", "--check", str(normalized)], password)
                if scenario.startswith("editable-") or scenario == "slash-string-values":
                    record["normalizedFreeText"] = free_text_details(qpdf, normalized, password)
                    print("FREETEXT NORMALIZED " + name + ": " + json.dumps(record["normalizedFreeText"], ensure_ascii=False, sort_keys=True), flush=True)
                normalized_json = directory / (name + ".annotations-normalized.json")
                record["normalizedInspection"] = run([str(executable), "inspect-annotations", str(normalized), str(normalized_json)], verbose=True)
                if completed(record["normalizedInspection"]) and record["normalizedInspection"]["exitCode"] == 0:
                    record["normalized"] = json.loads(read_regular(normalized_json, 1024 * 1024))
                    print("ANNOTATIONS NORMALIZED " + name + ": " + json.dumps(record["normalized"], ensure_ascii=False, sort_keys=True), flush=True)
            record["originalUnchanged"] = hashlib.sha256(read_regular(source)).hexdigest() == original_hash
            if not record["originalUnchanged"]:
                raise ValueError("An original annotation fixture was modified")


def measure(executable, qpdf, directory):
    directory.mkdir(mode=0o700)
    fixtures = directory / "fixtures"
    report = {"schemaVersion": 1, "scope": "synthetic-pdfkit-structural-diagnosis",
              "productValidation": False, "sourceCommit": os.environ.get("GITHUB_SHA"),
              "records": []}
    try:
        report["qpdfVersion"] = run([str(qpdf), "--version"])
        annotation_measurements(executable, qpdf, directory, report)
        report["generation"] = run([str(executable), "generate", str(fixtures)], verbose=True)
        if not completed(report["generation"]) or report["generation"]["exitCode"] != 0:
            raise ValueError("Synthetic fixture generation did not complete successfully")
        originals = {name: hashlib.sha256(read_regular(fixtures / name)).hexdigest()
                     for name in ("source.pdf", "copy.pdf", "protected.pdf")}
        for name in originals:
            source = fixtures / name
            password = READER if name == "protected.pdf" else ""
            item = {"name": name, "originalSHA256": originals[name]}
            report["records"].append(item)
            item["originalCheck"] = run([str(qpdf), "--password-file=-", "--check", str(source)], password)
            item["originalEncryption"] = run([str(qpdf), "--password-file=-", "--show-encryption", str(source)], password)
            inspection = directory / (name + ".original-reader.json")
            item["originalReaderProcess"] = run([str(executable), "inspect", str(source), str(inspection)], verbose=True)
            if completed(item["originalReaderProcess"]) and item["originalReaderProcess"]["exitCode"] == 0:
                item["originalReader"] = json.loads(read_regular(inspection, 1024 * 1024))
            normalized = directory / ("normalized-" + name)
            item["normalization"] = run([str(qpdf), "--password-file=-", "--object-streams=disable",
                                         str(source), str(normalized)], password)
            if normalized.exists():
                item["normalizedSHA256"] = hashlib.sha256(read_regular(normalized)).hexdigest()
                item["normalizedCheck"] = run([str(qpdf), "--password-file=-", "--check", str(normalized)], password)
                item["normalizedEncryption"] = run([str(qpdf), "--password-file=-", "--show-encryption", str(normalized)], password)
                inspection = directory / (name + ".normalized-reader.json")
                item["normalizedReaderProcess"] = run([str(executable), "inspect", str(normalized), str(inspection)], verbose=True)
                if completed(item["normalizedReaderProcess"]) and item["normalizedReaderProcess"]["exitCode"] == 0:
                    item["normalizedReader"] = json.loads(read_regular(inspection, 1024 * 1024))
            print(name + ": original qpdf exit " + str(item["originalCheck"]["exitCode"]) +
                  "; normalization exit " + str(item["normalization"]["exitCode"]) +
                  "; normalized qpdf exit " + str(item.get("normalizedCheck", {}).get("exitCode")), flush=True)
        cycle_source = directory / "normalized-copy.pdf"
        serialization_cycles(executable, qpdf, directory, cycle_source if cycle_source.exists() else fixtures / "copy.pdf", report)
        report["originalsUnchanged"] = all(hashlib.sha256(read_regular(fixtures / name)).hexdigest() == digest
                                           for name, digest in originals.items())
        if not report["originalsUnchanged"]:
            raise ValueError("An original fixture changed during diagnostic measurement")
        if not all(completed(result) for result in process_results(report)):
            raise ValueError("A diagnostic subprocess was interrupted, timed out or exceeded its output bound")
        report["measurementComplete"] = True
    except Exception as error:
        report["measurementComplete"] = False
        report["measurementError"] = redacted(type(error).__name__ + ": " + str(error))
        raise
    finally:
        write_json(directory / "PDFKit-diagnostics.json", report)
        if "annotationGeneration" in report:
            write_json(directory / "annotation-generation-process.json", report["annotationGeneration"])
        for item in report["records"]:
            for key, value in item.items():
                if isinstance(value, dict) and "stderr" in value:
                    with (directory / (item["name"] + "." + key + ".log")).open("x") as log:
                        log.write("stdout (redacted):\n" + value["stdout"] + "\nstderr (redacted):\n" + value["stderr"])
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as output:
                output.write("### Synthetic PDFKit structural measurement\n\nThis diagnostic does not approve the application. Original bytes, independent qpdf statuses, encryption details and PDFKit reopening results are retained in the artifact.\n\n")
                for item in report["records"]:
                    output.write("- " + item["name"] + ": original check " + str(item.get("originalCheck", {}).get("exitCode")) +
                                 "; normalized check " + str(item.get("normalizedCheck", {}).get("exitCode")) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--qpdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exact-only", action="store_true", help="Run instrumented copies of the exact d3b3857 editable-annotation audits on synthetic inputs only")
    args = parser.parse_args()
    if args.exact_only:
        from run_exact_serialization import run_exact
        run_exact(Path(__file__).resolve().parents[1], args.output, args.qpdf.resolve(strict=True))
    else:
        measure(args.executable.resolve(strict=True), args.qpdf.resolve(strict=True), args.output)
