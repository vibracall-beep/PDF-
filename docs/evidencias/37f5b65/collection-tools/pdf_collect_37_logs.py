#!/usr/bin/env python3
"""Retain a terminal attempt's authenticated full logs; never execute artifact code."""
from pathlib import Path
from collections import Counter
import hashlib, importlib.util, json, os, re, resource, stat, struct, subprocess, sys, time, zipfile
ROOT=Path('/workspace/.cache/pdf-native-37f5b65')
REPO=Path('/workspace/PDF-')
RUN=40239018570
SHA='37f5b65e35a9f70c716cfcd64db7ba69837f5c21'
JOBS={'macos-26':121306620661,'xcode-27':121306620477}
API='/repos/vibracall-beep/PDF-'
MAX_ZIP=64*1024**2
MAX_MEMBER=32*1024**2
MAX_TOTAL=128*1024**2
ATTEMPT=1
sys.dont_write_bytecode=True

def require(ok,detail):
    if not ok: raise ValueError(detail)

def read_regular(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as s:
        before=os.fstat(s.fileno());require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and 0<before.st_size<=limit,'Bounded owned regular file required: '+path.name)
        raw=s.read(limit+1);after=os.fstat(s.fileno())
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,len(raw),after.st_mtime_ns,after.st_ctime_ns),'File changed: '+path.name)
        return raw

def folder(path):
    path.mkdir(mode=0o700,exist_ok=True);metadata=path.lstat()
    require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid==os.getuid() and not metadata.st_mode&0o077,'Private owned directory required: '+path.name)

def write(path,raw):
    if os.path.lexists(path):
        require(read_regular(path,max(len(raw),1))==raw,'Existing evidence differs: '+path.name);return
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())

