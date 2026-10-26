# Revisão factual9d78ab9 — focal automatizado aprovado, escopo restrito

Fonte/controlador `9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb`, run `40252786964`, tentativa1. Os dois jobs e todas as suas etapas terminaram em **success**. A releitura offline com o checker do Git exato confirmou reportes, originais e medidas. Isso aprova o diagnóstico focal de aparência; **não aprova recuperação, pacote/instalador, matriz nativa completa ou entrega**.

| Job | Sistema | PNGs | Checks | Medidas centrais | Menor contraste |
|---|---|---:|---:|---:|---:|
| compile-sdk26 · 121348103194 | Version 26.6.2 (Build 25G83) |7|12/12|18|4.136178:1|
| same-binary-xcode27 · 121349491713 | Version 27.0.1 (Build 26A434) |7|12/12|18|6.877762:1|

São36 medidas centrais, três controles reais em seis estados de workspace por sistema, com limiar3:1. O checker exato refez a comparação dos pixels e conferiu identidade, aparência, geometria e estabilidade antes/depois das capturas. Isso não é certificação WCAG universal nem validação de todos os controles/fluxos. Os24 snapshots e todas as36 medidas estão preservados no JSON acompanhante.

As sete linhas de captura de cada artefato coincidem com a etapa oficial e seu agregado. Os14 PNG coincidem com fingerprints/dimensões e passaram releitura de CRC/raster. O job26 registra28 testes do checker com OK, contados uma vez no agregado; o job27 não repete a suíte. O recibo impresso em cada validation.log corresponde exatamente ao JSON original e consta no log oficial.

Os manifestos são byte idênticos: SHA `2181b246f600178bc486a1de950fa9b06e33e6420a15f32e3f8f29f783350b09`. Declaram tar de 5173480 bytes, SHA `fa3cd391299df0b9a3f282e35ea21a67abe1ca46d3cdd99ccb0aad05ddae4dd7`. A coleta vincula a declaração do mesmo bundle pelos originais/API/pack/restore; não baixou, extraiu ou executou o tar/app localmente. Bundle mínimo não equivale ao instalador completo.

Os dois ZIPs de evidência foram baixados uma vez e reconferidos pelo digest GitHub e todos os membros. O ZIP oficial de logs e seus membros também foram reconferidos; esse endpoint autenticado não fornece digest externo independente. Os16 arquivos selecionados correspondem ao Git exato9d; os três arquivos de recuperação são apenas retenção de fonte, não caminhos exercitados pelo focal. Nenhum produto/gate foi alterado por esta releitura.

A revisão visual dos14 originais é independente e não foi inferida destes contadores. O coordenador relatou separadamente falha no package-source (147MB expandidos acima de120MiB), com correção atribuída a outra frente. Esta revisão não reproduziu nem aprovou esse pacote. A fonte9d não recebe aprovação de matriz completa/instalação/recuperação por ter passado no focal. M4 físico, energia/Neural Engine, IA real, scanner, VoiceOver humano e serviços de produção permanecem fora deste diagnóstico.
