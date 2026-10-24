# Instalação do PDF por comando

O instalador compila o aplicativo no próprio Mac, prepara suas dependências, executa verificações automáticas e só então ativa a instalação. A distribuição é de fontes verificáveis: o `.app` produzido num runner de CI depende daquele computador e não é um binário portátil para outros Macs.

## Requisitos do Mac

- Mac Apple Silicon executado nativamente, sem Rosetta. O alvo solicitado é M4 e superior; a verificação `arm64` também permite outras gerações Apple Silicon, sem afirmar desempenho equivalente.
- macOS 26 ou posterior, Xcode 26 ou posterior selecionado e Swift 6.2 ou posterior. Compatibilidade exata com outra versão do sistema deve ser estabelecida pela validação daquela versão.
- Homebrew arm64 em `/opt/homebrew`, instalado pelas instruções oficiais de <https://brew.sh>.
- Acesso às fontes no GitHub e aos registries usados por Homebrew, PyPI e Playwright.
- Para IA local: Apple Intelligence disponível e habilitada nas configurações do Mac. A presença do framework não garante que o modelo esteja disponível naquele dispositivo ou idioma.

Não é necessária uma assinatura paga de desenvolvedor Apple. O bundle recebe assinatura local ad hoc. Isso não cria assinatura Developer ID nem notarização Apple.

## Comando da versão validada

O bloco abaixo instala a versão 0.5.0 do commit **`5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`**, aprovado integralmente na [execução 40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837). Os dois jobs, macOS **26.6.2** e **27.0.1** arm64, passaram compilação, 224 testes Python distintos por sistema, instalação/ativação, três verificações nativas, 19 capturas, quatro relatórios AX e benchmark. Os [relatórios originais e a verificação dos pacotes](evidencias/5a11c07/README.md) registram a procedência dessa aprovação.

No macOS 27, o OCR funcional passou usando Tesseract; os dois testes estritos do Apple Vision permaneceram reprovados e estão preservados nos relatórios. O benchmark foi executado em Apple M1 virtualizado, sem medição de M4 físico ou NPU. A aprovação corresponde ao commit indicado; o [histórico](HISTORICO-VALIDACAO.md) conserva as versões anteriores e as falhas corrigidas. Com os requisitos acima instalados, cole este bloco no Terminal de cada Mac:

```bash
bash <<'PDF_INSTALL'
set -euo pipefail
PDF_SOURCE_DIR="$(mktemp -d "$HOME/PDF-fontes.XXXXXX")"
git clone --quiet https://github.com/vibracall-beep/PDF-.git "$PDF_SOURCE_DIR"
git -C "$PDF_SOURCE_DIR" checkout --quiet --detach 5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad
printf 'Fontes preservados em: %s\n' "$PDF_SOURCE_DIR"
bash "$PDF_SOURCE_DIR/scripts/install-mac.sh"
open "$HOME/Applications/PDF.app"
PDF_INSTALL
```

O diretório de fontes recebe um nome novo; cópias existentes não são alteradas. O instalador verifica o próprio computador antes de ativar `PDF.app`. Os limites da evidência — incluindo M4 físico, interação humana com VoiceOver, Pages, scanner/iPhone e geração por Apple Intelligence — estão em [VALIDACAO.md](VALIDACAO.md). A aprovação automatizada não demonstra uso desses equipamentos/modelos nem interação humana completa.

## Instalar fontes já baixados

Na pasta de fontes do PDF:

```bash
bash scripts/install-mac.sh
open "$HOME/Applications/PDF.app"
```

O comando inclui qpdf, OCRmyPDF, Tesseract com português e inglês, Ghostscript pela dependência de OCRmyPDF, LibreOffice, Python, Chromium/Playwright, pyHanko e Java 21 com veraPDF 1.30.3 verificado por SHA-256. O qpdf em `/opt/homebrew/bin/qpdf` é obrigatório para validar os PDFs gerados nativamente antes de salvar. `install-optional-mac.sh` permanece como entrada de compatibilidade e verifica a instalação completa.

A publicação nativa exige `qpdf --check` sem avisos e comparação dos campos, texto, páginas e anotações capturados antes da gravação. A cópia protegida usa AES-256 com credenciais de leitura e proprietário distintas, preservando as permissões compatíveis; restrições legadas incompatíveis são recusadas. O limite é 1 GiB por PDF, 64 MiB para o JSON auxiliar e 1–127 bytes UTF-8 para a senha. Esses limites provocam erro explícito, preservando o original.

