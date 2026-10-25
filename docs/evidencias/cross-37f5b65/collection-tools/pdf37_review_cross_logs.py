#!/usr/bin/env python3
"""Offline review of already authenticated cross-run originals; no downloads."""
from pathlib import Path
from collections import Counter
import ast,hashlib,json,os,re,stat,struct,subprocess,sys,types,zipfile
ROOT=Path('/workspace/.cache/pdf-cross-37f5b65');REPO=Path('/workspace/PDF-')
SOURCE='37f5b65e35a9f70c716cfcd64db7ba69837f5c21';CONTROL='e4f6c056058d3482b18cdcc24011ccdc96327004';RUN=40243611339;JOB=121320462461
sys.dont_write_bytecode=True

def require(ok,why):
 if not ok:raise ValueError(why)
def read(path,limit):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as f:
  before=os.fstat(f.fileno());require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and 0<=before.st_size<=limit,'Bounded owned file required: '+path.name)
  data=f.read(limit+1);after=os.fstat(f.fileno());require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,len(data),after.st_mtime_ns,after.st_ctime_ns),'Input changed: '+path.name);return data
def digest(data):return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def load(path,limit=4*1024**2):return json.loads(read(path,limit))
def retain(path,raw):
 if os.path.lexists(path):require(read(path,len(raw))==raw,'Existing derivative differs: '+path.name);return
 with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
def pinned(relative):
 data=subprocess.check_output(['git','show',CONTROL+':'+relative],cwd=REPO,env=dict(os.environ,GIT_NO_LAZY_FETCH='1'))
 require(read(ROOT/'controller-source'/relative,2*1024**2)==data,'Pinned source mismatch: '+relative)
 module=types.ModuleType('pinned_'+Path(relative).stem);exec(compile(data,str(ROOT/'controller-source'/relative),'exec'),module.__dict__)
 return module,{'gitPath':relative,'commit':CONTROL,**digest(data),'executedFromGitVerifiedBytes':True}
summary=load(ROOT/'collector-summary.json');config=load(ROOT/'collector-configuration.json');run=load(ROOT/'collector-cross-run.json');jobs=load(ROOT/'collector-cross-jobs.json');api_artifacts=load(ROOT/'collector-cross-artifacts.json');state=load(ROOT/'collector-artifact-state.json')
require(config['sourceCommit']==SOURCE and config['controlCommit']==CONTROL and config['crossRunID']==RUN and config['crossAttempt']==1 and config['crossJobID']==JOB,'Configuration mismatch.')
require(run['id']==RUN and run['head_sha']==CONTROL and run['run_attempt']==1 and run['status']=='completed' and run['conclusion']=='success','Run identity/result mismatch.')
require(run['repository']['id']==run['head_repository']['id']==1431437116,'Repository mismatch.')
require(jobs['total_count']==1 and len(jobs['jobs'])==1,'Unexpected jobs.')
job=jobs['jobs'][0];require(job['id']==JOB and job['run_id']==RUN and job['head_sha']==CONTROL and job['run_attempt']==1 and job['name']=='compatible-binary' and 'xcode-27' in job['labels'] and job['status']=='completed' and job['conclusion']=='success','Job mismatch.')
require(all(s['conclusion']=='success' for s in job['steps']),'Non-success job step.')
require(all(summary[k] is True for k in ['completeNativeAndCrossGatesPassed','receiptVerified','lifecycleReceiptVerified']),'Collector gates incomplete.')
metadata=[];snapshot=Path(summary['snapshotDirectory'])
for label in ['cross-run','cross-jobs','cross-artifacts']:
 raw=read(ROOT/('collector-'+label+'.json'),4*1024**2);record=load(snapshot/(label+'-record.json'))
 require(raw==read(snapshot/(label+'.json'),4*1024**2) and record['authenticatedAPIResponse'] is True and digest(raw)=={'bytes':record['bytes'],'sha256':record['sha256']},'Metadata original binding mismatch.')
 metadata.append({'path':str(snapshot/(label+'.json')),**digest(raw),'endpoint':record['endpoint'],'authenticatedAPIResponse':True})
