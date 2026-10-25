# Evidência nativa — 37f5b65

Fonte `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`, matriz `40239018570`, tentativa 1. **Matriz nativa concluída com sucesso nos dois sistemas. Teste cruzado do mesmo binário em curso e entrega privada ainda pendente neste snapshot. O run cross `40243611339`, job `121320462461`, foi informado pela coordenação como despachado às 23:11:20 UTC, com controlador `e4f6c056058d3482b18cdcc24011ccdc96327004`; este montador offline não consultou sua API nem o aprovou.** Isso não afirma que todas as solicitações foram integralmente implementadas nem aprova M4 físico, IA real, serviços externos, VoiceOver humano ou ausência universal de erros.

## Contagens verificadas nos logs oficiais completos

| Runner | Métodos Python, incluindo skips | Aprovados | Skips | Grupos nativos |
|---|---:|---:|---:|---:|
| macos-26 | 720 | 719 | 1 | 44 × 9 = 396 |
| xcode-27 | 720 | 719 | 1 | 44 × 9 = 396 |

Cada runner executou installer/scripts 150 métodos (149 PASS, 1 skip), core 510 PASS e integração 60 PASS. O skip é o ensaio Linux `/dev/full`; grupos nativos repetidos não são contados como novas ferramentas. A distribuição das nove execuções foi 2 + 1 + 1 + 5 nas etapas registradas. Avisos, diagnósticos negativos PDFKit/CoreGraphics e probes App Intents estão classificados na revisão original, sem apagar os logs.

## Pacotes autenticados, não incluídos neste diretório

| Artefato | ID | SHA-256 do tar medido em stream | Bytes do tar |
|---|---:|---|---:|
| PDF-binary-validated-macos-26 | 12617457782 | `641d66d3c4bd68ad8074d906e6dd9c3c18ef946292da2d9512541948db52c4a4` | 1449079284 |
| PDF-binary-validated-xcode-27 | 12617482313 | `b21b530ae9df9c51de3c54bd16f2b499705e83e43754df4ffd4c496ea3fe570d` | 1447024392 |

O coletor binário concluiu a comparação de cada arquivo do tar com o manifesto, limites/storage, fonte e instalador exatos. Esta retenção rehashou os quatro metadados pequenos por pacote, preservando o recibo dessa medição; não reabriu nem extraiu o tar grande e não faz novo download. O checksum isolado não substitui a autenticação registrada.

## Organização e reprodução da evidência

- `originals/downloads/`: os 12 ZIPs originais pequenos autenticados pelo digest GitHub, incluindo os dois grupos de lifecycle.
- `originals/extracted/`: 106 membros dos grupos pequenos, quatro metadados de fonte por runner e quatro metadados de binário por runner; nomes e bytes originais preservados.
- `originals/full-run-logs/`: ZIP oficial completo e os dois logs agregados. O endpoint de logs não fornece digest independente; o SHA identifica os bytes recebidos, com CRC/hashes de todos os membros verificados.
- `provenance/`: API final, snapshots históricos, coletores e recibos binários. `provisional-stage/` preserva os registros anteriores sem reescrever seu estado `in_progress`; seus índices históricos referem-se ao layout provisório.
- `exact-source/`: seleção de arquivos do Git exato de produto; `final-selected-source-manifest.json` registra a seleção. Não é o tar completo de fonte.
- `reviews/`: revisões visuais independentes dos 66 PNG, auditoria estática de 71 ferramentas, controle de entrega e logs completos. Relatórios anteriores mantêm seus estados temporais próprios; revisão estática do controle não aprova sua futura execução.
- `collection-tools/`: coletores e montadores locais derivados, identificados separadamente do código de produto.
- `inventory.json` e `SHA256SUMS`: tamanho, SHA-256, natureza e origem de cada arquivo retido. Verificação local: `sha256sum -c SHA256SUMS` a partir deste diretório.

O diagnóstico de janela tem escopo específico: apresentação automática e restauração são deliberadamente desativadas. Seu bundle inicial mínimo não é tratado como instalador; existe também auditoria no aplicativo completo instalado. A montagem desta evidência não equipara hashes early/installed ao binário empacotado quando assinatura/empacotamento mudam legitimamente os bytes.

Não foram retidos tar/ZIP de fonte, tar/ZIP binários grandes ou payload instalável. As ausências, hashes e tamanhos constam de `staging-summary.json`. Caminhos absolutos dentro dos relatórios originais apontam ao ambiente de coleta e são preservados como recebidos. Nenhuma evidência de 81769db foi usada em substituição à fonte atual.

Capturas estáticas e árvores AX não aprovam cliques, arraste, animações, rolagem completa ou VoiceOver humano. O OCR mostrado usa tesseract/inglês em exemplo português e tem erros de reconhecimento registrados; M4 físico, Neural Engine, energia, IA real elegível e integrações externas continuam exigindo evidência própria. Os limites de implementação estão na auditoria de escopo preservada.
