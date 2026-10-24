# Observação do início da janela — 64036d3

Na [execução 40133600178, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40133600178), fonte [`64036d30d51a73eb443f6f221df45a674f3f80ec`](https://github.com/vibracall-beep/PDF-/commit/64036d30d51a73eb443f6f221df45a674f3f80ec), os dois lançamentos de cada sistema chegaram ao `WindowGroup` real, com janela visível e fila principal responsiva. **A falha de início observada no macOS 27 da [rodada e9af24a](../e9af24a/README.md) não foi reproduzida. Isso não demonstra uma correção causal nem aprova o aplicativo.**

O diagnóstico verificou os hashes de três fontes contra e9af24a e acrescentou observações numa cópia privada. O instalador real permaneceu inalterado. A sequência de captura foi deliberadamente pausada depois da associação da janela e da ativação, antes de preparar documentos, executar subprocessos ou capturar imagens. Não houve aprovação de PNGs, OCR, AX ou pacote portátil.

## O que os originais mostram

| Sistema | Lançamentos | Janela/fila principal | Estado após dois segundos | Limpeza |
| --- | --- | --- | --- | --- |
| macOS 26 | 2 | Associada, visível e responsiva | Aplicativo ativo; janela principal e de teclado presentes | Confirmada nos dois |
| SDK/macOS 27 | 2 | Associada, visível e responsiva | Aplicativo ativo; janela principal e de teclado presentes | Confirmada nos dois |

Todos os marcadores foram registrados: entrada, corpo do App, criação do conteúdo da cena, associação da janela, `didFinishLaunching`, próximo turno da fila principal e observação após dois segundos. O primeiro lançamento indicou `defaultLaunch=true`; o segundo, `false`, em ambos os sistemas. Os hashes do executável e do `Info.plist` permaneceram iguais entre os lançamentos.

Cada processo foi observado por 45 segundos e encerrado pelo coletor com SIGTERM (`-15`), com limpeza confirmada e sem erro do coletor. Esse encerramento é parte do diagnóstico, não um ensaio do fluxo normal de fechar o aplicativo. Os relatórios mantêm `product_approval: not_evaluated`.

Nos quatro logs, a criação do conteúdo da janela aparece antes de `didFinishLaunching`. No original e9af24a do macOS 27, o último marcador era `didFinishLaunching`, sem criação do conteúdo. Essa diferença localiza o que foi observado; quatro lançamentos bem-sucedidos numa cópia instrumentada não explicam por que a falha anterior ocorreu nem descartam intermitência. A captura normal precisa ser verificada novamente na matriz completa.

## Originais preservados

- [ZIP oficial dos logs](attempt-1-logs.zip): 156.108 bytes, SHA-256 `25daf99eb98cf71b30fa94ae6d8b80862e7633e83bd22014cc4dbb7d476283a6`.
- macOS 26: [observations.json](macos-26-observations.json), [instrumentation.json](macos-26-instrumentation.json), [primeiro lançamento](macos-26-launch-1-startup.log) e [segundo lançamento](macos-26-launch-2-startup.log).
- SDK/macOS 27: [observations.json](xcode-27-observations.json), [instrumentation.json](xcode-27-instrumentation.json), [primeiro lançamento](xcode-27-launch-1-startup.log) e [segundo lançamento](xcode-27-launch-2-startup.log).
- [Procedência, hashes e verificações independentes](provenance.json).

Os relatórios e logs de lançamento são membros originais dos artefatos **12576396702** (macOS 26) e **12576681540** (SDK/macOS 27), obtidos pela API normal e conferidos contra os digests do GitHub. Foram preservados sem reformatar ou redigir os bytes; nenhum executável foi adicionado a esta pasta. Os hashes dos quatro logs também conferem com seus respectivos relatórios.

A triagem de 32 entradas de texto não encontrou os padrões selecionados de tokens, URLs temporárias assinadas, valores de autorização ou chaves privadas. Essa verificação por padrões tem alcance limitado e não garante a ausência de toda forma possível de segredo.