archives,archive_validator=pinned('diagnostics/delivery_archives.py');lifecycle_checker,lifecycle_validator=pinned('scripts/check_window_lifecycle.py')
archive=ROOT/'downloads'/f'run-{RUN}-attempt-1-logs.zip';raw=read(archive,64*1024**2);measure=digest(raw)
require(summary['originalRunLogs']['path']==str(archive) and measure=={k:summary['originalRunLogs'][k] for k in ['bytes','sha256']} and summary['originalRunLogs']['authenticatedAPIEndpoint'] is True,'Official ZIP binding mismatch.')
require(load(snapshot/'run-logs-record.json')==summary['originalRunLogs'],'Original download record differs.')
output=ROOT/'official-attempt-1-logs';output.mkdir(mode=0o700,exist_ok=True);require(output.lstat().st_uid==os.getuid() and stat.S_ISDIR(output.lstat().st_mode) and not output.lstat().st_mode&0o077,'Unsafe extraction target.')
texts={};members=[];aggregate=None
with archive.open('rb') as stream:
 length=min(len(raw),65557);stream.seek(len(raw)-length);tail=stream.read(length);offset=tail.rfind(b'PK\x05\x06');require(offset>=0 and offset+22<=len(tail),'Missing ZIP end record.')
 count=struct.unpack('<4s4H2IH',tail[offset:offset+22])[4];require(0<count<=128,'Unexpected inventory count.');archives._zip_directory(stream,len(raw),count)
 with zipfile.ZipFile(stream) as z:
  names=set();total=0
  for entry in z.infolist():
   name=entry.orig_filename;normal=archives._name(name);require(name==entry.filename and normal not in names,'Ambiguous log name.');names.add(normal)
   require(name=='0_compatible-binary.txt' or re.fullmatch(r'compatible-binary/(?:system|\d+_[^/]+)\.txt',name),'Unexpected log member.')
   require(stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and not entry.is_dir() and not entry.flag_bits&(1|0x40|0x2000) and entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and 0<=entry.file_size<=32*1024**2,'Unsafe member type/size.')
   total+=entry.file_size;require(total<=128*1024**2,'Expanded archive exceeds limit.')
  for entry in z.infolist():
   chunks=[];n=0
   with z.open(entry) as f:
    while chunk:=f.read(1024**2):n+=len(chunk);require(n<=entry.file_size,'Expanded member exceeds declaration.');chunks.append(chunk)
   data=b''.join(chunks);require(n==entry.file_size,'Truncated member.');members.append({'name':entry.filename,**digest(data)});texts[entry.filename]=data.decode()
   if entry.filename=='0_compatible-binary.txt':aggregate=data;retain(output/entry.filename,data)
