# Coletor focal de aparência — preparação, não execução

Script: `/tmp/pdf_collect_appearance.py`. Testes offline: `/tmp/test_pdf_collect_appearance_offline.py` (16 métodos aprovados). Nenhum main, consulta API, download ou execução de artefato foi realizado durante a preparação.

Candidato informado pela coordenação: fonte/controlador `2f3134a41229054f41a176d6a48cc6c23e388b77`, run `40246632222`, tentativa 1, evento `workflow_dispatch`, workflow `.github/workflows/appearance-compatibility.yml`.

Configuração provisória: `/tmp/pdf-appearance-2f3134a-config.draft.json`. O job de compilação foi informado como `121329466580`; o ID de `same-binary-xcode27` ainda está nulo porque não foi informado à preparação. O parser recusa esta configuração até ambos os IDs reais positivos/distintos serem preenchidos. Nenhuma busca automática por run recente, branch ou fonte alternativa ocorre. A saída exclusiva será `/workspace/.cache/pdf-appearance-2f3134a-40246632222`.

## Antes de executar

O coordenador precisa revisar o coletor, preencher os IDs exatos `compile-sdk26` e `same-binary-xcode27` da tentativa e aguardar estado terminal. Exemplo de comando futuro, somente após essa coordenação:

```
python /tmp/pdf_collect_appearance.py --config /tmp/pdf-appearance-2f3134a-config.json
```

A inicialização importável não faz IO/rede. `main` exige configuração fechada: `schemaVersion`, `sourceCommit`, `controlCommit`, `runID`, `runAttempt`, `jobIDs`, `outputDirectory`. Não instala, compila, dispara workflow, modifica release nem executa/restaura binário ou tar de artefato.

## Contrato de origem e retenção

- API oficial fixa do repositório ID 1431437116; evento/path/commits/run/tentativa/IDs/nomes/labels dos jobs conferidos, com metadados originais antes e depois. O run deve estar terminal; falha ou cancelamento não vira sucesso e suas evidências parciais são conservadas.
- Artefatos permitidos: `PDF-appearance-sdk26` (15 arquivos de sucesso), `PDF-appearance-same-binary-xcode27` (14), `PDF-appearance-minimal-bundle-sdk26` (somente identidade/digest API, **sem download do bundle/tar**).
- Cada grupo de evidência tem sete PNG `PDF-appearance{,.dark-attached-1,.dark-attached-2,.customization,.dark-recreated,.light-return,.system}.png`, reporte nativo, recibo, manifesto e logs originais. O fonte tem origin/build/bundle/capture/validation.log; o destino origin/restore/capture/validation.log.
- O ZIP de evidências deve coincidir com tamanho/digest GitHub e intervalo de execução do job. Verificação estrita de diretório, nomes, tipos, CRC, tamanhos e expansão; somente arquivos regulares conhecidos são publicados em diretório privado. Extração nunca usa `extractall` nem executa conteúdo.
- O helper e validador ZIP são carregados somente de bytes `git show` do controlador exato, com lazy network fetch desativado e cópias retidas. O helper da fonte deve ser idêntico ao do controlador; Info.plist é comparado ao Git exato da fonte. Nenhum módulo de artefato é importado.
- `validate_report` do helper exato revalida PNGs originais e relatório; o recibo deve vincular cada original e quatro fingerprints do bundle. As declarações do mesmo manifesto/tar/bundle precisam coincidir nos dois sistemas; origem do destino também vincula o ID do artefato de transporte e os hashes independentes recebidos do job de compilação. Não declara rehash local do binário, porque ele não é baixado.
- O ZIP oficial de logs terminais e os dois agregados são preservados; todos os membros têm CRC/hash verificados. O endpoint de logs não oferece digest independente; o coletor distingue o hash recebido da autenticação por API.
- Downloads de evidência já autenticados são reusados. Uma tentativa falha não gera retry automático; arquivos temporários não são apresentados como originais. Erros HTTP são resumidos sem expor URLs assinadas ou stderr completo.

Limites: ZIPs de evidências até128MiB, PNG80MiB, JSON2MiB, log32MiB, expansão de evidência256MiB; ZIP oficial de logs64MiB e expansão128MiB. São limites do coletor e não promessas sobre arquivos PDF arbitrários.

## Conclusões permitidas

`appearanceDiagnosticAutomatedPassed` só é verdadeiro com os dois jobs e run em sucesso, os dois inventários completos/recibos aprovados e o mesmo bundle declarado. A revisão visual continua pendente, e `fullNativeMatrixApproved`, `installationApproved`, `completeApplicationApproved` e `deliveryAllowed` permanecem falsos. O app mínimo não testa runtime/engine/instalador completo. A reprovação visual histórica de37f5b65 não é apagada e sua aprovação nativa não é transferida ao novo candidato.
