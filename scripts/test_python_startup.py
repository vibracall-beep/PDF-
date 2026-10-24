"""Run real Python startup to prove host .pth files no longer execute."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv

from package_binary import isolate_python_startups

MARKER = '# This file is created by Homebrew and is executed on each python startup.\n'


class PythonStartupIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pdf-startup-isolation-')
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.version = f'{sys.version_info.major}.{sys.version_info.minor}'
        self.formula = 'python@' + self.version
        self.runtime = self.root / 'private runtime'
        self.prefix = self.runtime / ('vendor/' + self.formula + '/Frameworks/Python.framework/Versions/' + self.version)
        self.stdlib = self.prefix / ('lib/python' + self.version); self.stdlib.mkdir(parents=True)
        self.site = self.stdlib / 'site-packages'; self.site.mkdir()
        (self.site / 'private_pdf_module.py').write_text('value = "private module loaded"\n')
        self.host = self.root / 'host-global-site'; self.host.mkdir()
        self.sentinel = self.root / 'host-pth-executed'
        (self.host / 'host_policy.pth').write_text('import pathlib; pathlib.Path(' + repr(str(self.sentinel)) + ').write_text("executed")\n')
        (self.host / 'host_only_module.py').write_text('value = "host module must be absent"\n')
        self.startup = self.stdlib / 'sitecustomize.py'
        self.startup.write_text(MARKER + 'import site\nsite.addsitedir(' + repr(str(self.host)) + ')\n')

    def startup_process(self, interpreter=None):
        # -I keeps user site and PYTHONPATH excluded. -S permits selecting this
        # synthetic framework prefix before calling the real site.main(), which
        # uses the same .pth and sitecustomize startup logic as production.
        script = '''import sys,site,json,importlib.util,ssl,sqlite3,os
# Match the entire synthetic framework identity. Otherwise site.venv() can
# rediscover the test runner's pyvenv.cfg and discard this framework's PREFIXES.
sys.executable=sys._base_executable=os.path.join(sys.argv[1], 'bin', 'python3')
os.environ.pop('__PYVENV_LAUNCHER__', None)
sys.prefix=sys.exec_prefix=sys.base_prefix=sys.base_exec_prefix=sys.argv[1]
site.PREFIXES[:]=[sys.argv[1]]
sys.path.insert(0,sys.argv[2])
site.main()
import private_pdf_module
print(json.dumps({"prefix":sys.prefix,"private":private_pdf_module.value,"host":importlib.util.find_spec("host_only_module") is not None,"ssl":bool(ssl.OPENSSL_VERSION),"sqlite":sqlite3.connect(":memory:").execute("select 7").fetchone()[0]}))
'''
        result = subprocess.run([str(interpreter or sys.executable), '-I', '-S', '-B', '-c', script, str(self.prefix), str(self.stdlib)],
                                capture_output=True, text=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def check_isolation(self, interpreter=None):
        before = self.startup_process(interpreter)
        self.assertEqual(before["prefix"], str(self.prefix))
        self.assertTrue(before['host']); self.assertTrue(self.sentinel.is_file())
        self.sentinel.unlink()
        original = self.startup.read_bytes()
        self.assertEqual(isolate_python_startups(self.runtime, [self.formula]), [self.formula])
        after = self.startup_process(interpreter)
        self.assertEqual(after["prefix"], str(self.prefix))
        self.assertFalse(after['host']); self.assertFalse(self.sentinel.exists())
        self.assertEqual(after['private'], 'private module loaded')
        self.assertTrue(after['ssl']); self.assertEqual(after['sqlite'], 7)
        self.assertFalse(self.startup.exists())
        evidence = self.runtime / 'share/python-startup-provenance' / (self.formula + '-sitecustomize.txt')
        self.assertEqual(evidence.read_bytes(), original)
        self.assertEqual(evidence.stat().st_mode & 0o111, 0)

    def test_real_isolated_startup_no_longer_executes_host_pth_and_keeps_imports(self):
        self.check_isolation()

    def test_real_virtualenv_runner_uses_the_same_synthetic_framework_startup(self):
        # Explicitly cover this even when the overall script suite uses a base
        # interpreter. No pip/network is involved; startup still runs site.main.
        host_venv = self.root / 'runner virtualenv'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(host_venv)
        self.check_isolation(host_venv / 'bin/python')

    def test_unknown_or_cached_startup_is_preserved_and_refused(self):
        self.startup.write_text('print("unknown customization")\n')
        with self.assertRaisesRegex(ValueError, 'desconhecida'):
            isolate_python_startups(self.runtime, [self.formula])
        self.assertTrue(self.startup.is_file())
        self.startup.write_text(MARKER)
        (self.stdlib / 'sitecustomize.pyc').write_bytes(b'unknown cached executable')
        with self.assertRaisesRegex(ValueError, 'Bytecode'):
            isolate_python_startups(self.runtime, [self.formula])
        self.assertTrue(self.startup.is_file())

    def test_startup_fifo_or_link_is_rejected_without_reading_its_target(self):
        self.startup.unlink(); os.mkfifo(self.startup)
        with self.assertRaises(ValueError): isolate_python_startups(self.runtime, [self.formula])
        self.startup.unlink(); self.startup.symlink_to(self.site / 'private_pdf_module.py')
        with self.assertRaises(OSError): isolate_python_startups(self.runtime, [self.formula])
        self.assertEqual((self.site / 'private_pdf_module.py').read_text(), 'value = "private module loaded"\n')


if __name__ == '__main__':
    unittest.main()
