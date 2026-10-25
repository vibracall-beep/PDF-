#!/usr/bin/env python3
"""Offline final compact native retention, after terminal log review and binary validation.
No network, large TAR extraction, product writes, or global product approval.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, io, json, os, stat, subprocess, zipfile
ROOT=Path('/workspace/.cache/pdf-native-37f5b65')
STAGE=Path('/tmp/pdf37-native-evidence-staging')
NEXT=Path('/tmp/pdf37-native-evidence-staging.finalizing')
BACKUP=Path('/tmp/pdf37-native-evidence-staging.provisional-backup')
REPO=Path('/workspace/PDF-')
SHA='37f5b65e35a9f70c716cfcd64db7ba69837f5c21'
RUN=40239018570
JOBS={'macos-26':121306620661,'xcode-27':121306620477}
LIMIT=64*1024*1024

def require(ok,msg):
    if not ok:raise ValueError(msg)

def read(p,limit=LIMIT):
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as s:
        a=os.fstat(s.fileno());require(stat.S_ISREG(a.st_mode) and a.st_uid==os.getuid() and a.st_size<=limit,'Bounded regular file required: '+str(p))
        raw=s.read(limit+1);b=os.fstat(s.fileno())
        require((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,len(raw),b.st_mtime_ns,b.st_ctime_ns),'File changed during read: '+str(p))
        return raw

def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def load(p):return json.loads(read(p))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reviewed-log-json-sha256',required=True,help='Final hash confirmed by audit_documentation after its review completes')
    args=parser.parse_args()
    require(not os.path.lexists(NEXT) and not os.path.lexists(BACKUP),'Do not overwrite a prior finalization or provisional backup.')
    require(STAGE.is_dir() and not STAGE.is_symlink(),'Original provisional staging required.')
    config=load(ROOT/'collector-configuration.json')
    require(config=={'schemaVersion':1,'sourceCommit':SHA,'nativeRunID':RUN,'runAttempt':1,'jobIDs':JOBS,'outputDirectory':str(ROOT)},'Configuration differs.')
    run=load(ROOT/'collector-run.json');jobs=load(ROOT/'collector-jobs.json')
    require(run['id']==RUN and run['head_sha']==SHA and run['run_attempt']==1 and run['status']=='completed' and run['conclusion']=='success','Final native run not successful.')
    require(jobs['total_count']==2 and len(jobs['jobs'])==2,'Unexpected native job inventory.')
    for runner,ident in JOBS.items():
        found=[j for j in jobs['jobs'] if j['id']==ident]
        require(len(found)==1 and found[0]['head_sha']==SHA and found[0]['run_id']==RUN and found[0]['run_attempt']==1 and found[0]['status']=='completed' and found[0]['conclusion']=='success','Final native job not successful.')
    log_review_path=Path('/tmp/pdf-native-37f5b65-full-log-review.json');lograw=read(log_review_path)
    require(sha(lograw)==args.reviewed_log_json_sha256,'Final log review hash differs from reviewer-confirmed bytes.')
    logs=json.loads(lograw)
    log_provenance=load(Path('/tmp/pdf-native-37f5b65-full-log-provenance.json'))
    require(log_provenance['sourceCommit']==SHA and log_provenance['runID']==RUN and log_provenance['conclusion']=='success','Log provenance identity differs.')
    for group in ['metadataOriginals','aggregateLogs','derivedReviewAndCollector']:
        for record in log_provenance[group]:
            value=read(Path(record['path']));require(len(value)==record['bytes'] and sha(value)==record['sha256'],'Reviewed log provenance hash mismatch.')
    require(logs['sourceSHA']==SHA and logs['runID']==RUN and logs['attempt']==1 and logs['sourceConclusion']=='success' and logs['evidenceIsCompleteTerminalAttempt'],'Final log review source/status differs.')
    require(len(logs['jobs'])==2 and {j['jobID'] for j in logs['jobs']}==set(JOBS.values()),'Log review jobs differ.')
    for j in logs['jobs']:
        require(j['jobConclusion']=='success' and not j['reviewIssues'] and not j['credentialLikePatternsObserved'] and not j['signedURLPatternsObserved'],'Final log review has unresolved issues or sensitive-pattern review required.')
        require(j['native']['expectedNineExecutionsObserved'] and j['native']['startPassMultisetEqual'] and j['native']['distinctPassed']==44,'Native counts differ.')
        require(j['pythonCasesIncludingSkips']==720 and j['pythonPassed']==719 and j['pythonSkipped']==1,'Python counts changed; review required.')
    binary=load(ROOT/'collector-binary-downloads.json');bs=load(ROOT/'collector-binary-summary.json')
    require(binary['schemaVersion']==1 and binary['configuration']==config,'Binary record configuration differs.')
    require(bs['sourceSHA']==SHA and bs['runID']==RUN and bs['runAttempt']==1 and bs['exactRunAndBothJobsPassed'] and bs['binaryArtifacts']==2 and not bs['binaryTarsExtracted'],'Complete binary validation not yet available.')
    records=list(binary['attempts'].values())
    require(len(records)==2 and {r['name'] for r in records}=={'PDF-binary-validated-'+r for r in JOBS},'Binary inventory differs.')
    for r in records:
        require(r['sourceSHA']==SHA and r['runID']==RUN and r['runAttempt']==1 and r['jobID'] in JOBS.values() and r['downloaded'] and r['validationReportVerified'] and not r.get('validationError') and not r.get('downloadError') and r['tar']['manifestMatchedEveryFile'] and not r['tar']['tarExtracted'],'Binary validation pending or inconsistent.')
    small=load(ROOT/'collector-artifact-state.json');available_all=load(ROOT/'collector-available-artifacts.json')
    expected_small={name+'-'+runner for name in ('PDF-Apple-Vision-capability','PDF-local-AI','PDF-macOS-benchmark','PDF-macOS-preview','PDF-native-checks','PDF-window-lifecycle') for runner in JOBS}|{'PDF-source-macos-26','PDF-source-ocr-compatibility-xcode-27'}
    expected_binary={'PDF-binary-validated-'+runner for runner in JOBS}
    require(len(available_all)==16 and {a['name'] for a in available_all}==expected_small|expected_binary,'Final API artifact inventory differs.')
    available=[a for a in available_all if a['name'] in expected_small]
    for a in available_all:
        if a['name'] in expected_binary:
            matching=[r for r in records if r['id']==a['id'] and r['name']==a['name'] and r['archiveBytes']==a['bytes'] and r['githubDigest']==a['digest'] and r['jobID']==a['jobID']]
            require(len(matching)==1,'Final API/binary collector artifact binding differs.')
    require(small['runID']==RUN and small['sourceSHA']==SHA and small['runAttempt']==1 and len(available)==14,'Small/source evidence state differs.')
    oldindex=load(STAGE/'inventory.json');require(oldindex['sourceCommit']==SHA and oldindex['runID']==RUN and oldindex['draft'],'Provisional index identity differs.')
    oldraw={}
    for r in oldindex['files']:
        raw=read(STAGE/r['path']);require(len(raw)==r['bytes'] and sha(raw)==r['sha256'],'Provisional retained bytes changed: '+r['path']);oldraw[r['path']]=raw
    require(len(list(STAGE.rglob('*.png')))==66,'Provisional PNG inventory differs.')
    NEXT.mkdir(mode=0o700);inventory=[]
    def put(rel,raw,kind,origin):
        p=Path(rel);require(not p.is_absolute() and '..' not in p.parts,'Unsafe staged path.')
        target=NEXT/p;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as out:out.write(raw)
        require(read(target)==raw,'Copied bytes changed.')
        inventory.append({'path':p.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
    # Retain immutable originals/reviews/source and preserve mutable provisional records separately.
    for r in oldindex['files']:
        path=r['path']
        if path.startswith('provenance/') or path in {'README.md','staging-summary.json'}:
            destination='provenance/provisional-stage/'+path
        else:destination=path
        put(destination,oldraw[path],r['kind'],{**r['origin'],'provisionalRecordRetained':destination!=path})
    for name in ['inventory.json','SHA256SUMS']:
        put('provenance/provisional-stage/'+name,read(STAGE/name),'historical-provisional-index',{'note':'Paths in this historical index refer to the original provisional layout, not the final layout; final integrity uses top-level inventory/SHA256SUMS.'})
    # Preserve current final collector/API snapshots. Never copy huge downloads by enumeration.
    topnames=['collector-artifact-state.json','collector-artifacts.json','collector-available-artifacts.json','collector-configuration.json','collector-jobs.json','collector-run.json','collector-standalone-native-counts.json','collector-summary.json','collector-validators.json','collector-binary-downloads.json','collector-binary-summary.json','collector-binary-validators.json','binary-gate-artifacts.json','binary-gate-jobs.json','binary-gate-run.json','collector-counts-complete-logs.json']
    snapshot_raw={}
    for name in topnames:
        raw=read(ROOT/name);snapshot_raw[name]=raw
        put('provenance/'+name,raw,'original-final-collector-record',{'path':str(ROOT/name)})
    for family in ['snapshots','binary-snapshots']:
        for p in sorted((ROOT/family).rglob('*')):
            if p.is_dir():require(not p.is_symlink(),'Symlink snapshot directory.');continue
            require(p.suffix in {'.json','.log'},'Unexpected snapshot type.')
            raw=read(p)
            put('provenance/'+str(p.relative_to(ROOT)),raw,'original-api-snapshot' if p.suffix=='.json' else 'derived-validator-log',{'path':str(p)})
    artifact_summary=[];excluded=[]
    for a in sorted(available,key=lambda a:a['name']):
        r=small['attempts'][str(a['id'])]
        require(r['name']==a['name'] and r['runID']==RUN and r['sourceSHA']==SHA and r['downloaded'] and r['extractionVerified'] and r['inventoryComplete'] and not r['missingRequiredFiles'],'Authenticated artifact required.')
        is_source=a['name'] in {'PDF-source-macos-26','PDF-source-ocr-compatibility-xcode-27'}
        if not is_source:
            require(any(x['path']=='originals/downloads/'+str(a['id'])+'.zip' and x['sha256']==r['archiveSHA256'] for x in inventory),'Retained small ZIP differs from final state.')
            artifact_summary.append({'artifactID':a['id'],'name':a['name'],'archiveRetained':True,'retainedMembers':len(r['files'])});continue
        require(r.get('sourceArchiveChecksumVerified') is True and len(r['files'])==5,'Source archive authentication incomplete.')
        archive=ROOT/'downloads'/f'{a["id"]}.zip';raw=read(archive)
        require(len(raw)==a['bytes']==r['archiveBytes'] and sha(raw)==r['archiveSHA256']==a['digest'].removeprefix('sha256:'),'Source ZIP digest differs.')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            expected={f['name']:f for f in r['files']}
            require(len(z.infolist())==5 and set(z.namelist())==set(expected),'Source ZIP member inventory differs.')
            for name,f in expected.items():
                if name=='PDF-source.tar.gz':
                    excluded.append({'artifactID':a['id'],'artifactName':a['name'],'member':name,'bytes':f['bytes'],'sha256':f['sha256'],'reason':'Source tar deliberately not retained; upstream authenticated record preserved.'});continue
                require(name in {'PDF-source.tar.gz.sha256','PDF-benchmark.json','PDF-local-ai.json','PDF-vision-audit.json'},'Unexpected source metadata name.')
                value=read(ROOT/'extracted'/a['name']/name)
                require(len(value)==f['bytes'] and sha(value)==f['sha256'] and z.read(name)==value,'Source metadata differs from original ZIP.')
                put('originals/extracted/'+a['name']+'/'+name,value,'original-source-artifact-metadata',{'artifactID':a['id'],'artifactName':a['name'],'zipSHA256':r['archiveSHA256'],'zipMember':name})
        excluded.append({'artifactID':a['id'],'name':archive.name,'bytes':len(raw),'sha256':sha(raw),'reason':'Source ZIP not retained because it contains the source tar.'})
        artifact_summary.append({'artifactID':a['id'],'name':a['name'],'archiveRetained':False,'retainedMembers':4})
    binary_summary=[]
    for r in records:
        require(len(r['files'])==4 and {f['name'] for f in r['files']}=={'PDF-arm64.tar.gz.sha256','distribution-manifest.json','distribution-validation.json','install-binary.sh'},'Expected four small binary metadata files.')
        for f in r['files']:
            value=read(ROOT/'extracted'/r['name']/f['name'])
            require(len(value)==f['bytes'] and sha(value)==f['sha256'],'Binary small metadata changed.')
            put('originals/extracted/'+r['name']+'/'+f['name'],value,'original-binary-artifact-metadata',{'artifactID':r['id'],'artifactName':r['name'],'zipSHA256':r['archiveSHA256'],'zipMember':f['name'],'comparisonScope':'Rehashed the small extracted file against the completed authenticated streaming collector; did not reopen or extract the large TAR.'})
        binary_summary.append({'artifactID':r['id'],'name':r['name'],'jobID':r['jobID'],'archiveBytes':r['archiveBytes'],'archiveSHA256':r['archiveSHA256'],'tar':r['tar'],'manifestSHA256':r['manifestSHA256'],'sourceInstaller':r['sourceInstaller'],'validationReportVerified':True,'archiveAndTarRetainedInCompactEvidence':False,'smallMetadataRehashed':True})
        excluded.append({'artifactID':r['id'],'name':str(r['id'])+'.zip','bytes':r['archiveBytes'],'sha256':r['archiveSHA256'],'tar':r['tar'],'reason':'Large binary ZIP/TAR deliberately omitted; no additional download or large-TAR extraction by retention.'})
    # Official full logs were authorized only after audit_documentation completed its review.
    archive=Path(logs['archive']['path']);raw=read(archive)
    require(len(raw)==logs['archive']['bytes'] and sha(raw)==logs['archive']['sha256'],'Official full log ZIP changed.')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        expected={m['name']:m for m in logs['zipMembers']}
        require(len(z.infolist())==len(expected)==logs['archive']['memberCount'] and set(z.namelist())==set(expected),'Full-log ZIP inventory differs.')
        for name,m in expected.items():
            value=z.read(name);require(len(value)==m['bytes'] and sha(value)==m['sha256'],'Official ZIP log member changed.')
        for j in logs['jobs']:
            info=j['fullLog'];value=read(Path(info['path']))
            require(len(value)==info['bytes'] and sha(value)==info['sha256'] and z.read(info['file'])==value,'Aggregate official log changed.')
            put('originals/full-run-logs/'+info['file'],value,'original-official-aggregate-log',{'runID':RUN,'jobID':j['jobID'],'zipMember':info['file']})
    put('originals/full-run-logs/'+archive.name,raw,'original-official-run-log-zip',{'runID':RUN,'endpoint':logs['officialEndpoint'],'upstreamDigestSupplied':False,'note':'SHA identifies received official endpoint bytes; the endpoint supplies no independent digest.'})
    # Exact extra validators/installer from product commit; existing selected-source manifest stays historical.
    git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1');extra=[]
    for path in ['diagnostics/portable_compatibility.py','scripts/install-binary.sh']:
        raw=subprocess.check_output(['git','show',SHA+':'+path],cwd=REPO,env=git_env)
        put('exact-source/'+path,raw,'exact-git-source',{'sourceCommit':SHA,'gitPath':path});extra.append({'gitPath':path,'bytes':len(raw),'sha256':sha(raw)})
    for v in load(ROOT/'collector-binary-validators.json'):
        require(v['sourceSHA']==SHA,'Binary validator source differs.')
        matched=next((x for x in inventory if x['path']=='exact-source/'+v['path']),None)
        require(matched and matched['sha256']==v['sha256'],'Binary source validator differs from exact Git retained bytes.')
    allsource=[{'gitPath':i['origin']['gitPath'],'bytes':i['bytes'],'sha256':i['sha256']} for i in inventory if i['kind']=='exact-git-source']
    put('exact-source/final-selected-source-manifest.json',enc({'sourceCommit':SHA,'completeSourceArchiveRetained':False,'files':allsource}),'derived-selected-source-index',{'sourceCommit':SHA})
    for p in [log_review_path,log_review_path.with_suffix('.md'),Path('/tmp/pdf37-final-scope-audit.json'),Path('/tmp/pdf37-final-scope-audit.md'),Path('/tmp/pdf37-delivery-control-final-review.md'),Path('/tmp/pdf37-full-logs-static-review.md'),Path('/tmp/pdf-native-37f5b65-full-log-provenance.json'),Path('/tmp/pdf37-install-storage-review.json')]:
        raw=read(p)
        if p.name.endswith('scope-audit.json'):require(json.loads(raw)['productCommit']==SHA,'Scope review source differs.')
        if p==log_review_path:require(raw==lograw,'Final log review changed.')
        put('reviews/'+p.name,raw,'derived-independent-review',{'path':str(p),'scopeNote':'Preserved original report; historical pending states inside earlier reviews remain as recorded, not rewritten to imply later approval.'})
    for p in [Path('/tmp/pdf_collect_scene_binary.py'),Path('/tmp/pdf_collect_37_logs.py'),Path('/tmp/pdf_finalize_native37_evidence.py'),Path('/tmp/pdf37_finalize_full_log_review.py')]:
        put('collection-tools/'+p.name,read(p),'derived-local-collection-code',{'path':str(p),'notPartOfGitSource':True})
    summary={'schemaVersion':2,'draft':False,'sourceCommit':SHA,'runID':RUN,'runAttempt':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'nativeMatrix':{'status':'completed','conclusion':'success','jobs':JOBS,'source':'Authenticated original terminal API snapshots and official complete attempt logs'},'pythonPerRunner':{j['runner']:{'methodsIncludingSkips':j['pythonCasesIncludingSkips'],'passed':j['pythonPassed'],'skipped':j['pythonSkipped']} for j in logs['jobs']},'nativePerRunner':{j['runner']:{'distinctGroups':44,'completeExecutions':9,'starts':j['native']['starts'],'passes':j['native']['passes']} for j in logs['jobs']},'crossOS':{'status':'in_progress','approved':False,'runID':40243611339,'jobID':121320462461,'controllerCommit':'e4f6c056058d3482b18cdcc24011ccdc96327004','dispatchReportedUTC':'2026-10-25T23:11:20Z','statusSource':'Root coordinator message; not independently queried by this offline staging tool'},'privateDelivery':{'status':'pending','approved':False},'completeApplicationApproved':False,'allRequestedFeaturesComplete':False,'authenticatedSmallAndSourceArtifacts':artifact_summary,'binaries':binary_summary,'excludedLargeFiles':excluded,'retentionScope':'12 small original artifact ZIPs plus original full-run log ZIP; four small source metadata files and four small binary metadata files per runner; no source ZIP/TAR or binary ZIP/TAR retained. Exact original and derived records explicitly separated.','provisionalHistory':'Earlier draft provenance/README/index are preserved under provenance/provisional-stage; complete unchanged provisional staging also retained outside this final directory as .provisional-backup.'}
    put('staging-summary.json',enc(summary),'derived-final-native-summary',{'sourceCommit':SHA,'runID':RUN})
    rows=[]
    for j in logs['jobs']:rows.append(f"| {j['runner']} | {j['pythonCasesIncludingSkips']} | {j['pythonPassed']} | {j['pythonSkipped']} | 44 × 9 = {j['native']['passes']} |")
    binary_rows=[]
    for r in binary_summary:binary_rows.append(f"| {r['name']} | {r['artifactID']} | `{r['tar']['sha256']}` | {r['tar']['bytes']} |")
    readme=f'''# Evidência nativa — 37f5b65

Fonte `{SHA}`, matriz `{RUN}`, tentativa 1. **Matriz nativa concluída com sucesso nos dois sistemas. Teste cruzado do mesmo binário em curso e entrega privada ainda pendente neste snapshot. O run cross `40243611339`, job `121320462461`, foi informado pela coordenação como despachado às 23:11:20 UTC, com controlador `e4f6c056058d3482b18cdcc24011ccdc96327004`; este montador offline não consultou sua API nem o aprovou.** Isso não afirma que todas as solicitações foram integralmente implementadas nem aprova M4 físico, IA real, serviços externos, VoiceOver humano ou ausência universal de erros.

## Contagens verificadas nos logs oficiais completos

| Runner | Métodos Python, incluindo skips | Aprovados | Skips | Grupos nativos |
|---|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

Cada runner executou installer/scripts 150 métodos (149 PASS, 1 skip), core 510 PASS e integração 60 PASS. O skip é o ensaio Linux `/dev/full`; grupos nativos repetidos não são contados como novas ferramentas. A distribuição das nove execuções foi 2 + 1 + 1 + 5 nas etapas registradas. Avisos, diagnósticos negativos PDFKit/CoreGraphics e probes App Intents estão classificados na revisão original, sem apagar os logs.

## Pacotes autenticados, não incluídos neste diretório

| Artefato | ID | SHA-256 do tar medido em stream | Bytes do tar |
|---|---:|---|---:|
'''+ '\n'.join(binary_rows)+'''

O coletor binário concluiu a comparação de cada arquivo do tar com o manifesto, limites/storage, fonte e instalador exatos. Esta retenção rehashou os quatro metadados pequenos por pacote, preservando o recibo dessa medição; não reabriu nem extraiu o tar grande e não faz novo download. O checksum isolado não substitui a autenticação registrada.

## Organização e reprodução da evidência

- `originals/downloads/`: os 12 ZIPs originais pequenos autenticados pelo digest GitHub, incluindo os dois grupos de lifecycle.
- `originals/extracted/`: 106 membros dos grupos pequenos, quatro metadados de fonte por runner e quatro metadados de binário por runner; nomes e bytes originais preservados.
- `originals/full-run-logs/`: ZIP oficial completo e os dois logs agregados. O endpoint de logs não fornece digest independente; o SHA identifica os bytes recebidos, com CRC/hashes de todos os membros verificados.
- `provenance/`: API final, snapshots históricos, coletores e recibos binários. `provisional-stage/` preserva os registros anteriores sem reescrever seu estado `in_progress`; seus índices históricos referem-se ao layout provisório.
- `exact-source/`: seleção de arquivos do Git exato de produto; `final-selected-source-manifest.json` registra a seleção. Não é o tar completo de fonte.
- `reviews/`: revisões visuais independentes dos 66 PNG, auditoria estática de 71 ferramentas, controle de entrega e logs completos. Relatórios anteriores mantêm seus estados temporais próprios; revisão estática do controle não aprova sua futura execução.
- `collection-tools/`: coletores e montadores locais derivados, identificados separadamente do código de produto.
- `inventory.json` e `SHA256SUMS`: tamanho, SHA-256, natureza e origem de cada arquivo retido. Verificação local: `sha256sum -c SHA256SUMS` a partir deste diretório.

O diagnóstico de janela tem escopo específico: apresentação automática e restauração são deliberadamente desativadas. Seu bundle inicial mínimo não é tratado como instalador; existe também auditoria no aplicativo completo instalado. A montagem desta evidência não equipara hashes early/installed ao binário empacotado quando assinatura/empacotamento mudam legitimamente os bytes.

Não foram retidos tar/ZIP de fonte, tar/ZIP binários grandes ou payload instalável. As ausências, hashes e tamanhos constam de `staging-summary.json`. Caminhos absolutos dentro dos relatórios originais apontam ao ambiente de coleta e são preservados como recebidos. Nenhuma evidência de 81769db foi usada em substituição à fonte atual.

Capturas estáticas e árvores AX não aprovam cliques, arraste, animações, rolagem completa ou VoiceOver humano. O OCR mostrado usa tesseract/inglês em exemplo português e tem erros de reconhecimento registrados; M4 físico, Neural Engine, energia, IA real elegível e integrações externas continuam exigindo evidência própria. Os limites de implementação estão na auditoria de escopo preservada.
'''
    put('README.md',readme.encode(),'derived-final-native-readme',{'sourceCommit':SHA,'runID':RUN})
    index={'schemaVersion':2,'sourceCommit':SHA,'runID':RUN,'draft':False,'scope':'All retained files except inventory.json and SHA256SUMS to avoid self-reference; SHA256SUMS covers inventory.json too.','files':sorted(inventory,key=lambda i:i['path'])}
    raw=enc(index);(NEXT/'inventory.json').write_bytes(raw)
    checks=sorted([(r['path'],r['sha256']) for r in inventory]+[('inventory.json',sha(raw))])
    (NEXT/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in checks))
    for r in inventory:
        value=read(NEXT/r['path']);require(len(value)==r['bytes'] and sha(value)==r['sha256'],'Final retained inventory mismatch.')
    require(not list(NEXT.rglob('*.tar')) and not list(NEXT.rglob('*.tar.gz')) and len(list((NEXT/'originals/downloads').glob('*.zip')))==12,'Large archive leaked into compact staging.')
    # Ensure collector records, final audit and old index stayed stable during construction.
    for name,raw in snapshot_raw.items():require(read(ROOT/name)==raw,'Collector changed during finalization; do not publish stage: '+name)
    require(read(log_review_path)==lograw,'Log review changed during finalization.')
    require(load(STAGE/'inventory.json')==oldindex,'Provisional evidence changed concurrently.')
    os.rename(STAGE,BACKUP);os.rename(NEXT,STAGE)
    files=[p for p in STAGE.rglob('*') if p.is_file()]
    print(json.dumps({'stage':str(STAGE),'provisionalBackup':str(BACKUP),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(read(STAGE/'inventory.json')),'sourceSHA':SHA,'nativeConclusion':'success','cross':'in_progress','privateDelivery':'pending'},indent=2))

if __name__=='__main__':main()
