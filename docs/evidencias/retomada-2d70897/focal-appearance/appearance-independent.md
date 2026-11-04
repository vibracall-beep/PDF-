# Revisão independente do focal de aparência 2d70897

Fonte/controlador: `2d708974d91c96dde422adf1d8a480a7c6b9d808`. Execução `40254721260`, tentativa 1. Revisão retomada em 28/10/2026, com os originais preservados da coleta anterior.

**Os 14 PNGs originais foram abertos individualmente em resolução original. Não foi encontrado bloqueador visual confirmado nos viewports capturados.** Os três ícones da barra estão legíveis em todos os 12 frames de workspace. Equilibrado e Restaurar aparecem e estão legíveis nas duas capturas de Personalização. Nenhuma aprovação visual de 9d foi herdada.

A rechecagem local conferiu os dois ZIPs contra seus hashes GitHub retidos, CRCs e todos os 29 membros extraídos; os 16 arquivos selecionados do controlador/aplicativo correspondem byte a byte à fonte Git. O ZIP de logs conserva os 31 membros e seus hashes. A consulta API não foi refeita nesta revisão offline.

O validador exato da fonte foi reaplicado aos relatórios e PNGs. Os dois sistemas têm **12 checks aprovados cada, 36 medidas ao todo e 24 snapshots antes/depois**. A conferência adicional vincula os três controles de cada snapshot aos rótulos públicos únicos do NSToolbarItem, ao item.view e à hierarquia nativa enraizada no AXToolbar real, com identidades, aparência, alfa e geometria correspondentes. Os tokens são preservados nas três primeiras fases; os provedores são recriados após Personalização. O modo Sistema libera os overrides de app/janela.

Contraste central mínimo nativo: **4,136177866:1 no macOS 26.6.2** e **6,877762169:1 no macOS 27.0.1**, acima do limiar 3:1. Valores conferidos nos relatórios e na fórmula; a conversão nativa ColorSync não foi reproduzida no Linux. Não é certificação WCAG universal.

O bundle mínimo SDK 26.5 tem manifestos idênticos nos dois sistemas, com executável SHA-256 `a6346adc216816eea30703da8209c261e962c3ba366de6b368dd7d531af230db`. O executável não foi baixado, rehashado nem executado localmente por esta revisão.

No macOS 26, os cinco pop-ups observados registram aparência clara; somente Equilibrado e Restaurar estão dentro do viewport avaliado. No 27, a captura contém esses controles legíveis, mas o inventário de NSControl pop-up é vazio; não se infere equivalência de implementação interna.

**Aprovação restrita ao diagnóstico de aparência.** Não aprova aplicativo completo, recuperação, todas as ferramentas, instalador, entrega, M4 físico, Neural Engine, VoiceOver humano ou integrações de produção. Animações, cliques, abas não abertas e conteúdo fora da rolagem não foram avaliados. Os cortes de próximos cartões/controles são os limites naturais do viewport 1050×772.

| Artefato | PNG | SHA-256 | Resultado visual |
| --- | --- | --- | --- |
| PDF-appearance-sdk26 | PDF-appearance.png | `3abb578412f16ea8aa18059a705644c95e3de889ebaa258d3e04f842cf6f3974` | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.dark-attached-1.png | `a2a766902179a68f7580d2c7002d08c7f03221ace9ab030d7251f64364083bb7` | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.dark-attached-2.png | `b9a511ffb4f8fd6d700b9c09b9f8e89eca6142ddf743059b5b6a1c86174d4150` | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.customization.png | `829ea541dc6e47839f37d0cfc98b10646dcba082dd38e7fec334b0e407e631f5` | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.dark-recreated.png | `52cd7ca64c82b9a840b478a31588e84d7ce31d695dfdb32afb2426699ba7b59e` | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.light-return.png | `cdabb485276c653e0272cf5c165f932cd7bcbb56d8df52f2d142181c2112453c` | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.system.png | `cd9793b0548e19f46131de24fe80e89974dbfe20d894db438d704d703ce6cfcd` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.png | `39815d2d60568009aab70300d655b17ce0a139aeb012e503cfa7947aeae5db93` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.dark-attached-1.png | `d55eccb88c7c6082a199711aeb32d43b972923fb7d168bfd698234cae6c01133` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.dark-attached-2.png | `baa67d691fcf2426f6cba9971343e8f460d48ffdeaf948d6155446814d28f8a5` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.customization.png | `14d4dea097ab54f98171573ca1e289d83935d81b50c3340f1c92f6b00b00cf1b` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.dark-recreated.png | `a49948efd1e7f362b0425d5128cb2fb270c4cdab5f407493d6a304d4b51ae50c` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.light-return.png | `460e978133e6f53a45390e3422ec5a5df745d28493c477eafcc9bc8d2425e3b6` | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.system.png | `460e978133e6f53a45390e3422ec5a5df745d28493c477eafcc9bc8d2425e3b6` | Sem bloqueador confirmado no viewport |

O JSON companheiro conserva os hashes dos insumos, todas as medidas, os vínculos de cada snapshot e os limites da conclusão. Nenhuma fonte do aplicativo ou evidência original foi alterada.
