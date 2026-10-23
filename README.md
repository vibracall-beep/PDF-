# PDF

Aplicativo nativo macOS para leitura, organização, edição e conversão de documentos. Interface em português com SwiftUI/PDFKit, Liquid Glass, ferramentas locais, OCR Vision, scanner ImageCaptureCore, IA local e fluxos visuais. O catálogo inclui as adições da terceira imagem: PNG, ODT/TXT/RTF/EPUB/CSV/Pages, achatamento, compartilhamento, chat e questões.

A especificação está em [docs/REQUISITOS.md](docs/REQUISITOS.md), a correspondência de todos os itens da nova imagem em [docs/FERRAMENTAS.md](docs/FERRAMENTAS.md) e as evidências em [docs/VALIDACAO.md](docs/VALIDACAO.md). **Compilação, instalação e verificações automatizadas passaram no macOS Apple Silicon.** Isso não demonstra ausência absoluta de erros ou superioridade sobre outros produtos; os recursos dependentes de dispositivos, Pages e modelos Apple têm limites de validação descritos abaixo.

## Estado verificável

- Motor Python ampliado: 61 testes funcionais aprovados em Linux, incluindo saídas atômicas, cancelamento, preservação dos originais e de criptografia, formulários, conversões novas, achatamento, texto longo e comparação visual.
- A execução macOS [40015439670](https://github.com/vibracall-beep/PDF-/actions/runs/40015439670) aprovou compilação, 61 testes do motor, oito integrações e instalação completa do commit `9884ed1` em macOS 26.6.2, Apple M1 virtualizado.
- Verificação nativa aprovada antes e depois da ativação: PDFKit, formulários, renderização, Vision OCR, processamento gráfico, seleção de fontes para IA, validação estrutural de questões, criptografia, exportação e preservação de destinos.
- O CI também gerou as capturas nativas da tela inicial e do leitor e o pacote de fontes com manifesto e checksum. Os artefatos estão na execução; o resultado efetivo de cada versão está no registro de validação.

## Instalação completa por comando

Pré-requisitos: Apple Silicon (alvo M4 ou superior), macOS 26 ou posterior, Xcode 26 com Swift 6.2 ou posterior selecionado e Homebrew arm64 em `/opt/homebrew`. Os procedimentos por commit imutável ou pacote com checksum estão em [docs/INSTALACAO.md](docs/INSTALACAO.md).

Na pasta do código-fonte:

```bash
bash scripts/install-mac.sh
```

O script compila arm64, instala o runtime e dependências, verifica idiomas OCR, executa testes do motor e verificações nativas, assina localmente e só então ativa `~/Applications/PDF.app`. Instalações anteriores são preservadas com outro nome; falhas de ativação acionam restauração. `PDF_INSTALL_DIR=/caminho` altera o destino. As dependências incluem Python, OCRmyPDF, Tesseract português/inglês, Ghostscript, LibreOffice e Chromium/Playwright.

Não exige assinatura paga de desenvolvedor Apple. A assinatura é ad hoc local, sem notarização Apple. O runtime fica em `~/Library/Application Support/PDF/runtimes`; execute o instalador em cada Mac, pois o bundle não é portátil entre computadores. O script não desativa Gatekeeper ou verificação de TLS/assinaturas de pacotes.

```bash
bash scripts/check-mac.sh "$HOME/Applications/PDF.app"
open "$HOME/Applications/PDF.app"
```

A validação deve ocorrer no ambiente de desenvolvimento macOS antes de entregar a versão final ao usuário; esses comandos não significam pedido de teste antecipado ao usuário.

## Funcionalidades e limites relevantes

| Área | Implementação e limites |
|---|---|
| Leitor | PDFKit, pesquisa, navegação, miniaturas, marcadores, anotações, impressão e cópia |
| Interface | Favoritos, ordem/visibilidade das ferramentas, aparência, densidade, opções do leitor e destinos; não equivale à personalização arbitrária de qualquer aspecto do macOS |
| Edição | Texto novo e substituição por busca, imagem, formas, assinatura visual, marca d'água, numeração, recorte e rotação |
| Formulários | Criação e preenchimento de widgets, exportação de campos e sugestões automáticas por caixas/linhas; a detecção é heurística e precisa de revisão |
| Office | Word com reconstrução básica de estilos; PPTX com texto editável ou páginas rasterizadas; Excel por tabelas. Fidelidade exige revisão em documentos reais |
| Outros formatos | PNG com transparência; TXT Unicode paginado; EPUB sem DRM; ODT/RTF/CSV com LibreOffice. Textos que não possam ser acomodados são recusados em vez de cortados silenciosamente |
| Pages | Exporta uma cópia privada pelo aplicativo Pages, com autorização de Automação do macOS, cancelamento e limite de tempo; requer Pages instalado |
| Achatamento | Incorpora a aparência de anotações e/ou widgets ao conteúdo, preservando a proteção do arquivo; não substitui remoção de informações sensíveis |
| Assinatura | Imagem visual e preparação de solicitação no compositor de e-mail do macOS; sem assinatura digital certificada ou rastreamento remoto de assinaturas |
| Compartilhamento e Sign.com | Compartilhamento pelos serviços nativos; Sign.com abre o serviço externo, que administra conta, envio e acompanhamento no navegador |
| Segurança | AES-256, desbloqueio com senha conhecida, preservação de proteção nas operações PDF; redaction remove texto/áreas e limpa metadados/anexos |
| OCR | OCRmyPDF ou Vision nativo; Vision recria páginas e pode perder widgets, links e assinaturas. OCR nativo recusa documento criptografado |
| Scanner | Captura com scanner via ImageCaptureCore/ImageKit, importação, ordenação e Câmera de Continuidade do iPhone/iPad pelos menus públicos do macOS; depende de dispositivos/configurações compatíveis |
| PDF/A | OCRmyPDF; metadados verificados em Linux, conformidade não certificada por veraPDF |
| Comparação | Diferenças textuais ou relatório HTML lado a lado com diferenças gráficas |
| IA | Foundation Models local; resumo, tradução, chat com histórico e páginas citadas, questões abertas/múltipla escolha com gabarito. Busca de contexto local limitada, cancelamento e exportação TXT/Markdown/PDF; exige Apple Intelligence disponível. Referências validadas estruturalmente não garantem correção factual |
| Tradução | Tradução de texto ou de blocos posicionados no PDF original, preservando imagens/vetores e recusando texto que não caiba; fontes e fidelidade tipográfica exata não são garantidas |
| Markdown | Reconstrução heurística de títulos, tabelas, estilos, imagens e links; sem garantia de preservação semântica perfeita |
| Fluxos | Editor visual, etapas ordenáveis, biblioteca local e importação/exportação de presets; senhas não são gravadas nos presets |
| Desempenho Apple | Motor usa CPU; Core Image usa contexto Metal para melhoria de contraste; Vision/IA escolhem dispositivos conforme o sistema. Uso do Neural Engine e ganhos M4 não foram medidos |

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

Integrações exigem LibreOffice, OCRmyPDF, Tesseract com inglês, Ghostscript e Chromium. Nesta máquina Linux o OCR português não está instalado; use `{"language":"eng"}`. Não há servidor permanente nem credenciais de API necessárias. HTML remoto acessa os destinos da página e pode carregar recursos externos.

Saídas usam caminhos novos e publicação atômica sem substituição de arquivos. Para senhas use `PDF_OPTIONS_STDIN=1` e JSON via stdin; evite senhas nos argumentos/histórico. A interface usa pipe. Capturas do scanner permanecem em `~/Library/Application Support/PDF/Capturas`; a remoção da lista não deve apagar os originais.

```bash
.venv/bin/python engine/pdf_engine.py organize entrada.pdf --output organizado.pdf --options '{"pages":"3,1-2"}'
.venv/bin/python engine/pdf_engine.py workflow entrada.pdf --output fluxo.pdf --options '{"steps":[{"operation":"rotate"},{"operation":"numbers"}]}'
bash scripts/package-source.sh
```

A distribuição de código inclui manifesto e SHA-256; exclui runtimes, caches e credenciais. Não é um binário macOS previamente compilado.

PyMuPDF possui licenciamento AGPL/comercial; consulte seus termos antes de definir licença e distribuição do produto. Este projeto ainda não define uma licença própria.
