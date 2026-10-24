# Evidências de 4ac9d26 — captura/AX e empacotamento reprovados

Originais da [execução 40114980785](https://github.com/vibracall-beep/PDF-/actions/runs/40114980785), tentativa 1, commit `4ac9d264473fd5440df4d67bfa6cf2e702d8d3bf`. **Os dois jobs terminaram reprovados.** Os testes Python e os grupos nativos passaram, mas isso não sobrepõe as falhas de captura/acessibilidade e assinatura do framework Python.

Esta pasta preserva **11 arquivos sem alterar bytes**: os dois logs completos dos jobs, os dois últimos logs de smoke, seis JSONs originais de Vision/IA/benchmark e o relatório AX reprovado do macOS 26. O [manifesto](provenance.json) registra origem, tamanho, SHA-256 e IDs/digests dos nove ZIPs de artefatos baixados pela API padrão. Cada artefato foi vinculado à execução e ao SHA de origem antes da leitura. Não foram preservadas URLs temporárias assinadas.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo Python | 281 aprovados · 77,252 s | 281 aprovados · 69,602 s |
| Integrações Python | 46 aprovadas · 68,648 s | 46 aprovadas · 39,903 s |
| Scripts | 100 aprovados + 1 skip · 26,817 s | 100 aprovados + 1 skip · 19,297 s |
| Smoke nativo | 38 grupos × três, todos aprovados | 38 grupos × três, todos aprovados |
| Captura | 32 PNGs/seis AX gerados | Timeout de 300 s; nenhum PNG/AX gerado |
| Gate de captura/AX | Reprovado: Scope sem nome acessível | Sem conjunto para validar |
| Vision estrito | Dois checks aprovados | Dois checks reprovados, erros preservados |
| OCR no benchmark | Vision: aquecimento + três amostras | Tesseract: aquecimento + três amostras |
| Modelo Apple | Indisponível, nenhuma geração | Indisponível, nenhuma geração |
| Montagem portátil | Codesign de Python.framework reprovado | Codesign de Python.framework reprovado |

São **428 casos Python distintos por sistema: 427 aprovados e um skip**. O caso ignorado exige `/dev/full` do Linux. HFS+ realmente cheio, SIGKILL e a nova regressão macOS de relocação/execução de Mach-O com nomes entre parênteses passaram. Os testes focais de acessibilidade e produção pertencem ao núcleo; reexecuções não são somadas como casos novos.

A contagem de **38 grupos × três = 114 aprovações por sistema** usa exclusivamente os dois logs completos de topo, preservados em `jobs/`. O último smoke de cada artefato contém apenas uma dessas execuções. As entradas parciais de etapas e o snapshot inicial incompleto da API de passos não foram usados para contagens. Na consulta posterior de 24/10/2026, às 17:54:23 UTC, a API já mostrava os 26 passos completos de cada job, ambos `failure`; os endpoints da execução, da tentativa e de cada job concordaram. A inconsistência da coleta anterior não é um bloqueio atual. O ZIP de logs regenerado pelo GitHub tem 485.990 bytes e SHA-256 `56ff863ae28d7f1497e491a439f473967fec9d3ef63b4bee1fd7159c59e2e478`; o manifesto identifica também os hashes independentes dos dois logs completos. Variação de entradas parciais numa nova geração do ZIP não é uma nova tentativa de CI.

No macOS 26, a tela de acessibilidade foi capturada após inspeção real e preenchimento da tag TH. O controle `pdf.accessibility.tag.scope` ficou sem nome nos dois canais de inspeção: dois nós e quatro falhas do checker. Os cinco outros relatórios AX passaram. O layout legível da imagem não corrige essa falha assistiva. O responsável de interface abriu individualmente os 32 PNGs: não encontrou nova sobreposição/corte de controles fixos, conferiu o rodapé por aba e os cinco valores/ações do TH. O root também inspecionou início, personalização e TH. Essa revisão visual não aprova o AX reprovado, o pacote ou os rótulos do candidato posterior. As imagens não integram esta pasta.

No macOS 27, a captura excedeu 300 segundos antes do primeiro arquivo e terminou com status 124. A tentativa de coletar a stack do processo também expirou; não há diagnóstico conclusivo da causa da inicialização nem aprovação visual. Não foi produzido artefato de preview desse sistema.

A montagem avançou além do erro anterior de `otool`, mas os dois jobs pararam em `codesign` de `runtime/vendor/python@3.12/Frameworks/Python.framework`, status 1: `bundle format unrecognized, invalid, or unsuitable`. Os passos posteriores de isolamento sem dependências/rede e instalação/atualização do binário não foram executados. Ajustes locais dos rótulos AX e links do framework, e novos diagnósticos de inicialização, dependem de outra matriz; esta rodada não os aprova.

O benchmark executou seis operações, com aquecimento e três amostras, em Apple M1 Virtual, três CPUs e 7 GiB. Os documentos sintéticos têm 100 páginas; contraste/OCR usam só a primeira e os hashes de entrada diferem entre sistemas. Os dois relatórios de IA registram cinco itens `unavailable`, `modelAttempted=false`, por `deviceNotEligible`. Não houve geração avaliada, medição de M4 físico, energia/NPU ou ensaio humano com VoiceOver.

Os [originais de cbb3298](../cbb3298/README.md), com 64 capturas revisadas, permanecem históricos. O [estado de entrega](../../VALIDACAO.md) e o [histórico](../../HISTORICO-VALIDACAO.md) distinguem resultados de cada revisão.

A rodada posterior [0bd707d](../0bd707d/README.md) concluiu as capturas/AX e a montagem/assinatura nos dois sistemas, mas reprovou no isolamento do Office. Este registro permanece vinculado exclusivamente a `4ac9d26`; a galeria e seus limites não mudam retroativamente.
