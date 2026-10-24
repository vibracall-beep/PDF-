# Auditoria 437a8f4 — matriz e instalação aprovadas

A [matriz 40137438618, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40137438618), fonte [`437a8f4d6bb6ebb003859f769e3756fce30c9da3`](https://github.com/vibracall-beep/PDF-/commit/437a8f4d6bb6ebb003859f769e3756fce30c9da3), **concluiu com sucesso nos dois sistemas**. Passaram compilação, instalação por fontes, validação portátil isolada, primeira instalação binária, atualização, checksum incorreto, preservação de preferências e isolamento após instalação.

Cada binário foi validado no sistema que o produziu. A execução do **mesmo tar do macOS 26 no macOS 27** exige o gate cruzado separado; este registro não o substitui. A assinatura é ad hoc, sem notarização Apple.

## Resultados contados nos logs completos

Cada sistema teve **491 métodos Python distintos: 490 executados e aprovados, um skip**. Reexecuções e subcasos não foram somados como métodos novos.

| Suíte | macOS 26 | SDK/macOS 27 |
| --- | --- | --- |
| Núcleo | 313 PASS · 122,269 s | 313 PASS · 109,412 s |
| Integrações reais | 50 PASS · 79,863 s | 50 PASS · 83,232 s |
| Scripts | 128 métodos: 127 PASS/1 skip · 26,213 s | 128 métodos: 127 PASS/1 skip · 20,577 s |
| Nativo por fontes | 41 grupos × 3 execuções PASS | 41 grupos × 3 execuções PASS |
| Nativo portátil antes do pacote | 41 grupos × 1 execução PASS | 41 grupos × 1 execução PASS |
| Instalação, atualização e validação final | 41 grupos × 5 execuções PASS | 41 grupos × 5 execuções PASS |
| Capturas e gate AX | 32 PNGs + 6 relatórios AX PASS | 32 PNGs + 6 relatórios AX PASS |
| Primeira instalação / atualização | PASS / PASS | PASS / PASS |
| Checksum incorreto / preferências | Recusado / preservadas | Recusado / preservadas |

O único skip foi o teste de ENOSPC com `/dev/full`, exclusivo de Linux. **As nove execuções nativas somam 369 grupos aprovados por sistema, zero falhas**; ficam separadas dos 491 métodos Python. Na fase binária, cada instalação valida o aplicativo preparado e o destino publicado, e há uma validação isolada final: cinco execuções adicionais, não cinco suítes diferentes.

As duas regressões da extração do tar passaram nos dois Macs: preservação de modos/links/executável e detecção da perda histórica sob `umask 077`, incluindo alteração posterior dos modos. Ao contrário da [rodada 352ae6f](../352ae6f/README.md), esta execução alcançou e aprovou a instalação nova, a segunda instalação transacional, a recusa do checksum falso e a preferência sentinela.

## Imagens e OCR

As **64 imagens originais foram abertas individualmente**: [macOS 26](visual-review-macos26-all32.json) e [SDK/macOS 27](visual-review-macos27.json). O título **“Palavras reconhecidas”** aparece inteiro, com margem superior e painel próprio de rolagem. O editor conserva os controles visíveis e a Biblioteca mostra **“1 versão”**. Não foi encontrado outro corte bloqueante nos estados capturados. A [galeria desta fonte](../../imagens/437a8f4/README.md) contém uma seleção dos originais.

Isso não aprova ações, rolagem fora da área capturada, redimensionamento, animações ou uso humano com VoiceOver. O gate automatizado e a revisão visual têm escopos distintos.

As análises derivadas dos originais OCR — [26](ocr-macos-26.json) e [27](ocr-xcode-27.json) — confirmam uma página raster de 1130 × 1600, sem texto selecionável, e 60 palavras com IDs únicos, hashes correspondentes, confiança finita e caixas dentro da página. **Inglês / Página automática** corresponde a `eng`/PSM 3, 200 DPI, confiança mínima zero e deskew desativado. Erros reais no português, como `informag6es` e `retne`, permanecem expostos para revisão. Confiança alta não comprova transcrição correta, e reamostragem a 200 DPI não acrescenta detalhe ao raster original.

## Capacidades e limites medidos

Vision estrito passou no macOS 26. No 27, suas duas verificações falharam; o OCR do produto passou usando **Tesseract local**, identificado nos registros de aquecimento e nas três amostras do benchmark. Essa compatibilidade não foi rotulada como aprovação do Vision.

Os dois relatórios de Apple Intelligence registraram **`unavailable` / `deviceNotEligible`**, sem execução do modelo ou aprovação da qualidade de geração. Os benchmarks cobriram seis operações numa fixture de 100 páginas, com aquecimento e três amostras, em Apple M1 virtual (arm64), três núcleos disponíveis e 7 GiB de memória. OCR e contraste abrangem somente a primeira página. Os sistemas registraram macOS 26.6.2 (25G83) e macOS 27.0.1 (26A434); os picos de RSS do processo principal foram 301.449.216 e 150.618.112 bytes, respectivamente. Não medem M4 físico, energia, ocupação da GPU ou uso efetivo da Neural Engine.

Scanner, Pages real, dispositivos físicos, VoiceOver humano, modelos disponíveis no Mac de destino e serviços externos com credenciais mantêm suas validações próprias; esta matriz não os declara universalmente testados.

## Pacotes autenticados

Os ZIPs foram conferidos contra digest e tamanho publicados pelo GitHub e vinculados ao run/commit acima. Os hashes abaixo foram calculados por **streaming dos membros tar originais**, sem executar o pacote, e conferidos com sidecars e logs. Os relatórios originais de [instalação26](macos-26-distribution-validation.json) e [instalação27](xcode-27-distribution-validation.json) confirmam os gates alcançados.

| Sistema | Artefato binário validado | Bytes do tar | SHA-256 do tar |
| --- | --- | --- | --- |
| macOS 26 | 12578358642 | 1,448,521,887 | `7dabd68ffcc1b65ea551efd51bb17f9194bb6d3990261f6c52e33735d96cb7ad` |
| SDK/macOS 27 | 12578502165 | 1,446,486,442 | `ff8ab80f49b20eb7754e67e99d8c5186c7d34be5ae402739b5af8c26d77d10df` |

Os arquivos de cerca de 1,4 GB e os manifestos completos não foram adicionados ao repositório. IDs, hashes, tamanhos, membros e procedência estão no [registro de coleta](provenance.json); os originais permanecem na coleta local e nos artefatos da execução enquanto durar a retenção. A aprovação deste run não equivale à publicação de uma versão nem à aprovação do gate cruzado.

## Originais preservados

- [ZIP oficial dos logs da tentativa](attempt-1-logs.zip): 886,935 bytes, SHA-256 `590164ffd2c14af2182f83a8be2724b002628124be813a7b96af0f9ba9e78b97`.
- Logs nativos originais: [26](macos-26-native-checks.log) e [27](xcode-27-native-checks.log).
- Vision: [26](macos-26-vision.json) e [27](xcode-27-vision.json).
- IA local: [26](macos-26-local-ai.json) e [27](xcode-27-local-ai.json).
- Benchmarks: [26](macos-26-benchmark.json) e [27](xcode-27-benchmark.json).
- [Contagens derivadas por linha](final-counts.json), dois relatórios de instalação originais acima e [procedência completa](provenance.json).

Todos os 14 ZIPs de artefatos foram obtidos pela API normal do GitHub e verificados. Os dois logs completos recebidos por job são byte a byte iguais aos membros de topo do ZIP oficial; cópias parciais das etapas não foram somadas. **Onze arquivos originais** foram preservados sem reformatar ou redigir. Os cinco relatórios locais de contagem/OCR/revisão visual estão identificados como derivados.

A triagem de 71 entradas de texto encontrou zero ocorrências dos padrões selecionados de tokens, URLs temporárias assinadas, valores de autorização e chaves privadas. Os logs conservam diagnósticos de fixtures sintéticas e caminhos do runtime. A triagem por padrões não prova ausência de toda forma possível de segredo.
