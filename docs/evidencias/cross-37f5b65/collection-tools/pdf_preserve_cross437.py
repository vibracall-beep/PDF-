from pathlib import Path
import json,hashlib,re,zipfile,struct,sys
R=Path('/tmp/pdf-cross-437a8f4');D=R/'extracted'/'PDF-cross-platform-validated';O=Path('/workspace/PDF-/docs/evidencias/cross-437a8f4')
RUN=40141728214;CONTROL='6daf46294b10f35ec8252fd473f1d0865cd4bf8f';SOURCE='437a8f4d6bb6ebb003859f769e3756fce30c9da3';TAR='7dabd68ffcc1b65ea551efd51bb17f9194bb6d3990261f6c52e33735d96cb7ad'
run=json.loads((R/'collector-run.json').read_text());assert run['id']==RUN and run['head_sha']==CONTROL and run['run_attempt']==1 and run['conclusion']=='success'
a=json.loads((R/'collector-artifacts.json').read_text())['artifacts'];assert len(a)==1;a=a[0]
rec=json.loads((R/'collector-artifact-state.json').read_text())['attempts'][str(a['id'])];assert rec['downloaded'] and rec['extractionVerified'] and rec['sourceBinaryAndGUIReceiptVerified'] and rec['archiveSHA256']==a['digest'][7:]
report=json.loads((D/'PDF-cross-platform.json').read_text());assert report['sourceRunID']==40137438618 and report['sourceCommit']==SOURCE and report['archiveSHA256']==TAR and report['crossOSTestPassed'] is True and report['rebuiltOnDestination'] is False
counts=json.loads((R/'collector-final-counts.json').read_text());assert [x['count']for x in counts['controllerPythonSuites']]==[9,11] and all(x['resultLine'].endswith(' OK')for x in counts['controllerPythonSuites']) and len(counts['nativeSuccessfulRuns'])==3 and all(x['groups']==41 for x in counts['nativeSuccessfulRuns']) and counts['nativeFailureLines']==0
O.mkdir(parents=True,exist_ok=True);files=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def preserve(name,data,**metadata):
 p=O/name
 if p.exists():assert p.read_bytes()==data,name
 else:p.write_bytes(data)
 files.append({'file':name,'bytes':len(data),'sha256':sha(data),**metadata})
archive=(R/'downloads'/f'{a["id"]}.zip').read_bytes();assert len(archive)==a['size_in_bytes'] and sha(archive)==a['digest'][7:]
preserve('original-artifact.zip',archive,kind='original',origin='unchanged GitHub artifact ZIP',artifactID=a['id'],artifactName=a['name'])
logs=(R/'collector-attempt-1-logs.zip').read_bytes();identity=json.loads((R/'collector-log-identity.json').read_text());assert sha(logs)==identity['sha256']
preserve('attempt-1-logs.zip',logs,kind='original',origin='unchanged official GitHub attempt log archive',upstreamDigestAvailable=False)
selected=['PDF-cross-origin.json','PDF-cross-verified.json','PDF-cross-gui-before.json','PDF-cross-gui.json','PDF-cross-platform.json','PDF-cross-isolation.log','PDF-cross-gui-capture.log','PDF-cross-gui-validation.log','PDF-preview.png','PDF-preview.ferramentas.png','PDF-preview.revisao-ocr.png']
with zipfile.ZipFile(R/'downloads'/f'{a["id"]}.zip')as z:
 assert len(z.infolist())==48
 for name in selected:
  data=(D/name).read_bytes();assert z.read(name)==data;entry=next(x for x in rec['files']if x['name']==name);assert sha(data)==entry['sha256'] and len(data)==entry['bytes']
  preserve(name,data,kind='original',origin='unchanged original artifact member',artifactID=a['id'],member=name)
for name in ['collector-final-counts.json','collector-ocr-macos26-binary-on27.json']:
 preserve(name.removeprefix('collector-'),(R/name).read_bytes(),kind='derived',origin='local read-only analysis of authenticated originals')
