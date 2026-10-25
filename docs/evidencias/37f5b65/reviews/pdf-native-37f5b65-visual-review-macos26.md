# Revisão visual independente — macOS 26, fonte 37f5b65

Fonte: `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`. Run: `40239018570`. Revisor: `/root/print_audit`.

Inspeção visual independente de todos os 33 PNG originais com tools.view_image; hashes e dimensões calculados sobre os mesmos arquivos. Sem edição de produto ou imagens e sem comparação substitutiva com fontes anteriores.

**33/33 PNG abertos; 0 bloqueadores visuais confirmados no conteúdo visível.** Os 33 enquadramentos foram lidos. Não foi identificado bloqueador visual confirmado nos controles efetivamente visíveis. Existem áreas que dependem de rolagem e experiências não cobertas pela amostra.

**Não é aprovação global do aplicativo, instalador, fluxos completos ou VoiceOver.** A revisão não extrapola de screenshots para interações nem usa imagens anteriores como evidência desta fonte.

## Observações e limites

### V1 — observation

Toolbar horizontal mostra somente parte dos comandos; com inspetor de anotações, a área fica menor e controles à direita são parcialmente cortados no viewport. Há barra de rolagem no leitor.
Não foi confirmado bloqueio funcional; alcançar todos os comandos exige interação/rolagem, fora do escopo estático.

Imagens: `PDF-preview.leitor.png`, `PDF-preview.abas.png`, `PDF-preview.anotacoes.png`

### V2 — coverage-limit

Telas extensas têm controles abaixo da área inicialmente visível e barras de rolagem.
A revisão não aprovou controles inferiores ou fluxos completos apenas porque a parte superior está legível.

Imagens: `PDF-preview.editor-conteudo.png`, `PDF-preview.revisao-ocr.png`, `PDF-preview.fluxo-lote.png`, `PDF-preview.solicitar-assinaturas.png`, `PDF-preview.ferramentas.png`, `PDF-preview.opcoes-leitura.png`

### V3 — observation

A captura de revisão OCR declara idioma Inglês/tesseract enquanto a página de demonstração contém português.
A imagem prova a apresentação de palavras/confiança/correção, não a avaliação do reconhecimento em português ou a seleção automática do idioma.

Imagens: `PDF-preview.revisao-ocr.png`

### V4 — coverage-limit

Hardware informado é Apple Paravirtual device, 3 núcleos e 7 GB.
Esta evidência de CI não mede desempenho, energia, GPU ou Neural Engine em M4 físico.

Imagens: `PDF-preview.arquivos.png`

### V5 — coverage-limit

Não há captura dedicada de criar/preencher formulários, scanner, diálogo de sincronização, geração real de IA, menus abertos da barra do macOS ou resultados finais de impressão/assinatura.
Ausência na amostra não prova ausência da função; estas experiências não foram aprovadas nesta revisão.

Cobertura ausente na amostra.

## Inventário inspecionado

### PDF-preview.abas.png

- SHA-256: `8b59fef2f330cec8b671a1018eecf455e74ed9e5654add5a5032904f40c0df58`
- Dimensões: 1050 × 772; bytes: 124057.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.abas.png`
- Aberto com `tools.view_image`.

Duas abas distinguíveis, segunda selecionada, botão + e fechamento por aba visíveis; conteúdo corresponde ao título selecionado. Persistência/troca por interação não testadas nesta revisão.

### PDF-preview.anotacoes.png

- SHA-256: `a414e0083c73cf27547638b45ebc19bcd888bba45464f45babdc02fbeaf210d4`
- Dimensões: 1050 × 772; bytes: 155431.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.anotacoes.png`
- Aberto com `tools.view_image`.

Nota selecionada com alças, texto e dimensões no inspetor. Aplicar alterações/Desfazer e Salvar cópia visíveis. O inspetor reduz a área do leitor; toolbar e ações à direita ficam parcialmente fora do enquadramento, sem prova estática de acesso a todas.

