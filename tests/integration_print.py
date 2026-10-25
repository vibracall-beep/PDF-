"""Exercise the real Ghostscript PDF/X path with a CMYK output profile."""
from pathlib import Path
import hashlib
import shutil
import sys
import tempfile
import unittest
import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from pdf_engine import run
from print_inspection import inspect_structure


def cmyk_profile():
    executable = shutil.which('gs')
    candidates = [Path('/usr/share/color/icc/ghostscript/default_cmyk.icc')]
    if executable:
        base = Path(executable).resolve().parent.parent
        candidates.append(base / 'share/ghostscript/iccprofiles/default_cmyk.icc')
        candidates += list((base / 'share/ghostscript').glob('*/iccprofiles/default_cmyk.icc'))
    candidates.append(Path('/opt/homebrew/share/ghostscript/iccprofiles/default_cmyk.icc'))
    candidates += list(Path('/opt/homebrew/share/ghostscript').glob('*/iccprofiles/default_cmyk.icc'))
    return next((path for path in candidates if path.is_file()), None)


class PrintIntegration(unittest.TestCase):
    def test_pdfx_embeds_supplied_icc_and_preserves_page_text(self):
        executable = shutil.which('gs')
        self.assertIsNotNone(executable, 'Ghostscript is required for this integration suite')
        profile = cmyk_profile()
        self.assertIsNotNone(profile, 'A real Ghostscript CMYK profile is required')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source.pdf'; output = root / 'pdfx.pdf'
            with fitz.open() as document:
                document.new_page(width=400, height=500).insert_text((50, 80), 'Print integration retained text')
                document.save(source)
            original = source.read_bytes()
            run('pdfx', [source], output, {'icc_profile': str(profile)})
            with fitz.open(output) as document:
                self.assertEqual(len(document), 1)
                self.assertIn('Print integration retained text', document[0].get_text())
                info = document.xref_get_key(-1, 'Info')
                self.assertIn('PDF/X-3:2002', document.xref_object(int(info[1].split()[0])))
                intents = document.xref_get_key(document.pdf_catalog(), 'OutputIntents')
                intent = int(intents[1].strip('[]').split()[0])
                reference = document.xref_get_key(intent, 'DestOutputProfile')
                embedded = document.xref_stream(int(reference[1].split()[0]))
                self.assertEqual(hashlib.sha256(embedded).digest(), hashlib.sha256(profile.read_bytes()).digest())
            self.assertEqual(source.read_bytes(), original)
            independent = inspect_structure(output)
            self.assertEqual(independent['parser'], 'pyHanko')
            self.assertEqual(independent['pdfx_checks']['status'], 'checks_passed')
            self.assertIsNone(independent['pdfx_checks']['conformant'])
            self.assertFalse(independent['pdfx_checks']['independently_certified'])
            # A real converted file with the channel count adulterated must
            # fail the independent ICC check, even with its PDF/X label intact.
            tampered = root / 'tampered-profile.pdf'
            with fitz.open(output) as document:
                intents = document.xref_get_key(document.pdf_catalog(), 'OutputIntents')
                intent = int(intents[1].strip('[]').split()[0])
                reference = document.xref_get_key(intent, 'DestOutputProfile')
                document.xref_set_key(int(reference[1].split()[0]), 'N', '3')
                document.save(tampered)
            broken = inspect_structure(tampered)
            self.assertEqual(broken['pdfx_checks']['status'], 'checks_failed')
            checks = {item['code']: item['status'] for item in broken['pdfx_checks']['checks']}
            self.assertEqual(checks['output-profile'], 'failed')

    def test_actual_rendered_process_ink_coverage_across_two_pages(self):
        import json
        self.assertIsNotNone(shutil.which('gs'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'plates.pdf'; output = root / 'coverage.json'
            with fitz.open() as document:
                # 1/4 cyan on page one, 1/2 black on page two. Distinct CMYK
                # primitives test the actual renderer without font variation.
                page = document.new_page(width=144, height=144)
                page.draw_rect(fitz.Rect(0, 0, 72, 72), color=None, fill=(1, 0, 0, 0))
                page = document.new_page(width=144, height=144)
                page.draw_rect(fitz.Rect(0, 0, 72, 144), color=None, fill=(0, 0, 0, 1))
                document.save(source)
            original = source.read_bytes()
            run('print-preflight', [source], output, {'render_inks': True, 'ink_dpi': 72})
            report = json.loads(output.read_text())
            coverage = report['ink_coverage']
            self.assertEqual(coverage['engine'], 'Ghostscript inkcov')
            self.assertEqual(len(coverage['pages']), 2)
            self.assertEqual(coverage['dpi'], 72)
            first, second = coverage['pages']
            self.assertAlmostEqual(first['cyan'], .25, delta=.015)
            self.assertAlmostEqual(second['black'], .5, delta=.015)
            for channel in ('magenta', 'yellow', 'black'):
                self.assertLess(first[channel], .001)
            for channel in ('cyan', 'magenta', 'yellow'):
                self.assertLess(second[channel], .001)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(list(root.glob('.pdf-output-*')))

    def test_ink_measurement_uses_selected_real_profile_and_identifies_its_bytes(self):
        import json
        profile = cmyk_profile()
        self.assertIsNotNone(profile)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'color.pdf'; output = root / 'coverage.json'
            with fitz.open() as document:
                document.new_page(width=144, height=144).draw_rect(fitz.Rect(10, 10, 130, 130), color=None, fill=(0.3, .5, .1))
                document.save(source)
            run('print-preflight', [source], output, {'render_inks': True, 'ink_dpi': 100, 'icc_profile': str(profile)})
            coverage = json.loads(output.read_text())['ink_coverage']
            self.assertEqual(coverage['profile']['sha256'], hashlib.sha256(profile.read_bytes()).hexdigest())
            self.assertEqual(coverage['profile']['color_space'], 'CMYK')
            self.assertEqual(coverage['dpi'], 100)
            self.assertEqual(len(coverage['pages']), 1)
            self.assertGreater(sum(coverage['pages'][0][channel] for channel in ('cyan', 'magenta', 'yellow', 'black')), .1)
