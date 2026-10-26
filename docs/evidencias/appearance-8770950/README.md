# Aparência8770950 — focal e revisão visual reprovados

Fonte/controlador `8770950674f5e026dda5f3f9a0ae479e337f06d8`, run `40248300537`, tentativa1, jobs26 `121334482597` e27 `121336057194`. **Compilar/empacotar no SDK26 e restaurar o mesmo bundle no27 passaram. Captura, observador e validação falharam nos dois sistemas. Foram produzidos sete PNGs por sistema, porém zero medidas nativas de contraste. A revisão visual focal também reprovou Personalização26. A matriz nativa completa877 não foi executada.** Nada aqui aprova instalação, aplicativo completo ou entrega.

| Resultado | Evidência atual |
|---|---|
| Compilação/empacotamento SDK26 e restore27 | Etapas API concluídas com success |
| Capturas originais |14 PNGs íntegros, sete de cada sistema; inventários15/14 |
| Checks nativos por sistema |8 true,4 false; reportes e recibos failed |
| Observações de workspace |24 snapshots antes/depois com AXToolbar e zero filhos;12 toolbarReports sem medidas |
| Personalização26 |Espaçamento/Equilibrado e Restaurar invisíveis; providers DarkAqua dentro de Aqua, sem causa inferida |
| Matriz completa877 / instalação / entrega |Não executada / não aprovada / não autorizada por estas evidências |

A revisão independente abriu todos14 originais. Os12 estados de workspace examinados parecem legíveis, mas isso não substitui as medições ausentes nem aprova o fluxo completo. Os controles ausentes em Personalização26 constituem um achado visual separado da falha do observador. Cinco NSPopUpButton reais reportam tema escuro em contexto claro; só os dois bounds visíveis foram relacionados à região branca do PNG. Capturas estáticas não aprovam cliques, animações, conteúdo que exige rolagem, VoiceOver humano ou acessibilidade completa.

## Proveniência

- `originals/downloads/`: os dois ZIPs de evidência com digest GitHub e o ZIP oficial de logs. Cada evidência foi baixada uma vez. O transporte tar/app não foi baixado ou retido localmente.
- `originals/extracted/`:15/14 membros originais, incluindo PNGs, reportes de falha, manifestos e logs. Nenhuma imagem foi editada.
- `originals/official-attempt-logs/`: dois agregados; logs por etapa estão no ZIP original. O endpoint oficial autenticado não fornece digest independente; o SHA registrado identifica os bytes recebidos.
- `provenance/`: snapshots API antes/depois, configuração/recibos do coletor e vínculo dos quatro hashes de preflight ao Git exato877.
- `exact-source/`:11 seleções de fonte exata usadas pelo controle e diagnóstico; não é o aplicativo completo.
- `reviews/`: revisão factual offline, revisão visual independente dos14 PNG e diagnóstico técnico do observador. Todos preservam a reprovação.
- `local-preflight/`: registro de sintaxe90 Swift sem typecheck SDK, controles21 e escopo preparatório. A referência histórica ao log de whitespace2f é preservada como referência; não incluímos esse log antigo como evidência atual.
- `collection-tools/`: coletor observer congelado, diff,18 testes offline, configurações final/rascunho, log desta coleta e script desta retenção. A única diferença do coletor revisado é reter AccessibilityAudit.swift do Git exato. O histórico de sua base não é um incidente deste run.

## Verificações e limites

Os digests de ambos os ZIPs, todos os membros, os14 fingerprints de frame e PNGs (CRC/raster), o ZIP/logs oficiais e os11 arquivos de fonte foram reconferidos offline. As sete linhas de captura por sistema coincidem entre log de artefato, etapa oficial e agregado; os21 testes do checker26 foram recontados uma vez. A retenção não executou binários, alterou produto/gates ou fez nova coleta.

Os manifestos são byte idênticos: SHA `06e2b831c2fb37d8b2b32c2887d0b729f59eb9e8862b692062bbd4971e3f1816`. Declaram tar de5119116 bytes com SHA `1c6f6207274033133c69e997599e81b51209280ccaa4d09f6e6b73473e618a41`. O vínculo é baseado em APIs, pack/restore e metadados, sem rehash local desse tar. O gate geral de bundle aprovado permanece falso devido aos reportes/recibos reprovados. Bundle mínimo não é instalador completo.

`inventory.json` registra bytes/SHA/origem; `SHA256SUMS` cobre todos os arquivos do índice e o próprio índice. Confira com `sha256sum -c SHA256SUMS`. Não há TAR, app ou ZIP de transporte nesta retenção compacta. Resultados anteriores não foram transferidos: nenhuma aprovação37/2f ou de outro candidato torna877 aprovado. Permanecem fora do escopo M4 físico, energia/Neural Engine, IA real, serviços de produção, scanner, VoiceOver humano e promessa de ausência universal de erros.