### PDF-preview.arquivos.png

- SHA-256: `a8fe7b7e3418ce2289d3554b0f1ac3721557ddf082c9a5be59db770509a38b49`
- Dimensões: 1050 × 752; bytes: 77306.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.arquivos.png`
- Aberto com `tools.view_image`.

Modelo de nomes, nome alternativo, pasta, cópias automáticas e limpar recentes visíveis. Informação de hardware mostra Apple Paravirtual device, 3 núcleos e 7 GB; não é evidência de M4 físico.

### PDF-preview.assinatura-digital.png

- SHA-256: `96bf99a028edac865a2b378330a7459db6638b74598652f9520578bd497eab8b`
- Dimensões: 1050 × 752; bytes: 84324.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.assinatura-digital.png`
- Aberto com `tools.view_image`.

Campos de certificado, PIN, motivo, local, nome e perfil PAdES legíveis. Salvar desabilitado sem certificado; avisos de original e limitações claros. Não há assinatura concluída.

### PDF-preview.atalhos.png

- SHA-256: `c126dbd134dee4ca7d62b092939bd8c14c968d167fa1246ee2d023e40c8e38f8`
- Dimensões: 1050 × 752; bytes: 75603.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.atalhos.png`
- Aberto com `tools.view_image`.

Busca e atalhos editáveis de comandos visíveis, com informação sobre conflitos/reservas. Lista rolável; editor de um atalho não está aberto.

### PDF-preview.auditar-pdfua.png

- SHA-256: `8dde7c59314eaac2a771225ae9cfaacc33ef574073493719b1aa125a57f0b4bf`
- Dimensões: 1050 × 752; bytes: 70265.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.auditar-pdfua.png`
- Aberto com `tools.view_image`.

veraPDF, perfil PDF/UA-1 e ação de validar legíveis. Texto distingue regras automáticas, criação de tags e revisão humana; não equivale a teste com VoiceOver.

### PDF-preview.automacao.png

- SHA-256: `e86301c350608686c653a532d6264cf43a9662bf937fc6a585eb2773e23dab9e`
- Dimensões: 1050 × 752; bytes: 93918.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.automacao.png`
- Aberto com `tools.view_image`.

Regra de pasta, fluxo, entrada/saída e instruções Finder legíveis; criar regra desabilitado sem entradas, nenhuma pasta ativa. Limitação de app aberto explícita; não comprova disparo real.

### PDF-preview.biblioteca.png

- SHA-256: `09ff575038c2f3fce69c4e9212eedd3fb66d95e94b9387d91037b808b57283ca`
- Dimensões: 1050 × 752; bytes: 111883.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.biblioteca.png`
- Aberto com `tools.view_image`.

Dois documentos/versões, filtros, coleções, etiquetas e pesquisa local presentes. Sincronizar visível; zero documentos selecionados mantém busca desabilitada. Sem resultados ou sincronização real exibidos.

### PDF-preview.configuracao-ferramenta.png

- SHA-256: `f0f07f1ea94c10ba3f1d1ed6541260c5248de1e5724b1a4da8fe894d175b338a`
- Dimensões: 1050 × 772; bytes: 88095.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.configuracao-ferramenta.png`
- Aberto com `tools.view_image`.

Marca d’água mostra preset, aviso de alterações não salvas, salvar cópia atual, entrada e opções de texto/imagem. Cancelar e executar ficam no rodapé; parâmetros inferiores requerem rolagem.

### PDF-preview.corrigir-acessibilidade.png

- SHA-256: `cd230eba4c7ec45d7dfacad414445e9d330d761d75caf27205e2a02575596873`
- Dimensões: 1050 × 752; bytes: 99631.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.corrigir-acessibilidade.png`
- Aberto com `tools.view_image`.

Árvore Document/Table/TR/TH/TD, TH selecionado, título, Alt, ActualText, idioma, cabeçalho, spans e salvar cópia visíveis. Aviso de que tags não certificam PDF/UA legível; não comprova ordem de leitura humana.

