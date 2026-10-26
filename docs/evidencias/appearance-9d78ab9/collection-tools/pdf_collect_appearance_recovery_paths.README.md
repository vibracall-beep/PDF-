# Preparação de retenção da fonte dos caminhos de recuperação

Coletor `/tmp/pdf_collect_appearance_recovery_paths.py`, SHA-256 `83430bd79e67203b15378ec9489090d479e0671791b6306d9d9014c74aad3480`. A versão histórica `/tmp/pdf_collect_appearance_public_items.py`, SHA `030d370363510ee3972739d7285c9e19ad6801a22ef97117f4f6accd604ea4c7`, foi preservada sem alteração.

O único delta acrescenta `Sources/PDF/WorkspaceModel.swift` e `Sources/PDF/SessionAnnotationAuditChecks.swift` à seleção explícita do Git da futura fonte, que já inclui `RecoveryStore.swift`. Não altera fluxo de coleta, validação, inventário, limites, identidade, downloads ou gates. Os caminhos de descarte/limpeza de estado foram ampliados no produto pelo coordenador; **o focal de aparência não os exercita**. Retenção do código não significa aprovação nativa ou teste desses caminhos.

A configuração `/tmp/pdf-appearance-recovery-paths-config.draft.json` mantém SHA, run, tentativa e IDs deliberadamente inválidos. Antes de qualquer coleta, a configuração real precisa da fonte/controlador commitados, run/tentativa e ambos os IDs fornecidos pelo coordenador, além do diretório exclusivo. Não foi executado main/coletor.

Passaram 18 testes offline do coletor e quatro guardas de recusa (rascunho real, run ausente, jobs ausentes e duplicados). O script de testes difere do anterior apenas no import. Os negativos existentes de identidade, workflow, digest, intervalo, nomes/colisões ZIP, traversal, symlinks, CRC, expansão e trailing bytes permanecem. Nenhuma rede, download ou execução de artefato ocorreu. Os 28 métodos atuais do checker mencionados pelo coordenador não foram executados nesta preparação e não aprovam o nativo.

Delta: `/tmp/pdf-appearance-recovery-paths-collector.diff`. Resultado/log: `/tmp/pdf-appearance-recovery-paths-collector-offline-tests.{json,log}`. Inventários focais futuros permanecem15/14, com sete PNG por sistema. Resultados de e0 e demais fontes anteriores permanecem históricos; nenhuma aprovação foi transferida.
