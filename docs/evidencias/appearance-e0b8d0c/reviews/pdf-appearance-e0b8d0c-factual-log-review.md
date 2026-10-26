# Revisão factual e0b8d0c — focal reprovado

Fonte/controlador `e0b8d0cef2e66fe1a6d41db4fe9e04c5c50510b2`, run `40249767201`, tentativa1. **Build/pack SDK26 e restore27 passaram; captura e validação falharam em ambos os sistemas.** A coleta exit0 preservou falhas; ela não aprovou o aplicativo. Esta releitura offline não executou artefatos, fez rede ou alterou produto/gates.

| Job | Sistema | PNGs íntegros | Checks true/false | Medidas nativas |
|---|---|---:|---:|---:|
| compile-sdk26 · 121338897259 | Version 26.6.2 (Build 25G83) |7|8/4|0|
| same-binary-xcode27 · 121340681527 | Version 27.0.1 (Build 26A434) |7|8/4|0|

Os14 PNG atuais coincidem com nome, tamanho, SHA e dimensões dos frames; o parser do Git exato conferiu CRC/raster. As sete linhas de captura de cada artefato coincidem com as linhas da etapa oficial e do agregado. O job26 registra uma suíte de21 testes do checker com OK; o job27 não repetiu essa suíte. Isso não representa a matriz nativa completa.

Os24 snapshots antes/depois dos12 estados de workspace continuam encontrando AXToolbar sem filhos diretos e sem seleção dos três controles. Todos os12 toolbarReports têm measurements vazio. A nova topologia nativa e os itens públicos estão registrados nos JSON originais; sua existência não sobrepõe a seleção/checks reprovados. Os mesmos quatro IDs falharam: same-real-window, three-controls-central-contrast-every-workspace-frame, attached-toolbar-identities-preserved e toolbar-controls-return-after-customization.

Nesta fonte, os cinco NSPopUpButton observados em Personalização26 reportam light/Aqua dentro de aplicação/janela/conteúdo light/Aqua. Esse fato não deve ser substituído pelo resultado DarkAqua do run877 anterior, nem aprova aparência sem abrir os pixels atuais. A revisão visual independente é separada desta recontagem factual. Não foi inferida causa única para a falha do observador.

Os dois manifestos são byte idênticos, SHA `727334f713191e0913e8a353cd714646b2679806604f7522304342bec0858514`. Declaram tar de5145129 bytes, SHA `a4f0a7b114ce5180144cfc471283e5631cf693877a21e1cac74398078be50e39`. Pack/restore passaram nas etapas originais, porém o gate geral de aprovação do vínculo continua falso porque os reportes/recibos falharam. O tar/app não foi baixado, extraído ou executado localmente.

Cada ZIP de evidência foi baixado uma vez. Os dois digests GitHub, todos os membros e o ZIP oficial de logs foram reconferidos. O endpoint de logs autenticado não fornece digest externo independente. Nenhum incidente de coleta ocorreu nesta execução. Os13 arquivos de fonte/controlador usados na retenção coincidem com o Git exato e0; nenhum arquivo de evidência anterior foi relabelado como atual.

Não há aprovação visual, de instalação, de produto completo ou de entrega nesta leitura. O foco é um bundle mínimo e sete estados por sistema; não mede M4 físico/energia/Neural Engine, VoiceOver humano, IA real, scanner ou serviços de produção. Resultados anteriores não foram transferidos.
