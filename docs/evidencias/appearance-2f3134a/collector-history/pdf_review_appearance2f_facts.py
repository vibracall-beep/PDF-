#!/usr/bin/env python3
"""Offline factual review of original failed diagnostic; no product or gate edits."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import hashlib,importlib.util,json,re,subprocess,sys
sys.dont_write_bytecode=True
ROOT=Path('/workspace/.cache/pdf-appearance-2f3134a-40246632222')
SHA='2f3134a41229054f41a176d6a48cc6c23e388b77';RUN=40246632222
config=json.loads((ROOT/'collector-configuration.json').read_text());state=json.loads((ROOT/'collector-artifact-state.json').read_text());api=json.loads((ROOT/'collector-jobs-after.json').read_text());official=json.loads((ROOT/'collector-official-logs.json').read_text())
assert config['sourceCommit']==config['controlCommit']==SHA and config['runID']==RUN
helper=ROOT/'exact-source/controller/scripts/check_appearance_preview.py'
expected=subprocess.check_output(['git','show',SHA+':scripts/check_appearance_preview.py'],cwd='/workspace/PDF-',env={**__import__('os').environ,'GIT_NO_LAZY_FETCH':'1'})
assert helper.read_bytes()==expected
spec=importlib.util.spec_from_file_location('appearance_factual_png_parser',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def fp(p):
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
results=[];manifests=[]
for jobname,artifact in [('compile-sdk26','PDF-appearance-sdk26'),('same-binary-xcode27','PDF-appearance-same-binary-xcode27')]:
 d=ROOT/'extracted'/artifact;job=next(j for j in api['jobs'] if j['name']==jobname);r=json.loads((d/'PDF-appearance.appearance.json').read_text());rec=json.loads((d/'appearance-validation.json').read_text());man=json.loads((d/'appearance-bundle.json').read_text());manifests.append((d/'appearance-bundle.json').read_bytes());download=next(x for x in state['attempts'].values() if x['name']==artifact)
 frames=[];errors=Counter()
 for f in r['frames']:
  p=d/f['png'];raw=p.read_bytes();dim=m.png_dimensions(raw)
  assert dim==(f['width'],f['height']) and len(raw)==f['bytes'] and hashlib.sha256(raw).hexdigest()==f['sha256']
  toolbar=f.get('toolbarReport');snapshot=f.get('windowSnapshot',{})
  if toolbar:errors.update(toolbar.get('errors',[]))
  frames.append({'phase':f['phase'],'selection':f['selection'],'original':fp(p),'dimensions':list(dim),'PNGCRCAndRasterParsed':True,'nativeFrameFingerprintMatched':True,'windowNumber':snapshot.get('windowNumber'),'workspaceToolbarProviderCount':snapshot.get('workspaceToolbarProviderCount'),'controlsDetected':len(snapshot.get('controls',[])),'snapshotErrors':snapshot.get('errors',[]),'toolbarItemIdentifiers':snapshot.get('toolbarItemIdentifiers',[]),'toolbarPassed':None if toolbar is None else toolbar['passed'],'measurementCount':0 if toolbar is None else len(toolbar.get('measurements',[]))})
 capture=(d/'capture.log').read_text();validation=(d/'validation.log').read_text();origin=(d/'origin.log').read_text()
 captures=[{'png':a,'windowNumber':int(b),'points':c,'pixels':e} for a,b,c,e in re.findall(r'PDF preview captured from WindowServer via ScreenCaptureKit: ([^;]+); window=(\d+); content=([^;]+); pixels=([^;\n]+)',capture)]
 assert len(captures)==7 and {x['png'] for x in captures}=={f['png'] for f in r['frames']}
 step_records=[{k:s.get(k) for k in ['number','name','status','conclusion','started_at','completed_at']} for s in job['steps']]
 summaries=re.findall(r'^Ran (\d+) tests? in ([\d.]+)s\s*\n\s*OK\s*$',origin,re.M)
 results.append({'job':jobname,'jobID':job['id'],'conclusion':job['conclusion'],'steps':step_records,'artifact':{'id':download['artifactID'],'bytes':download['archiveBytes'],'sha256':download['archiveSHA256'],'downloadAttempts':download['downloadAttempts']},'nativeReport':fp(d/'PDF-appearance.appearance.json'),'nativeStatus':r['status'],'nativeFailure':r.get('failure'),'checks':r['checks'],'passedChecks':sum(c['passed'] is True for c in r['checks']),'failedChecks':[c['id'] for c in r['checks'] if c['passed'] is False],'operatingSystem':r['operatingSystem'],'manifest':fp(d/'appearance-bundle.json'),'builtSDK':man['builtSDK'],'declaredArchive':man['tar'],'declaredFiles':man['files'],'failedReceipt':rec,'receiptOriginal':fp(d/'appearance-validation.json'),'frames':frames,'observedWindowNumbers':sorted({f['windowNumber'] for f in frames}),'toolbarReportsWithNoMeasurements':sum(f['toolbarPassed'] is not None and f['measurementCount']==0 for f in frames),'measurementRowsTotal':sum(f['measurementCount'] for f in frames),'toolbarErrorCounts':dict(errors),'originalCaptureLines':captures,'captureLogsNoTimeoutMarkersFound':not bool(re.search(r'TimeoutExpired|timed out|timeout exceeded',capture,re.I)),'validationLastError':validation.strip().splitlines()[-1],'originPythonSuites':[{'tests':int(a),'seconds':float(b),'status':'OK'} for a,b in summaries],'originalLogs':[fp(d/name) for name in sorted(p.name for p in d.glob('*.log'))]})
assert len(results)==2 and all(x['nativeStatus']=='failed' and x['passedChecks']==8 and len(x['failedChecks'])==4 and x['measurementRowsTotal']==0 for x in results)
assert manifests[0]==manifests[1]
output={'schemaVersion':1,'reviewedAtUTC':datetime.now(timezone.utc).isoformat(),'sourceCommit':SHA,'controllerCommit':SHA,'runID':RUN,'attempt':1,'status':'factual-review-of-failed-appearance-diagnostic','networkCallsDuringReview':0,'artifactCodeExecuted':False,'productModified':False,'gatesModified':False,'applicationFailureCauseEstablished':False,'visualApprovalInferred':False,'completeApplicationApproved':False,'deliveryAllowed':False,'jobs':results,'manifestBytesIdenticalAcrossSystems':True,'sameDeclaredBundleFingerprintAcrossSystems':True,'binaryOrTarLocallyDownloadedOrExecuted':False,'transferBindingScope':'Original workflow pack/restore steps passed and both manifests are byte identical; this reviewer did not download or rehash the transport tar or execute the app. Collector summary remains false because full receipt checks did not pass.','PNGObservations':{'originalCount':14,'allNativeFrameFingerprintsMatched':True,'allPNGCRCAndRasterParsed':True,'notVisualApproval':True},'officialLogs':official,'metadataOriginals':[fp(ROOT/name) for name in ['collector-configuration.json','collector-run-before.json','collector-run-after.json','collector-jobs-before.json','collector-jobs-after.json','collector-artifacts-before.json','collector-artifacts-after.json','collector-artifact-state.json','collector-summary.json']],'parserFromExactGit':{'commit':SHA,'path':'scripts/check_appearance_preview.py','sha256':hashlib.sha256(expected).hexdigest()},'collectorIncident':{'firstAttemptStoppedBeforeExtraction':True,'reason':'Local collector incorrectly compared original filename to casefold-normalized collision key; legitimate uppercase PDF names were refused.','originalZip26RetainedAndReused':True,'downloadAttemptsPerArtifact':1,'approvedFix':'Keep exact original filename/allowlist and use normalized names only to reject collisions.','fixDiff':fp(Path('/tmp/pdf-appearance-collector-casefold.diff')),'notEvidenceAboutApplicationFailure':True},'limits':['Both reports failed and no contrast measurements were completed; this review cannot conclude whether visual contrast is acceptable.','Observed numeric window IDs alone do not override failed same-real-window or identity checks.','The errors describe failure to locate the expected direct toolbar controls; root cause of that observation was not established by this factual review.','No full native matrix, installer/runtime, physical M4, human VoiceOver or final delivery was approved.']}
base=Path('/tmp/pdf-appearance-2f3134a-factual-log-review');base.with_suffix('.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
md=f'''# Revisão factual do focal 2f3134a — execução reprovada

Fonte/controlador `{SHA}`, run `{RUN}`, tentativa 1. Os dois jobs terminaram em **failure**. Esta revisão somente leu originais autenticados; não executou artefatos, alterou produto/gates ou estabeleceu causa da falha.

| Job | Sistema reportado | PNGs produzidos | Checks true/false | Medidas de contraste |
|---|---|---:|---:|---:|
'''
for j in results:md+=f"| {j['job']} · {j['jobID']} | {j['operatingSystem']} | 7 | 8/4 | 0 |\n"
md+='''
Build/pack do SDK26 e restore do mesmo bundle no27 passaram nas etapas da API. Captura e validação falharam nos dois sistemas, e os artefatos de falha foram publicados. O job de origem registra 21 testes do checker com OK; isso não substitui o ensaio real reprovado.

Os sete arquivos PNG existem em cada sistema e coincidem com nome, bytes, SHA-256 e dimensões registrados no reporte nativo. A releitura offline com o parser do Git exato conferiu CRC e raster dos14 originais. São arquivos de1050×772; essa integridade não aprova aparência.

## Fatos registrados nos reportes

Os dois reportes falham nos mesmos quatro IDs:

- `same-real-window`
- `three-controls-central-contrast-every-workspace-frame`
- `attached-toolbar-identities-preserved`
- `toolbar-controls-return-after-customization`

Cada sistema tem seis toolbarReports, todos com `measurements=[]`. Os erros repetidos são `Expected exactly one direct toolbar control: autoSidebar`, `...pdf.commands.toolbar` e `...pdf.customize.toolbar`. As snapshots registram `workspaceToolbarProviderCount=0` e nenhuma entrada em `controls`. Portanto estes JSON não contêm uma medição de contraste concluída. Não concluí que as cores foram aprovadas ou reprovadas por uma medida inexistente.

As snapshots/logs de captura registram número de janela29 durante as sete fases de cada sistema. Esse dado numérico não altera o check `same-real-window=false`, nem prova por si só a identidade dos controles. As listas de toolbarItemIdentifiers e erros completos permanecem no JSON derivado e nos originais para investigação independente.

Drenagem do trabalho, limpeza privada, ausência de documento e liberação das sobrescritas no modo Sistema são registrados como true pelos respectivos checks. Não houve marcador de timeout procurado nos logs de captura; os reportes foram escritos com `status=failed; originalFrames=7`. A causa dessa falha não foi inferida aqui.

## Vínculo de transporte, sem executar o bundle

'''
md+=f"SDK declarado: `{results[0]['builtSDK']}`. Os dois `appearance-bundle.json` são byte idênticos, SHA-256 `{results[0]['manifest']['sha256']}`. Declaram tar `{results[0]['declaredArchive']['sha256']}`, {results[0]['declaredArchive']['bytes']} bytes, e o mesmo executável/Info.plist/lock/CodeResources. A etapa de restore/verificação passou na API. Este revisor não baixou nem executou o tar; o flag geral do coletor permanece falso porque os recibos de validação falharam.\n\n"
md+='''## Integridade da coleta e limites

O primeiro main do coletor interrompeu a extração ao tratar incorretamente o resultado casefold de `_name` como nome original. Esse defeito local foi corrigido com autorização, preservando comparação literal/allowlist e recusando colisões. A regressão passou com nomes maiúsculos legítimos e colisões por caixa. O ZIP26 já autenticado foi reutilizado; cada artefato tem uma única tentativa de download. Esse incidente não é evidência da causa da falha do aplicativo.

ZIPs, logs oficiais agregados, snapshots API, reportes e14 PNG originais permanecem em `/workspace/.cache/pdf-appearance-2f3134a-40246632222`. Seus caminhos, hashes e bytes constam do JSON acompanhante. O ZIP oficial de logs foi obtido do endpoint autenticado, que não fornece digest independente.

Não há aprovação visual nesta leitura factual. A revisão visual independente dos PNGs ocorre separadamente. A fonte37f5b65 continua visualmente reprovada no seu teste cruzado; nenhum resultado anterior foi transferido para2f3134a. Não houve matriz completa, validação de instalação/engine, VoiceOver humano, medição física deM4 ou entrega aprovada.
'''
base.with_suffix('.md').write_text(md)
print(json.dumps({'json':fp(base.with_suffix('.json')),'markdown':fp(base.with_suffix('.md')),'jobsFailed':2,'PNGsIntegrityChecked':14,'contrastMeasurementsCompleted':0,'visualApproval':False,'causeEstablished':False},indent=2))
