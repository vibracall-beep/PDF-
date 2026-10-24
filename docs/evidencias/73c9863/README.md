# Evidências de 73c9863 — aprovação funcional parcial, pacote reprovado

Originais da [execução 40106710898](https://github.com/vibracall-beep/PDF-/actions/runs/40106710898), commit `73c98630e50e4b978f0bebeeb7965613c2d4536f`, baixados dos artefatos do GitHub Actions e copiados **sem alteração de bytes**. O [manifesto de procedência](provenance.json) identifica artefatos, digest do ZIP informado pelo GitHub, tamanho/SHA-256 de cada arquivo e os logs usados para a apuração. As contagens derivadas não são novos relatórios emitidos pelo aplicativo.

Cada diretório preserva o último smoke instalado (`PDF-native-checks.log`) e os três JSONs originais de Vision, IA e benchmark. O log preservado contém uma execução de 37 grupos; os logs completos dos jobs comprovam **três execuções de cada grupo**. Cada sistema aprovou 268 testes de núcleo, 46 integrações e 86 testes de scripts, com um caso ignorado por depender de `/dev/full` do Linux: **401 casos distintos, 400 aprovados e um skip**. HFS+ real e SIGKILL passaram. Os gates de 32 PNGs/cinco relatórios AX passaram em cada sistema; esses arquivos visuais não integram esta pasta.

| Conjunto | macOS 26.6.2 | macOS 27.0.1 |
|---|---:|---:|
| Núcleo | 268 aprovados · 74,062 s | 268 aprovados · 74,056 s |
| Integrações | 46 aprovadas · 50,320 s | 46 aprovadas · 49,618 s |
| Scripts | 86 aprovados + 1 skip · 15,753 s | 86 aprovados + 1 skip · 18,657 s |
| Smoke nativo | 37 grupos × três, todos aprovados | 37 grupos × três, todos aprovados |
| Vision estrito | Dois checks aprovados | Dois checks reprovados, erros preservados |
| OCR no benchmark | Vision no aquecimento e nas três amostras | Tesseract no aquecimento e nas três amostras |
| Modelo Apple | Indisponível; nenhuma geração | Indisponível; nenhuma geração |

O ensaio de IA registrou `deviceNotEligible` nos dois ambientes, com cinco itens `unavailable` e `modelAttempted=false`. Isso não aprova qualidade de respostas. O benchmark executou seis operações em Apple M1 Virtual, três CPUs/7 GiB, corpus sintético de 100 páginas; OCR e contraste usam só a primeira página. Não mede M4 físico, energia, ocupação da NPU ou interação humana com VoiceOver.

**A matriz global reprovou no empacotamento.** No26, descrições UTF-8 fora dos blocos PEM foram rejeitadas por uma decodificação ASCII da lista pública de certificados. No27, o cabeçalho compartilhado `CAFEBABE` fez um arquivo Java `javaversion.class` ser enviado ao `lipo` como Mach-O, provocando SIGSEGV. As etapas seguintes de isolamento do pacote e instalação/atualização binária foram ignoradas. Nenhum destes relatórios aprova um pacote portátil ou correções posteriores.

O [histórico de validação](../../HISTORICO-VALIDACAO.md) conserva o contexto; o [estado de entrega](../../VALIDACAO.md) separa aprovação de funcionalidades e distribuição.
