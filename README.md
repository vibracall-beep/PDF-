# PDF

Aplicativo nativo macOS com **54 ferramentas**, interface em português, SwiftUI/PDFKit e Liquid Glass. Inclui leitura em abas e lado a lado, recuperação de sessões, edição de anotações, conversões, OCR e scanner, assinaturas digitais, validação PDF/A e PDF/UA, busca semântica local para IA, fluxos em lote e benchmark do Mac.

A especificação está em [docs/REQUISITOS.md](docs/REQUISITOS.md), a correspondência de todos os itens da nova imagem em [docs/FERRAMENTAS.md](docs/FERRAMENTAS.md) e as evidências em [docs/VALIDACAO.md](docs/VALIDACAO.md). **A versão histórica `9d72a9d` passou na compilação, instalação e verificações automatizadas em macOS Apple Silicon. A integração das dez melhorias agora implementadas aguarda nova validação completa no CI.** Consulte a [matriz das melhorias autorizadas](docs/MELHORIAS.md). Evidências de uma versão anterior não validam alterações posteriores; dispositivos, Pages, certificados e modelos Apple têm requisitos próprios.

## Estado verificável

- **Código atual:** 54 identificadores únicos no catálogo; implementações e testes das dez melhorias estão mapeados em [MELHORIAS.md](docs/MELHORIAS.md). Há testes específicos para assinatura criptográfica, veraPDF, análise de digitalizações, lotes, sessões, recuperação, anotações e fontes verificáveis da IA. A execução integrada deste conjunto está pendente.
- **Histórico aprovado:** a execução macOS [40019981712](https://github.com/vibracall-beep/PDF-/actions/runs/40019981712) compilou, instalou e testou o commit `9d72a9d`: 61 testes do motor, oito integrações e verificações nativas antes/depois da ativação. Ambiente: macOS 26.6.2, Apple M1 virtualizado. Esses números pertencem àquela versão.
- **Evidências visuais históricas:** menu e leitor capturados pelo ScreenCaptureKit e revisados, além de pacote de fontes com manifesto/checksum. Duas capturas estáticas não comprovam todas as interações nem acessibilidade com VoiceOver.
- **Novas verificações:** o benchmark identifica a máquina usada; veraPDF identifica bytes/perfil examinados; relatórios de assinatura separam integridade de confiança. Nenhum desses resultados equivale a ausência absoluta de erros ou superioridade sobre outros produtos.

## Menu principal

![Menu principal do PDF](docs/imagens/menu-principal.png)

Captura histórica da janela em macOS 26.6.2, 1050 × 772 pixels; antecede as dez melhorias atuais. A barra lateral reúne Início, Leitor, Favoritos, Digitalizar, Inteligência e Fluxos. O catálogo atual tem 54 opções, busca, categorias e estrelas de favoritos. Personalizar permite escolher aparência, cor, densidade, ordem e visibilidade das ferramentas, além das preferências de arquivos. A navegação entre Início e Favoritos limpa os filtros; resultados vazios oferecem uma ação para limpá-los.

O [leitor também foi capturado](docs/imagens/leitor.png), com miniaturas e conteúdo do documento de exemplo visíveis.

## Instalação completa por comando

Pré-requisitos: Apple Silicon (alvo M4 ou superior), macOS 26 ou posterior, Xcode 26 com Swift 6.2 ou posterior selecionado e Homebrew arm64 em `/opt/homebrew`. Os procedimentos por commit imutável ou pacote com checksum estão em [docs/INSTALACAO.md](docs/INSTALACAO.md).

Na pasta do código-fonte:

```bash
bash scripts/install-mac.sh
```

O script compila arm64, instala o runtime e dependências, verifica idiomas OCR, executa testes do motor e verificações nativas, assina localmente e só então ativa `~/Applications/PDF.app`. Instalações anteriores são preservadas com outro nome; falhas de ativação acionam restauração. `PDF_INSTALL_DIR=/caminho` altera o destino. As dependências incluem Python, OCRmyPDF, Tesseract português/inglês, Ghostscript, LibreOffice, Chromium/Playwright, pyHanko, Java 21 e o JAR oficial veraPDF 1.30.3 com SHA-256 fixado.

Não exige assinatura paga de desenvolvedor Apple. A assinatura é ad hoc local, sem notarização Apple. O runtime fica em `~/Library/Application Support/PDF/runtimes`; execute o instalador em cada Mac, pois o bundle não é portátil entre computadores. O script não desativa Gatekeeper ou verificação de TLS/assinaturas de pacotes.

```bash
bash scripts/check-mac.sh "$HOME/Applications/PDF.app"
open "$HOME/Applications/PDF.app"
```

A validação deve ocorrer no ambiente de desenvolvimento macOS antes de entregar a versão final ao usuário; esses comandos não significam pedido de teste antecipado ao usuário.

## Funcionalidades e limites relevantes

| Área | Implementação e limites |
|---|---|
| Leitor e sessões | PDFKit, abas, referência lado a lado, página/zoom independentes, pesquisa, miniaturas, marcadores, impressão e cópia; recuperação automática por sessão preserva criptografia |
| Interface | Favoritos, ordem/visibilidade das ferramentas, aparência, densidade, opções do leitor e destinos; não equivale à personalização arbitrária de qualquer aspecto do macOS |
| Edição | Texto novo/substituição, imagens, formas, assinatura visual, marca d'água, numeração, recorte e rotação; anotações existentes selecionáveis, movíveis e redimensionáveis, com inspector e desfazer/refazer |
| Formulários e tabelas | Widgets, exportação de campos e detecção vetorial ou raster com Tesseract; sugestões de campos, rótulos e células editáveis em Word/Excel. Grades incompletas, manuscritos e inclinação exigem revisão; pontuações OCR não são precisão calibrada |
| Office | Word com reconstrução básica de estilos; PPTX com texto editável ou páginas rasterizadas; Excel por tabelas. Fidelidade exige revisão em documentos reais |
| Outros formatos | PNG com transparência; TXT Unicode paginado; EPUB sem DRM; ODT/RTF/CSV com LibreOffice. Textos que não possam ser acomodados são recusados em vez de cortados silenciosamente |
| Pages | Exporta uma cópia privada pelo aplicativo Pages, com autorização de Automação do macOS, cancelamento e limite de tempo; requer Pages instalado |
| Achatamento | Incorpora a aparência de anotações e/ou widgets ao conteúdo, preservando a proteção do arquivo; não substitui remoção de informações sensíveis |
| Assinaturas | Marca visual e assinatura criptográfica PAdES com PKCS#12 do usuário; verificação offline de integridade e raízes locais explícitas, TSA HTTPS opcional. Não comprova identidade civil, revogação, validade jurídica ou PAdES-LT/LTA |
| Compartilhamento e Sign.com | Compartilhamento pelos serviços nativos; Sign.com abre o serviço externo, que administra conta, envio e acompanhamento no navegador |
| Segurança | AES-256, desbloqueio com senha conhecida, preservação de proteção nas operações PDF; redaction remove texto/áreas e limpa metadados/anexos |
| OCR | OCRmyPDF ou Vision nativo; Vision recria páginas e pode perder widgets, links e assinaturas. OCR nativo recusa documento criptografado |
| Scanner | Captura com scanner via ImageCaptureCore/ImageKit, importação, ordenação e Câmera de Continuidade do iPhone/iPad pelos menus públicos do macOS; depende de dispositivos/configurações compatíveis |
| PDF/A e PDF/UA | Conversão PDF/A por OCRmyPDF e validação independente por veraPDF com relatório de regras, XML e hash. A conformidade vale para os bytes/perfil examinados. Auditoria PDF/UA não cria tags nem substitui revisão humana |
| Comparação | Diferenças textuais ou relatório HTML lado a lado com diferenças gráficas |
| IA | Foundation Models local; resumo, tradução, chat e questões. Busca semântica com embeddings NaturalLanguage disponíveis e alternativa por termos; citações verificadas contra trechos originais e páginas extraídas. Geração exige Apple Intelligence; citação correta não garante interpretação correta |
| Tradução | Tradução de texto ou de blocos posicionados no PDF original, preservando imagens/vetores e recusando texto que não caiba; fontes e fidelidade tipográfica exata não são garantidas |
| Markdown | Reconstrução heurística de títulos, tabelas, estilos, imagens e links; sem garantia de preservação semântica perfeita |
| Fluxos | Etapas PDF→PDF com exportação final DOCX/XLSX/PPTX/Markdown/JPG/PNG, lote com senha por arquivo, progresso, cancelamento e pasta publicada atomicamente. Presets v1/v2 sem senhas; formulários/certificados continuam nas ferramentas próprias |
| Desempenho Apple | CPU, Core Image/Metal e Vision conforme disponibilidade. Benchmark em interface/CLI registra hardware, corpus, tempos, memória e falhas. Medição no runner M1 não comprova ganho M4 ou uso do Neural Engine; é necessária execução no equipamento-alvo |
| Acessibilidade | Rótulos e inspector por teclado, relatório da árvore AX da própria janela e validação PDF/UA. A árvore interna não demonstra interação humana com VoiceOver, contraste de qualquer tema ou ordem semântica correta |

Compatibilidade visual específica com macOS **27.0.1** não foi validada. Recursos disponíveis no código não equivalem a recursos já aprovados em Mac.

## Desenvolvimento na nuvem

Cada tarefa já é isolada. Use o checkout existente em `/workspace/PDF-`, sem criar worktrees salvo pedido explícito.

```bash
bash scripts/setup-cloud.sh
.venv/bin/python engine/pdf_engine.py --capabilities
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip install -r requirements-optional.txt
PDF_CHROMIUM_EXECUTABLE=/usr/bin/chromium .venv/bin/python tests/integration_optional.py -v
```

Integrações exigem LibreOffice, OCRmyPDF, Tesseract com inglês, Ghostscript e Chromium. O setup exige Java disponível e provisiona o veraPDF fixado; os testes de padrões usam esse validador real. A suíte raster pode ser executada com `.venv/bin/python tests/integration_scan.py -v`. Nesta máquina Linux o OCR português não está instalado; use `{"language":"eng"}`. Não há servidor permanente nem credenciais de API necessárias. HTML remoto acessa os destinos da página e pode carregar recursos externos.

Saídas usam caminhos novos e publicação atômica sem substituição de arquivos. Para senhas use `PDF_OPTIONS_STDIN=1` e JSON via stdin; evite senhas nos argumentos/histórico. A interface usa pipe. Capturas do scanner permanecem em `~/Library/Application Support/PDF/Capturas`; a remoção da lista não deve apagar os originais.

```bash
.venv/bin/python engine/pdf_engine.py organize entrada.pdf --output organizado.pdf --options '{"pages":"3,1-2"}'
.venv/bin/python engine/pdf_engine.py workflow entrada.pdf --output fluxo.pdf --options '{"steps":[{"operation":"rotate"},{"operation":"numbers"}]}'
bash scripts/package-source.sh
```

A distribuição de código inclui manifesto e SHA-256; exclui runtimes, caches e credenciais. Não é um binário macOS previamente compilado.

PyMuPDF possui licenciamento AGPL/comercial; consulte seus termos antes de definir licença e distribuição do produto. Este projeto ainda não define uma licença própria.
