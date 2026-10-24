# Evidência parcial de d0fda92 — macOS 26

Originais baixados do [GitHub Actions 40103086558](https://github.com/vibracall-beep/PDF-/actions/runs/40103086558), preservados sem edição. O manifesto informa SHA-256 de cada arquivo e artefato de origem.

O terceiro smoke do aplicativo instalado aprovou 37 grupos. Vision passou os dois checks. O modelo Apple ficou indisponível (`deviceNotEligible`): nenhum dos cinco casos executou geração. O benchmark executou seis operações no corpus sintético de 100 páginas; OCR/contraste abrangem somente a primeira página. O hardware foi Apple M1 virtualizado; não há medição de M4 físico, NPU ou energia.

**A execução global falhou:** o empacotamento no macOS 26 recusou uma dependência de certificados do Homebrew; o macOS 27 parou na desmontagem do volume HFS+ de teste. Estes relatórios não aprovam o pacote portátil nem alterações posteriores.
