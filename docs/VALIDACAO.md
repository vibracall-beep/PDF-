# Evidências de validação

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

As duas imagens de 1050 × 772 pixels foram baixadas e abertas para inspeção: [menu principal](imagens/menu-principal.png) e [leitor](imagens/leitor.png). Foram conferidos barra lateral, rótulos, busca, categorias, três colunas de cartões, favoritos, controles do leitor, miniaturas e texto do PDF de exemplo. Os arquivos preservam os bytes do artefato original, sem montagem ou retoque. As capturas anteriores por cache de NSView apresentavam áreas vazias e foram substituídas; não eram evidência adequada da aparência real.

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
