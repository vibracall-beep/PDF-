from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,re,subprocess
report=Path('/tmp/pdf-native-37f5b65-full-log-review.json');j=json.loads(report.read_text())
assert j['sourceConclusion']=='success' and j['sourceSHA']=='37f5b65e35a9f70c716cfcd64db7ba69837f5c21'
ansi=re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
def body(line):return re.sub(r'^\d{4}-\d\d-\d\dT\S+\s+','',ansi.sub('',line))
notes={
 'relocation-signature-warning':'install_name_tool informa invalidação durante relocação; o empacotador reassina código alterado e exige codesign --verify --deep --strict antes de publicar o manifesto. A etapa e o isolamento posteriores passaram; isso não é notarização.',
 'vision-deprecated-api':'usesCPUOnly está obsoleto no diagnóstico Vision; duas compilações repetem o mesmo sítio VisionFailureDiagnostics.swift:122.',
 'vision-deprecated-source-excerpt':'Repetição visual do aviso no trecho da linha de fonte, não outro sítio do compilador.',
 'qpdf-already-installed':'Homebrew informa que qpdf já estava instalado e atualizado.',
 'openjdk-not-globally-linked':'Homebrew instalou openjdk@21 sem link global porque outro openjdk já existia; as integrações que usam o runtime configurado passaram.',
 'pymupdf-swig-deprecation':'Depreciação do binding SWIG/PyMuPDF; as suítes registradas passaram.',
 'node-punycode-deprecation':'Aviso do runtime Node usado pelas ações de CI.',
 'node-url-parse-deprecation':'Aviso do runtime Node usado pelas ações de CI.',
 'node20-action-migration':'GitHub informa que ações configuradas para Node20 foram executadas em Node24.'}
