# Aparência 9d78ab9 — diagnóstico focal aprovado, entrega não aprovada

Fonte/controlador `9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb`, run `40252786964`, tentativa 1, jobs 26 `121348103194` e27 `121349491713`. **O diagnóstico focal automatizado passou nos dois sistemas:** 12 checks por sistema, sete PNGs por sistema e 36 medidas centrais dos três controles de toolbar. A revisão independente dos 14 originais não encontrou bloqueador visual confirmado nesses quadros; seu escopo restrito está preservado. Isso não aprova matriz completa, recuperação, pacote/instalador ou entrega.

| Evidência | Resultado |
|---|---|
| Build/pack SDK 26 e restore do mesmo bundle no 27 |Etapas originais success |
| Frames/reportes/recibos |7+7 PNGs; reportes/recibos passed |
| Checks nativos |12/12 em cada sistema |
| Contraste central dos 3 controles |18 medidas por sistema; mínimos 26=4.136178:1 e27=6.877762:1; limiar 3:1 |
| Identidade/geometria |24 snapshots antes/depois, conferidos pelo checker exato |
| Checker no SDK 26 |28 testes OK; não é a matriz completa |
| Recuperação/empacotamento/entrega |Fora da aprovação focal |

A escolha dos controles usa itens públicos reais; os JSON preservam identidades, metadados, bounds, medidas e PNGs correspondentes. O checker do Git exato refez offline as medidas a partir dos originais e conferiu seus gates. Contraste central em três controles não equivale a certificação universal WCAG; imagens estáticas não validam todos os cliques, animações, conteúdo rolável, VoiceOver humano ou demais áreas do aplicativo.

## Originais e proveniência

- `originals/downloads/`: dois ZIPs de evidência autenticados por digest GitHub e ZIP oficial de logs. Cada evidência foi baixada uma vez. Não há ZIP de transporte do bundle.
- `originals/extracted/`:inventários 15/14, com 14 PNGs, JSON/recibos, manifestos e logs originais. Nenhuma imagem foi alterada.
- `originals/official-attempt-logs/`:dois agregados; 31 membros completos estão no ZIP. O endpoint autenticado de logs não fornece digest independente; o SHA identifica os bytes recebidos.
- `provenance/`:APIs antes/depois, configuração/recibos e vínculo dos preflights ao Git 9d.
- `exact-source/`:16 seleções do coletor e o teste do checker acrescentado pelo vínculo do preflight. São seleções de fonte, não o aplicativo completo. RecoveryStore/WorkspaceModel/SessionAnnotationAuditChecks foram retidos, mas seus caminhos de recuperação não são exercitados por este focal.
- `reviews/`:recontagem factual e revisão independente dos 14 originais. Nenhuma aprovação anterior foi transferida. O collector-summary original mantém visual pending porque antecede esta revisão; a aprovação visual restrita posterior está no relatório independente, sem editar aquele original.
- `local-preflight/`:sintaxe de 90 Swift sem typecheck SDK, suíte local de 178 métodos (171 PASS e7 testes macOS pulados no Linux), reteste do checker 28 e hashes dos arquivos. A redação temporal de testes nativos pendentes foi preservada como preparação; o sucesso posterior aqui é limitado ao focal de aparência.
- `collection-tools/`:coletor 83430bd, delta / 18 testes offline, rascunhos, configuração final, log único de coleta e scripts de verificação/retenção. Rascunhos inválidos foram preservados como história, não usados como identidade real.

## Limites de aprovação

O root reproduziu separadamente falha do pacote fonte por tamanho expandido e atribuiu sua correção. Os relatórios dessa falha/preflight sujo ficam em retenção separada, sem TAR grande ou checkout encapsulado. A matriz completa 9d foi adiada; nenhum resultado deste focal aprova o pacote ou valida caminhos de recuperação. Um futuro pacote feito de commit limpo exigirá evidência separada.

Os manifestos são byte idênticos: SHA `2181b246f600178bc486a1de950fa9b06e33e6420a15f32e3f8f29f783350b09`. Declaram tar de5173480 bytes, SHA `fa3cd391299df0b9a3f282e35ea21a67abe1ca46d3cdd99ccb0aad05ddae4dd7`. APIs, pack/restore e metadados vinculam a declaração do mesmo bundle; o tar/app não foi baixado, extraído ou executado localmente. Bundle mínimo não é instalador completo.

`inventory.json` registra bytes/SHA/origem e `SHA256SUMS` cobre arquivos e índice. Confira com `sha256sum -c SHA256SUMS`. Esta retenção não testa M4 físico, consumo/Neural Engine, IA real, scanner, serviços de produção ou VoiceOver humano. `deliveryAllowed` permanece false.