require(aggregate is not None,'Missing aggregate job log.')
# Pure parser functions from our reviewed local collector, never downloaded code.
parser_file=Path('/tmp/pdf_collect_37_logs.py');parser_bytes=read(parser_file,128*1024);tree=ast.parse(parser_bytes)
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'clean','body','python_suites'} or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ansi' for t in n.targets)]
parser={'re':re};exec(compile(ast.Module(body=nodes,type_ignores=[]),'<reviewed local pure parser>','exec'),parser)
clean=parser['clean'];body=parser['body'];parse_suites=parser['python_suites']
text=aggregate.decode();lines=text.splitlines();require(SOURCE in text and CONTROL in text,'Source/controller missing in log.')
expected_native=set(re.findall(r'\b(?:audit|auditAsync)\("([^\"]+)"',subprocess.check_output(['git','show',SOURCE+':Sources/PDF/MacSmokeTests.swift'],cwd=REPO,text=True)))
require(len(expected_native)==44,'Native source inventory differs.')
starts=Counter(re.findall(r'Native check starting: ([^\r\n]+)',text));passes=Counter(re.findall(r'Native check passed: ([^\r\n]+)',text));expected_steps={'Install the unchanged macOS 26 binary on macOS 27':2,'Deny host dependencies and validate runtime, metadata and native operations':1}
by_step=[];step_starts=Counter();step_passes=Counter();python_steps=[]
for name,t in texts.items():
 m=re.fullmatch(r'compatible-binary/\d+_(.+)\.txt',name)
 if not m:continue
 title=m[1];a=Counter(re.findall(r'Native check starting: ([^\r\n]+)',t));b=Counter(re.findall(r'Native check passed: ([^\r\n]+)',t));step_starts.update(a);step_passes.update(b)
 if a or b or title in expected_steps:
  require(title in expected_steps and a==b and set(b)==expected_native and set(b.values())=={expected_steps[title]},'Native per-step count mismatch.')
  by_step.append({'step':title,'member':name,'starts':sum(a.values()),'passes':sum(b.values()),'groups':len(b),'executions':expected_steps[title],'startPassMultisetEqual':a==b})
 for suite in parse_suites(t):python_steps.append({**suite,'step':title,'member':name})
require(Counter(x['step'] for x in by_step)==Counter({k:1 for k in expected_steps}),'Missing/duplicate native step log.')
require(starts==passes==step_starts==step_passes and set(passes)==expected_native and set(passes.values())=={3},'Native aggregate/step multisets differ.')
suites=parse_suites(text);fingerprint=lambda xs:Counter((v['cases'],v['passed'],v['skipped'],v['status'],v['seconds']) for v in xs)
require(fingerprint(suites)==fingerprint(python_steps) and all(v['status']=='passed' for v in suites),'Python suite summary mismatch/failure.')
# Recheck root's two authenticated small artifacts, all original members, without extracting or executing anything else.
artifacts=[]
for record in state:
 api=next(a for a in api_artifacts['artifacts'] if a['id']==record['artifactID']);path=ROOT/'downloads'/f"{record['artifactID']}.zip";blob=read(path,64*1024**2)
 require(digest(blob)==record['archive']=={'bytes':api['size_in_bytes'],'sha256':api['digest'].removeprefix('sha256:')},'Artifact digest mismatch.')
 require(api['workflow_run']['id']==RUN and api['workflow_run']['head_sha']==CONTROL,'Artifact source mismatch.')
 allowed=record['files'];expanded=0
 with path.open('rb') as stream:
  archives._zip_directory(stream,len(blob),len(allowed))
  with zipfile.ZipFile(stream) as z:
   require(set(z.namelist())==set(allowed) and len(z.infolist())==len(allowed),'Artifact members differ.')
   for e in z.infolist():
    archives._name(e.filename,flat=True);require(not e.is_dir() and not e.flag_bits&1 and stat.S_IFMT(e.external_attr>>16) in (0,stat.S_IFREG) and e.file_size<=32*1024**2,'Unsafe artifact member.')
    expanded+=e.file_size;require(expanded<=128*1024**2,'Artifact expansion bound exceeded.')
    value=z.read(e);require(digest(value)==allowed[e.filename] and value==read(ROOT/'extracted'/record['name']/e.filename,32*1024**2),'Artifact original differs.')
 artifacts.append({'id':record['artifactID'],'name':record['name'],'path':str(path),**digest(blob),'members':len(allowed),'expandedBytes':expanded,'githubDigestMatched':True,'allMemberCRCAndHashesVerified':True})
