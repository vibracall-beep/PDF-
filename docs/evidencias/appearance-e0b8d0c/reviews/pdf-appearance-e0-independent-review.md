# Revisão independente do focal e0b8d0c

Fonte `e0b8d0cef2e66fe1a6d41db4fe9e04c5c50510b2`; run `40249767201`, tentativa 1. Scope_audit abriu e revisou todos os 14 PNGs originais, leu os JSONs correspondentes e recalculou hashes/tamanhos. Nenhum original, código, documento do repositório ou gate foi modificado. A revisão visual por agente não equivale a avaliação humana de acessibilidade.

## Resultado

**O focal continua sem aprovação global**, pois a observação AX não seleciona os três controles de toolbar e não existe medição de contraste. Separadamente, o defeito dos dois controles invisíveis na personalização do macOS 26 foi corrigido no percurso capturado nesta execução.

## Personalização do macOS 26

O seletor Equilibrado e o menu Restaurar aparecem e estão legíveis no PNG atual. SHA256: `829ea541dc6e47839f37d0cfc98b10646dcba082dd38e7fec334b0e407e631f5`. Os mesmos dois bounds estavam integralmente brancos no focal 877, cuja imagem foi preservada. A comparação RGB no JSON irmão usa bounds derivados dos providers nativos pós-PNG, sem coordenadas fixas no produto.

Os cinco NSPopUpButton agora relatam override Aqua e aparência efetiva light. Todos os ancestrais registrados também são light e não há truncamento das cadeias. Aplicação, janela e conteúdo continuam light. Antes, em 877, os cinco controles relatavam DarkAqua/dark com aplicação/janela/conteúdo claros. Os três controles abaixo do recorte não foram avaliados visualmente nesta imagem.

Este resultado demonstra correção visual nesse caminho após a troca para applicationColorScheme local. Não prova todas as transições possíveis, funcionamento por clique ou ausência de outras falhas. As novas observações nativas foram apenas de leitura; não houve priming AX, alteração de imagem ou aumento de espera para esta correção.

## macOS 27 e demais imagens

A imagem de personalização do macOS 27 permanece byte a byte idêntica à do focal 877: `14d4dea097ab54f98171573ca1e289d83935d81b50c3340f1c92f6b00b00cf1b`; Equilibrado e Restaurar continuam visíveis. Zero NSPopUpButton nesse sistema não significa ausência de controle SwiftUI.

Revisei os 12 quadros restantes: os três ícones da toolbar estão visualmente legíveis nos temas claros/escuros, nas duas capturas escuras consecutivas e na volta da personalização. Não observei a antiga toolbar branca sobre branco do cross37. Esta avaliação visual não substitui a medição formal pendente nem aprova o aplicativo completo.

## Falha de observação ainda presente

Cada quadro workspace tem um NSToolbarView real registrado, porém seus filhos AX diretos continuam vazios. `controls=[]` e `measurements=[]`; portanto não houve reprovação numérica de contraste, mas ausência de medição. Os quatro checks que falham permanecem: same-real-window, three-controls-central-contrast-every-workspace-frame, attached-toolbar-identities-preserved e toolbar-controls-return-after-customization.

A janela permanece 29 nos sete quadros do macOS 26 e 30 nos sete quadros do macOS 27, sempre 1050×772, escala 1. A falha same-real-window inclui erros de seleção e não demonstra mudança de janela.

A topologia nativa nova registra cinco itens públicos de toolbar por quadro workspace e árvores de 32 NSViews no macOS 26 / 34 no macOS 27, sem truncamento. Os itens Hide Sidebar, Comandos e Personalizar possuem views reais/bounds registrados. Estes dados não foram usados para substituir silenciosamente a seleção falha nem produzir aprovação retrospectiva. O diagnóstico técnico da estratégia de seleção é separado desta revisão visual.

## Preservação

Os 14 tamanhos e hashes recalculados coincidem com os relatórios nativos. O JSON irmão registra cada original, SHA, tamanho, observação visual, estilos, topologias, erros, medições vazias, providers/ancestrais e comparação exata com 877. Originais em `/workspace/.cache/pdf-appearance-e0b8d0c-40249767201/extracted`.
