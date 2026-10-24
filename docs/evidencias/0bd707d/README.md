# Evidências de 0bd707d — montagem aprovada, isolamento Office reprovado

A [execução 40118132309](https://github.com/vibracall-beep/PDF-/actions/runs/40118132309), tentativa 1, commit **`0bd707d4023ce764a2e0121a1b93dcb0ca69fc1d`**, terminou **reprovada nos dois sistemas**. Compilação, instalação por fontes, testes nativos, capturas/AX, benchmark e montagem/assinatura do bundle passaram. A etapa **Validate portable app without host dependencies or network** falhou em ambos ao executar o Office: `RuntimeError: soffice falhou (1):`, sem detalhe capturado. Esse resultado não determina a causa. A instalação e a atualização posteriores do binário não foram executadas; o pacote não está aprovado para entrega.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo Python | 281 aprovados · 70,998 s | 281 aprovados · 69,053 s |
| Integrações Python | 46 aprovadas · 42,309 s | 46 aprovadas · 40,156 s |
| Scripts | 106 aprovados + 1 skip · 19,913 s | 106 aprovados + 1 skip · 19,203 s |
| Smoke nativo | 38 grupos × três, todos aprovados | 38 grupos × três, todos aprovados |
| Capturas e gate AX | 32 PNGs + seis relatórios, aprovados | 32 PNGs + seis relatórios, aprovados |
| Vision estrito | Dois checks aprovados | Dois checks reprovados, motivos preservados |
| OCR no benchmark | Vision: aquecimento + três amostras | Tesseract: aquecimento + três amostras |
| Modelo Apple | Indisponível, nenhuma geração | Indisponível, nenhuma geração |
| Montagem e assinatura | Aprovadas | Aprovadas |
| Isolamento portátil | Office reprovado | Office reprovado |

São **434 casos Python distintos por sistema: 433 aprovados e um skip**. O skip exige `/dev/full` do Linux; os ensaios reais exclusivos de macOS não foram ignorados. Repetições de uma suíte ou dos smokes não são somadas como casos distintos. A contagem de **38 × três = 114 aprovações nativas** por sistema foi refeita nos dois logs completos de topo, e não inferida do único smoke preservado em cada artefato.

Os originais da captura foram baixados, extraídos com inventário e limites e passaram novamente o checker de **32 PNGs/seis relatórios AX** em cada sistema. O Scope sem nome da rodada anterior não se repetiu no gate. O macOS 27 produziu a série completa; isso não prova a causa do timeout anterior nem garante ausência de recorrência. Os 64 PNGs foram revisados individualmente: não houve novo corte de controles fixos nas telas observadas. A captura escura do macOS 26 ficou menos nítida (1050 × 752) que a do macOS 27 (1050 × 772); foi preservada sem retoque. O log dessa captura registra a janela em 1050 × 772 e o filtro do WindowServer ainda em 1050 × 752, diferente da captura equivalente no macOS 27. Essa divergência orienta a correção do sincronismo de captura; não demonstra defeito no layout do aplicativo. AX automático não substitui uso humano com VoiceOver.

Esta pasta preserva **13 arquivos sem alterar bytes**: o [manifesto original da retenção](retention-manifest.json), dois logs completos dos jobs, dois logs de smoke, seis JSONs de Vision/IA/benchmark e os dois relatórios AX da tela de acessibilidade. O [manifesto desta pasta](provenance.json) registra hashes, tamanhos e origem. Os PNGs não estão copiados aqui.

Os downloads diretos dos artefatos inicialmente retornaram `Forbidden`. A [retenção 40120146837](https://github.com/vibracall-beep/PDF-/actions/runs/40120146837) preservou os originais no rascunho privado de release **422903642**, tag `audit-0bd707d4023c-40118132309`. Foram recebidos os 12 assets: manifesto, dez ZIPs de artefatos e ZIP de logs. Tamanhos e SHA-256 correspondem à release e ao manifesto; os dez ZIPs também correspondem aos digests Actions e ao SHA da fonte. Não foram preservadas URLs temporárias assinadas.

O ZIP de logs retido tem **731.203 bytes**, SHA-256 `a8032fcf101c81d47c57fcd70797edd3727e1e5685838db08c1b10fa43bccfb6`. A origem Actions não forneceu digest desse ZIP; seu hash foi calculado no download e conferido na retenção. Os dois logs completos desta pasta são idênticos às entradas correspondentes desse ZIP. O sucesso da retenção não modifica o `failure` da execução de produto.

O benchmark mediu seis operações com aquecimento e três amostras em **Apple M1 Virtual**, três CPUs e 7 GiB. As amostras têm 100 páginas e hashes diferentes entre sistemas; OCR/contraste usam somente a primeira página. Não é uma comparação controlada entre processadores. Os cinco itens de IA por sistema registram `unavailable`, `modelAttempted=false` e `deviceNotEligible`: nenhuma geração foi avaliada. M4 físico, energia, ocupação da NPU, serviços externos e VoiceOver humano permanecem sem comprovação por essa rodada.

Os [originais de 4ac9d26](../4ac9d26/README.md) permanecem históricos, incluindo suas falhas AX/captura/assinatura. Este resultado não aprova correções posteriores ao commit `0bd707d`; o [estado de entrega](../../VALIDACAO.md) identifica as rodadas separadamente.
