from pathlib import Path
import json,hashlib,os,re,resource,subprocess,sys,time,zipfile
R=Path('/tmp/pdf-cross-437a8f4');R.mkdir(mode=0o700,exist_ok=True)
RUN=40141728214;CONTROL='6daf46294b10f35ec8252fd473f1d0865cd4bf8f';SOURCE='437a8f4d6bb6ebb003859f769e3756fce30c9da3';TAR='7dabd68ffcc1b65ea551efd51bb17f9194bb6d3990261f6c52e33735d96cb7ad'
ROOT=Path('/workspace/PDF-');sys.path[:0]=[str(ROOT/'diagnostics'),str(ROOT/'scripts')]
from delivery_archives import extract_zip
import cross_gui_evidence as gui
STATE=R/'collector-artifact-state.json';state=json.loads(STATE.read_text()) if STATE.exists() else {'attempts':{}}
def persist():STATE.write_text(json.dumps(state,indent=2)+'\n')
def error(r):
 e=r.stderr.decode(errors='replace');return {'exit':r.returncode,'http':re.findall(r'HTTP (\d+)',e),'hosts':sorted(set(re.findall(r'https?://([^/\s?]+)',e))),'forbidden':'Forbidden' in e}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
r=subprocess.run(['gh','api',f'/repos/vibracall-beep/PDF-/actions/runs/{RUN}/artifacts?per_page=100'],capture_output=True,timeout=45)
if r.returncode:print(json.dumps({'metadataError':error(r)}));raise SystemExit(1)
m=json.loads(r.stdout);assert m['total_count']<=2;(R/'collector-artifacts.json').write_bytes(r.stdout)
for part in ('downloads','extracted'):(R/part).mkdir(mode=0o700,exist_ok=True)
for a in m['artifacts']:
 assert a['name'] in ('PDF-cross-platform-validated','PDF-cross-platform-unvalidated') and a['workflow_run']['head_sha']==CONTROL and a['workflow_run']['id']==RUN and re.fullmatch('sha256:[0-9a-f]{64}',a['digest']) and not a['expired']
 if str(a['id']) in state['attempts'] or state.get('proxyBlocked'):continue
 assert 0<a['size_in_bytes']<=gui.MAX_TOTAL
 rec={'id':a['id'],'name':a['name'],'controllerSHA':CONTROL,'sourceSHA':SOURCE,'runID':RUN,'sourceRunID':40137438618,'archiveBytes':a['size_in_bytes'],'githubDigest':a['digest'],'attemptedAt':time.time(),'downloaded':False};state['attempts'][str(a['id'])]=rec;persist()
 target=R/'downloads'/f'{a["id"]}.zip';temp=target.with_suffix('.zip.partial')
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  def bounded():resource.setrlimit(resource.RLIMIT_FSIZE,(a['size_in_bytes']+1024,a['size_in_bytes']+1024))
  with os.fdopen(fd,'wb') as out:
   try:r=subprocess.run(['gh','api',f'/repos/vibracall-beep/PDF-/actions/artifacts/{a["id"]}/zip'],stdout=out,stderr=subprocess.PIPE,timeout=60,preexec_fn=bounded)
   except subprocess.TimeoutExpired:rec['error']={'timeoutSeconds':60};persist();print(json.dumps(rec));continue
  if r.returncode:
   rec['error']=error(r)
   if rec['error']['forbidden']:state['proxyBlocked']=rec['error']
   persist();print(json.dumps(rec));continue
  assert temp.stat().st_size==a['size_in_bytes'] and sha(temp)==a['digest'][7:];temp.rename(target)
 finally:
  if temp.exists():temp.unlink()
 allow=dict(gui.GUI_CONTENTS,**dict.fromkeys(gui.BASE_CONTENTS,64*1024**2),**{'PDF-cross-platform.json':32768})
 with zipfile.ZipFile(target) as z:
  items=z.infolist();assert 0<len(items)<=len(allow) and all(x.filename in allow for x in items)
  names={x.filename:allow[x.filename] for x in items};assert len(names)==len(items)
  if a['name']=='PDF-cross-platform-validated':assert set(names)==set(allow)
 dest=R/'extracted'/a['name'];paths=extract_zip(target,dest,names,total_limit=gui.MAX_TOTAL)
 rec.update({'downloaded':True,'archiveSHA256':sha(target),'directory':str(dest),'extractionVerified':True,'files':[{'name':n,'bytes':p.stat().st_size,'sha256':sha(p)}for n,p in sorted(paths.items())]});persist()
 if a['name']=='PDF-cross-platform-validated':
  verified=json.loads((dest/'PDF-cross-verified.json').read_text());assert verified['sourceCommit']==SOURCE and verified['sourceRunID']==40137438618 and verified['archiveSHA256']==TAR and verified['sourceArtifactID']==12578358642
  manifest=json.loads(Path('/tmp/pdf-native-437a8f4/extracted/PDF-binary-validated-macos-26/distribution-manifest.json').read_text())
  gui.verify_receipt(dest,verified,manifest)
  report=json.loads((dest/'PDF-cross-platform.json').read_text());assert all(report.get(k) is True for k in ['crossOSTestPassed','freshInstallPassed','isolatedRuntimePassed','appIntentsMetadataVerified','nativeSmokePassed','installedBinaryGUIPassed']) and report['sourceCommit']==SOURCE and report['archiveSHA256']==TAR
  rec['sourceBinaryAndGUIReceiptVerified']=True;persist()
 print(json.dumps({'artifact':a['name'],'directory':str(dest),'files':len(paths),'receiptVerified':rec.get('sourceBinaryAndGUIReceiptVerified',False)}))
print(json.dumps({'published':m['total_count'],'downloaded':sum(x['downloaded']for x in state['attempts'].values()),'blocked':bool(state.get('proxyBlocked'))}))
