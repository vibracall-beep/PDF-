# Instalação do PDF por comando

**Estado da versão 0.6:** o instalador autocontido e o atualizador estão implementados, mas o pacote portátil ainda não foi aprovado. A última matriz completa, [40130449411](https://github.com/vibracall-beep/PDF-/actions/runs/40130449411), fonte `e9af24a`, aprovou nos dois sistemas **480 métodos Python: 479 aprovados e um skip**, **41 grupos nativos em três execuções**, compilação e instalação por fontes. Montagem/assinatura e o runtime portátil isolado, incluindo Java, Office, Chromium e OCR, também passaram. **A rodada reprovou:** o smoke nativo portátil teve 27 grupos aprovados e 11 reprovados em caminhos de PDFs protegidos; três grupos dependentes não foram alcançados. No macOS 26, o gate aprovou 32 PNGs/seis AX; no macOS 27, a captura expirou após o lançamento, sem criar arquivos. Instalação/atualização binária posteriores não foram executadas. [Originais, contagens e procedência](evidencias/e9af24a/README.md). O [diagnóstico criptográfico posterior](evidencias/qpdf-crypto-55eab2e/README.md) confirmou a descoberta incorreta do provider OpenSSL e verificou a correção isolada nos dois sistemas. Sua integração no pacote precisa de nova matriz; a abertura da janela continua sob diagnóstico. [Estado de cada rodada](VALIDACAO.md). Este documento descreve procedimentos preparados, sem solicitar ao usuário teste de versão incompleta. Consulte [VALIDACAO.md](VALIDACAO.md) antes de identificar qualquer pacote como entrega final.

## Requisitos comuns

- Mac Apple Silicon nativo, sem Rosetta, com macOS 26 ou posterior. O alvo solicitado é M4 e superior; aceitar arm64 não demonstra ganho de desempenho numa geração específica.
- Espaço para pacote, instalação e cópia anterior. O runtime completo inclui conversores e pode ocupar vários gigabytes; clones APFS reduzem cópias físicas quando disponíveis, sem eliminar o requisito de espaço.
- Para geração de IA: Apple Intelligence disponível, habilitada e com modelo instalado. A ausência do modelo deve aparecer como indisponibilidade; ela não é substituída por resposta fictícia.
- Pages, scanner, Continuidade, certificado, TSA e serviço de assinaturas dependem dos componentes/contas próprios quando essas ferramentas forem usadas.

Não é necessária assinatura paga de desenvolvedor Apple. A assinatura é **ad hoc, sem Developer ID nem notarização Apple**. O instalador mantém Gatekeeper, TLS e verificação de assinaturas ativos. Isso pode exigir a autorização normal do macOS para um aplicativo obtido fora da App Store; não há promessa de instalação silenciosa em qualquer política de segurança.

## Pacote autocontido — caminho de entrega preparado

O pacote `PDF-arm64.tar.gz` deve conter `PDF.app`, manifesto e componentes de distribuição. O artefato aprovado também precisa fornecer `install-binary.sh`, checksum e `distribution-validation.json`, identificando o commit, a instalação isolada e as limitações do ensaio. O Mac de destino **não precisa de Xcode, Homebrew, Git ou Python previamente instalados**.

Após existir um pacote aprovado e um SHA-256 publicado por um canal confiável, o comando será:

```bash
bash install-binary.sh /caminho/PDF-arm64.tar.gz SHA256_COMPLETO_DO_PACOTE
```

O primeiro argumento também aceita URL HTTPS. O terceiro argumento opcional define a pasta de aplicativos:

```bash
bash install-binary.sh /caminho/PDF-arm64.tar.gz SHA256_COMPLETO_DO_PACOTE "$HOME/Applications/Documentos"
```

Os valores acima são parâmetros documentais, **não um link ou checksum de uma versão já aprovada**. O script verifica SHA-256 antes de extrair, valida a assinatura do bundle e usa o Python incluído para conferir o manifesto e instalar. A assinatura ad hoc não identifica um publicador Apple; a origem confiável do checksum continua necessária.

O bundle inclui runtime Python e bibliotecas, qpdf, Tesseract português/inglês, OCRmyPDF, Ghostscript, LibreOffice, Chromium/Playwright, pyHanko, Java e veraPDF fixado. O empacotador verifica arquitetura e relocação; `check-portable.sh` exige execução sem rede e sem ferramentas/dependências externas. A lista CA é pública Mozilla, sem Keychains do host. Em `e9af24a`, montagem, assinatura e o runtime isolado, incluindo Office, Java, Chromium e OCR, passaram nos dois sistemas. O smoke nativo portátil seguinte falhou nos caminhos de PDFs protegidos. O [diagnóstico criptográfico](evidencias/qpdf-crypto-55eab2e/README.md) confirmou a descoberta do provider OpenSSL como causa e verificou uma correção isolada; sua integração ainda precisa passar a matriz completa, seguida da primeira instalação, atualização e compatibilidade do binário. As falhas anteriores de relocação, assinatura e Office continuam registradas na [tabela histórica](VALIDACAO.md).

## Atualização, recuperação e retorno à versão anterior

Executar o instalador com outro pacote aprovado atualiza o mesmo destino. Preferências, perfis, biblioteca e recuperação ficam fora do bundle e são preservados. Os formatos novos mantêm leitura de presets anteriores; não se promete compatibilidade de qualquer dado futuro com qualquer versão antiga.

O atualizador:

1. Verifica manifesto, identidade e arquivos antes de publicar.
2. Obtém bloqueios exclusivos das instalações envolvidas; recusa substituir um bundle em uso pelos processos que participam do protocolo.
3. Prepara e valida uma cópia, grava um diário durável e preserva `PDF.previous.<identificador>.app`.
4. Ativa a cópia e repete verificações. Falha tratada restaura a anterior; uma interrupção pode deixar diário para recuperação na próxima execução.

Testes reais exercitam cinco pontos com SIGKILL, disco cheio, corrupção e destino alterado por concorrência. HFS+ realmente cheio, desmontagem do volume e recuperação após SIGKILL passaram nos dois sistemas em `cbb3298`. Isso valida esses cenários do helper, sem aprovar o pacote portátil completo. Processos do aplicativo, motor e filhos explicitamente encaminhados mantêm o bloqueio por descritores. Subprocessos internos de terceiros que fecham descritores não têm garantia universal de cobertura.

Para **voltar deliberadamente** a uma versão, use novamente o instalador com o pacote anterior aprovado e seu checksum original. Isso preserva a instalação que está sendo substituída. Não mova bundles manualmente enquanto houver aplicativo, tarefas ou instalador em execução. Não apague cópias anteriores e runtimes durante a investigação de uma interrupção.

Uma instalação antiga sem `Contents/Resources/installation.lock` não pode ser substituída automaticamente por este protocolo. Nesse caso, escolha outra pasta de destino; a versão anterior e suas configurações são preservadas. O instalador não mata aplicações do usuário para forçar a atualização.

O caminho **por fontes** conserva seu mecanismo de limpeza e tem limites distintos: SIGKILL pode deixar `.pdf-install.lock`, estágio e runtime. Um lock residual impede nova instalação até investigação; não há recuperação universal desses resíduos. O diário transacional novo pertence ao instalador binário.

## Compilação por fontes — desenvolvimento

Exige Xcode 26/Swift 6.2 ou posterior, SDK macOS 26 ou posterior selecionado e Homebrew arm64 em `/opt/homebrew`. O script não instala nem aceita a licença do Xcode e não instala Homebrew automaticamente. Use as instruções oficiais de <https://brew.sh>.

Na pasta dos fontes revisados:

```bash
bash scripts/install-mac.sh
```

O script compila arm64, instala dependências, verifica idiomas, gera metadados reais de App Intents, executa testes, assina localmente e valida antes/depois da ativação em `~/Applications/PDF.app`. `PDF_INSTALL_DIR` muda o destino. O runtime desse caminho fica em `~/Library/Application Support/PDF/runtimes`; o `.app` gerado por fontes **não é a distribuição autocontida** para copiar entre computadores.

Para instalar fontes de um commit revisado, o helper aceita SHA completo de 40 caracteres, não uma branch mutável:

```bash
bash scripts/install-from-github.sh --commit SHA_COMPLETO_DA_VERSAO_REVISADA
```

Também aceita arquivo HTTPS com checksum obrigatório:

```bash
bash scripts/install-from-github.sh --archive URL_HTTPS_DO_PACOTE_DE_FONTES --sha256 SHA256_COMPLETO
```

Fontes existentes não são mesclados nem apagados. O helper conserva a cópia em `~/Library/Application Support/PDF/sources/<SHA>`; `--source-dir` escolhe outra pasta nova. Não passe credenciais na URL ou linha de comando.

## Identificação da versão aprovada

A revisão 0.6 ainda não tem pacote portátil aprovado. A [tabela de execuções](VALIDACAO.md) identifica o resultado de cada commit e os respectivos originais. As falhas anteriores de captura, empacotamento e isolamento permanecem no histórico; uma compilação ou um diagnóstico focal aprovado não substitui a instalação, atualização e compatibilidade do pacote completo. Por isso ainda não há checksum de entrega final para indicar aqui.

A última base inteiramente aprovada foi **0.5**, commit `5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`, na [execução 40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837). Os dois sistemas, macOS 26.6.2 e 27.0.1, passaram os checks daquele código. Essa base não contém as 17 ampliações atuais nem o novo pacote portátil. Os [relatórios históricos](evidencias/5a11c07/README.md) conservam sua procedência.

Artefatos `unvalidated` não são aprovados. Um relatório de IA `unavailable` informa ausência do modelo e não aprova qualidade de geração; falhas estritas do Vision também permanecem identificadas mesmo quando o OCR funcional passa com Tesseract. A validação atual precisa distinguir esses estados.

GitHub Actions conserva artefatos por prazo limitado. A entrega permanente precisa de publicação de versão e checksums após aprovação; não trate um artefato temporário como disponibilidade definitiva.

## Dados e proteção

Os instaladores não removem documentos, preferências, histórico ou recuperação do usuário. Operações produzem arquivos novos e recusam sobrescrita; preservar originais não equivale a preservar a validade de uma assinatura digital sobre bytes editados.

PDFs temporários protegidos e cópias de recuperação permanecem cifrados. Opções enviadas ao motor usam arquivo privado `0600`, cujo nome é removido antes de entregar stdin; não é criptografia nem armazenamento apenas em RAM. Jobs/patches qpdf também usam arquivos privados e podem conter texto e credenciais durante a execução; encerramento abrupto pode deixar resíduos. Senhas não entram em presets/snapshots de configuração. PDFs comuns e metadados da biblioteca não recebem criptografia ponta a ponta adicional.

O manifesto identifica os arquivos do pacote; hashes não substituem a confiança no canal que publica o pacote/checksum. Bibliotecas de terceiros conservam seus avisos e licenças. PyMuPDF é AGPL/comercial; a distribuição deve observar os termos aplicáveis.
