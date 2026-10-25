# Revisão visual do binário instalado — cross macOS 27

**Resultado: aprovação visual pendente.** Todos os 33 PNGs originais foram abertos individualmente em detalhe `original`. Há um impedimento confirmado: os três ícones dos controles superiores no tema escuro ficam quase invisíveis sobre cápsulas quase brancas. Os demais estados não apresentaram novo bloqueio visual confirmado nos viewports vistos.

Fonte `37f5b65e35a9f70c716cfcd64db7ba69837f5c21` · nativo `40239018570` · cross `40243611339` · tentativa `1` · job `121320462461`.
Controlador `e4f6c056058d3482b18cdcc24011ccdc96327004` · tar instalado SHA-256 `641d66d3c4bd68ad8074d906e6dd9c3c18ef946292da2d9512541948db52c4a4`.
Artefato GUI `12618361902` · 3421238 bytes · SHA-256 `196e62ea761dd6291a5c14e2db6c36bffee467c2dd3002655ecd9e93e552d665`.
Lifecycle separado `12617224816` · SHA-256 `9f842412e7022e076ce9c438cbf879207ad2274a01debe1642fd484c890c4e17`.

O coletor autenticou 50 arquivos GUI (33 PNG, 7 AX, 2 OCR e controles) e 3 lifecycle; os gates nativos/cross e os recibos passaram. Essa autenticação não é aprovação visual. O binário macOS 26 foi instalado sem recompilar no macOS 27.0.1, Apple M1 (Virtual), segundo a evidência autenticada.

## Achado confirmado

**CROSS-DARK-TOOLBAR-CONTRAST — Ícones dos controles superiores quase invisíveis no tema escuro.** Em `PDF-preview.escuro.png`, SHA-256 `13dcfebf3a4ec930d6ee42360004ec4da89072da1d2b0e39a64249ad9aa0387a`, os símbolos de barra lateral, paleta e personalização são praticamente ilegíveis. Regiões aproximadas, origem superior esquerda: x166–202/y8–45 e x968–1043/y8–45. O restante do conteúdo escuro permanece legível.

O achado é visual; não prova que os cliques falhem. Causa, permanência após transição e eventual relação com o SDK não foram demonstradas. Investigar e produzir nova evidência autenticada antes de uma aprovação visual sem ressalvas. Os originais desta execução devem permanecer preservados.

**OCR:** a tela e o JSON desta execução mostram `informag6es`, confiança `0.37141106`, sobre um exemplo em português reconhecido em inglês por Tesseract. A presença de revisão manual não aprova a precisão do reconhecimento.

## Limites

- Todos os 33 PNGs deste artefato cross foram abertos individualmente por view_image em detalhe original, inclusive quando seus bytes coincidem com capturas nativas anteriores.
- A revisão visual por agente é independente dos gates automatizados aprovados. O sucesso de instalação, isolamento, GUI e lifecycle não elimina a falha visual confirmada.
- As capturas pertencem ao mesmo tar macOS 26 instalado em macOS 27.0.1, sem recompilar, conforme os recibos autenticados. Esta revisão não recompilou, reinstalou ou executou o aplicativo.
- Foram vistos apenas viewports de 1050×752 e 1050×772. Barras horizontais no leitor e rolagem em telas densas deixam controles fora da captura; seu acionamento não foi exercitado.
- Não houve cliques, rolagem, arraste, edição de atalhos, observação temporal de animações ou avaliação humana com VoiceOver nesta revisão.
- O baixo contraste da barra superior escura está confirmado na imagem; a causa, duração após a transição, correção e eventual impacto funcional ainda não estão estabelecidos.
- O erro OCR informag6es é real e confirmado no JSON desta execução. O exemplo português usou Tesseract em inglês, 200 DPI e página automática; precisão global e documentos difíceis não foram aprovados.
- A presença de 71 ferramentas e 93 comandos na interface não comprova execução completa, fidelidade de conversões, edição irrestrita ou qualidade de IA.
- Assinaturas/certificados de produção, serviços externos, scanner, sincronização entre Macs, Atalhos, impressão física e conformidade universal PDF/A/UA/X não foram exercitados por esta inspeção.
- O relatório cross identifica Apple M1 (Virtual), 3 CPUs, não M4 físico. Não há aqui medição de GPU, Neural Engine ou energia.
- Nenhum arquivo do produto/repositório ou original de evidência foi editado. Não houve rede, execução de coletor ou publicação nesta revisão.

