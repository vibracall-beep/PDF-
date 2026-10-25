# Matriz 6f0a68b — reabertura reprovada no macOS 26 e cancelamento posterior no 27

A execução [40238135021](https://github.com/vibracall-beep/PDF-/actions/runs/40238135021), fonte **`6f0a68b6ef70a4e2d5d58b9aecd4bd4bad629828`**, terminou com conclusão **cancelled**, conforme a [API final](collector-run.json), atualizada em 25/10/2026 às 22:07:28 UTC. Os [jobs](collector-jobs.json) têm resultados diferentes: **macOS 26 falhou na reabertura da janela real; macOS 27 passou no diagnóstico antecipado e teve a instalação completa cancelada pelo coordenador após essa falha no 26**. O cancelamento do segundo job não é uma segunda falha de GUI nem uma aprovação de instalação.

**Ambos compilaram, mas a matriz completa e a entrega 0.7 não estão aprovadas.** A correção de isolamento resolveu os erros de compilação exercitados em `6a388b5`; o novo controle revelou uma falha funcional posterior. Nenhum dos dois jobs concluiu a instalação completa, os 44 grupos nativos, a auditoria da janela instalada, as capturas ou o pacote binário.

## Resultados separados por sistema

| Sistema / job | Scripts e compilação | Diagnóstico da janela em bundle mínimo | Etapas posteriores |
|---|---|---|---|
| macOS 26 · `121304006266` | 150 métodos: **149 aprovados/um skip Linux**, 25,833 s; compilação aprovada. | **Reprovado**, 17.891,16 ms. Nove checks registrados como aprovados, mas faltaram os três de reabertura/conclusão. Foram emitidos 24 pedidos e concluídas 16 ações. | Instalação completa e demais ensaios ignorados por falha. |
| macOS 27 · `121304006424` | 150 métodos: **149 aprovados/um skip Linux**, 25,395 s; compilação aprovada. | **Aprovado nesse escopo**, 6.298,89 ms: 12 checks e 24 pedidos/24 ações, com recibo vinculado. | Instalação completa iniciada e cancelada por decisão do coordenador; ensaios posteriores ignorados. |

O skip de scripts usa `/dev/full` do Linux. As contagens não são somadas às rodadas anteriores. O diagnóstico mínimo usa executável real, Info.plist de produção, `WindowGroup`, `openWindow` e guard reais, com estado privado e apresentação/restauração automáticas deliberadamente suprimidas. Não contém o runtime completo do motor. Sua aprovação no 27 não é aprovação do aplicativo instalado, das capturas, do uso humano ou de compatibilidade do mesmo tar entre sistemas.

## Evidência original e procedência

O [snapshot anterior ao cancelamento](before-cancellation/jobs-owner-snapshot.json) registra macOS 26 já reprovado e macOS 27 com o diagnóstico antecipado aprovado e instalação em andamento. Os [metadados originais anteriores](before-cancellation/run.json) e finais preservam essa sequência. O motivo da interrupção foi comunicado pelo coordenador; a API comprova o cancelamento e o snapshot comprova as etapas, mas a API não informa por si só essa motivação. A [recontagem derivada](recheck.json) identifica essas fontes separadamente.

| Artefato original | ID | ZIP / SHA-256 | Membros retidos |
|---|---|---|---|
| `PDF-window-lifecycle-macos-26` | 12615955413 | 3.731 bytes · `f19e4d610b5286eacdfe43d399a9c14afcfeab102e926bc0936956d4abcbbdc2` | [ZIP](macos26/artifact-original.zip), [early.json](macos26/early.json), [early.log](macos26/early.log). Sem recibo de aprovação. |
| `PDF-window-lifecycle-xcode-27` | 12615888226 | 5.390 bytes · `bf47b2e672194c31ac601ffcbdf8509eb54612e524f387db3e1db54f33e17f78` | [ZIP](macos27/artifact-original.zip), [early.json](macos27/early.json), [recibo](macos27/early-receipt.json), [early.log](macos27/early.log). |

Os digests dos dois ZIPs conferem com a [API dos artefatos](collector-artifacts.json). CRCs, inventário, bytes e hashes de cada membro foram reconferidos; o [estado final do coletor](collector-artifact-state.json) permanece original. Os logs completos [macOS 26](macos26/job-complete.log) e [macOS 27](macos27/job-complete.log) têm, respectivamente, **97.124 bytes**, SHA-256 `18b1b692e5620c694ca405c3c4997d0e1eba75bcef085a8eb07ae2cdac905bc2`, e **145.255 bytes**, SHA-256 `c1d019e3e51fbd0ec25e41c8c34894fa3ed97dce974c4f22689f955d43faae08`. [provenance.json](provenance.json) relaciona os payloads às origens e ao commit.

O [checker exato do commit](source/scripts/check_window_lifecycle.py) foi reaplicado aos relatórios: recusa o 26 e aceita o 27. O recibo 27 confere com todos os bytes do relatório, a fonte e o escopo `minimal-diagnostic`; os hashes de executável/Info.plist são afirmações do workflow autenticado, **sem nova leitura local do bundle**. O próprio recibo mantém `completeApplicationApproved: false`, `historicalTimeoutCauseDemonstrated: false` e os limites de capturas/VoiceOver. Não há recibo da janela instalada em nenhum sistema.

A API também registra um artefato de fonte rotulado `unvalidated`. Seu tar/ZIP grande não foi duplicado nesta retenção. Nenhum binário de aplicativo, tar de fonte ou PNG está incluído; as capturas não foram executadas.

## Sequência observada no macOS 26

O relatório confirma criação da primeira janela, ações prontas sobre essa janela e fechamento por `WorkspaceWindowGuard`, com um pedido de fechamento e uma notificação real `willClose`. O máximo observado foi uma janela de trabalho anexada. Após fechar, oito novos pedidos deixaram o total em 24; as ações concluídas permaneceram em 16.

O trace registra, então, nova avaliação do construtor `WindowGroup` e a mensagem **scene construction began**, mas não registra uma segunda **openWindow action invoked** antes de falhar com **“A mesma ação do produto não reabriu a área de trabalho.”** A limpeza privada e a espera das tarefas foram registradas como concluídas. Essa sequência está nos originais; nove checks aprovados não compensam os três ausentes nem o estado final `failed`.

O [coordenador histórico](source/Sources/PDF/WorkspaceSceneCoordinator.swift) e a [declaração da cena](source/Sources/PDF/PDFApp.swift) ficam preservados junto aos traces. A revisão está corrigindo o uso de avaliação declarativa como indicação de construção efetiva da janela. **Esta evidência não aprova essa correção, nem prova retrospectivamente a causa do timeout cruzado de `81769db`.** Migração da geometria salva e interação humana completa continuam sem prova própria.

Logs e demais originais conservam seus bytes. A [auditoria 0.7](../../AUDITORIA-0.7.md) e a [matriz](../../MATRIZ-0.7.md) mantêm os resultados separados e o bloqueio de entrega; checks de estilo excluem os payloads originais de log.