### PDF-preview.editor-conteudo.png

- SHA-256: `a5dd137cfdc16c5a47b5c269d807835c3a9bdd1a3546668d74a406462f283eb6`
- Dimensões: 1050 × 752; bytes: 115338.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.editor-conteudo.png`
- Aberto com `tools.view_image`.

Origem à esquerda com caixas selecionáveis; lista de objetos, operação de substituir, texto e fonte à direita. Exportar desabilitado com zero alterações; opções inferiores ficam na rolagem. Não mostra uma edição exportada.

### PDF-preview.escuro.png

- SHA-256: `94ef50b5eae0243083ad00f59f3b7a59e045099097a86af8ca60f542c7aa579e`
- Dimensões: 1050 × 772; bytes: 399127.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.escuro.png`
- Aberto com `tools.view_image`.

Tema escuro com destaque roxo, recuperação, recentes, grade, busca e contagem 71 legíveis. Sem corte anormal confirmado dos controles visíveis.

### PDF-preview.ferramentas.png

- SHA-256: `5cf2d8f68b5e42cf83bf7c8235a6dd8628b3201f016dbf3cc46fffbb61bdf5c6`
- Dimensões: 1050 × 752; bytes: 87759.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.ferramentas.png`
- Aberto com `tools.view_image`.

Categorias visíveis, busca e linhas com nome, visibilidade, ícone, alça e setas de ordem. Primeiro conjunto legível; lista continua por rolagem. Não comprova execução das 71 ferramentas.

### PDF-preview.fluxo-lote.png

- SHA-256: `7b58ff7ea4801595227f5212141d2c07d2c959f1a5cd56bd31dc8645d505ad0d`
- Dimensões: 1050 × 752; bytes: 105251.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.fluxo-lote.png`
- Aberto com `tools.view_image`.

Fluxo de três etapas, dois documentos, destino, dependências, salvar e adicionar etapa visíveis. Apenas as primeiras etapas cabem; etapa final e execução não estão no enquadramento. Barra de rolagem existe.

### PDF-preview.lado-a-lado.png

- SHA-256: `f9bf140109371164adaa988a0ce52f1bb324f7cffc97336b67b41c45119dc5dd`
- Dimensões: 1050 × 772; bytes: 138433.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.lado-a-lado.png`
- Aberto com `tools.view_image`.

Dois PDFs visíveis em painéis separados, com rótulos Principal/Tornar principal, fechamento e navegação do segundo painel. Texto reduzido pelo ajuste à largura, sem sobreposição confirmada.

### PDF-preview.leitor.png

- SHA-256: `8ff027aefee3ba7d343475457b5f7a82c4bbe589912b5ee714bf6e765623c491`
- Dimensões: 1050 × 772; bytes: 120849.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.leitor.png`
- Aberto com `tools.view_image`.

Página e miniaturas legíveis; busca, modos, zoom e Salvar cópia visíveis. A toolbar tem rolagem horizontal e nem todos os controles aparecem simultaneamente.

### PDF-preview.lista.png

- SHA-256: `7124ad2c0e5754d2e414f3a8efd47691c45ec6a73f351d6530f0183eea24eadd`
- Dimensões: 1050 × 772; bytes: 94729.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.lista.png`
- Aberto com `tools.view_image`.

Tema claro com destaque verde, navegação só por ícones e lista; nome personalizado Reunir meus documentos e favoritos visíveis. Contagem 71 e rolagem presentes.

### PDF-preview.menus.png

- SHA-256: `ce4fc7173edff119d1c41f4a86851cc045e8102bce9a4e798353ca755b2e9834`
- Dimensões: 1050 × 752; bytes: 80367.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.menus.png`
- Aberto com `tools.view_image`.

Acesso rápido editável, alças, setas, remoção e adicionar comando legíveis. Texto diferencia catálogo preservado e menus do sistema. Não há menu de barra aberto nem demonstração de arraste.

