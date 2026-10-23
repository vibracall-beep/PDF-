# Instalação do PDF por comando

O instalador compila o aplicativo no próprio Mac, prepara suas dependências, executa verificações automáticas e só então ativa a instalação. A distribuição é de fontes verificáveis: o `.app` produzido num runner de CI depende daquele computador e não é um binário portátil para outros Macs.

## Requisitos do Mac

- Mac Apple Silicon executado nativamente, sem Rosetta. O alvo solicitado é M4 e superior; a verificação `arm64` também permite outras gerações Apple Silicon, sem afirmar desempenho equivalente.
- macOS 26 ou posterior, Xcode 26 ou posterior selecionado e Swift 6.2 ou posterior. Compatibilidade exata com outra versão do sistema deve ser estabelecida pela validação daquela versão.
- Homebrew arm64 em `/opt/homebrew`, instalado pelas instruções oficiais de <https://brew.sh>.
- Acesso às fontes no GitHub e aos registries usados por Homebrew, PyPI e Playwright.
- Para IA local: Apple Intelligence disponível e habilitada nas configurações do Mac. A presença do framework não garante que o modelo esteja disponível naquele dispositivo ou idioma.

Não é necessária uma assinatura paga de desenvolvedor Apple. O bundle recebe assinatura local ad hoc. Isso não cria assinatura Developer ID nem notarização Apple.

## Comando da versão histórica validada

O bloco abaixo é da versão anterior. As dez melhorias da versão 0.5.0 estão em validação na matriz macOS 26/27; o commit de instalação será atualizado após essa execução. Não use a aprovação histórica para atribuir aprovação às mudanças posteriores.

