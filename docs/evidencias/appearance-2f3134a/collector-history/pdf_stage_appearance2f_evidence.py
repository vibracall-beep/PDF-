#!/usr/bin/env python3
"""Offline preservation of the failed appearance-only 2f3134a experiment."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,os,stat,subprocess,sys,zipfile,io
sys.dont_write_bytecode=True
ROOT=Path('/workspace/.cache/pdf-appearance-2f3134a-40246632222')
DEST=Path('/tmp/pdf-appearance-2f3134a-evidence-staging')
WORK=Path('/tmp/pdf-appearance-2f3134a-evidence-staging.building')
SOURCE='2f3134a41229054f41a176d6a48cc6c23e388b77';RUN=40246632222
JOBS={'compile-sdk26':121329466580,'same-binary-xcode27':121330497217}
LIMIT=128*1024*1024

def need(ok,message):
 if not ok:raise ValueError(message)
def read(p,cap=LIMIT):
 with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
  a=os.fstat(f.fileno());need(stat.S_ISREG(a.st_mode) and a.st_uid==os.getuid() and a.st_size<=cap,'Bounded regular original required: '+str(p));raw=f.read(cap+1);b=os.fstat(f.fileno());need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,len(raw),b.st_mtime_ns,b.st_ctime_ns),'Original changed: '+str(p));return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def load(p):return json.loads(read(p))
def matches(raw,record):return len(raw)==record['bytes'] and sha(raw)==record['sha256']
need(not os.path.lexists(DEST) and not os.path.lexists(WORK),'Do not overwrite retained evidence.')
config=load(ROOT/'collector-configuration.json');state=load(ROOT/'collector-artifact-state.json');summary=load(ROOT/'collector-summary.json')
need(config['sourceCommit']==config['controlCommit']==SOURCE and config['runID']==RUN and config['runAttempt']==1 and config['jobIDs']==JOBS,'Configuration identity differs.')
need(summary['runConclusion']=='failure' and summary['appearanceDiagnosticAutomatedPassed'] is False and summary['deliveryAllowed'] is False,'Failed diagnostic must remain failed.')
need(len(state['attempts'])==2 and {v['name'] for v in state['attempts'].values()}=={'PDF-appearance-sdk26','PDF-appearance-same-binary-xcode27'},'Expected two evidence artifacts.')
# Reuse reviewed local ZIP reader, and only exact Git archive validation source.
cp=Path('/tmp/pdf_collect_appearance.py');need(sha(read(cp))=='95c779d4183fd7bd79318d58d3d55847f0f55580d620606753b47f19e669947b','Collector changed since reviewed casefold fix.')
spec=importlib.util.spec_from_file_location('retention_appearance_collector',cp);collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
ap=ROOT/'exact-source/controller/diagnostics/delivery_archives.py';git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1')
need(read(ap)==subprocess.check_output(['git','show',SOURCE+':diagnostics/delivery_archives.py'],cwd='/workspace/PDF-',env=git_env),'Archive validator differs from exact Git.')
spec=importlib.util.spec_from_file_location('retention_appearance_archives',ap);archives=importlib.util.module_from_spec(spec);spec.loader.exec_module(archives)
for rec in state['attempts'].values():
 need(rec['sourceCommit']==rec['controllerCommit']==SOURCE and rec['runID']==RUN and rec['runAttempt']==1 and rec['downloadAttempts']==1 and rec['downloaded'] and rec['inventoryComplete'],'Artifact origin/inventory/download count differs.')
 raw=read(ROOT/'downloads'/f"{rec['artifactID']}.zip")
 need(len(raw)==rec['archiveBytes'] and sha(raw)==rec['archiveSHA256']==rec['githubDigest'].removeprefix('sha256:'),'Artifact ZIP digest differs.')
 job='compile-sdk26' if rec['name']=='PDF-appearance-sdk26' else 'same-binary-xcode27'
 members=collector.unpack_small_zip(raw,{n:collector.cap_for(n) for n in collector.inventory_for(job)},archives)
 need(set(members)==set(rec['files'])=={p.name for p in (ROOT/'extracted'/rec['name']).iterdir()},'Artifact exact inventory differs.')
 for n,value in members.items():need(matches(value,rec['files'][n]) and value==read(ROOT/'extracted'/rec['name']/n),'Artifact member changed.')
visual_path=Path('/tmp/pdf-appearance-2f-independent-review.json');visual_raw=read(visual_path);visual=json.loads(visual_raw)
need(sha(visual_raw)=='46be1870f7f355a2b0c6123b8ff806fd06a4f83bb0daacd59bccab22d4b03ef1' and visual['sourceCommit']==SOURCE and visual['runID']==RUN and visual['originalPNGCount']==14 and visual['productApproved'] is False,'Frozen visual review differs.')
for f in visual['files']:need(matches(read(ROOT/'extracted'/f['artifact']/f['file']),f) and f['originalVisuallyInspected'],'Visual-review original differs.')
factual=load(Path('/tmp/pdf-appearance-2f3134a-factual-log-review.json'))
need(factual['sourceCommit']==SOURCE and factual['runID']==RUN and factual['deliveryAllowed'] is False and all(j['measurementRowsTotal']==0 for j in factual['jobs']),'Factual review differs.')
preflight_path=Path('/tmp/pdf-appearance-local-preflight.json');preflight=load(preflight_path);bound_files=[]
for path,digest in preflight['candidateFiles'].items():
 raw=subprocess.check_output(['git','show',SOURCE+':'+path],cwd='/workspace/PDF-',env=git_env);need(sha(raw)==digest,'Local preflight candidate is not exact committed source: '+path);bound_files.append({'path':path,'bytes':len(raw),'sha256':digest,'raw':raw})
need(sha(read(Path('/tmp/pdf-appearance-scripts-local.log')))==preflight['scriptsLogSHA256'],'Local preflight log changed.')
WORK.mkdir(mode=0o700);inventory=[];observed={}
def put(path,raw,kind,origin):
 rel=Path(path);need(not rel.is_absolute() and '..' not in rel.parts,'Unsafe staged path.');p=WORK/rel;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as out:out.write(raw)
 need(read(p)==raw,'Staged file changed.');inventory.append({'path':rel.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
for p in sorted(ROOT.rglob('*')):
 if p.is_dir():need(not p.is_symlink(),'Unexpected symlink cache directory.');continue
 if '__pycache__' in p.parts or p.suffix=='.pyc':continue
 rel=p.relative_to(ROOT);raw=read(p);observed[p]=raw
 need(not p.name.endswith(('.tar','.tar.gz')) and '.app' not in p.parts,'Transport bundle must not enter compact evidence.')
 if rel.parts[0] in {'downloads','extracted','official-attempt-logs'}:
  dest='originals/'+rel.as_posix();kind='original-authenticated-evidence'
 elif rel.parts[0]=='exact-source':dest=rel.as_posix();kind='exact-git-source'
 else:dest='provenance/'+rel.as_posix();kind='original-collector-record-or-api-snapshot'
 put(dest,raw,kind,{'originalPath':str(p),'sourceCommit':SOURCE,'runID':RUN})
for f in bound_files:put('exact-source/preflight-candidate/'+f['path'],f['raw'],'exact-git-source',{'commit':SOURCE,'gitPath':f['path'],'binding':'Matches the candidate hash preserved by the local preflight.'})
put('provenance/local-preflight-binding.json',enc({'sourceCommit':SOURCE,'preflightSourceParent':preflight['sourceParent'],'preflightCandidateFilesMatchCommit':True,'files':[{k:v for k,v in f.items() if k!='raw'} for f in bound_files],'sdkTypecheck':False,'sourceOfTestCounts':'Original local preflight/log; this retention did not rerun product tests.'}),'derived-preflight-binding',{'sourceCommit':SOURCE})
review_paths=['pdf-appearance-2f3134a-factual-log-review.json','pdf-appearance-2f3134a-factual-log-review.md','pdf-appearance-2f-independent-review.json','pdf-appearance-2f-independent-review.md','pdf-appearance-2f-customization-observations.json','pdf-appearance-checker-scope.md','pdf-appearance-remaining-scope.md']
for name in review_paths:
 p=Path('/tmp')/name;put('reviews/'+name,read(p),'derived-independent-or-preparation-review',{'originalPath':str(p),'note':'Original temporal wording preserved; preparation notes are not relabeled as final success.'})
for name in ['pdf-appearance-local-preflight.json','pdf-appearance-scripts-local.log','pdf-appearance-catalog-preservation.json']:
 p=Path('/tmp')/name;put('local-preflight/'+name,read(p),'derived-local-preflight',{'originalPath':str(p),'sourceCommitBinding':'Candidate hashes compared independently to 2f3134a; no SDK/runtime approval from Linux syntax.'})
for name in ['pdf_collect_appearance.py','pdf_collect_appearance.casefold-before.py','pdf_collect_appearance.README.md','test_pdf_collect_appearance_offline.py','pdf-appearance-collector-offline-tests.json','pdf-appearance-collector-offline-tests.log','pdf-appearance-collector-casefold.diff','pdf-appearance-2f3134a-config.json','pdf-appearance-2f3134a-config.draft.json','pdf-appearance-2f3134a-collector.log','pdf-appearance-2f3134a-collector-resumed.log','pdf_review_appearance2f_facts.py','pdf_stage_appearance2f_evidence.py']:
 p=Path('/tmp')/name;put('collector-history/'+name,read(p),'derived-collector-and-incident-record',{'originalPath':str(p),'notProductOrArtifactCode':True})
retained={'schemaVersion':1,'sourceCommit':SOURCE,'controllerCommit':SOURCE,'runID':RUN,'attempt':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'runConclusion':'failure','jobs':JOBS,'sourceCompilePackSucceeded':True,'targetRestoreSucceeded':True,'appearanceObserverPassed':False,'visualReviewPassed':False,'nativeContrastMeasurementsCompleted':0,'nativeChecksPerSystem':{'passed':8,'failed':4},'originalPNGCount':14,'artifactInventories':{'PDF-appearance-sdk26':15,'PDF-appearance-same-binary-xcode27':14},'fullNativeWorkflowDispatched':False,'fullNativeWorkflowStatusSource':'Coordinator instruction; focal workflow is the only run retained here.','installationApproved':False,'completeApplicationApproved':False,'deliveryAllowed':False,'sameManifestBytesAcrossSystems':True,'transferArtifactNotDownloaded':True,'tarOrAppRetained':False,'visualReview':{'productApproved':False,'source':'reviews/pdf-appearance-2f-independent-review.json','separateFinding':visual['separateVisualFinding'],'scope':'14 original images reviewed by agent, 12 workspace toolbar states legible in the displayed regions; not a native measurement or full interaction approval.'},'collectorIncident':{'firstCollectionStoppedOnLegitimateUppercaseNames':True,'approvedCasefoldCollisionFixApplied':True,'offlineMethodsPassed':18,'eachArtifactDownloadedOnce':True,'productFailureCauseNotInferredFromCollectorBug':True},'localPreflight':{'swiftSyntaxFiles':preflight['swiftFiles'],'SDKTypecheck':preflight['sdkTypecheck'],'scriptsMethods':preflight['scriptsMethods'],'scriptsPassed':preflight['scriptsPassed'],'scriptsMacSkips':preflight['scriptsMacSkips']},'historical37VisualRejectionUnchanged':True,'approvalTransferredFromPriorSource':False}
put('retention-summary.json',enc(retained),'derived-failed-focal-retention-summary',{'sourceCommit':SOURCE,'runID':RUN})
readme=f'''# Aparência 2f3134a — focal reprovado, sem aprovação de entrega

Fonte e controlador `{SOURCE}`, run `{RUN}`, tentativa 1. **Compilação/empacotamento SDK 26 e restauração no macOS 27 passaram; o observador de aparência e a validação falharam nos dois sistemas. Foram concluídas zero medidas nativas de contraste. A revisão visual focal também foi reprovada pelos controles ausentes em Personalização no SDK 26. O workflow nativo completo não foi despachado para esta fonte.** Nenhum resultado deste diretório aprova instalação, pacote completo ou entrega.

## Resultado preservado

| Etapa / evidência | Estado |
|---|---|
| Build/pack SDK 26.5, bundle mínimo | Aprovados pelas etapas originais |
| Restore/verificação do mesmo bundle no macOS 27 | Aprovados pelas etapas originais |
| Capturas originais | Sete por sistema, 14 PNG preservados e íntegros |
| Reportes/recibos de aparência | `failed` nos dois sistemas |
| Checks nativos | 8 true e 4 false em cada sistema |
| Medidas de contraste | Zero; `measurements=[]` nos seis toolbarReports de cada sistema |
| Revisão visual focal | Reprovada: Espaçamento e Restaurar ausentes no SDK 26; causa/duração desconhecidas |
| Matriz completa / instalação / entrega | Não aprovadas; matriz completa não despachada |

Os mesmos quatro checks falharam: janela real, contraste dos três controles, preservação das identidades anexadas e retorno dos controles após personalização. Os erros dizem que os controles diretos esperados não foram localizados; `workspaceToolbarProviderCount=0` e `controls=[]`. Esses registros não demonstram que o contraste numérico passou ou falhou. As snapshots/logs contêm janela 29 em cada processo; esse número não sobrepõe os checks falhos. A revisão factual não estabeleceu causa do aplicativo.

A revisão visual independente abriu os 14 originais: não observou os símbolos brancos sobre branco nos 12 estados de workspace examinados. **Separadamente, Espaçamento e Restaurar não aparecem na captura de Personalização do SDK 26**, enquanto aparecem na do mesmo bundle em27. As imagens e observações por arquivo estão preservadas; isso não aprova cliques, animações, interação completa ou VoiceOver. O resultado permanece reprovado.

Os dois manifestos do bundle são byte idênticos: SHA-256 `9aceea76b8efd1cccf43abf6469b2ba1ed885220a35daa4756024331a7c9a937`. Declaram tar `0aa4044312b4486c7b712fac98ffb035cbffa08f8788729f9bada1d74e635868`, 5.104.036 bytes. Esse tar/app mínimo não foi baixado, extraído, executado nem retido pelo coletor local; o vínculo é dado pelas APIs, etapas e metadados originais. Bundle mínimo não é instalador completo.

## Originais e proveniência

- `originals/downloads/`: dois ZIPs de evidência autenticados pelo digest GitHub e o ZIP oficial de logs. Não contém ZIP do bundle de transporte.
- `originals/extracted/`: inventários originais de 15 e 14 arquivos, incluindo PNGs, reportes de falha, manifestos e logs.
- `originals/official-attempt-logs/`: dois logs completos agregados; os logs por etapa permanecem no ZIP. O endpoint oficial não fornece digest independente; o SHA identifica os bytes obtidos pela API autenticada.
- `provenance/`: configuração, estados, snapshots API antes/depois, recibos do coletor e vínculo do preflight local ao commit exato.
- `exact-source/`: seleção do Git exato usada por validadores/diagnósticos, além dos oito arquivos de candidato cujos hashes constam do preflight. Não é o arquivo completo do aplicativo.
- `reviews/`: revisão factual, revisão visual independente e notas de preparação preservadas com sua redação temporal original.
- `local-preflight/`: sintaxe Swift de 90 arquivos (sem typecheck do SDK), scripts: 171 métodos, 164 PASS e 7 skips no Mac e preservação do catálogo. Isso não substitui o ensaio macOS real reprovado.
- `collector-history/`: código antes/depois, configuração, diff, resultados dos 18 testes offline e logs do incidente de coleta.

## Incidente local do coletor, separado do produto

A primeira coleta autenticou o ZIP26, mas recusou seus nomes `PDF-appearance…` porque comparava erroneamente o nome literal com a chave de colisão normalizada em minúsculas. A correção autorizada usa normalização somente para detectar colisões, preserva nomes literais/allowlist/caminhos e mantém as verificações ZIP. Passaram 18 testes offline, incluindo maiúsculas legítimas e colisão por caixa. O ZIP26 foi reutilizado; cada artefato foi baixado uma única vez. O erro não foi apagado nem apresentado como falha do aplicativo.

## Integridade e limites

`inventory.json` registra caminho, bytes, SHA-256, natureza e origem de cada arquivo; `SHA256SUMS` também cobre o índice. Execute `sha256sum -c SHA256SUMS` aqui para conferência local. Os14 PNG também tiveram CRC/raster e fingerprints comparados aos frames, sem retoque ou execução do aplicativo. Nenhum arquivo de produto foi alterado por esta retenção.

A reprovação visual histórica de 37f5b65 permanece. Sua aprovação nativa não foi transferida a 2f3134a, e as observações desta fonte não aprovam uma futura correção. Não há medição de M4 físico/Neural Engine/energia, prova de modelo de IA real, serviços de produção, VoiceOver humano ou aplicativo definitivo sem erros.
'''
put('README.md',readme.encode(),'derived-failed-focal-readme',{'sourceCommit':SOURCE,'runID':RUN})
index={'schemaVersion':1,'sourceCommit':SOURCE,'runID':RUN,'status':'failed-appearance-diagnostic-retention','deliveryAllowed':False,'scope':'All retained files except inventory.json and SHA256SUMS; SHA256SUMS also covers inventory.json.','files':sorted(inventory,key=lambda x:x['path'])}
raw=enc(index);(WORK/'inventory.json').write_bytes(raw);checks=sorted([(i['path'],i['sha256']) for i in inventory]+[('inventory.json',sha(raw))]);(WORK/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in checks))
for i in inventory:need(matches(read(WORK/i['path']),i),'Final retained hash mismatch.')
for p,raw in observed.items():need(read(p)==raw,'Original collector file changed during retention.')
need(read(visual_path)==visual_raw,'Frozen visual report changed.')
need(not list(WORK.rglob('*.tar.gz')) and not list(WORK.rglob('*.tar')) and not list(WORK.rglob('*.app')),'Unexpected app/tar retained.')
os.rename(WORK,DEST);files=[p for p in DEST.rglob('*') if p.is_file()]
print(json.dumps({'stage':str(DEST),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(read(DEST/'inventory.json')),'runConclusion':'failure','nativeContrastMeasurements':0,'deliveryAllowed':False},indent=2))
