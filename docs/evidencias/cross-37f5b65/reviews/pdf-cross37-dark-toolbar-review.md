# Revisão independente — contraste da toolbar no cruzado 37f5b65

Revisão somente leitura; nenhum PNG, produto, workflow ou gate alterado. Fonte: `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`; cruzado usa o binário construído no macOS 26 e executado no 27.0.1. A aprovação automatizada de captura não cobre o defeito visual observado.

## Constatação reproduzível

Os três PNGs originais `PDF-preview.escuro.png` foram abertos. O cruzado tem símbolos quase brancos sobre fundos quase brancos nos controles Comandos, Personalizar e no botão de sidebar gerado pelo sistema. Os dois builds nativos apresentam símbolos legíveis. São 1050×772 RGBA nos três casos. O perfil ICC incorporado é byte a byte igual entre nativo27 e cruzado (SHA-256 `b6c0968d40a5b85c695bb708a72c640c8b96d0756e4d41d4295130945fc668e7`).

A leitura direta de pixels, sem transformação ou edição de imagem, está em `pdf-cross37-dark-toolbar-pixels.json`. Nas caixas internas dos símbolos:

| Controle | Nativo26: mínimo–máximo | Nativo27: mínimo–máximo | Cruzado: mínimo–máximo |
|---|---:|---:|---:|
| Comandos | 20–231 | 43–223 | 251–254 |
| Personalizar | 20–224 | 43–220 | 251–254 |
| Sidebar | 30–232 | 22–220 | 251–255 |

Valores são luminância ponderada em escala 0–255; nessas regiões os pixels são neutros R=G=B. A tabela mede o defeito da imagem original; não certifica contraste de todo o aplicativo.

Comparação entre os originais nativo27 e cruzado:
- Toda a área abaixo da toolbar, retângulo `(0,52,1050,772)`, é **100% idêntica pixel a pixel**, em todos os canais RGB.
- O título e fundo fora dos controles, `(210,0,960,52)`, também são **100% idênticos**.
- O grupo à direita, `(968,8,1042,45)`, tem diferença média por canal 166,7157 e 88,532% dos pixels com algum canal divergindo mais de 20.
- O botão da sidebar, `(166,8,202,45)`, tem diferença média por canal 157,6086 e 80,180% dos pixels com algum canal divergindo mais de 20.

A divergência, portanto, está na toolbar compartilhada, incluindo controle criado pelo sistema; não há evidência de alteração global de cor, conteúdo ou escala do screenshot.

## Estado e tempos documentados

`MacPreview.swift:559–564` muda o tema para escuro, o acento, a apresentação de categorias e a rota de personalização para workspace antes da única captura escura. `capture(_:auditRequired:)` (linha 462) espera 1,5 s, força layout/display e inicia ScreenCaptureKit. `capture(_:to:)` (linha 190) valida identidade, visibilidade, geometria AppKit/WindowServer e dimensões antes/depois, mas não registra ou valida aparência efetiva.

| Origem | Início settle | Início ScreenCaptureKit | PNG escrito | Espera observada até SC | Tempo SC→PNG |
|---|---:|---:|---:|---:|---:|
| Nativo26 |1586,716|1588,778|1589,427|2,062s|0,649s|
| Nativo27 |2523,801|2525,382|2525,545|1,581s|0,163s|
| Cruzado26→27 |2018,948|2020,758|2021,654|1,810s|0,896s|

As três capturas registram `active=true`, `key=true`, `main=true`, `activationPolicy=0`, janela 1050×772, layout 1050×720, escala 1 e duas amostras geométricas. Houve reavaliação do builder durante a chamada ScreenCaptureKit no cruzado **e também no nativo26 legível**. Esse marcador isolado não explica o defeito.

A captura inicial clara e a captura posterior `lista` do cruzado têm pixels 39–255 na mesma caixa do comando, preservando contraste. Contudo, a sequência retorna imediatamente ao tema claro após o único frame escuro. Nenhum log existente registra `NSApp.appearance`, `window.effectiveAppearance`, aparência dos controles da toolbar ou um segundo frame mantendo escuro. **Não é possível concluir, apenas com esses originais, se a divergência persiste ou se foi uma transição.**

## Hipótese e prova necessária

A divergência específica de fundo/símbolo na toolbar é compatível com resolução discordante de aparência entre SwiftUI e o material AppKit. A raiz, ContentView e CustomizationView aplicam `preferredColorScheme`, mas não há ponte explícita de aparência de janela no produto 37. A simultaneidade de recriação da toolbar e mudança de tema é um possível gatilho, sem demonstração causal suficiente. SDK/runtime distintos também são uma diferença factual, não uma causa estabelecida.

Um teste curto significativo pode usar a **WindowGroup e toolbar reais do produto**, estado privado e nenhum documento/engine Python. Deve verificar: claro→escuro com toolbar existente; retorno de Personalização criando toolbar enquanto o tema muda (caso observado); escuro→claro→Sistema. Registrar em cada fase preferência solicitada, aparência efetiva de janela/conteúdo/controles e os bounds AX dos controles. Capturar dois frames reais em instantes distintos, sem alterar pixels ou materiais, distingue persistência de um frame transitório. O gate precisa inspecionar contraste da superfície renderizada nos bounds reais; igualdade dos traits sozinha não demonstra que o material foi composto corretamente.

Os dois positivos e o negativo autênticos acima permitem conferir o detector de regressão. Para o ensaio novo, coordenadas devem vir de bounds AX/NSView associados aos identificadores reais, não de recortes fixos presumidos para qualquer janela. Manter conteúdo, toolbar automática, Liquid Glass e verificações de geometria. Repetir apenas com um sleep maior não comprova correção de produto.

Os 33 estados de captura existentes contêm somente um estado escuro. Não demonstram tema escuro no leitor, formulários, Ajustes, janelas auxiliares ou inativas. A correção deve compartilhar uma política de aparência entre essas superfícies, com testes nos caminhos públicos relevantes e sem overrides fixos de cor para esconder o defeito.

## Originais consultados

- `/workspace/.cache/pdf-cross-37f5b65/extracted/PDF-cross-platform-validated/PDF-preview.escuro.png`
- `/workspace/.cache/pdf-cross-37f5b65/extracted/PDF-cross-platform-validated/PDF-cross-gui-capture.log`
- `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.escuro.png`
- `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-xcode-27/PDF-preview.escuro.png`
- `/workspace/.cache/pdf-native-37f5b65/collector-attempt-1-logs/0_native-application (macos-26).txt`
- `/workspace/.cache/pdf-native-37f5b65/collector-attempt-1-logs/1_native-application (xcode-27).txt`
