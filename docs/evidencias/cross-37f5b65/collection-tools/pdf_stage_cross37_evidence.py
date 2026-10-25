#!/usr/bin/env python3
"""Offline compact retention of cross37 evidence, explicitly visually rejected."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,io,json,os,stat,subprocess,zipfile
ROOT=Path('/workspace/.cache/pdf-cross-37f5b65')
NATIVE=Path('/workspace/.cache/pdf-native-37f5b65')
DEST=Path('/tmp/pdf-cross37-evidence-staging')
WORK=Path('/tmp/pdf-cross37-evidence-staging.building')
REPO=Path('/workspace/PDF-')
SOURCE='37f5b65e35a9f70c716cfcd64db7ba69837f5c21'
CONTROL='e4f6c056058d3482b18cdcc24011ccdc96327004'
NATIVE_RUN=40239018570;CROSS_RUN=40243611339;JOB=121320462461
TAR='641d66d3c4bd68ad8074d906e6dd9c3c18ef946292da2d9512541948db52c4a4'
DARK='13dcfebf3a4ec930d6ee42360004ec4da89072da1d2b0e39a64249ad9aa0387a'
MAX=64*1024*1024

def require(ok,msg):
    if not ok:raise ValueError(msg)

def read(p,cap=MAX):
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        a=os.fstat(f.fileno());require(stat.S_ISREG(a.st_mode) and a.st_uid==os.getuid() and a.st_size<=cap,'Expected bounded owned regular file: '+str(p))
        raw=f.read(cap+1);b=os.fstat(f.fileno());require((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,len(raw),b.st_mtime_ns,b.st_ctime_ns),'File changed: '+str(p));return raw

def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def load(p):return json.loads(read(p))
def measured(raw,r):return len(raw)==r['bytes'] and sha(raw)==r['sha256']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--visual-report-sha256',required=True)
    parser.add_argument('--logs-report-sha256',required=True)
    args=parser.parse_args()
    require(not os.path.lexists(DEST) and not os.path.lexists(WORK),'Refuse replacing existing evidence.')
    cfg=load(ROOT/'collector-configuration.json');summary=load(ROOT/'collector-summary.json');artifacts=load(ROOT/'collector-artifact-state.json')
    expected={'schemaVersion':1,'sourceCommit':SOURCE,'nativeRunID':NATIVE_RUN,'nativeAttempt':1,'nativeRoot':str(NATIVE),'archiveSHA256':TAR,'crossRunID':CROSS_RUN,'crossAttempt':1,'controlCommit':CONTROL,'crossJobID':JOB,'outputDirectory':str(ROOT)}
    require(cfg==expected,'Cross configuration differs.')
    require(summary['sourceCommit']==SOURCE and summary['sourceRunID']==NATIVE_RUN and summary['crossRunID']==CROSS_RUN and summary['controllerCommit']==CONTROL and summary['crossJobID']==JOB and summary['archiveSHA256']==TAR and summary['runStatus']=='completed' and summary['runConclusion']=='success' and summary['completeNativeAndCrossGatesPassed'] and summary['receiptVerified'] and summary['lifecycleReceiptVerified'],'Automated gate/source identity mismatch.')
    run=load(ROOT/'collector-cross-run.json');jobs=load(ROOT/'collector-cross-jobs.json')
    require(run['id']==CROSS_RUN and run['head_sha']==CONTROL and run['run_attempt']==1 and run['status']=='completed' and run['conclusion']=='success','Terminal cross API differs.')
    require(jobs['total_count']==1 and len(jobs['jobs'])==1 and jobs['jobs'][0]['id']==JOB and jobs['jobs'][0]['head_sha']==CONTROL and jobs['jobs'][0]['run_id']==CROSS_RUN and jobs['jobs'][0]['run_attempt']==1 and jobs['jobs'][0]['status']=='completed' and jobs['jobs'][0]['conclusion']=='success','Cross job differs.')
    vrpath=Path('/tmp/pdf-cross-37f5b65-visual-review.json');vrraw=read(vrpath);visual=json.loads(vrraw)
    require(sha(vrraw)==args.visual_report_sha256 and visual['sourceCommit']==SOURCE and visual['crossRunID']==CROSS_RUN and visual['crossJobID']==JOB and visual['controllerCommit']==CONTROL and visual['archiveSHA256']==TAR,'Frozen visual report binding/hash differs.')
    require(visual['visualApproval'] is False and visual['completeApplicationApproved'] is False and visual['inspectedPNGCount']==33 and visual['allPNGsOpenedIndividually'],'Expected visually rejected review of all33 screenshots.')
    blockers=visual['confirmedVisualBlockers'];require(any(b['imageSHA256']==DARK and b['id']=='CROSS-DARK-TOOLBAR-CONTRAST' for b in blockers),'Required confirmed original dark-toolbar finding absent.')
    lrpath=Path('/tmp/pdf-cross-37f5b65-full-log-review.json');lrraw=read(lrpath);logs=json.loads(lrraw)
    require(sha(lrraw)==args.logs_report_sha256 and logs['sourceCommit']==SOURCE and logs['controllerCommit']==CONTROL and logs['runID']==CROSS_RUN and logs['attempt']==1 and logs['jobID']==JOB and logs['APIConclusion']=='success','Frozen full-log review differs.')
    require(logs['automatedCrossProtocolPassed'] is True and logs['releaseReady'] is False and logs['privateDeliveryApprovedByThisReport'] is False and logs['independentVisualReview']['visualApproval'] is False,'Final review must preserve the visual delivery blocker.')
    lp=load(Path('/tmp/pdf-cross-37f5b65-full-log-provenance.json'))
    require(lp['sourceCommit']==SOURCE and lp['controllerCommit']==CONTROL and lp['runID']==CROSS_RUN,'Log provenance origin differs.')
    for group in ['outputs','analysisSources','metadataOriginals','visualReviewReports']:
        for record in lp[group]:
            require(measured(read(Path(record['path'])),record),'Frozen provenance record changed.')
    require(logs['native']['distinctGroups']==44 and logs['native']['starts']==132 and logs['native']['passes']==132 and logs['native']['repetitionsPerGroup']==3 and logs['native']['startPassMultisetEqual'] and logs['native']['perStepCountersMatchAggregate'] and not logs['fatalMarkers'],'Cross automated counts/errors differ.')
    require(len(artifacts)==2 and {a['name'] for a in artifacts}=={'PDF-cross-platform-validated','PDF-cross-lifecycle'},'Cross artifact inventory differs.')
    WORK.mkdir(mode=0o700);inventory=[];source_snapshots={}
    def put(rel,raw,kind,origin):
        path=Path(rel);require(not path.is_absolute() and '..' not in path.parts,'Unsafe target path.')
        target=WORK/path;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw)
        require(read(target)==raw,'Retained bytes changed.')
        inventory.append({'path':path.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
    retained_artifacts=[]
    for a in artifacts:
        require((a['runID'],a['jobID'],a['controllerCommit'],a['sourceCommit'])==(CROSS_RUN,JOB,CONTROL,SOURCE) and not a['missingRequiredFiles'],'Artifact origin differs.')
        count=50 if a['name']=='PDF-cross-platform-validated' else 3
        require(len(a['files'])==count,'Unexpected original artifact count.')
        require(a['sourceBinaryAndGUIReceiptVerified'] if count==50 else a['lifecycleReceiptVerified'],'Required artifact receipt was not validated.')
        zpath=ROOT/'downloads'/f'{a["artifactID"]}.zip';raw=read(zpath)
        require(measured(raw,a['archive']) and a['githubDigest']=='sha256:'+sha(raw),'Original artifact ZIP digest differs.')
        group=ROOT/'extracted'/a['name'];require({p.name for p in group.iterdir()}==set(a['files']),'Extracted artifact inventory differs.')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            require(len(z.infolist())==count and set(z.namelist())==set(a['files']),'Original ZIP inventory differs.')
            for info in z.infolist():
                name=info.filename;require(name==info.orig_filename and '/' not in name and '\\' not in name and not info.is_dir() and info.file_size<=MAX,'Unexpected ZIP member.')
                value=read(group/name);require(measured(value,a['files'][name]) and value==z.read(name),'ZIP/extracted content differs.')
                put('originals/extracted/'+a['name']+'/'+name,value,'original-cross-artifact-member',{'artifactID':a['artifactID'],'artifactName':a['name'],'runID':CROSS_RUN,'jobID':JOB,'zipMember':name})
        put('originals/downloads/'+zpath.name,raw,'original-cross-artifact-zip',{'artifactID':a['artifactID'],'artifactName':a['name'],'runID':CROSS_RUN,'githubDigest':a['githubDigest']})
        retained_artifacts.append({'artifactID':a['artifactID'],'name':a['name'],'bytes':len(raw),'sha256':sha(raw),'members':count,'originalZipAndMembersReverified':True})
    for image in visual['images']:
        name=image.get('name',image.get('filename'));value=read(ROOT/'extracted/PDF-cross-platform-validated'/name)
        require(sha(value)==image['sha256'],'Original PNG differs from frozen visual report.')
    require(sha(read(ROOT/'extracted/PDF-cross-platform-validated/PDF-preview.escuro.png'))==DARK,'Confirmed dark PNG differs.')
    for p in sorted(ROOT.glob('collector-*.json')):
        raw=read(p);source_snapshots[p]=raw
        put('provenance/'+p.name,raw,'original-cross-collector-record',{'path':str(p)})
    for p in sorted((ROOT/'snapshots').rglob('*')):
        if p.is_dir():require(not p.is_symlink(),'Symlink snapshot directory.');continue
        require(p.suffix in {'.json','.log'},'Unexpected cross snapshot file.')
        raw=read(p);source_snapshots[p]=raw
        put('provenance/'+str(p.relative_to(ROOT)),raw,'original-collector-api-snapshot',{'path':str(p)})
    git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1');git_records=[]
    snap=Path(summary['snapshotDirectory'])
    for family,commit,label in [('application-source',SOURCE,'application'),('controller-source',CONTROL,'controller')]:
        manifest=load(snap/('application-files.json' if label=='application' else 'controller-files.json'))
        for path,m in manifest.items():
            value=read(ROOT/family/path);exact=subprocess.check_output(['git','show',commit+':'+path],cwd=REPO,env=git_env)
            require(value==exact and measured(value,m),'Cached source differs from exact commit: '+path)
            put('exact-source/'+label+'/'+path,value,'exact-git-source',{'commit':commit,'gitPath':path,'role':label})
            git_records.append({'role':label,'commit':commit,'gitPath':path,'bytes':len(value),'sha256':sha(value)})
        extras=['.github/workflows/portable-compatibility.yml']
        if label=='application':extras+=['Sources/PDF/PDFApp.swift','Sources/PDF/WorkspaceViews.swift','Sources/PDF/AppearancePreferences.swift','Sources/PDF/MacPreview.swift','Sources/PDF/WindowSceneLifecycleAudit.swift','scripts/install-binary.sh']
        for path in extras:
            value=subprocess.check_output(['git','show',commit+':'+path],cwd=REPO,env=git_env)
            put('exact-source/'+label+'/'+path,value,'exact-git-source',{'commit':commit,'gitPath':path,'role':label})
            git_records.append({'role':label,'commit':commit,'gitPath':path,'bytes':len(value),'sha256':sha(value)})
        value=subprocess.check_output(['git','cat-file','commit',commit],cwd=REPO,env=git_env)
        put('exact-source/'+label+'/git-commit-object.txt',value,'exact-git-commit-object',{'commit':commit,'role':label})
    put('exact-source/selected-source-manifest.json',enc({'applicationCommit':SOURCE,'controllerCommit':CONTROL,'completeSourceArchiveRetained':False,'files':git_records}),'derived-selected-source-index',{'method':'git show exact commit with lazy network fetch disabled; comparison against collector cached source'})
    # Retain only small native inputs, with their original authenticated records, not huge ZIP/TARs.
    bstate=load(NATIVE/'collector-binary-downloads.json');binary=bstate['attempts']['12617457782']
    require(binary['sourceSHA']==SOURCE and binary['runID']==NATIVE_RUN and binary['validationReportVerified'] and binary['tar']['sha256']==TAR and binary['tar']['manifestMatchedEveryFile'],'Native binary origin differs.')
    for item in binary['files']:
        require(item['name'] in {'PDF-arm64.tar.gz.sha256','distribution-manifest.json','distribution-validation.json','install-binary.sh'},'Unexpected binary input metadata.')
        value=read(ROOT/'native-inputs/binary-small'/item['name']);require(measured(value,item),'Small native binary input differs.')
        put('originals/native-inputs/binary-small/'+item['name'],value,'original-native-binary-metadata',{'sourceArtifactID':12617457782,'sourceRunID':NATIVE_RUN,'sourceCommit':SOURCE,'tarSHA256':TAR,'scope':'Small bytes rehashed against completed native streaming collector; large binary ZIP/TAR not reopened by stager.'})
    nstate=load(NATIVE/'collector-artifact-state.json');source=nstate['attempts']['12617342983']
    require(source['sourceSHA']==SOURCE and source['runID']==NATIVE_RUN and source['sourceArchiveChecksumVerified'],'Source artifact binding differs.')
    for item in source['files']:
        if item['name']=='PDF-source.tar.gz':continue
        require(item['name'] in {'PDF-source.tar.gz.sha256','PDF-benchmark.json','PDF-local-ai.json','PDF-vision-audit.json'},'Unexpected source input metadata.')
        value=read(ROOT/'native-inputs/source'/item['name']);require(measured(value,item),'Small source input metadata differs.')
        put('originals/native-inputs/source/'+item['name'],value,'original-native-source-metadata',{'sourceArtifactID':12617342983,'sourceRunID':NATIVE_RUN,'sourceCommit':SOURCE,'sourceTarNotRetained':True})
    for name in ['collector-binary-downloads.json','collector-binary-summary.json','collector-artifact-state.json']:
        put('provenance/native-binding/'+name,read(NATIVE/name),'original-native-collector-record',{'path':str(NATIVE/name),'scope':'Origin binding only; native37 success does not transfer visual approval to cross or future patches.'})
    official=logs['officialLogArchive'];zp=Path(official['path']);raw=read(zp)
    require(measured(raw,official) and sha(raw)==summary['originalRunLogs']['sha256'],'Official log ZIP differs.')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members={m['name']:m for m in logs['officialLogMembers']};require(len(z.infolist())==len(members)==official['memberCount'] and set(z.namelist())==set(members),'Official log ZIP inventory differs.')
        for name,m in members.items():require(measured(z.read(name),m),'Official log ZIP member differs.')
        aggregate=logs['fullJobLog'];p=Path(aggregate['path']);value=read(p)
        require(measured(value,aggregate) and z.read(p.name)==value,'Original full-job log differs.')
        put('originals/full-run-logs/'+p.name,value,'original-official-cross-job-log',{'runID':CROSS_RUN,'jobID':JOB,'zipMember':p.name})
    put('originals/full-run-logs/'+zp.name,raw,'original-official-cross-log-zip',{'runID':CROSS_RUN,'upstreamDigestProvided':False,'note':'Official authenticated endpoint, no independent upstream digest; hash identifies received bytes.'})
    report_paths=[vrpath,vrpath.with_suffix('.md'),lrpath,lrpath.with_suffix('.md'),Path('/tmp/pdf-cross-37f5b65-full-log-provenance.json'),Path('/tmp/pdf-cross37-dark-toolbar-pixels.json'),Path('/tmp/pdf-cross37-dark-toolbar-review.md')]
    for p in report_paths:
        value=read(p)
        if p==vrpath:require(value==vrraw,'Frozen visual report changed.')
        if p==lrpath:require(value==lrraw,'Frozen log report changed.')
        put('reviews/'+p.name,value,'derived-independent-review',{'path':str(p),'scope':'Preserved source-specific review; no future patch approval.'})
    for p in [Path('/tmp/pdf_collect_scene_cross.py'),Path('/tmp/pdf_collect_cross437.py'),Path('/tmp/pdf_count_cross437.py'),Path('/tmp/pdf_preserve_cross437.py'),Path('/tmp/pdf_collect_37_logs.py'),Path('/tmp/pdf_cross_37f5b65_visual_report.py'),Path('/tmp/pdf_stage_cross37_evidence.py'),Path('/tmp/pdf37_review_cross_logs.py'),Path('/tmp/pdf37_finalize_cross_log_review.py')]:
        require(p.is_file(),'Expected local collector/reviewer source missing: '+str(p))
        put('collection-tools/'+p.name,read(p),'derived-local-collection-review-code',{'path':str(p),'notProductSource':True})
    final={'schemaVersion':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'sourceCommit':SOURCE,'sourceRunID':NATIVE_RUN,'controllerCommit':CONTROL,'crossRunID':CROSS_RUN,'crossAttempt':1,'crossJobID':JOB,'archiveSHA256':TAR,'automatedNativeAndCrossChecksPassed':True,'visualReviewPassed':False,'visualBlockers':blockers,'deliveryAllowed':False,'privateDelivery':{'status':'not_performed_due_to_confirmed_visual_blocker','approved':False},'completeApplicationApproved':False,'approvalTransferredToFuturePatch':False,'originalNative37ApprovalChanged':False,'artifacts':retained_artifacts,'counts':{'originalArtifactFiles':53,'originalPNGs':33,'originalAXReports':7,'originalOCRFiles':2,'lifecycleFiles':3,'nativeGroups':44,'nativeExecutions':3,'nativeStarts':132,'nativePasses':132,'controllerPythonMethods':sum(s['cases'] for s in logs['controlPythonSuites'])},'excludedLargeFiles':[{'artifactID':12617457782,'binaryZIPBytes':binary['archiveBytes'],'binaryZIPSHA256':binary['archiveSHA256'],'tarBytes':binary['tar']['bytes'],'tarSHA256':TAR,'reason':'Binary ZIP/TAR not copied or extracted.'},{'artifactID':12617342983,'sourceZIPBytes':source['archiveBytes'],'sourceZIPSHA256':source['archiveSHA256'],'sourceTar':next(f for f in source['files'] if f['name']=='PDF-source.tar.gz'),'reason':'Source ZIP/TAR deliberately omitted; small source metadata preserved.'}],'limits':['Automated success does not imply visual approval.','Static PNG review does not establish click failure, causal mechanism or persistence after transitions.','Prior native37 success remains historical and is not transferred to any new patched source.','No M4 physical, Neural Engine/energy, human VoiceOver or production service approval.']}
    put('retention-summary.json',enc(final),'derived-cross-retention-summary',{'sourceCommit':SOURCE,'crossRunID':CROSS_RUN})
    readme=f'''# Cross 37f5b65 — checks automatizados aprovados, revisão visual reprovada

**Não entregar este pacote como aprovado.** O run cross `{CROSS_RUN}`, job `{JOB}`, concluiu com `success`, mas a revisão dos **33 PNG originais do binário instalado** confirmou um bloqueador visual: três controles da barra superior ficam quase brancos sobre cápsulas quase brancas no tema escuro. A aprovação visual é falsa e não houve entrega privada desta versão por esse motivo.

A evidência é do produto `{SOURCE}`, compilado na matriz `{NATIVE_RUN}` em macOS 26 e instalado sem recompilar em macOS 27.0.1. Controlador cross: `{CONTROL}`. Tar examinado: `{TAR}` ({binary['tar']['bytes']} bytes); seu ZIP/TAR grande não integra esta retenção compacta.

## Bloqueador confirmado no original

- Imagem: `originals/extracted/PDF-cross-platform-validated/PDF-preview.escuro.png`.
- SHA-256: `{DARK}`.
- Controles afetados: alternar barra lateral, paleta de comandos e personalização.
- A revisão confirma a legibilidade insuficiente na captura. Não estabelece a causa, falha de clique nem permanência após transições.
- Os diagnósticos de pixels e o relatório visual estão preservados em `reviews/`; valores de pixels não são certificados como medição formal de contraste WCAG.

O nome upstream `PDF-cross-platform-validated` e os flags automatizados verdadeiros foram preservados literalmente. Eles representam o contrato de instalação/recibos/PNG/AX/OCR verificado, **não** a aprovação visual posterior. O achado não foi apagado nem reclassificado como sucesso.

## Evidência automatizada preservada

- Dois ZIPs originais de artefatos: 50 arquivos GUI e 3 arquivos lifecycle; digests GitHub, CRC e bytes/hashes de todos os membros novamente conferidos.
- 33 PNG, 7 árvores AX, par OCR original, metadados/recibos GUI e lifecycle separado. A auditoria de janela reporta 12 checks; seu escopo artificial permanece descrito no original.
- Logs oficiais completos: 44 grupos nativos repetidos três vezes, 132 inícios/132 aprovações, multiconjuntos e soma por etapa iguais. Os 20 métodos Python (9 + 11) pertencem ao controlador. Os logs e sua revisão discriminam diagnósticos negativos e avisos.
- Fonte e controlador selecionados diretamente dos commits Git exatos, comparados com os bytes usados pelo coletor; manifestos separados registram a seleção, que não equivale ao tar completo de fonte.
- Quatro metadados pequenos do binário e quatro da fonte vinculam o instalador, manifesto e arquivo testado. A retenção não refez download nem extração do tar grande.

## Organização

`originals/downloads/` contém os dois ZIPs de artefato; `originals/extracted/` preserva os dois inventários sem acrescentar arquivos dentro deles. `originals/full-run-logs/` contém o ZIP oficial e o log agregado; o endpoint oficial não fornece digest independente, e o hash identifica os bytes recebidos. `provenance/` conserva APIs, recibos, snapshots e vínculos nativos. `exact-source/` separa produto e controlador. `reviews/` contém relatórios derivados e `collection-tools/` preserva os scripts locais, sem confundi-los com o produto.

`inventory.json` registra caminho, tamanho, SHA-256, natureza e origem. `SHA256SUMS` também cobre o índice: execute `sha256sum -c SHA256SUMS` neste diretório para conferir os bytes retidos. Caminhos absolutos nos registros originais apontam ao ambiente de coleta e permanecem intactos.

O sucesso nativo anterior da fonte 37f5b65 não foi alterado. Ele não apaga a reprovação visual deste teste cruzado e não serve como aprovação de uma futura correção: qualquer novo commit/pacote exige evidência própria. Nenhum teste humano com VoiceOver, benchmark M4 físico, energia/Neural Engine ou integração externa de produção é aprovado por este diretório.
'''
    put('README.md',readme.encode(),'derived-cross-retention-readme',{'sourceCommit':SOURCE,'crossRunID':CROSS_RUN})
    index={'schemaVersion':1,'sourceCommit':SOURCE,'controllerCommit':CONTROL,'crossRunID':CROSS_RUN,'visualApproval':False,'deliveryAllowed':False,'scope':'Every retained file except inventory.json and SHA256SUMS; SHA256SUMS also covers inventory.json.','files':sorted(inventory,key=lambda x:x['path'])}
    raw=enc(index);(WORK/'inventory.json').write_bytes(raw)
    hashes=sorted([(r['path'],r['sha256']) for r in inventory]+[('inventory.json',sha(raw))]);(WORK/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in hashes))
    for item in inventory:require(measured(read(WORK/item['path']),item),'Final compact hash mismatch.')
    for p,raw in source_snapshots.items():require(read(p)==raw,'Collector changed during retention.')
    require(read(vrpath)==vrraw and read(lrpath)==lrraw,'Frozen review changed during retention.')
    require(not list(WORK.rglob('*.tar.gz')) and not list(WORK.rglob('*.tar')),'Large TAR accidentally retained.')
    os.rename(WORK,DEST);files=[p for p in DEST.rglob('*') if p.is_file()]
    print(json.dumps({'stage':str(DEST),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(read(DEST/'inventory.json')),'automatedChecksPassed':True,'visualApproval':False,'deliveryAllowed':False},indent=2))

if __name__=='__main__':main()