### PDF-preview.navegacao.png

- SHA-256: `a9396e2490149fb5cfdcc553d12b652aa8adfabc04952e228b942f76bcfa119f`
- Dimensões: 1050 × 752; bytes: 80150.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.navegacao.png`
- Aberto com `tools.view_image`.

Ícones/nomes, largura, renomeação, visibilidade, ícones e reordenação da navegação visíveis. Início indicado como acesso preservado. Não há controle importante sobreposto.

### PDF-preview.opcoes-leitura.png

- SHA-256: `ecee24a41fd1aad72b3e6cd4d4142d287954316491c36d451806f341e9aaab3f`
- Dimensões: 1050 × 752; bytes: 83941.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.opcoes-leitura.png`
- Aberto com `tools.view_image`.

Modo, direção, área, fundo, separação, ajuste/zoom, abas, leitura simultânea, miniaturas e barra de anotações visíveis; estilos inferiores continuam por rolagem.

### PDF-preview.paleta.png

- SHA-256: `d9122419794dc2ea167c7c2d68ddf69b4d09b0bfa8a63d1b8b995e1842e4f063`
- Dimensões: 1050 × 752; bytes: 63068.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.paleta.png`
- Aberto com `tools.view_image`.

Campo de busca focado, lista com ícones/atalhos e indicação de 93 comandos. Legível, mas teclado e execução de comandos não foram exercitados por esta revisão.

### PDF-preview.perfis.png

- SHA-256: `12e1789ee3a569602e4701bcf61f1b5f419b526f96ecfb27832f20ca5d3b5df0`
- Dimensões: 1050 × 752; bytes: 62720.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.perfis.png`
- Aberto com `tools.view_image`.

Nome de perfil e guardar ajustes atuais, texto sobre conteúdo preservado e importar/exportar/restaurar visíveis. Campo vazio deixa guardar desabilitado; não há perfil salvo nesta captura.

### PDF-preview.personalizar.png

- SHA-256: `9191514015309549dd74c2effaf15915a26a86a3304ec950679de795e4e832e5`
- Dimensões: 1050 × 752; bytes: 100235.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.personalizar.png`
- Aberto com `tools.view_image`.

Aparência possui presets, tema, cores, grade/lista, espaçamento, tamanhos e prévia; importar/exportar/restaurar visíveis. Opções inferiores continuam em área rolável.

### PDF-preview.png

- SHA-256: `94ad1dcda1b4b74ad31762a87f014974b79426c42f9a2e18a569e61f572d4813`
- Dimensões: 1050 × 772; bytes: 348695.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.png`
- Aberto com `tools.view_image`.

Início claro: 71 ferramentas informadas, grade de três colunas, pesquisa, categoria, Abrir documento, favoritos e Personalizar visíveis. Primeiros cartões legíveis; demais dependem de rolagem.

### PDF-preview.producao-bates.png

- SHA-256: `390e8ff9de2e46cc957200e4a94d724b1f092d976c8c6b6363261754563731a7`
- Dimensões: 1050 × 752; bytes: 64205.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.producao-bates.png`
- Aberto com `tools.view_image`.

Entrada, páginas, prefixo, início e dígitos legíveis; criar cópia desabilitado sem documento. Sem resultado de numeração mostrado.

### PDF-preview.producao-measure.png

- SHA-256: `f23a69b7cc88c88c1fa61ee98d593a62249682e0fb7d51e29a0bb23f37744aa2`
- Dimensões: 1050 × 752; bytes: 73628.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.producao-measure.png`
- Aberto com `tools.view_image`.

Entrada, página, escala, unidade, área e pontos visíveis; relatório desabilitado sem documento. Texto orienta conferir escala; não há medição concluída.

### PDF-preview.producao-pdfx.png

