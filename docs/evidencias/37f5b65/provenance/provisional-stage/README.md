# Evidência nativa 37f5b65 — staging provisório

Fonte `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`, execução `40239018570`, tentativa 1.

**Rascunho: final do run = PLACEHOLDER_FINAL_RUN; contagens finais de testes = PLACEHOLDER_FINAL_COUNTS.** O snapshot preservado informa `in_progress` / `None`. Não afirma aprovação da matriz, instalador, teste cruzado, M4 físico ou experiência humana.

Este diretório foi montado offline a partir dos arquivos pequenos já autenticados em `/workspace/.cache/pdf-native-37f5b65`. Não há dados herdados da fonte 81769db. Todos os 12 ZIPs pequenos foram novamente comparados ao digest GitHub registrado; os 106 membros foram comparados byte a byte com seus ZIPs e hashes registrados. Os 66 PNG atuais estão preservados sem edição.

- `originals/downloads/`: os 12 ZIPs originais pequenos do GitHub, por ID de artefato.
- `originals/extracted/`: membros originais com nomes e agrupamentos dos artefatos, inclusive recibos e logs pequenos pertencentes a esses artefatos.
- `provenance/`: registros do coletor e snapshots API originais. Caminhos absolutos dentro dos JSON permanecem como recebidos, referentes ao ambiente de coleta.
- `exact-source/`: seleção de 19 arquivos obtidos do commit Git exato, incluindo workflows, validadores, instalação e diagnósticos nativos. Não é o arquivo de fonte completo; manifesto próprio informa a seleção.
- `reviews/`: revisões visuais independentes dos 33 PNG de cada sistema, com limites explícitos sobre interações, rolagem, animação e VoiceOver.
- `collection-tools/`: coletor e montador de staging como ferramentas locais derivadas; não são código do commit de produto.
- `inventory.json` e `SHA256SUMS`: caminhos, tamanho, hashes, natureza e origem de cada arquivo retido. Os índices de integridade não são assinaturas nem substituem a autenticação da origem.

O relatório de ciclo de janela é evidência específica: apresentação automática/restauração são deliberadamente desativadas no diagnóstico; a etapa inicial usa bundle mínimo e a etapa posterior usa o aplicativo instalado. Não apresenta o bundle mínimo como instalador aprovado. Os hashes de executável nos recibos são afirmações do workflow, ainda não rechecados aqui contra um tar binário.

Não foram copiados o tar de fonte, os ZIPs/tars binários grandes, os logs completos do run ou sua análise ainda pendente. Os logs pequenos de preview/native-checks/lifecycle foram mantidos porque integram os 12 artefatos autenticados. A revisão terminal e contagens finais serão acrescentadas somente após autorização/auditoria. Este staging não contém o aplicativo instalável.

Para conferir os arquivos retidos localmente: `sha256sum -c SHA256SUMS` a partir deste diretório. A API fornece o digest dos ZIPs de artefato registrado nos snapshots; `staging-summary.json` liga os IDs aos arquivos preservados. Nenhum código extraído dos artefatos foi executado.
