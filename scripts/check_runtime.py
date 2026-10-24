#!/usr/bin/env python3
"""Exercise the portable engines using only a synthetic fixture; no user files."""
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile


def main():
    app = Path(sys.argv[1]).resolve(strict=True)
    runtime = app / 'Contents/Resources/runtime'
    if not sys.prefix.startswith(str(runtime) + os.sep):
        raise RuntimeError('Python escaped the bundled runtime: ' + sys.prefix)
    helpers = Path(__file__).resolve().parent
    allowed_import_roots = (runtime, helpers, app / 'Contents/Resources/engine')
    for entry in sys.path:
        # A non-existent stdlib zip path is normal, but it must still resolve
        # under this bundle. Empty entries would enable imports from cwd.
        if not entry or not any(Path(entry).resolve().is_relative_to(root) for root in allowed_import_roots):
            raise RuntimeError('Python retained an external import path: ' + str(entry))
    for location in (sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix, sys.executable):
        if not Path(location).resolve().is_relative_to(runtime):
            raise RuntimeError('Python retained an external runtime location: ' + str(location))
    trust_paths = ssl.get_default_verify_paths()
    for location in (trust_paths.cafile, trust_paths.capath):
        if not location or not Path(location).resolve().is_relative_to(runtime):
            raise RuntimeError('Python TLS trust escaped the bundled runtime.')
    if ssl.create_default_context().cert_store_stats()['x509'] == 0:
        raise RuntimeError('Bundled TLS trust store contains no valid certificates.')
    # -I intentionally omits the script directory; permit only this signed
    # distribution helper directory, without restoring cwd or host packages.
    sys.path.insert(0, str(helpers))
    from app_intents_metadata import verify
    verify(app / 'Contents/Resources')
    for name in ('qpdf', 'gs', 'ocrmypdf', 'tesseract', 'soffice', 'java', 'fc-match', 'fc-conflist'):
        executable = shutil.which(name)
        if not executable or not Path(executable).is_relative_to(runtime):
            raise RuntimeError('External or missing executable: ' + name)
    fontconfig = runtime / 'share/fontconfig'
    if (os.environ.get('FONTCONFIG_FILE') != str(fontconfig / 'fonts.conf')
            or os.environ.get('FONTCONFIG_PATH') != str(fontconfig)):
        raise RuntimeError('Fontconfig did not use its private configuration.')
    configurations = subprocess.check_output(['fc-conflist'], text=True, timeout=60)
    allowed_configurations = [fontconfig / 'fonts.conf', *(fontconfig / 'conf.d').glob('*.conf')]
    active = [line for line in configurations.splitlines() if line.startswith('+ ')]
    if not active or any(not any(line.startswith('+ ' + str(path) + ':')
                                for path in allowed_configurations) for line in active):
        raise RuntimeError('Fontconfig loaded an external configuration.')
    matched_font = subprocess.check_output(['fc-match', '--format=%{file}', 'sans-serif'],
                                           text=True, timeout=60).strip()
    if not matched_font or not Path(matched_font).is_file():
        raise RuntimeError('Private fontconfig could not find an installed font.')
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    from docx import Document
    from playwright.sync_api import sync_playwright
    import pyhanko.sign.signers
    sys.path.insert(0, str(app / 'Contents/Resources/engine'))
    from pdf_engine import run
    from pdf_standards import validator_paths
    languages = subprocess.check_output(['tesseract', '--list-langs'], text=True)
    if not all(language in languages.splitlines() for language in ('eng', 'por')):
        raise RuntimeError('Bundled Portuguese/English OCR data is incomplete.')
    validator_paths()
    with tempfile.TemporaryDirectory(prefix='pdf-portable-check-') as directory:
        root = Path(directory)
        source = root / 'source.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), 'PDF portable verification')
            pdf.save(source)
        run('rotate', [str(source)], str(root / 'rotated.pdf'), {'degrees': 90})
        with fitz.open(root / 'rotated.pdf') as pdf:
            assert pdf[0].rotation == 90 and 'portable verification' in pdf[0].get_text()
        run('validate-pdfua', [str(source)], str(root / 'standards.json'), {})
        report = json.loads((root / 'standards.json').read_text())
        assert report['compliant'] is False and report['counts']['failedRules'] > 0
        run('verify-signatures', [str(source)], str(root / 'signatures.json'), {})
        assert json.loads((root / 'signatures.json').read_text())['signature_count'] == 0
        office = Document(); office.add_paragraph('PDF portable Office verification')
        office.save(root / 'office.docx')
        run('office', [str(root / 'office.docx')], str(root / 'office.pdf'), {})
        with fitz.open(root / 'office.pdf') as pdf:
            assert 'portable Office verification' in pdf[0].get_text()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_content('<h1>PDF portable browser verification</h1>')
            page.pdf(path=str(root / 'browser.pdf'))
            browser.close()
        with fitz.open(root / 'browser.pdf') as pdf:
            assert 'portable browser verification' in pdf[0].get_text()
        subprocess.run(['qpdf', '--check', str(source)], check=True, capture_output=True)
        subprocess.run(['gs', '-dBATCH', '-dNOPAUSE', '-sDEVICE=pdfwrite',
                        '-sOutputFile=' + str(root / 'ghostscript.pdf'), str(source)], check=True, capture_output=True)
        # Genuine image-only OCR through both bundled Tesseract and OCRmyPDF.
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 60)
        image = Image.new('RGB', (1600, 400), 'white')
        ImageDraw.Draw(image).text((50, 100), 'PDF portable verification', fill='black', font=font)
        image.save(root / 'scan.png')
        with fitz.open() as pdf:
            page = pdf.new_page(width=800, height=200)
            page.insert_image(page.rect, filename=str(root / 'scan.png'))
            pdf.save(root / 'scan.pdf')
        subprocess.run(['ocrmypdf', '--force-ocr', '--output-type', 'pdf', '--optimize', '0',
                        '-l', 'eng', str(root / 'scan.pdf'), str(root / 'ocr.pdf')], check=True, capture_output=True, timeout=180)
        with fitz.open(root / 'ocr.pdf') as pdf:
            assert 'verification' in pdf[0].get_text().lower()
    print('Portable runtime: Python/TLS paths, private fontconfig, Office, browser, Ghostscript, qpdf, OCR and standards passed.', flush=True)


if __name__ == '__main__':
    main()
