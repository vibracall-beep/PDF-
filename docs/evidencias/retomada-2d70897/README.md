# Retomada da auditoria — fonte `2d70897`

Esta retenção registra a retomada da auditoria do aplicativo PDF na fonte
`2d708974d91c96dde422adf1d8a480a7c6b9d808`. Os arquivos foram copiados dos
caches locais sem editar PNGs, JSONs ou logs. `SHA256SUMS` cobre cada arquivo
retido (o próprio manifesto não é incluído no cálculo).

O commit posterior `bc3021a` acrescenta uma proteção de contraste nos dois
controles reais da barra, sem alterar os IDs, a seleção pública ou os gates do
diagnóstico. A retenção abaixo continua vinculada somente à fonte `2d`; a nova
fonte exige uma matriz nativa própria.

## Focal de aparência

A execução [40254721260](https://github.com/vibracall-beep/PDF-/actions/runs/40254721260),
tentativa 1, compilou o diagnóstico mínimo no SDK 26 e executou o mesmo bundle
no macOS 27.0.1. Os dois sistemas têm 12 checks aprovados, 36 medidas centrais e
24 snapshots antes/depois. A revisão independente abriu os 14 PNGs originais em
resolução original: os três controles da barra estão legíveis nos 12 frames de
workspace e Equilibrado/Restaurar aparecem nas duas capturas de Personalização.
Os menores contrastes medidos foram 4,136177866:1 no macOS 26 e 6,877762169:1
no macOS 27, com limiar interno de 3:1.

Esse resultado é **focal**. Ele não aprova o motor completo, recuperação,
instalador, conversão de documentos, abas, edição, IA, M4 físico, VoiceOver
humano, serviços de assinatura ou entrega do aplicativo. Os PNGs e relatórios
originais estão em `focal-appearance/originals/`; os ZIPs de transporte não são
duplicados nesta retenção e continuam no cache autenticado fora do repositório.
A análise independente está em `focal-appearance/appearance-independent.md` e
`.json`.

## Matriz completa na fonte final

A execução [40254721424](https://github.com/vibracall-beep/PDF-/actions/runs/40254721424),
tentativa 1, foi iniciada por `workflow_dispatch` na mesma fonte. A página
pública do GitHub registra o job macOS 26 como concluído e o job xcode-27 como
**falho** em `Capture native window preview`, em 26/10/2026. O diagnóstico
visível na anotação é:

> A legibilidade dos controles reais da barra superior falhou em escuro. O PNG original e as medições foram preservados.

A mensagem é o erro genérico emitido quando o relatório de barra não passa; sem
o JSON/PNG autenticado do job 27, ela **não prova** se a causa foi contraste,
seleção, geometria, estilo ou outra invariável do relatório. A etapa seguinte
de validação de todos os artefatos foi pulada. `full-failure/` preserva as
páginas públicas, textos, cabeçalhos e inventário de artefatos observados; os
artefatos do GitHub não foram baixados nesta retomada porque o endpoint
autenticado permaneceu bloqueado. Os IDs e digests publicados são apenas
referências, não uma autenticação local do conteúdo.

Por isso a matriz completa e a entrega permanecem **não aprovadas**. Não se
reutiliza a aprovação histórica de outra fonte.

## Verificações locais da fonte

Em 03/11/2026 UTC, com a árvore limpa nessa fonte:

- núcleo Python: 510 testes, `OK`;
- scripts: 183 testes, `OK (skipped=7)` — os sete skips são testes macOS no Linux;
- controles de entrega: 55 testes, `OK`;
- capacidades do motor: dependências declaradas disponíveis, com as limitações
  registradas no JSON.

Os recibos e logs originais dessas execuções estão em `local-20261103/`. Eles
não substituem compilação/execução nativa no macOS.

## Limites e próximo gate

O catálogo conserva 71 ferramentas e o leitor, mas presença estática não é
aprovação funcional de cada documento. Permanecem parciais ou dependentes de
ambiente: reconstrução universal de layouts/objetos, OCR de documentos difíceis,
reconstrução semântica PDF/UA, rascunhos de editor/OCR após crash, geração IA
real em português, medições em M4 físico (GPU/NPU/energia), certificados e
serviços de produção, sincronização entre dois Macs, scanner/Atalhos de
produção e certificação ISO PDF/X.

O próximo gate é corrigir e reproduzir o erro do job xcode-27, executar uma nova
matriz completa na fonte exata, coletar os artefatos autenticados e revisar as
capturas originais antes de qualquer teste cruzado ou retenção de instalador.
Nenhuma publicação pública, assinatura Apple ou licença nova é criada por esta
retenção.
