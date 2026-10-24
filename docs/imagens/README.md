# Capturas reais — 5a11c07

Estas imagens pertencem ao commit **`5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`**, execução [40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837). Substituem a galeria histórica de `0910ad9` anteriormente presente nesta pasta. Os dois artefatos desta execução foram baixados normalmente e inspecionados localmente.

São capturas reais por ScreenCaptureKit da WindowGroup de produção, usando documentos de demonstração e preferências isoladas. Os 19 estados foram inspecionados visualmente nos artefatos dos dois ambientes de CI, `xcode-27` e `macos-26`, sem novo corte de cabeçalhos, abas ou inspector. As imagens abaixo vêm do artefato `xcode-27`; os bytes originais, títulos visíveis e dimensões foram preservados, sem recorte, retoque ou recomposição.

- Artefato publicado aqui: `PDF-macOS-preview-xcode-27`, ID `12545860080`, criado em `2026-10-24T02:52:03Z`.
- SHA-256 do ZIP informado pelo GitHub: `90f9a14794be7ec70e88e8d7c7056d32c0b22d9787d790f5ee8fd0b9bc0c5ba6`.
- Os dois artefatos passaram a validação de 19 PNGs e quatro relatórios AX, repetida localmente após o download.
- [Procedência completa e SHA-256 de cada arquivo](proveniencia.json).

**Matriz completa aprovada nos dois ambientes.** A execução vinculada terminou com sucesso nos jobs `macos-26` e `xcode-27`, incluindo construção, instalação, validação funcional e artefatos visuais. O OCR funcional pode utilizar a alternativa Tesseract identificada no resultado; essa aprovação não significa que a auditoria independente e estrita do Apple Vision tenha passado. Os resultados e as limitações desse framework permanecem separados em [Validação](../VALIDACAO.md). A inspeção cobre a aparência dos estados capturados. Painéis roláveis mostram a parte visível naquele instante. A auditoria AX encontrou os identificadores obrigatórios usando as APIs públicas da própria janela; isso não equivale à avaliação humana de VoiceOver, contraste de todas as cores personalizadas ou comprovação de desempenho em um Mac M4 físico.

| Estado capturado | Nome original no artefato | Dimensões |
| --- | --- | --- |
| [Menu principal](menu-principal.png) | `PDF-preview.png` | 1050 × 772 |
| [Leitor de PDF](leitor.png) | `PDF-preview.leitor.png` | 1050 × 772 |
| [Abas de documentos](abas.png) | `PDF-preview.abas.png` | 1050 × 772 |
| [Leitura lado a lado](leitura-lado-a-lado.png) | `PDF-preview.lado-a-lado.png` | 1050 × 772 |
| [Inspector de anotações](anotacoes.png) | `PDF-preview.anotacoes.png` | 1050 × 772 |
| [Recuperação de documentos](recuperacao.png) | `PDF-preview.recuperacao.png` | 1050 × 772 |
| [Personalização da aparência](personalizacao-aparencia.png) | `PDF-preview.personalizar.png` | 1050 × 752 |
| [Personalização das ferramentas](personalizacao-ferramentas.png) | `PDF-preview.ferramentas.png` | 1050 × 752 |
| [Personalização da navegação](personalizacao-navegacao.png) | `PDF-preview.navegacao.png` | 1050 × 752 |
| [Personalização do leitor](personalizacao-leitor.png) | `PDF-preview.opcoes-leitura.png` | 1050 × 752 |
| [Personalização dos arquivos](personalizacao-arquivos.png) | `PDF-preview.arquivos.png` | 1050 × 752 |
| [Menu no tema escuro](menu-escuro.png) | `PDF-preview.escuro.png` | 1050 × 772 |
| [Menu em lista](menu-lista.png) | `PDF-preview.lista.png` | 1050 × 772 |
| [Configuração de marca d’água](configuracao-ferramenta.png) | `PDF-preview.configuracao-ferramenta.png` | 1050 × 772 |
| [Fluxo de trabalho em lote](fluxo-lote.png) | `PDF-preview.fluxo-lote.png` | 1050 × 752 |
| [Assinatura digital](assinatura-digital.png) | `PDF-preview.assinatura-digital.png` | 1050 × 752 |
| [Verificação de assinaturas](verificar-assinaturas.png) | `PDF-preview.verificar-assinaturas.png` | 1050 × 752 |
| [Validação PDF/A](validar-pdfa.png) | `PDF-preview.validar-pdfa.png` | 1050 × 752 |
| [Auditoria PDF/UA](auditar-pdfua.png) | `PDF-preview.auditar-pdfua.png` | 1050 × 752 |

Os relatórios AX originais, também preservados byte a byte, estão disponíveis para [menu](menu-principal.accessibility.json), [leitor](leitor.accessibility.json), [leitura lado a lado](leitura-lado-a-lado.accessibility.json) e [anotações](anotacoes.accessibility.json). Nenhum identificador obrigatório está ausente e nenhuma travessia atingiu o limite. Avisos genéricos e verificações humanas pendentes permanecem registrados nos próprios JSONs.
