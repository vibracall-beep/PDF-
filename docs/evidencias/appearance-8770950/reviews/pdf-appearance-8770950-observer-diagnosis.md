# Diagnóstico técnico do focal 8770950

Fonte `8770950674f5e026dda5f3f9a0ae479e337f06d8`, run `40248300537`, tentativa 1.

A falha do observador permanece anterior aos pixels. Todos os 24 snapshots workspace (antes/depois, seis fases por sistema) encontram uma NSToolbarView real e visível com AXToolbar, porém zero filhos diretos. Leitura moderna, legacy pública anunciada e filhos de navegação não bastaram. Os três controles não foram selecionados; nenhuma medição nativa de contraste foi concluída. Os quatro checks reprovados são as consequências dessa seleção ausente, sem provar mudança da janela.

A personalização no macOS 26 acrescenta evidência concreta: os cinco NSPopUpButton observados têm DarkAqua/dark, apesar de app/janela/conteúdo Aqua/light. Equilibrado e Restaurar têm alpha 1, hidden false e bounds internos à janela. Nas regiões correspondentes do PNG original, todos os 2784 pixels de Equilibrado e todos os 2568 de Restaurar são RGB255/255/255. Os bounds foram observados após o PNG; não há prova individual de estabilidade antes/depois. Os três outros pop-ups estão fora do viewport; nenhuma conclusão visual é atribuída a eles.

O PNG customization do macOS 26 é byte a byte idêntico ao focal 2f, SHA256 `a8cc670cd1a3dc7ad6d783a8634d30caf4348e1b680600d9d4392445a4683fe2`. A falha visual persiste. No macOS 27, os dois controles estão visíveis, embora nenhum NSPopUpButton nativo tenha sido observado. Isso reforça que ausência desse provider não significa ausência do controle SwiftUI.

Foram abertos os dois PNGs de personalização para este diagnóstico. A revisão independente de todos os 14 originais pertence a scope_audit (`/tmp/pdf-appearance-877-independent-review.{md,json}`). Este relatório não aprova contraste nem aplicativo, não atribui o mismatch a um ancestral ainda não observado e não propõe priming como correção. O JSON companheiro retém todos os hashes, snapshots, checks e medidas dos originais analisados. Nenhum código ou original foi alterado.
