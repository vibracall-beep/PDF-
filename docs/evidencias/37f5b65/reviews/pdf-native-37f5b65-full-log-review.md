# Revisão final dos logs oficiais — 37f5b65

Fonte **37f5b65e35a9f70c716cfcd64db7ba69837f5c21**, execução **40239018570**, tentativa 1: API final **success nos dois jobs**. Identidade, tentativa, fonte e estado terminal foram confirmados antes e depois do download autenticado.

O ZIP original tem **1.007.879 bytes**, SHA-256 **`b8b11dd2ae6c07293d88ba787662a972e3d866d5ec4e321349725aeca310923c`**. Seus **62 membros**, totalizando **8.295.273 bytes expandidos**, passaram em CRC, nomes, tipos e limites de tamanho. O endpoint oficial não oferece digest independente; o SHA identifica os bytes recebidos. Somente os dois logs agregados foram extraídos. Nenhum código do ZIP foi executado.

| Resultado por Mac | Métodos / execuções | Aprovações / skips |
|---|---:|---:|
| Scripts | 150 | 149 aprovados / um skip Linux |
| Núcleo | 510 | 510 aprovados |
| Integrações | 60 | 60 aprovados |
| Total Python | 720 | 719 aprovados / um skip |
| Nativos | 44 grupos distintos × 9 | 396 inícios / 396 aprovações |

O skip é `test_real_enospc_after_backup_restores_old_bundle`: requer `/dev/full` do Linux. Não houve falhas, erros ou expected failures nas três suítes. Os multiconjuntos de nomes iniciados/aprovados coincidem, e a soma das quatro etapas coincide com o agregado: **duas execuções na instalação de fontes, uma no app instalado, uma no isolamento portátil e cinco na instalação/atualização do binário**. As repetições não são novas funções.

## macos-26 — job 121306620661

installer/scripts: 27.095 s; core/tests: 140.128 s; integration: 113.808 s. Log completo: **1,332,840 bytes**, SHA-256 **`7bee54537f9ea8a848480483f184f9fd1e15368c581e4eba9114aeb4b4c54038`**.

PDFKit bruto registrou **9 resultados `FAILED`**, explicitamente diagnósticos de referência, sem saída de produto. As verificações de estrutura das saídas tratadas passaram. Houve **seis avisos CoreGraphics**, cada um entre a recusa deliberada do stream inválido e sua normalização aprovada. Não houve `Native check failed` nem marcador fatal de etapa.

Duas mensagens do ciclo real da janela correspondem às etapas antecipada e instalada. A leitura dos logs também localizou uma publicação do instalador de fontes, duas instalações binárias aprovadas e uma recusa do checksum adulterado. Os JSONs/recibos e a autenticação dos próprios pacotes permanecem evidências separadas.

## xcode-27 — job 121306620477

installer/scripts: 30.556 s; core/tests: 133.672 s; integration: 99.881 s. Log completo: **2,814,135 bytes**, SHA-256 **`ca9ae98b246e9c5594b50f959368c0e3ab58c837cc7c4e6ec69a0356c1a7cde2`**.

PDFKit bruto registrou **27 resultados `FAILED`**, explicitamente diagnósticos de referência, sem saída de produto. As verificações de estrutura das saídas tratadas passaram. Houve **seis avisos CoreGraphics**, cada um entre a recusa deliberada do stream inválido e sua normalização aprovada. Não houve `Native check failed` nem marcador fatal de etapa.

Duas mensagens do ciclo real da janela correspondem às etapas antecipada e instalada. A leitura dos logs também localizou uma publicação do instalador de fontes, duas instalações binárias aprovadas e uma recusa do checksum adulterado. Os JSONs/recibos e a autenticação dos próprios pacotes permanecem evidências separadas.

## Avisos preservados e classificados

Em **cada Mac**, o único sítio de aviso Swift foi `VisionFailureDiagnostics.swift:122`: uso diagnóstico de `usesCPUOnly`, obsoleto desde macOS 14. Apareceu em duas compilações e em dois trechos de fonte. Os avisos anteriores de retorno `drop` e isolamento `MainActor` não aparecem nesses logs.

Também em cada Mac, **614 avisos de `install_name_tool`** informaram invalidação da assinatura durante a relocação de dependências. O código exato do empacotador reassina os arquivos modificados e exige `codesign --verify --deep --strict` antes do manifesto; essa etapa e os controles posteriores passaram. Isso não equivale a notarização Apple.

Avisos de infraestrutura por Mac: um de qpdf já instalado, um de openjdk@21 instalado sem link global por existir outro openjdk, um do binding SWIG/PyMuPDF, oito sobre `punycode`, oito sobre `url.parse()` e um sobre ações Node20 executadas em Node24. O probe `appintentsmetadataprocessor --help` recusou opções uma vez em cada sistema; a verificação final de metadados é uma etapa distinta. Todas essas mensagens permanecem nos originais, com categorias e números de linha no JSON. Nenhuma categoria de aviso ficou sem classificação nesta revisão.

## Alcance

Esta revisão confirma a matriz registrada e as contagens de sua tentativa completa. Não aprova o mesmo tar entre sistemas, a retenção privada da entrega, M4 físico, Neural Engine/energia, VoiceOver humano, geração real por modelo indisponível, serviços externos ou notarização. A existência de avisos diagnósticos não foi escondida; os controles e limites foram associados aos logs correspondentes.

Arquivos: `collector-attempt-1-logs.zip`, dois logs completos em `collector-attempt-1-logs/`, snapshots de API antes/depois e `/tmp/pdf-native-37f5b65-full-log-review.json`. SHA/CRC dos originais preservados; nenhum arquivo do repositório foi alterado.
