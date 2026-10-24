#!/usr/bin/env python3
"""Real, synthetic IPC/browser probes; no product fallback or external input.

Run with the copied runtime's Python -I -B. The supervising diagnostic owns the
process group and its hard deadline. Exit zero requires a complete positive
report, including orderly child/browser shutdown; failures never fabricate PDF
or multiprocessing results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
from multiprocessing.managers import SyncManager
import os
from pathlib import Path
import secrets
import stat
import sys


def private_directory(path: Path) -> tuple[Path, int]:
    # Canonicalize the parent only: /var aliases are valid, a symlink leaf isn't.
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError("Private directory must be an absolute, named path.")
    canonical = path.parent.resolve(strict=True) / path.name
    fd = os.open(canonical, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("Directory must be owned by this user with mode 0700.")
        return canonical, fd
    except BaseException:
        os.close(fd)
        raise


def create_output(path: Path) -> tuple[int, int]:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError("Output must be an absolute, named file.")
    _, parent_fd = private_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent_fd)
        return fd, parent_fd
    except BaseException:
        os.close(parent_fd)
        raise


def populate_manager(values) -> None:
    values["value"] = 42
    values["childPID"] = os.getpid()


def reap(process) -> None:
    if process is None or process.pid is None:
        return
    process.join(timeout=1)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)
    if process.is_alive():
        raise RuntimeError("Owned diagnostic child did not exit.")


def multiprocessing_probe(ipc: Path, report: dict) -> None:
    context = multiprocessing.get_context("spawn")
    address = ipc / "manager.sock"
    if len(os.fsencode(address)) >= 104 or os.path.lexists(address):
        raise ValueError("Manager socket must be absent and fit the Unix address limit.")
    manager = SyncManager(address=str(address), authkey=secrets.token_bytes(32), ctx=context,
                          shutdown_timeout=2)
    child = None
    manager_process = None
    try:
        manager.start()
        manager_process = manager._process  # This is a diagnostic of the real owned child.
        report["managerPID"] = manager_process.pid
        report["managerAddress"] = str(manager.address)
        values = manager.dict()
        child = context.Process(target=populate_manager, args=(values,))
        child.start()
        report["childPID"] = child.pid
        child.join(timeout=15)
        if child.is_alive():
            raise TimeoutError("Spawned manager client exceeded its deadline.")
        report["childExitCode"] = child.exitcode
        report["value"] = values.get("value")
        observed_pid = values.get("childPID")
        if child.exitcode != 0 or report["value"] != 42 or observed_pid != child.pid:
            raise RuntimeError("Spawned client did not return the expected real result.")
        if len({os.getpid(), child.pid, manager_process.pid}) != 3:
            raise RuntimeError("Manager/client did not run in separate processes.")
        manager.shutdown()
        manager_process.join(timeout=3)
        report["managerExitCode"] = manager_process.exitcode
        report["managerShutdown"] = not manager_process.is_alive() and manager_process.exitcode == 0
        report["socketRemoved"] = not os.path.lexists(address)
        if not report["managerShutdown"] or not report["socketRemoved"]:
            raise RuntimeError("Manager did not complete normal shutdown and socket cleanup.")
    finally:
        reap(child)
        manager_process = manager_process or getattr(manager, "_process", None)
        if manager_process is not None and manager_process.is_alive():
            try:
                shutdown = getattr(manager, "shutdown", None)
                if shutdown is not None:
                    shutdown()
            finally:
                reap(manager_process)


def browser_probe(ipc: Path, executable: Path, report: dict) -> None:
    import pymupdf
    from playwright.sync_api import sync_playwright

    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("An executable local browser is required.")
    profile = ipc / "browser-profile"
    profile.mkdir(mode=0o700)
    expected = "Private IPC browser verification 42"
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), executable_path=str(executable), headless=True,
            timeout=20000, env={**os.environ, "TMPDIR": str(ipc), "MAC_CHROMIUM_TMPDIR": str(ipc)},
            args=["--disable-background-networking", "--disable-component-update", "--no-first-run"],
        )
        browser = context.browser
        try:
            # The fixture requires no network. Abort any page URL accidentally
            # introduced in a future edit, in addition to the runner's sandbox.
            context.route("**/*", lambda route: route.abort())
            page = context.pages[0] if context.pages else context.new_page()
            page.set_content('<!doctype html><html><head><meta charset="utf-8">'
                             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
                             '</head><body><h1>' + expected + '</h1><p>Local synthetic document.</p></body></html>',
                             wait_until="load", timeout=10000)
            data = page.pdf(format="A4", print_background=True)
            if not data.startswith(b"%PDF-") or not 128 <= len(data) <= 2 * 1024 * 1024:
                raise RuntimeError("Browser returned an invalid or excessive PDF.")
            fd = os.open(ipc / "browser.pdf", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            with pymupdf.open(stream=data, filetype="pdf") as document:
                report["pageCount"] = len(document)
                text = " ".join(" ".join(page.get_text() for page in document).split())
                report["recognizedTextMatched"] = expected in text
            report["browserPDFBytes"] = len(data)
            report["browserPDFSHA256"] = hashlib.sha256(data).hexdigest()
            if report["pageCount"] != 1 or not report["recognizedTextMatched"]:
                raise RuntimeError("The real PDF did not contain the expected one-page text.")
        finally:
            context.close()
            report["browserClosed"] = browser is not None and not browser.is_connected()
        if not report["browserClosed"]:
            raise RuntimeError("Browser connection remained open after closing the context.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("multiprocessing", "browser"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ipc", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    if args.mode == "browser" and args.browser_executable is None:
        parser.error("--browser-executable is required for browser mode")
    output_fd = parent_fd = ipc_fd = -1
    try:
        ipc, ipc_fd = private_directory(args.ipc)
        output_fd, parent_fd = create_output(args.output)
    except (OSError, ValueError):
        if ipc_fd >= 0:
            os.close(ipc_fd)
        print("Unsafe or unavailable diagnostic paths.", file=sys.stderr)
        return 2
    report = {"schemaVersion": 1, "mode": args.mode, "passed": False, "parentPID": os.getpid()}
    previous_umask = os.umask(0o077)
    # Shared ownership policy is installed only by this executable entrypoint.
    # Both checkout scripts/ and bundle Resources/distribution/ have ../engine.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
    from owned_process import cooperative_signals
    try:
        with cooperative_signals():
            if args.mode == "multiprocessing":
                multiprocessing_probe(ipc, report)
            else:
                browser_probe(ipc, args.browser_executable, report)
        report["passed"] = True
    except BaseException as error:
        report["errorType"] = type(error).__name__
        report["errorMessage"] = str(error)[:1000]
    finally:
        os.umask(previous_umask)
        try:
            data = (json.dumps(report, ensure_ascii=True, allow_nan=False) + "\n").encode()
            if len(data) > 16384:
                raise RuntimeError("Diagnostic report exceeded its limit.")
            with os.fdopen(output_fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        finally:
            os.close(ipc_fd)
            os.close(parent_fd)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
