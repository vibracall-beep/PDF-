#!/usr/bin/env python3
"""Offline preservation of current failed focal e0; no network or artifact execution."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib, importlib.util, json, os, re, stat, subprocess, sys
sys.dont_write_bytecode=True
SOURCE='e0b8d0cef2e66fe1a6d41db4fe9e04c5c50510b2'
RUN=40249767201
JOBS={'compile-sdk26':121338897259,'same-binary-xcode27':121340681527}
ROOT=Path('/workspace/.cache/pdf-appearance-e0b8d0c-40249767201')
DEST=Path('/tmp/pdf-appearance-e0b8d0c-evidence-staging')
WORK=Path(str(DEST)+'.building')
COLLECTOR=Path('/tmp/pdf_collect_appearance_environment.py')
COLLECTOR_SHA='d2337d77396bce0ac99aecd472ca046a1d2b9b9335ff08b88f7d5402830368f9'
EXPECTED_ARTIFACTS={'PDF-appearance-sdk26':(12619533926,2199208,'354c9793753e7310d3888eb394203b33d40499e61675f1f8d22388db5214bfe0'),'PDF-appearance-same-binary-xcode27':(12619879872,2206051,'d2cc00f348783ee3ca4b4769b162c0e439fe29c7b23804c2a7bfe600bbf831ea')}
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
need(load('/tmp/pdf-appearance-e0b8d0c-config.json')==config,'Final configuration differs from collection.')
need(summary['runConclusion']=='failure' and summary['deliveryAllowed'] is False and summary['appearanceDiagnosticAutomatedPassed'] is False,'Failure status must remain failed.')
api=load(ROOT/'collector-jobs-after.json')
for phase in ['before','after']:
    run=load(ROOT/f'collector-run-{phase}.json');jobs=load(ROOT/f'collector-jobs-{phase}.json')
    need(run['id']==RUN and run['head_sha']==SOURCE and run['run_attempt']==1 and run['event']=='workflow_dispatch' and run['path']=='.github/workflows/appearance-compatibility.yml' and run['status']=='completed' and run['conclusion']=='failure','Terminal API run identity mismatch.')
    need({j['name']:j['id'] for j in jobs['jobs']}==JOBS and all(j['head_sha']==SOURCE and j['run_id']==RUN and j['conclusion']=='failure' for j in jobs['jobs']),'API jobs differ.')
need(sha(read(COLLECTOR))==COLLECTOR_SHA,'Reviewed collector changed.')
collector=module('focale0_retention_collector',COLLECTOR)
git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1')
source_records=load(ROOT/'collector-source-files.json')
for record in source_records:
    p=ROOT/'exact-source'/record['role']/record['path'];raw=read(p)
    need(record['commit']==SOURCE and match(raw,record),'Exact-source receipt differs.')
    need(raw==subprocess.check_output(['git','show',SOURCE+':'+record['path']],cwd='/workspace/PDF-',env=git_env),'Exact Git source differs: '+record['path'])
archives=module('focale0_retention_archives',ROOT/'exact-source/controller/diagnostics/delivery_archives.py')
png_helper=module('focale0_retention_png',ROOT/'exact-source/controller/scripts/check_appearance_preview.py')
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
need(manifests[0]==manifests[1] and sha(manifests[0])=='727334f713191e0913e8a353cd714646b2679806604f7522304342bec0858514','Manifest identity differs.')
# Review identities and exact current fingerprints; older reports are never relabeled as current.
visual_path=Path('/tmp/pdf-appearance-e0-independent-review.json');visual=load(visual_path)
need(sha(read(visual_path))=='0dcfde36a8c34ebb6eaa330f18f6b221ab6ebf72aa821f906f20cf74365e33aa' and sha(read('/tmp/pdf-appearance-e0-independent-review.md'))=='a9dbe0585dbbdf6527aed06c735ca1bbe4b4c6b6adb19c1d6bb3233a7048ce9f','Frozen visual review changed.')
need(visual['source']==SOURCE and visual['runID']==RUN and visual['attempt']==1 and visual['humanVisualReview'] is False and visual['conclusion'].startswith('Global focal remains unapproved:'),'Visual review identity/conclusion differs.')
visual_count=0
for artifact in visual['artifacts']:
    need(sha(read(artifact['nativeJSON']))==artifact['nativeJSONSHA256'],'Visual source report differs.')
    for frame in artifact['frames']:
        need(match(read(frame['originalPNG']),frame) and frame['originalReviewedVisually'] and frame['reportHashMatchesOriginal'] and frame['reportBytesMatchOriginal'],'Reviewed current PNG differs.');visual_count+=1
need(visual_count==14,'Expected fourteen reviewed originals.')
factual_path=Path('/tmp/pdf-appearance-e0b8d0c-factual-log-review.json');factual=load(factual_path)
need(sha(read(factual_path))=='c07379b727a8c2b9dec296c9daa340ced24aabb955b51dfdaad8f94ca8a269be' and sha(read('/tmp/pdf-appearance-e0b8d0c-factual-log-review.md'))=='44b366bb22998adb24c5fda1b03cbb2232d6ccf52ef26c94d061f3a32d6ee506','Factual frozen review changed.')
need(factual['sourceCommit']==SOURCE and factual['runID']==RUN and factual['deliveryAllowed'] is False and factual['totalPNGsVerified']==14 and factual['nativeContrastMeasurements']==0,'Factual scope differs.')
# Frozen technical report paths/hashes are completed only after its author confirms freeze.
TECH_JSON=Path('/tmp/pdf-appearance-e0b8d0c-public-items-diagnosis.json')
TECH_MD=Path('/tmp/pdf-appearance-e0b8d0c-public-items-diagnosis.md')
TECH_JSON_SHA='a719917d041cb83f0a6d1f10f555372309ee25ecc102d20751f8c39cc011a1cb'
TECH_MD_SHA='341755ae5d2cc3d49856113a5bfed820e424436786f410c9b0cd54c215346ca7'
need(sha(read(TECH_JSON))==TECH_JSON_SHA and sha(read(TECH_MD))==TECH_MD_SHA,'Technical diagnosis not yet frozen/matching.')
technical=load(TECH_JSON)
need(technical['configuration']==config and technical['observedWorkspaceSnapshots']==24 and technical['nativeContrastApproved'] is False and technical['applicationApproved'] is False and technical['originalNativeGateResultsPreserved'] is True,'Technical diagnosis identity/scope differs.')
preflight=load('/tmp/pdf-appearance-environment-local-preflight.json');preflight_binding=[]
for path,digest in preflight['sourceFiles'].items():
    raw=read(ROOT/'exact-source/application'/path);need(sha(raw)==digest,'Preflight does not describe current source: '+path);preflight_binding.append({'gitPath':path,'bytes':len(raw),'sha256':digest})
need(preflight['swiftFilesParsed']==90 and preflight['syntaxFailures']==[] and preflight['sdkTypecheck'] is False and preflight['selectionGatesUnchanged'] is True,'Preflight claims differ.')
offline=load('/tmp/pdf-appearance-environment-collector-offline-tests.json')
need(offline['collectorSHA256']==COLLECTOR_SHA and offline['tests']==offline['passed']==18 and offline['networkCalls']==0 and not offline['collectorMainExecuted'] and not offline['artifactCodeExecuted'],'Offline collector results differ.')
need(sha(read('/tmp/test_pdf_collect_appearance_environment_offline.py'))==offline['suiteSHA256'] and sha(read('/tmp/pdf-appearance-environment-collector-offline-tests.log'))==offline['logSHA256'] and sha(read('/tmp/pdf-appearance-environment-collector.diff'))==offline['diffSHA256'],'Collector test/delta changed.')
preparation=load('/tmp/pdf-appearance-e0b8d0c-collector-preparation.json')
need(preparation['sourceCommit']==SOURCE and preparation['runID']==RUN and preparation['newSHA256']==COLLECTOR_SHA and preparation['offlineTests']['passed']==18,'Original collector preparation differs.')
for result in factual['jobs']:
    for frame in result['frames']:need(match(read(frame['original']['path']),frame['original']),'Factual current PNG fingerprint changed.')
    for log in result['originalLogs']:need(match(read(log['path']),log),'Factual current log changed.')
WORK.mkdir(mode=0o700);inventory=[]
def put(path,raw,kind,origin):
    rel=Path(path);need(not rel.is_absolute() and '..' not in rel.parts,'Unsafe staged path.');p=WORK/rel;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw)
    need(read(p)==raw,'Staged bytes changed.');inventory.append({'path':rel.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
for p in sorted(ROOT.rglob('*')):
    if p.is_dir():need(not p.is_symlink(),'Unexpected cache symlink directory.');continue
    if '__pycache__' in p.parts or p.suffix=='.pyc':continue
    rel=p.relative_to(ROOT);need(not p.name.endswith(('.tar','.tar.gz')) and not any(x.endswith('.app') for x in p.parts),'No tar/app in compact evidence.')
    if rel.parts[0] in {'downloads','extracted','official-attempt-logs'}:dest='originals/'+rel.as_posix();kind='original-authenticated-evidence'
    elif rel.parts[0]=='exact-source':dest=rel.as_posix();kind='exact-git-source'
    else:dest='provenance/'+rel.as_posix();kind='original-collector-record-or-api-snapshot'
    put(dest,read(p),kind,{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
put('provenance/local-preflight-binding.json',enc({'sourceCommit':SOURCE,'preflightParent':preflight['parentCommit'],'candidateFilesMatchExactCommit':True,'files':preflight_binding,'SDKTypecheck':False,'preparationWordingPreserved':True,'preparationAssertionsNotRuntimeApproval':True}),'derived-local-preflight-binding',{'sourceCommit':SOURCE})
for name in ['pdf-appearance-e0b8d0c-factual-log-review.json','pdf-appearance-e0b8d0c-factual-log-review.md','pdf-appearance-e0-independent-review.json','pdf-appearance-e0-independent-review.md',TECH_JSON.name,TECH_MD.name]:
    p=Path('/tmp')/name;put('reviews/'+name,read(p),'derived-factual-or-independent-review',{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
put('local-preflight/pdf-appearance-environment-local-preflight.json',read('/tmp/pdf-appearance-environment-local-preflight.json'),'derived-preparation-record',{'originalPath':'/tmp/pdf-appearance-environment-local-preflight.json','note':'Original preparation wording retained; source hashes match e0. Does not approve runtime or the complete application.'})
for name in ['pdf_collect_appearance_environment.py','test_pdf_collect_appearance_environment_offline.py','pdf-appearance-environment-collector.diff','pdf-appearance-environment-collector-offline-tests.json','pdf-appearance-environment-collector-offline-tests.log','pdf-appearance-e0b8d0c-collector-preparation.json','pdf-appearance-e0b8d0c-config.json','pdf-appearance-e0b8d0c-config.draft.json','pdf-appearance-e0b8d0c-collector.log','pdf_review_appearancee0_facts.py','pdf_review_e0_public_items.py','pdf_stage_appearancee0_evidence.py']:
    p=Path('/tmp')/name;put('collection-tools/'+name,read(p),'derived-collector-or-retention-tool-record',{'originalPath':str(p),'notProductOrArtifactCode':True})
retention={'schemaVersion':1,'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'runConclusion':'failure','jobs':JOBS,'sourceCompilePackPassed':True,'targetRestorePassed':True,'appearanceCapturePassed':False,'appearanceObserverPassed':False,'appearanceValidationPassed':False,'nativeContrastMeasurementsCompleted':0,'beforeAfterWorkspaceObservationsWithoutAXChildren':24,'checksPerSystem':{'passed':8,'failed':4},'originalPNGCount':14,'artifactInventories':{'PDF-appearance-sdk26':15,'PDF-appearance-same-binary-xcode27':14},'independentVisualInspectionCompleted':True,'visualFinding':'Equilibrado and Restaurar are visible in current SDK 26 customization frame, with light popup/ancestor appearance. This observed route corrects the prior captured defect, but no full interaction or universal approval follows.','fullNativeWorkflowApproved':False,'fullNativeWorkflowEvidenceRetained':False,'installationApproved':False,'completeApplicationApproved':False,'deliveryAllowed':False,'sameManifestBytesAcrossSystems':True,'overallApprovedSameBundleGateStillFalse':True,'transferArtifactDownloaded':False,'tarOrAppRetained':False,'collectorIncidentInThisRun':False,'eachArtifactDownloadedOnce':True,'collectorOfflineTestsPassed':18,'currentSourceFilesBoundToPreflight':4,'approvalTransferredFromPriorSource':False}
put('retention-summary.json',enc(retention),'derived-failed-focal-retention-summary',{'sourceCommit':SOURCE,'runID':RUN})
readme=f'''# Aparência e0b8d0c — focal reprovado; correção visual específica observada

Fonte/controlador `{SOURCE}`, run `{RUN}`, tentativa 1, jobs 26 `{JOBS['compile-sdk26']}` e27 `{JOBS['same-binary-xcode27']}`. **Build/pack SDK 26 e restore 27 passaram. Captura, observador e validação falharam nos dois sistemas: sete PNGs por sistema, zero medidas nativas de contraste.** A revisão dos 14 originais confirma Espaçamento/Equilibrado e Restaurar visíveis no percurso atual de Personalização 26, com providers/ancestrais claros. Isso corrige o defeito visual específico nesse percurso; o focal global e a entrega permanecem sem aprovação.

| Resultado | Evidência atual |
|---|---|
| Compilação/empacotamento SDK 26 e restore 27 |Etapas API success |
| Capturas originais |14 PNGs íntegros; inventários15/14 |
| Checks nativos por sistema |8 true,4 false; reportes/recibos failed |
| Observações de workspace |24 snapshots antes/depois com AXToolbar sem filhos;12 toolbarReports sem medidas |
| Personalização 26 atual |Equilibrado/Restaurar visíveis; popups e ancestrais light/Aqua |
| Matriz completa / instalação / entrega |Não aprovadas por este focal |

A nova hierarquia nativa e os itens públicos estão preservados nos JSON. Sua existência não sobrepõe os checks falhos de seleção/identidade/contraste. Uma imagem estática não valida cliques, animações, conteúdo fora da área visível, VoiceOver humano ou todas as rotas de personalização. A ausência antiga dos controles em 877 não foi apresentada como falha atual de e0. Nenhuma causa única da falha do observador foi inferida por esta retenção.

## Proveniência

- `originals/downloads/`: dois ZIPs de evidência autenticados pelo digest GitHub e o ZIP oficial de logs. Cada evidência foi baixada uma vez; não há ZIP de transporte do bundle.
- `originals/extracted/`:15/14 membros originais, incluindo14 PNGs, reportes e recibos failed, manifestos e logs. Nenhuma imagem foi editada.
- `originals/official-attempt-logs/`: dois agregados;31 membros completos por etapa/agregados estão no ZIP original. O endpoint autenticado de logs não fornece digest independente; o SHA registrado identifica os bytes recebidos.
- `provenance/`: APIs antes/depois, configuração/recibos e vínculo dos quatro hashes de preflight ao Git exato e0.
- `exact-source/`:13 seleções da fonte/controlador usadas no diagnóstico/validação; não é o código completo do aplicativo.
- `reviews/`: recontagem factual offline, revisão independente dos 14 originais e diagnóstico técnico; nenhuma aprova a entrega.
- `local-preflight/`: sintaxe de 90 Swift, sem typecheck do SDK, e hashes do candidato. A redação preparatória sobre correção ainda não provada é preservada; o resultado posterior do percurso capturado consta da revisão independente.
- `collection-tools/`: coletor environment congelado, delta (somente acrescenta PDFApp.swift e CustomizationView.swift à seleção Git),18 testes offline, preparação, configurações final/rascunho, log único da coleta e scripts desta retenção.

## Verificações e limites

Os dois digests de ZIP e todos os membros, os 14 fingerprints de frame e PNGs (CRC/raster), o ZIP oficial e os 13 arquivos de fonte foram reconferidos offline. As sete linhas de captura por sistema coincidem no artefato, etapa oficial e agregado. Os 21 testes do checker 26 foram recontados uma vez; os 18 testes locais verificam somente o coletor. Exit0 da coleta significa que as falhas foram preservadas corretamente, não que o aplicativo passou.

Os manifestos são byte idênticos: SHA `{sha(manifests[0])}`. Declaram tar de {results[0]['declaredArchive']['bytes']} bytes com SHA `{results[0]['declaredArchive']['sha256']}`. O vínculo é baseado em API, pack/restore e metadados; esse tar/app não foi baixado, extraído ou executado localmente. O gate geral de bundle aprovado continua falso devido aos reportes/recibos falhos. Bundle mínimo não é instalador completo.

`inventory.json` registra bytes/SHA/origem; `SHA256SUMS` cobre os arquivos e o índice. Confira com `sha256sum -c SHA256SUMS`. Não há TAR/app ou evidência antiga relabelada como atual. Esta retenção focal não contém/aprova matriz nativa completa, instalação final, M4 físico, energia/Neural Engine, IA real, serviços de produção, scanner, VoiceOver humano ou ausência universal de erros. Nenhuma aprovação de outra fonte foi transferida.
'''
put('README.md',readme.encode(),'derived-failed-focal-readme',{'sourceCommit':SOURCE,'runID':RUN})
index={'schemaVersion':1,'sourceCommit':SOURCE,'runID':RUN,'status':'failed-appearance-diagnostic-retention','deliveryAllowed':False,'scope':'Every retained file except inventory.json and SHA256SUMS; SHA256SUMS additionally covers inventory.json.','files':sorted(inventory,key=lambda row:row['path'])}
index_raw=enc(index);(WORK/'inventory.json').write_bytes(index_raw)
checks=sorted([(row['path'],row['sha256']) for row in inventory]+[('inventory.json',sha(index_raw))]);(WORK/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in checks))
for row in inventory:need(match(read(WORK/row['path']),row),'Retained hash mismatch.')
need({p.relative_to(WORK).as_posix() for p in WORK.rglob('*') if p.is_file()}=={row['path'] for row in inventory}|{'inventory.json','SHA256SUMS'},'Retained inventory not closed.')
for p,value in list(OBSERVED.items()):need(read(p)==value,'Original changed during retention.')
need(not list(WORK.rglob('*.tar.gz')) and not list(WORK.rglob('*.tar')) and not list(WORK.rglob('*.app')),'Unexpected transport tar/app retained.')
os.rename(WORK,DEST)
files=[p for p in DEST.rglob('*') if p.is_file()]
print(json.dumps({'stage':str(DEST),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(index_raw),'sourceCommit':SOURCE,'runID':RUN,'runConclusion':'failure','nativeContrastMeasurements':0,'observedCustomizationRouteCorrected':True,'deliveryAllowed':False},indent=2))
