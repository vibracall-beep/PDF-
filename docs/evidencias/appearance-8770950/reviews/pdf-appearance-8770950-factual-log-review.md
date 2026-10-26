# Revisão factual 8770950 — focal reprovado

Fonte/controlador `8770950674f5e026dda5f3f9a0ae479e337f06d8`, run `40248300537`, tentativa1. **Build/pack do SDK26 e restore do mesmo bundle no27 passaram; captura e validação falharam em ambos.** Esta revisão apenas releu originais autenticados, sem rede, executar artefatos ou modificar produto/gates. Não estabeleceu causa da falha.

| Job | Sistema | PNGs íntegros | Checks true/false | Medidas nativas |
|---|---|---:|---:|---:|
| compile-sdk26 · 121334482597 | Version 26.6.2 (Build 25G83) |7|8/4|0|
| same-binary-xcode27 · 121336057194 | Version 27.0.1 (Build 26A434) |7|8/4|0|

Os14 PNG coincidem com nome, tamanho, SHA e dimensões dos frames; o parser do Git exato conferiu CRC/raster. As sete linhas de captura de cada artefato coincidem com as linhas do log oficial por etapa e do agregado, sem duplicar contagens. O job26 contém uma suíte de21 testes do checker com OK; o job27 não repetiu essa suíte. São controles do diagnóstico, não a matriz nativa completa.

Os24 snapshots antes/depois dos12 estados de workspace encontram um NSToolbarView/AXToolbar, com zero filhos diretos e nenhuma seleção dos três controles. Todos os12 toolbarReports têm measurements vazio. Os quatro checks reprovados são same-real-window, three-controls-central-contrast-every-workspace-frame, attached-toolbar-identities-preserved e toolbar-controls-return-after-customization. Não se concluiu uma medida de contraste; IDs numéricos de janela não substituem esses checks falhos.

A revisão visual independente de scope_audit abriu os14 originais. Ela registra12 estados de workspace visualmente legíveis, mas reprova Personalização26: Espaçamento/Equilibrado e Restaurar estão ausentes. A revisão técnica registra cinco NSPopUpButton DarkAqua em contexto Aqua; somente os dois controles com bounds visíveis são comparados à região branca do PNG. Nenhuma causa única ou duração do defeito foi inferida. A inspeção estática não aprova interação, animação ou VoiceOver.

Os manifestos de bundle são byte idênticos: `06e2b831c2fb37d8b2b32c2887d0b729f59eb9e8862b692062bbd4971e3f1816`. Declaram tar de5119116 bytes, SHA `1c6f6207274033133c69e997599e81b51209280ccaa4d09f6e6b73473e618a41`. O coletor não baixou/extraiu/executou esse tar/app. O gate geral de vínculo aprovado continua falso porque os reportes/recibos falharam.

Cada ZIP de evidência foi baixado uma vez; seus digests GitHub e todos os membros foram reconferidos offline. O ZIP oficial de logs e seus membros foram reconferidos pelos hashes registrados; esse endpoint autenticado não oferece digest externo independente. Não houve incidente de coleta neste run. O diff/testes18 do coletor registram a única alteração de retenção de fonte, acrescentando AccessibilityAudit.swift.

O preflight local tem hashes dos quatro arquivos que correspondem ao Git877: sintaxe de90 Swift sem typecheck do SDK e21 controles locais. Sua referência histórica ao log de whitespace2f permanece literal, não é evidência do run877. A matriz nativa completa877 não foi executada. Instalação, produto completo, M4 físico, serviços reais e entrega não foram aprovados. Nenhuma aprovação anterior foi transferida.
