# Evidências de 75d5012 — Office isolado ainda reprovado

A [execução 40121275705](https://github.com/vibracall-beep/PDF-/actions/runs/40121275705), tentativa 1, commit **`75d5012cc31032bd953e2075dacf2e81c541a591`**, terminou **reprovada nos dois sistemas**. Compilação, instalação por fontes, testes nativos, capturas/AX, benchmark e montagem/assinatura do bundle passaram. A etapa **Validate portable app without host dependencies or network** falhou em ambos: `RuntimeError: soffice falhou (1):`, sem detalhe capturado. O log principal não determina a causa. A instalação e a atualização posteriores do binário não foram executadas; o pacote não está aprovado para entrega.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo Python | 281 aprovados · 78,149 s | 281 aprovados · 70,670 s |
| Integrações Python | 46 aprovadas · 59,547 s | 46 aprovadas · 43,401 s |
| Scripts | 108 aprovados + 1 skip · 19,120 s | 108 aprovados + 1 skip · 19,753 s |
| Smoke nativo | 39 grupos × três, todos aprovados | 39 grupos × três, todos aprovados |
| Capturas e gate AX | 32 PNGs + seis relatórios, aprovados | 32 PNGs + seis relatórios, aprovados |
| Vision estrito | Dois checks aprovados | Dois checks reprovados, motivos preservados |
| OCR no benchmark | Vision: aquecimento + três amostras | Tesseract: aquecimento + três amostras |
| Modelo Apple | Indisponível, nenhuma geração | Indisponível, nenhuma geração |
| Montagem e assinatura | Aprovadas | Aprovadas |
| Isolamento portátil | Office reprovado | Office reprovado |

São **436 casos Python distintos por sistema: 435 aprovados e um skip**. O skip exige `/dev/full` do Linux; os ensaios reais exclusivos de macOS não foram ignorados. Repetições das suítes ou dos smokes não são somadas como casos distintos. Os **39 × três = 117 resultados nativos aprovados** por sistema foram contados nos dois logs completos de topo, sem inferir três execuções a partir do único smoke preservado em cada artefato.

Os originais passaram novamente o checker de **32 PNGs/seis relatórios AX** após download e extração verificados. Os 64 PNGs foram revisados individualmente, sem novo corte ou sobreposição dos controles fixos nos estados capturados. A captura escura26 agora tem **1050 × 772 pixels e está nítida**; o log registra rejeição da geometria anterior de 752 pixels antes de publicar a captura concordante com o WindowServer. Os originais não foram retocados.

**Ressalva do OCR:** a tela de revisão mostra palavras reconhecidas incorretamente e resultado `eng`, enquanto o seletor exibe Português + inglês. O snapshot carrega `eng`; essa imagem não comprova precisão do OCR nem concordância de configuração. A ressalva está em investigação. A revisão visual não equivale a teste interativo, ensaio humano com VoiceOver ou aprovação do pacote.

Esta pasta preserva **13 arquivos sem alterar bytes**: [manifesto original da retenção](retention-manifest.json), dois logs completos dos jobs, dois logs de smoke, seis JSONs de Vision/IA/benchmark e os dois relatórios AX da tela de acessibilidade. O [manifesto desta pasta](provenance.json) registra hashes, tamanhos, contagens e origem. Os PNGs não estão copiados aqui.

Após a recusa inicial do download direto de artefato, a [retenção 40123290389](https://github.com/vibracall-beep/PDF-/actions/runs/40123290389) preservou os originais no rascunho privado de release **422923712**, tag `audit-75d5012cc310-40121275705`. Foram recebidos 12 assets: manifesto, dez ZIPs de artefatos e ZIP de logs. Tamanhos e SHA-256 correspondem à release e ao manifesto; os dez ZIPs também correspondem aos digests Actions e ao SHA da fonte. O sucesso da retenção não muda o `failure` da execução de produto.

O ZIP de logs tem **731.223 bytes**, SHA-256 `2b9a2fdbf4ba2dbc91ed250050572b077e651621369ff2d9d5a2c900cfd386d2`. O download oficial direto e o retido produziram esse mesmo arquivo. A origem Actions não forneceu digest desse ZIP; o hash foi calculado no download e conferido na retenção. Os dois logs completos preservados são idênticos às entradas correspondentes do ZIP. A varredura dos 25 logs/JSONs de origem não encontrou os padrões verificados de tokens, URLs assinadas, cabeçalhos de autorização ou chaves privadas; nenhum original foi redigido.

O benchmark mediu seis operações, com aquecimento e três amostras, em **Apple M1 Virtual**, três CPUs e 7 GiB. As amostras têm 100 páginas e hashes diferentes entre sistemas; OCR/contraste usam somente a primeira página. Não é uma comparação controlada entre processadores. Os cinco itens de IA por sistema registram `unavailable`, `modelAttempted=false` e `deviceNotEligible`: nenhuma geração foi avaliada. M4 físico, energia, ocupação da NPU, serviços externos e VoiceOver humano permanecem sem comprovação por essa rodada.

Os [originais de 0bd707d](../0bd707d/README.md) permanecem históricos. Este resultado não aprova alterações posteriores a `75d5012`, inclusive as mudanças de encerramento/processos em desenvolvimento. O [estado de validação](../../VALIDACAO.md) identifica separadamente as rodadas seguintes.