reviews=sorted(R.glob('visual-review-*.json'));seen=set()
assert len(reviews)==2, 'Wait for the two independent visual reports before freezing evidence.'
for p in reviews:
 data=p.read_bytes();v=json.loads(data);images=v.get('files',v.get('images',v.get('originals')));assert len(images)==16
 for image in images:
  name=image.get('file',image.get('name'));assert name not in seen;seen.add(name);raw=(D/name).read_bytes();assert sha(raw)==image['sha256']
  if 'bytes' in image:assert len(raw)==image['bytes']
 preserve(p.name,data,kind='derived',origin='independent individual visual review after the automated workflow; not a GitHub-produced report')
assert len(seen)==32
patterns={'temporary_signed_url':re.compile(rb'[?&](?:sig|se|sv|X-Amz-Signature|X-Amz-Credential|X-Goog-Signature)=',re.I),'github_token':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),'private_key':re.compile(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----'),'authorization_value':re.compile(rb'Authorization\s*[:=]\s*(?:Bearer|Basic)\s+[A-Za-z0-9+/_.=-]{12,}',re.I)}
texts=[]
for p in [R/'downloads'/f'{a["id"]}.zip',R/'collector-attempt-1-logs.zip']:
 with zipfile.ZipFile(p) as z:
  texts.extend(z.read(i)for i in z.namelist()if i.endswith(('.json','.log','.txt')))
texts.extend((O/x['file']).read_bytes()for x in files if x['kind']=='derived')
privacy={k:sum(len(rx.findall(b))for b in texts)for k,rx in patterns.items()};assert all(x==0 for x in privacy.values()),privacy
proof={'schemaVersion':1,'repository':'vibracall-beep/PDF-','controllerSHA':CONTROL,'sourceSHA':SOURCE,'sourceRunID':40137438618,'runID':RUN,'runAttempt':1,'runConclusion':'success','workflowURL':f'https://github.com/vibracall-beep/PDF-/actions/runs/{RUN}','sourceTarSHA256':TAR,'sourceArtifactID':12578358642,'collection':'Normal authenticated GitHub API, original artifact ZIP checked against published digest, size, run and controller SHA; source identity checked from receipt against the independently authenticated source tar and manifest.','artifact':{'id':a['id'],'name':a['name'],'bytes':a['size_in_bytes'],'githubDigest':a['digest'],'sha256':rec['archiveSHA256'],'createdAt':a['created_at'],'expiresAt':a['expires_at'],'originalMembers':rec['files']},'preservedFiles':files,'logIdentity':identity,'actualCounts':counts,'sourceBinding':{'manifestComparedWithOriginalMacOS26Artifact':True,'GUIReceiptVerifiedBeforeAndAfter':True,'originalGUIFilesVerified':40,'noExecutableRebuiltOrReplaced':True},'visualReview':{'individualOriginalPNGsReviewed':32,'performedAfterWorkflow':True,'workflowOriginalReceiptHumanVisualReviewRemainsFalse':True,'originalsUnmodified':True},'privacyReview':{'textEntriesScanned':len(texts),'patternOccurrences':privacy,'redacted':False,'limits':'Pattern screening is not proof of absence of all possible sensitive data; synthetic fixture diagnostics and runtime paths remain in original logs.'},'limits':['The GUI capture runs outside the dependency sandbox; the isolated runtime gate passed separately.','One capture attempt with a 300-second deadline; static screenshots do not approve live interaction, scrolling outside the viewport, animations or human VoiceOver.','The target is a virtual Apple M1 with macOS 27.0.1, not a physical M4. No energy or Neural Engine usage measurements.','OCR errors in the Portuguese raster fixture remain visible with the explicitly selected English model.','Ad-hoc signing without Apple notarization. External device, Pages and signing-service checks require their own setup.','The 20 controller methods and 123 native groups are separate evidence; they were not added to the 491 distinct methods of the source matrix.']}
(O/'provenance.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'folder':str(O),'originals':sum(x['kind']=='original'for x in files),'derived':sum(x['kind']=='derived'for x in files),'privacyTextEntries':len(texts),'privacyPatterns':privacy}))