- SHA-256: `14ffab59b726bcfbe7dd5fc298b9c47c10b8e4d7d03e21845e1e1e1ea7abefc9`
- Dimensões: 1050 × 752; bytes: 75044.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.producao-pdfx.png`
- Aberto com `tools.view_image`.

Perfil ICC e condição de impressão visíveis, com cópia candidata PDF/X-3:2002 e limites de validação claramente descritos. Criar desabilitado sem documento/perfil; não demonstra certificação.

### PDF-preview.producao-print-preflight.png

- SHA-256: `c2630c2ec96c9249bfca7698b5be6b35f30cdabc19c0944cfa39dedd50448fb1`
- Dimensões: 1050 × 752; bytes: 73176.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.producao-print-preflight.png`
- Aberto com `tools.view_image`.

Entrada, senha, DPI e medir cobertura CMYK visíveis; gerar desabilitado sem documento. Texto distingue inspeções enumeradas de certificação ISO/prova física de cor.

### PDF-preview.recuperacao.png

- SHA-256: `aa980bea0b68cbb1b69d2b74bd8fce379c0ed6fc25adc1fe910c56c736965d4e`
- Dimensões: 1050 × 772; bytes: 68351.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.recuperacao.png`
- Aberto com `tools.view_image`.

Duas cópias locais listadas com recuperar/excluir e aviso sobre originais e senha. Caminhos longos truncados de forma esperada; não demonstra recuperação após falha.

### PDF-preview.revisao-ocr.png

- SHA-256: `119675073fc4f066dc21427429648e19f2e986f1c375aa089e66a0f9f13e34b4`
- Dimensões: 1050 × 752; bytes: 131586.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.revisao-ocr.png`
- Aberto com `tools.view_image`.

Imagem original com palavras/caixas e confiança, lista e campo de correção presentes. Idioma e análise estão em Inglês com tesseract sobre texto em português; não demonstra qualidade OCR em português. Parte inferior do editor está fora do enquadramento rolável.

### PDF-preview.solicitar-assinaturas.png

- SHA-256: `ed3153117498882bd7727936d2fecdfb724acd35c5af3aff4a8b4d92d057dafe`
- Dimensões: 1050 × 752; bytes: 99164.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.solicitar-assinaturas.png`
- Aberto com `tools.view_image`.

Conexão Dropbox Sign, chave, título/assunto, modo de teste e destinatário/coordenadas visíveis. Aviso de possíveis emails reais claro. Ações inferiores dependem de rolagem; sem envio/status real exibido.

### PDF-preview.validar-pdfa.png

- SHA-256: `9cf0bdcf82f346cbb0d9be66deb96101bd1e16cbae361352643b3bd1db8edd30`
- Dimensões: 1050 × 752; bytes: 62268.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.validar-pdfa.png`
- Aberto com `tools.view_image`.

veraPDF 1.30.3, perfil PDF/A-2b, documento e ação de validação legíveis. Captura é configuração, não relatório de conformidade.

### PDF-preview.verificar-assinaturas.png

- SHA-256: `9b97ce5fcbe08823e7d29ddc7917089eb14099ebd11e0429bc8d6c1f8c0309f7`
- Dimensões: 1050 × 752; bytes: 73581.
- Original: `/workspace/.cache/pdf-native-37f5b65/extracted/PDF-macOS-preview-macos-26/PDF-preview.verificar-assinaturas.png`
- Aberto com `tools.view_image`.

Entrada, raízes explícitas, opções OCSP/CRL e LTA e Validar/salvar relatório visíveis. Não há resultado ou cadeia real validada na captura.

## Limites gerais

- Capturas estáticas não exercitam cliques, foco, teclado, arraste, menus animados, efeitos dinâmicos, persistência ou navegação por VoiceOver.
- A contagem visível de 71 ferramentas não comprova a funcionalidade de cada ferramenta.
- Não há comprovação visual de todos os estados de erro, cancelamento, recuperação ou gravação.
- Não aprova a matriz inteira, o instalador nem o pacote final; a matriz estava em empacotamento quando esta revisão foi solicitada.
