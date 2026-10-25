# Evidência da primeira rodada 0.7 — reprovada

A execução [40221525855, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40221525855), fonte **`887d82453e08621084635f31434c15ef4b4c76f4`**, terminou em **falha** nos dois sistemas em 25/10/2026. A única etapa com conclusão `failure` em cada job foi **Validate all native previews and accessibility reports**. Compilação, instalação e ensaios do pacote passaram, mas não sobrepõem esse bloqueio. Estes dados não aprovam um instalador 0.7 nem alterações posteriores.

Os [metadados da execução](collector-run.json), [jobs e etapas](collector-jobs.json), [artefatos](collector-artifacts.json) e [logs originais completos](collector-attempt-1-logs.zip) foram obtidos pela coleta autenticada do repositório. O ZIP de logs tem **938.076 bytes**, SHA-256 **`0890c6125cd706f8e4ab772e2f1bce927fd50393c6a845c0b753490089378b22`**. A [proveniência](provenance.json) registra tamanho, hash e origem de cada arquivo retido. Os arquivos de artefatos foram conferidos contra o membro ZIP, o digest do GitHub e o [estado da coleta](collector-artifact-state.json), preservando seus bytes.

## Resultados observados

| Controle | macOS 26.6.2 — `macos-26` | macOS 27.0.1 — `xcode-27` | Alcance |
|---|---|---|---|
| Scripts Python | 138 métodos: 137 aprovados, um ignorado; 27,830 s | 138 métodos: 137 aprovados, um ignorado; 22,449 s | O teste ignorado exige `/dev/full` do Linux. |
| Núcleo Python | 364 aprovados; 109,186 s | 364 aprovados; 107,947 s | Resultados do commit indicado. |
| Integrações Python | 57 aprovados; 59,558 s | 57 aprovados; 60,035 s | Incluem dependências reais instaladas no runner. |
| Total Python por sistema | 559 métodos: **558 aprovados e um ignorado** | 559 métodos: **558 aprovados e um ignorado** | Repetir um método em outro ambiente não cria outro método. |
| Grupos nativos | 42 grupos, nove execuções: 378 aprovações de grupo | 42 grupos, nove execuções: 378 aprovações de grupo | Não são 378 grupos distintos nem métodos Python. |
| Compilar, instalar, smoke tests, isolar pacote, instalar/atualizar binário | Etapas aprovadas | Etapas aprovadas | Não aprovam os gates que falharam nem o uso no Mac físico do usuário. |
| Capturas e relatórios AX | **Gate reprovado** | **Gate reprovado** | As duas falhas de interface abaixo permanecem como evidência. |
| Apple Vision estrito | Reconhecimento da amostra aprovado | Reconhecimento falhou | O OCR de compatibilidade com Tesseract não é aprovação do Vision. |
| Foundation Models local | Indisponível: `deviceNotEligible` | Indisponível: `deviceNotEligible` | Nenhuma geração real aprovada pelo modelo. |
| M4 físico, energia e Neural Engine | Não medidos | Não medidos | Os relatórios identificam Apple M1 virtual e GPU paravirtual. |

A [revisão de contagens dos logs](collector-log-review.json) é um resultado derivado, separado dos originais. O teste ignorado é `test_real_enospc_after_backup_restores_old_bundle`; o ambiente macOS não fornece o dispositivo Linux usado nesse cenário. Isso não deve ser apresentado como teste aprovado.

## Falhas preservadas e reprodução

- **Menus:** os identificadores `pdf.menus.quick-title` e `pdf.menus.quick-add` não apareceram como exigido; controles herdaram `pdf.customization.menus` e surgiram sem nome acessível. A causa no código foi a propagação do identificador aplicado ao contêiner raiz. O relatório e o checker registram sete ocorrências de falha por sistema; algumas são verificações diferentes da mesma causa.
- **Corrigir acessibilidade:** o seletor `pdf.accessibility.group.role` não expôs nome acessível. O checker registra quatro ocorrências por sistema, incluindo a inspeção da árvore e do cliente AX público. A correção acrescenta o label explícito.
- **Demais cinco relatórios AX:** passaram nos checks automatizados dessa rodada, mantendo controles para revisão humana. Isso não comprova experiência VoiceOver, contraste ou ordem semântica de PDFs.

Os logs originais do gate estão em [macOS 26](macos-26/preview-gate-original.log) e [macOS 27](xcode-27/preview-gate-original.log). Foram retidos os sete JSONs AX de cada sistema e os checkers exatos de `887d824`, sem substituir os originais pelos arquivos corrigidos da árvore de trabalho. A reprodução local dos JSONs com esse checker confirmou cinco relatórios sem falhas, quatro ocorrências no relatório de acessibilidade e sete no de Menus, com **saída 1 em ambos**: [reprodução 26](macos-26/ax-replay.log), [reprodução 27](xcode-27/ax-replay.log).

Executada na raiz do repositório, a conferência abaixo deve continuar falhando para essa evidência histórica:

```sh
python docs/evidencias/887d824/checker-887d824/check_accessibility_report.py docs/evidencias/887d824/macos-26/*.accessibility.json
python docs/evidencias/887d824/checker-887d824/check_accessibility_report.py docs/evidencias/887d824/xcode-27/*.accessibility.json
```

O checker completo de capturas também foi preservado em [checker-887d824/check_preview_artifacts.py](checker-887d824/check_preview_artifacts.py). Os PNGs e pacotes binários não fazem parte deste subconjunto retido; portanto, a reprodução local acima confere os JSONs AX e não repete a validação completa de imagens. Nenhuma imagem gerada foi usada como evidência.

## Limites que continuam explícitos

Os relatórios de Vision de [macOS 26](macos-26/PDF-vision-audit.json) e [macOS 27](xcode-27/PDF-vision-audit.json) registram resultados diferentes. Os relatórios de IA de [macOS 26](macos-26/PDF-local-ai.json) e [macOS 27](xcode-27/PDF-local-ai.json) preservam indisponibilidade e `modelAttempted: false`; não contêm respostas substitutas tratadas como geração aprovada.

Os benchmarks de [macOS 26](macos-26/PDF-benchmark.json) e [macOS 27](xcode-27/PDF-benchmark.json) medem as operações disponíveis no ambiente virtual, com o backend OCR efetivamente usado. Os arquivos sintéticos possuem hashes diferentes entre sistemas; esses resultados não constituem comparação controlada de desempenho. Não medem energia ou ocupação da GPU/Neural Engine e não estabelecem vantagem em M4 físico.

Correções de AX, rascunhos, editor, conversões e outras ampliações posteriores exigem novo commit e nova execução. A entrega histórica 0.6 continua separada. A [auditoria 0.7](../../AUDITORIA-0.7.md) acompanha o estado atual sem reclassificar esta rodada reprovada como aprovada.
