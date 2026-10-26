# Revisão visual independente do focal 9d

Fonte/controlador: `9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb`. Execução `40252786964`, tentativa `1`.

**Conclusão restrita ao focal:** os 14 PNGs originais foram abertos individualmente; não identifiquei bloqueador visual confirmado nos viewports capturados. A toolbar está legível em todos os 12 quadros workspace. Espaçamento/Equilibrado e Restaurar estão presentes nas duas capturas de Personalização.

Os dois relatórios nativos passam os 12 checks e contêm 36 medições de contraste. A conferência independente vinculou todos os 24 snapshots antes/depois aos NSToolbarItem e item.view reais registrados, incluindo identidade, aparência, geometria, unicidade e presença na hierarquia nativa. Os tokens permanecem nas três primeiras fases e mudam após Personalização; as duas capturas escuras têm intervalos de observação distintos. Sistema libera os overrides de app/janela.

Menor razão central nativa: **4,136:1 no macOS 26** e **6,878:1 no macOS 27**, acima do limiar de 3:1 deste teste. Esses valores foram lidos e conferidos nos relatórios nativos, sem substituir pixels ou reconstruir imagens.

Os manifestos registram o mesmo executável SDK26.5 nos dois jobs, SHA256 `b2aff5d9db9e97147f9edd20f2c71dd85f3c60380aaa338163a8dd79ff5dc9ff`. O escopo é um bundle mínimo de aparência. **Esta aprovação não valida aplicativo instalado, recuperação de documentos, pacote de entrega, todas as ferramentas, desempenho em M4 físico, VoiceOver ou animações.** O problema separado de tamanho do package-source não é resolvido por este focal.

A inspeção cobre apenas conteúdo visível em 1050×772. A rolagem corta naturalmente as próximas linhas de cartões/controles; conteúdo abaixo desse viewport e abas não abertas não foram avaliados. Não há afirmação de interação humana ou de conformidade WCAG universal.

| Artefato | PNG original | SHA256 | Dimensões | Resultado visual |
| --- | --- | --- | --- | --- |
| PDF-appearance-sdk26 | PDF-appearance.png | `c104766d414a3cd14721fa5edc15cf87bb8cb460d2240291e51469e3936186f3` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.dark-attached-1.png | `c3d2cf647cacfd47635c4c8a1c96655255d8c5baf72b33ab771faeb0620648e0` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.dark-attached-2.png | `c3d2cf647cacfd47635c4c8a1c96655255d8c5baf72b33ab771faeb0620648e0` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.customization.png | `829ea541dc6e47839f37d0cfc98b10646dcba082dd38e7fec334b0e407e631f5` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.dark-recreated.png | `52cd7ca64c82b9a840b478a31588e84d7ce31d695dfdb32afb2426699ba7b59e` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.light-return.png | `cdabb485276c653e0272cf5c165f932cd7bcbb56d8df52f2d142181c2112453c` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-sdk26 | PDF-appearance.system.png | `cd9793b0548e19f46131de24fe80e89974dbfe20d894db438d704d703ce6cfcd` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.png | `c9a1e05fbaebe91ffa304f6491cebbbecfaa016729c49513709fe94ee9ff426b` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.dark-attached-1.png | `358dd97850c8caa27a8df3410342b867e218f6ac2893b78899606b2efbd17e1a` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.dark-attached-2.png | `baa67d691fcf2426f6cba9971343e8f460d48ffdeaf948d6155446814d28f8a5` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.customization.png | `14d4dea097ab54f98171573ca1e289d83935d81b50c3340f1c92f6b00b00cf1b` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.dark-recreated.png | `a49948efd1e7f362b0425d5128cb2fb270c4cdab5f407493d6a304d4b51ae50c` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.light-return.png | `460e978133e6f53a45390e3422ec5a5df745d28493c477eafcc9bc8d2425e3b6` | 1050×772 | Sem bloqueador confirmado no viewport |
| PDF-appearance-same-binary-xcode27 | PDF-appearance.system.png | `460e978133e6f53a45390e3422ec5a5df745d28493c477eafcc9bc8d2425e3b6` | 1050×772 | Sem bloqueador confirmado no viewport |

O JSON companheiro conserva nomes, hashes, dimensões, observações por quadro, vínculos aos relatórios originais e medições. Nenhum original, fonte do produto ou revisão anterior foi alterado.
