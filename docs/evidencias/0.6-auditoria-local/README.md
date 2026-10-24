# Evidências locais da auditoria 0.6

Código: **`7205dd106c07002ec1c5ed8fd2ebbef448cf9f3a`**, commit local ainda não enviado ao GitHub. O [manifesto SHA-256 dos fontes](source-sha256.json) identifica 162 arquivos de implementação, testes, dependências e workflows. Alterações documentais posteriores não mudam esse código. O [relatório estruturado](validation.json) conserva ambiente, comandos, contagens e limites.

| Conjunto | Resultado | Duração | Registro |
|---|---:|---:|---|
| Núcleo Python | 268 aprovados | 36,888 s | [core.log](core.log) |
| Integrações reais | 45 aprovadas | 94,387 s | [integration.log](integration.log) |
| Scripts | 75 aprovados, um ignorado | 3,006 s | [scripts.log](scripts.log) |
| Total distinto | **388 aprovados, um ignorado — 389 casos** | — | Não inclui repetição dos mesmos casos nos ensaios focados |

O caso ignorado requer um volume HFS+ real no macOS; não é aprovação. Os avisos de revogação no núcleo pertencem a casos com busca de rede proibida, e os asserts correspondentes passaram. A integração usa conversores/OCR/veraPDF reais, com Chromium em `/usr/bin/chromium`; o motor Apple não está disponível no Linux.

Também passaram: parser dos 70 arquivos Swift, sintaxe de oito scripts Bash, leitura dos três workflows e checagem de referências sequenciais de etapas, e `git diff --check`. O catálogo contém 71 IDs únicos e conserva todos os 54 IDs históricos; o leitor fica fora dessa contagem. **Sintaxe Swift não é compilação nem execução macOS.**

## Gate nativo pendente

A integração GitHub respondeu `401 — Bad credentials`. A revisão atual não foi compilada nos SDKs Apple e não possui aprovação do instalador portátil, novas capturas, App Intents ou execução nativa dos novos bloqueios/recuperação. A aprovação do antigo commit `5a11c07` não é reutilizada. Os testes de falha do atualizador que passaram no Mac em uma rodada intermediária têm escopo identificado na [matriz das ampliações](../../AMPLIACOES-2026-10.md).

Não foram medidos M4 físico, energia ou Neural Engine. Não houve interação humana com VoiceOver, avaliação factual do modelo Apple instalado ou entrega externa de solicitações de assinatura. O pacote de fontes não é um aplicativo compilado e estes resultados não autorizam chamá-lo de instalador final aprovado.
