# Evidência nativa de 6c8be0e — bloqueio antes da compilação

A execução [40228648128, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40228648128), fonte **`6c8be0e740826064e363515fa5aa86f57eccb1ee`**, terminou em **falha nos dois sistemas**. Criada em 25/10/2026 às 19:59:49 UTC, foi concluída às 20:00:41 UTC. A etapa **Verify installer integrity** bloqueou a compilação. Os resultados Python consolidados no Linux permanecem na [retenção local](../local-6c8be0e/README.md), com alcance distinto.

Os JSONs originais de [run](run.json) e [jobs](jobs.json) vieram da API autenticada do GitHub. Os logs abaixo conservam os bytes da coleta autenticada, incluindo checkout, nome do job, testes, falhas e skips. [provenance.json](provenance.json) liga fonte, execução, IDs, URLs, tamanhos e SHA-256.

| Sistema/job | Scripts executados | Tempo | Log original / SHA-256 |
|---|---|---:|---|
| macOS 27 · `121275450621` | 143 métodos: **140 aprovados, dois falharam, um ignorado** | 24,608 s | [xcode-27.log](xcode-27.log), 71.095 bytes · `ed18e8522e90ca89659c6af936c8e57a5e4cee707f82cc909895d0892af187a1` |
| macOS 26 · `121275450755` | 143 métodos: **140 aprovados, dois falharam, um ignorado** | 28,317 s | [macos-26.log](macos-26.log), 71.184 bytes · `fe5196fdebd16aa7c5d21bf0cc597beeff80b05dd86fcdcc400e4a8b7deced35` |

O teste ignorado exige o `/dev/full` do Linux. As etapas de compilação, instalação, smoke tests, capturas, Vision, IA, benchmark, isolamento e produção/instalação do pacote constam como **skipped**. Não há aprovação dessas etapas para esta fonte e execução.

## Causa confirmada

O preflight novo chamou **`/usr/bin/plutil -lint storage-manifest.json`** diretamente sobre JSON válido. Nesse percurso nativo o `plutil` rejeitou o primeiro `{`, com **`Unexpected character { at line 1`**, antes de consultar o espaço livre.

Dois testes reais expuseram a mesma causa em ambos os sistemas:

- `test_actual_native_preflight_accepts_valid_legacy_and_rejects_invalid_metadata`, linha 71: o caso válido esperava saída 0 e recebeu 1.
- `test_actual_native_preflight_refuses_real_low_space_without_changing_existing_app`, linha 127: o volume de baixo espaço deveria produzir “Espaço insuficiente”, mas foi bloqueado antes pela leitura incorreta do manifesto.

O [instalador histórico](source-6c8be0e/install-binary.sh) e os [testes históricos](source-6c8be0e/test_binary_space.py) foram preservados do commit exato. Esses arquivos não são o instalador corrigido e não devem ser usados como entrega.

## Encaminhamento, ainda sem aprovação do produto

O candidato posterior [`81769db`](../local-81769db/README.md), em validação na [execução 40229486932](https://github.com/vibracall-beep/PDF-/actions/runs/40229486932), prepara uma cópia privada em **plist XML**, usando `plutil -convert xml1`, antes de `lint`, consulta de tipos e extração; também valida `schema == 1` antes do ramo legado. Os testes locais e a sintaxe shell passaram na árvore corrigida. Na nova execução, a API já informou Verify installer integrity aprovada nos dois jobs, que avançaram à compilação; o restante continua em andamento. Isso não reclassifica os dois testes que falharam aqui e não constitui aprovação de um novo instalador.

A [auditoria 0.7](../../AUDITORIA-0.7.md) acompanha a correção. O histórico da rodada [887d824](../887d824/README.md), reprovada por AX, e a entrega 0.6 permanecem separados. Nenhum resultado é transferido entre fontes.
