# Diagnóstico dos itens públicos da toolbar — focal e0

A execução 40249767201 continua reprovada: o aplicativo selecionou zero controles e não produziu medidas de contraste. Este relatório não altera esse resultado.

Os 24 snapshots workspace (antes/depois, seis fases em dois sistemas) oferecem uma alternativa pública comprovável: um NSToolbarItem com label/paletteLabel Comandos, outro Personalizar e outro com o nome observado do sidebar. Cada item possui uma view real e única, pertencente à mesma janela/toolbar; identidade, aparência e geometria coincidem com a observação da hierarquia NSView. A evidência foi conferida em todos os 24 snapshots. Os metadados completos não mudam durante cada PNG, e as identidades permanecem nas três primeiras fases; recriam-se após Personalização nos dois sistemas.

A implementação seguinte pode selecionar pelos labels e paletteLabels exatos e validar item.view, descendência da única toolbar, janela, visibilidade, alpha, bounds e estabilidade. Deve registrar o itemIdentifier real separado do auditKey lógico, sem usar UUID, identifier interno do sistema, classe privada, ordem ou coordenada fixa para escolher o controle. O limiar 3:1 e todos os demais gates permanecem. Essa proposta e sua implementação exigem um novo focal nativo.

No primeiro PNG de personalização do macOS 26, Equilibrado e Restaurar estão visíveis. Os cinco NSPopUpButton e seus ancestrais agora têm aparência clara; isso é limitado ao percurso capturado. A revisão dos 14 originais pertence a scope_audit. O JSON companheiro preserva hashes, dimensões, checks nativos e a evidência individual dos 24 snapshots.
