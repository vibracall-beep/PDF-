# Aparência 2f3134a — focal reprovado, sem aprovação de entrega

Fonte e controlador `2f3134a41229054f41a176d6a48cc6c23e388b77`, run `40246632222`, tentativa 1. **Compilação/empacotamento SDK 26 e restauração no macOS 27 passaram; o observador de aparência e a validação falharam nos dois sistemas. Foram concluídas zero medidas nativas de contraste. A revisão visual focal também foi reprovada pelos controles ausentes em Personalização no SDK 26. O workflow nativo completo não foi despachado para esta fonte.** Nenhum resultado deste diretório aprova instalação, pacote completo ou entrega.

## Resultado preservado

| Etapa / evidência | Estado |
|---|---|
| Build/pack SDK 26.5, bundle mínimo | Aprovados pelas etapas originais |
| Restore/verificação do mesmo bundle no macOS 27 | Aprovados pelas etapas originais |
| Capturas originais | Sete por sistema, 14 PNG preservados e íntegros |
| Reportes/recibos de aparência | `failed` nos dois sistemas |
| Checks nativos | 8 true e 4 false em cada sistema |
| Medidas de contraste | Zero; `measurements=[]` nos seis toolbarReports de cada sistema |
| Revisão visual focal | Reprovada: Espaçamento e Restaurar ausentes no SDK 26; causa/duração desconhecidas |
| Matriz completa / instalação / entrega | Não aprovadas; matriz completa não despachada |

Os mesmos quatro checks falharam: janela real, contraste dos três controles, preservação das identidades anexadas e retorno dos controles após personalização. Os erros dizem que os controles diretos esperados não foram localizados; `workspaceToolbarProviderCount=0` e `controls=[]`. Esses registros não demonstram que o contraste numérico passou ou falhou. As snapshots/logs contêm janela 29 em cada processo; esse número não sobrepõe os checks falhos. A revisão factual não estabeleceu causa do aplicativo.

A revisão visual independente abriu os 14 originais: não observou os símbolos brancos sobre branco nos 12 estados de workspace examinados. **Separadamente, Espaçamento e Restaurar não aparecem na captura de Personalização do SDK 26**, enquanto aparecem na do mesmo bundle em27. As imagens e observações por arquivo estão preservadas; isso não aprova cliques, animações, interação completa ou VoiceOver. O resultado permanece reprovado.

Os dois manifestos do bundle são byte idênticos: SHA-256 `9aceea76b8efd1cccf43abf6469b2ba1ed885220a35daa4756024331a7c9a937`. Declaram tar `0aa4044312b4486c7b712fac98ffb035cbffa08f8788729f9bada1d74e635868`, 5.104.036 bytes. Esse tar/app mínimo não foi baixado, extraído, executado nem retido pelo coletor local; o vínculo é dado pelas APIs, etapas e metadados originais. Bundle mínimo não é instalador completo.

## Originais e proveniência

- `originals/downloads/`: dois ZIPs de evidência autenticados pelo digest GitHub e o ZIP oficial de logs. Não contém ZIP do bundle de transporte.
- `originals/extracted/`: inventários originais de 15 e 14 arquivos, incluindo PNGs, reportes de falha, manifestos e logs.
- `originals/official-attempt-logs/`: dois logs completos agregados; os logs por etapa permanecem no ZIP. O endpoint oficial não fornece digest independente; o SHA identifica os bytes obtidos pela API autenticada.
- `provenance/`: configuração, estados, snapshots API antes/depois, recibos do coletor e vínculo do preflight local ao commit exato.
- `exact-source/`: seleção do Git exato usada por validadores/diagnósticos, além dos oito arquivos de candidato cujos hashes constam do preflight. Não é o arquivo completo do aplicativo.
- `reviews/`: revisão factual, revisão visual independente e notas de preparação preservadas com sua redação temporal original.
- `local-preflight/`: sintaxe Swift de 90 arquivos (sem typecheck do SDK), scripts: 171 métodos, 164 PASS e 7 skips no Mac e preservação do catálogo. Isso não substitui o ensaio macOS real reprovado.
- `collector-history/`: código antes/depois, configuração, diff, resultados dos 18 testes offline e logs do incidente de coleta.

## Incidente local do coletor, separado do produto

A primeira coleta autenticou o ZIP26, mas recusou seus nomes `PDF-appearance…` porque comparava erroneamente o nome literal com a chave de colisão normalizada em minúsculas. A correção autorizada usa normalização somente para detectar colisões, preserva nomes literais/allowlist/caminhos e mantém as verificações ZIP. Passaram 18 testes offline, incluindo maiúsculas legítimas e colisão por caixa. O ZIP26 foi reutilizado; cada artefato foi baixado uma única vez. O erro não foi apagado nem apresentado como falha do aplicativo.

## Integridade e limites

`inventory.json` registra caminho, bytes, SHA-256, natureza e origem de cada arquivo; `SHA256SUMS` também cobre o índice. Execute `sha256sum -c SHA256SUMS` aqui para conferência local. Os14 PNG também tiveram CRC/raster e fingerprints comparados aos frames, sem retoque ou execução do aplicativo. Nenhum arquivo de produto foi alterado por esta retenção.

A reprovação visual histórica de 37f5b65 permanece. Sua aprovação nativa não foi transferida a 2f3134a, e as observações desta fonte não aprovam uma futura correção. Não há medição de M4 físico/Neural Engine/energia, prova de modelo de IA real, serviços de produção, VoiceOver humano ou aplicativo definitivo sem erros.
