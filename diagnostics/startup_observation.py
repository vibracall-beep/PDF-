"""Observe startup in an instrumented private checkout; never approve the app."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from owned_process import OwnedProcess, cooperative_signals

SOURCE_HASHES = {
    "PDFApp.swift": "8d8d58fb360bfc2aca1fbb6cf9f77aa214b371af9f7ad0d7f5d517e8619a9982",
    "MacPreview.swift": "61945246fa6944531807d120bbf19ebef672c3b11a6e1e248ea147d186585c21",
    "WorkspaceLifecycle.swift": "c03a1a51a2f717d0564684ae054ebc55dfa3970e66cc7d5836bc33c232498ba9",
}
SOURCE_REFERENCE = "e9af24a1bd9babe886ec74a9d96e97feb153a2bf"
LIMITATION = (
    "Diagnostic copy only. Genuine SwiftUI WindowGroup and normal installer; "
    "capture sequence pauses after attachment/activation before fixtures or subprocesses. "
    "No PNG, OCR, accessibility, packaging or product approval is inferred."
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Startup diagnostic requires one exact anchor: " + old[:80])
    return text.replace(old, new, 1)


def instrument(name, data):
    if digest(data) != SOURCE_HASHES[name]:
        raise ValueError("Startup diagnostic source hash changed: " + name)
    text = data.decode("utf-8")
    if name == "PDFApp.swift":
        return replace(text, "        WindowGroup {\n", '        WindowGroup {\n            let _ = PreviewStartupTrace.record("WindowGroup content builder evaluated")\n')
    if name == "MacPreview.swift":
        text = replace(text, 'static func record(_ phase: StaticString) {', 'static func record(_ phase: StaticString, details: String = "") {')
        text = replace(text, 'swiftTask=\\(hasSwiftTask)\\n"', 'swiftTask=\\(hasSwiftTask)\\(details)\\n"')
        marker = "\n}\n\n/// Captures the real WindowServer-composited application surface"
        state = '''
    @MainActor static func applicationState(_ phase: StaticString, defaultLaunch: Bool? = nil) {
        guard CommandLine.arguments.contains("--render-preview") else { return }
        guard let app = NSApp else { record(phase, details: "; application=absent"); return }
        let windows = app.windows
        let details = "; policy=\\(app.activationPolicy().rawValue); running=\\(app.isRunning); active=\\(app.isActive); windows=\\(windows.count); visible=\\(windows.filter(\\.isVisible).count); contentViews=\\(windows.filter { $0.contentView != nil }.count); key=\\(app.keyWindow != nil); main=\\(app.mainWindow != nil); defaultLaunch=\\(defaultLaunch.map { String($0) } ?? "unknown")"
        record(phase, details: details)
    }
'''
        text = replace(text, marker, state + marker)
        return replace(text, "        watchdog = Task { @MainActor [weak self] in\n", '''        if ProcessInfo.processInfo.environment["PDF_STARTUP_OBSERVATION_ONLY"] == "1" {
            PreviewStartupTrace.applicationState("diagnostic WindowGroup attached; capture sequence paused")
            return
        }
        watchdog = Task { @MainActor [weak self] in
''')
    if name == "WorkspaceLifecycle.swift":
        text = replace(text, 'PreviewStartupTrace.record("application will finish launching")', 'PreviewStartupTrace.applicationState("application will finish launching")')
        return replace(text, '        PreviewStartupTrace.record("application did finish launching")', '''        let defaultLaunch = (notification.userInfo?[NSApplication.launchIsDefaultUserInfoKey] as? NSNumber)?.boolValue
        PreviewStartupTrace.applicationState("application did finish launching", defaultLaunch: defaultLaunch)
        if CommandLine.arguments.contains("--render-preview") {
            DispatchQueue.main.async {
                PreviewStartupTrace.applicationState("post-launch main queue turn", defaultLaunch: defaultLaunch)
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                PreviewStartupTrace.applicationState("post-launch two-second observation", defaultLaunch: defaultLaunch)
            }
        }''')
    raise ValueError("Unexpected instrumentation target")


def prepare(repository, output):
    repository = repository.resolve(strict=True)
    originals = {name: (repository / "Sources/PDF" / name).read_bytes() for name in SOURCE_HASHES}
    patched = {name: instrument(name, data).encode() for name, data in originals.items()}
    commit = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    tracked = subprocess.check_output(["git", "-C", str(repository), "ls-files", "-z"]).split(b"\0")
    output.mkdir(mode=0o700)
    source = output / "source"; source.mkdir(mode=0o700)
    evidence = output / "evidence"; evidence.mkdir(mode=0o700)
    for raw in tracked:
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe tracked path")
        original = repository / relative
        if not stat.S_ISREG(original.lstat().st_mode):
            raise ValueError("Diagnostic checkout requires regular tracked files")
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    changes = []
    for name, data in patched.items():
        destination = source / "Sources/PDF" / name
        if destination.read_bytes() != originals[name]:
            raise ValueError("Source changed while staging " + name)
        destination.write_bytes(data)
        diff = "".join(difflib.unified_diff(originals[name].decode().splitlines(True), data.decode().splitlines(True), fromfile="original/" + name, tofile="diagnostic/" + name))
        private_write(evidence / (name + ".patch"), diff.encode())
        changes.append({"path": "Sources/PDF/" + name, "before_sha256": digest(originals[name]), "after_sha256": digest(data)})
    manifest = {"schema": 1, "checkout_commit": commit, "source_reference": SOURCE_REFERENCE, "changes": changes, "limitation": LIMITATION,
                "installer_sha256": digest((source / "scripts/install-mac.sh").read_bytes()),
                "run": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    private_write(evidence / "instrumentation.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print("Private instrumented checkout prepared; original sources unchanged.")


def summarize(text):
    markers = {
        "entry": "entrypoint begin; acquire bundle lease",
        "body": "PDFApp body evaluated",
        "did_finish": "application did finish launching",
        "main_queue": "post-launch main queue turn",
        "two_seconds": "post-launch two-second observation",
        "scene_content": "WindowGroup content builder evaluated",
        "attached": "diagnostic WindowGroup attached; capture sequence paused",
    }
    seen = {name: phrase in text for name, phrase in markers.items()}
    states = []
    for line in text.splitlines():
        if not line.startswith("PDF preview startup:"):
            continue
        values = dict(re.findall(r"\b(policy|running|active|windows|visible|contentViews|key|main|defaultLaunch)=([^;\s]+)", line))
        if "windows" in values and "visible" in values:
            states.append(values)
    visible = any(value.get("visible", "0").isdigit() and int(value["visible"]) > 0 for value in states)
    present = any(value.get("windows", "0").isdigit() and int(value["windows"]) > 0 for value in states)
    responsive = seen["main_queue"] and seen["two_seconds"]
    if seen["attached"]:
        status = "window_attached" if all(seen.values()) and visible else "attached_without_observed_visibility" if not visible else "attachment_observation_incomplete"
    else:
        status = "windowgroup_not_attached" if seen["did_finish"] and responsive else "incomplete"
    return {"status": status, "markers": seen, "main_queue_responsive": responsive,
            "window_observation": "visible" if visible else "present_hidden" if present else "none" if states else "unknown",
            "lifecycle_samples": states, "product_approval": "not_evaluated"}


def observe(app, evidence, seconds):
    if sys.platform != "darwin":
        raise ValueError("Startup observation requires a native macOS runner")
    binary = app.resolve(strict=True) / "Contents/MacOS/PDF"
    if not binary.is_file() or not evidence.is_dir() or not 5 <= seconds <= 45:
        raise ValueError("Invalid installed bundle, evidence directory or observation limit")
    info = binary.parents[1] / "Info.plist"
    bundle_identity = {"executable_sha256": digest(binary.read_bytes()), "info_plist_sha256": digest(info.read_bytes())}
    reports = []
    for number in (1, 2):
        trial = evidence / f"launch-{number}"; trial.mkdir(mode=0o700)
        log = trial / "startup.log"
        started = time.monotonic(); child = None; timeout = False; cleanup_error = None; driver_error = None
        env = dict(os.environ, PDF_STARTUP_OBSERVATION_ONLY="1")
        with log.open("xb") as stream:
            os.chmod(log, 0o600)
            try:
                child = OwnedProcess([str(binary), "--render-preview", str(trial / "PDF-preview.png")],
                                     stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, env=env)
                child.wait(seconds)
            except subprocess.TimeoutExpired:
                timeout = True  # Expected observation stop, never a product pass.
            except Exception as error:
                driver_error = type(error).__name__
            finally:
                if child is not None:
                    try:
                        child.close()
                    except BaseException as error:
                        cleanup_error = type(error).__name__
        data = log.read_bytes(); report = summarize(data.decode("utf-8", errors="replace"))
        report.update({"launch": number, "seconds": time.monotonic() - started, "deadline_seconds": seconds,
                       "observation_deadline_reached": timeout, "owned_pid": child.pid if child else None,
                       "returncode": child.returncode if child else None,
                       "cleanup_confirmed": child.cleanup_confirmed if child else False, "cleanup_error": cleanup_error,
                       "driver_error": driver_error,
                       "log_sha256": digest(data), "log_bytes": len(data), "limitation": LIMITATION})
        if driver_error or not timeout:
            report["status"] = "observation_incomplete"
        if child is not None and not report["cleanup_confirmed"]:
            report["status"] = "cleanup_incomplete"
        private_write(trial / "observation.json", (json.dumps(report, indent=2) + "\n").encode())
        reports.append(report)
        print(json.dumps({"launch": number, "status": report["status"], "product_approval": "not_evaluated"}))
        if cleanup_error:
            break
    bundle_unchanged = bundle_identity == {"executable_sha256": digest(binary.read_bytes()), "info_plist_sha256": digest(info.read_bytes())}
    private_write(evidence / "observations.json", (json.dumps({"schema": 1, "bundle": bundle_identity, "bundle_unchanged": bundle_unchanged,
                  "launches": reports, "limitation": LIMITATION}, indent=2) + "\n").encode())
    return 0 if bundle_unchanged and len(reports) == 2 and all(row["status"] == "window_attached" and row["cleanup_confirmed"] for row in reports) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    staging = commands.add_parser("prepare"); staging.add_argument("--repository", type=Path, required=True); staging.add_argument("--output", type=Path, required=True)
    running = commands.add_parser("observe"); running.add_argument("--app", type=Path, required=True); running.add_argument("--evidence", type=Path, required=True); running.add_argument("--seconds", type=float, default=45)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.repository, args.output); return 0
    with cooperative_signals():
        return observe(args.app, args.evidence, args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
