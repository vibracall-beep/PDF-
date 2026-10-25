# Cross 37f5b65 — checks automatizados aprovados, revisão visual reprovada

**Não entregar este pacote como aprovado.** O run cross `40243611339`, job `121320462461`, concluiu com `success`, mas a revisão dos **33 PNG originais do binário instalado** confirmou um bloqueador visual: três controles da barra superior ficam quase brancos sobre cápsulas quase brancas no tema escuro. A aprovação visual é falsa e não houve entrega privada desta versão por esse motivo.

A evidência é do produto `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`, compilado na matriz `40239018570` em macOS 26 e instalado sem recompilar em macOS 27.0.1. Controlador cross: `e4f6c056058d3482b18cdcc24011ccdc96327004`. Tar examinado: `641d66d3c4bd68ad8074d906e6dd9c3c18ef946292da2d9512541948db52c4a4` (1449079284 bytes); seu ZIP/TAR grande não integra esta retenção compacta.

## Bloqueador confirmado no original

- Imagem: `originals/extracted/PDF-cross-platform-validated/PDF-preview.escuro.png`.
- SHA-256: `13dcfebf3a4ec930d6ee42360004ec4da89072da1d2b0e39a64249ad9aa0387a`.
- Controles afetados: alternar barra lateral, paleta de comandos e personalização.
- A revisão confirma a legibilidade insuficiente na captura. Não estabelece a causa, falha de clique nem permanência após transições.
- Os diagnósticos de pixels e o relatório visual estão preservados em `reviews/`; valores de pixels não são certificados como medição formal de contraste WCAG.

O nome upstream `PDF-cross-platform-validated` e os flags automatizados verdadeiros foram preservados literalmente. Eles representam o contrato de instalação/recibos/PNG/AX/OCR verificado, **não** a aprovação visual posterior. O achado não foi apagado nem reclassificado como sucesso.

## Evidência automatizada preservada

- Dois ZIPs originais de artefatos: 50 arquivos GUI e 3 arquivos lifecycle; digests GitHub, CRC e bytes/hashes de todos os membros novamente conferidos.
- 33 PNG, 7 árvores AX, par OCR original, metadados/recibos GUI e lifecycle separado. A auditoria de janela reporta 12 checks; seu escopo artificial permanece descrito no original.
- Logs oficiais completos: 44 grupos nativos repetidos três vezes, 132 inícios/132 aprovações, multiconjuntos e soma por etapa iguais. Os 20 métodos Python (9 + 11) pertencem ao controlador. Os logs e sua revisão discriminam diagnósticos negativos e avisos.
- Fonte e controlador selecionados diretamente dos commits Git exatos, comparados com os bytes usados pelo coletor; manifestos separados registram a seleção, que não equivale ao tar completo de fonte.
- Quatro metadados pequenos do binário e quatro da fonte vinculam o instalador, manifesto e arquivo testado. A retenção não refez download nem extração do tar grande.

## Organização

`originals/downloads/` contém os dois ZIPs de artefato; `originals/extracted/` preserva os dois inventários sem acrescentar arquivos dentro deles. `originals/full-run-logs/` contém o ZIP oficial e o log agregado; o endpoint oficial não fornece digest independente, e o hash identifica os bytes recebidos. `provenance/` conserva APIs, recibos, snapshots e vínculos nativos. `exact-source/` separa produto e controlador. `reviews/` contém relatórios derivados e `collection-tools/` preserva os scripts locais, sem confundi-los com o produto.

`inventory.json` registra caminho, tamanho, SHA-256, natureza e origem. `SHA256SUMS` também cobre o índice: execute `sha256sum -c SHA256SUMS` neste diretório para conferir os bytes retidos. Caminhos absolutos nos registros originais apontam ao ambiente de coleta e permanecem intactos.

O sucesso nativo anterior da fonte 37f5b65 não foi alterado. Ele não apaga a reprovação visual deste teste cruzado e não serve como aprovação de uma futura correção: qualquer novo commit/pacote exige evidência própria. Nenhum teste humano com VoiceOver, benchmark M4 físico, energia/Neural Engine ou integração externa de produção é aprovado por este diretório.
