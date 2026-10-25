#!/usr/bin/env python3
"""Offline retention of already authenticated SMALL native artifacts; no product approval."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, io, json, os, stat, subprocess, zipfile
ROOT=Path('/workspace/.cache/pdf-native-37f5b65')
DEST=Path('/tmp/pdf37-native-evidence-staging')
REPO=Path('/workspace/PDF-')
SHA='37f5b65e35a9f70c716cfcd64db7ba69837f5c21'
RUN=40239018570
JOBS={'macos-26':121306620661,'xcode-27':121306620477}
MAX_SMALL=16*1024*1024

def check(ok,message):
    if not ok: raise ValueError(message)

def read(path,limit=MAX_SMALL):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        first=os.fstat(stream.fileno())
        check(stat.S_ISREG(first.st_mode) and first.st_uid==os.getuid() and first.st_size<=limit,'Expected bounded owned regular file: '+str(path))
        raw=stream.read(limit+1);last=os.fstat(stream.fileno())
        check((first.st_dev,first.st_ino,first.st_size,first.st_mtime_ns,first.st_ctime_ns)==(last.st_dev,last.st_ino,len(raw),last.st_mtime_ns,last.st_ctime_ns),'Source changed during read: '+str(path))
        return raw

def digest(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

check(not os.path.lexists(DEST),'Staging already exists; do not overwrite prior evidence.')
configraw=read(ROOT/'collector-configuration.json');config=json.loads(configraw)
check(config['sourceCommit']==SHA and config['nativeRunID']==RUN and config['runAttempt']==1 and config['jobIDs']==JOBS and config['outputDirectory']==str(ROOT),'Collector configuration mismatch.')
state_raw=read(ROOT/'collector-artifact-state.json');state=json.loads(state_raw)
check(state['runID']==RUN and state['sourceSHA']==SHA and state['runAttempt']==1,'Artifact state identity mismatch.')
runraw=read(ROOT/'collector-run.json');run=json.loads(runraw)
check(run['id']==RUN and run['head_sha']==SHA and run['run_attempt']==1,'Run identity mismatch.')
availraw=read(ROOT/'collector-available-artifacts.json');available=json.loads(availraw)
expected={name+'-'+runner for name in ('PDF-Apple-Vision-capability','PDF-local-AI','PDF-macOS-benchmark','PDF-macOS-preview','PDF-native-checks','PDF-window-lifecycle') for runner in JOBS}
check(len(available)==12 and {a['name'] for a in available}==expected,'Expected exactly 12 small artifact families.')
DEST.mkdir(mode=0o700)
records=[]

def put(rel,raw,kind,origin):
    rel=Path(rel)
    check(not rel.is_absolute() and '..' not in rel.parts,'Unsafe destination path.')
    target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:
        stream.write(raw)
    check(read(target)==raw,'Retained file changed.')
    records.append({'path':rel.as_posix(),'bytes':len(raw),'sha256':digest(raw),'kind':kind,'origin':origin})

artifact_records=[]
for a in sorted(available,key=lambda a:a['name']):
    e=state['attempts'][str(a['id'])]
    runner=next(r for r in JOBS if a['name'].endswith('-'+r))
    check(e['name']==a['name'] and e['runID']==RUN and e['sourceSHA']==SHA and e['runAttempt']==1 and e['jobID']==JOBS[runner]==a['jobID'],'Artifact binding mismatch.')
    check(e['downloaded'] and e['extractionVerified'] and e['inventoryComplete'] and not e['missingRequiredFiles'],'Artifact not previously authenticated and complete.')
    archive=ROOT/'downloads'/f'{a["id"]}.zip';raw=read(archive)
    check(len(raw)==a['bytes']==e['archiveBytes'] and digest(raw)==a['digest'].removeprefix('sha256:')==e['archiveSHA256'] and a['digest']==e['githubDigest'],'Original ZIP digest mismatch.')
    membermap={f['name']:f for f in e['files']};check(len(membermap)==len(e['files']),'Duplicate extracted inventory.')
    group=ROOT/'extracted'/a['name'];actual={p.name for p in group.iterdir()}
    check(actual==set(membermap),'Extracted inventory differs.')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        info=z.infolist();check(len(info)==len(membermap) and {i.filename for i in info}==set(membermap),'ZIP/extraction inventory mismatch.')
        for i in info:
            check(i.filename==i.orig_filename and '/' not in i.filename and '\\' not in i.filename and not i.is_dir() and i.file_size<=MAX_SMALL,'Unexpected original ZIP member.')
            f=membermap[i.filename];member=z.read(i);local=read(group/i.filename)
            check(len(member)==f['bytes'] and digest(member)==f['sha256'] and member==local,'ZIP/extracted content mismatch.')
            put('originals/extracted/'+a['name']+'/'+i.filename,local,'original-artifact-member',{'artifactID':a['id'],'artifactName':a['name'],'jobID':a['jobID'],'zipMember':i.filename})
    put('originals/downloads/'+archive.name,raw,'original-artifact-zip',{'artifactID':a['id'],'artifactName':a['name'],'jobID':a['jobID'],'githubDigest':a['digest']})
    artifact_records.append({'artifactID':a['id'],'name':a['name'],'jobID':a['jobID'],'archiveBytes':len(raw),'archiveSHA256':digest(raw),'members':len(membermap),'expandedBytes':sum(f['bytes'] for f in membermap.values()),'originalZipRehashed':True,'membersRehashedAndComparedToOriginalZip':True})

collector_names=['collector-artifact-state.json','collector-artifacts.json','collector-available-artifacts.json','collector-configuration.json','collector-jobs.json','collector-run.json','collector-standalone-native-counts.json','collector-summary.json','collector-validators.json']
retained_raw={'collector-artifact-state.json':state_raw,'collector-available-artifacts.json':availraw,'collector-configuration.json':configraw,'collector-run.json':runraw}
for name in collector_names:
    raw=retained_raw.get(name)
    if raw is None:raw=read(ROOT/name)
    put('provenance/'+name,raw,'original-collector-record',{'path':str(ROOT/name)})
for directory in sorted((ROOT/'snapshots').iterdir()):
    check(directory.is_dir() and not directory.is_symlink(),'Unsafe snapshot directory.')
    if not directory.name[0].isdigit():continue # Excludes pending full run logs/binary collectors.
    for p in sorted(directory.iterdir()):
        check(p.name in {'run.json','jobs.json','artifacts.json','PDF-macOS-preview-macos-26.validation.log','PDF-macOS-preview-xcode-27.validation.log'},'Unexpected small-collector snapshot member.')
        raw=read(p)
        if p.name=='run.json':
            v=json.loads(raw);check(v['id']==RUN and v['head_sha']==SHA and v['run_attempt']==1,'Snapshot source differs.')
        put('provenance/snapshots/'+directory.name+'/'+p.name,raw,'original-api-snapshot' if p.suffix=='.json' else 'derived-validator-log',{'path':str(p)})

# Reproduction code below is an exact selection from Git, not the complete source archive.
source_paths=[
'.github/workflows/macos.yml','.github/workflows/portable-compatibility.yml',
'diagnostics/delivery_archives.py','scripts/check_preview_artifacts.py','scripts/check_accessibility_report.py','scripts/check_window_lifecycle.py',
'scripts/prepare-window-audit-bundle.py','scripts/run-with-timeout.py','scripts/install-mac.sh','scripts/PDF-Info.plist',
'scripts/package-source.sh','scripts/check_runtime.py','scripts/compare_benchmarks.py',
'Sources/PDF/MacSmokeTests.swift','Sources/PDF/WindowSceneLifecycleAudit.swift','Sources/PDF/MacPreview.swift','Sources/PDF/WorkspaceLifecycle.swift','Sources/PDF/PDFApp.swift',
'Package.swift']
git_env=dict(os.environ,GIT_NO_LAZY_FETCH='1')
source_records=[]
for name in source_paths:
    raw=subprocess.check_output(['git','show',SHA+':'+name],cwd=REPO,env=git_env)
    check(len(raw)<=MAX_SMALL,'Source file too large.')
    put('exact-source/'+name,raw,'exact-git-source',{'sourceCommit':SHA,'gitPath':name})
    source_records.append({'gitPath':name,'bytes':len(raw),'sha256':digest(raw)})
for v in json.loads(read(ROOT/'collector-validators.json')):
    check(v['sourceSHA']==SHA,'Collector validator source mismatch.')
    source=next(x for x in source_records if x['gitPath']==v['path'])
    check(source['sha256']==v['sha256'],'Collector validator does not match exact Git source.')
commit=subprocess.check_output(['git','cat-file','commit',SHA],cwd=REPO,env=git_env)
put('exact-source/git-commit-object.txt',commit,'exact-git-commit-object',{'sourceCommit':SHA})
put('exact-source/selected-source-manifest.json',encode({'sourceCommit':SHA,'completeSourceArchiveRetained':False,'files':source_records}),'derived-selected-source-index',{'method':'git show exact source commit; no lazy network fetch'})

for runner,label in [('macos-26','macos26'),('xcode-27','macos27')]:
    report=Path('/tmp')/f'pdf-native-37f5b65-visual-review-{label}.json';v=json.loads(read(report))
    check(v['sourceCommit']==SHA and v['nativeRunID']==RUN and len(v['images'])==33,'Visual review identity/count mismatch.')
    for item in v['images']:
        name=item.get('filename',item.get('name'));original=ROOT/'extracted'/('PDF-macOS-preview-'+runner)/name
        check(digest(read(original))==item['sha256'],'Visual report image hash mismatch.')
    for suffix in ['json','md']:
        p=report.with_suffix('.'+suffix);put('reviews/'+p.name,read(p),'derived-independent-visual-review',{'path':str(p),'runner':runner,'sourceCommit':SHA})

for p in [Path('/tmp/pdf_collect_scene_candidate.py'),Path('/tmp/pdf_stage_native37_evidence.py')]:
    put('collection-tools/'+p.name,read(p),'derived-offline-collection-code',{'path':str(p),'notPartOfGitSource':True})

counts={'authenticatedSmallArtifactZIPs':len(artifact_records),'artifactMemberFiles':sum(a['members'] for a in artifact_records),'artifactPNGFiles':sum(1 for r in records if r['kind']=='original-artifact-member' and r['path'].endswith('.png')),'exactSelectedGitFiles':len(source_paths),'independentVisualReports':4,'fullRunLogsCopied':False,'sourceTarCopied':False,'largeBinaryZipOrTarCopied':False}
summary={'schemaVersion':1,'draft':True,'sourceCommit':SHA,'runID':RUN,'runAttempt':1,'createdAtUTC':datetime.now(timezone.utc).isoformat(),'capturedRunState':{'status':run['status'],'conclusion':run['conclusion']},'finalRunConclusion':'PLACEHOLDER_FINAL_RUN','finalTestCounts':'PLACEHOLDER_FINAL_COUNTS','completeNativeMatrixApproved':False,'crossOSApproved':False,'installationApproved':False,'counts':counts,'artifacts':artifact_records,'scope':'Offline compact retention of the 12 authenticated small artifacts and exact selected Git source. No complete run logs, source tar or binary archives copied. No network call and no artifact code executed.'}
put('staging-summary.json',encode(summary),'derived-draft-summary',{'sourceCommit':SHA,'runID':RUN})
readme=f'''# Evidência nativa 37f5b65 — staging provisório

Fonte `{SHA}`, execução `{RUN}`, tentativa 1.

**Rascunho: final do run = PLACEHOLDER_FINAL_RUN; contagens finais de testes = PLACEHOLDER_FINAL_COUNTS.** O snapshot preservado informa `{run['status']}` / `{run['conclusion']}`. Não afirma aprovação da matriz, instalador, teste cruzado, M4 físico ou experiência humana.

Este diretório foi montado offline a partir dos arquivos pequenos já autenticados em `{ROOT}`. Não há dados herdados da fonte 81769db. Todos os {counts['authenticatedSmallArtifactZIPs']} ZIPs pequenos foram novamente comparados ao digest GitHub registrado; os {counts['artifactMemberFiles']} membros foram comparados byte a byte com seus ZIPs e hashes registrados. Os 66 PNG atuais estão preservados sem edição.

- `originals/downloads/`: os 12 ZIPs originais pequenos do GitHub, por ID de artefato.
- `originals/extracted/`: membros originais com nomes e agrupamentos dos artefatos, inclusive recibos e logs pequenos pertencentes a esses artefatos.
- `provenance/`: registros do coletor e snapshots API originais. Caminhos absolutos dentro dos JSON permanecem como recebidos, referentes ao ambiente de coleta.
- `exact-source/`: seleção de {len(source_paths)} arquivos obtidos do commit Git exato, incluindo workflows, validadores, instalação e diagnósticos nativos. Não é o arquivo de fonte completo; manifesto próprio informa a seleção.
- `reviews/`: revisões visuais independentes dos 33 PNG de cada sistema, com limites explícitos sobre interações, rolagem, animação e VoiceOver.
- `collection-tools/`: coletor e montador de staging como ferramentas locais derivadas; não são código do commit de produto.
- `inventory.json` e `SHA256SUMS`: caminhos, tamanho, hashes, natureza e origem de cada arquivo retido. Os índices de integridade não são assinaturas nem substituem a autenticação da origem.

O relatório de ciclo de janela é evidência específica: apresentação automática/restauração são deliberadamente desativadas no diagnóstico; a etapa inicial usa bundle mínimo e a etapa posterior usa o aplicativo instalado. Não apresenta o bundle mínimo como instalador aprovado. Os hashes de executável nos recibos são afirmações do workflow, ainda não rechecados aqui contra um tar binário.

Não foram copiados o tar de fonte, os ZIPs/tars binários grandes, os logs completos do run ou sua análise ainda pendente. Os logs pequenos de preview/native-checks/lifecycle foram mantidos porque integram os 12 artefatos autenticados. A revisão terminal e contagens finais serão acrescentadas somente após autorização/auditoria. Este staging não contém o aplicativo instalável.

Para conferir os arquivos retidos localmente: `sha256sum -c SHA256SUMS` a partir deste diretório. A API fornece o digest dos ZIPs de artefato registrado nos snapshots; `staging-summary.json` liga os IDs aos arquivos preservados. Nenhum código extraído dos artefatos foi executado.
'''
put('README.md',readme.encode(),'derived-draft-readme',{'sourceCommit':SHA,'runID':RUN})
index={'schemaVersion':1,'sourceCommit':SHA,'runID':RUN,'draft':True,'scope':'All retained files except inventory.json and SHA256SUMS to avoid self-reference. SHA256SUMS covers inventory.json as well.','files':sorted(records,key=lambda r:r['path'])}
index_raw=encode(index)
(DEST/'inventory.json').write_bytes(index_raw)
checks=sorted([(r['path'],r['sha256']) for r in records]+[('inventory.json',digest(index_raw))])
(DEST/'SHA256SUMS').write_text(''.join(sha+'  '+path+'\n' for path,sha in checks))
# Ensure the source identity/state records used to bind artifacts were not replaced during staging.
for name,raw in retained_raw.items():check(read(ROOT/name)==raw,'Collector snapshot changed while staging; stage must be reviewed: '+name)
all_files=[p for p in DEST.rglob('*') if p.is_file()]
print(json.dumps({'stage':str(DEST),'files':len(all_files),'bytes':sum(p.stat().st_size for p in all_files),'counts':counts,'capturedRunStatus':run['status'],'capturedRunConclusion':run['conclusion'],'draft':True},indent=2))
