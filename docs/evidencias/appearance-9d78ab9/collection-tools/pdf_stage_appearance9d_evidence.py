#!/usr/bin/env python3
"""Offline retention of successful appearance-only focal9d, without delivery approval; no network or artifact execution."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib, importlib.util, json, os, re, stat, subprocess, sys
sys.dont_write_bytecode=True
SOURCE='9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb'
RUN=40252786964
JOBS={'compile-sdk26':121348103194,'same-binary-xcode27':121349491713}
ROOT=Path('/workspace/.cache/pdf-appearance-9d78ab9-40252786964')
DEST=Path('/tmp/pdf-appearance-9d78ab9-evidence-staging')
WORK=Path(str(DEST)+'.building')
COLLECTOR=Path('/tmp/pdf_collect_appearance_recovery_paths.py')
COLLECTOR_SHA='83430bd79e67203b15378ec9489090d479e0671791b6306d9d9014c74aad3480'
EXPECTED_ARTIFACTS={'PDF-appearance-sdk26':(12621670299,2209437,'a7cd264bfe5630a2b8dfae108f0666311fb7b19770afad40ca0652103b0cfc8c'),'PDF-appearance-same-binary-xcode27':(12621521510,2215442,'790c34da0f3844edf77618d7f810e46e50b55c64a709332c24adc764fdb1ec6c')}
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
need(load('/tmp/pdf-appearance-9d78ab9-config.json')==config,'Final configuration differs from collection.')
need(summary['runConclusion']=='success' and summary['deliveryAllowed'] is False and summary['appearanceDiagnosticAutomatedPassed'] is True,'Focal status must match the successful original without approving delivery.')
api=load(ROOT/'collector-jobs-after.json')
for phase in ['before','after']:
    run=load(ROOT/f'collector-run-{phase}.json');jobs=load(ROOT/f'collector-jobs-{phase}.json')
    need(run['id']==RUN and run['head_sha']==SOURCE and run['run_attempt']==1 and run['event']=='workflow_dispatch' and run['path']=='.github/workflows/appearance-compatibility.yml' and run['status']=='completed' and run['conclusion']=='success','Terminal API run identity mismatch.')
    need({j['name']:j['id'] for j in jobs['jobs']}==JOBS and all(j['head_sha']==SOURCE and j['run_id']==RUN and j['conclusion']=='success' for j in jobs['jobs']),'API jobs differ.')
need(sha(read(COLLECTOR))==COLLECTOR_SHA,'Reviewed collector changed.')
collector=module('focal9d_retention_collector',COLLECTOR)
git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1')
source_records=load(ROOT/'collector-source-files.json')
for record in source_records:
    p=ROOT/'exact-source'/record['role']/record['path'];raw=read(p)
    need(record['commit']==SOURCE and match(raw,record),'Exact-source receipt differs.')
    need(raw==subprocess.check_output(['git','show',SOURCE+':'+record['path']],cwd='/workspace/PDF-',env=git_env),'Exact Git source differs: '+record['path'])
archives=module('focal9d_retention_archives',ROOT/'exact-source/controller/diagnostics/delivery_archives.py')
png_helper=module('focal9d_retention_png',ROOT/'exact-source/controller/scripts/check_appearance_preview.py')
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
need(summary['sameDiagnosticBundleBoundAcrossBothSystems'] is True and summary['fullNativeMatrixApproved'] is False and summary['installationApproved'] is False and summary['completeApplicationApproved'] is False,'Collector scope differs.')
capture_regex=r'PDF preview captured from WindowServer via ScreenCaptureKit: ([^;]+); window=(\d+); content=([^;]+); pixels=([^;\n]+)'
results=[];manifests=[];all_measurements=[]
for jobname,artifact in [('compile-sdk26','PDF-appearance-sdk26'),('same-binary-xcode27','PDF-appearance-same-binary-xcode27')]:
    folder=ROOT/'extracted'/artifact;job=next(j for j in api['jobs'] if j['name']==jobname)
    # Exact Git checker replays pixel measurements, control identity/geometry and native report gates.
    report,originals=png_helper.validate_report(folder)
    receipt=load(folder/'appearance-validation.json');manifest=png_helper.manifest_at(folder/'appearance-bundle.json',SOURCE);manifests.append(read(folder/'appearance-bundle.json'))
    need(report['status']=='passed' and len(report['frames'])==7 and len(report['checks'])==12 and all(c['passed'] is True for c in report['checks']),'Native focal checks differ.')
    need(receipt['status']=='passed' and receipt['sourceCommit']==SOURCE and receipt['originals']==originals and receipt['unchangedBundleFiles']==manifest['files'] and receipt['archive']==manifest['tar'] and receipt['nativeChecksPassed']==12,'Receipt binding differs.')
    need(all(receipt[k] is False for k in ['completeApplicationApproved','engineRuntimeInstalled','humanVisualReview','universalWCAGCertification']),'Receipt overclaims scope.')
    frames=[];observations=[];measurements=[]
    for frame in report['frames']:
        raw=read(folder/frame['png']);dim=png_helper.png_dimensions(raw);need(match(raw,frame) and dim==(frame['width'],frame['height']),'PNG/frame differs.')
        toolbar=frame.get('toolbarReport');snapshot=frame['windowSnapshot']
        if toolbar:
            need(toolbar['passed'] is True and len(toolbar['measurements'])==3,'Expected three passing measures per workspace frame.')
            for row in toolbar['measurements']:
                need(row['passed'] is True and row['minimumContrast']==3 and row['centralContrast']>=3,'Native contrast measure failed.')
                measurements.append({'phase':frame['phase'],**row})
            for timing in ['before','after']:
                snap=toolbar[timing];need(len(snap['controls'])==3 and len({c['identity'] for c in snap['controls']})==3 and snap['errors']==[],'Real control selection differs.')
                observations.append({'phase':frame['phase'],'timing':timing,'windowNumber':snap['windowNumber'],'controls':snap['controls'],'workspaceToolbarProviderCount':snap['workspaceToolbarProviderCount']})
        frames.append({'phase':frame['phase'],'selection':frame['selection'],'original':fp(folder/frame['png']),'dimensions':list(dim),'PNGCRCAndRasterParsed':True,'nativeFrameFingerprintMatched':True,'windowNumber':snapshot['windowNumber'],'selectedControls':len(snapshot['controls']),'measurementCount':len(toolbar['measurements']) if toolbar else 0,'nativePopupProviderCount':snapshot['nativePopupProviderCount']})
    need(len(measurements)==18 and len(observations)==12,'Workspace measurement/snapshot count differs.')
    all_measurements+=measurements
    capture=read(folder/'capture.log').decode();captures=re.findall(capture_regex,capture)
    need(len(captures)==7 and {v[0] for v in captures}=={f['png'] for f in report['frames']},'Capture names/count differ.')
    aggregate_name=next(x['name'] for x in official['aggregates'] if x['name'].endswith('_'+jobname+'.txt'));aggregate=log_members[aggregate_name].decode()
    step_name=next(n for n in log_members if n.startswith(jobname+'/') and '_Capture ' in n)
    need(Counter(captures)==Counter(re.findall(capture_regex,aggregate))==Counter(re.findall(capture_regex,log_members[step_name].decode())),'Capture counters differ among originals.')
    validation=read(folder/'validation.log').decode();last=validation.strip().splitlines()[-1]
    need(json.loads(last)==receipt and last in aggregate,'Printed validation receipt differs from official log.')
    origin=read(folder/'origin.log').decode();need(f'source_commit={SOURCE}' in origin and f'control_commit={SOURCE}' in origin and f'run_id={RUN}' in origin and 'run_attempt=1' in origin,'Origin identity differs.')
    suites=[{'tests':int(a),'seconds':float(b),'status':'OK'} for a,b in re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*\n\s*OK\s*$',origin,re.M)]
    need(([v['tests'] for v in suites]==[28]) if jobname=='compile-sdk26' else not suites,'Checker test count differs.')
    for suite in suites:need(len(re.findall(r'Ran '+str(suite['tests'])+r' tests in '+re.escape(str(suite['seconds']))+'s',aggregate))==1,'Official checker count differs.')
    need(all(s['conclusion']=='success' for s in job['steps']),'API step is not success.')
    custom=next(f['windowSnapshot'] for f in report['frames'] if f['phase']=='customization')
    results.append({'job':jobname,'jobID':job['id'],'conclusion':job['conclusion'],'operatingSystem':report['operatingSystem'],'steps':[{'number':s['number'],'name':s['name'],'conclusion':s['conclusion']} for s in job['steps']],'nativeReport':fp(folder/'PDF-appearance.appearance.json'),'nativeStatus':'passed','passedChecks':12,'failedChecks':[],'exactSourceCheckerReplayedOffline':True,'measurementRowsTotal':18,'measurementMinimum':min(v['centralContrast'] for v in measurements),'measurementMaximum':max(v['centralContrast'] for v in measurements),'measurements':measurements,'workspaceObservations':observations,'frames':frames,'originalCaptureLines':[{'png':a,'windowNumber':int(b),'points':c,'pixels':d} for a,b,c,d in captures],'officialCaptureCounterMatchesArtifactLog':True,'originPythonSuites':suites,'manifest':fp(folder/'appearance-bundle.json'),'builtSDK':manifest['builtSDK'],'declaredArchive':manifest['tar'],'passedReceipt':receipt,'receiptScope':'minimal-appearance-diagnostic-only','originalLogs':[fp(p) for p in sorted(folder.glob('*.log'))],'officialAggregate':fp(ROOT/'official-attempt-logs'/aggregate_name),'captureTimeoutMarkerFound':bool(re.search(r'TimeoutExpired|timed out|timeout exceeded',capture,re.I)),'customizationAppearance':{'application':custom['applicationEffectiveAppearance'],'window':custom['windowEffectiveAppearance'],'content':custom['contentEffectiveAppearance'],'nativePopups':[{'title':v['title'],'effectiveStyle':v['effectiveStyle'],'effectiveAppearance':v['effectiveAppearance']} for v in custom['nativePopupControls']]}})
need(manifests[0]==manifests[1] and sha(manifests[0])=='2181b246f600178bc486a1de950fa9b06e33e6420a15f32e3f8f29f783350b09','Manifests differ.')
need(len(all_measurements)==36 and len(source_records)==16,'Focal totals/source selections differ.')
FACT_JSON=Path('/tmp/pdf-appearance-9d78ab9-factual-log-review.json');FACT_MD=Path('/tmp/pdf-appearance-9d78ab9-factual-log-review.md')
need(sha(read(FACT_JSON))=='e891c5f1fe1b3663c8fcba1f56ec93d4533b34b516aebd0baf1ffb96fcdc4c11' and sha(read(FACT_MD))=='8b9a239cdc02a1f68ad05cdba53c7a4d0a58691f9c11cdbec7223816be5cc0b1','Frozen factual review changed.')
factual=load(FACT_JSON);need(factual['sourceCommit']==SOURCE and factual['runID']==RUN and factual['nativeCentralContrastMeasurements']==36 and factual['deliveryAllowed'] is False,'Factual identity/scope differs.')
VISUAL_JSON=Path('/tmp/pdf-appearance-9d-independent-review.json');VISUAL_MD=Path('/tmp/pdf-appearance-9d-independent-review.md')
VISUAL_JSON_SHA='c7bb591a733173f09e72d7eef5a931163055d6a8a60d1068a5239266a31f87b0';VISUAL_MD_SHA='afa82d37e79a1c4aad9519e08dcfd41e89b9bd7db42f705394a479bfd16a9f2d'
need(sha(read(VISUAL_JSON))==VISUAL_JSON_SHA and sha(read(VISUAL_MD))==VISUAL_MD_SHA,'Frozen visual review required.')
visual=load(VISUAL_JSON)
need(visual['configuration']==config and visual['originalPNGsReviewed']==14 and visual['nativeWorkspaceSnapshotsVerified']==24 and visual['nativeToolbarMeasurements']==36 and visual['assistantVisualReviewCompleted'] is True and visual['focalVisualApproval'] is True and visual['confirmedVisualBlockers']==[],'Visual focal scope differs.')
need(all(visual[key] is False for key in ['humanInteractiveReview','installedApplicationApproved','packageDeliveryApproved','documentRecoveryValidated','completeToolCatalogValidated','physicalM4PerformanceValidated','universalWCAGCertification','animationsValidated']),'Visual report overclaims scope.')
reviewed_count=0
for artifact in visual['artifacts']:
    directory=ROOT/'extracted'/artifact['artifact']
    for name,record in artifact['sourceFiles'].items():need(match(read(directory/name),record),'Visual report original JSON/log changed.')
    for frame in artifact['frames']:
        need(Path(frame['path'])==directory/frame['file'] and frame['openedIndividuallyWithViewImageOriginal'] and match(read(frame['path']),frame),'Visual reviewed PNG changed.');reviewed_count+=1
need(reviewed_count==14,'Expected14 visually reviewed originals.')
PREFLIGHT_NAMES=['pdf-appearance-itemview-local-preflight.json','pdf-public-toolbar-recovery-preflight.json']
bindings=[];extra_sources={}
for name in PREFLIGHT_NAMES:
    preflight=load(Path('/tmp')/name);bound=[]
    need(preflight['sdkTypecheck'] is False and preflight['swiftFilesParsed']==90 and preflight['syntaxFailures']==[],'Preflight scope differs.')
    for path,digest in preflight['sourceFiles'].items():
        raw=subprocess.check_output(['git','show',SOURCE+':'+path],cwd='/workspace/PDF-',env=git_env);need(sha(raw)==digest,'Preflight source differs from9d: '+path)
        bound.append({'gitPath':path,'bytes':len(raw),'sha256':digest})
        if not (ROOT/'exact-source/application'/path).exists():extra_sources[path]=raw
    bindings.append({'preflight':name,'parentCommit':preflight['parentCommit'],'sourceCommit':SOURCE,'candidateHashesMatchExactCommit':True,'files':bound,'nativePendingWordingPreservedAsPreparation':True})
    if 'pythonScripts' in preflight:
        rec=preflight['pythonScripts'];need(sha(read(rec['log']))==rec['logSHA256'],'Original preflight test log differs.')
offline=load('/tmp/pdf-appearance-recovery-paths-collector-offline-tests.json')
need(offline['collectorSHA256']==COLLECTOR_SHA and offline['tests']==offline['passed']==18 and offline['networkCalls']==0 and offline['collectorMainExecuted'] is False,'Collector offline preparation differs.')
for path,key in [('/tmp/test_pdf_collect_appearance_recovery_paths_offline.py','suiteSHA256'),('/tmp/pdf-appearance-recovery-paths-collector-offline-tests.log','logSHA256'),('/tmp/pdf-appearance-recovery-paths-collector.diff','diffSHA256')]:need(sha(read(path))==offline[key],'Offline collector file changed.')
WORK.mkdir(mode=0o700);inventory=[]
def put(path,raw,kind,origin):
    rel=Path(path);need(not rel.is_absolute() and '..' not in rel.parts,'Unsafe staged path.');p=WORK/rel;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw)
    need(read(p)==raw,'Staged bytes changed.');inventory.append({'path':rel.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
for p in sorted(ROOT.rglob('*')):
    if p.is_dir():need(not p.is_symlink(),'Unexpected cache symlink directory.');continue
    if '__pycache__' in p.parts or p.suffix=='.pyc':continue
    rel=p.relative_to(ROOT);need(not p.name.endswith(('.tar','.tar.gz')) and not any(x.endswith('.app') for x in p.parts),'No transport tar/app in compact evidence.')
    if rel.parts[0] in {'downloads','extracted','official-attempt-logs'}:dest='originals/'+rel.as_posix();kind='original-authenticated-evidence'
    elif rel.parts[0]=='exact-source':dest=rel.as_posix();kind='exact-git-source'
    else:dest='provenance/'+rel.as_posix();kind='original-collector-record-or-api-snapshot'
    put(dest,read(p),kind,{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
for path,raw in extra_sources.items():put('exact-source/preflight-candidate/'+path,raw,'exact-git-preflight-source',{'sourceCommit':SOURCE,'gitPath':path,'note':'Additional preflight-selected source; not artifact code executed.'})
put('provenance/local-preflight-bindings.json',enc({'sourceCommit':SOURCE,'bindings':bindings,'SDKTypecheck':False,'recoveryPathsExercisedByAppearanceFocal':False}),'derived-preflight-bindings',{'sourceCommit':SOURCE})
for p in [FACT_JSON,FACT_MD,VISUAL_JSON,VISUAL_MD]:put('reviews/'+p.name,read(p),'derived-factual-or-independent-review',{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
for name in PREFLIGHT_NAMES+['pdf-public-toolbar-recovery-script-tests.log']:
    p=Path('/tmp')/name;put('local-preflight/'+name,read(p),'derived-preparation-record',{'originalPath':str(p),'note':'Original preparation wording retained; hashes bound to9d; not runtime recovery approval.'})
for name in ['pdf_collect_appearance_recovery_paths.py','pdf_collect_appearance_recovery_paths.README.md','test_pdf_collect_appearance_recovery_paths_offline.py','pdf-appearance-recovery-paths-collector.diff','pdf-appearance-recovery-paths-collector-offline-tests.json','pdf-appearance-recovery-paths-collector-offline-tests.log','pdf-appearance-recovery-paths-config.draft.json','pdf-appearance-9d78ab9-collector-preparation.json','pdf-appearance-9d78ab9-config.draft.json','pdf-appearance-9d78ab9-config.json','pdf-appearance-9d78ab9-collector.log','pdf_review_appearance9d_facts.py','pdf_review_appearance9d.py','pdf_stage_appearance9d_evidence.py']:
    p=Path('/tmp')/name;put('collection-tools/'+name,read(p),'derived-collector-or-retention-tool-record',{'originalPath':str(p),'notProductOrArtifactCode':True})
retention={'schemaVersion':1,'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'runConclusion':'success','jobs':JOBS,'sourceCompilePackPassed':True,'targetRestorePassed':True,'appearanceDiagnosticAutomatedPassed':True,'sameDiagnosticBundleDeclarationBoundAcrossSystems':True,'checksPerSystem':12,'originalPNGCount':14,'nativeCentralContrastMeasurements':36,'nativeCentralContrastMinimumSDK26':results[0]['measurementMinimum'],'nativeCentralContrastMinimumTarget27':results[1]['measurementMinimum'],'workspaceBeforeAfterObservations':24,'independentVisualReviewRetained':True,'focalVisualApproval':True,'confirmedVisualBlockersInObservedFrames':[],'visualReviewLimitedToObservedFrames':True,'fullNativeWorkflowExecutedAtRetention':False,'fullNativeWorkflowStatusSource':'Coordinator explicitly deferred the full matrix while source-package size failure is corrected.','recoveryPathsExercisedByAppearanceFocal':False,'sourcePackageApproved':False,'installationApproved':False,'completeApplicationApproved':False,'deliveryAllowed':False,'transferArtifactDownloaded':False,'tarOrAppRetained':False,'collectorIncidentInThisRun':False,'eachArtifactDownloadedOnce':True,'collectorOfflineTestsPassed':18,'approvalTransferredFromPriorSource':False}
put('retention-summary.json',enc(retention),'derived-appearance-only-retention-summary',{'sourceCommit':SOURCE,'runID':RUN})
readme=f'''# Aparência9d78ab9 — diagnóstico focal aprovado, entrega não aprovada

Fonte/controlador `{SOURCE}`, run `{RUN}`, tentativa1, jobs26 `{JOBS['compile-sdk26']}` e27 `{JOBS['same-binary-xcode27']}`. **O diagnóstico focal automatizado passou nos dois sistemas:**12 checks por sistema, sete PNGs por sistema e36 medidas centrais dos três controles de toolbar. A revisão independente dos14 originais não encontrou bloqueador visual confirmado nesses quadros; seu escopo restrito está preservado. Isso não aprova matriz completa, recuperação, pacote/instalador ou entrega.

| Evidência | Resultado |
|---|---|
| Build/pack SDK26 e restore do mesmo bundle no27 |Etapas originais success |
| Frames/reportes/recibos |7+7 PNGs; reportes/recibos passed |
| Checks nativos |12/12 em cada sistema |
| Contraste central dos3 controles |18 medidas por sistema; mínimos26={results[0]['measurementMinimum']:.6f}:1 e27={results[1]['measurementMinimum']:.6f}:1; limiar3:1 |
| Identidade/geometria |24 snapshots antes/depois, conferidos pelo checker exato |
| Checker noSDK26 |28 testes OK; não é a matriz completa |
| Recuperação/empacotamento/entrega |Fora da aprovação focal |

A escolha dos controles usa itens públicos reais; os JSON preservam identidades, metadados, bounds, medidas e PNGs correspondentes. O checker do Git exato refez offline as medidas a partir dos originais e conferiu seus gates. Contraste central em três controles não equivale a certificação universal WCAG; imagens estáticas não validam todos os cliques, animações, conteúdo rolável, VoiceOver humano ou demais áreas do aplicativo.

## Originais e proveniência

- `originals/downloads/`: dois ZIPs de evidência autenticados por digest GitHub e ZIP oficial de logs. Cada evidência foi baixada uma vez. Não há ZIP de transporte do bundle.
- `originals/extracted/`:inventários15/14, com14 PNGs, JSON/recibos, manifestos e logs originais. Nenhuma imagem foi alterada.
- `originals/official-attempt-logs/`:dois agregados;31 membros completos estão no ZIP. O endpoint autenticado de logs não fornece digest independente; o SHA identifica os bytes recebidos.
- `provenance/`:APIs antes/depois, configuração/recibos e vínculo dos preflights ao Git9d.
- `exact-source/`:16 seleções do coletor e o teste do checker acrescentado pelo vínculo do preflight. São seleções de fonte, não o aplicativo completo. RecoveryStore/WorkspaceModel/SessionAnnotationAuditChecks foram retidos, mas seus caminhos de recuperação não são exercitados por este focal.
- `reviews/`:recontagem factual e revisão independente dos14 originais. Nenhuma aprovação anterior foi transferida. O collector-summary original mantém visual pending porque antecede esta revisão; a aprovação visual restrita posterior está no relatório independente, sem editar aquele original.
- `local-preflight/`:sintaxe de90 Swift sem typecheck SDK, suíte local de178 métodos (171 PASS e7 testes macOS pulados noLinux), reteste do checker28 e hashes dos arquivos. A redação temporal de testes nativos pendentes foi preservada como preparação; o sucesso posterior aqui é limitado ao focal de aparência.
- `collection-tools/`:coletor83430bd, delta/18 testes offline, rascunhos, configuração final, log único de coleta e scripts de verificação/retenção. Rascunhos inválidos foram preservados como história, não usados como identidade real.

## Limites de aprovação

O root reproduziu separadamente falha do pacote fonte por tamanho expandido e atribuiu sua correção. Os relatórios dessa falha/preflight sujo ficam em retenção separada, sem TAR grande ou checkout encapsulado. A matriz completa9d foi adiada; nenhum resultado deste focal aprova o pacote ou valida caminhos de recuperação. Um futuro pacote feito de commit limpo exigirá evidência separada.

Os manifestos são byte idênticos: SHA `{sha(manifests[0])}`. Declaram tar de{results[0]['declaredArchive']['bytes']} bytes, SHA `{results[0]['declaredArchive']['sha256']}`. APIs, pack/restore e metadados vinculam a declaração do mesmo bundle; o tar/app não foi baixado, extraído ou executado localmente. Bundle mínimo não é instalador completo.

`inventory.json` registra bytes/SHA/origem e `SHA256SUMS` cobre arquivos e índice. Confira com `sha256sum -c SHA256SUMS`. Esta retenção não testa M4 físico, consumo/Neural Engine, IA real, scanner, serviços de produção ou VoiceOver humano. `deliveryAllowed` permanece false.
'''
# Spaces in prose are normalized before freezing; identifiers and hashes remain literal.
for a,b in [('Aparência9','Aparência 9'),('tentativa1','tentativa 1'),('jobs26','jobs 26'),(':**12',':** 12'),('e36','e 36'),('dos14','dos 14'),('dos3','dos 3'),('mínimos26','mínimos 26'),('limiar3','limiar 3'),('noSDK26','no SDK 26'),('SDK26','SDK 26'),('no27','no 27'),('inventários15','inventários 15'),('com14','com 14'),(';31','; 31'),('Git9d','Git 9d'),('de90','de 90'),('de178','de 178'),('noLinux','no Linux'),('checker28','checker 28'),('coletor83430bd','coletor 83430bd'),('delta/18','delta / 18'),('completa9d','completa 9d'),('de{','de {')]:readme=readme.replace(a,b)
need(SOURCE in readme and sha(manifests[0]) in readme and results[0]['declaredArchive']['sha256'] in readme,'Readme must preserve exact hashes.')
put('README.md',readme.encode(),'derived-appearance-only-readme',{'sourceCommit':SOURCE,'runID':RUN})
index={'schemaVersion':1,'sourceCommit':SOURCE,'runID':RUN,'status':'passed-appearance-only-retention-not-delivery','deliveryAllowed':False,'scope':'Every retained file except inventory.json and SHA256SUMS; SHA256SUMS additionally covers inventory.json.','files':sorted(inventory,key=lambda row:row['path'])}
index_raw=enc(index);(WORK/'inventory.json').write_bytes(index_raw)
checks=sorted([(row['path'],row['sha256']) for row in inventory]+[('inventory.json',sha(index_raw))]);(WORK/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in checks))
for row in inventory:need(match(read(WORK/row['path']),row),'Retained hash mismatch.')
need({p.relative_to(WORK).as_posix() for p in WORK.rglob('*') if p.is_file()}=={row['path'] for row in inventory}|{'inventory.json','SHA256SUMS'},'Retained inventory not closed.')
for p,value in list(OBSERVED.items()):need(read(p)==value,'Original changed during retention.')
need(not list(WORK.rglob('*.tar.gz')) and not list(WORK.rglob('*.tar')) and not list(WORK.rglob('*.app')),'Unexpected bundle retained.')
os.rename(WORK,DEST);files=[p for p in DEST.rglob('*') if p.is_file()]
print(json.dumps({'stage':str(DEST),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(index_raw),'sourceCommit':SOURCE,'runID':RUN,'runConclusion':'success','nativeCentralContrastMeasurements':36,'deliveryAllowed':False},indent=2))
