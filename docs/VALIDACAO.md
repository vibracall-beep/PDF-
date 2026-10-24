# Evidências de validação

## Revisão 0.6 — validação em andamento; pacote final ainda não aprovado

A implementação ampliada **ainda não está aprovada para instalação final**. A [matriz das 17 ampliações](AMPLIACOES-2026-10.md) identifica cada caminho, teste e limite. As 54 ferramentas anteriores foram preservadas e o catálogo passou a 71 entradas, além do leitor. O acesso ao GitHub foi restabelecido; o HTTP 401 anterior não é um bloqueio ativo.

| Código / execução | Resultado observado |
|---|---|
| `fcac3db` / [40101134318](https://github.com/vibracall-beep/PDF-/actions/runs/40101134318) | Ambos os sistemas compilaram e passaram 268 testes de núcleo, 45 integrações e 75/76 testes de scripts; o único skip exige `/dev/full` do Linux. HFS+ cheio e SIGKILL passaram. Primeiro smoke: 35/37 grupos aprovados, com falhas em perfis e automação. Instalação não ativada |
| `fcac3db` / [40101147782](https://github.com/vibracall-beep/PDF-/actions/runs/40101147782) | Diagnóstico SDK aprovado no 26 e no 27: extração real e verificação completa dos metadados App Intents. [Originais, hashes e procedência](evidencias/fcac3db-sdk/README.md) |
| `d0fda92` / [40103086558](https://github.com/vibracall-beep/PDF-/actions/runs/40103086558) | No macOS 26: compilação, instalação por fontes, 389 casos Python (388 aprovados/um skip), 37 grupos nativos × três execuções, 32 PNGs/cinco AX e seis operações de benchmark aprovados. As 32 capturas foram revisadas. A matriz **reprovou**: mac27 parou na desmontagem HFS+ do teste; mac26 recusou dependência CA externa durante o empacotamento portátil |
| `766fe59` / [40105444603](https://github.com/vibracall-beep/PDF-/actions/runs/40105444603) | Ambos pararam **antes de compilar**: 81 testes de scripts, 79 aprovados, um skip e uma falha por comparar `/var` com `/private/var` no teste CA. HFS+ real passou nos dois. O teste de aliases foi corrigido; a rodada seguinte consta abaixo |
| `73c9863` / [40106710898](https://github.com/vibracall-beep/PDF-/actions/runs/40106710898) | Ambos aprovaram compilação, instalação por fontes, 401 casos Python (400 aprovados/um skip), 37 grupos nativos × três, 32 PNGs/cinco AX e seis operações de benchmark. As 64 capturas foram revisadas. A matriz **reprovou no empacotamento**: comentários UTF-8 na lista CA26 e arquivo Java confundido com Mach-O27 |
| `cbb3298` / [40109285584](https://github.com/vibracall-beep/PDF-/actions/runs/40109285584) | Logs e artefatos recuperados: 411 casos Python (410 aprovados/um skip), 37 grupos nativos × três, 32 PNGs/cinco AX e seis operações de benchmark por sistema. As 64 capturas foram revisadas sem nova regressão visual. **Falha de montagem em ambos:** `otool-classic` truncou o nome `Chromium Helper (GPU)` |
| `4ac9d26` / [40114980785](https://github.com/vibracall-beep/PDF-/actions/runs/40114980785) | **Reprovada em ambos.** 428 casos Python (427 aprovados/um skip) e 38 grupos nativos × três aprovados por sistema. No macOS 26, 32 PNGs/seis AX gerados, mas Scope sem nome reprova o gate; no macOS 27, timeout de captura sem primeiro PNG. Ambos falham no codesign de Python.framework 3.12 |
| `0bd707d` / [40118132309](https://github.com/vibracall-beep/PDF-/actions/runs/40118132309) | **Reprovada no isolamento do Office em ambos.** 434 casos Python (433 aprovados/um skip), 38 grupos nativos × três, 32 PNGs/seis AX e montagem/assinatura aprovados. `soffice` retorna 1 sem detalhe; instalação/atualização posteriores do binário não executadas |
| `75d5012` / [40121275705](https://github.com/vibracall-beep/PDF-/actions/runs/40121275705) | **Reprovada no isolamento do Office em ambos.** 436 casos Python (435 aprovados/um skip), 39 grupos nativos × três, 32 PNGs/seis AX e montagem/assinatura aprovados. Captura escura26 corrigida; ressalva de precisão/idioma do OCR visual permanece |
| `f9958a3` / [40123759689](https://github.com/vibracall-beep/PDF-/actions/runs/40123759689) | **Reprovada na compilação em ambos.** Novos closures precisam de captura explícita de `self`; chamadas `Darwin.sigaction` foram resolvidas como inicializador do struct. Correções posteriores ainda dependem de nova matriz |
| `360dae6` / [40124180933](https://github.com/vibracall-beep/PDF-/actions/runs/40124180933) | **Compilação corrigida; primeiro smoke reprovado em ambos.** 454 casos Python (453 aprovados/um skip). Foram observados 18 grupos nativos aprovados e 16 reprovados; sete checks dependentes não foram alcançados. A preparação de descritores do novo owner falhou, afetando qpdf e seus consumidores. Nenhum smoke posterior ou instalação ativada |
| `ecae663` / [40125423021](https://github.com/vibracall-beep/PDF-/actions/runs/40125423021) | **Testes aprovados; matriz reprovada nos dois sistemas.** 460 casos Python aprovados/um skip e 41 grupos nativos × três. Captura expirou antes da WindowGroup, sem arquivos. Montagem/assinatura passou; controle de processos Java falhou com `EPERM` no isolamento, antes de Office |
| `a0a3c0c` / [40129073067](https://github.com/vibracall-beep/PDF-/actions/runs/40129073067) | **Compilação reprovada nos dois sistemas:** constante Core Foundation renomeada pelo SDK. Scripts: 119 aprovados/um skip por Mac, incluindo helper C real com quatro controles. Aplicativo/capturas/portátil não executados. [Original](evidencias/a0a3c0c/README.md) |
| `6200205` / [40129433128](https://github.com/vibracall-beep/PDF-/actions/runs/40129433128) | **Compilação aprovada; validação por fontes interrompida no núcleo Python.** Os testes expuseram um launcher de teste incompatível com espaços no caminho do Python e uma comparação lexical entre aliases `/var` e `/private/var`. Smokes, capturas e pacote portátil não foram alcançados. [Originais e contagens](evidencias/6200205/README.md) |
| `e9af24a` / [40130449411](https://github.com/vibracall-beep/PDF-/actions/runs/40130449411) | **Fontes aprovadas; matriz reprovada.** 479 métodos Python aprovados/um skip e 41 grupos nativos × três por Mac. Montagem e runtime isolado passaram; smoke portátil: 27 grupos aprovados/11 reprovados em caminhos protegidos, três dependentes não alcançados. Captura26: 32 PNGs/seis AX; captura27: timeout após lançamento, zero arquivos. [Originais](evidencias/e9af24a/README.md) |

Em **`e9af24a`**, as fixtures de espaços/aliases e os novos contratos de perfis, encerramento e cópias Pages passaram na matriz por fontes. O runtime portátil também executou Java/veraPDF, Office, Chromium, qpdf, Ghostscript e OCR sob isolamento. Os controles de comunicação privada e os três workers passaram; a falha posterior preservou o namespace por falta de prova de cleanup transitivo. **A validação completa ainda reprovou:** os caminhos nativos protegidos receberam qpdf status 2 nos dois sistemas, enquanto documentos sem senha passaram. No macOS 27, os traces mostram corpo/delegate e fila principal ativos, terminando em `application did finish launching`, sem WindowGroup observada. O [diagnóstico posterior de qpdf](evidencias/qpdf-crypto-55eab2e/README.md) confirmou a descoberta do provider OpenSSL como causa da falha criptográfica e aprovou os controles da correção isolada nos dois sistemas. Isso ainda precisa passar no pacote completo. O diagnóstico da janela continua; não se atribui o timeout ao mesmo ponto da inicialização anterior. [Resultados, tempos e limites](evidencias/e9af24a/README.md).

O [diagnóstico de inicialização `64036d3`](evidencias/startup-64036d3/README.md) observou quatro aberturas com janela real visível e fila principal responsiva, duas por sistema. A falha anterior não foi reproduzida; nenhuma correção causal foi demonstrada. O ensaio pausou a captura depois da associação da janela e não aprovou PNGs/AX ou o produto. A próxima matriz mantém a captura completa e acrescenta esses registros de estado, sem mudar política de ativação, prazos ou critérios de aprovação.

Em **`ecae663`**, [40125423021](https://github.com/vibracall-beep/PDF-/actions/runs/40125423021), os dois sistemas aprovaram **461 casos Python: 460 aprovados e um skip**, e **41 grupos nativos × três = 123 aprovações** por sistema. Isso confirma a correção anterior de descritores e os contratos OCR do snapshot. A captura expirou nos dois após `PDFApp init end; mainThread=true`, antes de qualquer janela observada: **zero PNGs, AX, PDFs ou JSONs de revisão OCR**. O amostrador também expirou. A montagem/assinatura passou; o isolamento falhou ao sinalizar um grupo Java/veraPDF com `EPERM`, antes de alcançar Office. Instalação/atualização binária não foram executadas. [Nove originais, tempos e procedência](evidencias/ecae663/README.md).

Esse resultado de `ecae663` é histórico. As correções seguintes passaram os contratos por fontes em `e9af24a`, e o helper sem privilégios permitiu executar o runtime Java/Office completo. As fixtures de espaços e aliases também passaram, preservando as provas de cancelamento, identidade, hashes e partes. Isso não elimina as novas reprovações do smoke portátil nem da janela no macOS 27 registradas acima.

### Rodada visual histórica 75d5012

Em `75d5012`, cada sistema aprovou **281 testes de núcleo, 46 integrações e 108 testes de scripts**, com um skip Linux: **436 casos distintos, 435 aprovados e um skip**. Tempos de núcleo/integrações/scripts: **78,149 / 59,547 / 19,120 s no macOS 26** e **70,670 / 43,401 / 19,753 s no macOS 27**. Os **39 grupos nativos passaram três vezes**, totalizando 117 aprovações por sistema. A contagem usa os dois logs completos de topo, conferidos contra o ZIP retido. [Treze originais e procedência](evidencias/75d5012/README.md).

Os 32 PNGs e seis relatórios AX por sistema passaram o gate no CI e novamente após download/extração segura. Os 64 originais foram revisados individualmente, sem novo corte ou sobreposição dos controles fixos. A imagem escura26 agora está nítida em 1050 × 772, com geometria confirmada antes da captura. **A tela de revisão OCR conserva uma ressalva:** palavras incorretas e resultado `eng` enquanto o seletor mostra Português + inglês; o snapshot carrega `eng`. Essa imagem não aprova precisão nem concordância de configuração. AX e revisão visual não substituem VoiceOver humano. Cada galeria publicada permanece vinculada ao seu commit de origem.

**Montagem e assinatura do pacote passaram nos dois sistemas.** A etapa **Validate portable app without host dependencies or network** reprovou com `RuntimeError: soffice falhou (1):`, sem detalhe capturado. O log principal não estabelece a causa. Isolamento completo, instalação/atualização subsequentes do binário e compatibilidade de um mesmo pacote entre sistemas continuam sem aprovação. Diagnósticos isolados e correções posteriores não mudam esse resultado.

Os JSONs originais registram Vision aprovado nos dois checks no macOS 26 e reprovado nos dois no macOS 27; OCR funcional e benchmark deste último usaram Tesseract identificado. A IA registrou **`unavailable` / `deviceNotEligible` em ambos**, com cinco itens sem tentativa de geração. O benchmark executou seis operações, aquecimento e três amostras em **Apple M1 Virtual**, três CPUs e 7 GiB. As amostras sintéticas têm 100 páginas, mas OCR/contraste usam somente a primeira; os SHA diferem entre sistemas. Não é comparação controlada de desempenho. M4 físico, energia, ocupação de NPU e modelo Apple instalado permanecem sem comprovação.

A [retenção privada 40123290389](https://github.com/vibracall-beep/PDF-/actions/runs/40123290389), release `422923712`, recuperou manifesto, dez ZIPs originais e ZIP de logs. IDs, commit, digests e tamanhos foram conferidos. O sucesso da retenção não transforma o `failure` da matriz em aprovação. As falhas e evidências anteriores permanecem no [histórico](HISTORICO-VALIDACAO.md).

A sequência de correções conserva seus resultados: `f9958a3` falhou na compilação; `360dae6` compilou, mas reprovou na preparação de descritores, com 18 grupos aprovados/16 reprovados no primeiro smoke. A correção de `/dev/null` em `ecae663` passou os 41 grupos em três smokes por sistema. Ela não resolveu a inicialização da WindowGroup nem a inspeção/sinalização no sandbox. Os fixes de encerramento/perfis posteriores ainda não foram executados nesses resultados.

A auditoria Linux consolidada anterior, do código `7205dd106c07002ec1c5ed8fd2ebbef448cf9f3a`, continua preservada: 268 testes de núcleo (36,888 s), 45 integrações (94,387 s), 76 de scripts (75 aprovados/um HFS+ exclusivo de macOS ignorado, 3,006 s). São **389 casos distintos, 388 executados e aprovados, um ignorado**. [Logs, ambiente, comandos e manifesto SHA-256](evidencias/0.6-auditoria-local/README.md) identificam esse snapshot, sem aprovar alterações posteriores. O parser dos 70 fontes Swift, as verificações Bash/YAML e a comparação dos 71 IDs foram checks estáticos separados.

Certificados/TSA/serviço de assinaturas de produção, Pages, scanner/Continuidade, dois Macs físicos e modelo Apple instalado ainda precisam dos componentes correspondentes. As matrizes aprovam amostras e cenários declarados; não demonstram fidelidade universal nem ausência de erros.

## Diagnóstico separado da comunicação Office

A [execução diagnóstica 40123784563](https://github.com/vibracall-beep/PDF-/actions/runs/40123784563), fonte `f9958a3`, confirmou nos dois sistemas a sequência bloqueio → permissão ao socket Unix exato → bloqueio, usando os mesmos bytes de entrada, executável, perfil e argumentos. A conversão produziu texto verificável somente com a permissão; o socket previsto foi observado enquanto o processo estava ativo. Controles nativos trocaram bytes pelo socket permitido e receberam `EPERM` ao tentar bind em TCP, UDP e Unix fora da exceção. Esse ensaio identifica a causa e verifica uma permissão delimitada; não aprova o runtime completo, o navegador, o OCR, a instalação ou uma mudança de isolamento ainda não promovida.

A rodada diagnóstica seguinte, [40125812418](https://github.com/vibracall-beep/PDF-/actions/runs/40125812418), fonte `c2ecff7`, aprovou também o namespace Unix privado para Office, multiprocessing Python e Chromium completo em ambos os sistemas, preservando recusas `EPERM` em TCP/UDP/Unix externo/escape por symlink. O headless-shell já passava no perfil anterior; não se atribui sua funcionalidade à nova permissão. O runtime focal foi movido, manteve os hashes e teve a assinatura verificada depois das operações. Os [logs oficiais e relatórios extraídos](evidencias/private-ipc-c2ecff7/README.md) conservam origem e SHA-256. **Não é aprovação do pacote PDF completo:** a promoção ao perfil de produção e a instalação/atualização ainda precisam passar.

O [diagnóstico 40128200878](https://github.com/vibracall-beep/PDF-/actions/runs/40128200878), fonte `6bb7d0f`, distinguiu a recusa de inspeção do estado real do grupo nos dois Macs. `/bin/ps` é setuid e sua execução dentro do sandbox retornou `EPERM`; fora funcionou. Grupos contendo apenas o líder zumbi retornaram `EPERM` aos sinais também fora do sandbox. Grupos com descendente vivo foram identificados como vivos pelas duas APIs e encerrados pelos sinais antes da coleta do líder. Oito controles e consultas externas conferiram; [originais e limites](evidencias/process-6bb7d0f/README.md). Isso fundamenta o helper de consulta, sem aprovar Java, Office ou o pacote completo.

## Base histórica 0.5 aprovada — escopo separado

As dez melhorias estão implementadas no código **`5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`**. A execução [40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837) terminou **aprovada nos dois ambientes Apple Silicon**: macOS 26.6.2 e 27.0.1. A instalação, ativação e as três execuções nativas passaram em cada sistema. A auditoria separada do framework Apple Vision mantém sua falha no runner27; o OCR funcional desse ambiente usou Tesseract local.

A documentação final e as evidências podem alterar o hash do pacote de fontes. Na entrega histórica 0.5, os arquivos de código, testes, dependências e scripts foram comparados ao commit aprovado e mantidos idênticos; o `BUILD-INFO.json` do pacote identifica sua revisão documental.

A correspondência entre requisitos, fontes e testes está em [MELHORIAS.md](MELHORIAS.md); o catálogo e a auditoria estão em [FERRAMENTAS.md](FERRAMENTAS.md) e [AUDITORIA-FERRAMENTAS.md](AUDITORIA-FERRAMENTAS.md). O [histórico](HISTORICO-VALIDACAO.md) conserva as reprovações e suas correções. Essa aprovação histórica não aprova o código 0.6 atual.

## Testes locais da base histórica

| Conjunto | Resultado Linux |
|---|---|
| Núcleo Python | 162/162 aprovados, 23,180 s |
| Integrações com dependências reais | 23/23 aprovadas, 59,077 s |
| Scripts de instalação e diagnóstico | 39/39 aprovados, 0,889 s |
| Total de casos Python distintos | **224 aprovados** |
| Sintaxe Swift | 41 arquivos; compilação real também aprovada nos dois SDKs Apple |

Logs locais: `/tmp/pdf-ocr-full-core.log`, `/tmp/pdf-ocr-full-integration.log` e `/tmp/pdf-native-final-scripts.log`. Incluem certificados temporários reais/PAdES, veraPDF, tabelas raster, formatos Office, lotes, proteção de originais, publicação sem sobrescrita, cancelamento e OCR real com Tesseract. As verificações Swift são contabilizadas separadamente; repetir o mesmo caso em outro sistema não cria um novo caso distinto.

## Matriz nativa 40055682837

| Verificação | macOS 26.6.2 / Xcode 26.6 | macOS 27.0.1 / Xcode 27.1 |
|---|---|---|
| Compilação release arm64 | Aprovada, 41 arquivos Swift | Aprovada, 41 arquivos Swift |
| Núcleo | 162/162, 29,094 s | 162/162, 36,687 s |
| Integrações reais | 23/23, 22,225 s | 23/23, 28,497 s |
| Scripts | 39/39, 1,824 s | 39/39, 1,681 s |
| Instalação e ativação | Aprovadas | Aprovadas |
| Testes nativos | 26 grupos × três execuções, nenhuma reprovação | 26 grupos × três execuções, nenhuma reprovação |
| Capturas e acessibilidade automática | 19 PNGs + quatro relatórios AX aprovados | 19 PNGs + quatro relatórios AX aprovados |
| OCR funcional | Apple Vision; Tesseract direto também aprovado | Tesseract local aprovado |
| Capacidade estrita Apple Vision | Dois testes aprovados | Dois testes reprovados, motivos preservados |
| Benchmark instalado | Seis operações aprovadas | Seis operações aprovadas |
| Pacote do CI | `PDF-source-macos-26` | `PDF-source-ocr-compatibility-xcode-27` |

Os grupos incluem serialização estrutural e semântica, credenciais Unicode, permissões originais, cancelamento, recuperação byte a byte, filas de abertura, anotações, formulários, preferências e referências da IA. A regressão de sessão monta o leitor de referência real com preferências isoladas; todos os painéis de saída usam o seletor central por revisão dos callsites. Isso não significa que todas as combinações possíveis de interação foram automatizadas.

Medianas em milissegundos, três amostras após aquecimento:

| Operação | macOS 26 | macOS 27 |
|---|---:|---:|
| Abrir | 0,152 | 0,206 |
| Extrair texto | 5,067 | 4,930 |
| Buscar | 1,104 | 1,190 |
| Renderizar | 3,826 | 6,977 |
| Contraste | 9,068 | 12,151 |
| OCR | 1.448,469 (Vision) | 2.014,244 (Tesseract após falha Vision) |

Hardware de ambos: **Apple M1 Virtual**, arm64, três CPUs, 7 GiB e Apple Paravirtual device. Pico de RSS do processo principal: 301.023.232 bytes (26) e 149.028.864 bytes (27); não inclui subprocessos. O sistema26 foi 26.6.2 (25G83), SDK26.5; o sistema27 foi 27.0.1 (26A434), SDK27.0. Os PDFs sintéticos vieram do mesmo gerador, mas cada relatório registra seu próprio hash; esta rodada não é uma comparação controlada entre processadores físicos.

Os [quatro relatórios JSON originais, hashes e metadados dos pacotes](evidencias/5a11c07/README.md) foram recebidos normalmente e preservados. Logs completos: `/tmp/pdf-5a11c07-all.log`; contagem separada dos grupos e tempos: `/tmp/pdf-5a11c07-summary.json`. As [19 capturas históricas](imagens/README.md) são originais do SDK27. Ambos os conjuntos foram baixados, validados e seus **38 estados revisados visualmente**, com procedência e hashes. Os oito relatórios AX passaram seus critérios automáticos.

Os relatórios de [2816a41](evidencias/2816a41/README.md) permanecem identificados como históricos. Não substituem os resultados atuais.

## OCR funcional e capacidade Apple

O produto prefere Apple Vision. Se o reconhecimento falhar por erro de execução classificado, inclusive no processo isolado, tenta o Tesseract local instalado. Erros de idioma, entrada inválida, protocolo, cancelamento e prazo continuam sendo falhas. A mensagem de conclusão e o benchmark identificam o mecanismo efetivamente usado; não existe retorno de texto fictício para fazer um teste passar.

O smoke obrigatório exige reconhecer texto real a partir de uma página sem camada textual, conferir geometria e metadados, além de executar o Tesseract em português e inglês. A instalação verifica esse comportamento antes e depois da ativação. O adaptador usa arquivos privados, limites de tamanho e prazo, e encerra seus subprocessos antes da limpeza.

`PDF --vision-audit CAMINHO.json` executa separadamente os dois testes estritos Apple: geração de PDF pesquisável e reconhecimento em processo isolado. Um relatório gravado corretamente pode conter resultados **failed**; o código de saída da gravação não significa aprovação do Vision. O CI verifica essa coerência, mantém o motivo da falha e identifica os pacotes que usaram OCR de compatibilidade.

Nas rodadas anteriores, macOS 27.0.1/Xcode 27.1 apresentou erro do compilador interno do Vision: `e5rt_e5_compiler_compile call failed`, código 11. Entradas normalizadas, execução CPU, APIs públicas alternativas e processo isolado não resolveram a falha naquele runner. A alternativa Tesseract preserva o OCR funcional; não corrige nem certifica o framework Apple.

## O que o CI da base histórica exigiu

- Compilação release arm64 e 39 testes dos scripts.
- 19 capturas reais da janela pelo ScreenCaptureKit e quatro relatórios AX. O cliente AX público inspeciona somente o próprio processo e complementa a inspeção da árvore nativa; identificadores obrigatórios ausentes reprovam a etapa.
- Instalação completa do runtime, núcleo e integrações, assinatura ad hoc e verificações antes/depois da ativação. Na base 0.5, o CI usou um destino novo; a restauração de uma instalação anterior era coberta pelos testes do helper. Os ensaios novos de atualização são descritos no estado 0.6 acima.
- Smoke do aplicativo instalado: PDFKit, leitura, formulários, OCR local, Core Image, recuperação criptografada, sessões, anotações/desfazer, preferências, citações semânticas e benchmark.
- Estrutura dos PDFs publicados com qpdf status 0; os bytes finais são reabertos e comparados ao estado anterior à gravação. A auditoria cobre campos, defaults, escolhas, texto, geometria, fontes, cores, traços, links e anotações. Vínculos só são corrigidos quando os dicionários completos identificam uma única duplicata. Unicode é comparado por bytes UTF-8.
- Cópias protegidas com AES-256, revisão 6, proprietário distinto e permissões verificadas. Senhas Unicode no limite de 127 bytes, recusa de restrições incompatíveis, processos interrompidos, limpeza normal e ausência de PDFs temporários desprotegidos têm casos próprios.
- Relatório independente do Vision e benchmark funcional com seis operações, três amostras e mecanismo OCR explicitado.
- Pacote de fontes com manifesto e SHA-256. Falha de qualquer requisito funcional mantém o artefato como não validado.

O benchmark usa 100 páginas sintéticas: abertura resolve primeira/última; extração e busca percorrem o documento; renderização cobre primeira, central e última; contraste e OCR medem somente a primeira página. Há aquecimento, sem limpeza de cache. O pico de RSS corresponde ao processo principal e não soma filhos. Os tempos OCR incluem tentativas e comunicação entre processos. O relatório identifica hardware, sistema e virtualização; não mede ocupação de GPU/NPU.

O qpdf recebe jobs privados por stdin. Os arquivos JSON auxiliares, incluindo credenciais e texto de anotações/formulários, são `0600` em pasta `0700`, sem corpos dos streams no relatório de reparo; **não são criptografados**. O caminho protegido nunca grava um PDF temporário sem criptografia. A limpeza é verificada na conclusão, erro, cancelamento e timeout controlados; um encerramento abrupto do aplicativo pode impedir essa limpeza. As cópias persistentes de recuperação mantêm a proteção do documento. O limite nativo é 1 GiB por PDF e 64 MiB por JSON de reparo.

A abertura protegida autentica os bytes originais pelo qpdf e associa ao `PDFDocument`, por identidade, uma prova imutável das permissões e da origem. O PDFKit recusa algumas senhas Unicode que os verificadores independentes aceitam; quando necessário, o leitor prepara uma cópia auxiliar AES-256 com credenciais ASCII aleatórias, preservando as oito permissões. O auxiliar continua cifrado e não substitui arquivo, URL ou senha originais. Uma restrição legada incompatível provoca recusa explícita, sem ampliação de acesso. A gravação protegida recusa documentos sem a prova de origem; não tenta reconstruir permissões a partir de `dataRepresentation`.

O leitor mantém a abertura direta por URL para PDFs comuns. Entradas protegidas e recuperações são processadas fora da fila da interface, com limite de 1 GiB, fila de pedidos distintos, cancelamento por tarefa e descarte de conclusões obsoletas. As verificações aguardam o trabalho real, inclusive a limpeza de tarefas canceladas. A comparação de Popup usa os flags PDF `/F` completos, pois o getter `shouldPrint` mostrou comportamento diferente após reabrir apesar de o bit e o dicionário permanecerem intactos. O reparo tipado de `/Open` só converte números 0/1 quando o Popup original comprova o booleano correspondente; a ausência desse campo significa fechado, conforme o padrão PDF. Alterações reais de estado e flags continuam sendo recusadas pela comparação final.

## Limites que permanecem explícitos

Os runners são Apple M1 virtualizados. A avaliação de **M4 ou superior físico**, consumo de energia e utilização do Neural Engine ainda exige hardware correspondente; o benchmark implementado permite produzir essa evidência, mas não a substitui.

A auditoria automática AX não executa uma sessão humana com **VoiceOver**. A validação PDF/UA verifica documentos e relata regras; não cria automaticamente tags corretas nem certifica significado, leitura falada ou ordem semântica. O código mantém `accessibility_certified=false`.

Geração de respostas pelo Foundation Models, scanner físico, Câmera de Continuidade e exportação pelo Pages dependem de modelos, dispositivos e aplicativos que não foram exercitados integralmente no runner. Embeddings disponíveis e validação de citações têm testes próprios; isso não comprova a qualidade de todas as respostas de IA.

Assinaturas são criptográficas e os testes usam certificados temporários reais. A base 0.5 verificava offline com raízes explícitas. A versão 0.6 acrescenta OCSP/CRL e PAdES LT/LTA, exercitados com PKI/HTTPS/TSA locais controlados; certificado do usuário, serviços de produção e validade jurídica precisam de avaliação própria. Conversões e OCR não prometem fidelidade perfeita em qualquer documento.

A recuperação tem testes de gerações, corrupção, gravação, cancelamento e restauração em nova sessão. A ampliação passou a interromper um processo real por SIGKILL depois de um checkpoint completo e a restaurar seu documento protegido; esse grupo passou nos dois sistemas em `cbb3298`. Isso não cobre interrupção em cada instrução de uma escrita incompleta. Interrupções abruptas também podem deixar locks/estágios do instalador, conforme [INSTALACAO.md](INSTALACAO.md).

A instalação por fontes usa runtime específico do Mac. A distribuição autocontida 0.6 está implementada, mas ainda sem aprovação completa de isolamento, instalação e atualização. Ambos os caminhos usam assinatura ad hoc, sem notarização Apple. Nenhuma suíte demonstra ausência universal de erros ou superioridade sobre todos os concorrentes.
