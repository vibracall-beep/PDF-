# Auditoria independente das ferramentas e dos requisitos

Data: 23/10/2026. Escopo: as 50 funções de `REQUISITOS.md`, representadas por 49 cartões e pelo leitor permanente, seus caminhos Swift e Python, instalação e evidências de validação. Uma entrada no catálogo não constitui implementação nem aprovação funcional.

Esta auditoria abriu o código dos caminhos de execução, reabriu saídas de fixtures reais e acrescentou regressões adversariais em `tests/test_audit.py`. A execução local é Linux x86_64. As evidências anteriores do macOS estão identificadas em `VALIDACAO.md`; a aprovação daquele commit não aprova alterações posteriores.

## Critérios

- **Verificado em amostra:** existe execução funcional com as propriedades indicadas conferidas na saída; não significa fidelidade universal.
- **Parcial:** existe implementação, mas uma parte expressa do requisito não é atendida ou permanece aproximada.
- **Dependente:** a função precisa de equipamento, aplicativo, modelo ou serviço não exercitado nesta auditoria.
- **Falha reproduzida:** um caso concreto gera comportamento incorreto. A lista de achados registra a correção e a repetição do teste separadamente.

Os testes `test_engine`, `test_advanced`, `test_layout`, `test_new_tools` e `test_audit` exercitam o motor; `integration_optional` executa conversores externos reais. `MacSmokeTests.swift` contém verificações nativas. Testes de disponibilidade e validação estrutural de JSON não demonstram qualidade de respostas geradas por IA, operação de scanner físico ou exportação real pelo Pages.

## Matriz das 50 funções