for x in j['jobs']:
 raw=Path(x['fullLog']['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==x['fullLog']['sha256']
 lines=raw.decode().splitlines();classified=defaultdict(list)
 for i,line in enumerate(lines):
  t=body(line)
  if 'warning:' not in t.lower() and '##[warning]' not in t:continue
  if 'install_name_tool: warning: changes being made to the file will invalidate the code signature in:' in t:key='relocation-signature-warning'
  elif 'usesCPUOnly' in t and re.search(r'[^ /]+\.swift:\d+:\d+: warning:',t):key='vision-deprecated-api'
  elif 'usesCPUOnly' in t:key='vision-deprecated-source-excerpt'
  elif 'qpdf' in t and 'already installed and up-to-date' in t:key='qpdf-already-installed'
  elif 'openjdk@21 was installed but not linked because openjdk is already installed' in t:key='openjdk-not-globally-linked'
  elif 'swigvarlink' in t:key='pymupdf-swig-deprecation'
  elif 'punycode' in t:key='node-punycode-deprecation'
  elif 'url.parse()' in t:key='node-url-parse-deprecation'
  elif 'Node.js 20 is deprecated' in t:key='node20-action-migration'
  else:key='unclassified'
  classified[key].append({'line':i+1,'text':t})
 assert 'unclassified' not in classified,classified.get('unclassified')
 x.pop('otherWarningCounts')
 x['warningClassification']=[{'category':key,'occurrences':len(values),'lines':[v['line'] for v in values],'samples':values[:2],'interpretation':notes[key]} for key,values in sorted(classified.items())]
 x['windowLifecycleSuccessMarkers']=[i+1 for i,line in enumerate(lines) if body(line)=='PDF real WindowGroup lifecycle audit passed']
 x['successfulSourceInstallationMarkers']=[i+1 for i,line in enumerate(lines) if body(line).startswith('Instalado e verificado:')]
 x['successfulBinaryInstallationMarkers']=[i+1 for i,line in enumerate(lines) if body(line).startswith('Instalado e validado:')]
 x['wrongChecksumRefusalMarkers']=[i+1 for i,line in enumerate(lines) if body(line)=='Checksum não corresponde: nada foi instalado.']
 assert len(x['windowLifecycleSuccessMarkers'])==2 and len(x['successfulSourceInstallationMarkers'])==1 and len(x['successfulBinaryInstallationMarkers'])==2 and len(x['wrongChecksumRefusalMarkers'])==1
 assert not x['reviewIssues'] and not x['explicitFailureMarkers'] and not x['productionStructureFailures']
 assert not x['credentialLikePatternsObserved'] and not x['signedURLPatternsObserved']
 assert len(x['compilerWarnings'])==2 and all('usesCPUOnly' in w['text'] for w in x['compilerWarnings'])
 assert len(x['coreGraphicsWarnings'])==6 and all(w['invalidStreamNegativeControlThenSuccessfulNormalization'] for w in x['coreGraphicsWarnings'])
 assert x['native']['starts']==x['native']['passes']==396 and x['native']['startPassMultisetEqual'] and x['native']['perStepCountersMatchAggregate']
 assert x['pythonCasesIncludingSkips']==720 and x['pythonPassed']==719 and x['pythonSkipped']==1
 assert all(s['expectedFailures']==s['unexpectedSuccesses']==0 for s in x['python'])
packer=subprocess.check_output(['git','show',j['sourceSHA']+':scripts/package_binary.py'],cwd='/workspace/PDF-')
assert b"subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)" in packer
j['manualReview']={'completed':True,'unclassifiedWarningCategories':[],'relocationSigningControl':{'gitPath':'scripts/package_binary.py','sourceCommit':j['sourceSHA'],'sha256':hashlib.sha256(packer).hexdigest(),'scope':'Read exact Git code; mandatory deep strict verification after re-signing and corresponding workflow success. No independent local rehash of application binaries by this log review.'},'originalsPreserved':True,'warningCompaction':'Categories retain occurrence counts, original line numbers and samples. Full byte-exact warning paths remain in original logs and official ZIP.','collectorRootRunJobsArtifactsUntouched':True}
report.write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
meta=Path(j['metadataSnapshot']);mfiles=[]
for p in sorted(meta.glob('*.json')):
 b=p.read_bytes();mfiles.append({'file':p.name,'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
review_payload=[]
lines=[f"# Revisão final dos logs oficiais — 37f5b65\n\nFonte **{j['sourceSHA']}**, execução **{j['runID']}**, tentativa 1: API final **success nos dois jobs**. Identidade, tentativa, fonte e estado terminal foram confirmados antes e depois do download autenticado.\n\nO ZIP original tem **1.007.879 bytes**, SHA-256 **`{j['archive']['sha256']}`**. Seus **62 membros**, totalizando **8.295.273 bytes expandidos**, passaram em CRC, nomes, tipos e limites de tamanho. O endpoint oficial não oferece digest independente; o SHA identifica os bytes recebidos. Somente os dois logs agregados foram extraídos. Nenhum código do ZIP foi executado.\n\n| Resultado por Mac | Métodos / execuções | Aprovações / skips |\n|---|---:|---:|\n| Scripts | 150 | 149 aprovados / um skip Linux |\n| Núcleo | 510 | 510 aprovados |\n| Integrações | 60 | 60 aprovados |\n| Total Python | 720 | 719 aprovados / um skip |\n| Nativos | 44 grupos distintos × 9 | 396 inícios / 396 aprovações |\n\nO skip é `test_real_enospc_after_backup_restores_old_bundle`: requer `/dev/full` do Linux. Não houve falhas, erros ou expected failures nas três suítes. Os multiconjuntos de nomes iniciados/aprovados coincidem, e a soma das quatro etapas coincide com o agregado: **duas execuções na instalação de fontes, uma no app instalado, uma no isolamento portátil e cinco na instalação/atualização do binário**. As repetições não são novas funções.\n\n"]
for x in j['jobs']:
 times='; '.join(f"{s['label']}: {s['seconds']:.3f} s" for s in x['python'])
 lines.append(f"## {x['runner']} — job {x['jobID']}\n\n{times}. Log completo: **{x['fullLog']['bytes']:,} bytes**, SHA-256 **`{x['fullLog']['sha256']}`**.\n\n")
 lines.append(f"PDFKit bruto registrou **{len(x['rawPDFKitBaselineDiagnostics'])} resultados `FAILED`**, explicitamente diagnósticos de referência, sem saída de produto. As verificações de estrutura das saídas tratadas passaram. Houve **seis avisos CoreGraphics**, cada um entre a recusa deliberada do stream inválido e sua normalização aprovada. Não houve `Native check failed` nem marcador fatal de etapa.\n\n")
 lines.append('Duas mensagens do ciclo real da janela correspondem às etapas antecipada e instalada. A leitura dos logs também localizou uma publicação do instalador de fontes, duas instalações binárias aprovadas e uma recusa do checksum adulterado. Os JSONs/recibos e a autenticação dos próprios pacotes permanecem evidências separadas.\n\n')
lines.append("## Avisos preservados e classificados\n\nEm **cada Mac**, o único sítio de aviso Swift foi `VisionFailureDiagnostics.swift:122`: uso diagnóstico de `usesCPUOnly`, obsoleto desde macOS 14. Apareceu em duas compilações e em dois trechos de fonte. Os avisos anteriores de retorno `drop` e isolamento `MainActor` não aparecem nesses logs.\n\nTambém em cada Mac, **614 avisos de `install_name_tool`** informaram invalidação da assinatura durante a relocação de dependências. O código exato do empacotador reassina os arquivos modificados e exige `codesign --verify --deep --strict` antes do manifesto; essa etapa e os controles posteriores passaram. Isso não equivale a notarização Apple.\n\nAvisos de infraestrutura por Mac: um de qpdf já instalado, um de openjdk@21 instalado sem link global por existir outro openjdk, um do binding SWIG/PyMuPDF, oito sobre `punycode`, oito sobre `url.parse()` e um sobre ações Node20 executadas em Node24. O probe `appintentsmetadataprocessor --help` recusou opções uma vez em cada sistema; a verificação final de metadados é uma etapa distinta. Todas essas mensagens permanecem nos originais, com categorias e números de linha no JSON. Nenhuma categoria de aviso ficou sem classificação nesta revisão.\n\n## Alcance\n\nEsta revisão confirma a matriz registrada e as contagens de sua tentativa completa. Não aprova o mesmo tar entre sistemas, a retenção privada da entrega, M4 físico, Neural Engine/energia, VoiceOver humano, geração real por modelo indisponível, serviços externos ou notarização. A existência de avisos diagnósticos não foi escondida; os controles e limites foram associados aos logs correspondentes.\n\nArquivos: `collector-attempt-1-logs.zip`, dois logs completos em `collector-attempt-1-logs/`, snapshots de API antes/depois e `/tmp/pdf-native-37f5b65-full-log-review.json`. SHA/CRC dos originais preservados; nenhum arquivo do repositório foi alterado.\n")
md=Path('/tmp/pdf-native-37f5b65-full-log-review.md');md.write_text(''.join(lines))
for p in [report,md,Path('/tmp/pdf_collect_37_logs.py'),Path('/tmp/pdf37-full-logs-static-review.md')]:
 b=p.read_bytes();review_payload.append({'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
provenance={'sourceCommit':j['sourceSHA'],'runID':j['runID'],'attempt':1,'conclusion':j['sourceConclusion'],'officialZIP':j['archive'],'metadataOriginals':mfiles,'aggregateLogs':[x['fullLog'] for x in j['jobs']],'derivedReviewAndCollector':review_payload,'noRepositoryFilesChanged':True}
Path('/tmp/pdf-native-37f5b65-full-log-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'JSONbytes':report.stat().st_size,'MDbytes':md.stat().st_size,'metadataOriginals':len(mfiles),'warningsClassified':True,'originalsUntouched':True,'result':'ready'},indent=2))
