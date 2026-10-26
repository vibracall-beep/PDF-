#!/usr/bin/env python3
"""Collect a pinned appearance-only workflow's authenticated original evidence.

Preparation is offline: importing this module performs no file/network operation.
Only main() may call gh after an explicit complete configuration is supplied.
Application binaries/transport tar are never downloaded, restored or executed.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, importlib.util, io, json, os, re, resource, stat, struct, subprocess, sys, time, zipfile, zlib
REPO=Path('/workspace/PDF-')
API='/repos/vibracall-beep/PDF-'
REPOSITORY_ID=1431437116
WORKFLOW='.github/workflows/appearance-compatibility.yml'
JOB_LABELS={'compile-sdk26':'macos-26','same-binary-xcode27':'xcode-27'}
ARTIFACTS={'compile-sdk26':'PDF-appearance-sdk26','same-binary-xcode27':'PDF-appearance-same-binary-xcode27'}
TRANSFER='PDF-appearance-minimal-bundle-sdk26'
PHASES=('light-initial','dark-attached-1','dark-attached-2','customization','dark-recreated','light-return','system')
PNG_NAMES=('PDF-appearance.png',)+tuple('PDF-appearance.'+p+'.png' for p in PHASES[1:])
JSON_NAMES=('PDF-appearance.appearance.json','appearance-validation.json','appearance-bundle.json')
LOGS={'compile-sdk26':('origin.log','build.log','bundle.log','capture.log','validation.log'),
      'same-binary-xcode27':('origin.log','restore.log','capture.log','validation.log')}
MIB=1024**2
MAX_ARCHIVE=128*MIB
MAX_PNG=80*MIB
MAX_REPORT=2*MIB
MAX_LOG=32*MIB
MAX_EXPANDED=256*MIB
MAX_API=4*MIB
MAX_OFFICIAL_ZIP=64*MIB
CONFIG_KEYS={'schemaVersion','sourceCommit','controlCommit','runID','runAttempt','jobIDs','outputDirectory'}


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()
def fingerprint(raw):return {'bytes':len(raw),'sha256':sha(raw)}
def encode(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()

def parse(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'Duplicate JSON key: '+key);result[key]=value
        return result
    def invalid(value):raise ValueError('Non-finite JSON constant: '+value)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def read_regular(path,limit,empty=False):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        before=os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and (0 if empty else 1)<=before.st_size<=limit,'Expected bounded owned regular file: '+str(path))
        raw=stream.read(limit+1);after=os.fstat(stream.fileno())
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,len(raw),after.st_mtime_ns,after.st_ctime_ns),'File changed while reading: '+str(path))
        return raw


def folder(path):
    path.mkdir(mode=0o700,parents=True,exist_ok=True);s=path.lstat()
    require(stat.S_ISDIR(s.st_mode) and s.st_uid==os.getuid() and not s.st_mode&0o077,'Private owned directory required: '+str(path))


def write(path,raw,replace=False):
    if os.path.lexists(path):
        existing=read_regular(path,max(len(raw),MAX_API),empty=True)
        if existing==raw:return
        require(replace,'Existing original differs: '+str(path))
    tmp=path.with_name(path.name+'.new-'+str(os.getpid())+'-'+str(time.time_ns()))
    try:
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        if replace:os.replace(tmp,path)
        else:os.link(tmp,path,follow_symlinks=False);tmp.unlink()
    finally:
        if os.path.lexists(tmp):tmp.unlink()


def configuration(path):
    value=parse(read_regular(path,16384))
    require(isinstance(value,dict) and set(value)==CONFIG_KEYS and type(value['schemaVersion']) is int and value['schemaVersion']==1,'Configuration fields/schema differ.')
    for key in ('sourceCommit','controlCommit'):
        require(isinstance(value[key],str) and re.fullmatch('[0-9a-f]{40}',value[key]),'Exact source and control commits required.')
    for key in ('runID','runAttempt'):
        require(type(value[key]) is int and value[key]>0,'Positive exact run and attempt required.')
    require(isinstance(value['jobIDs'],dict) and set(value['jobIDs'])==set(JOB_LABELS) and all(type(v) is int and v>0 for v in value['jobIDs'].values()) and len(set(value['jobIDs'].values()))==2,'Two explicit distinct job IDs required.')
    require(value['outputDirectory']==f"/workspace/.cache/pdf-appearance-{value['sourceCommit'][:7]}-{value['runID']}",'Dedicated source/run-specific output directory required.')
    return value


def datetime_at(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'));require(result.tzinfo is not None,'Timezone required.');return result


def validate_run_jobs(config,run,jobs):
    require(run['id']==config['runID'] and run['head_sha']==config['controlCommit'] and run['head_commit']['id']==config['controlCommit'] and run['run_attempt']==config['runAttempt'] and run['event']=='workflow_dispatch' and run['path']==WORKFLOW and run['repository']['id']==run['head_repository']['id']==REPOSITORY_ID,'Run identity/workflow/source differs.')
    require(run['status']=='completed' and run['conclusion'] is not None,'The exact attempt must be terminal before collecting artifacts/logs.')
    require(jobs['total_count']==2 and len(jobs['jobs'])==2,'Expected exactly two diagnostic jobs.')
    found={}
    for name,ident in config['jobIDs'].items():
        matches=[j for j in jobs['jobs'] if j['id']==ident];require(len(matches)==1,'Configured job absent.')
        job=matches[0]
        require(job['name']==name and job['run_id']==config['runID'] and job['run_attempt']==config['runAttempt'] and job['head_sha']==config['controlCommit'] and (JOB_LABELS[name] in job['labels'] or job['conclusion']=='skipped' and job['labels']==[]) and job['status']=='completed' and job['conclusion'] is not None,'Job identity/label/terminal status differs.')
        found[name]=job
    return found


def validate_artifact(config,run,job,item,name):
    require(item['name']==name and type(item['id']) is int and item['id']>0 and item.get('expired') is False and type(item['size_in_bytes']) is int and 0<item['size_in_bytes']<=MAX_ARCHIVE,'Artifact identity/size/expiry differs.')
    require(isinstance(item.get('digest'),str) and re.fullmatch('sha256:[0-9a-f]{64}',item['digest']),'Authenticated artifact digest required.')
    origin=item['workflow_run']
    require(origin['id']==config['runID'] and origin['head_sha']==config['controlCommit'] and origin['head_repository_id']==origin['repository_id']==REPOSITORY_ID and origin['head_branch']==run['head_branch'],'Artifact workflow/source/repository differs.')
    created=datetime_at(item['created_at']);updated=datetime_at(item['updated_at'])
    require(datetime_at(job['started_at'])<=created<=updated<=datetime_at(job['completed_at']),'Artifact does not belong to the configured terminal job interval.')


def inventory_for(job):return set(PNG_NAMES)|set(JSON_NAMES)|set(LOGS[job])
def cap_for(name):return MAX_PNG if name.endswith('.png') else MAX_LOG if name.endswith('.log') else MAX_REPORT


def unpack_small_zip(raw,allowed,archives,limit=MAX_EXPANDED,flat=True):
    """Return bounded verified bytes; this never invokes extract or executes members."""
    require(0<len(raw)<=MAX_ARCHIVE,'ZIP exceeds bound.')
    stream=io.BytesIO(raw);tail=raw[-65557:];offset=tail.rfind(b'PK\x05\x06')
    require(offset>=0 and offset+22<=len(tail),'Missing ZIP end record.')
    count=struct.unpack('<4s4H2IH',tail[offset:offset+22])[4]
    require(0<count<=len(allowed),'ZIP member count differs.')
    archives._zip_directory(stream,len(raw),count)
    result={};normalized_names=set();expanded=0
    with zipfile.ZipFile(stream) as z:
        for info in z.infolist():
            name=info.orig_filename;normal=archives._name(name,flat=flat)
            require(name==info.filename and name in allowed and name not in result and normal not in normalized_names,'Unexpected, duplicate or ambiguous ZIP member.')
            normalized_names.add(normal)
            require(not info.is_dir() and stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG) and not info.external_attr&0x10 and not info.flag_bits&(1|0x40|0x2000) and info.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and 0<=info.file_size<=allowed[name],'Unsafe member type, encoding or size.')
            expanded+=info.file_size;require(expanded<=limit,'ZIP expansion exceeds bound.')
            chunks=[];total=0
            with z.open(info) as source:
                while chunk:=source.read(MIB):
                    total+=len(chunk);require(total<=info.file_size,'Member exceeds declared length.');chunks.append(chunk)
            require(total==info.file_size,'Truncated ZIP member.');result[name]=b''.join(chunks)
    return result


def origin_values(raw):
    text=raw.decode('utf-8');result={}
    for line in text.splitlines():
        match=re.fullmatch(r'(source_commit|control_commit|run_id|run_attempt|sdk|artifact_id|archive_sha256|manifest_sha256)=(.*)',line)
        if match:
            require(match[1] not in result,'Duplicate origin assertion.');result[match[1]]=match[2]
    return result


class Collector:
    def __init__(self,config):
        self.config=config;self.root=Path(config['outputDirectory'])
        folder(self.root)
        for name in ('snapshots','downloads','extracted','exact-source'):folder(self.root/name)
        self.snapshot=self.root/'snapshots'/(str(time.time_ns())+'-'+str(os.getpid()));folder(self.snapshot)
        prior=self.root/'collector-configuration.json'
        write(prior,encode(config))
        state=self.root/'collector-artifact-state.json'
        self.state=parse(read_regular(state,8*MIB)) if state.exists() else {'schemaVersion':1,'configuration':config,'attempts':{}}
        require(self.state['schemaVersion']==1 and self.state['configuration']==config and isinstance(self.state['attempts'],dict),'Existing download state belongs to another run.')
    def persist(self):write(self.root/'collector-artifact-state.json',encode(self.state),replace=True)
    def fetch(self,endpoint,label):
        p=subprocess.run(['gh','api','--hostname','github.com',API+endpoint],capture_output=True,timeout=45)
        if p.returncode:raise RuntimeError(json.dumps({'endpoint':endpoint,'exit':p.returncode,'http':re.findall(r'HTTP (\d+)',p.stderr.decode(errors='replace'))}))
        require(0<len(p.stdout)<=MAX_API,'API response outside bound.')
        write(self.snapshot/(label+'.json'),p.stdout)
        write(self.root/('collector-'+label+'.json'),p.stdout,replace=True)
        write(self.snapshot/(label+'-record.json'),encode({'endpoint':API+endpoint,'authenticatedAPIResponse':True,**fingerprint(p.stdout)}))
        return parse(p.stdout)
    def exact_source(self):
        modules={};records=[]
        paths=['diagnostics/delivery_archives.py','scripts/check_appearance_preview.py',WORKFLOW]
        for label,commit,selection in [('controller',self.config['controlCommit'],paths),('application',self.config['sourceCommit'],['scripts/check_appearance_preview.py','scripts/PDF-Info.plist','scripts/prepare-window-audit-bundle.py','scripts/run-with-timeout.py','Sources/PDF/ToolbarRenderingAudit.swift','Sources/PDF/ApplicationAppearance.swift','Sources/PDF/MacPreview.swift','Sources/PDF/AccessibilityAudit.swift','Sources/PDF/PDFApp.swift','Sources/PDF/CustomizationView.swift','Sources/PDF/RecoveryStore.swift','Sources/PDF/WorkspaceModel.swift','Sources/PDF/SessionAnnotationAuditChecks.swift'])]:
            for path in selection:
                p=subprocess.run(['git','show',commit+':'+path],cwd=REPO,check=True,capture_output=True,timeout=30,env=dict(os.environ,GIT_NO_LAZY_FETCH='1'))
                require(0<len(p.stdout)<=2*MIB,'Source selection outside bound.')
                target=self.root/'exact-source'/label/path;folder(target.parent);write(target,p.stdout)
                records.append({'role':label,'commit':commit,'path':path,**fingerprint(p.stdout)})
        require(read_regular(self.root/'exact-source/controller/scripts/check_appearance_preview.py',2*MIB)==read_regular(self.root/'exact-source/application/scripts/check_appearance_preview.py',2*MIB),'Source and control appearance helpers differ; workflow requires exact equality.')
        for name,path in [('archives','diagnostics/delivery_archives.py'),('appearance','scripts/check_appearance_preview.py')]:
            target=self.root/'exact-source/controller'/path
            spec=importlib.util.spec_from_file_location('pinned_appearance_'+name,target);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules[name]=module
        write(self.root/'collector-source-files.json',encode(records),replace=True)
        return modules
    def download(self,item):
        ident=str(item['id']);record=self.state['attempts'].setdefault(ident,{'artifactID':item['id'],'name':item['name'],'sourceCommit':self.config['sourceCommit'],'controllerCommit':self.config['controlCommit'],'runID':self.config['runID'],'runAttempt':self.config['runAttempt'],'archiveBytes':item['size_in_bytes'],'githubDigest':item['digest'],'downloadAttempts':0})
        require((record['name'],record['archiveBytes'],record['githubDigest'],record['sourceCommit'],record['controllerCommit'],record['runID'],record['runAttempt'])==(item['name'],item['size_in_bytes'],item['digest'],self.config['sourceCommit'],self.config['controlCommit'],self.config['runID'],self.config['runAttempt']),'Artifact download identity changed.')
        dest=self.root/'downloads'/(ident+'.zip')
        if not dest.exists():
            require(record['downloadAttempts']==0,'Download already attempted; coordinate before retrying a failed request.')
            record['downloadAttempts']+=1;record['attemptedAtUTC']=datetime.now(timezone.utc).isoformat();self.persist()
            tmp=dest.with_name(dest.name+'.partial-'+str(os.getpid()))
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                def bound():resource.setrlimit(resource.RLIMIT_FSIZE,(item['size_in_bytes']+1,item['size_in_bytes']+1))
                with os.fdopen(fd,'wb') as f:
                    p=subprocess.run(['gh','api','--hostname','github.com',API+f'/actions/artifacts/{ident}/zip'],stdout=f,stderr=subprocess.PIPE,timeout=60,preexec_fn=bound);f.flush();os.fsync(f.fileno())
                if p.returncode:
                    record['downloadError']={'exit':p.returncode,'http':re.findall(r'HTTP (\d+)',p.stderr.decode(errors='replace'))};self.persist();raise RuntimeError(json.dumps(record['downloadError']))
                raw=read_regular(tmp,MAX_ARCHIVE);require(len(raw)==item['size_in_bytes'] and sha(raw)==item['digest'][7:],'Downloaded ZIP differs from GitHub digest.')
                os.link(tmp,dest,follow_symlinks=False);tmp.unlink()
            except subprocess.TimeoutExpired:
                record['downloadError']={'timeoutSeconds':60};self.persist();raise
            finally:
                if os.path.lexists(tmp):tmp.unlink()
        raw=read_regular(dest,MAX_ARCHIVE);require(len(raw)==item['size_in_bytes'] and sha(raw)==item['digest'][7:],'Cached original ZIP changed; no automatic redownload.')
        record.update(downloaded=True,archiveSHA256=sha(raw));self.persist();return raw,record
    def inspect(self,job,item,modules,transfer):
        raw,record=self.download(item);allowed={name:cap_for(name) for name in inventory_for(job)}
        files=unpack_small_zip(raw,allowed,modules['archives']);dest=self.root/'extracted'/item['name'];folder(dest)
        require({p.name for p in dest.iterdir()}<=set(files),'Prior extraction has extra files.')
        for name,value in files.items():write(dest/name,value)
        record.update(directory=str(dest),files={k:fingerprint(v) for k,v in sorted(files.items())},inventoryComplete=set(files)==set(allowed),missingFiles=sorted(set(allowed)-set(files)),originalZIPAndMemberCRCVerified=True)
        validation={'passed':False,'humanVisualApproval':False,'completeApplicationApproved':False,'bundleBytesIndependentlyRehashedHere':False}
        try:
            require(record['inventoryComplete'],'Evidence inventory incomplete; original partial evidence retained.')
            origin=origin_values(files['origin.log'])
            require(all(origin.get(key)==str(value) for key,value in {'source_commit':self.config['sourceCommit'],'control_commit':self.config['controlCommit'],'run_id':self.config['runID'],'run_attempt':self.config['runAttempt']}.items()),'Workflow source/control/run origin assertions differ.')
            manifest=modules['appearance'].manifest_at(dest/'appearance-bundle.json',self.config['sourceCommit'])
            report,originals=modules['appearance'].validate_report(dest)
            receipt=modules['appearance'].parse_json(files['appearance-validation.json'])
            expected_fields={'schemaVersion','scope','sourceCommit','sourceCommitAuthenticatedByThisHelper','status','completeApplicationApproved','humanVisualReview','universalWCAGCertification','engineRuntimeInstalled','externalDeadlineSeconds','originals','unchangedBundleFiles','archive','operatingSystem','nativeChecksPassed'}
            require(isinstance(receipt,dict) and set(receipt)==expected_fields and type(receipt['schemaVersion']) is int and receipt['schemaVersion']==1 and receipt['scope']=='minimal-appearance-diagnostic-only' and receipt['sourceCommit']==self.config['sourceCommit'] and receipt['status']=='passed','Appearance receipt status/schema/source differs.')
            require(all(receipt[key] is False for key in ('sourceCommitAuthenticatedByThisHelper','completeApplicationApproved','humanVisualReview','universalWCAGCertification','engineRuntimeInstalled')) and receipt['externalDeadlineSeconds']==90,'Appearance receipt overclaims scope/deadline.')
            require(receipt['originals']==originals and receipt['unchangedBundleFiles']==manifest['files'] and receipt['archive']==manifest['tar'] and receipt['operatingSystem']==report['operatingSystem'] and receipt['nativeChecksPassed']==len(modules['appearance'].CHECKS),'Originals/bundle/report receipt binding differs.')
            plist=read_regular(self.root/'exact-source/application/scripts/PDF-Info.plist',65536)
            require({k:manifest['files']['Contents/Info.plist'][k] for k in ('bytes','sha256')}==fingerprint(plist),'Manifest production Info.plist differs from exact source.')
            require(manifest['files']['Contents/Resources/installation.lock']['bytes']==0 and manifest['files']['Contents/Resources/installation.lock']['sha256']==sha(b''),'Installation lock is not empty.')
            os_major='26' if job=='compile-sdk26' else '27';require(re.match(r'^Version '+os_major+r'(?:\.|\s)',report['operatingSystem']) is not None,'Observed OS differs from runner role.')
            if job=='compile-sdk26':require(origin.get('sdk')==manifest['builtSDK'],'SDK26 origin and bundle manifest differ.')
            else:
                require(transfer is not None and origin.get('artifact_id')==str(transfer['id']) and origin.get('archive_sha256')==manifest['tar']['sha256'] and origin.get('manifest_sha256')==sha(files['appearance-bundle.json']),'Target transfer artifact/hash origin differs.')
            validation.update(passed=True,manifest=fingerprint(files['appearance-bundle.json']),archive=manifest['tar'],unchangedBundleFiles=manifest['files'],builtSDK=manifest['builtSDK'],operatingSystem=report['operatingSystem'],nativeChecksPassed=receipt['nativeChecksPassed'],originals=originals,exactSourceCheckerReplayed=True,scope='Authenticated diagnostic reports and same bundle declarations; no local binary execution, no full application/installation approval.')
        except (ValueError,KeyError,TypeError,OSError,OverflowError,zlib.error,struct.error) as e:
            validation['error']={'type':type(e).__name__,'message':str(e)[:2048]}
        record['validation']=validation;self.persist();return record
    def official_logs(self,modules,jobs):
        endpoint=f"/actions/runs/{self.config['runID']}/attempts/{self.config['runAttempt']}/logs"
        dest=self.root/'downloads'/f"run-{self.config['runID']}-attempt-{self.config['runAttempt']}-logs.zip"
        if not dest.exists():
            tmp=dest.with_name(dest.name+'.partial-'+str(os.getpid()));fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                def bound():resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_OFFICIAL_ZIP,MAX_OFFICIAL_ZIP))
                with os.fdopen(fd,'wb') as f:
                    p=subprocess.run(['gh','api','--hostname','github.com',API+endpoint],stdout=f,stderr=subprocess.PIPE,timeout=60,preexec_fn=bound);f.flush();os.fsync(f.fileno())
                if p.returncode:raise RuntimeError(json.dumps({'officialLogExit':p.returncode,'http':re.findall(r'HTTP (\d+)',p.stderr.decode(errors='replace'))}))
                read_regular(tmp,MAX_OFFICIAL_ZIP);os.link(tmp,dest,follow_symlinks=False);tmp.unlink()
            finally:
                if os.path.lexists(tmp):tmp.unlink()
        raw=read_regular(dest,MAX_OFFICIAL_ZIP)
        # Bound the directory before ZipFile can allocate an unbounded entry list.
        stream=io.BytesIO(raw);tail=raw[-65557:];offset=tail.rfind(b'PK\x05\x06')
        require(offset>=0 and offset+22<=len(tail),'Missing official ZIP end record.')
        count=struct.unpack('<4s4H2IH',tail[offset:offset+22])[4]
        require(0<count<=128,'Unexpected official log directory count.')
        modules['archives']._zip_directory(stream,len(raw),count)
        with zipfile.ZipFile(stream) as z:
            allowed={}
            for i in z.infolist():
                require(re.fullmatch(r'[01]_(compile-sdk26|same-binary-xcode27)\.txt',i.filename) or re.fullmatch(r'(compile-sdk26|same-binary-xcode27)/(system|\d+_[^/]+)\.txt',i.filename),'Unexpected official log path.')
                allowed[i.filename]=MAX_LOG
        require(0<len(allowed)<=128,'Unexpected official log count.')
        files=unpack_small_zip(raw,allowed,modules['archives'],limit=128*MIB,flat=False)
        destdir=self.root/'official-attempt-logs';folder(destdir);aggregates=[]
        for name,value in files.items():
            if re.fullmatch(r'[01]_(compile-sdk26|same-binary-xcode27)\.txt',name):
                write(destdir/name,value);aggregates.append({'name':name,**fingerprint(value)})
        required={name for name,j in jobs.items() if j.get('steps')}
        require({re.fullmatch(r'[01]_(.*)\.txt',x['name'])[1] for x in aggregates}==required,'Official aggregate job logs are incomplete.')
        result={'endpoint':API+endpoint,'path':str(dest),**fingerprint(raw),'authenticatedAPIEndpoint':True,'upstreamDigestProvided':False,'allMemberCRCVerified':True,'files':{k:fingerprint(v) for k,v in sorted(files.items())},'aggregates':aggregates,'artifactCodeExecuted':False}
        write(self.root/'collector-official-logs.json',encode(result),replace=True);return result
    def run(self):
        run=self.fetch(f"/actions/runs/{self.config['runID']}",'run-before')
        jobsraw=self.fetch(f"/actions/runs/{self.config['runID']}/attempts/{self.config['runAttempt']}/jobs?per_page=100",'jobs-before');jobs=validate_run_jobs(self.config,run,jobsraw)
        metadata=self.fetch(f"/actions/runs/{self.config['runID']}/artifacts?per_page=100",'artifacts-before')
        require(type(metadata['total_count']) is int and metadata['total_count']==len(metadata['artifacts'])<=3,'Unexpected artifacts/pagination; only focal diagnostic artifacts permitted.')
        require(len({a['name'] for a in metadata['artifacts']})==len(metadata['artifacts']) and all(a['name'] in set(ARTIFACTS.values())|{TRANSFER} for a in metadata['artifacts']),'Artifact names differ from focal contract.')
        byname={a['name']:a for a in metadata['artifacts']};transfer=byname.get(TRANSFER)
        if transfer:validate_artifact(self.config,run,jobs['compile-sdk26'],transfer,TRANSFER)
        modules=self.exact_source();results={}
        for job,name in ARTIFACTS.items():
            item=byname.get(name)
            if item is None:results[job]={'missingArtifact':name,'validation':{'passed':False}};continue
            validate_artifact(self.config,run,jobs[job],item,name);results[job]=self.inspect(job,item,modules,transfer)
        official=self.official_logs(modules,jobs)
        after=self.fetch(f"/actions/runs/{self.config['runID']}",'run-after')
        jobs_after=self.fetch(f"/actions/runs/{self.config['runID']}/attempts/{self.config['runAttempt']}/jobs?per_page=100",'jobs-after');checked=validate_run_jobs(self.config,after,jobs_after)
        artifacts_after=self.fetch(f"/actions/runs/{self.config['runID']}/artifacts?per_page=100",'artifacts-after')
        require(type(artifacts_after['total_count']) is int and artifacts_after['total_count']==len(artifacts_after['artifacts'])<=3 and len({a['id'] for a in artifacts_after['artifacts']})==len(artifacts_after['artifacts']),'Final artifact pagination or ID inventory differs.')
        identity=lambda xs:{a['id']:(a['name'],a['digest'],a['size_in_bytes'],a['expired'],a['workflow_run']) for a in xs['artifacts']}
        require(after['conclusion']==run['conclusion'] and {k:j['conclusion'] for k,j in checked.items()}=={k:j['conclusion'] for k,j in jobs.items()} and identity(metadata)==identity(artifacts_after),'Terminal run/jobs/artifact identities changed during collection.')
        passed=run['conclusion']=='success' and all(j['conclusion']=='success' for j in jobs.values()) and all(r['validation']['passed'] for r in results.values())
        same=False
        if all(r['validation']['passed'] for r in results.values()):
            left=results['compile-sdk26']['validation'];right=results['same-binary-xcode27']['validation']
            same=all(left[k]==right[k] for k in ('manifest','archive','unchangedBundleFiles','builtSDK'))
        passed=passed and same and transfer is not None
        result={'schemaVersion':1,'sourceCommit':self.config['sourceCommit'],'controllerCommit':self.config['controlCommit'],'runID':self.config['runID'],'runAttempt':self.config['runAttempt'],'jobIDs':self.config['jobIDs'],'runConclusion':run['conclusion'],'jobs':{k:{'id':j['id'],'conclusion':j['conclusion']} for k,j in jobs.items()},'appearanceDiagnosticAutomatedPassed':passed,'sameDiagnosticBundleBoundAcrossBothSystems':same,'sameBundleLocallyRehashed':False,'transferArtifactDownloaded':False,'transferArtifact':None if transfer is None else {'id':transfer['id'],'name':transfer['name'],'bytes':transfer['size_in_bytes'],'githubDigest':transfer['digest']},'evidence':results,'officialLogs':official,'visualReview':{'status':'pending','approved':False},'fullNativeMatrixApproved':False,'installationApproved':False,'completeApplicationApproved':False,'deliveryAllowed':False,'prior37VisualRejectionUnchanged':True,'snapshotDirectory':str(self.snapshot),'scope':'Seven-frame appearance-only minimal bundle built once with SDK26 and run on both systems. Authenticated workflow assertions/report binding; no app code or transport tar executed locally, no full product validation, no visual approval inferred.'}
        write(self.root/'collector-summary.json',encode(result),replace=True)
        print(json.dumps({'root':str(self.root),'runID':self.config['runID'],'runConclusion':run['conclusion'],'appearanceDiagnosticAutomatedPassed':passed,'sameDiagnosticBundleBoundAcrossBothSystems':same,'visualReviewApproved':False,'deliveryAllowed':False},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    sys.dont_write_bytecode=True
    Collector(configuration(args.config)).run()

if __name__=='__main__':main()
