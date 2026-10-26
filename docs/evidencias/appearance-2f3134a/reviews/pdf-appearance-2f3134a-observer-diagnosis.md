# Diagnóstico do observador — focal 2f3134a

Fonte e execução: `2f3134a41229054f41a176d6a48cc6c23e388b77`, run `40246632222`; SDK26 e mesmo binário no macOS27.

Os originais JSON e capture.log confirmam uma falha de seleção de providers anterior à análise dos pixels. Nos seis estados workspace de cada sistema, o observador encontra a toolbar e a aparência solicitada, mas não seleciona os três controles: `workspaceToolbarProviderCount=0`, `controls=[]`, `measurements=[]`. As quatro reprovações agregadas decorrem dessa falha; não provam mudança de janela ou contraste insuficiente. Nenhuma medição nativa de contraste foi concluída.

O observador novo lê somente getters modernos e accessibilityChildren. A auditoria existente também lê atributos públicos legacy anunciados e filhos de navegação; a árvore histórica ainda havia sido observada depois de consulta AX ao próprio processo. O material original não contém a topologia dos filhos diretos, portanto não permite isolar qual dessas diferenças causou o resultado. A correção de acesso compartilhado precisa de novo ensaio nativo.

Este relatório não declara uma revisão visual própria das 14 imagens. A revisão independente de scope_audit registra as imagens e o bloqueador dos controles Espaçamento/Restaurar invisíveis em customization26. Não há aprovação de contraste ou do aplicativo. O JSON companheiro conserva nomes, hashes, dimensões e resultados originais por fase.
