# Revalidação focal do preflight — 81769db

O candidato **[`81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5`](https://github.com/vibracall-beep/PDF-/commit/81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5)** altera somente `scripts/install-binary.sh` e `scripts/test_binary_space.py` em relação à fonte consolidada `6c8be0e`. A mudança prepara uma cópia privada do manifesto em plist XML antes de lint/tipos/extração e confere schema 1 antes do ramo legado. A [falha anterior](../6c8be0e/README.md) permanece registrada com seus originais.

| Suíte focal no Linux | Resultado | Log original |
|---|---|---|
| Scripts | 143 métodos: **136 aprovados, sete ignorados**, 3,713 s | [scripts.log](scripts.log) |
| Evidência/distribuição | **116 aprovados**, 3,139 s | [diagnostics.log](diagnostics.log) |

Os bytes dos dois logs foram preservados, com hashes e fonte em [provenance.json](provenance.json). As contagens focais não são somadas à [rodada consolidada de 6c8be0e](../local-6c8be0e/README.md), nem apresentadas como repetição integral daquela rodada. Os sete skips continuam exigindo recursos macOS reais. Os checksums de pacotes de teste impressos nesses logs não são checksums de uma entrega aprovada.

A nova execução [40229486932](https://github.com/vibracall-beep/PDF-/actions/runs/40229486932) foi disparada para este candidato. A consulta autenticada da API já informou **Verify installer integrity aprovada nos dois jobs**, que avançaram para **Compile native application**. Esse é um estado intermediário: logs e contagens nativos completos ainda serão retidos, e a compilação e as demais etapas continuam em andamento. **O aplicativo e o pacote ainda não estão aprovados nesta revisão.**
