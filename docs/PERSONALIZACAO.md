# Personalização do PDF 0.6

Abra **Personalizar** pelo botão no início, pela barra lateral ou pela barra superior. **PDF → Ajustes** abre os mesmos controles. As abas são **Aparência, Ferramentas, Navegação, Leitor, Arquivos, Atalhos e Perfis**. Os ajustes ficam salvos neste Mac; a restauração separa aparência/menu e leitor.

Este documento descreve a implementação 0.6, com **71 cartões de ferramentas, incluindo os 54 anteriores**, além do leitor permanente. A validação macOS desta revisão ainda está pendente: a integração GitHub retornou `401 — Bad credentials`, impedindo novos envios. Consulte a [matriz das 17 ampliações](AMPLIACOES-2026-10.md) e o [registro de validação](VALIDACAO.md); resultados da base anterior são históricos.

## Aparência e movimento

- Grade ou lista, três densidades, largura mínima dos cartões, tamanho das fontes e dos ícones.
- Descrições, categorias, agrupamento, boas-vindas e documentos recentes podem ser mostrados ou ocultados.
- Tema do sistema, claro ou escuro; cor livre, fundo em degradê ou plano.
- Liquid Glass, superfície fosca ou opaca, com transparência ajustável.
- Animações de navegação, transição e cartões, estilos suave/elástico/rápido, duração e ampliação ao passar o mouse.
- Reduzir Movimento e Reduzir Transparência, do macOS, prevalecem sobre os efeitos correspondentes.
- Predefinições visuais Vidro, Foco e Conforto, com prévia do cartão real.

Os efeitos se aplicam às superfícies e navegação do aplicativo. Menus e diálogos do sistema mantêm o comportamento fornecido pelo macOS.

## Ferramentas e navegação

Cada ferramenta pode receber nome e ícone diferentes, mudar de posição ou ficar oculta. Em **Personalizar → Ferramentas**, arraste pela alça para reordenar ou use as setas. Categorias também podem ser ocultadas. Favoritos são escolhidos pela estrela. Um estado vazio informa quando filtros ou preferências ocultam os itens.

As seções da barra lateral permitem renomear, escolher ícones, reordenar por arraste ou setas, ocultar e ajustar largura. A apresentação pode usar ícones, texto ou ambos. **Início** permanece acessível para permitir recuperar a navegação.

## Paleta, atalhos e perfis

**Ferramentas → Buscar comandos e ferramentas…**, por padrão **⌘⇧K**, abre a paleta. Ela pesquisa nomes personalizados, categorias e ações, apresenta comandos recentes e permite navegar com as setas e Return. Ferramentas ocultas no menu continuam acessíveis por essa busca.

Em **Atalhos**, atribua uma tecla ou seta combinada com Command; Shift, Option e Control são opcionais. O editor recusa colisões entre ações e combinações reservadas de edição/macOS. É possível remover uma combinação ou restaurar os padrões. Os atalhos configurados aparecem nos menus e na paleta; não são atalhos globais que interceptam outros aplicativos.

Em **Perfis**, guarde até **30 espaços de trabalho nomeados**, contendo aparência, menus, ordem das ferramentas, atalhos, opções do leitor e preferências de saída. Aplicar um perfil preserva documentos abertos, posições de leitura, histórico e recuperações. Atualizar um perfil existente exige a confirmação apresentada na tela. Os perfis são diferentes das três predefinições visuais mencionadas acima.

Implementação: [personalização](../Sources/PDF/CustomizationView.swift), [atalhos e perfis](../Sources/PDF/AdvancedCustomization.swift), [paleta](../Sources/PDF/CommandPalette.swift).

## Leitor e anotações

Modos de uma ou duas páginas, apresentação contínua, direção horizontal/vertical, área recortada ou folha completa, fundo, ajuste automático, zoom e separação entre páginas. É possível mostrar/ocultar navegação lateral, barra de anotações e controles individuais das barras.

