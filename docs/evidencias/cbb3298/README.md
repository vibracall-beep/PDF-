# Evidências de cbb3298 — aplicação por fontes aprovada, pacote reprovado

Originais da [execução 40109285584](https://github.com/vibracall-beep/PDF-/actions/runs/40109285584), tentativa 1, commit `cbb32987409a3911de29650e79a83840b670bdd7`. Os oito arquivos desta pasta foram copiados **sem alterar bytes** dos artefatos originais. O [manifesto de procedência](provenance.json) registra seus tamanhos/SHA-256, os dez ZIPs de artefatos e seus digests do GitHub, e o ZIP completo de logs da tentativa.

O acesso inicial aos artefatos ficou bloqueado no host de armazenamento. A [retenção 40113693926](https://github.com/vibracall-beep/PDF-/actions/runs/40113693926) preservou os originais no rascunho privado de release `422859507`, permitindo o download e a conferência independente. Essa retenção não executa nem aprova o produto. O resultado da matriz de origem permanece **failure**; não existe pacote portátil aprovado nesta evidência.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo Python | 268 aprovados · 74,409 s | 268 aprovados · 71,871 s |
| Integrações Python | 46 aprovadas · 67,864 s | 46 aprovadas · 40,273 s |
| Scripts | 96 aprovados + 1 skip · 17,227 s | 96 aprovados + 1 skip · 16,108 s |
| Smoke nativo | 37 grupos × três, todos aprovados | 37 grupos × três, todos aprovados |
| Gate de capturas/AX | 32 PNGs + cinco relatórios aprovados | 32 PNGs + cinco relatórios aprovados |
| Vision estrito | Dois checks aprovados | Dois checks reprovados, erros preservados |
| OCR no benchmark | Vision: aquecimento + três amostras | Tesseract: aquecimento + três amostras |
| Modelo Apple | Indisponível; nenhuma geração | Indisponível; nenhuma geração |

São **411 casos Python distintos por sistema: 410 aprovados e um skip**. O caso ignorado exige `/dev/full` do Linux; os ensaios reais de HFS+ cheio e interrupção por SIGKILL passaram no Mac. O `PDF-native-checks.log` preservado em cada diretório contém um smoke de 37 grupos; os três smokes são comprovados pelos logs completos dos jobs identificados no manifesto. As contagens derivadas não são novos relatórios emitidos pelo aplicativo.

Os 64 PNGs e dez relatórios AX foram recuperados; não integram esta pasta. A revisão visual individual dessas capturas ainda estava pendente neste registro. Um gate AX automatizado não substitui uma sessão humana com VoiceOver.

O ensaio de IA registrou `deviceNotEligible` nos dois sistemas, com cinco itens `unavailable` e `modelAttempted=false`. Não houve avaliação de qualidade de geração. O benchmark completou seis operações, aquecimento e três amostras em Apple M1 Virtual, três CPUs e 7 GiB, usando PDFs sintéticos de 100 páginas. OCR e contraste usam só a primeira página. Os SHA-256 dos PDFs diferem entre os sistemas; os tempos não constituem comparação controlada com entrada idêntica. Não foram medidos M4 físico, energia ou utilização do Neural Engine.

**A montagem portátil falhou nos dois sistemas.** `otool -l` recebeu o caminho completo do executável `Chromium Helper (GPU)`, mas `otool-classic` tentou abrir o nome truncado `Chromium Helper ` e retornou `No such file or directory`, status 1. A inspeção de dependências foi interrompida. Os passos de isolamento sem dependências/rede e de instalação/atualização do binário não foram executados. Nenhum relatório desta pasta aprova correções posteriores a `cbb3298`.

O [histórico](../../HISTORICO-VALIDACAO.md) preserva as rodadas anteriores; o [estado de entrega](../../VALIDACAO.md) distingue validação do aplicativo e da distribuição.
