# Ferramentas do PDF 0.6

O [catálogo atual](../Sources/PDF/PDFApp.swift) contém **71 cartões: 54 preservados da base anterior e 17 novos**, além do leitor permanente. Cartões de biblioteca, histórico, pesquisa e sincronização abrem o mesmo espaço de trabalho, onde ficam suas ações; a quantidade de cartões não equivale à quantidade de mecanismos independentes.

**A versão 0.6 está em validação.** A rodada [40114980785](https://github.com/vibracall-beep/PDF-/actions/runs/40114980785), commit `4ac9d264473fd5440df4d67bfa6cf2e702d8d3bf`, terminou **reprovada nos dois sistemas**. Cada um registrou **428 casos Python distintos: 427 aprovados e um skip**, além de **38 grupos nativos em três execuções**. No macOS 26 foram gerados 32 PNGs/seis relatórios AX, mas o gate recusou o controle Scope sem nome acessível. No macOS 27 a captura excedeu 300 segundos antes do primeiro PNG; a coleta de stack também expirou. Ambos falharam ao assinar `Python.framework` 3.12 durante a montagem. [Originais e procedência](evidencias/4ac9d26/README.md). Os 64 PNGs de `cbb3298` permanecem como revisão visual anterior concluída; não aprovam a captura ou os ajustes posteriores. O catálogo e as amostras não demonstram atendimento integral de cada requisito. Veja [AMPLIACOES-2026-10.md](AMPLIACOES-2026-10.md) e [VALIDACAO.md](VALIDACAO.md).

A candidata `0bd707d4023ce764a2e0121a1b93dcb0ca69fc1d`, [40118132309](https://github.com/vibracall-beep/PDF-/actions/runs/40118132309), está **em execução**, com ajustes de rótulos AX, descoberta do framework Python e diagnóstico de inicialização. Ainda não há aprovação dessa candidata ou do pacote portátil.

## Os 17 cartões acrescentados

| Nome no catálogo | Função implementada e limite relevante |
|---|---|
| Auditar conversão Office | Compara o PDF original com a saída editável e sua reexportação: texto, estrutura e aparência. O [painel de produção](../Sources/PDF/ProductionToolsView.swift) depende dos conversores necessários; métricas não garantem fidelidade universal. |
| Editar conteúdo original | [Editor de conteúdo](../Sources/PDF/AdvancedContentEditorView.swift) para texto, grupos de parágrafos compatíveis e imagens identificadas no PDF. Permite alterações suportadas, revisão e nova cópia; fontes ausentes, grupos complexos ou geometria sem preservação comprovada podem ser recusados. |
| Revisar OCR | [Revisão lado a lado](../Sources/PDF/OCRReviewView.swift) do reconhecimento real, com correção de palavras e caixas antes de aplicar uma camada pesquisável. Aceita páginas digitalizadas sem texto selecionável; plano e origem são vinculados por hash. |
| Biblioteca de documentos | [Biblioteca local](../Sources/PDF/DocumentLibraryView.swift) com importação explícita de cópias, coleções, etiquetas, duplicados por hash e até 64 pastas inteligentes salvas. As regras combinam texto, coleção, etiqueta, categoria e datas. |
| Histórico de versões | Na biblioteca, adiciona versões, compara e restaura uma versão anterior como nova revisão. Preserva os originais e todas as ramificações; não é edição colaborativa simultânea. |
| Pesquisar na coleção | [Busca em português](../Sources/PDF/LibraryRetrieval.swift), com documento, revisão, página e SHA-256. Pode usar NaturalLanguage instalado para ordenar resultados e Foundation Models disponível para responder ou comparar possíveis divergências. Cada par exige dois documentos e citações literais; o tópico é uma hipótese, não uma decisão de verdade. |
| Sincronizar biblioteca | Troca manual de objetos e manifestos pela pasta escolhida; conflitos permanecem no histórico e em cópias próprias. Também transfere snapshots de preferências, perfis e marcadores, aplicados apenas após revisão. Não inclui serviço de nuvem nem cifragem adicional da pasta. |
| Corrigir acessibilidade | [Editor de acessibilidade](../Sources/PDF/AccessibilityRemediationView.swift) para tags, ordem de leitura e alternativas textuais, com construção manual limitada de estrutura. Alterações preservam atributos omitidos; remoção explícita e mudança de TH conservam os demais atributos. A saída ainda exige validação PDF/UA e revisão humana; não promete conformidade automática. |
| Solicitar assinaturas | [Fluxo integrado](../Sources/PDF/SignatureRequestView.swift) com participantes, campos, confirmação, envio e consulta de status no Dropbox Sign. Requer credencial e conta do provedor; a integração real externa não foi exercitada. É separado do cartão Sign.com. |
| Diagnóstico de impressão | Relatório de fontes, DPI efetivo de imagens, caixas e presença de OutputIntent no [painel de produção](../Sources/PDF/ProductionToolsView.swift). Não valida toda a separação de cores ou sobreimpressão. |
| Corte e sangria | Define caixas na folha existente e marcas de corte. Não inventa arte além das bordas; recusa rotação/origem incompatível e CropBox diferente de MediaBox nas páginas selecionadas, sem revelar conteúdo oculto. |
| Preparar PDF/X-3 | Produz candidato PDF/X-3 com Ghostscript e perfil ICC CMYK fornecido. Não há certificação por validador independente PDF/X; a gráfica precisa conferir a saída. |
| Numeração Bates | Prefixo e contador para identificar páginas. A unicidade pertence à sequência configurada, sem registro global entre execuções. |
| Conjunto de documentos | Reúne até 500 PDFs com índice navegável e marcadores. A composição não conserva a validade criptográfica de assinaturas feitas sobre bytes anteriores. |
| Carimbo personalizado | Aplica carimbo gráfico de revisão ou identificação; não equivale a assinatura certificada. |
| Medir com escala | Calcula distância, perímetro e área com a escala informada pelo usuário. Não faz calibração física automática. |
| Automação do Mac | [Regras de pastas monitoradas](../Sources/PDF/AutomationWorkspace.swift) com fluxos salvos, fila e ativação explícita, além dos Serviços do Finder. Requer app aberto; não instala daemon. App Intents para abrir PDF e executar fluxo têm metadados reais aprovados nos SDKs 26/27 e testes de entrada/automação aprovados nos dois sistemas em `cbb3298`; a interação pela interface do Atalhos ainda não foi comprovada. |

## Correspondência histórica com a terceira imagem

Os 45 itens da terceira imagem correspondem a **44 cartões preservados e ao leitor**, que permanece na barra lateral. A tabela conserva essa referência visual; não é uma nova declaração de aprovação das ferramentas no macOS. Os outros dez cartões da base de 54 aparecem na seção seguinte.

| Item da imagem | Acesso no aplicativo e implementação |
|---|---|
| Comprimir PDF | Comprimir PDF; otimização sem perdas ou recompressão configurável de imagens |
| Conversor de PDF | Conversor de PDF; filtra o catálogo de formatos |
| OCR de PDF | OCR PDF; OCRmyPDF/Tesseract. O OCR local do leitor/digitalização identifica Vision ou o fallback Tesseract efetivamente usado |
| PDF para PDF/A | PDF para PDF/A; OCRmyPDF |
| PDF para JPG | PDF para JPG; páginas ou imagens incorporadas |
| PDF para PNG | PDF para PNG; resolução, páginas/imagens e transparência |
| JPG para PDF | JPG para PDF; também aceita outros formatos de imagem, papel, orientação e margens |
| PDF para Word | PDF para Word; DOCX com texto, estilos, imagens, tabelas e análise OCR opcional de digitalizações; reconstrução de layout tem limites |
| PDF para Excel | PDF para Excel; XLSX com tabelas, texto ao redor e análise OCR opcional; células e ordem precisam de revisão |
| PDF para PPT | PDF para PowerPoint; texto editável ou páginas como imagens |
| Word para PDF | Word para PDF; LibreOffice |
| Excel para PDF | Excel para PDF; ajuste à largura e orientação |
| PPT para PDF | PowerPoint para PDF; LibreOffice |
| ODT para PDF | ODT para PDF; LibreOffice |
| TXT para PDF | TXT para PDF; codificação, fonte, papel, orientação e margens |
| RTF para PDF | RTF para PDF; LibreOffice |
| HTML para PDF | HTML para PDF; arquivo ou URL, Chromium local |
| EPUB para PDF | EPUB para PDF; paginação de livros sem DRM |
| CSV para PDF | CSV para PDF; separador automático/manual, codificação e paginação da tabela |
| Pages para PDF | Pages para PDF; exportação pelo Pages instalado, mediante autorização de Automação do macOS |
| Juntar PDF | Juntar PDF; arquivos ordenáveis |
| Dividir PDF | Dividir PDF; páginas individuais ou grupos de intervalos |
| Girar PDF | Rodar PDF; seleção de páginas e processamento de vários documentos |
| Excluir páginas do PDF | Excluir páginas; salva novo arquivo e recusa exclusão de todas as páginas |
| Extrair páginas de PDF | Extrair páginas; preserva ordem e aceita repetição explícita |
| Organizar PDF | Organizar PDF; reordenar, repetir ou remover páginas |
| Editar PDF | Editar PDF; ferramenta anterior de texto, substituição, imagem e formas, preservada ao lado do novo editor de conteúdo original |
| Anotador de PDF | Anotar PDF; abre o leitor com realces, notas e desenho livre |
| Leitor de PDF | Leitor na barra lateral; PDFKit, busca, miniaturas, sumário, marcadores, zoom e impressão |
| Numere páginas | Números de página; posição, fonte, tamanho, início e formato |
| Recortar PDF | Recortar PDF; ajuste de margens |
| Redigir PDF | Ocultar PDF; remoção permanente de texto/áreas, metadados e anexos |
| Marca d'água PDF | Marca d’água; texto ou imagem, posição e transparência |
| Preenchimento de formulários em PDF | Preencher PDF; lê e preenche campos existentes. Formulários PDF também cria e sugere campos |
| Compartilhe PDFs | Compartilhar PDF; seletor nativo de serviços do macOS, com cópia atual salva |
| Assinar PDF | Assinar PDF; assinatura visual e composição de solicitação por e-mail |
| Solicitar assinaturas (Sign.com) | Sign.com; acesso identificado ao serviço externo no navegador, onde o usuário administra conta, envio e acompanhamento |
| Desproteger PDF | Desbloquear PDF; exige senha conhecida |
| Proteger PDF | Proteger PDF; AES-256 |
| Achatar PDF | Achatar PDF; incorpora aparência de anotações e/ou campos preenchidos ao conteúdo |
| Chat com PDF | Conversar com PDF; IA local com seleção de trechos, histórico e referências verificadas de página, conforme disponibilidade do modelo |
| Resumidor de PDF por IA | Resumir com IA; processamento em trechos e exportação |
| Traduzir PDF | Traduzir PDF; texto ou blocos posicionados, com verificação de encaixe |
| Gerador de questões por IA | Gerar questionário; questões abertas ou de múltipla escolha, nível, quantidade, gabarito e referências |
| Scanner de PDF | Digitalizar; scanner compatível, importação e Câmera de Continuidade |

## Os outros dez cartões preservados

| Nome no catálogo | Função |
|---|---|
| Reparar PDF | Tenta recuperar documentos que o mecanismo ainda consegue interpretar; não recupera qualquer corrupção. |
| Comparar PDF | Compara texto ou apresentação visual entre duas versões. |
| Formulários PDF | Cria, inspeciona e preenche campos; a detecção vetorial/OCR gera sugestões que exigem revisão. |
| PDF para Markdown | Exporta texto, títulos, tabelas reconhecidas e imagens. OCR e origem automática são escolhas explícitas; o padrão continua vetorial. |
| Criar fluxo de trabalho | Sequências tipadas, presets e lote com senhas transitórias por arquivo. Uma exportação final pode produzir DOCX, XLSX, PPTX, Markdown, JPG ou PNG. |
| Assinatura digital certificada | Assina com certificado do usuário via pyHanko; validação/revogação/carimbo temporal dependem da configuração e das evidências disponíveis. |
| Verificar assinaturas | Analisa integridade, certificados e evidências; confiança depende das raízes e políticas fornecidas. |
| Validar PDF/A | Usa veraPDF independente para o perfil selecionado, com relatório de conformidade ou falhas. |
| Auditar PDF/UA | Usa veraPDF para verificação técnica e gera achados; conformidade semântica e uso assistivo ainda exigem avaliação humana. |
| Desempenho do Mac | Mede operações definidas e registra tempos, recursos e mecanismo OCR. Não demonstra ganho M4, energia ou uso de Neural Engine sem medições correspondentes. |

## Parâmetros, fluxos e integração com o Mac

**25 ferramentas** oferecem presets reutilizáveis; aparência, nomes, ícones, ordem por arraste, menus, atalhos e perfis possuem controles próprios. A paleta abre por **⌘⇧K** no padrão e inclui ferramentas ocultas no menu. Veja [PERSONALIZACAO.md](PERSONALIZACAO.md) para opções, limites e transferência de configurações.

Word, Excel e Markdown permitem selecionar `vector`, `ocr` ou `auto`, além de tabelas com grades ou colunas alinhadas. O modo automático aplica OCR somente a páginas com imagem e sem texto selecionável. Os ajustes estruturados incluem idioma, `ocr_dpi` inteiro entre 120 e 400, `min_confidence` entre 0 e 100 e `ocr_deskew` opcional, desligado por padrão. A correção de inclinação depende de linhas de grade e limita-se a ±7°; altera a imagem temporária, não os pixels da fonte. Baixa confiança não elimina texto silenciosamente. Idiomas precisam estar instalados.

Esses parâmetros também persistem nas etapas de [fluxo](../Sources/PDF/WorkflowView.swift). Presets v1/v2 anteriores continuam aceitos: Word/Excel mantêm origem automática e inglês efetivo nas etapas antigas; Markdown permanece vetorial, sem passar a executar OCR implicitamente. A etapa direta OCRmyPDF conserva opções próprias. Fluxos usam no máximo 24 etapas no editor e até 1.000 entradas por lote; resultados são publicados apenas ao terminar o conjunto. Edições vinculadas a uma revisão, remediação de acessibilidade e solicitações remotas exigem suas telas de revisão e não entram em fluxos genéricos.

Os App Intents **Abrir PDF** e **Executar fluxo do PDF** usam cópias privadas; executar fluxo exige confirmação e destino novo. Serviços do Finder abrem PDFs para revisão, sem executar fluxos automaticamente. Pastas monitoradas são opt-in, ignoram arquivos presentes ao ativar, não percorrem subpastas e pausam em falhas ou necessidade de senha. O [código App Intents](../Sources/PDF/PDFAppIntents.swift) não substitui a validação de registro no app Atalhos.

## Limites de execução e validação

`4ac9d26` separa referências compartilhadas de página antes de Bates, carimbo e preparação de impressão, preservando atributos dos links, ações, catálogo e sumário. Os testes passaram nos dois Macs. O contrato nativo de edição de tags também passou; a nova captura/AX, contudo, reprovou por Scope sem nome no macOS 26 e timeout no macOS 27. Ajustes locais de rótulos AX e descoberta do framework Python, além de diagnóstico da inicialização da prévia, estão na candidata posterior em execução, sem aprovação antecipada. Não há aprovação desses ajustes, do pacote portátil, de sua instalação/atualização ou da compatibilidade do mesmo binário entre sistemas. O diagnóstico não muda uma falha em aprovação.

Achatar não remove informações sensíveis: use **Ocultar PDF** para remoção permanente. Recortar muda a área visível e não apaga conteúdo escondido. Assinatura visual, carimbo gráfico e assinatura criptográfica têm funções diferentes. O cartão **Sign.com** abre um serviço externo no navegador; a nova integração de solicitação é com **Dropbox Sign**, e requer conta, autorização e possíveis custos do provedor.

Conversões complexas podem alterar composição, quebras e fontes. Pages exige o aplicativo da Apple e autorização de Automação; scanner/iPhone dependem de equipamento compatível. Geração local depende de Apple Intelligence disponível, e uma citação literal não prova a interpretação do modelo. A pesquisa por termos permanece disponível sem modelo generativo.

Presença no catálogo não comprova ensaio com hardware físico, serviço externo ou modelo Apple. O atendimento por requisito e os ensaios restantes estão em [AMPLIACOES-2026-10.md](AMPLIACOES-2026-10.md); os resultados executados e sua revisão de origem estão em [VALIDACAO.md](VALIDACAO.md).
