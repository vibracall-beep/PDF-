"""Private page recognition transport, malformed inputs and real child cleanup."""
import io
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from pdf_engine import run
import ocr_page

HEADER='level\tleft\ttop\twidth\theight\tconf\ttext\n'
TSV=HEADER+'5\t30\t40\t60\t20\t91\tAção\n'


class OCRPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'source.png'
        metadata=PngImagePlugin.PngInfo();metadata.add_text('PrivateSourceMetadata','private-fixture')
        Image.new('RGB',(300,200),'white').save(self.source,pnginfo=metadata)
        self.original=self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(list(self.root.glob('.pdf-output-*')),[])
        self.tmp.cleanup()

    def recognize(self,target=None,tsv=TSV,options=None,inspect=None):
        target=target or self.root/'result.json'
        def external(command,timeout):
            if command[1]=='--list-langs':
                self.assertEqual(timeout,10)
                return subprocess.CompletedProcess(command,0,'eng\npor\n','')
            self.assertEqual(timeout,60)
            self.assertEqual(command[-3:],['--psm','3','tsv'])
            self.assertEqual(command[3:5],['-l','por+eng' if (options or {}).get('language')=='pt' else 'eng'])
            self.assertEqual(stat.S_IMODE(Path(command[1]).stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(Path(command[1]).parent.stat().st_mode),0o700)
            with Image.open(command[1]) as image:
                self.assertNotIn('PrivateSourceMetadata',image.info)
                self.assertEqual(image.size,(300,200))
            Path(command[2]).with_suffix('.tsv').write_bytes(tsv.encode('utf-8') if isinstance(tsv,str) else tsv)
            if inspect:inspect(command)
            return subprocess.CompletedProcess(command,0,'','')
        with patch('ocr_page.shutil.which',return_value='/fixture/tesseract'),patch('pdf_engine._external',side_effect=external):
            run('ocr-page',[self.source],target,options or {})
        return json.loads(target.read_text())

    def test_normalized_bottom_left_geometry_and_private_unicode_response(self):
        result=self.recognize(options={'language':'pt'})
        self.assertEqual({key:result[key] for key in ('version','backend','language','width','height')},
                         dict(version=1,backend='tesseract',language='pt',width=300,height=200))
        observation=result['observations'][0]
        self.assertEqual(observation['string'],'Ação');self.assertEqual(observation['confidence'],0.91)
        self.assertEqual(observation['boundingBox'],dict(origin=dict(x=0.1,y=0.7),size=dict(width=0.2,height=0.1)))
        self.assertEqual(stat.S_IMODE((self.root/'result.json').stat().st_mode),0o600)
        self.assertNotIn(str(self.source),json.dumps(result))

    def test_blank_success_is_distinct_from_failure(self):
        self.assertEqual(self.recognize(tsv=HEADER)['observations'],[])

    def test_invalid_languages_fail_before_running_external_process(self):
        for value in ('','eng','por','fr','en --evil',None,True,[]):
            with self.subTest(language=value),patch('pdf_engine._external') as external,self.assertRaises(ValueError):
                run('ocr-page',[self.source],self.root/'invalid.json',{'language':value})
            external.assert_not_called()

    def test_invalid_images_and_non_png_inputs_are_rejected(self):
        invalid=self.root/'bad.png'
        jpeg=io.BytesIO();Image.new('RGB',(20,20),'white').save(jpeg,format='JPEG')
        for data in (b'',b'not an image',self.original[:30],jpeg.getvalue()):
            invalid.write_bytes(data)
            with self.subTest(size=len(data)),patch('pdf_engine._external') as external,self.assertRaises(ValueError):
                run('ocr-page',[invalid],self.root/'invalid.json')
            external.assert_not_called()

    def test_animated_and_oversized_pngs_are_rejected(self):
        for name in ('animated','wide'):
            source=self.root/(name+'.png')
            if name=='animated':
                Image.new('RGB',(20,20),'white').save(source,save_all=True,append_images=[Image.new('RGB',(20,20),'black')],duration=100,loop=0)
            else:Image.new('RGB',(30_001,1),'white').save(source)
            with self.subTest(name=name),patch('pdf_engine._external') as external,self.assertRaises(ValueError):
                run('ocr-page',[source],self.root/'invalid.json')
            external.assert_not_called()

    def test_input_links_and_pipes_are_refused_without_blocking(self):
        link=self.root/'link.png';link.symlink_to(self.source)
        fifo=self.root/'pipe.png';os.mkfifo(fifo)
        started=time.monotonic()
        for source in (link,fifo):
            with self.subTest(source=source.name),self.assertRaises(ValueError):run('ocr-page',[source],self.root/'invalid.json')
        self.assertLess(time.monotonic()-started,1)

    def test_input_size_limit_applies_before_decoding(self):
        with patch('ocr_page.INPUT_LIMIT',10),patch('pdf_engine._external') as external,self.assertRaises(ValueError):
            run('ocr-page',[self.source],self.root/'invalid.json')
        external.assert_not_called()

    def test_destinations_files_directories_and_links_are_never_overwritten(self):
        existing=self.root/'existing.json';existing.write_bytes(b'KEEP')
        directory=self.root/'directory';directory.mkdir()
        link=self.root/'dangling';link.symlink_to(self.root/'absent')
        for target in (existing,directory,link,self.source):
            identity=target.lstat().st_ino
            with self.subTest(target=target.name),patch('pdf_engine._external') as external,self.assertRaises(ValueError):
                run('ocr-page',[self.source],target)
            external.assert_not_called();self.assertEqual(target.lstat().st_ino,identity)
        self.assertEqual(existing.read_bytes(),b'KEEP');self.assertTrue(link.is_symlink())

    def test_concurrent_destination_creation_is_preserved(self):
        target=self.root/'race.json';identity=[]
        def race(command):
            target.write_bytes(b'CONCURRENT');identity.append(target.stat().st_ino)
        with self.assertRaisesRegex(ValueError,'Outro processo'):
            self.recognize(target=target,inspect=race)
        self.assertEqual(target.read_bytes(),b'CONCURRENT');self.assertEqual(target.stat().st_ino,identity[0])

    def test_malformed_tsv_and_outside_boxes_fail_atomically(self):
        cases=['not TSV',HEADER+'5\tnan\t40\t60\t20\t91\tPrivate\n',
               HEADER+'5\t-1\t40\t60\t20\t91\tPrivate\n',
               HEADER+'5\t30\t40\t60\t20\t101\tPrivate\n',b'\xff\xfe']
        for index,tsv in enumerate(cases):
            target=self.root/f'invalid-{index}.json'
            with self.subTest(index=index),self.assertRaises(RuntimeError) as caught:self.recognize(target=target,tsv=tsv)
            self.assertFalse(target.exists());self.assertNotIn('Private',str(caught.exception))

    def test_observation_text_and_response_limits(self):
        for key,limit,tsv in [('WORD_LIMIT',1,TSV+TSV.split('\n')[1]+'\n'),
                              ('TEXT_LIMIT',2,TSV),('OUTPUT_LIMIT',40,TSV)]:
            with self.subTest(limit=key),patch.object(ocr_page,key,limit),self.assertRaises(RuntimeError):self.recognize(tsv=tsv)
        with self.assertRaises(RuntimeError):self.recognize(tsv=HEADER+'5\t30\t40\t60\t20\t91\t'+'x'*65_537+'\n')
        self.assertFalse((self.root/'result.json').exists())

    def test_missing_dependency_and_external_errors_do_not_leak_private_text(self):
        target=self.root/'failed.json'
        with patch('ocr_page.shutil.which',return_value=None),self.assertRaisesRegex(RuntimeError,'não está instalado'):
            run('ocr-page',[self.source],target)
        for error in [RuntimeError('PRIVATE_SOURCE_TEXT /private/document.png'),subprocess.TimeoutExpired('tesseract PRIVATE_SOURCE_TEXT',60)]:
            def external(command,timeout):
                if command[1]=='--list-langs':return subprocess.CompletedProcess(command,0,'eng\npor\n','')
                raise error
            with patch('ocr_page.shutil.which',return_value='/fixture/tesseract'),patch('pdf_engine._external',side_effect=external),self.assertRaises(RuntimeError) as caught:
                run('ocr-page',[self.source],target)
            self.assertNotIn('PRIVATE',str(caught.exception));self.assertFalse(target.exists())

    def test_portuguese_requires_both_packs_before_recognition(self):
        target=self.root/'language.json'
        with patch('ocr_page.shutil.which',return_value='/fixture/tesseract'),patch('pdf_engine._external',return_value=subprocess.CompletedProcess([],0,'eng\n','')) as external,self.assertRaisesRegex(RuntimeError,'por'):
            run('ocr-page',[self.source],target,{'language':'pt'})
        self.assertEqual(external.call_count,1);self.assertFalse(target.exists())

    def test_interrupt_is_not_replaced_with_generic_ocr_error(self):
        with patch('ocr_page.shutil.which',return_value='/fixture/tesseract'),patch('pdf_engine._external',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            run('ocr-page',[self.source],self.root/'cancelled.json')
        self.assertFalse((self.root/'cancelled.json').exists())


class OCRPageCancellationTests(unittest.TestCase):
    def test_sigint_stops_tesseract_without_publishing_or_logging_text(self):self.exercise(signal.SIGINT)
    def test_sigterm_stops_resistant_tesseract_without_publishing(self):self.exercise(signal.SIGTERM,resistant=True)

    def exercise(self,requested,resistant=False):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.png';Image.new('RGB',(300,200),'white').save(source)
            original=source.read_bytes();target=root/'output.json';pid=root/'child.pid'
            program=root/'recognizer with spaces.py'
            program.write_text('import os,signal,time,sys\nfrom pathlib import Path\n'
                + 'if sys.argv[1:]==["--list-langs"]:\n print("eng\\npor");sys.exit(0)\n'
                + ('signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' if resistant else '')
                + 'Path(os.environ["PDF_TEST_OCR_PID"]).write_text(str(os.getpid()))\n'
                + 'time.sleep(30)\n')
            executable=root/'tesseract'
            executable.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(program))+' "$@"\n');executable.chmod(0o755)
            environment=os.environ.copy();environment['PATH']=str(root)+os.pathsep+environment.get('PATH','');environment['PDF_TEST_OCR_PID']=str(pid)
            engine=Path(__file__).resolve().parents[1]/'engine'/'pdf_engine.py'
            process=subprocess.Popen([sys.executable,str(engine),'ocr-page',str(source),'--output',str(target)],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            child=None
            try:
                deadline=time.monotonic()+5
                while process.poll() is None and time.monotonic()<deadline:
                    if pid.exists() and pid.read_text().strip().isdecimal():child=int(pid.read_text());break
                    time.sleep(0.02)
                self.assertIsNotNone(child,'The real child must start before cancellation.')
                process.send_signal(requested);stdout,stderr=process.communicate(timeout=8)
                self.assertEqual(process.returncode,130);self.assertEqual(json.loads(stderr)['code'],'Cancelled')
                self.assertEqual(stdout,'');self.assertFalse(target.exists());self.assertEqual(source.read_bytes(),original)
                with self.assertRaises(ProcessLookupError):os.kill(child,0)
                self.assertEqual(list(root.glob('.pdf-output-*')),[])
            finally:
                if process.poll() is None:process.kill()
                process.communicate(timeout=5)
                if child is not None:
                    try:os.kill(child,signal.SIGKILL)
                    except ProcessLookupError:pass


if __name__=='__main__':unittest.main()
