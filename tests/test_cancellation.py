"""Cancel an external conversion through the same SIGINT used by the macOS UI."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class CancellationTests(unittest.TestCase):
    def test_interrupt_stops_converter_and_publishes_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_directory = root / 'bin'
            bin_directory.mkdir()
            pid_file = root / 'converter.pid'
            # A real installed runtime can live under 'Application Support'.
            # Exercise that path shape even on Linux: kernel shebang parsing does
            # not support a Python interpreter pathname containing spaces.
            runtime = root / 'runtime with spaces'
            runtime.mkdir()
            interpreter = runtime / 'python3'
            interpreter.symlink_to(sys.executable)
            child_script = root / 'converter child.py'
            child_script.write_text(
                'import os, time\n'
                'from pathlib import Path\n'
                'Path(os.environ["PDF_TEST_CHILD_PID"]).write_text(str(os.getpid()))\n'
                'time.sleep(30)\n',
                encoding='utf-8',
            )
            executable = bin_directory / 'soffice'
            executable.write_text(
                '#!/bin/sh\nexec ' + shlex.quote(str(interpreter)) + ' '
                + shlex.quote(str(child_script)) + ' "$@"\n',
                encoding='utf-8',
            )
            executable.chmod(0o755)
            source = root / 'sample.docx'
            source.write_bytes(b'converter cancellation fixture')
            target = root / 'cancelled.pdf'
            engine = Path(__file__).resolve().parents[1] / 'engine' / 'pdf_engine.py'
            environment = os.environ.copy()
            environment['PATH'] = str(bin_directory) + os.pathsep + environment.get('PATH', '')
            environment['PDF_TEST_CHILD_PID'] = str(pid_file)
            parent = subprocess.Popen(
                [sys.executable, str(engine), 'office', str(source), '--output', str(target)],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 5
                while parent.poll() is None and time.monotonic() < deadline:
                    if pid_file.exists():
                        ready = pid_file.read_text().strip()
                        if ready.isdecimal():
                            child_pid = int(ready)
                            break
                    time.sleep(0.02)
                self.assertIsNotNone(child_pid, 'The fixture converter must actually start before cancellation.')
                parent.send_signal(signal.SIGINT)
                stdout, stderr = parent.communicate(timeout=8)
                self.assertEqual(parent.returncode, 130)
                failure = json.loads(stderr)
                self.assertEqual(failure["code"], "Cancelled")
                self.assertFalse(failure["ok"])
                self.assertFalse(target.exists(), 'A cancelled conversion must not publish a final output.')
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    child_running = False
                else:
                    child_running = True
                self.assertFalse(child_running, 'The external converter survived cancellation of its parent.')
                self.assertFalse(list(root.glob('.pdf-output-*')), 'Temporary transaction output was not cleaned up.')
            finally:
                if parent.poll() is None:
                    parent.kill()
                # Close both pipes even if startup failed before the first
                # communicate call; this also prevents ResourceWarning noise.
                parent.communicate(timeout=5)
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == '__main__':
    unittest.main()
