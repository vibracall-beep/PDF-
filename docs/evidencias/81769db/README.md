# Evidência nativa de 81769db — matriz aprovada

A execução [40229486932, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40229486932), fonte **`81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5`**, terminou com **sucesso nos dois sistemas** em 25/10/2026, às 21:06:32 UTC. Compilação, instalação, interface automatizada, isolamento e instalação/atualização dos respectivos pacotes passaram. **O teste do mesmo pacote entre sistemas e a entrega privada permanecem etapas separadas**, não aprovadas por esta evidência.

Os originais de [run](run.json), [jobs](jobs.json) e [artefatos](artifacts.json) confirmam fonte, tentativa e conclusão. O [ZIP oficial completo dos logs](attempt-1-logs.zip) tem **984.613 bytes**, SHA-256 **`209e64bc59e68172c36c99dca617df68eeab75da306c3b7b2f838531beb9387a`**. Foi obtido pelo endpoint autenticado da tentativa; o GitHub não fornece digest independente nesse endpoint, portanto o hash identifica os bytes recebidos, cujos CRCs/membros foram verificados. Os arquivos de artefatos têm conferência separada com os digests da API.

[provenance.json](provenance.json) associa os arquivos retidos a fonte, artefato, ZIP/membro e SHA-256. O [estado final da coleta](artifact-state.json), a [verificação dos binários](binary-downloads.json) e os [metadados derivados dos pacotes](binary-metadata.json) preservam o vínculo. Os snapshots parciais em `progress/` permanecem intactos. **Os PNGs, tars/binários e manifestos completos de aproximadamente 12 MB não foram duplicados neste subconjunto do Git**; a origem, hashes, tamanhos e totais derivados estão registrados, e os originais permanecem nos arquivos autenticados da coleta e nos artefatos; a retenção privada da entrega ainda é uma etapa posterior.

## Contagens finais dos logs completos

| Suíte | macOS 26.6.2 | macOS 27.0.1 | Interpretação |
|---|---|---|---|
| Scripts | 143 métodos: 142 aprovados, um ignorado; 25,722 s | 143 métodos: 142 aprovados, um ignorado; 28,856 s | O único skip exige `/dev/full` do Linux. |
| Núcleo | 510 aprovados; 134,929 s | 510 aprovados; 141,137 s | Mesma fonte do aplicativo. |
| Integrações | 60 aprovados; 107,709 s | 60 aprovados; 129,129 s | Dependências reais no runner. |
| Total Python por sistema | **713 métodos: 712 aprovados e um ignorado** | **713 métodos: 712 aprovados e um ignorado** | Rodadas locais, reexecuções e subtestes não são somados. |
| Auditorias nativas | **43 grupos distintos**, nove execuções cada | **43 grupos distintos**, nove execuções cada | 387 aprovações de grupo por Mac; não são 387 grupos distintos. |

As [contagens do coletor](counts-complete-logs.json) e a [recontagem independente](suite-recheck.json) identificam os membros originais. Em cada log houve **387 inícios e 387 aprovações**, com multiconjuntos de nomes iguais; a ordem pode variar. As nove execuções ocorreram em duas verificações do instalador de fontes, uma do app instalado, uma no isolamento portátil e cinco durante instalação/atualização do binário.

O teste ignorado é `test_real_enospc_after_backup_restores_old_bundle`; não é contado como aprovado. Os 35 métodos focais de ocultação e os controles focais do editor já integram o núcleo, sem acréscimo artificial ao total. Os [logs do app instalado 26](macos-26/PDF-native-checks.log) e [27](xcode-27/PDF-native-checks.log) cobrem uma execução retida de 43 grupos cada; o total de nove vem dos logs completos, não da repetição desses arquivos.

A [classificação dos logs](log-review.md), com [referências estruturadas](log-review.json), preserva avisos e controles negativos. O PDFKit bruto registrou falhas diagnósticas antes das saídas corrigidas: nove no 26 e 27 no 27; as saídas tratadas passaram. Avisos CoreGraphics, retorno de drop não usado, API diagnóstica obsoleta e probe de ajuda do processador App Intents não foram apagados. Não houve marcador de falha nativa ou etapa fatal; a verificação final dos metadados App Intents passou.

## Pacotes nativos e próximo teste

Os relatórios originais de [macOS 26](macos-26/distribution-validation.json) e [macOS 27](xcode-27/distribution-validation.json) registram app 0.7.0, isolamento, instalação inicial, atualização, preservação da preferência de controle, recusa de checksum incorreto e metadados App Intents verificados. A aprovação corresponde ao pacote de cada sistema no próprio job.

| Pacote | Artefato | Bytes do tar | SHA-256 do tar |
|---|---:|---:|---|
| macOS 26 | 12613568897 | 1.448.948.424 | `71528d864bb9425516fe877318a734855ee0c74c818f021d53b13eca790297f5` |
| macOS 27 | 12613123845 | 1.446.966.449 | `bcb86b4019180bd54934070a40e91b29bc2397b48e13343ef13df18c3db7d3b5` |

