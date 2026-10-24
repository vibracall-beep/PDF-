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
import time

OWNER = "native-check-owner-123"
READER = "native-check-reader-123"
OUTPUT_LIMIT = 128 * 1024


def redacted(text):
    for secret in (OWNER, READER):
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


def run(arguments, password="", seconds=30, verbose=False):
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
                    available = OUTPUT_LIMIT - len(buffer)
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


def annotation_measurements(executable, qpdf, directory, report):
    fixtures = directory / "annotation-fixtures"
    generated = run([str(executable), "annotations", str(fixtures)], verbose=True)
    report["annotationGeneration"] = generated
    report["annotationRecords"] = []
    if generated["stdout"]:
        print("ANNOTATION INCREMENTAL RECORDS\n" + generated["stdout"], flush=True)
    if not completed(generated) or generated["exitCode"] != 0:
        print("Annotation generation did not complete: " + generated["stderr"], flush=True)
        raise ValueError("Synthetic annotation generation did not complete successfully")
    for scenario in ("smoke", "preview-note", "editable-defaults", "editable-materialized"):
        before = json.loads(read_regular(fixtures / (scenario + ".before.json"), 1024 * 1024))
        materialized = None
        if scenario == "editable-materialized":
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
            report["annotationRecords"].append(record)
            record["originalCheck"] = run([str(qpdf), "--password-file=-", "--check", str(source)], password)
            original_json = directory / (name + ".annotations-original.json")
            record["originalInspection"] = run([str(executable), "inspect-annotations", str(source), str(original_json)], verbose=True)
            if completed(record["originalInspection"]) and record["originalInspection"]["exitCode"] == 0:
                record["original"] = json.loads(read_regular(original_json, 1024 * 1024))
                print("ANNOTATIONS ORIGINAL " + name + ": " + json.dumps(record["original"], ensure_ascii=False, sort_keys=True), flush=True)
            normalized = directory / (name + ".annotations-normalized.pdf")
            record["normalization"] = run([str(qpdf), "--password-file=-", "--object-streams=disable", str(source), str(normalized)], password)
            if normalized.exists():
                record["normalizedCheck"] = run([str(qpdf), "--password-file=-", "--check", str(normalized)], password)
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
        report["originalsUnchanged"] = all(hashlib.sha256(read_regular(fixtures / name)).hexdigest() == digest
                                           for name, digest in originals.items())
        if not report["originalsUnchanged"]:
            raise ValueError("An original fixture changed during diagnostic measurement")
        processes = [report["qpdfVersion"], report["generation"], report["annotationGeneration"]]
        processes.extend(value for item in report["records"] for value in item.values()
                         if isinstance(value, dict) and "exitCode" in value)
        processes.extend(value for item in report["annotationRecords"] for value in item.values()
                         if isinstance(value, dict) and "exitCode" in value)
        if not all(completed(result) for result in processes):
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
    args = parser.parse_args()
    measure(args.executable.resolve(strict=True), args.qpdf.resolve(strict=True), args.output)
