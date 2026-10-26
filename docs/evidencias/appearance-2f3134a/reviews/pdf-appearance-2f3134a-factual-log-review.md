# Revisão factual do focal 2f3134a — execução reprovada

Fonte/controlador `2f3134a41229054f41a176d6a48cc6c23e388b77`, run `40246632222`, tentativa 1. Os dois jobs terminaram em **failure**. Esta revisão somente leu originais autenticados; não executou artefatos, alterou produto/gates ou estabeleceu causa da falha.

| Job | Sistema reportado | PNGs produzidos | Checks true/false | Medidas de contraste |
|---|---|---:|---:|---:|
| compile-sdk26 · 121329466580 | Version 26.6.2 (Build 25G83) | 7 | 8/4 | 0 |
| same-binary-xcode27 · 121330497217 | Version 27.0.1 (Build 26A434) | 7 | 8/4 | 0 |

Build/pack do SDK26 e restore do mesmo bundle no27 passaram nas etapas da API. Captura e validação falharam nos dois sistemas, e os artefatos de falha foram publicados. O job de origem registra 21 testes do checker com OK; isso não substitui o ensaio real reprovado.

Os sete arquivos PNG existem em cada sistema e coincidem com nome, bytes, SHA-256 e dimensões registrados no reporte nativo. A releitura offline com o parser do Git exato conferiu CRC e raster dos14 originais. São arquivos de1050×772; essa integridade não aprova aparência.

## Fatos registrados nos reportes

Os dois reportes falham nos mesmos quatro IDs:

- `same-real-window`
- `three-controls-central-contrast-every-workspace-frame`
- `attached-toolbar-identities-preserved`
- `toolbar-controls-return-after-customization`

Cada sistema tem seis toolbarReports, todos com `measurements=[]`. Os erros repetidos são `Expected exactly one direct toolbar control: autoSidebar`, `...pdf.commands.toolbar` e `...pdf.customize.toolbar`. As snapshots registram `workspaceToolbarProviderCount=0` e nenhuma entrada em `controls`. Portanto estes JSON não contêm uma medição de contraste concluída. Não concluí que as cores foram aprovadas ou reprovadas por uma medida inexistente.

As snapshots/logs de captura registram número de janela29 durante as sete fases de cada sistema. Esse dado numérico não altera o check `same-real-window=false`, nem prova por si só a identidade dos controles. As listas de toolbarItemIdentifiers e erros completos permanecem no JSON derivado e nos originais para investigação independente.

Drenagem do trabalho, limpeza privada, ausência de documento e liberação das sobrescritas no modo Sistema são registrados como true pelos respectivos checks. Não houve marcador de timeout procurado nos logs de captura; os reportes foram escritos com `status=failed; originalFrames=7`. A causa dessa falha não foi inferida aqui.

## Vínculo de transporte, sem executar o bundle

SDK declarado: `26.5`. Os dois `appearance-bundle.json` são byte idênticos, SHA-256 `9aceea76b8efd1cccf43abf6469b2ba1ed885220a35daa4756024331a7c9a937`. Declaram tar `0aa4044312b4486c7b712fac98ffb035cbffa08f8788729f9bada1d74e635868`, 5104036 bytes, e o mesmo executável/Info.plist/lock/CodeResources. A etapa de restore/verificação passou na API. Este revisor não baixou nem executou o tar; o flag geral do coletor permanece falso porque os recibos de validação falharam.

## Integridade da coleta e limites

O primeiro main do coletor interrompeu a extração ao tratar incorretamente o resultado casefold de `_name` como nome original. Esse defeito local foi corrigido com autorização, preservando comparação literal/allowlist e recusando colisões. A regressão passou com nomes maiúsculos legítimos e colisões por caixa. O ZIP26 já autenticado foi reutilizado; cada artefato tem uma única tentativa de download. Esse incidente não é evidência da causa da falha do aplicativo.

ZIPs, logs oficiais agregados, snapshots API, reportes e14 PNG originais permanecem em `/workspace/.cache/pdf-appearance-2f3134a-40246632222`. Seus caminhos, hashes e bytes constam do JSON acompanhante. O ZIP oficial de logs foi obtido do endpoint autenticado, que não fornece digest independente.

Não há aprovação visual nesta leitura factual. A revisão visual independente dos PNGs ocorre separadamente. A fonte37f5b65 continua visualmente reprovada no seu teste cruzado; nenhum resultado anterior foi transferido para2f3134a. Não houve matriz completa, validação de instalação/engine, VoiceOver humano, medição física deM4 ou entrega aprovada.
