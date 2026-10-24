# Evidências de validação

## Revisão 0.6 — aplicação por fontes aprovada nos dois sistemas; pacote portátil pendente

A implementação ampliada **ainda não está aprovada para instalação final**. A [matriz das 17 ampliações](AMPLIACOES-2026-10.md) identifica cada caminho, teste e limite. As 54 ferramentas anteriores foram preservadas e o catálogo passou a 71 entradas, além do leitor. O acesso ao GitHub foi restabelecido; o HTTP 401 anterior não é um bloqueio ativo.

| Código / execução | Resultado observado |
|---|---|
| `fcac3db` / [40101134318](https://github.com/vibracall-beep/PDF-/actions/runs/40101134318) | Ambos os sistemas compilaram e passaram 268 testes de núcleo, 45 integrações e 75/76 testes de scripts; o único skip exige `/dev/full` do Linux. HFS+ cheio e SIGKILL passaram. Primeiro smoke: 35/37 grupos aprovados, com falhas em perfis e automação. Instalação não ativada |
| `fcac3db` / [40101147782](https://github.com/vibracall-beep/PDF-/actions/runs/40101147782) | Diagnóstico SDK aprovado no 26 e no 27: extração real e verificação completa dos metadados App Intents. [Originais, hashes e procedência](evidencias/fcac3db-sdk/README.md) |
| `d0fda92` / [40103086558](https://github.com/vibracall-beep/PDF-/actions/runs/40103086558) | No macOS 26: compilação, instalação por fontes, 389 casos Python (388 aprovados/um skip), 37 grupos nativos × três execuções, 32 PNGs/cinco AX e seis operações de benchmark aprovados. As 32 capturas foram revisadas. A matriz **reprovou**: mac27 parou na desmontagem HFS+ do teste; mac26 recusou dependência CA externa durante o empacotamento portátil |
| `766fe59` / [40105444603](https://github.com/vibracall-beep/PDF-/actions/runs/40105444603) | Ambos pararam **antes de compilar**: 81 testes de scripts, 79 aprovados, um skip e uma falha por comparar `/var` com `/private/var` no teste CA. HFS+ real passou nos dois. O teste de aliases foi corrigido; a rodada seguinte consta abaixo |
| `73c9863` / [40106710898](https://github.com/vibracall-beep/PDF-/actions/runs/40106710898) | Ambos aprovaram compilação, instalação por fontes, 401 casos Python (400 aprovados/um skip), 37 grupos nativos × três, 32 PNGs/cinco AX e seis operações de benchmark. As 64 capturas foram revisadas. A matriz **reprovou no empacotamento**: comentários UTF-8 na lista CA26 e arquivo Java confundido com Mach-O27 |
| `cbb3298` / [40109285584](https://github.com/vibracall-beep/PDF-/actions/runs/40109285584) | **Concluída com falha somente em Assemble nos dois sistemas**, segundo a API. Integridade, compilação, instalação, smoke, preview/AX, relatórios Vision/IA e benchmark constam como sucesso. Logs e conteúdo dos artefatos estão bloqueados para download; diagnóstico e revisão visual pendentes. Nenhum novo tempo/total de testes foi inferido desses status |

No `73c9863`, cada sistema aprovou **268 testes de núcleo, 46 integrações e 86 testes de scripts**, com um caso Linux ignorado. Tempos de núcleo/integrações/scripts: **74,062 / 50,320 / 15,753 s no26** e **74,056 / 49,618 / 18,657 s no27**. HFS+ real e SIGKILL passaram. Os 37 grupos nativos passaram antes da ativação, depois dela e na verificação final do aplicativo instalado. Recuperação real, biblioteca, perfis, automação, entradas App Intents, contratos de edição/OCR, proteção Unicode e permissões fazem parte dessas fases. Os [oito relatórios/logs originais e a procedência](evidencias/73c9863/README.md) foram preservados; repetir casos em três execuções ou outro sistema não cria casos distintos.

Vision passou os dois checks no26 e reprovou os dois no27; o OCR funcional manteve o fallback Tesseract identificado. No benchmark, aquecimento e três amostras usaram Vision no26 e Tesseract no27. O ensaio de IA registrou **`unavailable` / `deviceNotEligible` em ambos**: nenhum dos cinco casos executou geração. O benchmark mediu seis operações em **Apple M1 Virtual**, com corpus sintético de 100 páginas; OCR e contraste usam só a primeira. Isso não mede M4 físico, energia ou ocupação do Neural Engine. Os gates das 64 capturas/dez relatórios AX passaram, e as 64 imagens foram revisadas; isso não substitui uso humano com VoiceOver.

A falha de perfis combinava uma expectativa antiga de primeiro cartão com uma restauração que não mudava a ordem; a revisão também corrigiu a gravação da normalização validada. A automação registrou `legacyCount=1`, `rawLookup=false`, `canonicalLookup=true`, `rootHasAlias=true`, confirmando o alias da pasta no acesso pela chave. Os testes corrigidos conservam as verificações de filtragem, identidade e persistência. A revisão visual de `73c9863` confirmou os rótulos corrigidos após `d0fda92`; a galeria continua histórica enquanto aguarda acesso e revisão das capturas de `cbb3298`, com ajuste do rodapé. Detalhes e tempos anteriores ficam no [histórico](HISTORICO-VALIDACAO.md).

O empacotador seleciona a lista pública Mozilla, sem copiar certificados privados/Keychains do host. `cbb3298` corrige as duas falhas observadas em `73c9863`: valida blocos PEM preservando comentários UTF-8 e distingue contêineres Mach-O de arquivos Java antes de acionar ferramentas Apple. As verificações de arquitetura/carregamento/assinatura continuam obrigatórias. **Ainda não houve aprovação da distribuição portátil em isolamento, instalação nova, segunda atualização ou compatibilidade do mesmo binário entre sistemas.** Os gates permanecem obrigatórios. A rodada `cbb3298` terminou reprovada na montagem, mas sua causa ainda não foi confirmada pelos logs inacessíveis. Os 97 testes de scripts locais tiveram 96 aprovações e um skip HFS+ exclusivo de Mac (2,948 s); essa contagem não é atribuída ao CI sem acesso ao log.

O download dos logs e artefatos de `cbb3298` retornou `Forbidden` no host de armazenamento `productionresultssa14.blob.core.windows.net`, inclusive na nova tentativa após autorização de rede. IDs e digests dos artefatos estão disponíveis, mas não substituem seus bytes. Sucesso das etapas de relatório Vision/IA não permite inferir capacidade Vision, disponibilidade do modelo ou qualidade de geração sem examinar os relatórios. Nenhuma captura de `cbb3298` foi declarada revisada. Um workflow de retenção privada está sendo preparado; ainda não foi executado.

A auditoria Linux consolidada anterior, do código `7205dd106c07002ec1c5ed8fd2ebbef448cf9f3a`, continua preservada: 268 testes de núcleo (36,888 s), 45 integrações (94,387 s), 76 de scripts (75 aprovados/um HFS+ exclusivo de macOS ignorado, 3,006 s). São **389 casos distintos, 388 executados e aprovados, um ignorado**. [Logs, ambiente, comandos e manifesto SHA-256](evidencias/0.6-auditoria-local/README.md) identificam esse snapshot, sem aprovar alterações posteriores. O parser dos 70 fontes Swift, as verificações Bash/YAML e a comparação dos 71 IDs foram checks estáticos separados.

Certificados/TSA/serviço de assinaturas de produção, Pages, scanner/Continuidade, dois Macs físicos e modelo Apple instalado ainda precisam dos componentes correspondentes. As matrizes aprovam amostras e cenários declarados; não demonstram fidelidade universal nem ausência de erros.

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

A recuperação tem testes de gerações, corrupção, gravação, cancelamento e restauração em nova sessão. A ampliação passou a interromper um processo real por SIGKILL depois de um checkpoint completo e a restaurar seu documento protegido; esse grupo passou nos dois sistemas em `73c9863`. Isso não cobre interrupção em cada instrução de uma escrita incompleta. Interrupções abruptas também podem deixar locks/estágios do instalador, conforme [INSTALACAO.md](INSTALACAO.md).

A instalação por fontes usa runtime específico do Mac. A distribuição autocontida 0.6 está implementada, mas ainda sem aprovação completa de isolamento, instalação e atualização. Ambos os caminhos usam assinatura ad hoc, sem notarização Apple. Nenhuma suíte demonstra ausência universal de erros ou superioridade sobre todos os concorrentes.
