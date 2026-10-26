#!/usr/bin/env python3
"""Preserve small failed/dirty packaging evidence; no package generation or extraction."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,re,stat
SOURCE='9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb'
DEST=Path('/tmp/pdf-source-package-9d78ab9-evidence-staging');WORK=Path(str(DEST)+'.building')
CAT=Path('/tmp/pdf-source-size-review-retention.json')
observed={}
def need(v,message):
 if not v:raise ValueError(message)
def read(p,cap=128*1024):
 p=Path(p)
 with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
  a=os.fstat(f.fileno());need(stat.S_ISREG(a.st_mode) and a.st_uid==os.getuid() and a.st_size<=cap,'Bounded regular file required.');raw=f.read(cap+1);b=os.fstat(f.fileno());need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,len(raw),b.st_mtime_ns,b.st_ctime_ns),'File changed.')
 if p in observed:need(observed[p]==raw,'Original changed since earlier read.')
 observed[p]=raw;return raw
def sha(raw):return hashlib.sha256(raw).hexdigest()
def enc(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def load(p):return json.loads(read(p))
need(not os.path.lexists(DEST) and not os.path.lexists(WORK),'Do not overwrite evidence.')
cat=load(CAT)
need(cat['baseCommit']==SOURCE and cat['newNativeRunApproved'] is False and cat['releaseApproved'] is False,'Catalog identity/scope differs.')
expected={'pdf-source-9d78ab9-preflight.log','pdf-source-size-review-9d78ab9.log','pdf-source-size-review-9d78ab9.json','pdf-source-size-review-dirty-gate.json','pdf-source-limits-installation-tests.log','pdf-source-limits-archives-tests.log','pdf-source-limits-delivery-tests.log'}
need(len(cat['files'])==7 and {Path(r['path']).name for r in cat['files']}==expected,'Unexpected catalog inventory.')
for r in cat['files']:
 p=Path(r['path']);need(p==Path('/tmp')/p.name,'Original outside declared small-file directory.');raw=read(p);need(len(raw)==r['bytes'] and sha(raw)==r['sha256'],'Catalog bytes/hash differ: '+str(p))
measurement=load('/tmp/pdf-source-size-review-9d78ab9.json');gate=load('/tmp/pdf-source-size-review-dirty-gate.json')
need(measurement['baseCommit']==SOURCE and measurement['workingTreeDirty'] is True and measurement['futureSourceCommitSelected'] is False and measurement['releaseApproved'] is False and measurement['nativeExecuted'] is False and measurement['networkExecuted'] is False,'Dirty preflight identity/scope differs.')
need(gate==measurement['deliveryRefusedDirtyTreeAfterSizeChecks'] and gate['expectedDirtyTreeGateRefused'] is True and gate['releaseApproved'] is False and gate['message']=='Source build identity or clean-tree evidence differs.','Dirty-tree refusal differs.')
root_failure=read('/tmp/pdf-source-9d78ab9-preflight.log').decode();need(root_failure=='Os fontes excedem os limites do pacote de instalação.\n','Root original failure differs.')
producer_log=read('/tmp/pdf-source-size-review-9d78ab9.log').decode()
counts=re.search(r'Arquivos: (\d+)\nCarga: (\d+); TAR: (\d+); gzip: (\d+) bytes',producer_log);need(counts is not None,'Producer count record missing.')
file_count,payload,tar_bytes,gzip_bytes=map(int,counts.groups())
need((file_count,payload,tar_bytes,gzip_bytes)==(1508,147879150,149350400,77212676) and measurement['members']==1510 and measurement['payloadBytes']==payload and measurement['uncompressedTarBytes']==tar_bytes and measurement['archive']['bytes']==gzip_bytes,'Producer count mismatch.')
need(measurement['archive']['sha256'] in producer_log and measurement['archive']['path'] in producer_log,'Producer archive reference differs.')
suite_counts=[]
for r in measurement['tests']:
 raw=read(r['path']);need(len(raw)==r['bytes'] and sha(raw)==r['sha256'],'Test log differs.')
 found=re.findall(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',raw.decode());need(found==[str(r['passed'])],'Test summary differs.');suite_counts.append({'name':r['name'],'passed':r['passed'],'log':Path(r['path']).name})
need([r['passed'] for r in suite_counts]==[18,18,16] and sum(r['passed'] for r in suite_counts)==measurement['validationTotal']==52,'Expected52 packaging tests.')
# Stream-hash the already existing referenced archive only; never retain, open as TAR or execute it.
p=Path(measurement['archive']['path']);digest=hashlib.sha256()
with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
 a=os.fstat(f.fileno());need(stat.S_ISREG(a.st_mode) and a.st_size==gzip_bytes and a.st_size<=100*1024*1024,'Unexpected archive size/type.')
 total=0
 while True:
  chunk=f.read(1024*1024)
  if not chunk:break
  total+=len(chunk);digest.update(chunk)
 b=os.fstat(f.fileno());need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,total,b.st_mtime_ns,b.st_ctime_ns),'Archive changed while hashing.')
need(digest.hexdigest()==measurement['archive']['sha256'],'Referenced archive digest differs.')
current_sources=[]
for r in measurement['changedFiles']:
 p=Path('/workspace/PDF-')/r['path'];raw=read(p);need(len(raw)==r['bytes'] and sha(raw)==r['sha256'],'Measured dirty-source file changed: '+r['path']);current_sources.append({'path':r['path'],'bytes':len(raw),'sha256':sha(raw),'matchedMeasuredWorkingTree':True})
review={'schemaVersion':1,'reviewedAtUTC':datetime.now(timezone.utc).isoformat(),'scope':'Small offline retention of original size refusal and later dirty-tree preflight, not clean-package approval','baseCommit':SOURCE,'originalRootFailureLogPreserved':True,'originalFailureExitCodeNotRecordedInThisLog':True,'dirtyTreePreflightDistinctFromBaseCommitArtifact':True,'workingTreeDirty':True,'futureSourceCommitSelected':False,'reportedPayloadBytes':payload,'reportedUncompressedTarBytes':tar_bytes,'referencedArchive':measurement['archive'],'referencedArchiveRehashedByStreaming':True,'archiveNotCopiedOrParsedOrExecuted':True,'payloadFileCountInProducerLog':file_count,'memberCountReportedIncludingBuildInfoAndManifest':measurement['members'],'testCountsRecountedFromOriginalLogs':suite_counts,'totalLocalTestsPassed':52,'dirtyTreeDeliveryGuardRefused':True,'changedSourceFingerprintsRechecked':current_sources,'originalExtractionClaimRetainedFromAuthor':measurement['all1510MaterializedMembersMatchedOriginalBytes'],'extractionNotRerunByRetention':True,'nativeApprovalTransferred':False,'focalApprovalTransferred':False,'recoveryApprovalTransferred':False,'cleanCommitPackageApproved':False,'releaseApproved':False,'repositoryEdited':False,'networkExecuted':False,'limits':['The original failure log contains an error message, not a source archive or full process transcript.','The modified producer/consumer preflight used a dirty tree based on9d; it is not a distributable source identity.','The referenced77MB archive was only stream-hashed; no archive, extraction, checkout ZIP or full source tree is retained.','A future package from a clean commit requires its own separate provenance, validation and evidence.']}
WORK.mkdir(mode=0o700);inventory=[]
def put(name,raw,kind,origin):
 rel=Path(name);need(not rel.is_absolute() and '..' not in rel.parts,'Unsafe retention path.');p=WORK/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(raw)
 inventory.append({'path':rel.as_posix(),'bytes':len(raw),'sha256':sha(raw),'kind':kind,'origin':origin})
for r in cat['files']:
 p=Path(r['path']);put('originals/'+p.name,read(p),'original-log-or-frozen-derived-local-report',{'originalPath':str(p),'baseCommit':SOURCE,'scope':'Original size failure or dirty-tree preflight as stated inside each file.'})
put('provenance/'+CAT.name,read(CAT),'frozen-author-retention-catalog',{'originalPath':str(CAT)})
put('review.json',enc(review),'derived-retention-integrity-review',{'baseCommit':SOURCE})
put('collection-tools/pdf_stage_source_package9d_evidence.py',read('/tmp/pdf_stage_source_package9d_evidence.py'),'retention-script',{'originalPath':'/tmp/pdf_stage_source_package9d_evidence.py'})
md=f'''# Pacote fonte9d78ab9 — falha original e preflight local de árvore suja

Referência base `{SOURCE}`. **Esta retenção não aprova um pacote distribuível.** O log original do root registra recusa por limite de tamanho. Depois, o produtor e consumidores modificados foram exercitados numa árvore suja baseada em9d; o novo limite permitiu a inspeção local, mas a guarda de identidade/árvore limpa continuou recusando entrega. Um pacote futuro gerado de commit limpo terá evidência separada.

| Evidência | Resultado preservado |
|---|---|
| Log original do root |`Os fontes excedem os limites do pacote de instalação.` |
| Preflight modificado |Árvore suja; não representa o commit base sem modificações |
| Carga reportada |147.879.150 bytes |
| TAR descomprimido reportado |149.350.400 bytes |
| gzip referenciado |77.212.676 bytes, SHA `{measurement['archive']['sha256']}` |
| Contagem |1.508 arquivos de carga;1.510 membros incluindo BUILD-INFO.json e manifesto |
| Testes locais |18 instalação +18 arquivos +16 entrega =52 PASS |
| Guarda de entrega |Recusou `Source build identity or clean-tree evidence differs.` |
| Aprovação de pacote limpo/entrega |Não |

Os novos limites registrados no preflight são240MiB para a carga,256MiB para gzip/TAR expandido,272MiB para ZIP de transporte,32MiB por arquivo e10.000 membros. O JSON original contém valores em bytes, margens, hashes dos sete arquivos modificados e o resultado do extrator. A afirmação de que os1.510 membros materializados coincidem com os originais pertence à revisão do autor; esta retenção não repetiu extração ou geração de pacote.

Os sete arquivos pequenos do catálogo foram reconferidos por tamanho/SHA, e os52 testes foram recontados nos três logs originais. O TAR já existente foi somente lido em blocos para conferir seu SHA; **não foi copiado, aberto como TAR, extraído ou executado**. Os hashes atuais dos sete arquivos modificados coincidem com os da medição congelada. Nenhum arquivo de produto foi editado.

`originals/` conserva o log de falha e os logs/JSON congelados; `provenance/` conserva o catálogo do autor; `review.json` distingue verificações desta retenção das alegações dos relatórios originais. O log da falha original tem56 bytes e não registra por si só exit code ou transcript completo. Não se apresentou a geração suja como artefato limpo do commit9d.

Não há TAR77MB, extração, ZIP contendo checkout ou árvore de fontes aqui. Isso evita incorporar o próprio checkout novamente às evidências e inflar artificialmente os pacotes. A aprovação do focal de aparência9d não aprova este pacote, a recuperação ou a instalação; nenhuma aprovação foi transferida.

`inventory.json` registra bytes/SHA/origem. `SHA256SUMS` cobre os arquivos e o índice; confira com `sha256sum -c SHA256SUMS`.
'''
put('README.md',md.encode(),'derived-dirty-preflight-scope-readme',{'baseCommit':SOURCE})
index={'schemaVersion':1,'baseCommit':SOURCE,'scope':'failed-original-and-dirty-preflight-small-retention','releaseApproved':False,'files':sorted(inventory,key=lambda r:r['path']),'inventoryExcludes':['inventory.json','SHA256SUMS']};raw=enc(index);(WORK/'inventory.json').write_bytes(raw)
checks=sorted([(r['path'],r['sha256']) for r in inventory]+[('inventory.json',sha(raw))]);(WORK/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in checks))
for r in inventory:
 v=read(WORK/r['path']);need(len(v)==r['bytes'] and sha(v)==r['sha256'],'Retained file differs.')
need({p.relative_to(WORK).as_posix() for p in WORK.rglob('*') if p.is_file()}=={r['path'] for r in inventory}|{'inventory.json','SHA256SUMS'},'Retention inventory not closed.')
for p,v in list(observed.items()):need(read(p)==v,'Original changed during retention.')
need(not list(WORK.rglob('*.zip')) and not list(WORK.rglob('*.tar')) and not list(WORK.rglob('*.gz')),'Archive must not be retained.')
os.rename(WORK,DEST);files=[p for p in DEST.rglob('*') if p.is_file()]
print(json.dumps({'stage':str(DEST),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'inventorySHA256':sha(raw),'sourceBase':SOURCE,'workingTreeDirty':True,'localTestsPassed':52,'releaseApproved':False,'archiveRetained':False},indent=2))