def encode(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

def fetch(endpoint,path):
    completed=subprocess.run(['gh','api',API+endpoint],capture_output=True,timeout=45)
    if completed.returncode:
        raise RuntimeError(json.dumps({'endpoint':endpoint,'exit':completed.returncode,'http':re.findall(r'HTTP (\d+)',completed.stderr.decode(errors='replace'))}))
    require(0<len(completed.stdout)<=4*1024**2,'Metadata exceeds limit.')
    write(path,completed.stdout)
    return json.loads(completed.stdout)

def identity(run,jobs):
    require(run['id']==RUN and run['head_sha']==SHA and run['head_commit']['id']==SHA and run['run_attempt']==ATTEMPT and run['status']=='completed' and run['conclusion'] is not None and run['repository']['id']==1431437116 and run['head_repository']['id']==1431437116 and run['path']=='.github/workflows/macos.yml','Run identity or terminal status differs.')
    require(jobs['total_count']==2 and len(jobs['jobs'])==2,'Unexpected jobs inventory.')
    result={}
    for runner,ident in JOBS.items():
        found=[j for j in jobs['jobs'] if j['id']==ident];require(len(found)==1,'Expected job absent.')
        job=found[0]
        require(job['run_id']==RUN and job['run_attempt']==ATTEMPT and job['head_sha']==SHA and job['name']==f'native-application ({runner})' and runner in job['labels'] and job['status']=='completed' and job['conclusion'] is not None,'Job identity or terminal status differs.')
        result[runner]=job
    return result

# Read the shared collector snapshot first. No API or ZIP fetch while it is active.
folder(ROOT)
config=json.loads(read_regular(ROOT/'collector-configuration.json',16384))
require(config['sourceCommit']==SHA and config['nativeRunID']==RUN and config['runAttempt']==ATTEMPT and config['jobIDs']==JOBS,'Collector binding differs.')
snapshot=json.loads(read_regular(ROOT/'collector-run.json',4*1024**2))
require(snapshot['id']==RUN and snapshot['head_sha']==SHA,'Snapshot identity differs.')
if snapshot['status']!='completed':
    print(json.dumps({'state':'not_terminal','runID':RUN,'noLogsDownloaded':True}));sys.exit(2)

# Execute the ZIP validator only after comparing it to the exact local Git blob.
validator_source=subprocess.check_output(['git','show',SHA+':diagnostics/delivery_archives.py'],cwd=REPO,env=dict(os.environ,GIT_NO_LAZY_FETCH='1'))
validator_path=ROOT/'validator-source/delivery_archives.py'
require(read_regular(validator_path,256*1024)==validator_source,'Pinned Git validator differs.')
spec=importlib.util.spec_from_file_location('pinned_37_delivery_archives',validator_path);validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
folder(ROOT/'snapshots');snap=ROOT/'snapshots'/('full-logs-'+str(time.time_ns()));folder(snap)
run_before=fetch(f'/actions/runs/{RUN}',snap/'run-before.json')
jobs_before=fetch(f'/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100',snap/'jobs-before.json')
by_runner=identity(run_before,jobs_before)
archive=ROOT/'collector-attempt-1-logs.zip'
if not os.path.lexists(archive):
    partial=archive.with_name(archive.name+'.partial-'+str(os.getpid()))
    fd=os.open(partial,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        def bound():resource.setrlimit(resource.RLIMIT_FSIZE,(MAX_ZIP,MAX_ZIP))
        with os.fdopen(fd,'wb') as out:
            completed=subprocess.run(['gh','api',API+f'/actions/runs/{RUN}/attempts/{ATTEMPT}/logs'],stdout=out,stderr=subprocess.PIPE,timeout=60,preexec_fn=bound)
            out.flush();os.fsync(out.fileno())
        if completed.returncode:
            raise RuntimeError(json.dumps({'downloadExit':completed.returncode,'http':re.findall(r'HTTP (\d+)',completed.stderr.decode(errors='replace'))}))
        require(0<partial.stat().st_size<=MAX_ZIP,'Log archive exceeds download bound.')
        os.link(partial,archive,follow_symlinks=False)
    finally:
        if os.path.lexists(partial):partial.unlink()
raw_archive=read_regular(archive,MAX_ZIP)
run_after=fetch(f'/actions/runs/{RUN}',snap/'run-after.json')
jobs_after=fetch(f'/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100',snap/'jobs-after.json')
after=identity(run_after,jobs_after)
require(run_before['conclusion']==run_after['conclusion'] and {r:j['conclusion'] for r,j in by_runner.items()}=={r:j['conclusion'] for r,j in after.items()},'Terminal conclusions changed during retrieval.')
size=len(raw_archive);archive_sha=hashlib.sha256(raw_archive).hexdigest()
destination=ROOT/'collector-attempt-1-logs';folder(destination)
entries=[];selected={};all_text={}
with archive.open('rb') as stream:
    length=min(size,65557);stream.seek(size-length);tail=stream.read(length);offset=tail.rfind(b'PK\x05\x06')
    require(offset>=0 and offset+22<=len(tail),'Missing ZIP end record.')
    record=struct.unpack('<4s4H2IH',tail[offset:offset+22]);count=record[4]
    require(0<count<=128,'Unexpected full log archive entry count.')
    validator._zip_directory(stream,size,count)
    with zipfile.ZipFile(stream) as z:
        names=set();expanded=0
        for item in z.infolist():
            name=item.orig_filename;normalized=validator._name(name)
            require(name==item.filename and normalized not in names,'Ambiguous member.');names.add(normalized)
            aggregate=re.fullmatch(r'[01]_native-application \((macos-26|xcode-27)\)\.txt',name)
            step=re.fullmatch(r'native-application \((macos-26|xcode-27)\)/(?:system|\d+_[^/]+)\.txt',name)
            require(aggregate or step,'Unexpected archive member name.')
            require(stat.S_IFMT(item.external_attr>>16) in (0,stat.S_IFREG) and not item.is_dir() and not item.external_attr&0x10 and not item.flag_bits&(1|0x40|0x2000) and item.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and 0<=item.file_size<=MAX_MEMBER,'Unsafe archive member.')
            expanded+=item.file_size;require(expanded<=MAX_TOTAL,'Expanded archive exceeds bound.')
            if aggregate:
                require(aggregate[1] not in selected,'Duplicate aggregate.');selected[aggregate[1]]=name
        require(set(selected)==set(JOBS),'Both aggregate job logs required.')
        for item in z.infolist():
            blocks=[];digest=hashlib.sha256();n=0
            with z.open(item) as source:
                while block:=source.read(1024*1024):
                    n+=len(block);require(n<=item.file_size,'ZIP member exceeds declaration.');blocks.append(block);digest.update(block)
            require(n==item.file_size,'Truncated member.')
            data=b''.join(blocks);entries.append({'name':item.filename,'bytes':n,'sha256':digest.hexdigest()});all_text[item.filename]=data.decode('utf-8')
            if item.filename in selected.values():write(destination/item.filename,data)

ansi=re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
def clean(line):return ansi.sub('',line)
def body(line):return re.sub(r'^\d{4}-\d\d-\d\dT\S+\s+','',clean(line))
def python_suites(text,step_name=None):
    lines=text.splitlines();found=[]
    for i,line in enumerate(lines):
        match=re.search(r'Ran (\d+) tests? in ([\d.]+)s',clean(line))
        if not match:continue
        # A later suite's OK must never override this suite's FAILED. Inspect
        # exact result lines only, stop before the next Ran, and reject ambiguity.
        terminals=[]
        for following in lines[i+1:i+6]:
            value=body(following)
            if re.fullmatch(r'Ran \d+ tests? in [\d.]+s',value):break
            result=re.fullmatch(r'(OK|FAILED)(?: \(([^)]*)\))?',value)
            if result:terminals.append(result)
        status='unrecognized';counts={}
        if len(terminals)==1:
            result=terminals[0];details=result[2]
            pairs=[] if details is None else [re.fullmatch(r'(failures|errors|skipped|expected failures|unexpected successes)=(\d+)',piece.strip()) for piece in details.split(',')]
            if all(pairs) and len({x[1] for x in pairs})==len(pairs):
                counts={x[1]:int(x[2]) for x in pairs}
                status='passed' if result[1]=='OK' else 'failed'
        count=int(match[1]);skipped=counts.get('skipped',0);failed=counts.get('failures',0);errors=counts.get('errors',0)
        expected_failures=counts.get('expected failures',0);unexpected_successes=counts.get('unexpected successes',0)
        if status=='passed' and (failed or errors or unexpected_successes):status='unrecognized'
        deductions=skipped+failed+errors+expected_failures+unexpected_successes
        if deductions>count:status='unrecognized'
        found.append({'cases':count,'passed':count-deductions if status!='unrecognized' else None,'skipped':skipped,'failures':failed,'errors':errors,'expectedFailures':expected_failures,'unexpectedSuccesses':unexpected_successes,'status':status,'seconds':float(match[2]),'line':i+1})
    if step_name=='Verify installer integrity':labels=['installer/scripts']
    elif step_name=='Build, install and validate complete application':labels=['core/tests','integration']
    else:labels=[]
    for i,item in enumerate(found):item['label']=labels[i] if i<len(labels) else 'unclassified'
    return found

native_source=subprocess.check_output(['git','show',SHA+':Sources/PDF/MacSmokeTests.swift'],cwd=REPO,text=True)
expected_names=set(re.findall(r'\b(?:audit|auditAsync)\("([^\"]+)"',native_source))
require(len(expected_names)==44,'Native group inventory changed unexpectedly.')
expected_repeats={'Build, install and validate complete application':2,'Validate installed application and local OCR':1,'Validate portable app without host dependencies or network':1,'Package and verify binary install and update':5}
reviews=[]
for runner in JOBS:
    name=selected[runner];text=all_text[name];lines=text.splitlines();plain=[clean(x) for x in lines]
    require(SHA in text,'Checkout SHA absent in complete log.')
    starts=Counter(re.findall(r'Native check starting: ([^\r\n]+)',text));passes=Counter(re.findall(r'Native check passed: ([^\r\n]+)',text))
    native_failures=re.findall(r'Native check failed: ([^\r\n]+)',text)
    issues=[];by_step=[];step_suites=[];step_starts=Counter();step_passes=Counter()
    for member,step_text in all_text.items():
        match=re.fullmatch(r'native-application \('+re.escape(runner)+r'\)/(\d+)_(.+)\.txt',member)
        if not match:continue
        title=match[2];suite=python_suites(step_text,title)
        for item in suite:step_suites.append({**item,'step':title,'stepLog':member})
        a=Counter(re.findall(r'Native check starting: ([^\r\n]+)',step_text));b=Counter(re.findall(r'Native check passed: ([^\r\n]+)',step_text))
        step_starts.update(a);step_passes.update(b)
        if a or b or title in expected_repeats:
            expected=expected_repeats.get(title)
            complete=a==b and set(b)==expected_names and len(set(b.values()))==1
            by_step.append({'step':title,'stepLog':member,'starts':sum(a.values()),'passes':sum(b.values()),'distinctGroups':len(b),'startPassMultisetEqual':a==b,'repeatCounts':sorted(set(b.values())),'completeNativeExecutions':next(iter(b.values())) if complete else None,'expectedExecutions':expected})
    aggregates=python_suites(text)
    fingerprint=lambda items:Counter((x['cases'],x['passed'],x['skipped'],x['status'],x['seconds']) for x in items)
    require(fingerprint(step_suites)==fingerprint(aggregates),'Aggregate and per-step Python summaries differ.')
    for item in step_suites:
        if item['status']!='passed':issues.append('Python suite did not pass: '+item['label'])
    if starts!=passes:issues.append('Native starts/passes differ by multiset.')
    if step_starts!=starts or step_passes!=passes:issues.append('Native per-step counter sums differ from aggregate logs.')
    if native_failures:issues.append('Native failure marker present.')
    if run_after['conclusion']=='success':
        if by_runner[runner]['conclusion']!='success' or any(step['conclusion']!='success' for step in by_runner[runner]['steps']):issues.append('Successful run has a non-success native job or step.')
        if Counter(step['step'] for step in by_step)!=Counter({title:1 for title in expected_repeats}):issues.append('Successful run lacks exactly the four expected native step logs.')
        if set(passes)!=expected_names or set(passes.values())!={9}:issues.append('Successful run lacks all 44 native groups repeated exactly nine times.')
        if len(step_suites)!=3 or {x['label'] for x in step_suites}!={'installer/scripts','core/tests','integration'}:issues.append('Unexpected successful Python suite inventory.')
        for step in by_step:
            if step['completeNativeExecutions']!=step['expectedExecutions']:issues.append('Native repeat distribution differs in '+step['step'])
    py_count=sum(x['cases'] for x in step_suites);py_passed=sum(x['passed'] or 0 for x in step_suites);py_skipped=sum(x['skipped'] for x in step_suites)
    skipped=[{'line':i+1,'text':body(x)} for i,x in enumerate(lines) if re.search(r'\.{3} skipped [\'\"]',clean(x))]
    fatal=[{'line':i+1,'text':body(x)[:1200]} for i,x in enumerate(lines) if any(t in clean(x) for t in ['##[error]','Native check failed:','subprocess.TimeoutExpired:','RuntimeError: soffice'])]
    if fatal:issues.append('Explicit fatal/step error markers require review.')
    structure=[{'line':i+1,'text':body(x)} for i,x in enumerate(lines) if 'PDF structure audit:' in x and 'FAILED' in x]
    baseline=[x for x in structure if 'raw PDFKit' in x['text'] and 'diagnostic only, not the product output' in x['text']]
    product_failures=[x for x in structure if x not in baseline]
    if product_failures:issues.append('Non-baseline PDF structure failures present.')
    cg=[]
    for i,line in enumerate(lines):
        if 'CoreGraphics PDF has logged an error' not in line:continue
        before='\n'.join(lines[max(0,i-5):i]);after_context='\n'.join(lines[i+1:i+7])
        classified='invalid stream-length control: correctly rejected' in before and 'production normalization of recoverable stream length: passed' in after_context
        cg.append({'line':i+1,'invalidStreamNegativeControlThenSuccessfulNormalization':classified})
        if not classified:issues.append('CoreGraphics warning outside classified negative-control context.')
    compiler=[]
    for i,line in enumerate(lines):
        value=body(line)
        if re.search(r'[^ /]+\.swift:\d+:\d+: warning:',value):compiler.append({'line':i+1,'text':value})
    other_warnings=Counter(body(x) for x in lines if 'warning:' in clean(x).lower() and not re.search(r'[^ /]+\.swift:\d+:\d+: warning:',body(x)))
    help_probes=[i+1 for i,x in enumerate(lines) if 'appintentsmetadataprocessor[' in x and 'error: Unable to parse options' in x]
    log_path=destination/name;raw=log_path.read_bytes()
    reviews.append({'runner':runner,'jobID':JOBS[runner],'jobConclusion':by_runner[runner]['conclusion'],'fullLog':{'file':name,'path':str(log_path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'python':step_suites,'pythonCasesIncludingSkips':py_count,'pythonPassed':py_passed,'pythonSkipped':py_skipped,'skipRecords':skipped,'native':{'distinctNamesInSource':len(expected_names),'starts':sum(starts.values()),'passes':sum(passes.values()),'startPassMultisetEqual':starts==passes,'perStepCountersMatchAggregate':step_starts==starts and step_passes==passes,'distinctStarted':len(starts),'distinctPassed':len(passes),'repeatCounts':sorted(set(passes.values())),'expectedNineExecutionsObserved':set(passes)==expected_names and set(passes.values())=={9} and starts==passes,'startCounts':dict(sorted(starts.items())),'passCounts':dict(sorted(passes.items())),'nativeSmokeTestPassedCount':text.count('PDF native smoke tests passed'),'byStep':by_step,'failureMarkers':native_failures},'rawPDFKitBaselineDiagnostics':baseline,'productionStructureFailures':product_failures,'coreGraphicsWarnings':cg,'compilerWarnings':compiler,'otherWarningCounts':dict(other_warnings),'toolchainHelpProbeErrorLines':help_probes,'explicitFailureMarkers':fatal,'stepResults':[{'number':s['number'],'name':s['name'],'conclusion':s['conclusion']} for s in by_runner[runner]['steps']],'credentialLikePatternsObserved':bool(re.search(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}',text)),'signedURLPatternsObserved':bool(re.search(r'X-Amz-Signature=|[?&]sig=[A-Za-z0-9%+/]{20,}',text)),'reviewIssues':issues})

summary={'schemaVersion':1,'runID':RUN,'sourceSHA':SHA,'attempt':ATTEMPT,'sourceConclusion':run_after['conclusion'],'reviewScope':'Complete original attempt logs and authenticated terminal metadata; separate binary artifacts, cross-OS test and private delivery are not approved by this report.','officialEndpoint':API+f'/actions/runs/{RUN}/attempts/{ATTEMPT}/logs','archive':{'path':str(archive),'bytes':size,'sha256':archive_sha,'upstreamDigestSupplied':False,'allMembersCRCVerified':True,'memberCount':len(entries),'expandedBytes':sum(x['bytes'] for x in entries),'limits':{'archive':MAX_ZIP,'member':MAX_MEMBER,'totalExpanded':MAX_TOTAL,'members':128}},'metadataSnapshot':str(snap),'validator':{'sourceCommit':SHA,'gitPath':'diagnostics/delivery_archives.py','sha256':hashlib.sha256(validator_source).hexdigest(),'loadedFromGitVerifiedSourceNotArtifact':True},'zipMembers':entries,'jobs':reviews,'evidenceIsCompleteTerminalAttempt':True,'crossOSApprovedByThisReview':False,'privateDeliveryApprovedByThisReview':False}
write(ROOT/'collector-counts-complete-logs.json',encode(summary))
write(Path('/tmp/pdf-native-37f5b65-full-log-review.json'),encode(summary))
rows=[]
for job in reviews:
    n=job['native'];suites='; '.join(f"{s['label']}: {s['cases']} métodos, {s['passed']} PASS, {s['skipped']} skips ({s['seconds']} s)" for s in job['python'])
    rows.append(f"| {job['runner']} · {job['jobID']} | {job['jobConclusion']} | {suites} | {n['starts']} inícios / {n['passes']} aprovações; {n['distinctPassed']} nomes; repetições {n['repeatCounts']}; multiconjuntos iguais: {n['startPassMultisetEqual']} |")
parts=[f'# Logs oficiais completos — 37f5b65\n\nExecução **{RUN}**, tentativa 1, fonte **{SHA}**, conclusão da API **{run_after["conclusion"]}**. A identidade e o estado terminal dos dois jobs foram conferidos antes e depois do download autenticado.\n\nZIP original: **{size:,} bytes**, SHA-256 **`{archive_sha}`**. O endpoint não fornece digest independente: o SHA identifica os bytes recebidos. CRC, tipos, nomes e limites dos {len(entries)} membros foram conferidos, totalizando {sum(x["bytes"] for x in entries):,} bytes expandidos. Somente os dois logs agregados foram extraídos; os logs por etapa permanecem no ZIP.\n\n| Sistema / job | API | Python | Grupos nativos |\n|---|---|---|---|\n'+'\n'.join(rows)+'\n']
for job in reviews:
    n=job['native'];parts.append(f"\n## {job['runner']}\n\nPython: {job['pythonCasesIncludingSkips']} métodos, {job['pythonPassed']} aprovados e {job['pythonSkipped']} skips. Grupos nativos são nomes distintos, não novas funções a cada repetição.\n")
    for s in n['byStep']:parts.append(f"- {s['step']}: {s['starts']} inícios/{s['passes']} aprovações; {s['completeNativeExecutions']} execuções completas observadas, {s['expectedExecutions']} esperadas.\n")
    parts.append(f"\nDiagnósticos PDFKit bruto com `FAILED`: **{len(job['rawPDFKitBaselineDiagnostics'])}**, classificados somente quando marcados como referência diagnóstica, sem saída de produto. Falhas estruturais de produto: **{len(job['productionStructureFailures'])}**. Avisos CoreGraphics: **{len(job['coreGraphicsWarnings'])}**; contexto de controle negativo e normalização conferido individualmente no JSON.\n")
    parts.append(f"\nAvisos de compilação com posição de fonte: **{len(job['compilerWarnings'])} ocorrências**; detalhes e repetições permanecem no JSON/log. Probes de ajuda App Intents que recusaram opções: **{len(job['toolchainHelpProbeErrorLines'])}**; isso é separado da verificação posterior dos metadados. Marcadores explícitos de erro fatal/etapa: **{len(job['explicitFailureMarkers'])}**.\n")
    for skip in job['skipRecords']:parts.append(f"\nSkip, linha {skip['line']}: `{skip['text']}`\n")
    parts.append('\nQuestões da revisão: '+('; '.join(job['reviewIssues']) if job['reviewIssues'] else 'nenhuma divergência identificada nos critérios automatizados desta revisão')+'.\n')
parts.append('\nEsta leitura não aprova o mesmo tar no outro macOS, retenção privada, M4 físico, Neural Engine/energia, VoiceOver humano, modelo de IA disponível ou serviços externos. Esses itens exigem evidência própria. Não houve execução de código extraído dos artefatos.\n')
write(Path('/tmp/pdf-native-37f5b65-full-log-review.md'),''.join(parts).encode())
print(json.dumps({'runID':RUN,'conclusion':run_after['conclusion'],'archiveBytes':size,'archiveSHA256':archive_sha,'members':len(entries),'jobs':[{'runner':j['runner'],'python':j['pythonCasesIncludingSkips'],'pythonPassed':j['pythonPassed'],'pythonSkipped':j['pythonSkipped'],'nativeStarts':j['native']['starts'],'nativePasses':j['native']['passes'],'groups':j['native']['distinctPassed'],'repeats':j['native']['repeatCounts'],'issues':j['reviewIssues']} for j in reviews]},ensure_ascii=False))