| Nº | Função / cartão | Caminho que executa o trabalho | Evidência e alcance efetivo |
|---|---|---|---|
| 1 | Juntar / `merge` | Seleção ordenável → `merge` → PyMuPDF `insert_pdf` | Ordem e contagem verificadas; segundo arquivo inválido não publica resultado parcial; proteção de entrada preservada. |
| 2 | Dividir / `split` | Intervalos ou grupos → `split` | Grupos `1-2;4,3`, páginas isoladas e proteção verificados. Saída é um diretório novo. |
| 3 | Comprimir / `compress` | Otimização de objetos; redução opcional de imagens | Compressão é real; tamanho depende do documento. Auditoria do motor verifica seleção e imagens compartilhadas. Não existe promessa demonstrada de melhor compressão do mercado. |
| 4 | PDF → Word / `word` | Extração de blocos, imagens e tabelas → python-docx | Texto editável e tabela detectada verificados. **Parcial:** fluxo de parágrafos reconstruído; não preserva universalmente colunas, geometria, fontes ou objetos do original. |
| 5 | PDF → PowerPoint / `powerpoint` | Blocos editáveis ou página raster → python-pptx | Objetos de texto editáveis e modo imagem verificados. **Parcial:** formas vetoriais não são reconstruídas no modo editável; fontes e dimensões de páginas distintas são aproximadas. Caso de página rotacionada incluído na auditoria. |
| 6 | PDF → Excel / `excel` | Detecção de tabelas; linhas como alternativa → openpyxl | Conteúdo tabular e prevenção de fórmulas executáveis verificados. **Parcial:** uma imagem de tabela precisa de OCR prévio; sem tabela detectada, linhas viram células, não colunas semanticamente recuperadas. |
| 7 | Word → PDF / `word-pdf` | `office` → LibreOffice | Conversão DOCX real exercitada. DOC legado e documentos complexos dependem da compatibilidade do LibreOffice e de fontes instaladas; equivalência visual perfeita não foi demonstrada. |
| 8 | PowerPoint → PDF / `powerpoint-pdf` | `office` → LibreOffice | PPTX real convertido e texto conferido. Animações não se tornam animações em PDF; fidelidade de todos os arquivos PPT/PPTX não demonstrada. |
| 9 | Excel → PDF / `excel-pdf` | `office` → ajuste de XLSX → LibreOffice | Planilha com 30 colunas, ajuste à largura e paisagem verificados, com origem intacta. Ajuste programático de XLS legado não tem a mesma cobertura do XLSX. |
| 10 | Editar / `edit` | Adicionar/substituir texto, imagem, forma; desenho no leitor | Texto português, substituição, imagem e forma verificados; overflow recusa publicação. **Parcial:** não é editor universal de objetos PDF nem de todas as fontes; teste adversarial exige Unicode correto ou recusa explícita. |
| 11 | PDF → JPG / `jpg` | Raster de páginas ou extração de imagens incorporadas | Resolução, extração e deduplicação de imagem compartilhada verificadas. JPEG não conserva transparência. |
| 12 | JPG → PDF / `images` | Conversão de imagens e composição no papel escolhido | A4/paisagem/margens verificados. A interface agora esclarece que é preciso escolher papel para configurar margem/orientação; tamanho original mantém dimensões da imagem. |
| 13 | Assinar / `signature` | Inserção de imagem; preparação de mensagem pelo compartilhamento do macOS | Assinatura visual implementada. **Parcial:** não cria assinatura criptográfica certificada nem acompanha uma transação de assinatura; envio depende da ação do usuário no serviço de e-mail. |
| 14 | Marca d’água / `watermark` | Sobreposição de texto ou imagem | Texto, imagem, opacidade e posição têm parâmetros reais. Unicode fora das fontes disponíveis está coberto pela auditoria de fidelidade. |
| 15 | Rodar / `rotate` | Rotação de páginas; lote via `executeBatch` | Seleção de página e ângulos verificados no motor. Cópias repetidas precisam permanecer independentes em edições posteriores; teste adversarial incluído. |
| 16 | HTML → PDF / `html` | Playwright/Chromium, URL HTTP(S) ou HTML local | Renderização de HTML real exercitada. Página remota depende da rede e de autenticação/conteúdo do site; recursos relativos de HTML local têm limites explicitados na API. |
| 17 | Desbloquear / `unlock` | Autenticação → nova cópia sem criptografia | Senha correta, senha errada, não publicação e não divulgação da senha nos erros verificados. Não recupera nem adivinha senha desconhecida. |
| 18 | Proteger / `protect` | AES-256 com senha de usuário e proprietário aleatório | Reabertura/autenticação, senha errada e preservação em operações subsequentes verificadas. Controle é documental; não existe criptografia por página. |
| 19 | Organizar / `organize` | Vários PDFs em sequência → seleção global de páginas | Incorporação de páginas de outros documentos, ordem global, omissão/repetição e proteção verificadas em teste do motor. Interface oferece múltiplas entradas e explica a numeração global; independência das cópias também foi auditada. |
| 20 | PDF/A / `pdfa` | OCRmyPDF/Ghostscript | Conversão externa executada; PDF criptografado é recusado. **Dependente de validação:** geração e metadados PDF/A não substituem relatório de conformidade ISO por validador independente. |
| 21 | Reparar / `repair` | Abertura/regravação por MuPDF | Regravação de PDF legível verificada. **Parcial:** não há reconstrução de bytes ausentes nem teste que demonstre recuperação de toda corrupção; erro irrecuperável deve recusar saída. |
| 22 | Números / `numbers` | Texto com posição/fonte/cor/formato/início | Geração funcional e intervalo verificados. Total refere-se ao conjunto selecionado, conforme API. |
| 23 | Digitalizar / `scan` | ImageCaptureCore/IKScannerDeviceView; Continuity Camera; importação | Importação, criação de PDF e rejeição de páginas protegidas têm smoke tests nativos. **Dependente:** scanner físico e iPhone/Continuity não foram exercitados no runner. |
| 24 | OCR / `ocr` | OCRmyPDF/Tesseract ou Vision no fluxo nativo | OCR externo real e OCR Vision sobre imagem sem texto têm evidência. Precisão universal, idiomas e desempenho dependem da imagem/modelos instalados. |
| 25 | Comparar / `compare` | Texto diff ou HTML com original/comparação/diferença | Mudança exclusivamente gráfica verificada. Auditoria inclui página branca adicionada e mudança de dimensão, que também devem constar como alteração. HTML compara a 96 DPI, sem garantia de identificar qualquer alteração subpixel. |
| 26 | Ocultar / `redact` | Redação de conteúdo por texto ou retângulos; limpeza de metadados/anexos | Conteúdo, metadados XML e anexos têm testes. Falha grave de anotações/widgets internos à área removida foi reproduzida, corrigida e testada novamente nesta auditoria; ver A01. |
| 27 | Recortar / `crop` | CropBox por margem ou retângulo | Margens e retângulos são suportados pelo motor. Auditoria inclui CropBox deslocado e quatro rotações. O recorte altera visibilidade; não elimina o conteúdo oculto. |
| 28 | Formulários / `forms` | Detectar → revisar → criar; preencher; JSON de inspeção | Texto, checkbox, combo, lista distinta e grupo de escolha exclusiva entre páginas verificados no motor, incluindo limpar seleção e recusar valor inválido/campo somente leitura. **Parcial:** detecção é heurística de caixas/linhas vetoriais, não inferência universal em scans; texto de formulário fora de Latin-1 é recusado quando não há aparência tipográfica compatível. |
| 29 | Resumir / `summary` | Foundation Models local, divisão por contexto | Divisão de texto e exportação PDF têm testes nativos. **Dependente:** respostas reais do modelo, cobertura factual e qualidade do resumo não foram demonstradas por testes estruturais. |
| 30 | Traduzir / `translate` | Foundation Models → texto ou `translate-layout` | Motor preserva imagens/vetores, rejeita sobreposição, bloco original alterado e overflow; texto Unicode testado. **Parcial:** inserção usa tipografia substituta; não garante preservar a fonte e toda a formatação como solicitado. Geração real depende do modelo disponível. |
| 31 | Markdown / `markdown` | Blocos/tabelas/imagens/links → Markdown | Tabela real e exportação de texto verificadas. **Parcial:** títulos são inferidos por tamanho de fonte; listas, ordem de leitura e semântica de qualquer PDF não têm preservação universal demonstrada. |
| 32 | Fluxos / `workflow` | Editor de etapas, biblioteca JSON, motor transacional | Etapas reais, falha intermediária sem resultado parcial e proteção têm testes. **Parcial:** UI oferece subconjunto das ferramentas, com PDF único intermediário/final; não permite qualquer combinação arbitrária das 49 opções. |
| 33 | Conversor / `converter` | Navegação para categoria Converter | É acesso unificado aos conversores reais acima; não é outro motor de conversão. Rota conferida no código. |
| 34 | PDF → PNG / `png` | Raster RGBA/opaco ou imagem incorporada com máscara | Dimensões, transparência e reconstrução de soft mask verificadas por pixels. |
| 35 | ODT → PDF / `odt-pdf` | `odt` → LibreOffice | ODT real com texto português convertido e conferido. Fontes, objetos e layouts complexos continuam dependentes do conversor. |
| 36 | TXT → PDF / `txt-pdf` | Story Unicode, paginação, codificação selecionável | Português/Unicode, múltiplas páginas, última linha, token de 5.000 caracteres e erro de codificação verificados. |
| 37 | RTF → PDF / `rtf-pdf` | `rtf` → LibreOffice | RTF real com escapes Unicode convertido; texto português conferido. |
| 38 | EPUB → PDF / `epub-pdf` | MuPDF reflow, papel/margens/fonte | EPUB real com navegação/manifesto convertido e conteúdo conferido; ligaturas normalizadas na comparação textual. DRM não é removido. |
| 39 | CSV → PDF / `csv-pdf` | Parser CSV → XLSX seguro → LibreOffice | Célula entre aspas com vírgula, célula longa/multilinha, texto semelhante a fórmula e recusa de altura impossível verificados. |
| 40 | Pages → PDF / `pages-pdf` | Cópia privada → AppleScript → Pages → publicação nativa | Código contém cópia isolada, timeout, cancelamento e verificação da saída. **Dependente:** exportação real requer Pages instalado e permissão de Automação; smoke test de cópia não comprova exportação do aplicativo Pages. |
| 41 | Excluir / `delete-pages` | Seleção inversa de páginas | Ordem restante, recusa de todas/inválidas/sem seleção e preservação de criptografia verificadas. |
| 42 | Extrair / `extract-pages` | Nova seleção na ordem pedida | Ordem, duplicatas e proteção verificadas; auditoria testa independência de cópias depois de alterações. |
| 43 | Anotador / `annotate` | Abre leitor com barra de anotações | Realce, nota e desenho livres implementados; persistência tem smoke tests. Os ajustes de cor e espessura estão sendo ampliados na revisão da interface; sua execução depende da verificação nativa final. |
| 44 | Leitor permanente | PDFKit/PDFView, miniaturas, sumário, busca, zoom, marcas, impressão | Busca, renderização, anotação/formulário e salvamento têm smoke tests e captura real anterior. Navegação e proteção contra perder alterações existem. Não há benchmark de grandes PDFs ou avaliação completa de acessibilidade que sustente superioridade ao mercado. |
| 45 | Preencher / `fill-forms` | `form-fill` e edição direta PDFKit | Valores e checkbox verdadeiro/falso, gravação e reabertura verificados. Tipos avançados de formulário precisam de casos adicionais; não executa uma suíte de compatibilidade de XFA/JavaScript PDF. |
| 46 | Compartilhar / `share` | ShareLink/serviços do macOS | Arquivo salvo é explicitamente selecionado; alterações não salvas exigem salvar cópia. **Dependente:** envio efetivo varia conforme o serviço escolhido pelo usuário; nenhum envio externo foi simulado como concluído. |
| 47 | Sign.com / `sign-service` | Link para o site externo | **Parcial:** abre o serviço indicado, identifica conta/custo e não faz upload automático. Não implementa API, autenticação, coleta de assinatura ou acompanhamento dentro de PDF. |
| 48 | Achatar / `flatten` | PyMuPDF bake de anotações e/ou widgets | Aparência comparada por pixels, texto mantido, remoção das estruturas interativas e proteção verificados. Operação de documento inteiro. |
| 49 | Chat / `chat` | Extração local, recuperação lexical limitada e Foundation Models | Recuperação e identificação das páginas têm testes estruturais. **Dependente:** respostas factuais reais, prompt injection documental e qualidade de citações não foram avaliadas com modelo em execução. |
| 50 | Questões / `quiz` | Foundation Models → JSON validado → UI/exportação | Quantidade/estrutura de alternativas, gabarito e referências têm validação. **Dependente:** correção pedagógica/factual e dificuldade solicitada não são demonstradas só por JSON válido. |

