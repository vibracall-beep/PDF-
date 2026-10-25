# Revalidação focal do preflight — 81769db

O candidato **[`81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5`](https://github.com/vibracall-beep/PDF-/commit/81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5)** altera somente `scripts/install-binary.sh` e `scripts/test_binary_space.py` em relação à fonte consolidada `6c8be0e`. A mudança prepara uma cópia privada do manifesto em plist XML antes de lint/tipos/extração e confere schema 1 antes do ramo legado. A [falha anterior](../6c8be0e/README.md) permanece registrada com seus originais.

| Suíte focal no Linux | Resultado | Log original |
|---|---|---|
| Scripts | 143 métodos: **136 aprovados, sete ignorados**, 3,713 s | [scripts.log](scripts.log) |
| Evidência/distribuição | **116 aprovados**, 3,139 s | [diagnostics.log](diagnostics.log) |

Os bytes dos dois logs foram preservados, com hashes e fonte em [provenance.json](provenance.json). As contagens focais não são somadas à [rodada consolidada de 6c8be0e](../local-6c8be0e/README.md), nem apresentadas como repetição integral daquela rodada. Os sete skips continuam exigindo recursos macOS reais. Os checksums de pacotes de teste impressos nesses logs não são checksums de uma entrega aprovada.

A execução nativa [40229486932](https://github.com/vibracall-beep/PDF-/actions/runs/40229486932) terminou com sucesso nos dois sistemas. A [retenção final](../81769db/README.md) registra 143 métodos de scripts (142 aprovados/um skip Linux), 510 de núcleo e 60 integrações por Mac; os 43 grupos nativos passaram nove vezes, além de isolamento, instalação e atualização dos respectivos pacotes. Esses resultados têm fonte/logs próprios e não são somados às contagens locais acima. O teste cruzado do mesmo tar e a entrega privada permanecem etapas separadas.