A execução [40019981712](https://github.com/vibracall-beep/PDF-/actions/runs/40019981712) aprovou o commit `9d72a9d75da72437a68d411359906e3e10a4466e`: compilação, 69 testes do motor/integrações, instalação e verificações nativas em macOS 26.6.2 arm64. Com os requisitos acima instalados, cole este bloco no Terminal de cada Mac:

```bash
bash <<'PDF_INSTALL'
set -euo pipefail
PDF_SOURCE_DIR="$(mktemp -d "$HOME/PDF-fontes.XXXXXX")"
git clone --quiet https://github.com/vibracall-beep/PDF-.git "$PDF_SOURCE_DIR"
git -C "$PDF_SOURCE_DIR" checkout --quiet --detach 9d72a9d75da72437a68d411359906e3e10a4466e
printf 'Fontes preservados em: %s\n' "$PDF_SOURCE_DIR"
bash "$PDF_SOURCE_DIR/scripts/install-mac.sh"
open "$HOME/Applications/PDF.app"
PDF_INSTALL
```

O diretório de fontes recebe um nome novo; cópias existentes não são alteradas. O instalador verifica o próprio computador antes de ativar `PDF.app`. Os limites da evidência — incluindo ausência de teste em macOS 27.0.1, M4 físico, Pages, scanner/iPhone e geração por Apple Intelligence — estão em [VALIDACAO.md](VALIDACAO.md).

## Instalar fontes já baixados

Na pasta de fontes do PDF:

```bash
bash scripts/install-mac.sh
open "$HOME/Applications/PDF.app"
```

O comando inclui OCRmyPDF, Tesseract com português e inglês, Ghostscript pela dependência de OCRmyPDF, LibreOffice, Python, Chromium/Playwright, pyHanko e Java 21 com veraPDF 1.30.3 verificado por SHA-256. `install-optional-mac.sh` permanece como entrada de compatibilidade e verifica a instalação completa.

Para outro diretório de aplicativos:

```bash
PDF_INSTALL_DIR="$HOME/Applications/Documentos" bash scripts/install-mac.sh
```

O instalador não instala nem aceita a licença do Xcode ou instala o Homebrew automaticamente. Ele informa a dependência que falta. As verificações de instalação são executadas pelo próprio comando; não exigem executar manualmente uma versão incompleta do aplicativo.

## Instalar um commit revisado do GitHub

Use um SHA completo de **40 caracteres** correspondente à versão revisada. Branches como `main` e tags mutáveis não são aceitas pelo instalador de fontes. A autenticação HTTPS usa a configuração Git que já existe no Mac.

Com o script presente em uma cópia revisada do repositório:

```bash
bash scripts/install-from-github.sh --commit SHA_COMPLETO_DA_VERSAO
```

O script busca exatamente esse commit em `vibracall-beep/PDF-`, verifica o HEAD e os objetos Git, preserva os fontes em `~/Library/Application Support/PDF/sources/<SHA>` e inicia o instalador completo. A instalação de cada Mac é independente. Para outro destino de fontes, informe `--source-dir`; uma pasta existente nunca é mesclada ou apagada.

O parâmetro `--repository dono/repositorio` permite um fork revisado. Não use credenciais como parâmetros de URL ou de linha de comando; reutilize a autenticação normal do Git no Mac.

## Pacote de fontes e checksum

O workflow de validação macOS produz o artefato `PDF-source` com:

- `PDF-source.tar.gz`: fontes, scripts, testes e documentação.
- `PDF-source.tar.gz.sha256`: checksum externo do pacote.
- Dentro do pacote, `SHA256SUMS` verifica os arquivos individualmente e `BUILD-INFO.json` identifica o commit e informa se havia alterações locais ao empacotar.

Depois de baixar o artefato da execução correspondente à versão revisada, confira o checksum antes de extrair:

```bash
shasum -a 256 -c PDF-source.tar.gz.sha256
```

O script também oferece download HTTPS com checksum obrigatório:

```bash
bash scripts/install-from-github.sh \
  --archive URL_HTTPS_DO_PACOTE \
  --sha256 SHA256_DO_PACOTE_REVISADO
```

Essa forma rejeita caminhos relativos inseguros, links, arquivos especiais, membros duplicados e manifestos divergentes antes de executar qualquer arquivo do pacote. Artefatos privados do GitHub exigem acesso autorizado; para eles, a forma por commit costuma ser mais simples. O script não solicita nem extrai tokens.

Para gerar um pacote local a partir dos fontes revisados:

```bash
bash scripts/package-source.sh
```

O comando usa conteúdo e metadados determinísticos, exclui caches e padrões de credenciais e recusa sobrescrever um pacote existente. Gerar um pacote não publica uma release.

## Conversões e dependências

| Operações | Dependências |
|---|---|
| PDF, PNG, JPG, texto e EPUB | Motor Python/PyMuPDF e bibliotecas fixadas em `requirements.txt` |
| DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT, RTF e CSV para PDF | LibreOffice; CSV é preparado pelo motor antes da conversão |
| HTML para PDF | Chromium/Playwright local |
| OCR e PDF/A | OCRmyPDF, Tesseract, idiomas e Ghostscript |
| Assinaturas digitais e verificação | pyHanko; certificado PKCS#12 do usuário para assinar; raízes públicas explícitas para avaliar confiança |
| Validação independente PDF/A e PDF/UA | Java 21 e veraPDF oficial com checksum fixado |
| Pages para PDF | Aplicativo **Pages da Apple**, instalado separadamente pela App Store; automação do macOS autorizada pelo sistema |
| Resumo, tradução, conversa e perguntas por IA | Modelo local Apple Intelligence disponível; nenhum segredo de API obrigatório |
| Compartilhar documentos | Serviços de compartilhamento instalados e configurados no macOS |

Pages é um aplicativo gratuito da Apple e não é redistribuído pelo PDF. Quando ausente, a instalação informa essa dependência da ferramenta Pages → PDF. O macOS pode pedir autorização para o PDF controlar o Pages na primeira conversão. O aplicativo fornece a descrição de uso de automação correspondente; não desabilita os controles de privacidade do sistema.

## Atualizações, verificações e recuperação

A versão 0.5.0 usa um runtime próprio em `~/Library/Application Support/PDF/runtimes/<identificador>`. O bundle contém um launcher para esse runtime e permanece selado por assinatura. Não mova ou copie o `.app` para outro Mac; execute a instalação nesse Mac.

Quando existe uma instalação anterior com o identificador `local.pdf.desktop`, o instalador preserva uma cópia `PDF.previous.<data>.<pid>.app`. A atualização é ativada depois dos testes e revertida se a verificação final falhar. Um aplicativo diferente chamado `PDF.app` não é substituído.

O comando `bash scripts/check-mac.sh CAMINHO/PDF.app` verifica arquitetura, assinatura, runtime, idiomas, motores e o teste nativo. O teste nativo e a renderização usada no CI têm limite de 180 segundos; exceder o limite provoca falha explícita e encerramento do grupo de processos. Testes aprovados não equivalem a provar ausência absoluta de erros, fidelidade de todos os documentos ou comportamento de todo scanner.

A execução de CI registra versão do macOS, nome do processador e número de CPUs, sem números de série. O artefato `PDF-macOS-preview` contém capturas reais do menu e do leitor, pelo ScreenCaptureKit, restritas ao próprio processo. As imagens da execução validada foram abertas e revisadas; cópias estão em `docs/imagens`. Uma imagem renderizada não substitui testes de interação, acessibilidade, Apple Intelligence ou equipamentos físicos.