O instalador retido nos dois artefatos tem **9.062 bytes**, SHA-256 **`3c0943ea52e1de018a140d51208d6829dd91317381dedf90ccce8da66ccad2a5`**, e foi comparado byte a byte ao arquivo do commit. A verificação em streaming dos ZIPs/tars está no registro do coletor; os pequenos membros de validação, checksum e instalador foram comparados novamente com os membros dos ZIPs.

O manifesto macOS 26 mede **12.263.013 bytes**, SHA-256 `540201d729049e850d0a51e80232e020d1a16dcd5c20483356cd295e14860ebb`, com bundle de **3.489.762.935 bytes lógicos**. A fórmula autenticada do preflight exige **10.068.713.145 bytes**, exibidos como **9.603 MiB livres após a cópia interna do tar**. Considerando também essa cópia e margem, a recomendação operacional é 15 GB livres além do download. Os [totais e cálculo por sistema](binary-metadata.json) distinguem ocupação lógica, estimativa e tamanho comprimido; o preflight não reserva blocos nem depende de clones APFS.

O tar macOS 26 foi usado em [40234132628](https://github.com/vibracall-beep/PDF-/actions/runs/40234132628), sem recompilação, com controlador `0c3aad82d319a8985ebc8b7c6fb868d5f91c5f0e` e produto `81769db`. Esse teste posterior **falhou na captura após 300 segundos, sem janela nem PNG**, apesar da instalação e operações nativas anteriores aprovadas. A [retenção própria da falha cruzada](../cross-81769db-failed/README.md) preserva os originais. **A aprovação nativa específica deste conjunto não aprova o teste cruzado ou a entrega privada 0.7, que permanece bloqueada.**

## Interface e revisão visual

Os dois jobs passaram no gate de **33 PNGs e sete relatórios AX** cada. Os originais do gate estão em [26](macos-26/preview-gate-original.log) e [27](xcode-27/preview-gate-original.log). A reprodução dos 14 JSONs retidos com o [checker exato do commit](checker-81769db/check_accessibility_report.py) passou: [replay 26](macos-26/ax-replay.log), [replay 27](xcode-27/ax-replay.log). A validação completa dos artefatos extraídos está em [26](macos-26/preview-artifact-validation.log) e [27](xcode-27/preview-artifact-validation.log), incluindo os pares OCR e seus hashes.

A [revisão visual do macOS 26](visual-review/macos-26.md), com [notas/hashes individuais](visual-review/macos-26.json), abriu os 33 PNGs originais. A [revisão do macOS 27](visual-review/macos-27.md), com [notas/hashes individuais](visual-review/macos-27.json), fez o mesmo. Não houve bloqueador confirmado nas regiões exibidas. São **66 PNGs distintos**; a [inspeção adicional de três imagens](visual-review/root-macos-26.json) reutiliza esse conjunto e não aumenta o total.

São inspeções estáticas por agentes, não ensaios humanos com VoiceOver. Controles inferiores exigem rolagem e as barras do leitor têm transbordamento horizontal; as imagens não comprovam todos os percursos por teclado/arraste. A amostra OCR em português usa o idioma Inglês, sem demonstrar qualidade geral de OCR em português. Animações, interação com dispositivos/serviços e fluxos não capturados continuam fora desse alcance.

## Capacidades e limites

A [síntese derivada](capability-summary.json) referencia os artefatos originais. Vision estrito [passou na amostra 26](macos-26/PDF-vision-audit.json) e [falhou no runner 27](xcode-27/PDF-vision-audit.json); no 27 o OCR funcional identificou Tesseract. Os relatórios de IA de [26](macos-26/PDF-local-ai.json) e [27](xcode-27/PDF-local-ai.json) registram `deviceNotEligible`, cinco casos e zero tentativas de geração por sistema. Não há aprovação de geração real ou qualidade linguística.

Os benchmarks de [26](macos-26/PDF-benchmark.json) e [27](xcode-27/PDF-benchmark.json) identificam M1 virtual e GPU paravirtual. Não medem M4 físico, energia ou ocupação do Neural Engine. Padrões, VoiceOver humano, produção de assinaturas e dispositivos externos conservam os limites da [matriz por ferramenta](../../MATRIZ-0.7.md).

A coleta teve HTTP 401 temporário, resolvido antes da retenção; isso não é resultado de teste do aplicativo. Logs e demais originais conservam seus bytes, inclusive whitespace. Verificação de estilo dos documentos exclui payloads originais de log; integridade destes é conferida pelos hashes. As falhas [887d824](../887d824/README.md) e [6c8be0e](../6c8be0e/README.md), as rodadas locais e a entrega 0.6 permanecem identificadas separadamente.
