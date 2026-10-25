# Matriz nativa de 6a388b5 — reprovada na compilação

A execução [40237714117](https://github.com/vibracall-beep/PDF-/actions/runs/40237714117), fonte **`6a388b55ed9ae85b2f8cbc3a508d37708358b8d6`**, terminou em **falha nos dois Macs**. A [API da execução](run.json), atualizada em 25/10/2026 às 21:56:33 UTC, e a [API dos jobs](jobs.json) identificam a etapa **Compile native application** como reprovada. A integridade do instalador passou antes dela.

**Nenhuma auditoria GUI da nova implementação foi executada.** Diagnóstico antecipado da janela, instalação completa, diagnóstico da janela instalada, grupos nativos, capturas, OCR, IA, benchmark e empacotamento ficaram ignorados. As etapas de retenção marcadas como concluídas não substituem a execução desses ensaios. O teste cruzado anterior de `81769db` continua reprovado e a entrega 0.7 permanece bloqueada.

## Resultados e originais

| Sistema / job | Scripts antes da compilação | Resultado posterior |
|---|---|---|
| macOS 26 · `121302740721` | **150 métodos: 149 aprovados, um skip Linux**, 25,221 s. | Compilação falhou; zero grupos nativos executados. |
| macOS 27 · `121302740978` | **150 métodos: 149 aprovados, um skip Linux**, 26,130 s. | Compilação falhou; zero grupos nativos executados. |

O skip corresponde ao ensaio de ENOSPC que usa `/dev/full` do Linux. Não é aprovação nem falha do caso no macOS. A [recontagem](recheck.json) distingue esses métodos dos 44 grupos apenas registrados no código. As contagens não são somadas às rodadas locais ou a matrizes anteriores.

Os logs completos [macOS 26](macos26.log) e [macOS 27](macos27.log) foram obtidos novamente pelos endpoints autenticados de cada job e comparados byte a byte com os originais coletados pelo coordenador:

| Log | Bytes | SHA-256 |
|---|---:|---|
| macos26.log | 86.161 | `1b3fbc97c14e9b329dff757826d0a5a271d5ed5927bec9abd63c28e10fb91c46` |
| macos27.log | 125.903 | `a1282dc12d061f18dc6eae18c3ac7c0b611f1a2f53dbc91ccc7e433fae1f0f42` |

[provenance.json](provenance.json) conserva tamanho, hash, endpoint e origem de todos os payloads. Os endpoints de logs não fornecem digest independente; os hashes identificam os bytes autenticados recebidos e reconferidos. Sequências ANSI, timestamps e whitespace dos logs foram preservados.

## Causa de compilação e encaminhamento

Em [WorkspaceLifecycle.swift histórico](source/WorkspaceLifecycle.swift), o método `Coordinator.install(on:)` não está isolado a `MainActor`, mas chama dois métodos que estão: `sceneCoordinator.windowAttached`, na linha 107, e `lifecycleAudit.windowAttached(_:model:)`, na linha 108. Ambos os compiladores recusaram essas chamadas síncronas de contexto não isolado. Os blobs históricos foram extraídos diretamente do commit, para que mudanças posteriores não alterem o significado das linhas.

Os dois logs também conservam o aviso de [MacPreview.swift](source/MacPreview.swift), linha 13: a autoclosure não isolada lê `WindowSceneLifecycleAudit.argument`, propriedade da classe anotada `@MainActor` em [WindowSceneLifecycleAudit.swift](source/WindowSceneLifecycleAudit.swift). Esse aviso é distinto dos dois erros que bloquearam a compilação.

A correção do isolamento está em preparação; **nenhuma mudança posterior foi aprovada por esta execução**. O [preflight local anterior](../local-6a388b5/README.md) continua verdadeiro em seu escopo: sintaxe Swift em Linux não equivale à verificação de tipos/isolamento do SDK macOS. A migração de geometria da cena anônima e os ensaios GUI continuam sem prova. A [auditoria](../../AUDITORIA-0.7.md) e a [matriz](../../MATRIZ-0.7.md) registram a reprovação sem apagar as evidências anteriores.
