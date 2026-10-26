#!/usr/bin/env python3
"""Offline retention/recount of failed focal877; no network or artifact execution."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib, importlib.util, json, os, re, stat, subprocess, sys
sys.dont_write_bytecode=True
SOURCE='8770950674f5e026dda5f3f9a0ae479e337f06d8'
RUN=40248300537
JOBS={'compile-sdk26':121334482597,'same-binary-xcode27':121336057194}
ROOT=Path('/workspace/.cache/pdf-appearance-8770950-40248300537')
DEST=Path('/tmp/pdf-appearance-8770950-evidence-staging')
WORK=Path(str(DEST)+'.building')
COLLECTOR=Path('/tmp/pdf_collect_appearance_observer.py')
COLLECTOR_SHA='d995f7c4ed2baffbba670b90fca2a43461c606b1afbeda3350dd92e7a8d79906'
EXPECTED_ARTIFACTS={'PDF-appearance-sdk26':(12620161367,2132011,'791772d41e9a2132c425f8f32f8413f2b655c352459761a4ce15f7f3365d8506'),'PDF-appearance-same-binary-xcode27':(12619707756,2141540,'1c37dd9fe421ae20b2eaca1115bf4bfeafa2985a46d0994e91bf6750608fa7d1')}
OBSERVED={}
def need(value,detail):
    if not value: raise ValueError(detail)
def read(path,cap=128*1024*1024):
    p=Path(path)
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        a=os.fstat(f.fileno());need(stat.S_ISREG(a.st_mode) and a.st_uid==os.getuid() and a.st_size<=cap,'Bounded regular original required: '+str(p))
        raw=f.read(cap+1);b=os.fstat(f.fileno())
        need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,len(raw),b.st_mtime_ns,b.st_ctime_ns),'File changed: '+str(p))
    if p in OBSERVED: need(OBSERVED[p]==raw,'Original changed between reads: '+str(p))
    OBSERVED[p]=raw
    return raw
def sha(raw): return hashlib.sha256(raw).hexdigest()
def load(p): return json.loads(read(p))
def enc(value): return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
def fp(p):
    raw=read(p);return {'path':str(p),'bytes':len(raw),'sha256':sha(raw)}
def match(raw,record): return len(raw)==record['bytes'] and sha(raw)==record['sha256']
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
need(not os.path.lexists(DEST) and not os.path.lexists(WORK),'Do not overwrite a retention.')
config=load(ROOT/'collector-configuration.json');state=load(ROOT/'collector-artifact-state.json');summary=load(ROOT/'collector-summary.json')
need(config['sourceCommit']==config['controlCommit']==SOURCE and config['runID']==RUN and config['runAttempt']==1 and config['jobIDs']==JOBS,'Identity mismatch.')
need(load('/tmp/pdf-appearance-8770950-config.json')==config,'Final configuration differs from collection.')
need(summary['runConclusion']=='failure' and summary['deliveryAllowed'] is False and summary['appearanceDiagnosticAutomatedPassed'] is False,'Failure status must remain failed.')
api=load(ROOT/'collector-jobs-after.json')
for phase in ['before','after']:
    run=load(ROOT/f'collector-run-{phase}.json');jobs=load(ROOT/f'collector-jobs-{phase}.json')
    need(run['id']==RUN and run['head_sha']==SOURCE and run['run_attempt']==1 and run['event']=='workflow_dispatch' and run['path']=='.github/workflows/appearance-compatibility.yml' and run['status']=='completed' and run['conclusion']=='failure','Terminal API run identity mismatch.')
    need({j['name']:j['id'] for j in jobs['jobs']}==JOBS and all(j['head_sha']==SOURCE and j['run_id']==RUN and j['conclusion']=='failure' for j in jobs['jobs']),'API jobs differ.')
need(sha(read(COLLECTOR))==COLLECTOR_SHA,'Reviewed collector changed.')
collector=module('focal877_retention_collector',COLLECTOR)
git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1')
source_records=load(ROOT/'collector-source-files.json')
for record in source_records:
    p=ROOT/'exact-source'/record['role']/record['path'];raw=read(p)
    need(record['commit']==SOURCE and match(raw,record),'Exact-source receipt differs.')
    need(raw==subprocess.check_output(['git','show',SOURCE+':'+record['path']],cwd='/workspace/PDF-',env=git_env),'Exact Git source differs: '+record['path'])
archives=module('focal877_retention_archives',ROOT/'exact-source/controller/diagnostics/delivery_archives.py')
png_helper=module('focal877_retention_png',ROOT/'exact-source/controller/scripts/check_appearance_preview.py')
need(len(state['attempts'])==2,'Expected two downloaded artifacts.')
for record in state['attempts'].values():
    identity=EXPECTED_ARTIFACTS[record['name']]
    need((record['artifactID'],record['archiveBytes'],record['archiveSHA256'])==identity,'Pinned artifact differs.')
    need(record['sourceCommit']==record['controllerCommit']==SOURCE and record['runID']==RUN and record['runAttempt']==1 and record['downloadAttempts']==1 and record['downloaded'] and record['inventoryComplete'],'Artifact origin/count/inventory differs.')
    raw=read(ROOT/'downloads'/f"{record['artifactID']}.zip")
    need(len(raw)==identity[1] and sha(raw)==identity[2]==record['githubDigest'].removeprefix('sha256:'),'Artifact ZIP digest differs.')
    job='compile-sdk26' if record['name']=='PDF-appearance-sdk26' else 'same-binary-xcode27'
    members=collector.unpack_small_zip(raw,{n:collector.cap_for(n) for n in collector.inventory_for(job)},archives)
    folder=ROOT/'extracted'/record['name']
    need(set(members)==set(record['files'])=={p.name for p in folder.iterdir()},'Exact artifact members differ.')
    for name,value in members.items():need(match(value,record['files'][name]) and value==read(folder/name),'ZIP/extracted bytes differ: '+name)
# Official original ZIP has its own local digest; the authenticated endpoint supplies no upstream digest.
official=load(ROOT/'collector-official-logs.json');logs_raw=read(official['path'])
need(official['endpoint']==f'/repos/vibracall-beep/PDF-/actions/runs/{RUN}/attempts/1/logs' and official['authenticatedAPIEndpoint'] and not official['upstreamDigestProvided'] and match(logs_raw,official),'Official log identity/digest differs.')
log_members=collector.unpack_small_zip(logs_raw,{n:32*1024*1024 for n in official['files']},archives,limit=128*1024*1024,flat=False)
need(set(log_members)==set(official['files']),'Official log inventory differs.')
for name,value in log_members.items(): need(match(value,official['files'][name]),'Official log member differs: '+name)
for record in official['aggregates']:
    need(read(ROOT/'official-attempt-logs'/record['name'])==log_members[record['name']] and match(log_members[record['name']],record),'Official aggregate differs.')
# Recount outputs from both per-step originals and their official aggregate, without interpreting echoed shell as tests.
capture_regex=r'PDF preview captured from WindowServer via ScreenCaptureKit: ([^;]+); window=(\d+); content=([^;]+); pixels=([^;\n]+)'
failed_ids={'same-real-window','three-controls-central-contrast-every-workspace-frame','attached-toolbar-identities-preserved','toolbar-controls-return-after-customization'}
results=[];manifests=[]
for jobname,artifact in [('compile-sdk26','PDF-appearance-sdk26'),('same-binary-xcode27','PDF-appearance-same-binary-xcode27')]:
    folder=ROOT/'extracted'/artifact;job=next(j for j in api['jobs'] if j['name']==jobname)
    report=load(folder/'PDF-appearance.appearance.json');receipt=load(folder/'appearance-validation.json');manifest=load(folder/'appearance-bundle.json');manifests.append(read(folder/'appearance-bundle.json'))
    need(report['status']=='failed' and len(report['frames'])==7 and receipt['status']=='failed' and receipt['sourceCommit']==SOURCE,'Native failure/frames/receipt differ.')
    need({c['id'] for c in report['checks'] if not c['passed']}==failed_ids and sum(c['passed'] is True for c in report['checks'])==8,'Native checks differ.')
    need(manifest['sourceCommit']==SOURCE and manifest['scope']=='minimal-appearance-diagnostic-only' and len(manifest['files'])==4,'Manifest scope/identity differs.')
    frames=[];observations=[];errors=Counter()
    for frame in report['frames']:
        p=folder/frame['png'];raw=read(p);dim=png_helper.png_dimensions(raw)
        need(match(raw,frame) and dim==(frame['width'],frame['height']),'PNG raster/fingerprint/dimensions differ.')
        toolbar=frame.get('toolbarReport');snapshot=frame['windowSnapshot']
        if toolbar:
            need(toolbar['measurements']==[],'Unexpected native measurement; review assumptions need update.')
            errors.update(toolbar['errors'])
            for timing in ['before','after']:
                ob=toolbar[timing];providers=ob['toolbarProviders'];need(len(providers)==1 and providers[0]['directChildCount']==0 and providers[0]['node']['role']=='AXToolbar' and ob['controls']==[],'Toolbar observation differs.')
                observations.append({'phase':frame['phase'],'timing':timing,'windowNumber':ob['windowNumber'],'providerClass':providers[0]['node']['nativeClass'],'role':'AXToolbar','directChildCount':0,'controlsDetected':0})
        frames.append({'phase':frame['phase'],'selection':frame['selection'],'original':fp(p),'dimensions':list(dim),'PNGCRCAndRasterParsed':True,'nativeFrameFingerprintMatched':True,'windowNumber':snapshot['windowNumber'],'workspaceToolbarProviderCount':snapshot['workspaceToolbarProviderCount'],'controlsDetected':len(snapshot['controls']),'measurementCount':0 if toolbar is None else len(toolbar['measurements']),'nativePopupProviderCount':snapshot['nativePopupProviderCount']})
    need(len(observations)==12,'Expected six before/after workspace observations.')
    capture=read(folder/'capture.log').decode();captures=re.findall(capture_regex,capture)
    need(len(captures)==7 and {row[0] for row in captures}=={f['png'] for f in report['frames']},'Capture lines differ.')
    aggregate_name=next(x['name'] for x in official['aggregates'] if x['name'].endswith('_'+jobname+'.txt'))
    aggregate=log_members[aggregate_name].decode()
    step_name=next(n for n in log_members if n.startswith(jobname+'/') and '_Capture ' in n)
    need(Counter(captures)==Counter(re.findall(capture_regex,aggregate))==Counter(re.findall(capture_regex,log_members[step_name].decode())),'Capture output counters differ across official aggregate/step/artifact.')
    validation=read(folder/'validation.log').decode();error_line=validation.strip().splitlines()[-1]
    need(error_line.startswith('ValueError: Appearance diagnostic:') and error_line in aggregate,'Expected validation failure absent from official log.')
    origin=read(folder/'origin.log').decode();need(f'source_commit={SOURCE}' in origin and f'control_commit={SOURCE}' in origin and f'run_id={RUN}' in origin and 'run_attempt=1' in origin,'Origin log identity differs.')
    python_suites=[{'tests':int(a),'seconds':float(b),'status':'OK'} for a,b in re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*\n\s*OK\s*$',origin,re.M)]
    need(([s['tests'] for s in python_suites]==[21]) if jobname=='compile-sdk26' else not python_suites,'Control test recount differs.')
    for suite in python_suites:
        need(len(re.findall(r'Ran '+str(suite['tests'])+r' tests in '+re.escape(str(suite['seconds']))+'s',aggregate))==1,'Official control-test count differs.')
    steps={s['name']:s['conclusion'] for s in job['steps']}
    required=['Compile the native arm64 executable once','Build and fingerprint the diagnostic-only bundle'] if jobname=='compile-sdk26' else ['Verify every byte and safely restore without rebuilding or resigning']
    need(all(steps[n]=='success' for n in required),'Build/pack/restore required step failed.')
    need(sum(v=='failure' for v in steps.values())==2 and all(v=='failure' for k,v in steps.items() if k.startswith(('Capture ','Validate '))),'Capture/validation stage failures differ.')
    results.append({'job':jobname,'jobID':job['id'],'conclusion':job['conclusion'],'operatingSystem':report['operatingSystem'],'steps':[{'number':s['number'],'name':s['name'],'conclusion':s['conclusion']} for s in job['steps']],'nativeReport':fp(folder/'PDF-appearance.appearance.json'),'nativeStatus':report['status'],'passedChecks':8,'failedChecks':sorted(failed_ids),'measurementRowsTotal':0,'frames':frames,'toolbarObservations':observations,'toolbarErrorCounts':dict(errors),'originalCaptureLines':[{'png':a,'windowNumber':int(b),'points':c,'pixels':d} for a,b,c,d in captures],'officialCaptureCounterMatchesArtifactLog':True,'validationLastError':error_line,'originPythonSuites':python_suites,'manifest':fp(folder/'appearance-bundle.json'),'builtSDK':manifest['builtSDK'],'declaredArchive':manifest['tar'],'failedReceipt':receipt,'originalLogs':[fp(p) for p in sorted(folder.glob('*.log'))],'officialAggregate':fp(ROOT/'official-attempt-logs'/aggregate_name)})
need(manifests[0]==manifests[1] and sha(manifests[0])=='06e2b831c2fb37d8b2b32c2887d0b729f59eb9e8862b692062bbd4971e3f1816','Manifest identity differs.')
visual_path=Path('/tmp/pdf-appearance-877-independent-review.json');visual=load(visual_path)
need(visual['source']==SOURCE and visual['runID']==RUN and visual['attempt']==1 and visual['humanVisualReview'] is False and visual['conclusion'].startswith('Not approved:'),'Independent review identity/conclusion differs.')
visual_count=0
for artifact in visual['artifacts']:
    need(sha(read(artifact['nativeJSON']))==artifact['nativeJSONSHA256'],'Review report hash differs.')
    for f in artifact['frames']:
        need(match(read(f['originalPNG']),f) and f['originalReviewedVisually'] and f['reportHashMatchesOriginal'] and f['reportBytesMatchOriginal'],'Visual review original differs.');visual_count+=1
need(visual_count==14,'Expected 14 independently reviewed originals.')
diag=load('/tmp/pdf-appearance-8770950-observer-diagnosis.json')
need(diag['configuration']==config and diag['nativeContrastApproved'] is False and diag['applicationApproved'] is False,'Observer diagnosis differs.')
need(sha(read('/tmp/pdf-appearance-8770950-observer-diagnosis.json'))=='d7d5454851803996b188f041b8dfd96b85e14b2e8aa2fe7a872b917dcd7cea3c' and sha(read('/tmp/pdf-appearance-8770950-observer-diagnosis.md'))=='903447321b5117cf354ce2d261cc8a71a1aa2fd657a4cfa2d5661bd572495d4b','Frozen diagnosis hash differs.')
preflight=load('/tmp/pdf-appearance-observer-local-preflight.json');preflight_binding=[]
for path,digest in preflight['sourceFiles'].items():
    raw=read(ROOT/'exact-source/application'/path);need(sha(raw)==digest,'Preflight source not current877: '+path);preflight_binding.append({'gitPath':path,'sha256':digest,'bytes':len(raw)})
need(preflight['swiftSyntax']=={'files':90,'errors':0,'SDKTypecheck':False} and preflight['appearanceContractTests']==21 and not preflight['newNativeRunPassed'],'Local preflight claims differ.')
offline=load('/tmp/pdf-appearance-observer-collector-offline-tests.json')
need(offline['collectorSHA256']==COLLECTOR_SHA and offline['tests']==offline['passed']==18 and offline['networkCalls']==0 and not offline['collectorMainExecuted'] and not offline['artifactCodeExecuted'],'Offline collector result differs.')
need(re.search(r'Ran 18 tests in [\d.]+s\s+OK\s*$',read('/tmp/pdf-appearance-observer-collector-offline-tests.log').decode()) is not None,'Offline18 log differs.')
need(re.search(r'Ran 21 tests in [\d.]+s\s+OK\s*$',read('/tmp/pdf-appearance-observer-controls.log').decode()) is not None,'Local21 checker log differs.')
# Derived factual report. No prior run report or incident is used as current evidence.
factual={'schemaVersion':1,'reviewedAtUTC':datetime.now(timezone.utc).isoformat(),'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'status':'failed-appearance-only-diagnostic','networkCallsDuringReview':0,'artifactCodeExecuted':False,'productModified':False,'gatesModified':False,'applicationFailureCauseEstablished':False,'deliveryAllowed':False,'jobs':results,'totalPNGsVerified':14,'nativeContrastMeasurements':0,'beforeAfterWorkspaceObservations':24,'manifestBytesIdenticalAcrossSystems':True,'transportTarLocallyDownloadedOrExecuted':False,'sameBundleGateRemainsFailed':summary['sameDiagnosticBundleBoundAcrossBothSystems'] is False,'officialLogZIP':official,'exactSourceRecords':source_records,'independentVisualReview':fp(visual_path),'observerDiagnosis':fp('/tmp/pdf-appearance-8770950-observer-diagnosis.json'),'currentCollectionIncidentObserved':False,'eachEvidenceArtifactDownloadedOnce':True,'localPreflightBinding':preflight_binding,'limits':['PNG integrity/CRC/raster is not visual or accessibility approval.','No native contrast measurement exists; static screenshots do not approve clicks, animations, VoiceOver or hidden/scrolling content.','The precise cause or duration of the SDK26 popup appearance mismatch is not established.','The full native workflow for877 was not executed, per coordinator; it cannot be inferred from this focal.','Bundle manifest/pack/restore evidence was retained without downloading, extracting or executing the transport tar or app locally.','The local preflight contains a historical2f whitespace-log reference, which is preserved verbatim as a reference only; that old log is not retained as current877 evidence.']}
factual_base=Path('/tmp/pdf-appearance-8770950-factual-log-review')
need(not factual_base.with_suffix('.json').exists() and not factual_base.with_suffix('.md').exists(),'Do not overwrite factual review.')
factual_base.with_suffix('.json').write_bytes(enc(factual))
md=f'''# Revisão factual 8770950 — focal reprovado

Fonte/controlador `{SOURCE}`, run `{RUN}`, tentativa1. **Build/pack do SDK26 e restore do mesmo bundle no27 passaram; captura e validação falharam em ambos.** Esta revisão apenas releu originais autenticados, sem rede, executar artefatos ou modificar produto/gates. Não estabeleceu causa da falha.

| Job | Sistema | PNGs íntegros | Checks true/false | Medidas nativas |
|---|---|---:|---:|---:|
'''
for result in results:md+=f"| {result['job']} · {result['jobID']} | {result['operatingSystem']} |7|8/4|0|\n"
md+='''
Os14 PNG coincidem com nome, tamanho, SHA e dimensões dos frames; o parser do Git exato conferiu CRC/raster. As sete linhas de captura de cada artefato coincidem com as linhas do log oficial por etapa e do agregado, sem duplicar contagens. O job26 contém uma suíte de21 testes do checker com OK; o job27 não repetiu essa suíte. São controles do diagnóstico, não a matriz nativa completa.

Os24 snapshots antes/depois dos12 estados de workspace encontram um NSToolbarView/AXToolbar, com zero filhos diretos e nenhuma seleção dos três controles. Todos os12 toolbarReports têm measurements vazio. Os quatro checks reprovados são same-real-window, three-controls-central-contrast-every-workspace-frame, attached-toolbar-identities-preserved e toolbar-controls-return-after-customization. Não se concluiu uma medida de contraste; IDs numéricos de janela não substituem esses checks falhos.

A revisão visual independente de scope_audit abriu os14 originais. Ela registra12 estados de workspace visualmente legíveis, mas reprova Personalização26: Espaçamento/Equilibrado e Restaurar estão ausentes. A revisão técnica registra cinco NSPopUpButton DarkAqua em contexto Aqua; somente os dois controles com bounds visíveis são comparados à região branca do PNG. Nenhuma causa única ou duração do defeito foi inferida. A inspeção estática não aprova interação, animação ou VoiceOver.

'''
md+=f"Os manifestos de bundle são byte idênticos: `{sha(manifests[0])}`. Declaram tar de{results[0]['declaredArchive']['bytes']} bytes, SHA `{results[0]['declaredArchive']['sha256']}`. O coletor não baixou/extraiu/executou esse tar/app. O gate geral de vínculo aprovado continua falso porque os reportes/recibos falharam.\n\n"
md+='''Cada ZIP de evidência foi baixado uma vez; seus digests GitHub e todos os membros foram reconferidos offline. O ZIP oficial de logs e seus membros foram reconferidos pelos hashes registrados; esse endpoint autenticado não oferece digest externo independente. Não houve incidente de coleta neste run. O diff/testes18 do coletor registram a única alteração de retenção de fonte, acrescentando AccessibilityAudit.swift.

O preflight local tem hashes dos quatro arquivos que correspondem ao Git877: sintaxe de90 Swift sem typecheck do SDK e21 controles locais. Sua referência histórica ao log de whitespace2f permanece literal, não é evidência do run877. A matriz nativa completa877 não foi executada. Instalação, produto completo, M4 físico, serviços reais e entrega não foram aprovados. Nenhuma aprovação anterior foi transferida.
'''
factual_base.with_suffix('.md').write_text(md)
# Preserve current originals and derived reports in a new, closed staging directory.
WORK.mkdir(mode=0o700);inventory=[]
def put(path,raw,kind,origin):
    rel=Path(path);need(not rel.is_absolute() and '..' not in rel.parts,'Unsafe staged path.');p=WORK/rel;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw)
    need(read(p)==raw,'Staged bytes changed.');inventory.append({'path':rel.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
for p in sorted(ROOT.rglob('*')):
    if p.is_dir():need(not p.is_symlink(),'Unexpected symlink directory.');continue
    if '__pycache__' in p.parts or p.suffix=='.pyc':continue
    rel=p.relative_to(ROOT);need(not p.name.endswith(('.tar','.tar.gz')) and not any(x.endswith('.app') for x in p.parts),'No transport tar/app allowed.')
    if rel.parts[0] in {'downloads','extracted','official-attempt-logs'}:dest='originals/'+rel.as_posix();kind='original-authenticated-evidence'
    elif rel.parts[0]=='exact-source':dest=rel.as_posix();kind='exact-git-source'
    else:dest='provenance/'+rel.as_posix();kind='original-collector-record-or-api-snapshot'
    put(dest,read(p),kind,{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
put('provenance/local-preflight-binding.json',enc({'sourceCommit':SOURCE,'preflightParent':preflight['parentCommit'],'sourceFilesMatch877':True,'files':preflight_binding,'SDKTypecheck':False,'historicalReferenceNotCurrentEvidence':preflight['rawLogWhitespaceRecord'],'preflightAssertionsNotNewRuntimeApproval':True}),'derived-preflight-source-binding',{'sourceCommit':SOURCE})
for name in ['pdf-appearance-8770950-factual-log-review.json','pdf-appearance-8770950-factual-log-review.md','pdf-appearance-877-independent-review.json','pdf-appearance-877-independent-review.md','pdf-appearance-8770950-observer-diagnosis.json','pdf-appearance-8770950-observer-diagnosis.md']:
    p=Path('/tmp')/name;put('reviews/'+name,read(p),'derived-factual-or-independent-review',{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
for name in ['pdf-appearance-observer-local-preflight.json','pdf-appearance-observer-controls.log','pdf-appearance-observer-access-scope.md']:
    p=Path('/tmp')/name;put('local-preflight/'+name,read(p),'derived-preparation-record',{'originalPath':str(p),'note':'Original temporal wording and historical parent references preserved; not runtime or full-product approval.'})
for name in ['pdf_collect_appearance_observer.py','pdf_collect_appearance_observer.README.md','pdf-appearance-observer-collector.diff','test_pdf_collect_appearance_observer_offline.py','pdf-appearance-observer-collector-offline-tests.json','pdf-appearance-observer-collector-offline-tests.log','pdf-appearance-8770950-config.json','pdf-appearance-8770950-config.draft.json','pdf-appearance-8770950-collector.log','pdf_stage_appearance877_evidence.py']:
    p=Path('/tmp')/name;put('collection-tools/'+name,read(p),'derived-collector-or-retention-tool-record',{'originalPath':str(p),'notProductOrArtifactCode':True})
retention={'schemaVersion':1,'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'runConclusion':'failure','jobs':JOBS,'sourceCompilePackPassed':True,'targetRestorePassed':True,'appearanceCapturePassed':False,'appearanceObserverPassed':False,'appearanceValidationPassed':False,'visualReviewPassed':False,'nativeContrastMeasurementsCompleted':0,'beforeAfterWorkspaceObservationsWithoutAXChildren':24,'checksPerSystem':{'passed':8,'failed':4},'originalPNGCount':14,'artifactInventories':{'PDF-appearance-sdk26':15,'PDF-appearance-same-binary-xcode27':14},'visualFinding':'SDK26 customization: Equilibrado/Restaurar are absent; five native popup providers report DarkAqua in Aqua, with two visible-control PNG rectangles white. Cause/duration unproven.','fullNativeWorkflowExecuted':False,'fullNativeWorkflowStatusSource':'Coordinator instruction; this retention is exclusively the focal workflow.','installationApproved':False,'completeApplicationApproved':False,'deliveryAllowed':False,'sameManifestBytesAcrossSystems':True,'overallApprovedSameBundleGateStillFalse':True,'transferArtifactDownloaded':False,'tarOrAppRetained':False,'collectorIncidentInThisRun':False,'eachArtifactDownloadedOnce':True,'collectorOfflineTestsPassed':18,'currentSourceFilesBoundToPreflight':4,'localPreflightHistoricalReferenceRelabeledAsCurrent':False,'approvalTransferredFromPriorSource':False}
put('retention-summary.json',enc(retention),'derived-failed-focal-retention-summary',{'sourceCommit':SOURCE,'runID':RUN})
readme=f'''# Aparência8770950 — focal e revisão visual reprovados

Fonte/controlador `{SOURCE}`, run `{RUN}`, tentativa1, jobs26 `{JOBS['compile-sdk26']}` e27 `{JOBS['same-binary-xcode27']}`. **Compilar/empacotar no SDK26 e restaurar o mesmo bundle no27 passaram. Captura, observador e validação falharam nos dois sistemas. Foram produzidos sete PNGs por sistema, porém zero medidas nativas de contraste. A revisão visual focal também reprovou Personalização26. A matriz nativa completa877 não foi executada.** Nada aqui aprova instalação, aplicativo completo ou entrega.

| Resultado | Evidência atual |
|---|---|
| Compilação/empacotamento SDK26 e restore27 | Etapas API concluídas com success |
| Capturas originais |14 PNGs íntegros, sete de cada sistema; inventários15/14 |
| Checks nativos por sistema |8 true,4 false; reportes e recibos failed |
| Observações de workspace |24 snapshots antes/depois com AXToolbar e zero filhos;12 toolbarReports sem medidas |
| Personalização26 |Espaçamento/Equilibrado e Restaurar invisíveis; providers DarkAqua dentro de Aqua, sem causa inferida |
| Matriz completa877 / instalação / entrega |Não executada / não aprovada / não autorizada por estas evidências |

A revisão independente abriu todos14 originais. Os12 estados de workspace examinados parecem legíveis, mas isso não substitui as medições ausentes nem aprova o fluxo completo. Os controles ausentes em Personalização26 constituem um achado visual separado da falha do observador. Cinco NSPopUpButton reais reportam tema escuro em contexto claro; só os dois bounds visíveis foram relacionados à região branca do PNG. Capturas estáticas não aprovam cliques, animações, conteúdo que exige rolagem, VoiceOver humano ou acessibilidade completa.

## Proveniência

- `originals/downloads/`: os dois ZIPs de evidência com digest GitHub e o ZIP oficial de logs. Cada evidência foi baixada uma vez. O transporte tar/app não foi baixado ou retido localmente.
- `originals/extracted/`:15/14 membros originais, incluindo PNGs, reportes de falha, manifestos e logs. Nenhuma imagem foi editada.
- `originals/official-attempt-logs/`: dois agregados; logs por etapa estão no ZIP original. O endpoint oficial autenticado não fornece digest independente; o SHA registrado identifica os bytes recebidos.
- `provenance/`: snapshots API antes/depois, configuração/recibos do coletor e vínculo dos quatro hashes de preflight ao Git exato877.
- `exact-source/`:11 seleções de fonte exata usadas pelo controle e diagnóstico; não é o aplicativo completo.
- `reviews/`: revisão factual offline, revisão visual independente dos14 PNG e diagnóstico técnico do observador. Todos preservam a reprovação.
- `local-preflight/`: registro de sintaxe90 Swift sem typecheck SDK, controles21 e escopo preparatório. A referência histórica ao log de whitespace2f é preservada como referência; não incluímos esse log antigo como evidência atual.
- `collection-tools/`: coletor observer congelado, diff,18 testes offline, configurações final/rascunho, log desta coleta e script desta retenção. A única diferença do coletor revisado é reter AccessibilityAudit.swift do Git exato. O histórico de sua base não é um incidente deste run.

## Verificações e limites

Os digests de ambos os ZIPs, todos os membros, os14 fingerprints de frame e PNGs (CRC/raster), o ZIP/logs oficiais e os11 arquivos de fonte foram reconferidos offline. As sete linhas de captura por sistema coincidem entre log de artefato, etapa oficial e agregado; os21 testes do checker26 foram recontados uma vez. A retenção não executou binários, alterou produto/gates ou fez nova coleta.

Os manifestos são byte idênticos: SHA `{sha(manifests[0])}`. Declaram tar de{results[0]['declaredArchive']['bytes']} bytes com SHA `{results[0]['declaredArchive']['sha256']}`. O vínculo é baseado em APIs, pack/restore e metadados, sem rehash local desse tar. O gate geral de bundle aprovado permanece falso devido aos reportes/recibos reprovados. Bundle mínimo não é instalador completo.

`inventory.json` registra bytes/SHA/origem; `SHA256SUMS` cobre todos os arquivos do índice e o próprio índice. Confira com `sha256sum -c SHA256SUMS`. Não há TAR, app ou ZIP de transporte nesta retenção compacta. Resultados anteriores não foram transferidos: nenhuma aprovação37/2f ou de outro candidato torna877 aprovado. Permanecem fora do escopo M4 físico, energia/Neural Engine, IA real, serviços de produção, scanner, VoiceOver humano e promessa de ausência universal de erros.
'''
put('README.md',readme.encode(),'derived-failed-focal-readme',{'sourceCommit':SOURCE,'runID':RUN})
index={'schemaVersion':1,'sourceCommit':SOURCE,'runID':RUN,'status':'failed-appearance-diagnostic-retention','deliveryAllowed':False,'scope':'Every retained file except inventory.json and SHA256SUMS; SHA256SUMS additionally covers inventory.json.','files':sorted(inventory,key=lambda r:r['path'])}
index_raw=enc(index);(WORK/'inventory.json').write_bytes(index_raw)
checks=sorted([(r['path'],r['sha256']) for r in inventory]+[('inventory.json',sha(index_raw))]);(WORK/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in checks))
for row in inventory:need(match(read(WORK/row['path']),row),'Final retained hash mismatch.')
need({p.relative_to(WORK).as_posix() for p in WORK.rglob('*') if p.is_file()}=={r['path'] for r in inventory}|{'inventory.json','SHA256SUMS'},'Retained inventory not closed.')
for p,value in list(OBSERVED.items()):need(read(p)==value,'Original changed during retention.')
need(not list(WORK.rglob('*.tar.gz')) and not list(WORK.rglob('*.tar')) and not list(WORK.rglob('*.app')),'Unexpected app/tar retained.')
os.rename(WORK,DEST)
files=[p for p in DEST.rglob('*') if p.is_file()]
print(json.dumps({'stage':str(DEST),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(index_raw),'sourceCommit':SOURCE,'runID':RUN,'runConclusion':'failure','nativeContrastMeasurements':0,'visualReviewPassed':False,'deliveryAllowed':False},indent=2))