## Achados adversariais e de interface

Gravidade **alta** indica vazamento de informação, alteração não solicitada de páginas ou perda silenciosa de conteúdo. **Média** indica resultado enganoso, campo sem efeito ou desvio importante de requisito. Os achados são acompanhados por reprodução, e não por inferência a partir do nome de uma ferramenta.

| ID | Gravidade | Reprodução / impacto observado | Acompanhamento |
|---|---|---|---|
| A01 | Alta | Redação da área `[30,30,310,210]` removia texto, mas mantinha `SECRET-781` em nota e widget internos; `get_text()` ainda retornava o segredo. | Corrigido e regressão aprovada: widget/nota internos removidos; widget público externo e página não selecionada preservados. |
| A02 | Alta | Adicionar `ação Ω 世界` publicava `ação · ··`; substituir por `你好` publicava `??`. | Corrigido com composição Unicode e verificação de área; regressões aprovadas exigem preservação ou recusa explícita antes de publicar. |
| A03 | Alta | `organize`/`extract-pages` com `1,1`, seguido de girar ou ocultar só página 1, alterava ambas as cópias. | Corrigido e regressões aprovadas: cópia não selecionada preservada após rotação e redação. |
| A04 | Média | Página com CropBox `(100,120,500,700)` recortada por `[10,20,300,400]` passava a CropBox `(10,20,300,400)`, em vez de `(110,140,400,520)`. | Corrigido e regressão aprovada nas quatro rotações. |
| A05 | Média | JSON de opções `[]`, `false`, `0` e `""` era aceito como `{}` e executava a operação padrão. | Corrigido; quatro entradas recusadas pela CLI com erro estruturado e sem saída. |
| A06 | Média | Comparação visual de 1 com 2 páginas brancas dizia que a página acrescentada era igual; mudança de tamanho de página branca também era igual. | Corrigido; regressões de presença e dimensão de página aprovadas. |
| A07 | Alta | PDF 500×650 girado 90°, texto em y=600: PPTX editável colocava textbox além da altura do slide. | Corrigido; teste de cantos após rotação aprovado. Exportação real do PPTX pelo LibreOffice preservou todo o texto dentro da página PDF. |
| A08 | Média | Interface de JPG→PDF apresentava margem/orientação no tamanho original, mas só transmitia esses valores se o papel fosse A4/Carta. | Corrigido por revisão estática: controles aparecem somente com papel definido, e explicação orienta a escolha; teste de interface nativa final pendente. |
| A09 | Média | Seleção de páginas exposta em operações documentais (OCR/PDF-A, proteger/desbloquear/reparar), mas ignorada; substituir texto mostrava posição/margem/opacidade sem aplicá-las. | Corrigido por revisão estática: allowlist de operações com seleção de página; edição direta mostra fonte/tamanho/cor, os controles que aplica. |
| A10 | Média | Comparação tinha apenas uma senha na UI apesar de o motor suportar `second_password`; documentos com senhas diferentes não podiam ser comparados pelo formulário. | Corrigido por revisão estática: campo da segunda senha é transmitido como `second_password`. |
| A11 | Média | UI de recorte oferecia somente margem, não o retângulo do requisito/API; organização não incorporava diretamente páginas de outros documentos. | Corrigidos: área envia `rect`; organização oferece múltiplos arquivos e seleção global, com teste funcional de conteúdo/ordem/proteção aprovado. |
| A12 | Média | Formulário oferecia texto/checkbox/combo denominado Lista, sem fluxo próprio para grupo de radio buttons/múltipla escolha exclusiva. | Motor corrigido e verificado: lista real, grupo radio com estado exclusivo entre páginas, limpeza/validação da escolha. Interface revisada oferece cinco tipos e lê os grupos via JSON do motor. |
| A13 | Média | Escolher imagem de marca d’água e depois mudar para texto ainda enviava `image`; o motor priorizava a imagem e ignorava o texto recém-escolhido. | Corrigido por revisão estática: `image` só é enviado nos modos que usam a imagem. |
| A14 | Média | Rotação/organização com uma única entrada exibiam senha individual, mas a encaminhavam apenas em `input_passwords`; leitura da senha individual existia só no caminho com múltiplas entradas. | Corrigido: rotação simples encaminha a senha; motor organiza uma entrada usando senha individual e nova senha do resultado, com regressão funcional aprovada. |
| A15 | Média | Ativar desenho, sair do leitor e esconder o controle na personalização podia manter `inkMode` ativo ao voltar, sem controle visível. | Corrigido por revisão estática: entrada no leitor desativa desenho quando barra ou controle estão ocultos, além dos observadores de alterações. |
| A16 | Média | Leitura dos campos ignorava `readonly` do JSON e reenviava campos bloqueados junto com os editáveis; o motor recusava toda a operação para preservar os campos bloqueados. | Corrigido por revisão estática: campos bloqueados aparecem desativados; somente valores editáveis realmente alterados são enviados. O teste do motor comprova recusa atômica de edição bloqueada. |

