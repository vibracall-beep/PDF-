#!/usr/bin/env python3
"""Finalize derived review only; originals and repository stay unchanged."""
from pathlib import Path
import collections,hashlib,json,re,zipfile
ROOT=Path('/workspace/.cache/pdf-cross-37f5b65')
OUT=Path('/tmp/pdf-cross-37f5b65-full-log-review.json')
def measure(p):
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
d=json.loads(OUT.read_text());visual_path=Path('/tmp/pdf-cross-37f5b65-visual-review.json');visual=json.loads(visual_path.read_text())
assert d['sourceCommit']==visual['sourceCommit'] and d['runID']==visual['crossRunID'] and d['controllerCommit']==visual['controllerCommit']
assert visual['visualApproval'] is False and visual['inspectedPNGCount']==33 and visual['allPNGsOpenedIndividually'] is True
assert len(visual['confirmedVisualBlockers'])==1
block=visual['confirmedVisualBlockers'][0]
image=ROOT/'extracted/PDF-cross-platform-validated'/block['image']
assert measure(image)['sha256']==block['imageSHA256']
with zipfile.ZipFile(d['officialLogArchive']['path']) as z:
 member=d['controlPythonSuites'][0]['member'];lines=z.read(member).decode().splitlines()
 previous=0
 for suite,label,count in zip(d['controlPythonSuites'],['test_portable_compatibility.py','test_cross_gui_evidence.py'],[9,11],strict=True):
  assert suite['cases']==suite['passed']==count and suite['status']=='passed' and suite['skipped']==0
  segment='\n'.join(lines[previous:suite['line']]);module=label.removesuffix('.py')
  assert len(re.findall(r'\('+module+r'\.[^\n]+\) \.\.\. ok$',segment,re.M))==count
  assert label in '\n'.join(lines[:10]);suite['label']=label;suite['classification']='controller diagnostics; not PDF tool execution';suite['labelEvidence']='exact verbose test module names before this summary and ordered commands in the same original step log'
  previous=suite['line']
classes=collections.Counter()
for w in d['warningRecords']:
 t=w['text']
 if '[DEP0040]' in t:k='Node punycode deprecated'
 elif '[DEP0169]' in t:k='Node url.parse deprecated'
 elif '[DEP0005]' in t:k='Node Buffer constructor deprecated'
 elif 'Node.js 20 is deprecated' in t:k='GitHub actions Node20 forced to Node24'
 else:raise ValueError('Unclassified warning: '+t)
 w['classification']=k;classes[k]+=1