## Registro individual

| PNG original | Dimensões | Constatação | Limite específico |
| --- | --- | --- | --- |
| `PDF-preview.abas.png` | 1050×772 | Dois documentos em abas, Referência de revisão ativa, página correspondente renderizada. | Captura não comprova preservação de posição/zoom durante alternância ou fechamento. |
| `PDF-preview.anotacoes.png` | 1050×772 | Nota selecionada na página e no painel, texto, cor, posição, dimensão, Aplicar alterações e Desfazer visíveis. | Painel e barra horizontal têm rolagem; alças, movimento, redimensionamento e gravação não são demonstrados pela imagem. |
| `PDF-preview.arquivos.png` | 1050×752 | Modelo de nomes, nome alternativo, destino e cópias locais visíveis; rodapé identifica Apple Paravirtual device, 3 núcleos, 7 GB. | Este ambiente virtual não constitui medição em M4 físico, GPU, Neural Engine ou energia. |
| `PDF-preview.assinatura-digital.png` | 1050×752 | Documento escolhido, certificado local, PIN, motivo/local, campo e perfil PAdES B-B visíveis; salvar desativado sem certificado. | Nenhum certificado selecionado ou assinatura produzida; produção, revogação e preservação temporal não são validadas pela captura. |
| `PDF-preview.atalhos.png` | 1050×752 | Busca de ações e atalhos para paleta, abrir, nova aba, fechar, salvar e imprimir, com Editar por linha. | A lista é rolável; edição, conflitos e atalhos de teclado não foram executados nesta revisão. |
| `PDF-preview.auditar-pdfua.png` | 1050×752 | Perfil PDF/UA-1 e ação de relatório; texto explica tags e necessidade de revisão humana. | Nenhum resultado PDF/UA nem auditoria humana com VoiceOver; o estado não aprova acessibilidade completa. |
| `PDF-preview.automacao.png` | 1050×752 | Formulário de pasta monitorada, seleção de fluxo e diretórios, estado sem regra ativa e instruções dos Serviços do Finder. | Nenhum fluxo salvo ou pasta ativa nesta captura; Atalhos, App Intents e disparo do Finder não foram exercitados. |
| `PDF-preview.biblioteca.png` | 1050×752 | Dois documentos, duas versões, filtros, coleções, etiquetas, pesquisa e sincronização visíveis; zero selecionados. | Busca nas fontes desativada no estado sem consulta/seleção; resultados, versões históricas e sincronização entre Macs não aparecem. |
| `PDF-preview.configuracao-ferramenta.png` | 1050×772 | Marca d’água com presets, aviso de alterações não salvas, salvar e usar cópia, seleção de arquivo, texto/imagem e tipografia. | Aviso distingue versão atual e arquivo de entrada vazio. Demais parâmetros estão abaixo da rolagem; resultado não aparece. |
| `PDF-preview.corrigir-acessibilidade.png` | 1050×752 | Árvore Document/Table/TR/TH/TD; título, texto alternativo, ActualText, idioma, escopo Coluna e extensão 1×2 legíveis. | A interface declara que tags não certificam PDF/UA. Exportação, reconstrução geral e leitura humana com VoiceOver não foram exercitadas. |
| `PDF-preview.editor-conteudo.png` | 1050×752 | Página com caixas de seleção de objetos; lista e campo do trecho original, operação Substituir texto e tamanho de fonte visíveis. | Há 0 alterações preparadas; controles inferiores e resultados de edição/exportação não aparecem; limites de objetos incompatíveis são declarados. |
| `PDF-preview.escuro.png` | 1050×772 | Falha visível: os três ícones dos controles superiores (barra lateral, paleta e personalização) têm cor quase branca sobre cápsulas quase brancas no tema escuro e ficam praticamente ilegíveis. O conteúdo principal do início permanece legível. | A captura prova o baixo contraste neste estado; não prova a causa, sua permanência após animação, nem falha dos cliques. A aprovação visual sem ressalvas depende de correção/explicação e nova evidência autenticada. |
| `PDF-preview.ferramentas.png` | 1050×752 | Categorias, pesquisa, visibilidade, nomes, ícones, alças de arraste e setas de ordem aparecem alinhados. | Última linha parcial no limite da área rolável; demais ferramentas e reordenação não foram acionadas. |
| `PDF-preview.fluxo-lote.png` | 1050×752 | Dois documentos selecionados, destino vazio, três etapas e controles das primeiras etapas de rotação e numeração visíveis. | Etapa final e execução ficam abaixo do viewport; nenhum resultado de lote ou conversão é mostrado. |
| `PDF-preview.lado-a-lado.png` | 1050×772 | Documentos distintos exibidos simultaneamente, identificação principal, Tornar principal, fechar secundário e controles de página. | Textos pequenos decorrem da escala ajustada e das duas colunas; sincronização de navegação e zoom não foi exercitada. |
| `PDF-preview.leitor.png` | 1050×772 | PDF renderizado, aba, miniaturas, páginas/sumário/marcas, busca, anotações e salvar cópia visíveis. | Barra de ferramentas horizontalmente rolável contém controles fora do viewport; página também rolável. |
| `PDF-preview.lista.png` | 1050×772 | Lista com destaque verde e barra lateral compacta; nomes personalizados e favoritos visíveis. | As linhas restantes estão abaixo do viewport; nenhum arraste ou clique foi exercitado nesta revisão. |
| `PDF-preview.menus.png` | 1050×752 | Acesso rápido editável com cinco entradas, remover, mover e adicionar comando; rótulos legíveis sem sobreposição. | As outras seções estão abaixo da rolagem; a captura não mostra menus macOS abertos nem personalização irrestrita. |
| `PDF-preview.navegacao.png` | 1050×752 | Largura, ícones/nomes, edição dos nomes e controles de ordem das seis seções visíveis. | O texto informa que Início continua disponível; persistência e arraste não foram testados por esta captura. |
| `PDF-preview.opcoes-leitura.png` | 1050×752 | Modo, direção, área da página, fundo, zoom, abas, leitura lado a lado, miniaturas e anotações visíveis. | Estilo de anotações continua abaixo do viewport; aplicação dos ajustes e persistência por aba não são provadas aqui. |
| `PDF-preview.paleta.png` | 1050×752 | Campo focado, Fechar, lista de comandos e indicação de 93 comandos; seleção inicial visível. | Não comprova teclado, execução de comando ou disponibilidade operacional de cada entrada. |
| `PDF-preview.perfis.png` | 1050×752 | Nome de perfil vazio, instrução de escopo e Guardar ajustes atuais desativado coerentemente com o estado vazio. | Não aparece perfil salvo nem aplicação/importação/exportação de perfil. |
| `PDF-preview.personalizar.png` | 1050×752 | Aparência: temas, cor, grade/lista, espaçamento, tamanhos de cartões/texto/ícones e prévia visíveis. | Há opções abaixo da rolagem; imagem estática não comprova resposta imediata, animação ou Liquid Glass em movimento. |
| `PDF-preview.png` | 1050×772 | Início em grade clara: navegação, pesquisa, categoria, favoritos e Personalizar visíveis; indicador de 71 ferramentas. | A grade continua abaixo da janela; o indicador não demonstra execução de 71 ferramentas. |
| `PDF-preview.producao-bates.png` | 1050×752 | Entrada, páginas, prefixo DOC-, número inicial e dígitos visíveis; criar cópia desativado sem documento. | Nenhuma saída numerada ou conjunto jurídico final aparece. |
| `PDF-preview.producao-measure.png` | 1050×752 | Escala 1:100, unidade metros, pontos X/Y, fechar polígono e adicionar ponto legíveis. | Sem documento ou relatório; precisão geométrica e interação na planta não são provadas. |
| `PDF-preview.producao-pdfx.png` | 1050×752 | Entrada, perfil ICC CMYK e condição de impressão; texto qualifica PDF/X-3 como cópia candidata e não certificação ISO completa. | Nenhum arquivo, perfil ou resultado; conformidade completa e prova física de cor não são demonstradas. |
| `PDF-preview.producao-print-preflight.png` | 1050×752 | Resolução mínima 200 DPI, opção de cobertura CMYK e descrição das verificações de impressão visíveis. | Não há relatório executado; interface distingue cobertura técnica de certificação ISO e prova física. |
| `PDF-preview.recuperacao.png` | 1050×772 | Duas cópias locais listadas com Recuperar/excluir e proteção dos originais explicada; caminhos longos usam reticências. | Não prova recuperação após encerramento, disco cheio, atualização interrompida ou cobertura de todas as gravações. |
| `PDF-preview.revisao-ocr.png` | 1050×752 | Imagem original com caixas de palavras e lista de confiança; idioma Inglês, Página automática, motor tesseract e 0 correções. | O texto reconhecido contém informag6es; erro confirmado no JSON original. Editor e ações inferiores exigem rolagem; nenhuma precisão global é aprovada. |
| `PDF-preview.solicitar-assinaturas.png` | 1050×752 | Integração Dropbox Sign, campo de chave vazio, dados da solicitação e destinatário, modo de teste e aviso sobre emails reais visíveis. | Ações finais estão abaixo do viewport; nenhum envio, retorno do serviço, participante ou credencial de produção foi usado. |
| `PDF-preview.validar-pdfa.png` | 1050×752 | Documento, veraPDF 1.30.3, perfil PDF/A-2b e ação de relatório visíveis. | Nenhum relatório de conformidade PDF/A aparece; presença da opção não comprova conformidade do documento. |
| `PDF-preview.verificar-assinaturas.png` | 1050×752 | Raízes explícitas, exigência OCSP/CRL, avaliação AdES-LTA e Validar e salvar relatório visíveis. | Não há resultado de integridade, confiança, revogação ou validade temporal nesta imagem. |