Realce, notas e desenho têm cores próprias; a espessura do desenho vai de 0,5 a 20 pontos. Esses padrões afetam novas anotações. Para modificar uma anotação existente, selecione-a na página ou no inspector e ajuste conteúdo, cor, traço e geometria. O histórico de desfazer/refazer pertence a cada documento. A busca é assíncrona, cancelável e percorre as ocorrências encontradas. Cancelar ou fechar o documento libera as referências mantidas aos resultados.

Novas abas começam com o zoom e o ajuste automático escolhidos nas preferências. Abas existentes e recuperações mantêm páginas, zoom e marcadores independentes; alternar rapidamente entre elas não aplica o zoom de uma aba anterior. O painel de referência recebe as mesmas opções de direção, área, fundo e separação de páginas, conservando sua navegação. É possível escolher uma aba de referência e apresentar os dois documentos lado a lado ou empilhados. A recuperação automática é configurável; a lista de recuperações permite restaurar, excluir ou localizar os arquivos preservados. PDFs protegidos exigem novamente a senha para restauração.

## Arquivos e configurações por ferramenta

A pasta preferida, o prefixo e o modelo de nome são usados por todos os painéis de exportação: ferramentas, leitor, OCR, digitalizações, IA, Pages, assinaturas, verificações, benchmark, personalização e presets. O nome sugerido de saída aceita `{original}`, `{ferramenta}`, `{data}` e `{hora}`. Componentes de caminho inválidos são removidos e a extensão é aplicada uma vez. A escolha final do destino continua explícita, e arquivos existentes não são sobrescritos pelo motor.

Nas **25 ferramentas com parâmetros reutilizáveis**, **Suas configurações desta ferramenta** permite salvar opções, escolher uma configuração padrão, importar, exportar e excluir. O limite é de 30 configurações por ferramenta e 128 no total. Inclui resolução, papel, orientação, fonte, cores, posições e demais parâmetros pertinentes à ferramenta. A relação aceita está em [ToolPresets.swift](../Sources/PDF/ToolPresets.swift); operações sem esses parâmetros não apresentam uma configuração vazia.

Word, Excel, Markdown e detecção de formulários oferecem origem automática, vetorial ou OCR. Quando o OCR está habilitado, há idioma, resolução inteira de **120 a 400 DPI**, limiar de confiança de **0 a 100** e correção opcional de pequena inclinação. Essa correção depende de evidência de linhas de grade, limita-se a ±7° e modifica somente a imagem temporária usada no reconhecimento. Palavras abaixo do limiar continuam disponíveis para revisão; o escore não é uma garantia de acerto. A detecção de tabelas oferece grades com linhas ou inclusão de colunas alinhadas sem bordas, sujeitas às limitações de reconstrução.

Senhas, textos dos documentos, preenchimentos, páginas selecionadas e caminhos de arquivos não são gravados nos presets por ferramenta. Uma biblioteca inválida pode ser exportada para recuperação antes de uma restauração explícita.

## Fluxos e automação

**Criar fluxo de trabalho** guarda até 24 etapas por sequência. Pode terminar em PDF, DOCX, XLSX, PPTX, Markdown ou uma pasta JPG/PNG, e processar um lote de até 1.000 PDFs. Exportações encerram o fluxo; senhas individuais são transitórias. A saída final só é publicada após a conclusão do lote.

Nas etapas Word, Excel e Markdown, o editor também guarda origem do texto, reconhecimento de tabelas e os ajustes de OCR acima. Fluxos antigos continuam decodificáveis: Word/Excel mantêm origem automática e o idioma efetivo anterior, inglês; Markdown permanece vetorial até a seleção explícita de OCR ou automático. A etapa direta **Reconhecer texto (OCR)** conserva seu contrato próprio com OCRmyPDF. Implementação e regressões: [WorkflowView.swift](../Sources/PDF/WorkflowView.swift).

**Automação do Mac** permite criar regras inicialmente desativadas para pastas de entrada/saída e fluxos salvos. Ao ativar, os PDFs já presentes são ignorados; novas chegadas precisam permanecer estáveis antes de entrar na fila. O app deve ficar aberto. Até 20 regras, 5.000 itens por pasta e 200 pendências; subpastas e links não são processados. Falha ou necessidade de senha pausa a regra para revisão. Não é instalado um serviço permanente de segundo plano.

