# Evidências de e9af24a — fontes aprovadas, distribuição portátil reprovada

A [execução 40130449411](https://github.com/vibracall-beep/PDF-/actions/runs/40130449411), tentativa 1, commit **`e9af24a1bd9babe886ec74a9d96e97feb153a2bf`**, terminou **reprovada nos dois sistemas**. Compilação, instalação por fontes, testes Python e três smokes nativos passaram. O bundle montado falhou no smoke portátil de PDFs protegidos em ambos os Macs; o macOS 27 também reprovou a captura. **O pacote não está aprovado para entrega.**

| Verificação | macOS 26 | macOS 27 |
|---|---:|---:|
| Scripts | 119 aprovados + um skip · 25,233 s | 119 aprovados + um skip · 24,399 s |
| Núcleo Python | 311 aprovados · 99,035 s | 311 aprovados · 103,765 s |
| Integrações Python | 49 aprovadas · 69,850 s | 49 aprovadas · 69,202 s |
| Smoke do aplicativo instalado por fontes | 41 grupos × três, todos aprovados | 41 grupos × três, todos aprovados |
| Captura e gate AX | 32 PNGs + seis relatórios AX aprovados pelo gate | Timeout; zero arquivos |
| Vision estrito, relatório original | Dois checks aprovados | Dois checks reprovados |
| Experimento com modelo Apple, relatório original | Indisponível | Indisponível |
| OCR no benchmark, aquecimento + três amostras | Vision nas quatro chamadas | Tesseract nas quatro chamadas |
| Montagem do bundle portátil | Aprovada | Aprovada |
| Verificações do runtime isolado anteriores ao smoke | Aprovadas | Aprovadas |
| Smoke do bundle portátil isolado | 27 grupos aprovados; 11 reprovados | 27 grupos aprovados; 11 reprovados |
| Instalação/atualização binária posterior | Não executada | Não executada |

São **480 métodos Python distintos por sistema: 479 aprovados e um skip**, exclusivo de `/dev/full` do Linux. As reexecuções de smoke não são somadas como novos testes Python. Os dois logs completos comprovam **123 resultados nativos aprovados por fontes em cada Mac**. No smoke portátil, **38 grupos foram efetivamente executados**; outros três dependem de operações que falharam e não foram alcançados. Não foram contados como aprovados nem como três novas falhas independentes.

## Falha no bundle portátil

O runtime isolado concluiu as verificações de Python/TLS, fontconfig privado, Office, Chromium, Ghostscript, qpdf, OCR e standards. Assim, esta rodada avançou além do erro de sinal de processo observado em [ecae663](../ecae663/README.md). O smoke nativo portátil seguinte, porém, continuou reprovando o produto.

As primeiras verificações estruturais de PDFs sem senha passaram com **qpdf status 0**. A primeira cópia protegida produzida pelo PDFKit recebeu **status 2**, e o serializador recusou a publicação. Os 11 grupos reprovados incluem credenciais AES/Unicode, permissões, recuperação, edição, biblioteca e recuperação após interrupção. O log também registra uma autenticação recusada na recuperação. Não houve relaxamento do requisito estrutural nem publicação de resultado considerado válido para contornar essas falhas.

Os três grupos dependentes não alcançados foram `Native serialization fidelity and encryption guards`, `Native serialization private process and cancellation` e `Published protected copy structural integrity`. **Os logs demonstram o resultado, mas não estabelecem a causa do status 2.** Diagnósticos posteriores de qpdf/criptografia e mudanças candidatas precisam de evidência própria; não são aprovados por esta execução.

## Captura: evidência diferente entre os sistemas

No macOS 26, foram recuperados e conferidos os **40 arquivos originais**: 32 PNGs, seis relatórios AX, o PDF rasterizado e o JSON da análise OCR. O verificador local confirmou novamente os 32 PNGs e seis relatórios AX. A captura escura tem **1050 × 772 pixels**. A revisão individual das **32 telas originais** foi concluída. **Correção da avaliação visual:** a segunda inspeção, durante `352ae6f`, confirmou também no original e9af24a o topo cortado do título da interface **“Palavras reconhecidas”**. A primeira revisão não identificou esse defeito de layout; os pixels e relatórios originais permanecem intactos. Foi registrado o texto incorreto **“1 versões”** em dois pontos da Biblioteca; a correção posterior não faz parte deste snapshot. Conteúdo rolável além do trecho visível, ações, animações e interação humana com VoiceOver não foram aprovados por essa inspeção.

A inspeção do PDF e do relatório OCR confirmou os hashes de origem e da revisão, uma página sem texto selecionável, uma imagem de **1130 × 1600 pixels** e 60 palavras com IDs únicos, coordenadas finitas dentro da página e confiança entre zero e um. A captura original de revisão foi aberta e comparada à imagem do PDF: os controles exibem **Inglês / Página automática**, correspondendo a `eng` e PSM 3 no JSON; as caixas visíveis acompanham os trechos da imagem. Os originais não foram corrigidos ou retocados.

O reconhecimento em inglês de texto português mantém erros reais: `informag6es` e `retne`, por exemplo. Seis palavras têm confiança abaixo de 80%, mas há divergências também acima desse valor, como `pagina.` com 96,7% e `organizagao,` com 84,1%. Confiança OCR não é garantia de correção. O processamento a 200 DPI reamostra a imagem incorporada e não cria detalhe original. A inspeção não equivale a aprovação de precisão geral, de todos os modos OCR ou de todos os trechos fora da parte visível da tela.

No macOS 27, a inicialização avançou além de `PDFApp.init`: o corpo do app e o delegate foram criados, o marcador da fila principal foi entregue e o último trace foi **`application did finish launching` às 20:53:18.109965 UTC**, com `mainThread=true` e `swiftTask=false`. Não houve fase de captura posterior. O supervisor encerrou o processo após **300 segundos**; a coleta de stack também excedeu seus 12 segundos. A etapa terminou com status **124**. O upload confirmou **zero PNGs, zero relatórios AX e nenhum PDF/JSON de OCR**. O ponto observado não identifica sozinho a causa do bloqueio.

## Originais preservados e recuperação privada

Esta pasta contém **dez originais sem alterações**: o [ZIP oficial dos logs da tentativa](actions-attempt-1-logs.zip), o [manifesto original da retenção parcial](retained-provenance.json), dois logs de smoke e seis JSONs de Vision/IA/benchmark, nas pastas [macOS 26](macos-26/) e [macOS 27](xcode-27/). O ZIP de logs tem **766.242 bytes**, SHA-256 **`2e76999cb2edec30b1967bfa8580541dc23d797563365c93ac5109f6728c70f9`**. O [manifesto derivado](provenance.json) registra origem, commit, jobs, contagens, tempos e linhas relevantes. Os dois logs completos de topo coincidiram byte a byte com os endpoints individuais de jobs; não foram duplicados descompactados no repositório. A API não fornece digest de origem para o ZIP de logs, portanto o hash identifica os bytes recebidos pelo endpoint oficial.

Após o bloqueio do download direto, a execução de retenção **40132887159** preservou o conteúdo no release privado em draft **422983201**, tag `audit-partial-e9af24a1bd9b-40130449411`, apontando para o commit original exato. Foram baixados pela API os **nove ZIPs de artefatos**, o ZIP de logs e o manifesto; IDs, tamanhos e hashes foram conferidos contra a retenção e os digests Actions antes da extração com inventário restrito. O ZIP de logs retido é byte a byte igual ao já preservado. O manifesto original tem SHA-256 **`e14b568804c0afca224c112e9a3893def166e82398d267ee3b94ff8215f5f365`**.

A retenção é explicitamente **parcial**: falta o artefato de prévia do macOS 27, porque não foi produzido. Ela não publica um aplicativo nem converte falhas em aprovação. Nenhuma URL assinada foi publicada, nenhum JSON foi reconstruído de logs e nenhum executável foi acrescentado a esta pasta. Os PNGs e os dois originais OCR foram extraídos para revisão, sem duplicar seu ZIP no repositório.

A varredura de **62 entradas textuais**, entre os logs do ZIP e os nove relatórios/manifesto acrescentados, não encontrou os padrões verificados de tokens, URLs assinadas, cabeçalhos de autorização ou chaves privadas. Nenhum trecho foi ocultado ou alterado. Essa busca por padrões não prova ausência de todo valor potencialmente sensível.

Os benchmarks originais registram seis operações, aquecimento e três amostras em Apple M1 Virtual, com três CPUs e 7 GiB. Os relatórios de IA registram cinco itens indisponíveis por sistema, `modelAttempted=false` e motivo `deviceNotEligible`. Não comprovam desempenho/energia/NPU em M4 físico, interação humana com VoiceOver, geração pelo modelo Apple, envio externo de assinaturas ou instalação/atualização do pacote binário em outro Mac. Os resultados por fontes e os resultados do bundle isolado permanecem separados.