## Produto, hardware, interface e instalação

| Orientação | O que existe / evidência | O que continua sem demonstração integral |
|---|---|---|
| Nome PDF; instalação por comando sem conta paga | Bundle PDF, compilação arm64 local, assinatura ad hoc, runtime e instalador exercitados no CI anterior. | Não é bundle notarizado com Developer ID; assinatura local não garante todas as políticas corporativas/Gatekeeper. |
| Instalar em outros Macs próprios | Instalador e pacote de fontes com dependências/checksum, preservação de instalação anterior e instruções. | Não há evidência de implantação física em vários Macs M4 do usuário. |
| CPU/GPU/NPU/IA | Motor em processos externos; Core Image com contexto Metal; Vision e Foundation Models locais. | Frameworks escolhem o dispositivo de execução. Não há evidência de uso mensurado do Neural Engine nem comparação de desempenho/energia em M4 físico. |
| M4 e superiores | Binário arm64 para macOS moderno; teste anterior em M1 virtual confirma execução arm64. | Compatibilidade/performance em M4 e gerações posteriores não foi medida em hardware físico. |
| Liquid Glass | Uso efetivo de SwiftUI `glassEffect` com SDK compatível, materiais nativos e captura real anterior. | A revisão de duas janelas claras não cobre toda interação, tema, escala e acessibilidade. |
| Layout macOS 27.0.1 | UI nativa segue SDK instalado. | CI anterior usou macOS 26.6.2 / SDK 26.5; não é validação em 27.0.1 nem prova de reproduzir aquele layout. |
| Tudo personalizável | Novos ajustes de grade/lista, densidade, dimensões, cores livres, vidro/fosco/opaco, animações, nomes/ícones/ordem/visibilidade de cartões e navegação; leitura e barras; importação/exportação; parâmetros reutilizáveis por ferramenta; prefixo/pasta de saída. | Revisão de código não substitui execução dos novos controles. Personalização irrestrita da barra de menus do sistema, atalhos e metadados de todo arquivo não foi demonstrada. |
| Completo, definitivo, sem erros, melhor do mercado | Testes reais, revisão de código, limitações registradas e correções reproduzíveis. | Uma suíte finita não demonstra ausência de erros nem superioridade de mercado. Os achados desta auditoria mostram por que catálogo e testes anteriores não bastavam. |
| Usuário testar só ao final | Verificação de desenvolvimento feita pela equipe e CI. | Pendências de hardware/modelo/aplicativo precisam ser resolvidas com evidência; não devem ser transferidas ao usuário como se o produto já tivesse validação integral. |

