# Revisão independente do focal 2f3134a

Fonte `2f3134a41229054f41a176d6a48cc6c23e388b77`, execução 40246632222, tentativa 1. Revisão dos 14 PNGs originais, dos dois JSONs nativos e do código exato; nenhum pixel, gate ou produto foi alterado. A compilação e a restauração do mesmo bundle no 27 são etapas concluídas; os dois diagnósticos terminaram em falha.

## Falha automatizada observada

Os dois relatórios têm sete frames na ordem prevista; tema efetivo de app/janela/conteúdo acompanha Claro/Escuro/Sistema. Todos os snapshots têm windowNumber 29, 1050×772 e backingScale 1. Os campos windowToolbarPresent/windowToolbarVisible são verdadeiros nos seis frames de workspace; o material alterna VibrantLight/VibrantDark. Contudo, workspaceToolbarProviderCount é zero e controls está vazio em todos esses frames. **Nenhuma medição central de contraste foi executada.**

Falharam os checks de janela, contraste, identidade anexada e retorno dos controles. O nome `same-real-window` agrega também errors dos snapshots: sua reprovação não é evidência de troca de janela ou dimensão incompatível. A recusa dos checks dependentes decorre da ausência dos providers identificados, e não de um contraste medido abaixo de 3:1. Ausência de prova continua sendo falha do gate; não se deve aprovar controles ausentes ou preencher identidades/bounds artificialmente.

A comparação do código identifica diferenças concretas em relação à árvore AX histórica usada como base:

- `AccessibilityAudit.attribute` consulta os getters públicos modernos e, quando necessário, o protocolo público legado apenas para atributos anunciados. `ToolbarRenderingAudit.attribute` da fonte 2f consulta somente os modernos.
- O percurso histórico une accessibilityChildren e accessibilityChildrenInNavigationOrder; o novo observador só usa accessibilityChildren.
- `AccessibilityAudit.write` faz a consulta pública do próprio processo em worker antes de ler os providers, para permitir a materialização dos providers virtuais. O novo observador não fez essa consulta.

Essas diferenças justificam corrigir a observação e registrar a topologia real antes/depois. Não demonstram isoladamente qual delas explica a ausência em 2f; isso depende do próximo ensaio nativo. Não se constatou erro geométrico nos snapshots existentes.

## Revisão visual dos 14 originais

Foram abertos os sete PNGs de `PDF-appearance-sdk26` e os sete de `PDF-appearance-same-binary-xcode27`: inicial claro, dois escuros com toolbar anexada, personalização clara, retorno ao workspace escuro, retorno claro e sistema.

Os 12 quadros de workspace mostram os três símbolos da toolbar legíveis, incluindo os dois `dark-recreated`. A falha branco sobre branco vista no cruzado 37 não foi observada nessas imagens. Isso é evidência visual limitada aos quadros, sem aprovação automática, de todo o aplicativo ou de interação humana.

**Defeito visual separado:** em `PDF-appearance-sdk26/PDF-appearance.customization.png` o seletor de Espaçamento e o menu Restaurar não aparecem nas posições reservadas. O rótulo Espaçamento, os demais ajustes e Importar/Exportar aparecem. Os dois controles estão visíveis no quadro equivalente 26→27 e no histórico 37 nativo26.

A medição somente para documentação, sem uso de coordenadas fixas no produto, confirmou:

| Região no original SDK26 | Pixels | Pixels exatamente brancos |
|---|---:|---:|
| Espaçamento `(214,422,330,447)` |2.900|2.900|
| Restaurar `(124,699,231,724)` |2.675|2.675|

No original26→27 há respectivamente 453 e 351 pixels com algum canal abaixo de 240 nessas regiões, correspondendo aos controles visíveis. O PNG SDK26 tem SHA-256 `a8cc670cd1a3dc7ad6d783a8634d30caf4348e1b680600d9d4392445a4683fe2`; o equivalente 27 tem `14d4dea097ab54f98171573ca1e289d83935d81b50c3340f1c92f6b00b00cf1b`. As métricas completas estão em `pdf-appearance-2f-customization-observations.json`.

Há apenas um frame dessa tela por sistema, sem topologia/estilos específicos dos dois controles. Não se pode afirmar que foram removidos, que são inoperantes, que a falha é permanente ou que foi introduzida pela ponte de aparência. O histórico 37 já havia feito uma consulta AX pública e o focal 2f não; essa diferença impede atribuir causalidade apenas à comparação. Se uma consulta AX fizer os controles aparecerem, isso não prova por si só a correção no uso comum sem cliente assistivo.

## Conclusão limitada

A toolbar está visualmente legível nos quadros inspecionados, mas a observação automatizada falhou e precisa ser corrigida sem reduzir os requisitos. O quadro de personalização do SDK26 tem duas ausências visuais concretas que permanecem separadas dessa correção. Não há aprovação do focal, do pacote completo, do teste cruzado normal ou de entrega.