## Identidade dos 33 originais

| PNG original | Bytes | SHA-256 |
| --- | ---: | --- |
| `PDF-preview.abas.png` | 118946 | `742d86b366e43d12513c7baf2d53764758f6fccac6cac0cce972fc0d2ac6c26d` |
| `PDF-preview.anotacoes.png` | 150949 | `2f1e7f271215995a083b1b77d680431656d45f3d6b009cadc00483c76e671698` |
| `PDF-preview.arquivos.png` | 78391 | `1fe95b2fbb936bbf24c1f7dda1cad8f098abd239f8834d408260c855185aaa53` |
| `PDF-preview.assinatura-digital.png` | 86312 | `41d776a0e1eea2049473ce9e1a59c27c3c83f10572d5385f008ffb2ee907f1ee` |
| `PDF-preview.atalhos.png` | 76686 | `33de89ef91ae965ea071278595d4543ecc7e8699eeec8707764d8a19befcf47d` |
| `PDF-preview.auditar-pdfua.png` | 71581 | `558d2d4faabc7d63c747c39dba3d08bf7d9ec1d1d570d69ae3797451bfa88418` |
| `PDF-preview.automacao.png` | 96109 | `d982da2f8bef486366b179cdf72e8a837077a42f762a498d234980120b38810d` |
| `PDF-preview.biblioteca.png` | 114493 | `915b488aea5399fd201ab9108f86a3ccb14e41adbed4de98b01c265c13d44f6c` |
| `PDF-preview.configuracao-ferramenta.png` | 89948 | `6d40c4d28c6aaebb536185a128f753d2b0283f9f10d2f69bb305363faab2eba7` |
| `PDF-preview.corrigir-acessibilidade.png` | 101757 | `2b6f50e8b74b852ccc3ffe2dd8dab54658cba47a8719a6ca6bf49b7f17c05d43` |
| `PDF-preview.editor-conteudo.png` | 117571 | `c634aa93ad5057bfcc3fdd25321bc2d41875341df805387283ed0f190b85d553` |
| `PDF-preview.escuro.png` | 401682 | `13dcfebf3a4ec930d6ee42360004ec4da89072da1d2b0e39a64249ad9aa0387a` |
| `PDF-preview.ferramentas.png` | 88831 | `380ee81e25e8eabeb86018501c18ed6758b9fe7d947a9fafa3402d451ef6952f` |
| `PDF-preview.fluxo-lote.png` | 107998 | `650340456b3cfa3db6d944bbff4ca8920e2ba73a413f5c723f80c31140265735` |
| `PDF-preview.lado-a-lado.png` | 132768 | `ed057d791cb057fc1ef0babe74077534e7d04cd0aa879fd1b5ec2d66eb05f3e1` |
| `PDF-preview.leitor.png` | 116420 | `e4370cf74e1903096bcf6617ca3f5bcb4127f0656fa5db7921c72a7ece16a4c8` |
| `PDF-preview.lista.png` | 92678 | `c791cd5473f473a1b15a9c9bebe12e5992bd726e524420c15b552634a37dda86` |
| `PDF-preview.menus.png` | 81214 | `64ffd68aab12f7b517332186f698d76d7a6394427a33d3be30c7f069619156e9` |
| `PDF-preview.navegacao.png` | 81084 | `e7f314deee4f5513754776080e01c7a0156a679f97b19755e2f0848e48ed8125` |
| `PDF-preview.opcoes-leitura.png` | 86373 | `488267bd9fd20767f073a661df4ee82378238c0fa584544c4b8f405a2e7891cf` |
| `PDF-preview.paleta.png` | 64705 | `5437e2d1415a3e6a8f0cd38c342297988b0542ade5180afa11786bf0a4d4984b` |
| `PDF-preview.perfis.png` | 63822 | `257a0f5ca24461dc50ec328b6e05708375d7bb5b3ff8963a41cb49cd1b8f8951` |
| `PDF-preview.personalizar.png` | 101366 | `9243600812fb7d0cb93863ed091667a5ea0fdd8f78f0fb4dadb724f70e28a7c3` |
| `PDF-preview.png` | 348641 | `a5b4ea22f66d719e08410a5461997a345be099ee16b07e93454314cac6d2290b` |
| `PDF-preview.producao-bates.png` | 66392 | `99033a2ebc8baabff9be273bf0cb1a20587a992fa5d7f42f5cacd096da42aa0f` |
| `PDF-preview.producao-measure.png` | 76071 | `0b47ae5daee684ac4ba89266a9c1d2793b40ac4ccb9916404831d8803ea578ae` |
| `PDF-preview.producao-pdfx.png` | 76823 | `ba4ec748dd463dc10fcebc8fdfe43c829a2b78719d6ef0cefe2b6edd3bdd306c` |
| `PDF-preview.producao-print-preflight.png` | 75282 | `700e0df373f5a1527fdcf11078083bb45805acdfc96fbccc36d1b172f5584e3a` |
| `PDF-preview.recuperacao.png` | 69350 | `0826f969ce7b6cdb66191ffbd3e6aa2ab12809d36ac042e2c7ced94544763e55` |
| `PDF-preview.revisao-ocr.png` | 133312 | `7100cb98cb37df40c7b3e5f1858d06e6c2715241920b8ce487102b2cd8d89207` |
| `PDF-preview.solicitar-assinaturas.png` | 100763 | `39b49577ce7afee91ca010df1da0509f737b9327251da78705d677cbcba514e5` |
| `PDF-preview.validar-pdfa.png` | 64131 | `83419a5ec567aa0a93c564c6636bb89c6c657979ed0a0d9596ecb8d22827bb53` |
| `PDF-preview.verificar-assinaturas.png` | 74744 | `6acc1acea3bec3afabc600416eb263e28054e709053f4edc26a3b51b4afcdd17` |
