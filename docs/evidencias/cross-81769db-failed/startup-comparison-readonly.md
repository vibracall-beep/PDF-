# Comparação factual da falha de início — somente leitura

Produto: 81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5. Cross: 40234132628, controle 0c3aad82d319a8985ebc8b7c6fb868d5f91c5f0e. Nenhuma edição, reexecução da GUI ou alteração de preferências foi feita nesta investigação.

## Diferença observada

- Cross817: 18 marcadores de início; nenhum `WindowGroup content builder evaluated`, `window observer` ou `PDF preview phase`; nenhuma captura começou. O corpo do App foi avaliado. `didFinishLaunching`, próximo turno da fila principal e observação de dois segundos ocorreram com `windows=0`, `contentViews=0`, `defaultLaunch=false`. O supervisor encerrou após 300 segundos (124). Isso não registra crash e não demonstra bloqueio da fila principal nos primeiros dois segundos.
- Native817 macOS26/27: o WindowGroup foi criado e associado antes de didFinishLaunching. Nesse ponto havia duas janelas, uma visível, duas contentViews e defaultLaunch=true. Cada execução contém 33 pares Capture starting/completed; os demais originais AX/OCR são artefatos diferentes dos PNGs.
- Cross437 aprovado: mesma ordem de criação da janela e defaultLaunch=true, com 32 pares Capture starting/completed.

## Invocação e ambiente conhecidos

- portable-compatibility.yml é byte idêntico entre o controle cross437 (6daf46294b10f35ec8252fd473f1d0865cd4bf8f) e o atual. Wrapper, prazo de 300s, argv `--render-preview`, caminho instalado, destino, tee e ausência de sandbox na GUI são iguais. As três variáveis explícitas PDF_SOURCE_RUN_ID/PDF_SOURCE_COMMIT/PDF_EXPECTED_SHA mudam para identificar o produto. O ambiente completo do processo não foi capturado; não se afirma igualdade universal.
- Cross437 e cross817 registram o mesmo macOS27.0.1 build26A434, image xcode-27-arm6420261023.0307.1 e runner provisioner20261021.618.
- Native817 usa caminho pdf-installed e fonte instalada pelo build; cross usa pdf-cross-installed e tar autocontido autenticado. Native inclui --sample-on-timeout; os dois cross não incluem. Essa flag só é consultada após expirar o prazo e não explica a ausência anterior de janela.
- run-with-timeout.py é byte idêntico entre produto437 e817. O início em PDFApp mantém entrada síncrona na main thread; o diff acrescentou seleção de LibraryCrashAudit ao modo CLI, mas cross817 registra CLI dispatch complete seguido de App.main/PDFApp.init completos. Os trechos de observação inicial e MacPreviewSession.init não mudaram. Mudanças posteriores de conteúdo, encerramento e capturas existem, portanto não se afirma equivalência de todo o produto.

## Histórico que impede inferência causal

- e9af24a/macOS27 já expirou após didFinishLaunching sem criação do WindowGroup; naquele commit faltavam as observações de estado posteriores.
- startup64036d3 registrou quatro lançamentos instrumentados com janela visível. Os segundos lançamentos, inclusive macOS27, tinham defaultLaunch=false e ainda assim criaram a janela. Logo esse flag distingue os resultados presentes, mas não é causa suficiente nem diagnóstico concluído.
- O diagnóstico64036d3 pausava antes de preparar documentos/capturar e não aprovou o produto. A falha atual não alcançou preparação de fixtures, OCR ou ScreenCaptureKit; não há evidência para atribuí-la a esses subsistemas.

## Originais preservados

Em originals/: run-40234132628.json, jobs-40234132628.json, annotations-121291948830.json e job-121291948830.log. comparison-cross437-job.txt é um membro original extraído do ZIP já versionado. startup-comparison-derived.json registra hashes, contagens e linhas dos quatro logs comparados. Os logs nativos817 permanecem em /tmp/pdf-native-81769db/collector-attempt-1-logs/.

Linhas atuais: invocação1288–1302, entrada1303, corpo1315, didFinish1318, callback1319, observação1320, timeout1321–1322. Cross437: WindowGroup1250, didFinish1255. Native817/mac26: WindowGroup5423, didFinish5428; native817/mac27: WindowGroup26504, didFinish26509. Histórico: docs/evidencias/startup-64036d3/xcode-27-launch-2-startup.log:16,21,28 prova janela com defaultLaunch=false.

Conclusão: o ponto concreto de falha é a realização inicial da cena/janela SwiftUI, antes da sequência de captura. A causa ainda não foi demonstrada. Esse ensaio continua reprovado; os sucessos nativos anteriores não o substituem.
