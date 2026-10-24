"""Focused subprocess checks for the synthetic private-IPC diagnostic."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


WORKER = (Path(__file__).resolve().parents[1] / "scripts/private_ipc_worker.py").resolve()


class PrivateIPCWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ipc-test-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ipc = self.root / "ipc"
        self.ipc.mkdir(mode=0o700)
        self.output = self.root / "result.json"

    def invoke(self, ipc=None, output=None):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(WORKER), "--mode", "multiprocessing",
             "--ipc", str(ipc or self.ipc), "--output", str(output or self.output)],
            capture_output=True, timeout=25,
        )

    def test_real_spawn_manager_exchange_and_shutdown(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        report = json.loads(self.output.read_bytes())
        self.assertIs(report["passed"], True)
        self.assertEqual(len({report["parentPID"], report["managerPID"], report["childPID"]}), 3)
        self.assertEqual(report["value"], 42)
        self.assertEqual(report["childExitCode"], 0)
        self.assertEqual(report["managerExitCode"], 0)
        self.assertTrue(report["managerShutdown"] and report["socketRemoved"])
        self.assertFalse((self.ipc / "manager.sock").exists())
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        for pid in [report["managerPID"], report["childPID"]]:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_existing_report_and_symlink_are_never_replaced(self):
        self.output.write_bytes(b"preserve original")
        before = self.output.stat()
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.output.read_bytes(), b"preserve original")
        self.assertEqual(self.output.stat().st_ino, before.st_ino)
        linked = self.root / "linked.json"
        linked.symlink_to(self.output)
        self.assertEqual(self.invoke(output=linked).returncode, 2)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(self.output.read_bytes(), b"preserve original")

    def test_symlinked_or_nonprivate_ipc_directory_is_rejected(self):
        linked = self.root / "linked-ipc"
        linked.symlink_to(self.ipc, target_is_directory=True)
        self.assertEqual(self.invoke(ipc=linked).returncode, 2)
        self.assertFalse(self.output.exists())
        self.ipc.chmod(0o755)
        self.assertEqual(self.invoke().returncode, 2)
        self.assertFalse(self.output.exists())

    def test_occupied_manager_socket_fails_without_clobber(self):
        occupied = self.ipc / "manager.sock"
        occupied.write_bytes(b"not a socket; must survive")
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        report = json.loads(self.output.read_bytes())
        self.assertIs(report["passed"], False)
        self.assertEqual(report["errorType"], "ValueError")
        self.assertEqual(occupied.read_bytes(), b"not a socket; must survive")


if __name__ == "__main__":
    unittest.main()
