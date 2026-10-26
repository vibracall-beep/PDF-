# Revisão independente do focal 8770950

Fonte `8770950674f5e026dda5f3f9a0ae479e337f06d8`; run `40248300537`, tentativa 1. Revisão estática/visual pelo agente scope_audit dos 14 PNGs originais e dos dois JSONs nativos. Nenhum arquivo original foi modificado, nenhum aplicativo foi executado localmente e nenhum gate foi alterado. Isto não é uma avaliação humana de acessibilidade.

## Resultado

**Não aprovado.** A compilação e o transporte do binário são fatos distintos da falha de captura/validação. Os dois processos preservaram sete imagens e os relatórios continuam falhando nos mesmos quatro checks. A observação não localizou os três controles necessários e, portanto, não produziu qualquer medição de contraste. Há também um defeito visual separado confirmado na personalização do macOS 26.

## Barra de ferramentas e geometria

Nos 12 quadros do espaço de trabalho, a topologia agora registra um `NSToolbarView` real, pertencente à janela e não oculto, porém com `directChildCount = 0`. Nenhum dos IDs de comandos/personalização foi selecionado; `controls` e `measurements` permanecem vazios. Isso documenta a insuficiência da observação AX usada, não um contraste numericamente reprovado. O observador não recebeu priming AX.

Todos os sete quadros de cada processo registram janela 29, 1050×772 e escala 1. Os estilos efetivos de aplicação, janela e conteúdo correspondem ao tema solicitado. `same-real-window` também depende de ausência de erros de seleção; sua falha não demonstra troca de janela nem geometria inválida.

Revisei cada um dos 14 PNGs originais. Os três ícones da toolbar estão visualmente legíveis em todos os 12 quadros do espaço de trabalho, inclusive os dois dark-attached e o dark-recreated de cada sistema. O defeito branco sobre branco do cross37 não aparece nessas capturas. Isto não substitui o gate numérico que continua sem medições, nem aprova outras telas ou todos os cenários.

## Personalização: defeito preservado e nova evidência

No macOS 26, o seletor Equilibrado, ao lado de Espaçamento, e o menu Restaurar continuam invisíveis. O PNG é byte a byte idêntico ao do focal 2f (`a8cc670cd1a3dc7ad6d783a8634d30caf4348e1b680600d9d4392445a4683fe2`). No macOS 27, ambos aparecem e o PNG também é idêntico ao respectivo 2f (`14d4dea097ab54f98171573ca1e289d83935d81b50c3340f1c92f6b00b00cf1b`). Portanto, a correção de reentrada não alterou esses dois resultados visuais.

Após o PNG, o observador nativo do macOS 26 encontrou cinco `NSPopUpButton`. Todos relatam `effectiveAppearance = DarkAqua` e `effectiveStyle = dark`, enquanto aplicação, janela e conteúdo relatam Aqua/light. Equilibrado e Restaurar têm títulos reais, `alpha = 1`, `hiddenOrHasHiddenAncestor = false` e bounds coincidentes com as regiões brancas. Os outros três controles ficam abaixo do recorte visível e não foram julgados visualmente. O relatório JSON acompanha contagens RGB dos dois bounds visíveis, derivados das coordenadas nativas, sem coordenadas fixas incorporadas ao produto.

No macOS 27, a mesma observação retorna zero `NSPopUpButton`, embora os controles sejam visíveis no PNG. A ausência desse tipo nativo não demonstra ausência de controles SwiftUI.

A divergência de aparência interna está observada. Ainda não há prova de qual override, ancestral ou transição a produziu, nem de que ela seja a única causa dos pixels brancos. A ordem de construção, o estado anterior e o efeito eventual de habilitar um cliente AX continuam hipóteses, sem justificativa para priming que mascare o uso comum.

## Preservação

Todos os 14 hashes e tamanhos foram recalculados e coincidem com os JSONs nativos. O arquivo irmão `.json` retém caminhos, hashes, topologia, medições vazias, erros, estilos, providers dos pop-ups e a comparação exata com 2f para cada quadro. Os originais continuam sob `/workspace/.cache/pdf-appearance-8770950-40248300537/extracted`.