PDFs temporários protegidos mantêm criptografia. Jobs de qpdf e relatórios/patches JSON usam arquivos `0600` em diretórios `0700`, mas podem conter credenciais e conteúdo textual legível ao próprio usuário; não são arquivos criptografados. A limpeza ocorre na conclusão, erro e cancelamento normal. Encerramento abrupto pode deixar esses temporários. As cópias persistentes de recuperação de um documento protegido permanecem criptografadas.

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

O workflow produz um pacote por runner: `PDF-source-macos-26` ou `PDF-source-xcode-27` quando todas as etapas e o Vision passam. Se o produto passa usando OCR de compatibilidade ou a auditoria independente do Vision registra falha, o nome é `PDF-source-ocr-compatibility-<runner>`. Um pacote `PDF-source-unvalidated-<runner>` não passou todos os requisitos funcionais e não é a versão aprovada para instalação. Cada pacote contém:

- `PDF-source.tar.gz`: fontes, scripts, testes e documentação.
- `PDF-source.tar.gz.sha256`: checksum externo do pacote.
- Dentro do pacote, `SHA256SUMS` verifica os arquivos individualmente e `BUILD-INFO.json` identifica o commit e informa se havia alterações locais ao empacotar.

Os artefatos aprovados também incluem `PDF-vision-audit.json` e `PDF-benchmark.json` ao lado do arquivo compactado. Para o commit validado acima, os pacotes são [macOS 26 — 12545312794](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12545312794) e [macOS 27 com OCR de compatibilidade — 12545304284](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12545304284). Ambos contêm o mesmo `PDF-source.tar.gz`, SHA-256 `e7b036f9d2277235b94758703c5fb4c789306573f4dca12a24a9aa138d253619`; o checksum externo, o manifesto completo e o commit de origem foram conferidos localmente.

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
| Salvar cópias, recuperação e PDFs nativos de scanner/OCR/IA | PDFKit/Core Graphics e qpdf arm64, com estrutura final e preservação de dados verificadas |
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

Quando existe uma instalação anterior com o identificador `local.pdf.desktop`, o instalador preserva uma cópia `PDF.previous.<data>.<pid>.app`. A atualização é ativada depois dos testes. Se a verificação final falhar, a rotina de limpeza preserva o bundle com falha como `PDF.failed.<data>.<pid>.app` e tenta restaurar a versão anterior sem sobrescrever um destino criado ou alterado por outro processo. Se a restauração não puder ocorrer, a versão anterior permanece no caminho de backup informado. Um aplicativo diferente chamado `PDF.app` não é substituído.

Essa limpeza depende de o instalador conseguir tratar a saída ou o sinal recebido. `SIGKILL`, queda de energia ou encerramento abrupto do sistema podem deixar `.pdf-install.lock`, uma pasta de estágio `.pdf-install.*` no diretório de aplicativos e um runtime `install.*` em `~/Library/Application Support/PDF/runtimes`. Não há recuperação automática desses resíduos na próxima execução: um lock existente interrompe a nova instalação. O arquivo `.pdf-install.lock/pid` ajuda a identificar o processo; confirme que não há instalador ativo antes de remover um lock residual. Preserve os bundles `PDF.previous.*.app` e `PDF.failed.*.app` e os runtimes apontados por seus arquivos `Contents/Resources/runtime-location.txt` ao investigar a interrupção.

O CI completo instala em um destino novo e verifica o aplicativo antes e depois da ativação. Os testes portáteis de [install_files.py](../scripts/install_files.py), em [test_installation.py](../scripts/test_installation.py), cobrem movimentos exclusivos, preservação de destinos e restauração de um bundle anterior. Essa cobertura do helper não equivale a uma execução completa do instalador no Mac atualizando uma versão existente e sofrendo falha após a ativação; esse cenário e a recuperação após queda de energia não foram demonstrados.

O comando `bash scripts/check-mac.sh CAMINHO/PDF.app` verifica arquitetura, assinatura, runtime, qpdf, idiomas, motores e o teste nativo. O teste nativo tem limite de 240 segundos; a renderização usada no CI mantém limite de 180 segundos; exceder o limite provoca falha explícita e encerramento do grupo de processos. Testes aprovados não equivalem a provar ausência absoluta de erros, fidelidade de todos os documentos ou comportamento de todo scanner.

A execução de CI registra versão do macOS, nome do processador e número de CPUs, sem números de série. Uma execução aprovada exige 19 capturas reais e quatro relatórios AX por sistema, restritos ao próprio processo. Os artefatos `PDF-macOS-preview-macos-26` e `PDF-macOS-preview-xcode-27` de execuções reprovadas podem conter somente evidências parciais. As imagens revisadas, seu commit, hashes e procedência estão em [imagens/README.md](imagens/README.md). Uma imagem renderizada não substitui testes de interação, acessibilidade, Apple Intelligence ou equipamentos físicos.
