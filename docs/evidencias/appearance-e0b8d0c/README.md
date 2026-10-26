# Aparência e0b8d0c — focal reprovado; correção visual específica observada

Fonte/controlador `e0b8d0cef2e66fe1a6d41db4fe9e04c5c50510b2`, run `40249767201`, tentativa 1, jobs 26 `121338897259` e27 `121340681527`. **Build/pack SDK 26 e restore 27 passaram. Captura, observador e validação falharam nos dois sistemas: sete PNGs por sistema, zero medidas nativas de contraste.** A revisão dos 14 originais confirma Espaçamento/Equilibrado e Restaurar visíveis no percurso atual de Personalização 26, com providers/ancestrais claros. Isso corrige o defeito visual específico nesse percurso; o focal global e a entrega permanecem sem aprovação.

| Resultado | Evidência atual |
|---|---|
| Compilação/empacotamento SDK 26 e restore 27 |Etapas API success |
| Capturas originais |14 PNGs íntegros; inventários15/14 |
| Checks nativos por sistema |8 true,4 false; reportes/recibos failed |
| Observações de workspace |24 snapshots antes/depois com AXToolbar sem filhos;12 toolbarReports sem medidas |
| Personalização 26 atual |Equilibrado/Restaurar visíveis; popups e ancestrais light/Aqua |
| Matriz completa / instalação / entrega |Não aprovadas por este focal |

A nova hierarquia nativa e os itens públicos estão preservados nos JSON. Sua existência não sobrepõe os checks falhos de seleção/identidade/contraste. Uma imagem estática não valida cliques, animações, conteúdo fora da área visível, VoiceOver humano ou todas as rotas de personalização. A ausência antiga dos controles em 877 não foi apresentada como falha atual de e0. Nenhuma causa única da falha do observador foi inferida por esta retenção.

## Proveniência

- `originals/downloads/`: dois ZIPs de evidência autenticados pelo digest GitHub e o ZIP oficial de logs. Cada evidência foi baixada uma vez; não há ZIP de transporte do bundle.
- `originals/extracted/`:15/14 membros originais, incluindo14 PNGs, reportes e recibos failed, manifestos e logs. Nenhuma imagem foi editada.
- `originals/official-attempt-logs/`: dois agregados;31 membros completos por etapa/agregados estão no ZIP original. O endpoint autenticado de logs não fornece digest independente; o SHA registrado identifica os bytes recebidos.
- `provenance/`: APIs antes/depois, configuração/recibos e vínculo dos quatro hashes de preflight ao Git exato e0.
- `exact-source/`:13 seleções da fonte/controlador usadas no diagnóstico/validação; não é o código completo do aplicativo.
- `reviews/`: recontagem factual offline, revisão independente dos 14 originais e diagnóstico técnico; nenhuma aprova a entrega.
- `local-preflight/`: sintaxe de 90 Swift, sem typecheck do SDK, e hashes do candidato. A redação preparatória sobre correção ainda não provada é preservada; o resultado posterior do percurso capturado consta da revisão independente.
- `collection-tools/`: coletor environment congelado, delta (somente acrescenta PDFApp.swift e CustomizationView.swift à seleção Git),18 testes offline, preparação, configurações final/rascunho, log único da coleta e scripts desta retenção.

## Verificações e limites

Os dois digests de ZIP e todos os membros, os 14 fingerprints de frame e PNGs (CRC/raster), o ZIP oficial e os 13 arquivos de fonte foram reconferidos offline. As sete linhas de captura por sistema coincidem no artefato, etapa oficial e agregado. Os 21 testes do checker 26 foram recontados uma vez; os 18 testes locais verificam somente o coletor. Exit0 da coleta significa que as falhas foram preservadas corretamente, não que o aplicativo passou.

Os manifestos são byte idênticos: SHA `727334f713191e0913e8a353cd714646b2679806604f7522304342bec0858514`. Declaram tar de 5145129 bytes com SHA `a4f0a7b114ce5180144cfc471283e5631cf693877a21e1cac74398078be50e39`. O vínculo é baseado em API, pack/restore e metadados; esse tar/app não foi baixado, extraído ou executado localmente. O gate geral de bundle aprovado continua falso devido aos reportes/recibos falhos. Bundle mínimo não é instalador completo.

`inventory.json` registra bytes/SHA/origem; `SHA256SUMS` cobre os arquivos e o índice. Confira com `sha256sum -c SHA256SUMS`. Não há TAR/app ou evidência antiga relabelada como atual. Esta retenção focal não contém/aprova matriz nativa completa, instalação final, M4 físico, energia/Neural Engine, IA real, serviços de produção, scanner, VoiceOver humano ou ausência universal de erros. Nenhuma aprovação de outra fonte foi transferida.