## Execuções desta auditoria

Comandos reproduzíveis, na raiz do repositório:

```sh
.venv/bin/python -m unittest discover -s tests -p test_audit.py -v
.venv/bin/python -m unittest discover -s tests -q
PDF_CHROMIUM_EXECUTABLE=/usr/bin/chromium .venv/bin/python tests/integration_optional.py -q
.venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -v
```

Primeira execução independente, antes das correções: 12 métodos, 5 aprovados e 7 reprovados; 16 falhas de subcasos, sem erros do harness. Depois foram acrescentados 3 casos para comparação estrutural e PPTX rotacionado, e um caso de concorrência para arquivo/diretório criados por outro processo durante a conversão.

Após as correções A01–A07 e quatro novos casos de formulários, a suíte independente passou **20/20**, sem skips. Além disso, uma conversão real PDF rotacionado → PPTX → LibreOffice → PDF preservou o texto completo dentro da página renderizada.

A última rodada agregada independente, após os ajustes de senha na organização simples e limpeza de valores de formulário, passou **95/95 testes do núcleo em 7,114 s** e **13/13 testes de integridade da instalação em 0,665 s**. As **8/8 integrações externas passaram em 24,810 s**; seus caminhos não sofreram alterações após essa execução. São **116 testes**, sem skips ou falhas, com os 20 casos de auditoria já incluídos nos 95.

A regressão intermediária de ajuste de texto em `translate-layout` foi corrigida e passou na rodada final. Limpeza de texto/lista/combo também tem regressão porque a biblioteca não apagava automaticamente o valor com `widget.update("")`. Nenhum desses resultados representa compilação ou execução das alterações Swift no macOS: os achados de interface encerrados por revisão estática ainda exigem a execução nativa do snapshot final.
