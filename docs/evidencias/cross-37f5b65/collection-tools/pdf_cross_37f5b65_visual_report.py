from pathlib import Path
from datetime import datetime, timezone
import ast, hashlib, json, struct

ROOT = Path('/workspace/.cache/pdf-cross-37f5b65')
IMAGES = ROOT/'extracted/PDF-cross-platform-validated'
OUT = Path('/tmp/pdf-cross-37f5b65-visual-review')

# Reuse only the observation wording for unchanged, freshly reopened states.
# No previous approval or screenshot is used as evidence for this execution.
template = ast.parse(Path('/tmp/pdf_native_37f5b65_visual_report.py').read_text())
notes = ast.literal_eval(next(n.value for n in template.body if isinstance(n, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id=='NOTES' for t in n.targets)))
notes['PDF-preview.escuro.png'] = (
    'Falha visível: os três ícones dos controles superiores (barra lateral, paleta e personalização) têm cor quase branca sobre cápsulas quase brancas no tema escuro e ficam praticamente ilegíveis. O conteúdo principal do início permanece legível.',
    'A captura prova o baixo contraste neste estado; não prova a causa, sua permanência após animação, nem falha dos cliques. A aprovação visual sem ressalvas depende de correção/explicação e nova evidência autenticada.')

config = json.loads((ROOT/'collector-configuration.json').read_text())
summary = json.loads((ROOT/'collector-summary.json').read_text())
state = json.loads((ROOT/'collector-artifact-state.json').read_text())
artifact = next(a for a in state if a['name']=='PDF-cross-platform-validated')
lifecycle = next(a for a in state if a['name']=='PDF-cross-lifecycle')
assert config['sourceCommit']=='37f5b65e35a9f70c716cfcd64db7ba69837f5c21'
assert config['crossRunID']==40243611339 and config['crossJobID']==121320462461
assert config['controlCommit']=='e4f6c056058d3482b18cdcc24011ccdc96327004'
assert all(summary[k] is True for k in ('completeNativeAndCrossGatesPassed','receiptVerified','lifecycleReceiptVerified'))
assert artifact['sourceBinaryAndGUIReceiptVerified'] is True and lifecycle['lifecycleReceiptVerified'] is True
assert len(artifact['files'])==50 and len(lifecycle['files'])==3
assert {p.name for p in IMAGES.glob('*.png')}==set(notes) and len(notes)==33
inventory=json.loads(Path('/tmp/pdf-cross-37f5b65-image-inventory.json').read_text())
records=[]
for item in inventory:
    raw=(IMAGES/item['name']).read_bytes()
    fingerprint={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    assert fingerprint==artifact['files'][item['name']]
    assert fingerprint=={k:item[k] for k in ('bytes','sha256')}
    assert struct.unpack('>II',raw[16:24])==(item['width'],item['height'])
    observation, limit=notes[item['name']]
    records.append(dict(item,openedIndividually=True,viewImageDetail='original',
        reviewedFromThisCrossArtifact=True,confirmedVisualBlocker=item['name']=='PDF-preview.escuro.png',
        observation=observation,limitation=limit))

ocr_path=IMAGES/'PDF-preview.revisao-ocr.analysis.json'
ocr_raw=ocr_path.read_bytes();ocr=json.loads(ocr_raw)
word=next(w for w in ocr['words'] if w['text']=='informag6es')
platform=json.loads((IMAGES/'PDF-cross-platform.json').read_text())
assert platform['archiveSHA256']==config['archiveSHA256'] and platform['rebuiltOnDestination'] is False

issue={
 'id':'CROSS-DARK-TOOLBAR-CONTRAST', 'status':'confirmed-in-original-capture',
 'image':'PDF-preview.escuro.png',
 'imageSHA256':next(r['sha256'] for r in records if r['name']=='PDF-preview.escuro.png'),
 'title':'Ícones dos controles superiores quase invisíveis no tema escuro',
 'observation':notes['PDF-preview.escuro.png'][0],
 'affectedControls':['Alternar barra lateral','Paleta de comandos','Personalizar'],
 'approximateRegionsTopLeftPixels':[[166,8,202,45],[968,8,1043,45]],
 'impact':'Dificulta identificar visualmente três controles principais da barra superior.',
 'causeEstablished':False,'permanenceAfterTransitionEstablished':False,'clickFailureEstablished':False,
 'numericalContrastRatioMeasured':False,
 'blocksUnqualifiedVisualApproval':True,
 'requiredFollowup':'Investigar a aparência dos controles superiores no binário macOS 26 instalado em macOS 27; preservar os originais e produzir nova evidência autenticada após a correção ou demonstração da causa.',
}
limits=[
 'Todos os 33 PNGs deste artefato cross foram abertos individualmente por view_image em detalhe original, inclusive quando seus bytes coincidem com capturas nativas anteriores.',
 'A revisão visual por agente é independente dos gates automatizados aprovados. O sucesso de instalação, isolamento, GUI e lifecycle não elimina a falha visual confirmada.',
 'As capturas pertencem ao mesmo tar macOS 26 instalado em macOS 27.0.1, sem recompilar, conforme os recibos autenticados. Esta revisão não recompilou, reinstalou ou executou o aplicativo.',
 'Foram vistos apenas viewports de 1050×752 e 1050×772. Barras horizontais no leitor e rolagem em telas densas deixam controles fora da captura; seu acionamento não foi exercitado.',
 'Não houve cliques, rolagem, arraste, edição de atalhos, observação temporal de animações ou avaliação humana com VoiceOver nesta revisão.',
 'O baixo contraste da barra superior escura está confirmado na imagem; a causa, duração após a transição, correção e eventual impacto funcional ainda não estão estabelecidos.',
 'O erro OCR informag6es é real e confirmado no JSON desta execução. O exemplo português usou Tesseract em inglês, 200 DPI e página automática; precisão global e documentos difíceis não foram aprovados.',
 'A presença de 71 ferramentas e 93 comandos na interface não comprova execução completa, fidelidade de conversões, edição irrestrita ou qualidade de IA.',
 'Assinaturas/certificados de produção, serviços externos, scanner, sincronização entre Macs, Atalhos, impressão física e conformidade universal PDF/A/UA/X não foram exercitados por esta inspeção.',
 'O relatório cross identifica Apple M1 (Virtual), 3 CPUs, não M4 físico. Não há aqui medição de GPU, Neural Engine ou energia.',
 'Nenhum arquivo do produto/repositório ou original de evidência foi editado. Não houve rede, execução de coletor ou publicação nesta revisão.',
]
report=dict(schemaVersion=1,createdAt=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
 reviewer='visual_candidate — revisão visual independente por agente',
 sourceCommit=config['sourceCommit'],nativeRunID=config['nativeRunID'],nativeAttempt=config['nativeAttempt'],
 crossRunID=config['crossRunID'],crossAttempt=config['crossAttempt'],crossJobID=config['crossJobID'],
 controllerCommit=config['controlCommit'],archiveSHA256=config['archiveSHA256'],
 imageDirectory=str(IMAGES),targetOperatingSystem=platform['targetOperatingSystem'],targetProcessor=platform['targetProcessor'],
 artifact={k:artifact[k] for k in ('artifactID','name','archive','githubDigest')},
 lifecycleArtifact={k:lifecycle[k] for k in ('artifactID','name','archive','githubDigest')},
 priorAuthenticatedAutomatedEvidence={k:summary[k] for k in ('completeNativeAndCrossGatesPassed','receiptVerified','lifecycleReceiptVerified','authenticatedNativeManifestSHA256')},
 assessment='Revisão de 33/33 imagens concluída com um impedimento visual confirmado: controles superiores quase ilegíveis no tema escuro. Demais estados sem novo bloqueio visual confirmado nos viewports vistos.',
 inspectedPNGCount=33,allPNGsOpenedIndividually=True,installedCrossBinaryScreenshotsReviewed=True,
 previousNativeReviewUsedAsApproval=False,visualApproval=False,visualApprovalWithoutReservations=False,
 confirmedVisualBlockers=[issue],completeApplicationApproved=False,humanVisualReview=False,humanVoiceOverTested=False,
 animationsTested=False,interactionsTested=False,OCRAccuracyApproved=False,editedImages=False,modifiedProductOrRepository=False,
 observedOCRLimitation={'image':'PDF-preview.revisao-ocr.png','language':ocr['language'],'backend':ocr['backend'],
    'recognizedText':word['text'],'intendedText':'informações','confidence':word['confidence'],'settings':ocr['settings'],
    'analysisFile':ocr_path.name,'analysisSHA256':hashlib.sha256(ocr_raw).hexdigest(),
    'sourceSHA256':ocr['source_sha256'],'reviewSHA256':ocr['review_sha256']},
 limitations=limits,images=records)
OUT.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
lines=[
 '# Revisão visual do binário instalado — cross macOS 27', '',
 '**Resultado: aprovação visual pendente.** Todos os 33 PNGs originais foram abertos individualmente em detalhe `original`. Há um impedimento confirmado: os três ícones dos controles superiores no tema escuro ficam quase invisíveis sobre cápsulas quase brancas. Os demais estados não apresentaram novo bloqueio visual confirmado nos viewports vistos.', '',
 f"Fonte `{config['sourceCommit']}` · nativo `{config['nativeRunID']}` · cross `{config['crossRunID']}` · tentativa `1` · job `{config['crossJobID']}`.",
 f"Controlador `{config['controlCommit']}` · tar instalado SHA-256 `{config['archiveSHA256']}`.",
 f"Artefato GUI `{artifact['artifactID']}` · {artifact['archive']['bytes']} bytes · SHA-256 `{artifact['archive']['sha256']}`.",
 f"Lifecycle separado `{lifecycle['artifactID']}` · SHA-256 `{lifecycle['archive']['sha256']}`.", '',
 'O coletor autenticou 50 arquivos GUI (33 PNG, 7 AX, 2 OCR e controles) e 3 lifecycle; os gates nativos/cross e os recibos passaram. Essa autenticação não é aprovação visual. O binário macOS 26 foi instalado sem recompilar no macOS 27.0.1, Apple M1 (Virtual), segundo a evidência autenticada.', '',
 '## Achado confirmado', '',
 f"**{issue['id']} — {issue['title']}.** Em `PDF-preview.escuro.png`, SHA-256 `{issue['imageSHA256']}`, os símbolos de barra lateral, paleta e personalização são praticamente ilegíveis. Regiões aproximadas, origem superior esquerda: x166–202/y8–45 e x968–1043/y8–45. O restante do conteúdo escuro permanece legível.", '',
 'O achado é visual; não prova que os cliques falhem. Causa, permanência após transição e eventual relação com o SDK não foram demonstradas. Investigar e produzir nova evidência autenticada antes de uma aprovação visual sem ressalvas. Os originais desta execução devem permanecer preservados.', '',
 '**OCR:** a tela e o JSON desta execução mostram `informag6es`, confiança `0.37141106`, sobre um exemplo em português reconhecido em inglês por Tesseract. A presença de revisão manual não aprova a precisão do reconhecimento.', '',
 '## Limites', '', *['- '+v for v in limits], '',
 '## Registro individual', '',
 '| PNG original | Dimensões | Constatação | Limite específico |', '| --- | --- | --- | --- |',
]
for r in records:lines.append(f"| `{r['name']}` | {r['width']}×{r['height']} | {r['observation']} | {r['limitation']} |")
lines+=['','## Identidade dos 33 originais','','| PNG original | Bytes | SHA-256 |','| --- | ---: | --- |']
for r in records:lines.append(f"| `{r['name']}` | {r['bytes']} | `{r['sha256']}` |")
OUT.with_suffix('.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'reports':[str(OUT.with_suffix('.md')),str(OUT.with_suffix('.json'))],
    'openedPNGCount':len(records),'confirmedVisualBlockers':1,'visualApproval':False,'completeApplicationApproved':False}))
