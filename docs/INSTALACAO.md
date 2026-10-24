# Instalação do PDF por comando

**Estado da versão 0.6:** os pacotes de `437a8f4` passaram na matriz [40137438618](https://github.com/vibracall-beep/PDF-/actions/runs/40137438618), nos dois sistemas, incluindo isolamento, primeira instalação, atualização, recusa de checksum incorreto e preservação da configuração de controle. [Originais e contagens](evidencias/437a8f4/README.md). O mesmo tar do macOS 26 também passou no macOS 27, sem recompilar, com runtime isolado e interface instalada: [40141728214](https://github.com/vibracall-beep/PDF-/actions/runs/40141728214), [evidências do teste cruzado](evidencias/cross-437a8f4/README.md). A [entrega privada](https://github.com/vibracall-beep/PDF-/releases/tag/untagged-46d8b6e9889cc9181621) foi retida e conferida na execução [40143091839](https://github.com/vibracall-beep/PDF-/actions/runs/40143091839); está disponível ao proprietário autenticado, sem publicação pública. [Procedência e checksums](evidencias/delivery-437a8f4/README.md). Consulte [VALIDACAO.md](VALIDACAO.md) para o estado de cada etapa.

## Requisitos comuns

- Mac Apple Silicon nativo, sem Rosetta, com macOS 26 ou posterior. O alvo solicitado é M4 e superior; aceitar arm64 não demonstra ganho de desempenho numa geração específica.
- Reserve **15 GB livres além do download** para instalação ou atualização. No pacote macOS 26 de `437a8f4`, o tar tem 1.448.521.887 bytes e `PDF.app` ocupa 3.487.890.655 bytes lógicos. A recomendação dá margem sobre cerca de 8,437 GB adicionais sem clones APFS; cada backup preservado acrescenta cerca de 3,49 GB lógicos. Clones APFS podem reduzir as cópias físicas. **O instalador não faz pré-checagem de espaço livre.**
- Para geração de IA: Apple Intelligence disponível, habilitada e com modelo instalado. A ausência do modelo deve aparecer como indisponibilidade; ela não é substituída por resposta fictícia.
- Pages, scanner, Continuidade, certificado, TSA e serviço de assinaturas dependem dos componentes/contas próprios quando essas ferramentas forem usadas.

Não é necessária assinatura paga de desenvolvedor Apple. A assinatura é **ad hoc, sem Developer ID nem notarização Apple**. O instalador mantém Gatekeeper, TLS e verificação de assinaturas ativos. Pode ser necessária a autorização normal do macOS, inclusive para executar o runtime antes da ativação do aplicativo. A cadeia específica de download no navegador, aplicação de quarentena e primeira execução não foi exercitada no GitHub Actions; não há promessa de instalação silenciosa em qualquer política de segurança.

## Instalar o pacote validado

Abra a [release em rascunho privado](https://github.com/vibracall-beep/PDF-/releases/tag/untagged-46d8b6e9889cc9181621) no navegador, autenticado com a conta proprietária do repositório. Baixe **`install-binary.sh`** e **`PDF-arm64.tar.gz`**, mantendo esses nomes em **Downloads**, sem extrair o tar. A release também conserva fontes, manifestos, licenças e evidências; não é preciso baixar os 71 arquivos para instalar. Os downloads retidos não dependem da expiração dos artefatos do GitHub Actions.

O Mac de destino **não precisa de Xcode, Homebrew, Git ou Python previamente instalados**. Cole o bloco abaixo no Terminal. Ele verifica o instalador antes de executá-lo; o instalador exige o SHA-256 do tar, confere a assinatura e o manifesto, instala em `~/Applications/PDF.app` e, se tudo terminar com sucesso, abre o aplicativo.

```bash
/bin/bash <<'PDF_INSTALL'
set -euo pipefail
cd "$HOME/Downloads"
printf '%s\n' '53ecfd803797d72111a0c51050a49a0db75d00dc310c8066a35888400509a211  install-binary.sh' | /usr/bin/shasum -a 256 -c -
test -f ./PDF-arm64.tar.gz
/bin/bash ./install-binary.sh ./PDF-arm64.tar.gz '7dabd68ffcc1b65ea551efd51bb17f9194bb6d3990261f6c52e33735d96cb7ad' "$HOME/Applications"
/usr/bin/open "$HOME/Applications/PDF.app"
PDF_INSTALL
```

| Arquivo desta entrega | Bytes | SHA-256 |
|---|---:|---|
| `install-binary.sh` | 3.344 | `53ecfd803797d72111a0c51050a49a0db75d00dc310c8066a35888400509a211` |
| `PDF-arm64.tar.gz` | 1.448.521.887 | `7dabd68ffcc1b65ea551efd51bb17f9194bb6d3990261f6c52e33735d96cb7ad` |

Se a verificação do instalador falhar ou algum arquivo não estiver no local indicado, o bloco encerra antes de executar o instalador. O checksum do tar é conferido antes da extração. Os valores identificam exatamente a entrega de `437a8f4`; não devem ser reutilizados para outro pacote. Os [recibos da entrega](evidencias/delivery-437a8f4/README.md) conservam a origem desses arquivos.

O terceiro argumento do instalador é a **pasta que receberá `PDF.app`**, não o caminho de `PDF.app`. Para escolher outra pasta, altere `"$HOME/Applications"` e o caminho do comando `open` de forma correspondente. O primeiro argumento aceita também URL HTTPS, mas o modo HTTPS usa `curl` e não herda a sessão autenticada do navegador; para esta release privada, use os arquivos locais.

A assinatura ad hoc não identifica um publicador Apple; a confiança na conta/repositório e no canal que fornece os checksums continua necessária. As condições de Gatekeeper e espaço livre estão descritas acima.

O bundle inclui runtime Python e bibliotecas, qpdf, Tesseract português/inglês, OCRmyPDF, Ghostscript, LibreOffice, Chromium/Playwright, pyHanko, Java e veraPDF fixado. O empacotador verifica arquitetura e relocação; `check-portable.sh` exige execução sem rede e sem ferramentas/dependências externas. A lista CA é pública Mozilla, sem Keychains do host. Em `437a8f4`, montagem, assinatura, runtime isolado e verificações nativas passaram nos dois sistemas, incluindo PDFs protegidos, Office, Java, Chromium e OCR. A extração conservou os modos do arquivo autenticado no staging privado, e a primeira instalação e a atualização passaram em ambos os sistemas. O teste separado [40141728214](https://github.com/vibracall-beep/PDF-/actions/runs/40141728214) aprovou o mesmo binário macOS 26 no macOS 27 e sua interface instalada, vinculados ao arquivo e ao manifesto inalterados. A falha de extração em `352ae6f` e os demais resultados anteriores estão preservados em [VALIDACAO.md](VALIDACAO.md).

## Atualização, recuperação e retorno à versão anterior

Executar o instalador com outro pacote aprovado atualiza o mesmo destino. Preferências, perfis, biblioteca e recuperação ficam fora do bundle e são preservados. Os formatos novos mantêm leitura de presets anteriores; não se promete compatibilidade de qualquer dado futuro com qualquer versão antiga.

O atualizador:

1. Verifica manifesto, identidade e arquivos antes de publicar.
2. Obtém bloqueios exclusivos das instalações envolvidas; recusa substituir um bundle em uso pelos processos que participam do protocolo.
3. Prepara e valida uma cópia, grava um diário durável e preserva `PDF.previous.<identificador>.app`.
4. Ativa a cópia e repete verificações. Falha tratada restaura a anterior; uma interrupção pode deixar diário para recuperação na próxima execução.

Testes reais exercitam cinco pontos com SIGKILL, disco cheio, corrupção e destino alterado por concorrência. HFS+ realmente cheio, desmontagem do volume e recuperação após SIGKILL passaram nos dois sistemas em `cbb3298`. Esses ensaios validam os cenários delimitados do helper; a aprovação posterior de instalação e atualização do pacote `437a8f4` está registrada separadamente. Processos do aplicativo, motor e filhos explicitamente encaminhados mantêm o bloqueio por descritores. Subprocessos internos de terceiros que fecham descritores não têm garantia universal de cobertura.

Para **voltar deliberadamente** a uma versão, use novamente o instalador com o pacote anterior aprovado e seu checksum original. Isso preserva a instalação que está sendo substituída. Não mova bundles manualmente enquanto houver aplicativo, tarefas ou instalador em execução. Não apague cópias anteriores e runtimes durante a investigação de uma interrupção.

Uma instalação antiga sem `Contents/Resources/installation.lock` não pode ser substituída automaticamente por este protocolo. Nesse caso, escolha outra pasta de destino; a versão anterior e suas configurações são preservadas. O instalador não mata aplicações do usuário para forçar a atualização.

No instalador **binário**, um SIGKILL antes da gravação do diário pode deixar `.pdf-download.*` ou `.pdf-incoming.*.app`. Não há limpeza automática universal desses resíduos. Uma transação com diário pode ser recuperada na próxima execução do instalador; essa recuperação não abrange todos os temporários criados antes do diário.

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

A revisão **0.6**, commit `437a8f4d6bb6ebb003859f769e3756fce30c9da3`, tem pacotes aprovados nos dois jobs da matriz. A [tabela de execuções](VALIDACAO.md) conserva o resultado de cada commit e os respectivos originais. A compatibilidade e a interface do mesmo binário entre sistemas também passaram. A entrega [40143091839](https://github.com/vibracall-beep/PDF-/actions/runs/40143091839) terminou com sucesso e preservou os arquivos no [rascunho privado](https://github.com/vibracall-beep/PDF-/releases/tag/untagged-46d8b6e9889cc9181621), tag `delivery-437a8f4d6bb6-40137438618-40141728214`. Os checksums acima identificam o instalador e o tar disponíveis. As falhas anteriores não são apagadas nem reinterpretadas como aprovação.

A base histórica **0.5**, commit `5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`, foi aprovada na [execução 40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837). Os dois sistemas, macOS 26.6.2 e 27.0.1, passaram os checks daquele código. Essa base não contém as 17 ampliações atuais nem o novo pacote portátil. Os [relatórios históricos](evidencias/5a11c07/README.md) conservam sua procedência.

Artefatos `unvalidated` não são aprovados. Um relatório de IA `unavailable` informa ausência do modelo e não aprova qualidade de geração; falhas estritas do Vision também permanecem identificadas mesmo quando o OCR funcional passa com Tesseract. A validação atual precisa distinguir esses estados.

GitHub Actions conserva artefatos por prazo limitado. Esta entrega preserva pacote, fontes, evidências e checksums como arquivos da release, fora desse prazo de expiração. O rascunho continua privado ao proprietário autenticado; não houve publicação pública nem alteração da licença do aplicativo. A disponibilidade depende da manutenção da release e da conta no GitHub.

## Dados e proteção

Os instaladores não removem documentos, preferências, histórico ou recuperação do usuário. Operações produzem arquivos novos e recusam sobrescrita; preservar originais não equivale a preservar a validade de uma assinatura digital sobre bytes editados.

PDFs temporários protegidos e cópias de recuperação permanecem cifrados. Opções enviadas ao motor usam arquivo privado `0600`, cujo nome é removido antes de entregar stdin; não é criptografia nem armazenamento apenas em RAM. Jobs/patches qpdf também usam arquivos privados e podem conter texto e credenciais durante a execução; encerramento abrupto pode deixar resíduos. Senhas não entram em presets/snapshots de configuração. PDFs comuns e metadados da biblioteca não recebem criptografia ponta a ponta adicional.

O manifesto identifica os arquivos do pacote; hashes não substituem a confiança no canal que publica o pacote/checksum. Bibliotecas de terceiros conservam seus avisos e licenças. PyMuPDF é AGPL/comercial; a distribuição deve observar os termos aplicáveis.
