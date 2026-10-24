"""Literal filename handling for Apple tools, including a real macOS fixture."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from package_binary import otool_libraries, rewrite_macho


class MachORelocationTests(unittest.TestCase):
    def test_library_names_preserve_spaces_and_parentheses_before_version_metadata(self):
        output = '''/tmp/Chromium Helper (GPU):
\t/tmp/Private Framework (GPU).dylib (compatibility version 1.0.0, current version 1.0.0)
\t@loader_path/Library (compatibility version example).dylib (compatibility version 0.0.0, current version 2.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
'''
        self.assertEqual(otool_libraries(output), {
            '/tmp/Private Framework (GPU).dylib',
            '@loader_path/Library (compatibility version example).dylib',
            '/usr/lib/libSystem.B.dylib',
        })

    def test_unrecognized_dependency_records_cannot_be_silently_ignored(self):
        for record in ('\t/unexpected/library.dylib\n', '\t (compatibility version 1.0.0)\n',
                       '\t/library.dylib (compatibility version missing terminator\n'):
            with self.subTest(record=record):
                with self.assertRaises(ValueError): otool_libraries(record)

    @unittest.skipUnless(sys.platform == 'darwin', 'real clang, otool and code signing require macOS')
    def test_real_helpers_with_parentheses_relocate_and_execute_without_external_fallback(self):
        with tempfile.TemporaryDirectory(prefix='PDF literal MachO ') as temporary:
            root = Path(temporary).resolve()
            original = root / 'Original library (public)'; original.mkdir()
            copied = root / 'Private runtime (relocated)'; copied.mkdir()
            library_name = 'Fixture Library (GPU).dylib'
            library = original / library_name
            def command(arguments, source=None):
                return subprocess.run(arguments, input=source, text=True, capture_output=True,
                                      check=True, timeout=45)
            command(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-dynamiclib',
                     '-Wl,-headerpad_max_install_names', '-install_name', str(library),
                     '-o', str(library), '-x', 'c', '-'], 'int pdf_fixture_value(void) { return 42; }\n')
            relocated_library = copied / library_name; shutil.copy2(library, relocated_library)
            rewrite_macho(relocated_library, {original: copied}, root)
            command(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(relocated_library)])
            source = '#include <stdio.h>\nextern int pdf_fixture_value(void);\nint main(void) { printf("%d\\n", pdf_fixture_value()); return 0; }\n'
            for name in ('Chromium Helper (GPU)', 'Chromium Helper (Renderer)', 'Helper with spaces'):
                with self.subTest(name=name):
                    executable = root / name
                    command(['/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-Wl,-headerpad_max_install_names',
                             '-o', str(executable), '-x', 'c', '-', '-x', 'none', str(library)], source)
                    command(['/usr/bin/lipo', str(executable), '-verify_arch', 'arm64'])
                    before = executable.read_bytes()
                    # A real unbundled dependency still fails; no flag disables
                    # the relocation policy or permits the host library.
                    with self.assertRaisesRegex(ValueError, 'externa não empacotada'):
                        rewrite_macho(executable, {}, root)
                    self.assertEqual(executable.read_bytes(), before)
                    rewrite_macho(executable, {original: copied}, root)
                    command(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(executable)])
                    command(['/usr/bin/codesign', '--verify', '--strict', str(executable)])
                    dependencies = otool_libraries(command(['/usr/bin/otool', '-m', '-L', str(executable)]).stdout)
                    self.assertIn('@loader_path/' + copied.name + '/' + library_name, dependencies)
                    self.assertNotIn(str(library), dependencies)
                    self.assertEqual(command([str(executable)]).stdout.strip(), '42')


if __name__ == '__main__':
    unittest.main()
