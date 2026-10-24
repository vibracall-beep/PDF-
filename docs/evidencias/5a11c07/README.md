# Relatórios originais do CI — 5a11c07

Origem: [execução 40055682837](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837), commit **`5a11c07ba2ffc89dd01e10d7ba9ae11cf1f124ad`**. Os dois jobs passaram os requisitos funcionais de compilação, instalação/ativação, verificações nativas, capturas/AX, benchmark e empacotamento. Os quatro JSONs abaixo foram recebidos pelo download normal dos artefatos e copiados byte a byte, sem reconstrução a partir de logs. A [procedência](proveniencia.json) registra artefatos, tamanhos, hashes e verificação dos pacotes.

No macOS 26, os dois testes estritos do Apple Vision passaram. No macOS 27, ambos permaneceram **failed**; o OCR funcional utilizou Tesseract no aquecimento e nas três amostras medidas, com os motivos preservados no relatório. A aprovação do aplicativo não transforma a falha Apple em sucesso.

| Arquivo original | Artefato | SHA-256 calculado localmente |
|---|---|---|
| [benchmark-macos26.json](benchmark-macos26.json) | [12544919197](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12544919197) | `ac7a3080a99424b0974e4480b3744542eea736afbfc2c9d88eca50eb3771a131` |
| [vision-macos26.json](vision-macos26.json) | [12545631497](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12545631497) | `c36d1c17910bab4f6f1a6b1702c98894054b64d411bbeabaca02fef717376582` |
| [benchmark-macos27.json](benchmark-macos27.json) | [12546230213](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12546230213) | `1c20940def31430e23cbcfc9ce5add347a98d967ef924be44c83b0b76b27ca78` |
| [vision-macos27.json](vision-macos27.json) | [12546165721](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12546165721) | `f9689ccdb8f75b092eda53444ffc6f68cba0c12fde44731a8343b8f3e1823edc` |

## Medições

Ambos os runners identificam **Apple M1 (Virtual), arm64, três CPUs, 7 GiB e Apple Paravirtual device**. Sistemas: macOS **26.6.2 (25G83)** e **27.0.1 (26A434)**. Pico de RSS do processo principal: **301.023.232 bytes** e **149.028.864 bytes**, respectivamente; os subprocessos não são somados.

Medianas calculadas das três amostras originais, em milissegundos:

| Operação | macOS 26 | macOS 27 |
|---|---:|---:|
| Abrir | 0,151584 | 0,205542 |
| Extrair texto | 5,066958 | 4,930209 |
| Buscar | 1,103875 | 1,190250 |
| Renderizar | 3,825584 | 6,976542 |
| Contraste | 9,068167 | 12,150917 |
| OCR | 1448,468625 | 2014,243750 |

O corpus tem 100 páginas sintéticas, com hashes próprios registrados em cada JSON. Abertura resolve primeira/última página; extração e busca percorrem o documento; renderização cobre primeira, central e última. Contraste e OCR medem apenas a primeira página, após aquecimento. OCR usa Vision no 26 e Tesseract após falha Vision no 27. As medições não comprovam desempenho em M4 físico, utilização de NPU, consumo energético ou superioridade sobre outros aplicativos.

## Pacotes de fontes verificados

- [macOS 26, artefato 12545312794](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12545312794): `PDF-source-macos-26`.
- [macOS 27, artefato 12545304284](https://github.com/vibracall-beep/PDF-/actions/runs/40055682837/artifacts/12545304284): `PDF-source-ocr-compatibility-xcode-27`.

Os dois arquivos `PDF-source.tar.gz` recebidos são idênticos: **879.944 bytes**, SHA-256 **`e7b036f9d2277235b94758703c5fb4c789306573f4dca12a24a9aa138d253619`**. O checksum externo e as 105 entradas do manifesto foram conferidos localmente. `BUILD-INFO.json` identifica o commit acima e `working_tree_dirty=false`; os 106 membros incluem o manifesto e os fontes de diagnóstico. A inspeção de nomes não encontrou extensões de chaves/certificados privados. Esses arquivos são fontes para instalação local, não bundles portáteis.