Os App Intents implementados são **Abrir PDF** e **Executar fluxo do PDF**. O segundo pede confirmação e uma nova pasta de resultados; fluxos que dependem de senha são executados manualmente. Também há integração com os Serviços do Finder. A descoberta no app Atalhos e a execução desses percursos precisam da validação nativa corrente; presença no código não comprova o registro no sistema. Veja [PDFAppIntents.swift](../Sources/PDF/PDFAppIntents.swift) e [AutomationWorkspace.swift](../Sources/PDF/AutomationWorkspace.swift).

## Biblioteca e pastas inteligentes

Na **Biblioteca de documentos**, organize cópias por título, coleção e etiquetas. Salve até **64 pastas inteligentes nomeadas** com regras de texto, coleção, etiqueta, categoria e intervalo de datas. Elas recalculam os resultados a partir das versões atuais; a data corresponde à importação, nova versão ou alteração de metadados na biblioteca. Atualizar ou excluir uma regra não move nem exclui PDFs. Essas regras permanecem locais neste Mac.

O histórico conserva versões, permite comparação e restauração como nova versão. **Pesquisar na coleção** consulta trechos em português e pode solicitar resposta ou **Comparar fontes / Contradições** ao modelo local disponível. Cada possível divergência exige dois documentos distintos e citações literais com versão, página e hash; os lados são extractivos e o tópico permanece uma hipótese a revisar. Sem duas fontes de apoio, não há comparação gerada. A qualidade de interpretação do modelo não decorre da validação das citações.

## Transferir para outro Mac

**Exportar** em Personalizar grava aparência, menus, ferramentas, leitor, estilos de anotação, atalhos e preferências de saída em JSON. **Importar** valida conteúdo e limites antes de aplicar. O caminho da pasta de saída integra essas preferências: revise-o após importar em outro Mac. Presets de ferramentas e fluxos possuem exportações próprias.

Para trocar configurações pela biblioteca, abra **Trocar ajustes**, escolha **Preferências**, **Perfis** ou **Marcadores e leitura** e guarde uma versão. Depois use **Sincronizar** com a pasta escolhida; no outro Mac, sincronize, revise o snapshot recebido e acione **Aplicar versão escolhida…**. Receber arquivos nunca aplica configurações automaticamente.

Perfis em conflito são mantidos como cópias por padrão; substituir os mesmos identificadores é uma escolha explícita. Marcadores exigem a mesma versão salva do PDF, conferida por SHA-256 e quantidade de páginas. A opção padrão une marcadores e conserva a posição atual; substituir marcadores ou restaurar página/zoom exige marcar os controles correspondentes. Senhas não entram nos snapshots.

A troca usa uma pasta local, externa ou de um provedor configurado pelo usuário. O aplicativo não fornece um backend de nuvem nem acrescenta cifragem ponta a ponta à pasta compartilhada. PDFs já protegidos conservam seus bytes cifrados. Regras de pastas monitoradas e pastas inteligentes não são migradas por esse mecanismo. Implementação: [SettingsExchangeView.swift](../Sources/PDF/SettingsExchangeView.swift) e [LibraryConfiguration.swift](../Sources/PDF/LibraryConfiguration.swift).

As suítes incluem persistência, ida e volta de JSON, compatibilidade anterior, rejeição sem aplicação parcial, conflitos de atalhos/perfis, fontes verificadas e integridade dos snapshots. Os novos casos nativos não são apresentados como aprovados antes da execução macOS. Capturas e resultados datados ficam em [VALIDACAO.md](VALIDACAO.md).

A cobertura atual e os limites restantes estão em [AMPLIACOES-2026-10.md](AMPLIACOES-2026-10.md). [MELHORIAS.md](MELHORIAS.md) registra a rodada anterior de dez melhorias e sua evidência histórica.
