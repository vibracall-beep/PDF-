# Evidências de ecae663 — testes aprovados; captura e isolamento reprovados

A [execução 40125423021](https://github.com/vibracall-beep/PDF-/actions/runs/40125423021), tentativa 1, commit **`ecae663e5d0006113fbf3948bfe86a7ca2c32b0b`**, terminou **reprovada nos dois sistemas**. Compilação, instalação por fontes, smokes nativos e montagem/assinatura do bundle passaram. A captura expirou antes da primeira janela observada; a validação portátil falhou ao sinalizar um grupo de processos durante a execução do Java/veraPDF. O pacote não está aprovado para entrega.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo Python | 301 aprovados · 88,735 s | 301 aprovados · 75,471 s |
| Integrações Python | 49 aprovadas · 54,853 s | 49 aprovadas · 46,686 s |
| Scripts | 110 aprovados + um skip · 25,488 s | 110 aprovados + um skip · 20,234 s |
| Smoke nativo | 41 grupos × três, todos aprovados | 41 grupos × três, todos aprovados |
| Captura | Timeout 300 s, zero arquivos | Timeout 300 s, zero arquivos |
| Gate AX | Não executado | Não executado |
| Vision estrito | Dois checks aprovados | Dois checks reprovados |
| OCR no benchmark | Vision nas quatro chamadas | Tesseract nas quatro chamadas |
| Modelo Apple | Indisponível, nenhuma geração | Indisponível, nenhuma geração |
| Montagem e assinatura | Aprovadas | Aprovadas |
| Isolamento portátil | Java/sinal de processo: `EPERM` | Java/sinal de processo: `EPERM` |

São **461 casos Python distintos por sistema: 460 aprovados e um skip**, que exige `/dev/full` do Linux. Os ensaios reais exclusivos de macOS não foram ignorados. Reexecuções não são somadas como novos casos. Os dois logs completos de topo comprovam **41 × três = 123 resultados nativos aprovados** em cada sistema; o único smoke copiado de cada artefato não é usado para inferir essas três execuções.

## Captura sem arquivos

O último trace dos dois processos foi `PDFApp init end; mainThread=true`: no26 às **19:47:14.175 UTC**, no27 às **19:42:00.163 UTC**. Não houve trace de montagem da WindowGroup, captura ou preparação da amostra OCR. Após 300 segundos, o supervisor encerrou a execução; a coleta de stack também excedeu seus 12 segundos. O passo terminou com status **124**. Esses dados delimitam o ponto observado, mas **não estabelecem a causa do bloqueio**.

O upload confirmou ausência de todos os arquivos esperados: **zero PNGs, zero relatórios AX, zero PDFs de origem OCR e zero JSONs de análise OCR**. Portanto, não existe revisão visual nem inspeção da nova amostra OCR desta rodada. As [capturas de 75d5012](../../imagens/75d5012/README.md) permanecem históricas e não representam este commit. Nenhum prazo foi ampliado ou resultado substituído para aprovar a captura.

## Falha portátil anterior ao Office

Nos dois sistemas, a montagem e a assinatura passaram. Após mover o bundle, a etapa `Validate portable app without host dependencies or network` iniciou `validate-pdfua`, usando Java/veraPDF. O traceback registra `OwnedProcess.communicate → close → signal_owned_group → os.killpg(SIGTERM)` com **`PermissionError: [Errno 1] Operation not permitted`**. A tentativa posterior de encerrar o grupo também foi recusada; a etapa terminou com status **127**.

Esse resultado é diferente do `soffice` status1 da [rodada75d](../75d5012/README.md): **Office não foi alcançado nesta validação portátil**. Não é uma reprovação de conformidade PDF/UA produzida pelo veraPDF; o caminho foi interrompido no controle de processos. O erro foi preservado e continua bloqueando a aprovação do pacote. Instalação/atualização binária posteriores e compatibilidade do mesmo pacote entre Macs não foram executadas. O [diagnóstico separado de IPC privado](../private-ipc-c2ecff7/README.md) não aprova este snapshot nem substitui o gate integral.

## Originais e limites

Esta pasta contém **nove originais sem alteração de bytes**: um [ZIP oficial dos logs da tentativa](actions-attempt-1-logs.zip), dois logs de smoke e seis JSONs de Vision/IA/benchmark. Os logs completos não foram duplicados descompactados no repositório. O [manifesto](provenance.json) registra IDs, digests, tamanhos, contagens, linhas relevantes e hashes das duas entradas completas dentro do ZIP.

O ZIP tem **694.836 bytes**, SHA-256 **`70384e3d860f909f7c4f4ce38a5bb01746529c79e96fb5630fc41d1833e0171d`**. A API Actions não forneceu digest de origem para esse arquivo; o hash foi calculado após o download oficial. Os oito ZIPs dos artefatos foram baixados pela API padrão, conferidos contra commit, ID, tamanho e digest Actions, e extraídos com inventário/limites/CRC. Não houve retenção por release nesta rodada. A varredura das 52 entradas do ZIP e dos oito relatórios preservados não encontrou os padrões verificados de tokens, URLs assinadas, autorização ou chaves privadas; nenhum conteúdo desses originais foi ocultado ou alterado.

Os relatórios registram seis operações com aquecimento e três amostras em **Apple M1 Virtual**, três CPUs e 7 GiB. As entradas sintéticas têm 100 páginas e hashes distintos entre sistemas; OCR/contraste medem somente a primeira página. IA registra cinco itens `unavailable`, `modelAttempted=false`, motivo `deviceNotEligible` por sistema. Não há prova de geração pelo modelo Apple, M4 físico, energia/NPU, serviços externos ou VoiceOver humano. Correções posteriores de perfis, encerramento, Pages, inicialização e isolamento precisam de nova validação integrada.