platform_dir=ROOT/'extracted/PDF-cross-platform-validated';life_dir=ROOT/'extracted/PDF-cross-lifecycle'
platform=load(platform_dir/'PDF-cross-platform.json');gui=load(platform_dir/'PDF-cross-gui.json');before=load(platform_dir/'PDF-cross-gui-before.json');verified=load(platform_dir/'PDF-cross-verified.json');life=load(life_dir/'cross.json');receipt=load(life_dir/'cross-receipt.json')
lifecycle_checker.validate(life)
require(receipt['sourceCommit']==SOURCE and receipt['scope']=='cross-installed-binary' and receipt['status']=='passed' and receipt['report']==digest(read(life_dir/'cross.json',2*1024**2)),'Lifecycle receipt mismatch.')
require(gui['sourceCommit']==before['sourceCommit']==verified['sourceCommit']==platform['sourceCommit']==SOURCE and gui['sourceRunID']==40239018570,'Application source binding mismatch.')
require(gui['beforeSHA256']==hashlib.sha256(read(platform_dir/'PDF-cross-gui-before.json',2*1024**2)).hexdigest() and platform['guiReceiptSHA256']==hashlib.sha256(read(platform_dir/'PDF-cross-gui.json',2*1024**2)).hexdigest(),'GUI receipt hash mismatch.')
require(gui['installedBinary']==before['installedBinary']=={'PDF.app/'+k:v for k,v in receipt['installedBundleFiles'].items()},'Installed executable/Info.plist binding differs.')
require(all(gui[k] is True for k in ['archiveUnchanged','installedBundleManifestMatchedBeforeAndAfter','guiCapturePassed','guiOutsideDependencySandbox','dependencyIsolationSeparate']),'GUI gate false.')
require(gui['rebuiltOnDestination'] is False and gui['captureAttempts']==1 and gui['captureDeadlineSeconds']==300 and gui['pngCount']==33 and gui['ownWindowAXCount']==7 and gui['originalOCRFileCount']==2,'GUI scope mismatch.')
for name,value in dict(gui['originals'],**gui['logs']).items():require(digest(read(platform_dir/name,32*1024**2))==value,'GUI original/log binding differs.')
require(platform['archiveSHA256']==gui['archiveSHA256']==before['archiveSHA256']==verified['archiveSHA256']==config['archiveSHA256'],'Archive digest binding differs.')
require(all(platform[k] is True for k in ['crossOSTestPassed','freshInstallPassed','isolatedRuntimePassed','nativeSmokePassed','installedBinaryGUIPassed','appIntentsMetadataVerified']),'Platform gate false.')
require(all(platform[k] is False for k in ['rebuiltOnDestination','physicalM4Measured','neuralEngineMeasured','humanVoiceOverTested','appleNotarized']),'Platform claims unsupported scope.')
validation_log=read(platform_dir/'PDF-cross-gui-validation.log',32*1024**2).decode()
ax=[{'file':m[1],'nodes':int(m[2]),'failures':int(m[3]),'controlsToReview':int(m[4])} for m in re.finditer(r'(?m)^(PDF-preview[^\n:]*accessibility\.json): (\d+) nodes, (\d+) failures, (\d+) controls to review$',validation_log)]
require(len(ax)==7 and all(x['failures']==0 for x in ax),'AX validation summaries incomplete/failed.')
fatal=[{'line':i+1,'text':body(s)} for i,s in enumerate(lines) if any(k in clean(s) for k in ['##[error]','Native check failed:','subprocess.TimeoutExpired:','RuntimeError: soffice'])]
baselines=[{'line':i+1,'text':body(s)} for i,s in enumerate(lines) if 'PDF structure audit:' in s and 'FAILED' in s]
require(all('raw PDFKit' in x['text'] and 'diagnostic only, not the product output' in x['text'] for x in baselines),'Production PDF structure failure observed.')
coregraphics=[]
for i,s in enumerate(lines):
 if 'CoreGraphics PDF has logged an error' not in s:continue
 classified='invalid stream-length control: correctly rejected' in '\n'.join(lines[max(0,i-5):i]) and 'production normalization of recoverable stream length: passed' in '\n'.join(lines[i+1:i+7])
 coregraphics.append({'line':i+1,'negativeControlThenSuccessfulNormalization':classified})
