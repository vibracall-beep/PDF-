# Auditoria 352ae6f — instalação binária recusada

A [matriz 40134906805, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40134906805), fonte [`352ae6fa8790ee51b547c93efc88f2f5c1956ebd`](https://github.com/vibracall-beep/PDF-/commit/352ae6fa8790ee51b547c93efc88f2f5c1956ebd), **falhou nos dois sistemas na primeira instalação binária**: `O manifesto não corresponde exatamente ao pacote extraído.` A montagem, assinatura e validação do aplicativo portátil isolado haviam passado. Isso não substitui a instalação/atualização, que permanece reprovada nesta revisão.

Também foi confirmado um defeito visual: o cabeçalho **“Palavras reconhecidas”** fica cortado no topo do painel direito da revisão OCR. O gate automático de PNG/AX passou, mas não detecta esse corte. Portanto, nem o pacote nem a interface final estão aprovados por esta rodada.

## Resultados contados nos logs completos

Cada sistema teve **489 métodos Python distintos: 488 executados e aprovados, um skip**. Reexecuções e subcasos não foram somados como métodos adicionais.

| Suíte | macOS 26 | SDK/macOS 27 |
| --- | --- | --- |
| Núcleo | 313 PASS · 96,772 s | 313 PASS · 100,967 s |
| Integrações reais | 50 PASS · 55,335 s | 50 PASS · 68,059 s |
| Scripts | 126 métodos: 125 PASS/1 skip · 23,254 s | 126 métodos: 125 PASS/1 skip · 21,346 s |
| Nativo por fontes | 41 grupos × 3 execuções PASS | 41 grupos × 3 execuções PASS |
| Nativo portátil isolado | 41 grupos × 1 execução PASS | 41 grupos × 1 execução PASS |
| Capturas/gate AX | 32 PNGs + 6 relatórios AX PASS | 32 PNGs + 6 relatórios AX PASS |
| Primeira instalação binária | Recusada por divergência do manifesto | Recusada pelo mesmo motivo |

O único skip foi o teste de ENOSPC com `/dev/full`, exclusivo de Linux. Houve **164 grupos nativos aprovados e zero falhas nativas por sistema**, distribuídos nas quatro execuções acima. O qpdf e os testes de autenticação/fidelidade passaram também no runtime portátil, antes do empacotamento. Os testes de checksum errado, segunda instalação/atualização, preservação da preferência sentinela e isolamento após a instalação **não foram alcançados**.

Os benchmarks registraram seis operações, aquecimento e três amostras, num Apple M1 virtual com três núcleos disponíveis e 7 GiB de memória, usando uma fixture de 100 páginas. O Vision estrito passou no macOS 26; no 27, suas duas verificações falharam e o OCR do produto usou Tesseract local, identificado nos quatro registros de aquecimento/amostras. Os dois relatórios do modelo Apple declararam `unavailable` por `deviceNotEligible`; não houve aprovação de geração com IA. Esses dados não medem um M4 físico, energia ou uso efetivo da Neural Engine.

## Revisão das imagens e OCR

As **64 imagens originais foram abertas individualmente**. Os quatro relatórios derivados abaixo registram escopo, hashes, observações e limites. A Biblioteca apresenta **“1 versão”** nos dois contadores singulares visíveis, corrigindo o achado anterior. O corte do cabeçalho OCR continua sendo um defeito real de interface, mesmo onde um relatório o classifica como não bloqueante para os controles. Ele exige correção e nova captura antes de aprovar a interface final.

- macOS 26: [índices 00–15](visual-review-macos26-indices00-15.json) e [16–31](visual-review-macos26-indices16-31.json).
- SDK/macOS 27: [índices 00–15](visual-review-macos27-indices00-15.json) e [16–31](visual-review-macos27-indices16-31.json).
- Análise técnica dos originais OCR: [macOS 26](ocr-macos26.json) e [SDK/macOS 27](ocr-xcode27.json).

Os PDFs sintéticos de OCR têm uma página raster de 1130 × 1600, sem texto selecionável. Cada relatório contém 60 palavras; hashes da fonte/revisão, IDs únicos, confiança finita e caixas dentro da página foram conferidos. Os controles **Inglês / Página automática** correspondem a `eng`/PSM 3. Erros reais no texto português, como `informag6es` e `retne`, foram preservados; confiança alta não garante transcrição correta. Renderizar a 200 DPI reamostra a imagem e não acrescenta detalhe original.

Os PNGs e os dois arquivos OCR por sistema permanecem nos artefatos verificados; não foram alterados ou substituídos. Conteúdo fora da área visível, ações, animações e uso humano com VoiceOver não foram aprovados pela revisão estática.

## Diagnóstico posterior da divergência de instalação

Os [inventários derivados do macOS 26](installer-inventory-macos-26.json) e [SDK/macOS 27](installer-inventory-xcode-27.json) foram produzidos **depois da CI**, por leitura dos tarballs originais, sem executar o aplicativo. A conferência encontrou manifesto embutido byte a byte igual e **56.817 entradas de arquivos/links correspondentes**, incluindo hash, tamanho, modo e destino dos links; zero diferenças no arquivo distribuído. Há ainda 4.307 diretórios.

O diagnóstico identificou a aplicação da `umask 077` na extração sem preservação dos modos: 32.526 arquivos e 2.531 diretórios têm modos que seriam alterados em cada pacote. Isso distingue o conteúdo correto do tar dos modos resultantes da extração. A correção local do comando de extração e suas regressões pertencem à revisão seguinte; **estes relatórios não comprovam a correção no macOS nem transformam a instalação recusada em aprovação**.

Os tarballs são **não validados**. Seus hashes foram calculados por streaming dos ZIPs autenticados e conferidos com sidecars e logs:

| Sistema | Artefato binário | Bytes do tar | SHA-256 do tar |
| --- | --- | --- | --- |
| macOS 26 | 12578100468 | 1.448.462.815 | `40ab427db9df55f5bafb58440a10d9fc9d658d79bff6b85142da15d320b27754` |
| SDK/macOS 27 | 12578135315 | 1.446.483.882 | `71a4e693e15eeb1ddd12e59ad319a8c392a9cb17354fdd2130cf5605ab0328c7` |

Não há autorização de entrega ou aprovação de compatibilidade cruzada desses pacotes. Os tars e manifestos completos não foram copiados para o repositório; permanecem na coleta local e nos artefatos da execução enquanto durar a retenção.

## Originais e procedência

- [ZIP oficial dos logs da tentativa](attempt-1-logs.zip): 807.126 bytes, SHA-256 `e14fe98082191ebed6a511b4333998f6266803113b417481ece49455d7083830`.
- Logs nativos originais: [macOS 26](macos-26-native-checks.log) e [SDK/macOS 27](xcode-27-native-checks.log).
- Vision: [26](macos-26-vision.json) e [27](xcode-27-vision.json).
- IA local: [26](macos-26-local-ai.json) e [27](xcode-27-local-ai.json).
- Benchmarks: [26](macos-26-benchmark.json) e [27](xcode-27-benchmark.json).
- [Contagem derivada por linha dos logs completos](final-counts.json) e [procedência, hashes, IDs e limites](provenance.json).

Todos os 14 ZIPs de artefatos foram obtidos pela API normal do GitHub e conferidos contra digest, tamanho, execução e commit. Os dois logs completos obtidos por job são byte a byte iguais aos membros de topo do ZIP oficial. As contagens vieram desses logs completos, sem somar cópias parciais das etapas. Os nove arquivos originais desta pasta foram preservados sem reformatar ou redigir; relatórios locais estão identificados como **derivados**.

A triagem de 73 entradas de texto não encontrou os padrões selecionados de tokens, URLs temporárias assinadas, valores de autorização ou chaves privadas. Logs mantêm diagnósticos de fixtures sintéticas e caminhos do runtime. A triagem por padrões não garante ausência de toda forma possível de segredo.
