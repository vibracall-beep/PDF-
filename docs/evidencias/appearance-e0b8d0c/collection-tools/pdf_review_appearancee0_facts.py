#!/usr/bin/env python3
"""Offline factual recount of failed focal e0; no network or artifact execution."""
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
# Supplement current hierarchy/topology observations without selecting controls or approving contrast.
for result in results:
    folder=ROOT/'extracted'/('PDF-appearance-sdk26' if result['job']=='compile-sdk26' else 'PDF-appearance-same-binary-xcode27')
    report=load(folder/'PDF-appearance.appearance.json')
    hierarchy=[]
    for frame in report['frames']:
        toolbar=frame.get('toolbarReport')
        if toolbar:
            for timing in ['before','after']:
                snapshot=toolbar[timing]
                hierarchy.append({'phase':frame['phase'],'timing':timing,'providers':[{'nativeClass':provider['node']['nativeClass'],'directChildCount':provider['directChildCount'],'nativeViews':len(provider.get('nativeViews',[])),'nativeHierarchyTruncated':provider.get('nativeHierarchyTruncated')} for provider in snapshot['toolbarProviders']],'nativeToolbarItemCount':len(snapshot.get('nativeToolbarItems',{}).get('items',[])),'nativeToolbarTraversalLimited':snapshot.get('nativeToolbarItems',{}).get('traversalLimited')})
    custom=next(frame['windowSnapshot'] for frame in report['frames'] if frame['phase']=='customization')
    result['newHierarchyObservations']=hierarchy
    result['customizationObservedAppearance']={'application':custom['applicationEffectiveAppearance'],'window':custom['windowEffectiveAppearance'],'content':custom['contentEffectiveAppearance'],'nativePopups':[{'title':v['title'],'effectiveStyle':v['effectiveStyle'],'effectiveAppearance':v['effectiveAppearance']} for v in custom['nativePopupControls']]}
    result['captureTimeoutMarkerFound']=bool(re.search(r'TimeoutExpired|timed out|timeout exceeded',read(folder/'capture.log').decode(),re.I))
factual={'schemaVersion':1,'reviewedAtUTC':datetime.now(timezone.utc).isoformat(),'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'status':'failed-appearance-only-diagnostic','networkCallsDuringReview':0,'artifactCodeExecuted':False,'productModified':False,'gatesModified':False,'applicationFailureCauseEstablished':False,'visualApprovalInferred':False,'completeApplicationApproved':False,'deliveryAllowed':False,'jobs':results,'totalPNGsVerified':14,'nativeContrastMeasurements':0,'beforeAfterWorkspaceObservations':24,'manifestBytesIdenticalAcrossSystems':True,'transportTarLocallyDownloadedOrExecuted':False,'sameBundleGateRemainsFailed':summary['sameDiagnosticBundleBoundAcrossBothSystems'] is False,'officialLogZIP':official,'exactSourceRecords':source_records,'currentCollectionIncidentObserved':False,'eachEvidenceArtifactDownloadedOnce':True,'limits':['Integrity/CRC/raster is not visual or accessibility approval.','There are no native contrast measurements; snapshots and numeric window IDs cannot override failed checks.','Aqua popup-provider observations are factual JSON records; an independent review of the current original PNGs is still required.','This focal is not the full native workflow, installer validation or a physical M4 benchmark.','Transport binding is based on original API/pack/restore/manifests without local download, extraction or execution of the tar/app.']}
base=Path('/tmp/pdf-appearance-e0b8d0c-factual-log-review')
need(not base.with_suffix('.json').exists() and not base.with_suffix('.md').exists(),'Do not overwrite factual review.')
base.with_suffix('.json').write_bytes(enc(factual))
md=f"""# Revisão factual e0b8d0c — focal reprovado

Fonte/controlador `{SOURCE}`, run `{RUN}`, tentativa1. **Build/pack SDK26 e restore27 passaram; captura e validação falharam em ambos os sistemas.** A coleta exit0 preservou falhas; ela não aprovou o aplicativo. Esta releitura offline não executou artefatos, fez rede ou alterou produto/gates.

| Job | Sistema | PNGs íntegros | Checks true/false | Medidas nativas |
|---|---|---:|---:|---:|
"""
for result in results:md+=f"| {result['job']} · {result['jobID']} | {result['operatingSystem']} |7|8/4|0|\n"
md+='\nOs14 PNG atuais coincidem com nome, tamanho, SHA e dimensões dos frames; o parser do Git exato conferiu CRC/raster. As sete linhas de captura de cada artefato coincidem com as linhas da etapa oficial e do agregado. O job26 registra uma suíte de21 testes do checker com OK; o job27 não repetiu essa suíte. Isso não representa a matriz nativa completa.\n\nOs24 snapshots antes/depois dos12 estados de workspace continuam encontrando AXToolbar sem filhos diretos e sem seleção dos três controles. Todos os12 toolbarReports têm measurements vazio. A nova topologia nativa e os itens públicos estão registrados nos JSON originais; sua existência não sobrepõe a seleção/checks reprovados. Os mesmos quatro IDs falharam: same-real-window, three-controls-central-contrast-every-workspace-frame, attached-toolbar-identities-preserved e toolbar-controls-return-after-customization.\n\nNesta fonte, os cinco NSPopUpButton observados em Personalização26 reportam light/Aqua dentro de aplicação/janela/conteúdo light/Aqua. Esse fato não deve ser substituído pelo resultado DarkAqua do run877 anterior, nem aprova aparência sem abrir os pixels atuais. A revisão visual independente é separada desta recontagem factual. Não foi inferida causa única para a falha do observador.\n\n'
md+=f"Os dois manifestos são byte idênticos, SHA `{sha(manifests[0])}`. Declaram tar de{results[0]['declaredArchive']['bytes']} bytes, SHA `{results[0]['declaredArchive']['sha256']}`. Pack/restore passaram nas etapas originais, porém o gate geral de aprovação do vínculo continua falso porque os reportes/recibos falharam. O tar/app não foi baixado, extraído ou executado localmente.\n\n"
md+='Cada ZIP de evidência foi baixado uma vez. Os dois digests GitHub, todos os membros e o ZIP oficial de logs foram reconferidos. O endpoint de logs autenticado não fornece digest externo independente. Nenhum incidente de coleta ocorreu nesta execução. Os13 arquivos de fonte/controlador usados na retenção coincidem com o Git exato e0; nenhum arquivo de evidência anterior foi relabelado como atual.\n\nNão há aprovação visual, de instalação, de produto completo ou de entrega nesta leitura. O foco é um bundle mínimo e sete estados por sistema; não mede M4 físico/energia/Neural Engine, VoiceOver humano, IA real, scanner ou serviços de produção. Resultados anteriores não foram transferidos.\n'
base.with_suffix('.md').write_text(md)
for p,value in list(OBSERVED.items()):need(read(p)==value,'Original changed during factual review.')
print(json.dumps({'json':fp(base.with_suffix('.json')),'markdown':fp(base.with_suffix('.md')),'originalPNGs':14,'officialLogMembers':len(log_members),'workspaceObservations':24,'nativeMeasurements':0,'visualApproval':False,'runConclusion':'failure','deliveryAllowed':False},indent=2))
