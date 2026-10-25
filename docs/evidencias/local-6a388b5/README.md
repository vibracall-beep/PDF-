# Preflight local de 6a388b5 — apresentação da janela

Fonte **`6a388b55ed9ae85b2f8cbc3a508d37708358b8d6`**, árvore **`1664d9cafe288672ded0666786884a4c8c666d3e`**. O [registro original](preflight-original.json), criado em 25/10/2026 às 21:55:17 UTC, conserva os resultados locais. Os logs foram retidos sem alteração; [provenance.json](provenance.json) registra origem, tamanho, SHA-256 e a conferência da árvore Git.

**Esta evidência é local, sem aprovação nativa ou de entrega.** A matriz [40237714117](https://github.com/vibracall-beep/PDF-/actions/runs/40237714117), jobs `121302740721` (macOS 26) e `121302740978` (macOS 27), estava na etapa de integridade quando este registro foi preparado. Esse estado parcial foi comunicado pelo coordenador. Posteriormente, a matriz **falhou na compilação nos dois Macs**, antes de qualquer auditoria GUI. A [retenção nativa separada](../6a388b5/README.md) conserva os logs/API finais e a causa de isolamento `MainActor`; este preflight local e seus originais não foram alterados.

| Controle | Resultado local | Alcance |
|---|---|---|
| [Scripts](scripts.log) | **150 métodos: 143 aprovados e sete ignorados**, 3,849 s. | Os sete exigem recursos macOS e não contam como aprovados. Inclui os contratos do relatório de ciclo de janela; não executa SwiftUI. |
| [Evidência/distribuição](diagnostics.log) | **116 métodos aprovados**, 3,221 s. | Verifica contratos de origem, artefatos e observação; não aprova um novo binário. |
| Swift | Sintaxe de **88 arquivos** aprovada no registro. | Não houve verificação de tipos contra o SDK macOS nem execução da interface nesta evidência. |
| Catálogo | **71 IDs, na mesma ordem de `81769db`**, reconferidos nos blobs Git. | Presença e ordem não provam execução de cada ferramenta. |
| YAML/shell | Sintaxe aprovada no registro. | Não demonstra que cada etapa de CI executará com sucesso. |
| Grupos nativos | **44 grupos registrados no código**, reconferidos em `audit`/`auditAsync`. | Nenhum foi executado por este preflight Linux; não são 44 aprovações. |

As contagens não são somadas às rodadas anteriores. Núcleo e integrações não foram repetidos neste conjunto local. Os hashes de pacotes temporários impressos pelos testes de scripts não identificam uma entrega aprovada.

## Implementação associada

O [coordenador de cena](../../../Sources/PDF/WorkspaceSceneCoordinator.swift) registra a ação real `openWindow` da `WindowGroup` identificada como `pdf-workspace`. Solicitações de mostrar/abrir/reabrir aguardam o fim do lançamento e a janela anexada. A política conserva as ações pendentes, evita pedidos duplicados durante construção e mantém o `Workspace` compartilhado ao fechar a última janela. Ativação passiva com Ajustes visíveis ou janela minimizada não solicita outra janela. O modo normal conserva apresentação e restauração automáticas.

A [auditoria GUI independente](../../../Sources/PDF/WindowSceneLifecycleAudit.swift) foi implementada para desativar deliberadamente apresentação/restauração automáticas somente na condição diagnóstica, comprovar o estado inicial sem janela e então emitir 24 pedidos em três fases: abrir, reapresentar e reabrir após o fechamento pelo guard real. Ela exige uma única janela real anexada, a mesma instância de `Workspace`, preferências privadas preservadas e limpeza do estado. O [checker](../../../scripts/check_window_lifecycle.py) valida o relatório e vincula um recibo ao executável e à fonte. **O código desses ensaios existe, mas a compilação posterior falhou e nenhum deles foi executado nessa rodada macOS.**

Os workflows executam esse diagnóstico primeiro em bundle mínimo, depois no aplicativo instalado e, no teste cruzado, no binário instalado sem recompilação. O bundle mínimo conserva o Info.plist de produção e a proteção do runtime, mas omite motor/dependências; sua aprovação eventual não substitui a instalação completa, os 44 grupos, as capturas ou o teste cruzado.

A [falha cruzada anterior](../cross-81769db-failed/README.md) permanece válida para `81769db`: a correção não estabelece retrospectivamente sua causa. Migração da geometria salva pela `WindowGroup` anteriormente anônima não está comprovada. Este diagnóstico usa estado privado e modelo sem documentos/rascunhos sujos; não cobre todo fluxo humano ou confirmações com dados não salvos. README e instruções finais de instalação continuam aguardando aprovação correspondente ao novo candidato.

Logs originais mantêm seus bytes, inclusive whitespace. Checks de estilo excluem payloads de log; a integridade destes é verificada pelos hashes.
