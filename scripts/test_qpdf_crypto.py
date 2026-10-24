"""ABI selection and the actual generated launcher, without an Apple SDK."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import package_binary as package


class QPDFCryptoPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='PDF crypto ABI ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.sources = {name: self.root / name for name in ('qpdf', 'openssl@3', 'openssl@4')}
        self.binary = self.sources['qpdf'] / 'bin/qpdf'
        self.binary.parent.mkdir(parents=True); self.binary.write_bytes(b'synthetic native header')
        for name in ('openssl@3', 'openssl@4'):
            library = self.sources[name] / ('lib/libcrypto.' + name[-1] + '.dylib')
            provider = self.sources[name] / 'lib/ossl-modules/legacy.dylib'
            provider.parent.mkdir(parents=True)
            library.write_bytes(b'synthetic native header'); provider.write_bytes(b'synthetic native header')
        self.crypto3 = self.sources['openssl@3'] / 'lib/libcrypto.3.dylib'
        self.crypto4 = self.sources['openssl@4'] / 'lib/libcrypto.4.dylib'
        self.provider4 = self.sources['openssl@4'] / 'lib/ossl-modules/legacy.dylib'
        self.loads = {self.binary: [self.crypto4], self.provider4: [self.crypto4]}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(package, 'macho', side_effect=lambda path: path.is_file() and not path.is_symlink()).start()
        def inspect(*arguments):
            self.assertEqual(arguments[:3], ('/usr/bin/otool', '-m', '-L'))
            path = arguments[3]
            return str(path) + ':\n' + ''.join('\t' + str(value) +
                ' (compatibility version 1.0.0, current version 1.0.0)\n'
                for value in self.loads.get(path, []))
        mock.patch.object(package, 'command', side_effect=inspect).start()

    def select(self):
        return package.qpdf_crypto_dependency(self.sources['qpdf'], self.sources)

    def test_selects_actual_linked_abi_when_multiple_openssl_versions_are_present(self):
        self.assertEqual(self.select(), ('openssl@4', self.crypto4, self.provider4.parent))
        self.loads[self.binary] = [self.crypto3]
        self.assertEqual(self.select(), ('openssl@3', self.crypto3,
                                       self.sources['openssl@3'] / 'lib/ossl-modules'))

    def test_missing_or_ambiguous_crypto_and_nonexplicit_load_paths_are_rejected(self):
        for dependencies in ([], [self.crypto3, self.crypto4], [Path('@rpath/libcrypto.4.dylib')]):
            with self.subTest(dependencies=dependencies):
                self.loads[self.binary] = dependencies
                with self.assertRaises(ValueError): self.select()

    def test_missing_external_or_mismatched_provider_is_rejected(self):
        self.loads[self.provider4] = [self.crypto3]
        with self.assertRaisesRegex(ValueError, 'ABI'): self.select()
        self.loads[self.provider4] = [self.crypto4]
        self.provider4.unlink()
        with self.assertRaisesRegex(ValueError, 'provider'): self.select()
        self.provider4.symlink_to(self.sources['openssl@3'] / 'lib/ossl-modules/legacy.dylib')
        with self.assertRaisesRegex(ValueError, 'provider'): self.select()

    def test_overlapping_formula_ownership_is_rejected(self):
        self.sources['ambiguous-owner'] = self.root
        with self.assertRaisesRegex(ValueError, 'one OpenSSL formula'): self.select()

    def test_actual_wrapper_survives_relocation_and_scopes_modules_to_qpdf(self):
        runtime = self.root / 'build runtime'; (runtime / 'bin').mkdir(parents=True)
        executable = runtime / 'vendor/qpdf/bin/qpdf'; executable.parent.mkdir(parents=True)
        modules = runtime / 'vendor/openssl@4/lib/ossl-modules'; modules.mkdir(parents=True)
        payload = runtime / 'synthetic executable.py'
        payload.write_text('import json,os,sys\nprint(json.dumps({"modules":os.environ.get("OPENSSL_MODULES"),"argv":sys.argv[1:]}))\n')
        executable.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) +
                              ' "$(dirname "$0")/../../../synthetic executable.py" "$@"\n')
        executable.chmod(0o755)
        environment_file = runtime / 'environment.sh'
        environment_file.write_text('PDF_RUNTIME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"\n')
        before = environment_file.read_bytes()
        package.write_qpdf_wrapper(runtime, executable, modules)
        moved = self.root / 'relocated runtime (M4)'; runtime.rename(moved)
        environment = dict(os.environ, OPENSSL_MODULES='/synthetic/other-abi')
        result = subprocess.run([str(moved / 'bin/qpdf'), 'argument with spaces'],
                                env=environment, capture_output=True, text=True, timeout=5, check=True)
        record = json.loads(result.stdout)
        self.assertEqual(record['modules'], str(moved / modules.relative_to(runtime)))
        self.assertEqual(record['argv'], ['argument with spaces'])
        self.assertEqual((moved / 'environment.sh').read_bytes(), before)
        other = subprocess.run(['/bin/bash', '-c', 'source "$1"; printf "%s" "$OPENSSL_MODULES"',
                                'sibling-runtime', str(moved / 'environment.sh')],
                               env=environment, capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(other.stdout, '/synthetic/other-abi')
        self.assertEqual(environment['OPENSSL_MODULES'], '/synthetic/other-abi')

    def test_wrapper_refuses_external_and_shell_expanding_paths(self):
        runtime = self.root / 'runtime'; (runtime / 'bin').mkdir(parents=True)
        for modules in (self.root / 'outside', runtime / 'vendor/$(bad)', runtime / '../outside'):
            with self.subTest(modules=modules):
                with self.assertRaises(ValueError):
                    package.write_qpdf_wrapper(runtime, runtime / 'qpdf', modules)
        self.assertFalse((runtime / 'bin/qpdf').exists())


if __name__ == '__main__': unittest.main()