require(not fatal and all(v['negativeControlThenSuccessfulNormalization'] for v in coregraphics),'Fatal/unclassified CoreGraphics markers.')
warning_lines=[{'line':i+1,'text':body(s)} for i,s in enumerate(lines) if 'warning:' in body(s).lower() or '##[warning]' in body(s)]
review={'schemaVersion':1,'sourceCommit':SOURCE,'controllerCommit':CONTROL,'runID':RUN,'attempt':1,'jobID':JOB,'APIConclusion':'success','stepResults':[{'number':s['number'],'name':s['name'],'conclusion':s['conclusion']} for s in job['steps']],'officialLogArchive':{'path':str(archive),**measure,'authenticatedByRootCollector':True,'upstreamDigestProvided':False,'allCRCVerified':True,'memberCount':len(members),'expandedBytes':sum(x['bytes'] for x in members),'limits':{'archive':64*1024**2,'member':32*1024**2,'total':128*1024**2}},'officialLogMembers':members,'fullJobLog':{'path':str(output/'0_compatible-binary.txt'),**digest(aggregate)},'metadataOriginals':metadata,'native':{'distinctGroups':44,'starts':sum(starts.values()),'passes':sum(passes.values()),'repetitionsPerGroup':3,'startPassMultisetEqual':starts==passes,'perStepCountersMatchAggregate':starts==step_starts and passes==step_passes,'startCounts':dict(sorted(starts.items())),'passCounts':dict(sorted(passes.items())),'byStep':by_step,'completeSmokeMarkers':text.count('PDF native smoke tests passed')},'controlPythonSuites':python_steps,'originalArtifacts':artifacts,'lifecycle':{'status':life['status'],'checks':len(life['checks']),'requests':life['presentationRequests'],'readyActions':life['readyActionsExecuted'],'milliseconds':life['totalMilliseconds'],'scope':receipt['scope'],'privateStateCleaned':life['privateStateCleaned'],'receiptHashAndBinaryBindingVerified':True,'allChecksReplayedWithExactControllerGit':True,'bundleBytesIndependentlyRehashedHere':False,'limitations':life['limitations']},'gui':{'PNGCount':33,'ownWindowAXCount':7,'originalOCRFileCount':2,'captureAttempts':1,'captureDeadlineSeconds':300,'rebuiltOnDestination':False,'originalsAndLogsBoundToReceipt':True,'sameInstalledBinaryAsLifecycle':True,'AXSummaries':ax,'AXControlsToReviewTotal':sum(x['controlsToReview'] for x in ax),'humanVoiceOverTested':False,'humanVisualReviewPerformedByThisTask':False},'platform':platform,'rawPDFKitBaselineDiagnostics':baselines,'coreGraphicsWarnings':coregraphics,'warningRecords':warning_lines,'fatalMarkers':fatal,'validators':[archive_validator,lifecycle_validator],'pureLocalParser':{'path':str(parser_file),**digest(parser_bytes)},'noNewDownload':True,'noArtifactCodeExecuted':True,'privateDeliveryApprovedByThisReport':False,'scope':'Same authenticated macOS26 tar installed and tested on macOS27; no general market superiority, physical M4, Neural Engine, energy, human VoiceOver or private-release approval.'}
path=Path('/tmp/pdf-cross-37f5b65-full-log-review.json');retain(path,(json.dumps(review,indent=2,ensure_ascii=False)+'\n').encode())
print(json.dumps({'review':str(path),'archiveBytes':measure['bytes'],'archiveSHA256':measure['sha256'],'members':len(members),'fullLogBytes':len(aggregate),'nativeStarts':sum(starts.values()),'nativePasses':sum(passes.values()),'groups':44,'repetitions':3,'controlPythonSuites':[(x['cases'],x['passed'],x['skipped']) for x in python_steps],'rawPDFKitBaselineFailures':len(baselines),'coreGraphicsWarnings':len(coregraphics),'warningRecords':warning_lines,'AXControlsToReview':sum(x['controlsToReview'] for x in ax),'fatalMarkers':len(fatal)},ensure_ascii=False))
