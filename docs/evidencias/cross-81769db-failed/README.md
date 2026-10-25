# Teste cruzado de 81769db — reprovado na abertura da interface

O teste [40234132628](https://github.com/vibracall-beep/PDF-/actions/runs/40234132628), job `121291948830`, terminou em **falha** em 25/10/2026 às 21:28:54 UTC. O mesmo tar do macOS 26, produto **`81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5`**, foi instalado no macOS 27 sob o controlador **`0c3aad82d319a8985ebc8b7c6fb868d5f91c5f0e`**. Instalação e operações nativas isoladas passaram, mas **a execução de captura não produziu janela nem PNG e foi encerrada após 300 segundos, com código 124**.

**O teste cruzado e a entrega privada da 0.7 não estão aprovados.** A [matriz nativa anterior](../81769db/README.md) continua aprovada para os respectivos pacotes em seus jobs; ela não substitui este resultado do mesmo arquivo instalado no outro sistema. A entrega permanece bloqueada até corrigir a apresentação da cena e obter nova evidência correspondente à fonte corrigida.

## Origem e arquivos retidos

Os originais de [run](collector-run.json), [jobs](collector-jobs.json), [artefatos](collector-artifacts.json) e [estado de autenticação/extração](collector-artifact-state.json) conservam a conclusão. O [log completo do job](originals/job-121291948830.log) tem **146.350 bytes**, SHA-256 **`18c9823aa3be8c2c35ba4a51b77eb0f42eb1965df31cac922788d5e1c8988746`**. As [anotações do job](originals/annotations-121291948830.json) mantêm o código 124 e os avisos recebidos.

O artefato **`PDF-cross-platform-unvalidated`**, ID **12614797387**, foi conferido contra o digest da API: ZIP de **8.404 bytes**, SHA-256 **`234d512fcc99d9bf2689b21c2122a45c65059314831fbe7d3105a882eb7757d9`**. O [ZIP original](cross-unvalidated-original.zip) contém **cinco arquivos e zero PNGs**; todos os membros foram comparados byte a byte e por hash. [provenance.json](provenance.json) distingue originais, arquivos do controlador e análises derivadas. Nenhum binário/tar de aplicativo foi duplicado nesta retenção.

| Evidência do artefato | O que comprova / o que não conclui |
|---|---|
| [PDF-cross-origin.json](artifact/PDF-cross-origin.json) | Origem nativa `40229486932`, artefato macOS 26 `12613568897` e SHA esperado do tar. |
| [PDF-cross-verified.json](artifact/PDF-cross-verified.json) | Tar de 1.448.948.424 bytes, SHA `71528d864bb9425516fe877318a734855ee0c74c818f021d53b13eca790297f5`, manifesto e validação de origem conferidos. Não é recibo de interface aprovada. |
| [PDF-cross-isolation.log](artifact/PDF-cross-isolation.log) | Runtime e operações nativas passaram no isolamento; assinatura e snapshot do bundle permaneceram verificados nessa etapa. |
| [PDF-cross-gui-before.json](artifact/PDF-cross-gui-before.json) | Identidade do binário instalado antes da captura, sem recompilação, uma tentativa, prazo de 300 s e GUI fora do sandbox de dependências. Não substitui o recibo posterior ausente. |
| [PDF-cross-gui-capture.log](artifact/PDF-cross-gui-capture.log) | Marcadores de inicialização e expiração do prazo antes de qualquer captura. Nenhuma janela/captura confirmada. |

O hash `manifestSHA256` dos recibos usa a serialização JSON canônica definida no [controlador](controller/diagnostics/portable_compatibility.py); os registros nativos também conservam separadamente o hash dos bytes do arquivo `manifest.json`.

## Etapas e sintoma observado

A API registra autenticação, instalação, isolamento e vínculo prévio do binário como aprovados. A etapa **Capture the installed binary GUI once outside the dependency sandbox** falhou. Validação/vínculo dos artefatos GUI e publicação da medição cruzada final ficaram ignoradas. O upload conservou o rótulo **unvalidated**; sua existência não aprova a instalação com interface utilizável.

A [recontagem derivada](recheck.json) confirma **43 grupos nativos distintos, três execuções de cada no job**: 129 inícios e 129 aprovações, com nomes equivalentes. Isso não aprova a etapa GUI posterior. Nenhum desses grupos é contado novamente como nova função nem somado à matriz nativa anterior.

No lançamento de captura há 18 marcadores de início. `PDFApp.init` e o corpo do App foram avaliados. `didFinishLaunching`, um turno posterior da fila principal e a observação de dois segundos ocorreram com `windows=0` e `contentViews=0`. Não aparece avaliação do construtor `WindowGroup`, observação de janela ou início de uma fase de captura. A fila principal respondeu nesses momentos iniciais; os logs não demonstram crash nem permitem concluir o estado dela durante todos os 300 segundos.

## Comparação factual e limite causal

A [comparação somente leitura](startup-comparison-readonly.md), com [dados/linhas/hashes](startup-comparison-derived.json), confronta os logs com os dois nativos 817 e o teste cruzado 437 anteriormente aprovado. O [log histórico comparado](originals/comparison-cross437-job.log) conserva o membro original extraído do ZIP já versionado; a extensão do nome retido não altera os bytes.

- O workflow cruzado é byte idêntico entre os dois controladores. Wrapper, prazo, argumentos de captura e GUI fora do sandbox são iguais. macOS 27.0.1, imagem do runner e provisionador registrados também coincidem. O ambiente completo do processo não foi capturado; isso não demonstra igualdade de todo o ambiente.
- Nos dois nativos 817 e no cruzado 437 aprovado, o `WindowGroup` e a janela foram construídos antes de `didFinishLaunching`. No cruzado 817, essa realização da cena não foi registrada.
- `defaultLaunch=false` foi observado na falha, mas lançamentos históricos com esse mesmo valor criaram janelas. **O flag não demonstra a causa.** A causa ainda não foi estabelecida pela comparação.
- A falha ocorreu antes de preparar documentos, OCR ou ScreenCaptureKit. As imagens nativas anteriores não substituem as capturas inexistentes do binário cruzado.

O coordenador está implementando reapresentação da cena e auditoria GUI controlada. **Nenhuma correção nova está aprovada por este conjunto**, e os originais não serão substituídos por uma eventual execução bem-sucedida. A [auditoria 0.7](../../AUDITORIA-0.7.md) e a [matriz](../../MATRIZ-0.7.md) registram o bloqueio. Os rascunhos finais de instalação e galeria continuam sem publicação como entrega.

Logs originais mantêm espaços finais e demais bytes. Checks de estilo dos documentos excluem os payloads de log; sua integridade é verificada pelos hashes.
