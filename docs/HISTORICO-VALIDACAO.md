# Histórico de validação

Este arquivo preserva registros anteriores. A aprovação vigente, os limites e o commit para instalação estão em [VALIDACAO.md](VALIDACAO.md) e [INSTALACAO.md](INSTALACAO.md).

## Auditoria estrutural posterior a 2816a41

A execução [40039860979](https://github.com/vibracall-beep/PDF-/actions/runs/40039860979), de `2816a41d282c93aadda21b2ba06fede3306697fc`, passou as verificações então existentes em macOS 26 e 27. Cada runner executou 224 casos Python distintos, três verificações nativas, 19 capturas e quatro relatórios AX, instalação e seis operações de benchmark. O Vision estrito passou no macOS 26 e falhou no 27; o produto usou Tesseract real nesse sistema. Os [JSONs originais](evidencias/2816a41/README.md) preservam essa evidência histórica.

A aprovação não cobria o defeito estrutural que a auditoria seguinte revelou. A execução [40041109539](https://github.com/vibracall-beep/PDF-/actions/runs/40041109539), de `d28c929bc116dea3e88eb872a70fbffc67f2ca24`, acrescentou `qpdf --check` aos bytes gravados. O macOS 26 passou; o macOS 27 falhou na cópia comum e na cópia protegida, com status 3. A instalação foi interrompida antes da ativação. Reabrir um PDF no PDFKit e ler texto/campos não bastava para provar sua estrutura válida.

O diagnóstico isolado [40042670948](https://github.com/vibracall-beep/PDF-/actions/runs/40042670948), de `5e062cd052ba30569553725c3c5be6699bced013`, reproduziu no macOS 27: fonte original status 0; cópias PDFKit comum e protegida status 3. A regravação independente manteve status 3 durante a recuperação, mas a verificação dos bytes resultantes terminou com **status 0** nos três casos. Isso demonstra a correção estrutural da amostra, não uma aprovação integral do aplicativo. O diagnóstico preserva os originais e nunca os substitui pelo resultado corrigido.

O log da execução isolada foi acessado normalmente pelo GitHub. O download de seu artefato ficou bloqueado pelo proxy no domínio `productionresultssa5.blob.core.windows.net`; não foi declarada inspeção local desse pacote. As capturas de `d28c929` foram baixadas e revisadas nos dois sistemas, independentemente desse bloqueio.

A primeira integração do verificador, `b37e7de53923096aaa97354196dec9dc477bc531`, foi **reprovada** na execução [40043006983](https://github.com/vibracall-beep/PDF-/actions/runs/40043006983). Ambos os sistemas compilaram e passaram os 224 casos Python; as capturas pararam após cinco PNGs/quatro relatórios AX, ao preparar a recuperação. A comparação detectou diferença de anotações e três grupos nativos recusaram cores padrão sem conversão sRGB. A instalação foi interrompida antes da ativação, sem executar benchmark ou auditoria Vision do aplicativo instalado. O controle de stream corrompido foi corretamente recusado e sua correção pelo caminho de produção terminou com qpdf status 0. Esse resultado não aprova o produto: motivou uma investigação específica dos valores padrão e da serialização de anotações do PDFKit.

O commit `0e4c645d8308f53ea8fc98e542c8eb3e0c2d229f` também foi **reprovado** na execução [40046273593](https://github.com/vibracall-beep/PDF-/actions/runs/40046273593). Os dois sistemas compilaram 40 fontes Swift e passaram os 224 casos Python. O macOS 26 produziu cinco capturas e quatro relatórios AX antes da falha de recuperação; o macOS 27 produziu os 19 estados e quatro relatórios. A comparação rigorosa encontrou vínculos de anotações alterados no macOS 26 e fonte/tamanho de texto alterados no macOS 27. O escritor PDFKit também recusou a senha Unicode de 127 bytes. A ativação, o benchmark e a auditoria Vision do aplicativo instalado não foram aprovados nessa rodada.

Os diagnósticos [40045994115](https://github.com/vibracall-beep/PDF-/actions/runs/40045994115) e [40046646482](https://github.com/vibracall-beep/PDF-/actions/runs/40046646482) identificaram a gravação indevida de strings iniciadas por `/` como nomes PDF. Isso afetava o programa de aparência `/DA`, nomes e valores de formulários e conteúdo de anotações. Acrescentar espaço sintaticamente neutro somente ao programa `/DA` preservou as fontes nas amostras dos dois sistemas; o conteúdo textual do usuário requer reparo de tipo com comparação exata ao valor capturado antes da gravação.

O diagnóstico [40047727166](https://github.com/vibracall-beep/PDF-/actions/runs/40047727166), de `3b95469907d9a64d3211c6e5fa5912b87cd02812`, demonstrou outro defeito do PDFKit 26: `/Fields`, `/Parent` e `/Popup` apontavam para cópias externas idênticas às anotações de `/Annots`. Os PDFs reais do artefato macOS 26 foram baixados. A correção exclusivamente das referências a duplicatas idênticas produziu qpdf status 0, preservando páginas, texto, pixels renderizados e streams; casos ambíguos ou com dicionários diferentes foram recusados. O mesmo diagnóstico demonstrou que `/InkList` armazena polilinhas: curvas Bézier arbitrárias perdem controles ao passar pelo escritor. O aplicativo cria traços poligonais; a auditoria mantém a recusa de uma gravação que perca controles de uma curva importada.

O commit `63bf88a4ba1421e94b2817e90b074ce8734f4b74` foi **reprovado** na execução [40049160286](https://github.com/vibracall-beep/PDF-/actions/runs/40049160286). Ambos os sistemas compilaram 41 fontes Swift, passaram 224 casos Python e produziram 19 capturas mais quatro relatórios AX; os 38 estados foram baixados e revisados visualmente. Recuperação, sessões, publicação protegida comum, reparo de streams, privacidade/cancelamento do patch e recusa de perda de curvas passaram. O macOS 26 passou 22 grupos nativos e falhou em três; o 27 passou 23 e falhou em dois. Persistiram avisos estruturais em regravações específicas no 26 e recusa de tipos em uma amostra editável no 27. A senha Unicode de 127 bytes passou a autenticação independente qpdf, mas falhou ao desbloquear a cópia no PDFKit nos dois sistemas. A instalação continuou bloqueada antes da ativação; não foram executados benchmark completo nem auditoria Vision do aplicativo instalado. A galeria desse commit comprova os estados visuais examinados, sem aprovar a entrega funcional.

O diagnóstico exato [40050744531](https://github.com/vibracall-beep/PDF-/actions/runs/40050744531), de `a517d8d005084f8380ff25bce931093b2c1e7c91`, compilou cópias instrumentadas dos fontes de `63bf88a`, com hashes e âncoras verificados. Os dois jobs concluíram a coleta; os resultados negativos das auditorias permaneceram registrados. Os artefatos de ambos os sistemas foram baixados normalmente. A regravação do PDFKit 26 omitia referências de campos de `/Fields`; no 27, a caixa de seleção tinha `/V` como string e uma aparência normal em stream único. Os reparos locais de referências e tipo passaram no qpdf e preservaram os dados conferidos, sem criar aparências de seleção.

Nas cinco senhas por sistema, qpdf e Core Graphics com UTF-8 explícito autenticaram todos os arquivos. O PDFKit abriu ASCII e o exemplo BMP, mas recusou os exemplos com acentos e emoji; desbloquear seu `documentRef` não atualizou o estado do wrapper. A prova local de uma cópia auxiliar novamente cifrada com senha ASCII preservou estrutura, oito permissões, texto, renderização e hashes dos originais nos dez PDFs. Isso motivou a abertura unificada do produto, ainda sujeita à validação integrada.

As fases independentes também revelaram duas diferenças antes encobertas pela primeira falha: normalizar um PDF com impressão limitada a baixa qualidade ampliava `printhigh` por causa do baseline obtido via `PDFKit.documentRef`; e o getter `shouldPrint` de um Popup independente mudava após reabrir, embora o dicionário inteiro e `/F=4` permanecessem idênticos. A amostra de Popup é adversarial, sem a associação de markup exigida pela especificação. A correção deve preservar os flags serializados, sem ignorar o objeto ou reduzir as verificações. Esses achados exigiram ampliar a abertura, a captura de permissões originais e os testes independentes, em vez de aceitar os resultados anteriores.

A integração `a032b992b20a68ca69fd8005aa78f4681cffa239` foi reprovada na compilação pela execução [40052130258](https://github.com/vibracall-beep/PDF-/actions/runs/40052130258). O SDK resolveu `Darwin.stat` como o tipo C `stat`, recusando os argumentos da consulta de arquivo. Essa rodada não produziu capturas nem aprovou a instalação. O commit `0910ad97614e53fd11becd65e173b6dbaff8cc7a` substituiu essa chamada por `fstatat`, preservando a consulta de arquivo regular e o suporte a caminhos de entrada convencionais, e iniciou nova matriz.

Essas provas isoladas identificam causas e verificam reparos em amostras. Não substituem a execução integral de instalação, recuperação, OCR, interface e auditorias do código integrado, cujo resultado vigente consta em [VALIDACAO.md](VALIDACAO.md).

## Ampliação 0.5.0 em validação

As dez melhorias de [MELHORIAS.md](MELHORIAS.md) estão implementadas. A última execução concluída, [40035676483](https://github.com/vibracall-beep/PDF-/actions/runs/40035676483), aprovou integralmente o job macOS 26 do commit `dec17f819ed00a836d4408433fba2f4db11a33d1`. No macOS 27.0.1, **Vision continua reprovado e impede a ativação da instalação**; os demais grupos nativos, 19 capturas e quatro relatórios AX passaram. A ampliação não tem aprovação integral nos dois sistemas.

O conjunto portátil soma **201 testes distintos: 145 do núcleo, 17 integrações e 39 scripts**, todos executados com sucesso nos dois jobs desse commit. As verificações internas Swift não entram nessa soma. A rodada local anterior passou 145/145 em 19,092 s (`/tmp/pdf-final-145.log`), 17/17 em 57,671 s (`/tmp/pdf-final-17.log`) e 39/39 em 0,997 s na revisão dos scripts. Os quatro casos de opções de formulário `/Opt` e a integração de orientação/ajuste de XLS legado agora também têm execução macOS aprovada.

Um processo isolado do Vision está sendo implementado e revisado depois de `dec17f8`. **Ainda não tem evidência de compilação ou execução aprovada** e não é apresentado como solução confirmada para a falha do macOS 27.

A nova suíte inclui assinaturas PAdES reais e certificados temporários, veraPDF 1.30.3 executado sobre documentos conformes e não conformes, OCR de tabelas raster e fluxos em lote. O teste nativo incorpora recuperação criptografada, abas, edição/desfazer de anotações, referências semânticas e benchmark. O CI exige ainda relatórios AX das próprias janelas e seis operações medidas sobre um documento sintético de 100 páginas, com o alcance por operação descrito abaixo. Nenhum resultado M1 virtualizado é apresentado como medição física M4 ou Neural Engine.

### Última execução concluída: 40035676483

Ambientes: Apple M1 virtualizado, macOS **26.6.2** / Xcode **26.6** / SDK **26.5**, e macOS **27.0.1** / Xcode **27.1** / SDK **27.0**. Logs locais: `/tmp/pdf-dec17-26.log` e `/tmp/pdf-dec17-27.log`.

| Verificação | macOS 26 | macOS 27 |
|---|---|---|
| Compilação arm64 | Aprovada | Aprovada |
| Núcleo | 145/145 em 26,709 s | 145/145 em 24,966 s |
| Integrações reais | 17/17 em 22,416 s | 17/17 em 18,309 s |
| Scripts | 39/39 em 1,136 s | 39/39 em 1,378 s |
| Smoke nativo | Três execuções aprovadas | Duas reprovadas somente no grupo Vision |
| Instalação | Ativada e verificada | Interrompida antes da ativação |
| Capturas e AX | 19 PNGs e quatro relatórios aprovados | 19 PNGs e quatro relatórios aprovados |
| Benchmark completo, incluindo OCR | Seis operações aprovadas | Não executado após falha da instalação |

Os cinco identificadores AX antes ausentes foram encontrados nos relatórios atuais; nenhum dos quatro relatórios apresentou falhas nos critérios automatizados. Isso encerra aquelas regressões de identificação na árvore, mas não comprova uso com VoiceOver, qualidade visual de todos os controles ou cobertura de todas as interações.

No macOS 27, Vision falhou nas três tentativas precisas de produção. Os cinco diagnósticos adicionais também falharam: API legada fora da thread principal, sem correção linguística, com entrada PNG e API Swift com CGImage/PNG. Os diagnósticos preservaram a reprovação original, sem fabricar texto reconhecido. Os demais grupos, incluindo `QuadPoints`, passaram; a causa do erro no runtime ainda está em investigação.

O benchmark macOS 26 usou 100 páginas sintéticas e três amostras após aquecimento. Medianas: abertura **0,141 ms**, extração **5,041 ms**, busca **1,272 ms**, renderização **5,190 ms**, contraste **15,635 ms** e OCR **1.698,927 ms**. OCR/contraste medem somente a primeira página; renderização cobre primeira, intermediária e última. Não são medições em M4 físico nem de NPU.

Artefatos: [capturas macOS 26](https://github.com/vibracall-beep/PDF-/actions/runs/40035676483/artifacts/12536299487), [capturas macOS 27](https://github.com/vibracall-beep/PDF-/actions/runs/40035676483/artifacts/12537116774), [benchmark macOS 26](https://github.com/vibracall-beep/PDF-/actions/runs/40035676483/artifacts/12537326278) e [fontes aprovadas para esse job macOS 26](https://github.com/vibracall-beep/PDF-/actions/runs/40035676483/artifacts/12537022283). O pacote do ambiente 27 permanece [não validado](https://github.com/vibracall-beep/PDF-/actions/runs/40035676483/artifacts/12537460882). Nenhuma aprovação deste commit se estende ao worker em desenvolvimento.

### Histórico: execução 40034287285

A [execução 40034287285](https://github.com/vibracall-beep/PDF-/actions/runs/40034287285), do commit `a4e6efd858e0d845e48a9420467b660ebc64d7bf`, terminou com falhas nos dois jobs. Os ambientes continuaram Apple M1 virtualizado: macOS **26.6.2**, Xcode **26.6**, SDK **26.5**; e macOS **27.0.1**, Xcode **27.1**, SDK **27.0**. Os logs locais são `/tmp/pdf-a4e6-26.log` e `/tmp/pdf-a4e6-27.log`.

| Verificação | macOS 26 | macOS 27 |
|---|---|---|
| Compilação arm64 | Aprovada | Aprovada |
| Núcleo presente nesse commit | 141/141 em 26,250 s | 141/141 em 24,647 s |
| Integrações presentes nesse commit | 16/16 em 21,786 s | 16/16 em 17,412 s |
| Scripts | 39/39 em 1,292 s | 39/39 em 1,142 s |
| Smoke nativo | Três execuções aprovadas | Duas execuções reprovadas somente no grupo Vision |
| Instalação | Ativada e verificada | Interrompida antes da ativação |
| Capturas e verificador PNG | 19 PNGs aprovados, quatro relatórios AX | 19 PNGs aprovados, quatro relatórios AX |
| Auditoria AX | Reprovada: cinco identificadores únicos ausentes | Reprovada: os mesmos cinco identificadores |
| Benchmark completo, incluindo OCR | Seis operações aprovadas | Não executado após falha da instalação |

No macOS 27, Vision tentou reconhecimento preciso em inglês por três caminhos: revisão 3 automática, revisão 3 com CPU e revisão 2 automática. Todos retornaram `Foundation._GenericObjCError (0)`. A tentativa CPU ocorreu nesta rodada, mas **não resolveu a falha**. Os outros grupos nativos passaram, incluindo a nova auditoria de `QuadPoints`, que conferiu números serializados e geometria após reabrir o PDF; os avisos de serialização anteriores não reapareceram.

Naquela rodada, os identificadores AX ausentes eram `pdf.catalog.search`, `pdf.customize.toolbar`, `pdf.reader.search`, `pdf.reader.page` e `pdf.reader.inspector`; o relatório lado a lado passou. O verificador fortalecido registra também a falha agregada dos identificadores, por isso o número de mensagens não equivale à quantidade de identificadores únicos. Os dois pacotes de fontes daquela rodada foram identificados como **não validados**.

No benchmark do macOS 26, com o mesmo corpus de 100 páginas e três amostras após aquecimento, as medianas foram: abertura **0,143 ms**, extração **5,891 ms**, busca **1,341 ms**, renderização **6,500 ms**, contraste **13,504 ms** e OCR **1.793,403 ms**. OCR/contraste continuam limitados à primeira página; renderização cobre primeira, intermediária e última. Esses resultados não medem M4 físico nem NPU.

Artefatos desta rodada: [capturas macOS 26](https://github.com/vibracall-beep/PDF-/actions/runs/40034287285/artifacts/12536581842), [capturas macOS 27](https://github.com/vibracall-beep/PDF-/actions/runs/40034287285/artifacts/12535839552) e [benchmark macOS 26](https://github.com/vibracall-beep/PDF-/actions/runs/40034287285/artifacts/12537270045). Esses eram os resultados de `a4e6efd`; a rodada `dec17f8` acima encerrou as falhas AX, mas manteve Vision reprovado no macOS 27.

### Rodadas anteriores da ampliação

As execuções intermediárias `40024594172` e `40025626994` compilaram e capturaram a interface, mas **não aprovaram o conjunto**: houve falha do Vision no macOS 27 e falha da auditoria de realce no macOS 26. As execuções posteriores superaram as verificações nativas no macOS 26; o estado atual está na seção de `dec17f8` acima.

A execução [40028618566](https://github.com/vibracall-beep/PDF-/actions/runs/40028618566), do commit `7cf1b14fae2267750d1dea3813e82a829f365efd`, compilou o conjunto ampliado em ambos os sistemas. Entretanto, a captura parou depois da comparação lado a lado e o teste de concorrência de destinos não provocou a corrida esperada: a comparação do hook ignorava a canonicalização de `/var` para `/private/var` no macOS. O instalador encerrou nessa falha do teste Python, antes das verificações nativas. Não houve aprovação da instalação nem do benchmark. As capturas parciais também revelaram abas ocultas e relatórios AX incompletos; esses achados motivaram as correções e verificações das rodadas posteriores.

### Histórico: execução 40032691474

O [job macOS 26](https://github.com/vibracall-beep/PDF-/actions/runs/40032691474/job/120684555727), do commit `7407bf3a81c2417c82cd9ed460438930d2fa2df5`, executou em macOS **26.6.2**, Xcode **26.6**, SDK **26.5**, **Apple M1 (Virtual)** com três CPUs e dispositivo gráfico **Apple Paravirtual device**. O log foi preservado no ambiente de desenvolvimento em `/tmp/pdf-7407-26.log`.

| Verificação | Resultado nesse commit e ambiente |
|---|---|
| Compilação Swift arm64 release | Aprovada |
| Scripts de instalação e diagnóstico | 23/23 aprovados em 1,396 s |
| Motor Python | 141/141 aprovados em 26,617 s |
| Integrações externas reais | 16/16 aprovadas em 23,166 s |
| Smoke nativo | Três execuções aprovadas: após compilar, no bundle preparado e após ativar a instalação |
| Instalação, arquitetura e assinatura ad hoc | Aprovadas; aplicativo ativado e verificado |
| Capturas reais | 19 PNGs registrados pelo WindowServer; quatro relatórios AX produzidos |
| Verificação AX | **Reprovada:** cinco identificadores obrigatórios ausentes |
| Benchmark de seis operações, incluindo Vision OCR | Aprovado, com três amostras por operação após aquecimento |

A falha AX foi a única etapa reprovada desse job. Faltaram `pdf.catalog.search` e `pdf.customize.toolbar` na tela inicial, `pdf.reader.search` e `pdf.reader.page` no leitor e `pdf.reader.inspector` nas anotações. O relatório da comparação lado a lado não apresentou falhas. Gerar imagens e ler a árvore AX não comprova a correção visual de todos os estados nem substitui uso real com VoiceOver. **O job não aprovou a ampliação**, e o pacote foi identificado como `PDF-source-unvalidated-macos-26`.

As regressões que bloqueavam a rodada anterior foram exercitadas novamente. O histórico de anotações agora nomeia o grupo ativo do `UndoManager` antes de fechá-lo, respeitando grupos externos e os de desfazer/refazer; a auditoria nativa passou e a captura avançou além da inserção de nota. No teste de concorrência de lotes, a comparação do hook normaliza somente o diretório pai, exige uma injeção e confere preservação de inode, conteúdo e symlink. Essa correção do teste não alterou as primitivas de publicação do motor; os 12 casos de lote passaram dentro dos 141 testes.

Na auditoria semântica, 39 verificações passaram. Embeddings Apple foram efetivamente executados em **um dos dois idiomas testados: inglês**. O modelo português estava indisponível; a busca por termos foi testada separadamente. Esse resultado não demonstra geração de respostas pelo Foundation Models.

O benchmark usou o corpus sintético `text-and-vector-v1`, com 100 páginas. Extração e busca percorrem o documento; renderização mede primeira, intermediária e última páginas; contraste e OCR medem **somente a primeira página**. As medianas foram: abertura **0,189 ms**, extração **5,772 ms**, busca **1,223 ms**, renderização **7,365 ms**, contraste **14,171 ms** e OCR **2.108,021 ms**. Não são medições de OCR de 100 páginas, cache frio, M4 físico ou utilização de NPU.

Artefatos: [capturas e relatórios AX](https://github.com/vibracall-beep/PDF-/actions/runs/40032691474/artifacts/12535668111), [benchmark](https://github.com/vibracall-beep/PDF-/actions/runs/40032691474/artifacts/12534814579) e [fontes não validadas](https://github.com/vibracall-beep/PDF-/actions/runs/40032691474/artifacts/12534899397).

O outro job executou em **macOS 27.0.1**, Xcode **27.1**, SDK **27.0** e Apple M1 virtualizado. Compilação, **141/141 testes do motor em 24,189 s**, **16/16 integrações em 16,497 s** e **23/23 testes dos scripts em 1,179 s** passaram. Os dois smokes executados reprovaram somente o grupo Vision: reconhecimento preciso em inglês, revisão 3, retornou `Foundation._GenericObjCError (0)`; nenhuma tentativa CPU foi registrada. Os demais grupos nativos, incluindo recuperação, sessões e histórico, passaram. A instalação parou nesse smoke antes da ativação, e o benchmark completo de 100 páginas não foi executado. As 19 capturas e quatro relatórios AX foram gerados, com os mesmos cinco identificadores ausentes. [Artefato visual do macOS 27](https://github.com/vibracall-beep/PDF-/actions/runs/40032691474/artifacts/12534514638); log local `/tmp/pdf-7407-27.log`.

Nesse commit `7407bf3`, macOS 27.0.1 tinha compilação e execução parcial, mas Vision, instalação e AX reprovaram. A rodada posterior `dec17f8` encerrou as falhas AX, mantendo Vision pendente. Os resultados históricos não aprovam automaticamente alterações posteriores.

Após esse commit, a suíte de scripts cresceu de 23 para 39 testes e foi executada na rodada `a4e6efd` descrita acima. Os resultados de `7407bf3` continuam restritos aos testes e fontes daquele commit.

## Histórico anterior: Linux

- 61 testes funcionais do motor: aprovados, sem falhas ou testes ignorados.
- Oito testes com integrações externas: aprovados, sem falhas ou testes ignorados.
- Verificações incluem alteração de documentos, formulários, criptografia, redaction, preservação de originais, publicação sem sobrescrita, cancelamento de processos, conversões Office, HTML, OCR e PDF/A.
- Casos de tradução do motor verificam inserção de texto traduzido fornecido no teste; não demonstram geração pelo modelo Apple.
- PDF/A foi gerado e seu identificador XMP foi verificado. Isso não substitui um validador independente de conformidade.
- Sintaxe shell verificada. Código Swift analisado por parser; esse resultado não substitui compilação ou checagem de tipos no SDK Apple.
- Empacotamento de fontes verificado quanto a reprodutibilidade, checksums, exclusões e não sobrescrita.
- Novos casos incluem transparência PNG, EPUB, TXT Unicode e palavras de 5.000 caracteres sem perda, achatamento com aparência preservada, exclusão/extração protegidas, ODT, RTF e CSV com campos longos, multilinha e fórmulas tratadas como texto.
- Catálogo conferido: 49 identificadores únicos, nenhum comando de motor sem correspondência. Os 45 itens da terceira imagem estão mapeados em `FERRAMENTAS.md`; o leitor possui acesso permanente na barra lateral.

## macOS: execução real pelo GitHub Actions

O usuário autorizou GitHub Actions. A matriz atual de `.github/workflows/macos.yml` usa os ambientes Apple Silicon `macos-26` e `xcode-27`. Compila e executa um smoke nativo antes de instalar as dependências, captura janelas reais pelo ScreenCaptureKit restrito ao próprio processo, executa a instalação e valida o bundle assinado localmente. O CI exige 19 PNGs e quatro relatórios AX, além do benchmark. Uma falha de captura ou acessibilidade permanece como falha do job, mas não impede verificações independentes da instalação. O pacote de fontes só recebe identificação de validado se todas as etapas exigidas forem aprovadas. O instalador requer macOS 26 e Swift 6.2 ou posteriores.

`PDF --smoke-test` contém verificações de PDFKit, busca, formulários, persistência de anotações, renderização, Vision OCR a partir de página sem texto, melhoria de imagem Core Image/Metal, divisão e recuperação de contexto para IA, validação estrutural de questões, exportação PDF, criptografia, importação de capturas e publicação atômica.

A versão ampliada do commit `9d72a9d75da72437a68d411359906e3e10a4466e` foi aprovada integralmente na execução [40019981712](https://github.com/vibracall-beep/PDF-/actions/runs/40019981712), em 23/10/2026:

| Verificação | Resultado |
|---|---|
| Compilação Swift arm64 release | Aprovada |
| Motor Python | 61/61 aprovados |
| Integrações externas | 8/8 aprovadas |
| Arquitetura, assinatura ad hoc e dependências | Aprovadas |
| Runtime instalado e Chromium | Aprovados |
| Testes nativos antes/depois da ativação | Aprovados nas duas execuções |
| Ativação do aplicativo | Aprovada |
| Capturas reais da tela inicial e do leitor | Geradas e revisadas visualmente |
| Pacote de fontes e checksum | Gerados |

Ambiente real: macOS **26.6.2**, Xcode **26.6**, SDK **26.5**, processador **Apple M1 (Virtual)** com três CPUs. O contexto gráfico identificado foi **Apple Paravirtual device**. Esse ambiente confirma execução nativa arm64 e dos frameworks testados; não é uma medição em M4 físico nem comprova utilização do Neural Engine.

Artefatos da execução: [preview nativo](https://github.com/vibracall-beep/PDF-/actions/runs/40019981712/artifacts/12529953197) e [fontes](https://github.com/vibracall-beep/PDF-/actions/runs/40019981712/artifacts/12530890738). SHA-256 do pacote dessa execução: `7ff9635c786dfaa3d096ad39c3ff406006ba8faa0ff24e1622c068a6fb55e449`.

Naquela execução, as duas imagens de 1050 × 772 pixels do menu e leitor foram baixadas e abertas para inspeção no artefato imutável vinculado acima. Foram conferidos barra lateral, rótulos, busca, categorias, três colunas de cartões, favoritos, controles do leitor, miniaturas e texto do PDF de exemplo. Naquela inspeção foram usados os bytes do artefato original, sem montagem ou retoque. A galeria atual do repositório foi substituída por capturas posteriores, identificadas em sua procedência, e não representa os bytes desta execução histórica. As capturas anteriores por cache de NSView apresentavam áreas vazias e foram substituídas; não eram evidência adequada da aparência real.

Esta revisão abrange somente os dois estados capturados, no modo claro. Não comprova todos os tamanhos de janela, temas, interações ou uso com VoiceOver. O preflight global de captura foi registrado como disponível no runner; a implementação usa somente a lista de janelas do próprio processo e não altera permissões do sistema.

Scanner físico, iPhone/Continuity Camera, respostas Foundation Models, exportação real pelo Pages e desempenho no hardware do usuário requerem dispositivos/aplicativos/capacidades disponíveis no ambiente de validação; um teste de disponibilidade não comprova a execução dessas funções. O acesso ao Sign.com é uma abertura de serviço externo, sem simulação de integração com conta ou API.

## Uso de memória observado em Linux

A comparação visual e a exportação Markdown passaram a gravar partes da saída à medida que são produzidas. Em uma amostra de 32 páginas de 400 × 400 pontos, com uma imagem RGB de ruído de 400 × 400 pixels reutilizada e uma linha de texto por página:

| Operação | Pico de RSS antes | Pico de RSS depois |
|---|---:|---:|
| Comparação visual do arquivo consigo mesmo, 96 DPI | 282.732 KiB | 69.884 KiB |
| Markdown com imagens incorporadas | 101.044 KiB | 61.144 KiB |

Medição por processos separados com `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss`, Linux x86_64, Python 3.12.14, PyMuPDF 1.26.5 e Pillow 12.0.0. Os números foram registrados na saída das ferramentas durante o desenvolvimento; não há log de RSS arquivado no repositório. A comparação é entre a implementação acumuladora de `953be71` e a implementação em fluxo de `2f8a853`.

Os arquivos antes/depois foram novamente comparados por SHA-256: HTML de 68.608.827 bytes (`ddfd7e3c141a05eb172c29db72a4863338ea2879c4481535839f1be432f0a3fa`) e Markdown de 20.509.892 bytes (`89ddcbd236f81266193922bc691b79042f513faf96af356a0130f958164ebf85`) são idênticos. Os hashes demonstram equivalência dessa saída, não validam sozinhos as medições de memória. Estes resultados não são benchmarks M4 nem medições do Neural Engine.

## Alcance da entrega

O instalador de fontes foi executado com sucesso no runner macOS. A instalação recompila e prepara o runtime no próprio computador; não existe uma alegação de bundle portátil ou notarizado. Os comandos estão em `INSTALACAO.md`. O usuário pediu para testar somente após a conclusão: as verificações de desenvolvimento foram realizadas pelo processo de implementação, sem transferi-las ao usuário.

Validação integral de execução e interface em **macOS 27.0.1**, equipamentos físicos, geração por Apple Intelligence e exportação pelo Pages permanecem pendentes. Os critérios AX automatizados passaram em `dec17f8`, com o alcance limitado indicado acima. Portanto, não se declara validação total de todos os requisitos originais nem uma versão universalmente livre de erros.

## 0910ad9 — abertura, permissões e recuperação aprovadas; dois grupos restantes

A execução [40052366911](https://github.com/vibracall-beep/PDF-/actions/runs/40052366911) compilou 41 arquivos Swift e aprovou os 224 testes Python em ambos os sistemas. Cada sistema aprovou 24 grupos nativos e reprovou dois. A instalação parou antes da ativação. Senhas Unicode, oito permissões, filas de abertura, recuperação criptografada e cancelamento passaram. A fixture negativa do parser possuía herança válida e foi corrigida localmente. A lista protegida no macOS 26 e Popup aberto no macOS 27 motivaram diagnóstico exato [40053626084](https://github.com/vibracall-beep/PDF-/actions/runs/40053626084), commit `5a643db2e69c99baf27a3eed6e668e4336fe2ba5`. Os 19 PNGs e quatro relatórios AX de cada sistema passaram; os 38 estados foram revisados. Não há benchmark ou auditoria Vision da instalação final dessa revisão.

## 5a643db e 91a55fa — distinção entre dados gravados, getters e fixture

Os diagnósticos [40053626084](https://github.com/vibracall-beep/PDF-/actions/runs/40053626084) e [40053904932](https://github.com/vibracall-beep/PDF-/actions/runs/40053904932) executaram cópias instrumentadas e identificadas por hash dos fontes `0910ad9`, em ambos os sistemas. Sucesso do diagnóstico não significa aprovação funcional. No macOS 26, o getter da lista protegida devolveu `Second label`, mas o qpdf confirmou `/V` como string `second`, opções e tipo da lista preservados. No macOS 27, o escritor gravou `/Open` como número `1`, quando a API antes da gravação continha booleano `true`; o leitor interpretou esse número como fechado. O reparo mantém o valor booleano capturado antes da gravação, sem aceitar mudanças reais do estado.

O diagnóstico ampliado mostrou que a atribuição de `.red` no teste de cor já retornava uma cor convertida pelo PDFKit antes de salvar, e que a gravação conservou essa cor. A fixture negativa precisa conferir a alteração efetivamente aplicada, sem ampliar tolerâncias. Os logs compactos sustentam essas conclusões; o download dos artefatos de `5a643db` permaneceu bloqueado por HTTP403 em `productionresultssa0.blob.core.windows.net`. Não foi alegada inspeção de arquivos inacessíveis.

## 2778686 e d66f674 — consistência das preferências e detecção byte a byte

A execução [40054223156](https://github.com/vibracall-beep/PDF-/actions/runs/40054223156), de `2778686`, foi cancelada deliberadamente antes de concluir a instalação para incorporar uma lacuna comprovada de detecção de edições Unicode. A matriz [40054501899](https://github.com/vibracall-beep/PDF-/actions/runs/40054501899) examina `d66f674055a322005148edea13a7ce5073ad8273`. O estado dos formulários usa SHA-256 de componentes UTF-8 com comprimentos explícitos; marcas combinantes canonicamente iguais mas distintas em bytes exigem nova recuperação. A integração inclui preferências de zoom/visualização do leitor e referência, descarte de callbacks de abas antigas, liberação de buscas e um seletor comum de destino para todos os painéis de exportação. Os testes nativos têm limite de 240 segundos, ajustado para os casos adicionais, mantendo todos os controles e limites próprios de subprocessos.

## d66f674 — teste com acesso privado; d3b3857 — correção pela API pública

A matriz `40054501899` reprovou a compilação nos dois sistemas: o teste novo de recuperação tentou ler `generation` e `sha256`, campos privados de `RecoveryRecord`. Não houve capturas, instalação ou medição dessa rodada. O commit `d3b3857228f522f1f731d1ac429b262c25d4647a` compara os bytes devolvidos por `RecoveryStore.load` antes e depois da alteração, mantendo o encapsulamento e exigindo recuperação distinta com o valor UTF-8 correto. A execução [40054628483](https://github.com/vibracall-beep/PDF-/actions/runs/40054628483) revalida a integração completa.

## d3b3857 — macOS 27 aprovado; macOS 26 rejeitou o default válido de Popup

A execução [40054628483](https://github.com/vibracall-beep/PDF-/actions/runs/40054628483) aprovou integralmente o job macOS 27: 224 testes Python, 26 grupos nativos em cada uma das três execuções, instalação/ativação, 19 imagens/quatro relatórios AX e seis operações de benchmark. Os dois testes estritos do Apple Vision falharam; o OCR funcional e o benchmark utilizaram Tesseract. O macOS 26 aprovou os 224 testes Python e 25 grupos nativos; reprovou somente a auditoria do Popup fechado, depois de qpdf status0. O resultado global permaneceu reprovado. Os downloads das prévias e dos relatórios27 foram bloqueados por HTTP403 em `productionresultssa11.blob.core.windows.net`; a galeria0910 foi preservada, sem aprovação visual manual atual.

O diagnóstico [40055470424](https://github.com/vibracall-beep/PDF-/actions/runs/40055470424), commit `24ad1e48bbd6aa55d65eb660c9e84d328d956f69`, confirmou nos bytes: macOS26 omite `/Open` quando fecha o Popup. O campo é opcional e seu valor padrão é `false`; exigir presença explícita era erro da auditoria. Os dois artefatos diagnósticos foram recebidos normalmente. O commit `5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad` aceita ausência somente quando espera fechado; valores presentes continuam exigindo booleanos reais, e a verificação de perda do estado aberto permanece estrita. A matriz [40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837) revalida essa correção.

## 5a11c07 — matriz completa aprovada nos dois sistemas

A execução [40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837), do commit `5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`, terminou aprovada em ambos os jobs. Cada sistema aprovou 224 casos Python distintos e 26 grupos nativos em três execuções, instalação/ativação e benchmark com seis operações. Os dois conjuntos de 19 imagens/quatro AX foram recebidos, validados e seus 38 estados revisados. Os quatro JSONs originais de Vision/benchmark e os dois pacotes de fontes também foram recebidos normalmente. A capacidade Apple Vision passou no26 e falhou nos dois checks do27, onde o OCR funcional e as quatro chamadas do benchmark usaram Tesseract. Medições, procedência, limites e comandos fixados estão em [VALIDACAO.md](VALIDACAO.md) e [INSTALACAO.md](INSTALACAO.md).

## Primeiras rodadas 0.6 — falhas anteriores à reconexão GitHub

| Revisão / execução | Resultado observado e correção |
|---|---|
| `4cd755c` / [40062813526](https://github.com/vibracall-beep/PDF-/actions/runs/40062813526) | Compilação passou nos dois SDKs; falha em expectativas antigas de tabela que supunham cabeçalho em A1. Corrigidas para conferir conteúdo e tabela sem descartar prosa. Ensaios reais HFS+ cheio/SIGKILL do atualizador passaram, sem aprovação do bundle portátil |
| `662edfe` / [40063951872](https://github.com/vibracall-beep/PDF-/actions/runs/40063951872) | SwiftUI excedeu capacidade de type-check em SettingsExchangeView; tela dividida em subviews. A execução foi substituída pela seguinte |
| `e1e8e0a` / [40064237569](https://github.com/vibracall-beep/PDF-/actions/runs/40064237569) | Compilação aprovada nos dois SDKs, 233 testes de núcleo e 37/38 integrações por sistema. Falha restante: descoberta do ICC no novo layout Ghostscript Homebrew. Localização corrigida no teste e no empacotador; integração Linux reexecutada com sucesso |

Um diagnóstico SDK26 já havia extraído metadados App Intents, mas as tentativas seguintes não completaram os dois SDKs. O gate foi endurecido para conferir ações, tipos, parâmetros e provider reais. A autenticação GitHub posteriormente retornou HTTP 401 e suspendeu novos envios; o acesso foi restabelecido antes das rodadas `fcac3db` abaixo. O bloqueio temporário não foi tratado como aprovação de qualquer código.

## fcac3db — ampliação compila nos dois sistemas; duas verificações nativas reprovadas

A matriz [40101134318](https://github.com/vibracall-beep/PDF-/actions/runs/40101134318), do commit `fcac3db3448762185f6c09f106dd995d252f54db`, compilou o aplicativo e aprovou os testes Python em ambos os sistemas. Cada job registrou **389 casos distintos: 388 executados e aprovados, um ignorado**. O caso ignorado depende de `/dev/full` do Linux; o teste de volume HFS+ realmente cheio passou no Mac, assim como os testes de interrupção por SIGKILL.

| Conjunto | macOS 26 | macOS 27 |
|---|---:|---:|
| Núcleo Python | 268 aprovados · 74,452 s | 268 aprovados · 83,861 s |
| Integrações Python | 45 aprovadas · 47,809 s | 45 aprovadas · 67,321 s |
| Scripts | 75 aprovados + 1 ignorado · 16,781 s | 75 aprovados + 1 ignorado · 17,002 s |
| Fases nativas iniciadas no primeiro smoke | 37 | 37 |
| Fases nativas aprovadas / reprovadas | 35 / 2 | 35 / 2 |

As duas falhas foram iguais nos sistemas: `Command palette shortcuts and workspace profiles` recusou a expectativa de reordenação do perfil; `Opt-in folder automation` recusou a asserção conjunta de filtragem e chave de caminho. As demais fases continuaram e seus resultados foram preservados. Passaram, entre outras, recuperação real após SIGKILL, retenção do lease em processos nativos, biblioteca/revisões/sincronização, transporte privado, contratos de edição/OCR e as verificações de serialização, senhas Unicode e permissões originais. O resultado global continuou **reprovado**, e o instalador parou antes da ativação. Essa rodada não aprovou os smokes posteriores, as 32 capturas/cinco relatórios AX previstos, o benchmark, o ensaio com o modelo Apple nem a distribuição portátil.

Em paralelo, o diagnóstico [40101147782](https://github.com/vibracall-beep/PDF-/actions/runs/40101147782), do mesmo commit, extraiu metadados App Intents reais com sucesso nos SDKs 26 e 27. Os artefatos originais foram baixados, e os JSONs `extract.actionsdata`/`version.json` passaram também pelo validador completo de produção: duas ações, entrada de arquivo PDF, fluxo obrigatório, provider, frases e consulta da entidade. Os identificadores de ferramentas foram `17F113` e `27A9275`. Os [bytes originais e a procedência](evidencias/fcac3db-sdk/README.md) preservam a prova. Extração válida não comprova, por si só, registro ou interação pelo aplicativo Atalhos.

## d0fda92 — aplicativo aprovado no macOS 26; empacotamento e teste HFS+ reprovados

O commit `d0fda928678a52b545302dd17f99992abce5aa93` corrige a auditoria de perfis: mover OCR **antes de Juntar PDF** não o torna o primeiro cartão quando `conversion-audit` já precede ambos. O teste antigo também não alterava efetivamente a ordem antes de restaurar. A nova auditoria exige a ordem completa de ferramentas e navegação, inverte ambas antes da aplicação, reabre as preferências e confere os bytes persistidos do perfil. A revisão do código encontrou ainda normalização descartada por uma segunda decodificação; o perfil passa a gravar o snapshot validado. IDs removidos ou duplicados são tratados sem perder a identidade dos cartões, com negativos de migração preservados.

Na automação, a asserção anterior combinava quantidade e presença de uma chave não canônica. O diagnóstico da nova rodada confirmou `legacyCount=1`, `rawLookup=false`, `canonicalLookup=true`, `rootHasAlias=true`: a filtragem produzia um único arquivo, mas o acesso pela chave divergia sob `/var` e `/private/var`. A correção canonicaliza somente a pasta após conferir tipo e identidade; cada folha continua passando por `lstat`, sem resolver links. A auditoria separa quantidade e chave exata, registra apenas indicadores booleanos de caminhos e acrescenta aliases ancestrais, ausência de replay, regra duplicada, diretório com extensão PDF, FIFO, links quebrados, troca de arquivo por link e cancelamento. Não aceita uma filtragem mais permissiva para fazer o teste passar.

Os ajustes receberam revisão independente de código. Na matriz [40103086558](https://github.com/vibracall-beep/PDF-/actions/runs/40103086558), o macOS 26 aprovou compilação, instalação/ativação por fontes e todos os **37 grupos nativos nas três execuções**. Os testes Python passaram: 268 de núcleo em 79,374 s; 45 integrações em 57,702 s; 75 testes de scripts e um skip Linux em 17,212 s. São 389 casos distintos, 388 aprovados e um ignorado. As 32 capturas reais/cinco relatórios AX passaram; as 32 imagens foram revisadas manualmente. Os seis testes de benchmark passaram em Apple M1 Virtual, com corpus sintético de 100 páginas; OCR/contraste medem só a primeira página. Os dois checks Vision passaram. O ensaio Apple registrou `unavailable`/`deviceNotEligible`, sem tentativa de geração em nenhum dos cinco casos. Os [quatro relatórios originais](evidencias/d0fda92-macos26/README.md) conservam hashes e procedência.

**A execução global reprovou.** O job27 parou antes de compilar porque `hdiutil detach` retornou 16 (`busy`) ao desmontar o volume HFS+ da fixture depois do corpo do teste. O job26 chegou pela primeira vez ao empacotamento portátil, que recusou `/opt/homebrew/etc/ca-certificates/cert.pem` como referência externa. Isso não aprova relocação, isolamento, instalação ou atualização do pacote autocontido. A revisão visual também encontrou títulos preenchidos sem rótulos persistentes nos painéis; ajustes preservando bindings/ações foram incluídos no snapshot seguinte.

## 766fe59 — HFS+ corrigido; fixture CA reprovada por alias de caminho

O commit `766fe59459b79f279d41803e9602995497bf0153`, [40105444603](https://github.com/vibracall-beep/PDF-/actions/runs/40105444603), inclui rótulos persistentes, limpeza do volume de teste e seleção da lista pública Mozilla no bundle. A desmontagem valida imagem/dispositivo antes de cada tentativa, repete somente erro `busy` e não usa força; uma falha de cleanup não apaga o erro original. O empacotador não copia a lista de certificados do host mesclada com Keychains e mantém a recusa de outras referências externas.

Nos dois sistemas, o teste HFS+ real passou. A etapa de scripts teve **81 casos: 79 aprovados, um reprovado e um skip**; tempos 16,578 s no26 e 16,485 s no27. A falha comparou `/var` com `/private/var` no teste CA; não demonstrou divergência no certificado selecionado. A fixture foi corrigida com raiz canônica e `samefile`; seus três casos focais passaram localmente em 0,174 s. Como a etapa de integridade reprovou, **não houve compilação nem nova validação visual/nativa deste snapshot**. O isolamento Python e as correções aguardam nova matriz; pacote portátil, M4 físico, modelo Apple e VoiceOver humano não recebem aprovação por antecipação.

## Correções posteriores a 766fe59 — aguardando nova matriz

A auditoria ampliou o isolamento do pacote: a política `sitecustomize.py` gerada pelo Homebrew é retirada somente das cópias, com o texto original preservado fora do caminho de importação; nenhum `.pth` do host deve executar. A trust store e o diretório TLS passam a ser internos. Fontconfig usa configurações públicas selecionadas, fontes do sistema/usuário e cache fora do bundle assinado; o verificador exige configurações internas e descoberta de fonte real. Os 87 testes de scripts passaram localmente com 86 executados e um HFS+ exclusivo de macOS ignorado (2,510 s). Isso não substitui isolamento do pacote no Mac.

A prévia de validação/assinatura passa a rejeitar callbacks após alteração de contexto ou saída da tela. PDF→Excel conserva valores como `=1+1`, `-12`, `+55` e texto Unicode como strings, sem apóstrofos adicionais e sem fórmulas no XML. Foram aprovados 14 testes focados e três integrações reais LibreOffice (38,613 s); uma nova integração de ida e volta amplia o conjunto de 45 para 46 casos, ainda sem execução agregada macOS deste snapshot.

A comparação entre PDFs seleciona documentos distintos antes de trechos adicionais de uma mesma fonte, preservando o ranking de busca/resposta comum. Interface, geração e validação usam o mesmo contexto efetivamente incluído no orçamento de 4.500 caracteres. A auditoria nativa acrescenta o cenário de oito trechos dominantes de A e um relevante de B, truncamento e referências indevidas. Parser e revisão independente passaram; a execução dessas regressões nativas ainda depende da próxima matriz.

## 73c9863 — aplicação ampliada passa nos dois sistemas; pacote portátil reprovado

A execução [40106710898](https://github.com/vibracall-beep/PDF-/actions/runs/40106710898), do commit `73c98630e50e4b978f0bebeeb7965613c2d4536f`, compilou, instalou e ativou o aplicativo por fontes nos dois sistemas. Cada job aprovou **401 casos Python distintos: 400 executados e aprovados, um ignorado**, e todos os **37 grupos nativos nas três execuções**. O caso ignorado depende de `/dev/full` do Linux; HFS+ realmente cheio e interrupções por SIGKILL passaram no Mac. Repetições dos mesmos grupos não foram somadas como casos novos.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo Python | 268 aprovados · 74,062 s | 268 aprovados · 74,056 s |
| Integrações Python | 46 aprovadas · 50,320 s | 46 aprovadas · 49,618 s |
| Scripts | 86 aprovados + 1 skip · 15,753 s | 86 aprovados + 1 skip · 18,657 s |
| Fases nativas | 37 × três, nenhuma falha | 37 × três, nenhuma falha |
| Gate de capturas/AX | 32 PNGs + cinco relatórios AX aprovados | 32 PNGs + cinco relatórios AX aprovados |
| Vision estrito | Dois checks aprovados | Dois checks reprovados, razões preservadas |
| Modelo Apple | `unavailable`, sem geração | `unavailable`, sem geração |

Os gates das capturas passaram nos dois sistemas, e os arquivos foram recebidos normalmente. Isso comprova os critérios automáticos aplicados; não equivale a uma sessão humana com VoiceOver. As imagens não foram incorporadas a esta pasta de evidência. Os [oito relatórios/logs originais](evidencias/73c9863/README.md), com tamanho, hashes e IDs dos artefatos, conservam um smoke completo de 37 grupos e Vision/IA/benchmark de cada sistema. A contagem de três smokes vem dos logs completos dos jobs identificados no manifesto.

O benchmark aprovou seis operações, com aquecimento e três amostras em Apple M1 Virtual, três CPUs e 7 GiB. O corpus tem 100 páginas; contraste/OCR usam só a primeira. As quatro chamadas OCR usaram Vision no26 e Tesseract no27, com a causa do fallback registrada. Ambos os relatórios de IA contêm cinco itens `unavailable`/`modelAttempted=false` por `deviceNotEligible`; a etapa produz um relatório válido, sem aprovar geração que não ocorreu. M4 físico, energia, uso do Neural Engine e serviços/dispositivos externos continuam fora desta evidência.

**A matriz global reprovou na montagem do pacote portátil.** No macOS 26, a lista pública Mozilla continha comentários UTF-8, mas a validação decodificava o arquivo inteiro como ASCII (`UnicodeDecodeError`). No27, o arquivo Java `gettext/share/gettext/javaversion.class` compartilha a assinatura inicial `CAFEBABE` com um contêiner Mach-O; o classificador de quatro bytes o enviou ao `lipo -verify_arch arm64`, que terminou com SIGSEGV. As etapas de isolamento sem dependências/rede e de instalação/atualização do binário **não foram executadas**. O aplicativo instalado por fontes não foi apresentado como distribuição portátil validada.

As correções posteriores validam cada bloco PEM individualmente sem alterar comentários/bytes originais e distinguem estruturalmente contêineres Mach-O de arquivos Java, mantendo as verificações obrigatórias de arquitetura, carregamento e assinatura. Elas precisam de nova execução; a aprovação funcional desta rodada não aprova essas alterações nem o pacote resultante.

## cbb3298 — relatórios originais recuperados; empacotamento interrompido pelo otool

A execução [40109285584](https://github.com/vibracall-beep/PDF-/actions/runs/40109285584), tentativa 1, commit `cbb32987409a3911de29650e79a83840b670bdd7`, terminou **reprovada nos dois sistemas somente na etapa Assemble relocatable binary distribution**. Compilação, instalação/ativação por fontes, verificações nativas e gates de relatórios anteriores passaram. Inicialmente a API permitia confirmar os estados, mas o download dos artefatos estava bloqueado. A [retenção 40113693926](https://github.com/vibracall-beep/PDF-/actions/runs/40113693926), no rascunho privado de release `422859507`, permitiu recuperar os dez ZIPs originais de artefatos e o ZIP completo de logs, com hashes conferidos. O sucesso da retenção não altera a reprovação do produto.

Os [oito originais preservados](evidencias/cbb3298/README.md) contêm um smoke e os JSONs de Vision, IA e benchmark de cada sistema. O manifesto registra também os hashes dos ZIPs e os logs completos que sustentam três smokes por sistema. Cada job aprovou **411 casos Python distintos: 410 executados e aprovados, um skip**, além dos **37 grupos nativos em três execuções**.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo | 268 aprovados · 74,409 s | 268 aprovados · 71,871 s |
| Integrações | 46 aprovadas · 67,864 s | 46 aprovadas · 40,273 s |
| Scripts | 96 aprovados + 1 skip · 17,227 s | 96 aprovados + 1 skip · 16,108 s |
| Fases nativas | 37 × três, nenhuma falha | 37 × três, nenhuma falha |

O skip depende de `/dev/full` do Linux; os ensaios reais HFS+ cheio e SIGKILL passaram. Os gates de 32 PNGs/cinco relatórios AX passaram por sistema, e os arquivos foram recuperados; a revisão visual individual das 64 capturas ainda estava pendente neste registro. Não se presume aprovação visual pela aprovação do gate automatizado.

Os JSONs originais mostram dois checks Vision aprovados no26 e dois reprovados no27. O benchmark completou seis operações, com OCR Vision no26 e Tesseract no27 nas quatro chamadas de cada sistema. Apple Intelligence permaneceu indisponível (`deviceNotEligible`), com cinco itens `unavailable`/`modelAttempted=false` por sistema, sem geração avaliada. O hardware é Apple M1 Virtual, três CPUs e 7 GiB. Os PDFs sintéticos de 100 páginas têm SHA distintos; não há comparação controlada com entrada idêntica nem medição de M4 físico, energia/NPU ou VoiceOver humano.

A falha de empacotamento ocorreu em `otool -l` sobre o executável `Chromium Helper (GPU)`: o argumento completo foi passado corretamente, mas `otool-classic` registrou tentativa de abrir o nome truncado `Chromium Helper `, `No such file or directory`, e encerrou com status 1. Os passos seguintes de isolamento do pacote e instalação/atualização binária foram ignorados. As correções posteriores de empacotamento, preservação de páginas/links e edição de tags de acessibilidade precisam de nova matriz; os resultados históricos de `cbb3298` não as aprovam.