d['warningSummary']={'byClassification':dict(classes),'unclassified':0,'scope':'Infrastructure deprecations retained; not Swift compilation (the destination did not rebuild).'}
d['independentVisualReview']={'reviewer':visual['reviewer'],'reports':[measure(visual_path),measure(Path('/tmp/pdf-cross-37f5b65-visual-review.md'))],'reviewedPNGCount':33,'allPNGsOpenedIndividually':True,'visualApproval':False,'status':'blocked by a confirmed visible contrast defect','confirmedVisualBlockers':[block],'blockingImage':measure(image),'observedOCRLimitation':visual['observedOCRLimitation'],'humanVoiceOverTested':False,'humanVisualReview':False,'assessment':visual['assessment'],'performedByLogReviewer':False,'rootIndependentlyConfirmedBlocker':True,'originalAutomatedReceiptsUnmodified':True}
d['automatedCrossProtocolPassed']=True
d['releaseReady']=False
d['privateDeliveryApprovedByThisReport']=False
d['deliveryBlocker']='CROSS-DARK-TOOLBAR-CONTRAST: three main toolbar controls almost illegible in original dark-theme cross capture; new authenticated evidence required after correction/investigation.'
d['scope']='Authenticated macOS26 tar installed unchanged on macOS27: automated protocol passed, independent visual review found a blocking contrast defect. No final delivery approval, universal feature completeness, physical M4/Neural Engine/energy measurement or human VoiceOver approval.'
OUT.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n')
md='''# Revisão dos logs oficiais do teste cruzado 37f5b65

**O protocolo automatizado passou; a revisão visual independente encontrou um bloqueador. A entrega desta fonte não está aprovada.** Os três controles superiores de barra lateral, paleta e personalização ficam quase ilegíveis na captura do tema escuro. O sucesso da instalação, isolamento, ciclo de janela e gates AX permanece registrado e não elimina esse defeito.

## Identidade e origem

- Produto: `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`, versão 0.7.0, proveniente da matriz nativa `40239018570`.
- Teste cruzado: [40243611339](https://github.com/vibracall-beep/PDF-/actions/runs/40243611339), tentativa 1, job `121320462461`, concluído com `success` em 25/10/2026 às 23:26:36 UTC. As 18 etapas registradas na API passaram.
- Controlador: `e4f6c056058d3482b18cdcc24011ccdc96327004`; é distinto da fonte do aplicativo.
- O mesmo tar produzido no macOS 26 foi instalado em macOS 27.0.1 sem recompilar: SHA-256 `641d66d3c4bd68ad8074d906e6dd9c3c18ef946292da2d9512541948db52c4a4`, 1.449.079.284 bytes.
- O destino identifica Apple M1 (Virtual), 3 CPUs lógicas; não é evidência de desempenho de um M4 físico.

O coletor do coordenador já havia baixado os originais por API autenticada. Esta revisão não fez downloads. Foram conferidos identidade de run/job/commits, hashes e tamanhos, diretório ZIP, tipos e nomes de membros, limites de expansão e CRC de todos os membros. Nenhum código de artefato foi executado. Os validadores empregados vieram de bytes Git do controlador exato, comparados ao checkout retido; o parser de logs é código local previamente revisado.

## Recontagem dos logs integrais

| Execução | Grupos distintos | Inícios | Sucessos |
| --- | ---: | ---: | ---: |
| Instalação do binário macOS 26 em macOS 27 | 44 | 88 | 88 |
| Isolamento de dependências do host e operações nativas | 44 | 44 | 44 |
| Total de três execuções dos mesmos grupos | 44 | 132 | 132 |

Os nomes correspondem aos 44 grupos reais da fonte. Foram comparados os multiconjuntos de inícios e sucessos, exigidas as duas etapas esperadas e conferida a igualdade entre suas somas e o log agregado. Há três marcadores finais de smoke completo. **São 44 grupos repetidos três vezes, não 132 ferramentas diferentes.**

Os controles Python do workflow também passaram: `test_portable_compatibility.py`, 9/9 em 0,020 s; `test_cross_gui_evidence.py`, 11/11 em 0,404 s; nenhum skip. Os nomes foram identificados pelas linhas de testes e comandos originais. Esses 20 métodos verificam o controlador de evidências; não são nova execução das 720 verificações Python por Mac da matriz nativa anterior e não se somam a ela como cobertura inédita.

## Janela, GUI e limite da aprovação automática

O ensaio de ciclo real passou 12 verificações, com 24 pedidos de apresentação e 24 ações prontas, em 4.592,99 ms. O recibo vincula o relatório, a fonte e os hashes do executável e Info.plist ao mesmo binário da captura; o validador foi reaplicado. O ensaio usa estado privado e documentos vazios. Não demonstra a causa do timeout histórico, migração de geometria nem os percursos com documentos alterados.

O artefato GUI contém 50 arquivos, incluindo 33 PNGs, 7 árvores AX e 2 registros OCR; o artefato de ciclo contém outros 3 arquivos. Todos foram conferidos contra os ZIPs autenticados e recibos, incluindo os logs de captura/validação. Houve uma tentativa de captura, com limite de 300 s. O relatório confirma arquivo de instalação e manifesto preservados antes/depois. Esta revisão não recalculou hashes de um bundle executável local: conferiu os originais e vínculos produzidos no runner.

As sete árvores AX passaram o gate, mas registram **116 controles para revisão**. Passar esse gate não comprova contraste, VoiceOver humano, cliques ou animações. O recibo automatizado original continua declarando que não houve revisão humana.

## Bloqueador visual e OCR observado

A revisão independente por agente abriu individualmente os 33 PNGs originais. Em `PDF-preview.escuro.png` (401.682 bytes; SHA-256 `13dcfebf3a4ec930d6ee42360004ec4da89072da1d2b0e39a64249ad9aa0387a`), os controles **Alternar barra lateral**, **Paleta de comandos** e **Personalizar** apresentam símbolos quase brancos sobre cápsulas quase brancas. O coordenador confirmou o achado. Identificador: `CROSS-DARK-TOOLBAR-CONTRAST`.

O achado reprova a aprovação visual sem ressalvas e bloqueia a entrega desta fonte. Não estabelece a causa, duração após uma transição, contraste numérico ou falha de cliques. Será necessária nova evidência autenticada após investigação/correção. O resultado `success` da API e os recibos automáticos não foram modificados para registrar a avaliação visual.

A mesma revisão registra o OCR `informag6es`, confiança 0,37141106, em exemplo português processado com idioma inglês, Tesseract, 200 DPI e segmentação automática. Esse erro observado não é ocultado pela disponibilidade de revisão manual, nem usado como prova geral da qualidade do OCR. O JSON derivado desta análise aponta para os relatórios visuais e seus hashes; estes distinguem a avaliação por agente de uma avaliação humana.

## Avisos e diagnósticos preservados

- Nove linhas `FAILED` são controles de serialização bruta do PDFKit, explicitamente marcados `diagnostic only, not the product output`; não foram contabilizadas como falhas de uma saída do produto nem ocultadas.
- Três avisos CoreGraphics ocorrem nos controles de comprimento de stream inválido, entre a rejeição esperada e a normalização de produção aprovada.
- Oito avisos de infraestrutura: três de `punycode`, três de `url.parse`, um do construtor `Buffer()` e um sobre ações Node 20 forçadas a Node 24. Todos estão classificados com a linha original no JSON.
- Nenhum marcador fatal procurado (`##[error]`, `Native check failed:`, `subprocess.TimeoutExpired:`, `RuntimeError: soffice`) foi encontrado. Essa busca delimitada não significa ausência universal de erros; existe o bloqueador visual confirmado.

## Retenção e limites

| Original | Bytes | SHA-256 |
| --- | ---: | --- |
| ZIP oficial de logs completos | 98.516 | `20587424d8624d096405179dadb6ad9ae3e6f7d3052f11dc599aece3f6335e69` |
| Log agregado `0_compatible-binary.txt` | 267.884 | `5b48c5e7c8edec5732a9b828e3ad61e0b0fcd870bff792fb6360e2fa7cc1e043` |
| ZIP original GUI `12618361902` | 3.421.238 | `196e62ea761dd6291a5c14e2db6c36bffee467c2dd3002655ecd9e93e552d665` |
| ZIP original ciclo `12617224816` | 5.272 | `9f842412e7022e076ce9c438cbf879207ad2274a01debe1642fd484c890c4e17` |

O ZIP oficial tem 20 membros, 536.414 bytes expandidos. Foram aplicados limites de 64 MiB para o arquivo, 32 MiB por membro e 128 MiB expandidos. Apenas o log agregado foi extraído nesta análise; os logs por etapa permanecem no ZIP original. A API de logs não fornece digest upstream; o SHA retido identifica os bytes obtidos pela requisição autenticada. Os dois ZIPs de artefatos coincidem com os digests da API.

Os snapshots API, inventário/hash de cada membro, classificação de avisos, vínculos de GUI/ciclo e fontes dos validadores constam do JSON acompanhante. Bytes originais, espaços e sequências ANSI foram preservados. Os relatórios desta análise são derivados e não substituem os originais.

Não houve publicação, release, entrega aprovada, teste físico em M4, medição de Neural Engine/energia, geração real de IA em português, VoiceOver humano, serviços/certificados de produção ou execução de todos os recursos comerciais. O pacote permanece ad hoc, sem notarização Apple. A presença de 71 ferramentas na interface não demonstra completude irrestrita. A aprovação nativa específica de 37f5b65 e as falhas históricas anteriores continuam com seus próprios escopos.
'''
Path('/tmp/pdf-cross-37f5b65-full-log-review.md').write_text(md)
provenance={'schemaVersion':1,'sourceCommit':d['sourceCommit'],'controllerCommit':d['controllerCommit'],'runID':d['runID'],'attempt':1,'scope':'Derived offline log review; automated cross passed, independent visual blocker prevents delivery. Original collector and repository unchanged.','outputs':[measure(OUT),measure(Path('/tmp/pdf-cross-37f5b65-full-log-review.md'))],'analysisSources':[measure(Path('/tmp/pdf37_review_cross_logs.py')),measure(Path('/tmp/pdf37_finalize_cross_log_review.py')),d['pureLocalParser']],'officialLogArchive':d['officialLogArchive'],'fullJobLog':d['fullJobLog'],'metadataOriginals':d['metadataOriginals'],'visualReviewReports':d['independentVisualReview']['reports'],'blockingImage':d['independentVisualReview']['blockingImage']}
Path('/tmp/pdf-cross-37f5b65-full-log-provenance.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'outputs':provenance['outputs'],'nativeStarts':132,'nativePasses':132,'groups':44,'automatedCrossProtocolPassed':True,'visualApproval':False,'deliveryApproved':False},ensure_ascii=False))
