"""Run the packager's actual OCR launcher through real spawned processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from package_binary import write_ocr_dispatcher


class OCRDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF OCR private runtime ')
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name).resolve()
        self.package = self.runtime / 'private site/ocrmypdf'
        self.package.mkdir(parents=True)
        (self.package / '__init__.py').write_text('')
        self.launcher = write_ocr_dispatcher(self.runtime, ['private site'])

    def execute(self, *arguments):
        return subprocess.run([sys.executable, '-I', '-B', str(self.launcher), *arguments],
                              capture_output=True, text=True, timeout=15)

    def test_spawn_imports_generated_launcher_without_rerunning_cli(self):
        # Synthetic OCR entrypoint exercises Python's real spawn protocol,
        # independent of installed OCR engines or the platform's default mode.
        (self.package / 'worker.py').write_text('import os\ndef value():\n    return {"value":42,"pid":os.getpid()}\n')
        (self.package / '__main__.py').write_text('''import json,multiprocessing,os,sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from ocrmypdf.worker import value
if __name__ == "__main__":
    sentinel=Path(sys.argv[1])
    with sentinel.open("a") as stream: stream.write(str(os.getpid())+"\\n")
    with ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context("spawn")) as pool:
        result=pool.submit(value).result(timeout=5)
    print(json.dumps({"result":result,"parent":os.getpid(),"argv":sys.argv}),flush=True)
''')
        sentinel = self.runtime / 'CLI executions.txt'
        result = self.execute(str(sentinel), '--synthetic-flag', 'value with spaces')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['result']['value'], 42)
        self.assertNotEqual(report['result']['pid'], report['parent'])
        self.assertEqual(report['argv'], ['ocrmypdf', str(sentinel), '--synthetic-flag', 'value with spaces'])
        self.assertEqual(sentinel.read_text().splitlines(), [str(report['parent'])])

    def test_cli_error_exit_and_diagnostic_are_preserved(self):
        (self.package / '__main__.py').write_text('import sys\nprint("synthetic OCR failure",file=sys.stderr)\nsys.exit(17)\n')
        result = self.execute()
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr.strip(), 'synthetic OCR failure')


if __name__ == '__main__':
    unittest.main()
