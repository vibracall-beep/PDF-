import importlib.util,io,json,os,subprocess,tempfile,unittest,zipfile,stat
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('appearance_collector','/tmp/pdf_collect_appearance_observer.py');c=importlib.util.module_from_spec(spec)
with patch.object(subprocess,'run',side_effect=AssertionError('import must not execute subprocess')),patch.object(subprocess,'check_output',side_effect=AssertionError('import must not execute subprocess')):
 spec.loader.exec_module(c)
SOURCE='1'*40;CONTROL='2'*40
cfg={'schemaVersion':1,'sourceCommit':SOURCE,'controlCommit':CONTROL,'runID':12345,'runAttempt':2,'jobIDs':{'compile-sdk26':51,'same-binary-xcode27':52},'outputDirectory':'/workspace/.cache/pdf-appearance-1111111-12345'}
run={'id':12345,'head_sha':CONTROL,'head_commit':{'id':CONTROL},'run_attempt':2,'event':'workflow_dispatch','path':c.WORKFLOW,'repository':{'id':c.REPOSITORY_ID},'head_repository':{'id':c.REPOSITORY_ID},'status':'completed','conclusion':'success','head_branch':'main'}
def jobs():return {'total_count':2,'jobs':[{'id':i,'name':name,'run_id':12345,'run_attempt':2,'head_sha':CONTROL,'labels':[c.JOB_LABELS[name]],'status':'completed','conclusion':'success','started_at':'2026-10-25T12:00:00Z','completed_at':'2026-10-25T12:10:00Z'} for name,i in cfg['jobIDs'].items()]}
def artifact():return {'name':'PDF-appearance-sdk26','id':61,'expired':False,'size_in_bytes':123,'digest':'sha256:'+'3'*64,'workflow_run':{'id':12345,'head_sha':CONTROL,'head_repository_id':c.REPOSITORY_ID,'repository_id':c.REPOSITORY_ID,'head_branch':'main'},'created_at':'2026-10-25T12:01:00Z','updated_at':'2026-10-25T12:02:00Z'}
def zipped(entries):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for n,v in entries:z.writestr(n,v)
 return b.getvalue()
class OfflineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  # Trusted local Git source only; no network and no artifact code execution.
  raw=subprocess.check_output(['git','show','37f5b65e35a9f70c716cfcd64db7ba69837f5c21:diagnostics/delivery_archives.py'],cwd='/workspace/PDF-',env=dict(os.environ,GIT_NO_LAZY_FETCH='1'))
  cls.tmp=tempfile.TemporaryDirectory(prefix='pdf-appearance-collector-test-');p=Path(cls.tmp.name)/'delivery_archives.py';p.write_bytes(raw)
  spec=importlib.util.spec_from_file_location('trusted_offline_archives',p);cls.archives=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.archives)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def test_valid_config_and_explicit_source_run(self):
  p=Path(self.tmp.name)/'config.json';p.write_text(json.dumps(cfg));self.assertEqual(c.configuration(p),cfg)
  bad=dict(cfg,outputDirectory='/tmp/shared');p.write_text(json.dumps(bad))
  with self.assertRaises(ValueError):c.configuration(p)
 def test_config_rejects_duplicate_keys(self):
  p=Path(self.tmp.name)/'duplicate.json';p.write_text('{"schemaVersion":1,"schemaVersion":1}')
  with self.assertRaises(ValueError):c.configuration(p)
 def test_exact_terminal_run_jobs_accepted(self):self.assertEqual(set(c.validate_run_jobs(cfg,run,jobs())),set(cfg['jobIDs']))
 def test_failure_is_evidence_not_a_success_gate(self):
  r=dict(run,conclusion='failure');j=jobs();j['jobs'][0]['conclusion']='failure';self.assertEqual(c.validate_run_jobs(cfg,r,j)['compile-sdk26']['conclusion'],'failure')
 def test_skipped_target_without_allocated_runner_is_retained(self):
  j=jobs();j['jobs'][1].update(conclusion='skipped',labels=[]);self.assertEqual(c.validate_run_jobs(cfg,dict(run,conclusion='failure'),j)['same-binary-xcode27']['conclusion'],'skipped')
 def test_wrong_workflow_or_event_or_attempt_refused(self):
  for key,value in [('path','.github/workflows/macos.yml'),('event','push'),('run_attempt',1),('head_sha',SOURCE),('status','in_progress')]:
   with self.subTest(key=key),self.assertRaises(ValueError):c.validate_run_jobs(cfg,dict(run,**{key:value}),jobs())
 def test_job_identity_or_label_refused(self):
  for key,value in [('id',99),('name','other'),('labels',['ubuntu']),('head_sha',SOURCE),('run_attempt',1)]:
   j=jobs();j['jobs'][1][key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):c.validate_run_jobs(cfg,run,j)
 def test_authenticated_artifact_interval_and_digest(self):
  c.validate_artifact(cfg,run,jobs()['jobs'][0],artifact(),'PDF-appearance-sdk26')
  for key,value in [('digest','sha256:bad'),('expired',True),('created_at','2026-10-25T11:59:59Z'),('updated_at','2026-10-25T12:11:00Z'),('name','wrong')]:
   a=artifact();a[key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):c.validate_artifact(cfg,run,jobs()['jobs'][0],a,'PDF-appearance-sdk26')
 def test_artifact_wrong_repository_or_source_refused(self):
  for key,value in [('repository_id',0),('head_repository_id',0),('head_sha',SOURCE),('id',555)]:
   a=artifact();a['workflow_run'][key]=value
   with self.subTest(key=key),self.assertRaises(ValueError):c.validate_artifact(cfg,run,jobs()['jobs'][0],a,'PDF-appearance-sdk26')
 def test_small_zip_crc_exact_bytes_and_empty_logs(self):
  raw=zipped([('origin.log',b'origin'),('capture.log',b'')]);self.assertEqual(c.unpack_small_zip(raw,{'origin.log':100,'capture.log':100},self.archives),{'origin.log':b'origin','capture.log':b''})
 def test_literal_uppercase_evidence_names_are_preserved(self):
  values={'PDF-appearance.png':b'PNG fixture bytes','PDF-appearance.appearance.json':b'{}'}
  self.assertEqual(c.unpack_small_zip(zipped(list(values.items())),{k:100 for k in values},self.archives),values)
 def test_casefold_collisions_still_refused(self):
  entries=[('PDF-appearance.png',b'x'),('pdf-appearance.png',b'y')]
  with self.assertRaises(ValueError):c.unpack_small_zip(zipped(entries),{name:100 for name,_ in entries},self.archives)
 def test_zip_extra_traversal_or_duplicate_refused(self):
  for entries in [[('../escape.log',b'x')],[('unexpected.log',b'x')],[('origin.log',b'x'),('origin.log',b'y')]]:
   with self.subTest(entries=entries),self.assertRaises(ValueError):c.unpack_small_zip(zipped(entries),{'origin.log':100},self.archives)
 def test_symlink_and_expansion_limit_refused(self):
  info=zipfile.ZipInfo('origin.log');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
  with self.assertRaises(ValueError):c.unpack_small_zip(zipped([(info,b'/etc/passwd')]),{'origin.log':100},self.archives)
  with self.assertRaises(ValueError):c.unpack_small_zip(zipped([('origin.log',b'x'*101)]),{'origin.log':100},self.archives)
  with self.assertRaises(ValueError):c.unpack_small_zip(zipped([('origin.log',b'xx')]),{'origin.log':100},self.archives,limit=1)
 def test_zip_trailing_data_rejected(self):
  with self.assertRaises(ValueError):c.unpack_small_zip(zipped([('origin.log',b'x')])+b'payload',{'origin.log':100},self.archives)
 def test_zip_corrupted_payload_crc_rejected(self):
  raw=bytearray(zipped([('origin.log',b'public value')]));raw[40]^=0xff
  with self.assertRaises((ValueError,zipfile.BadZipFile,c.zlib.error)):c.unpack_small_zip(bytes(raw),{'origin.log':100},self.archives)
 def test_origin_exact_assertions_and_duplicates(self):
  self.assertEqual(c.origin_values(b'source_commit=abc\nrun_id=42\n'),{'source_commit':'abc','run_id':'42'})
  with self.assertRaises(ValueError):c.origin_values(b'run_id=42\nrun_id=43\n')
 def test_inventories_are_fifteen_and_fourteen(self):
  self.assertEqual(len(c.inventory_for('compile-sdk26')),15);self.assertEqual(len(c.inventory_for('same-binary-xcode27')),14)
  self.assertEqual(len(c.PNG_NAMES),7);self.assertNotIn('PDF-appearance-bundle.tar.gz',c.inventory_for('compile-sdk26'))
if __name__=='__main__':unittest.main(verbosity=2)
