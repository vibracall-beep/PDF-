# Validação local consolidada — 6c8be0e

Os logs abaixo pertencem à fonte **[`6c8be0e740826064e363515fa5aa86f57eccb1ee`](https://github.com/vibracall-beep/PDF-/commit/6c8be0e740826064e363515fa5aa86f57eccb1ee)**. O manifesto anterior ao commit registrou a árvore `54e2a447544a4ad4689a654dbd1d81da6db7e39a`; sua igualdade com `git rev-parse 6c8be0e^{tree}` foi conferida antes desta retenção. A [cópia vinculada ao commit](manifest.json) acrescenta essa associação e os caminhos retidos. O [manifesto original](manifest-original.json), os logs e o [relatório de runtime](runtime.json) permanecem byte a byte; hashes e origens estão em [provenance.json](provenance.json).

**É validação Python no Linux, não aprovação nativa nem de instalador.** A execução [40228648128](https://github.com/vibracall-beep/PDF-/actions/runs/40228648128), inicialmente na fila às 19:59:49 UTC de 25/10/2026, falhou depois em **Verify installer integrity** nos dois sistemas, antes da compilação. A [causa e os originais](../6c8be0e/README.md) estão retidos: JSON foi passado diretamente a `plutil -lint`, que recusou o manifesto válido. Cada Mac registrou 140 métodos de scripts aprovados, dois falhos e um ignorado. Esse resultado não autoriza declarar os ensaios Swift ou a instalação dessa fonte aprovados.

| Suíte | Métodos | Aprovados | Ignorados | Tempo | Log original |
|---|---:|---:|---:|---:|---|
| Núcleo | 510 | 510 | 0 | 93,211 s | [core.log](core.log) |
| Integrações | 60 | 60 | 0 | 128,589 s | [integration.log](integration.log) |
| Scripts | 143 | 136 | 7 | 5,841 s | [scripts.log](scripts.log) |
| Evidência/distribuição | 116 | 116 | 0 | 5,333 s | [diagnostics.log](diagnostics.log) |

Os 35 métodos diretos de ocultação e os 158 métodos da rodada focal do editor já estão compreendidos nos controles consolidados; não são somados novamente. Reexecuções anteriores e resultados de outra fonte permanecem separados. Os sete métodos ignorados dos scripts exigem recursos macOS reais: preflight/arquivo/volume, comportamento BSD de links, disco cheio, Mach-O/assinatura, tabela de processos do SDK e framework Python assinado. O log conserva nomes e motivos exatos; não são resultados aprovados.

## Ambiente e comandos

O [runtime original](runtime.json) registra Python 3.12.14, qpdf 12.2.0, Ghostscript 10.05.1, LibreOfficeDev 26.8.0.0.alpha0, Tesseract 5.5.0 e Chromium 154.0.8037.57. O qpdf resolvido por `/workspace/PDF-/.venv/bin/qpdf` aponta para `/workspace/.cache/pdf-audit-apt/runtime/usr/bin/qpdf`. O Chromium usado é **`/usr/bin/chromium`**, informado por `PDF_CHROMIUM_EXECUTABLE`; não se presume navegador presente no cache padrão do Playwright.

Comandos executados na raiz `/workspace/PDF-`, com stdout/stderr retidos nos respectivos logs:

```sh
PATH="/workspace/PDF-/.venv/bin:$PATH" PDF_CHROMIUM_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
PATH="/workspace/PDF-/.venv/bin:$PATH" PDF_CHROMIUM_EXECUTABLE=/usr/bin/chromium .venv/bin/python -m unittest discover -s tests -p 'integration_*.py' -v
PATH="/workspace/PDF-/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -v
.venv/bin/python -m unittest discover -s diagnostics -p 'test_*.py' -v
```

A rodada inicial de HTML falhou por caminho de navegador e o qpdf foi inicialmente ignorado. Essa história continua na [auditoria](../../AUDITORIA-0.7.md); a rodada consolidada passou com os executáveis acima, sem reclassificar retroativamente o primeiro resultado.

## Alcance das correções

A fonte inclui os repros conhecidos de ocultação, inclusive tags, anexos, metadados ICC/JPEG, rótulos e estados ocultos. A operação verifica o arquivo reaberto antes de publicar. Perfis/estados não suportados são recusados, e a cópia saneada perde tags, OCR invisível, interatividade e navegação; o original e sua proteção são preservados. Os testes delimitados não certificam sanitização arbitrária nem toda construção maliciosa possível.

O editor verifica vetores simples, componentes de cor e perfis suportados, imagens com vínculos estruturais e a recusa de recomprimir imagens ICC. As [fixtures nativas autenticadas](../../../tests/fixtures/coregraphics-gray/README.md) e suas variantes são usadas por testes Python; isso não equivale a executar a interface Swift dessa versão. Fontes Apple podem exigir substituição consentida; não se declara identidade de glifos ou fidelidade universal.

A fonte continua parcial nos requisitos de edição irrestrita, semântica/VoiceOver humano, geração Apple real, M4 físico/energia/Neural Engine e integrações de produção. A [matriz por ferramenta](../../MATRIZ-0.7.md) separa implementação, testes, dependências e limites. Nenhum pacote 0.7 é aprovado por este conjunto local.
