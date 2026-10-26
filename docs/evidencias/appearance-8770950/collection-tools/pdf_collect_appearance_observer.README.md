# Coletor focal do observador — cópia isolada

`/tmp/pdf_collect_appearance_observer.py` copia o coletor revisado de SHA-256 `95c779d4183fd7bd79318d58d3d55847f0f55580d620606753b47f19e669947b` e acrescenta somente `Sources/PDF/AccessibilityAudit.swift` à seleção de fonte exata do aplicativo. O arquivo contém o getter agora compartilhado. Não altera autenticação, limites, inventários de15/14 arquivos, gates, interpretação de resultados ou política de download. O coletor anterior e sua retenção permanecem intactos.

Novo SHA-256: `d995f7c4ed2baffbba670b90fca2a43461c606b1afbeda3350dd92e7a8d79906`.
Delta: `/tmp/pdf-appearance-observer-collector.diff`.

Configuração provisória: `/tmp/pdf-appearance-8770950-config.draft.json`.

- Fonte/controlador: `8770950674f5e026dda5f3f9a0ae479e337f06d8`.
- Run: `40248300537`, tentativa1.
- Compilação26: job `121334482597`.
- Destino27: ainda nulo; o parser recusa o rascunho.
- Saída dedicada: `/workspace/.cache/pdf-appearance-8770950-40248300537`.

18 testes offline passaram, sem rede, main, coleta ou execução de artefatos. O arquivo adicional existe no Git do commit exato; sua leitura usou `GIT_NO_LAZY_FETCH=1`. O resultado está em `/tmp/pdf-appearance-observer-collector-offline-tests.{json,log}`; teste em `/tmp/test_pdf_collect_appearance_observer_offline.py`.

Aguarda revisão do coordenador, ID real do destino e confirmação de run terminal. A execução futura será apenas com a configuração completa aprovada:

```
python /tmp/pdf_collect_appearance_observer.py --config /tmp/pdf-appearance-8770950-config.json
```

Não executar esse comando durante a preparação. O contrato do coletor original permanece descrito em `/tmp/pdf_collect_appearance.README.md`. Este focal não aprova matriz completa, instalador, aplicativo inteiro, revisão visual ou entrega e não altera as reprovações anteriores.
