#!/usr/bin/env python3
"""Offline factual recount of successful focal9d with limited scope; no network or artifact execution."""
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
output={'schemaVersion':1,'reviewedAtUTC':datetime.now(timezone.utc).isoformat(),'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'status':'passed-appearance-only-automated-diagnostic','networkCallsDuringReview':0,'artifactCodeExecuted':False,'productModified':False,'gatesModified':False,'visualApprovalInferred':False,'completeApplicationApproved':False,'installationApproved':False,'deliveryAllowed':False,'jobs':results,'totalPNGsVerified':14,'nativeCentralContrastMeasurements':36,'beforeAfterWorkspaceObservations':24,'manifestBytesIdenticalAcrossSystems':True,'sameDiagnosticBundleDeclarationBoundAcrossSystems':True,'transportTarLocallyDownloadedOrExecuted':False,'officialLogZIP':official,'exactSourceRecords':source_records,'currentCollectionIncidentObserved':False,'eachEvidenceArtifactDownloadedOnce':True,'separateRecoverySourceRetention':['Sources/PDF/RecoveryStore.swift','Sources/PDF/WorkspaceModel.swift','Sources/PDF/SessionAnnotationAuditChecks.swift'],'recoveryPathsExercisedByThisFocal':False,'fullNativeWorkflowApproved':False,'sourcePackageApproved':False,'packageFailureReportedSeparatelyByCoordinator':{'reported':True,'detail':'Root reproduced package-source expanded size147MB above120MiB and assigned producer/consumer correction. This focal does not exercise or approve that package.','independentlyReproducedByThisReview':False},'limits':['Three actual toolbar controls measured centrally in six workspace states per system; not universal WCAG certification.','Static PNGs and native focal checks do not approve all clicks, animation, scrolling, VoiceOver or other workspaces.','Source recovery changes are retained for provenance but not exercised by this appearance-only focal.','Full native matrix, source/runtime installer packaging, recovery paths, physical M4 and production services are outside this approval.','Transport tar/app is not downloaded, extracted or executed locally; original workflow pack/restore and metadata provide the same-bundle declaration binding.']}
base=Path('/tmp/pdf-appearance-9d78ab9-factual-log-review');need(not base.with_suffix('.json').exists() and not base.with_suffix('.md').exists(),'Do not overwrite review.')
base.with_suffix('.json').write_bytes(enc(output))
md=f'''# Revisão factual9d78ab9 — focal automatizado aprovado, escopo restrito

Fonte/controlador `{SOURCE}`, run `{RUN}`, tentativa1. Os dois jobs e todas as suas etapas terminaram em **success**. A releitura offline com o checker do Git exato confirmou reportes, originais e medidas. Isso aprova o diagnóstico focal de aparência; **não aprova recuperação, pacote/instalador, matriz nativa completa ou entrega**.

| Job | Sistema | PNGs | Checks | Medidas centrais | Menor contraste |
|---|---|---:|---:|---:|---:|
'''
for row in results:md+=f"| {row['job']} · {row['jobID']} | {row['operatingSystem']} |7|12/12|18|{row['measurementMinimum']:.6f}:1|\n"
md+='''
São36 medidas centrais, três controles reais em seis estados de workspace por sistema, com limiar3:1. O checker exato refez a comparação dos pixels e conferiu identidade, aparência, geometria e estabilidade antes/depois das capturas. Isso não é certificação WCAG universal nem validação de todos os controles/fluxos. Os24 snapshots e todas as36 medidas estão preservados no JSON acompanhante.

As sete linhas de captura de cada artefato coincidem com a etapa oficial e seu agregado. Os14 PNG coincidem com fingerprints/dimensões e passaram releitura de CRC/raster. O job26 registra28 testes do checker com OK, contados uma vez no agregado; o job27 não repete a suíte. O recibo impresso em cada validation.log corresponde exatamente ao JSON original e consta no log oficial.

'''
md+=f"Os manifestos são byte idênticos: SHA `{sha(manifests[0])}`. Declaram tar de {results[0]['declaredArchive']['bytes']} bytes, SHA `{results[0]['declaredArchive']['sha256']}`. A coleta vincula a declaração do mesmo bundle pelos originais/API/pack/restore; não baixou, extraiu ou executou o tar/app localmente. Bundle mínimo não equivale ao instalador completo.\n\n"
md+='''Os dois ZIPs de evidência foram baixados uma vez e reconferidos pelo digest GitHub e todos os membros. O ZIP oficial de logs e seus membros também foram reconferidos; esse endpoint autenticado não fornece digest externo independente. Os16 arquivos selecionados correspondem ao Git exato9d; os três arquivos de recuperação são apenas retenção de fonte, não caminhos exercitados pelo focal. Nenhum produto/gate foi alterado por esta releitura.

A revisão visual dos14 originais é independente e não foi inferida destes contadores. O coordenador relatou separadamente falha no package-source (147MB expandidos acima de120MiB), com correção atribuída a outra frente. Esta revisão não reproduziu nem aprovou esse pacote. A fonte9d não recebe aprovação de matriz completa/instalação/recuperação por ter passado no focal. M4 físico, energia/Neural Engine, IA real, scanner, VoiceOver humano e serviços de produção permanecem fora deste diagnóstico.
'''
base.with_suffix('.md').write_text(md)
for path,value in list(OBSERVED.items()):need(read(path)==value,'Original changed during review.')
print(json.dumps({'json':fp(base.with_suffix('.json')),'markdown':fp(base.with_suffix('.md')),'originalPNGs':14,'officialLogMembers':len(log_members),'workspaceObservations':24,'nativeCentralContrastMeasurements':36,'focalAutomatedPassed':True,'visualApprovalInferred':False,'fullApplicationApproved':False,'deliveryAllowed':False},indent=2))
