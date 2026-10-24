# Personalização do PDF

Abra **Personalizar** pelo botão no início, pela barra lateral ou pela barra superior. Os ajustes são aplicados imediatamente e ficam salvos no Mac. **PDF → Ajustes** abre os mesmos controles. A restauração separa aparência/menu e leitor.

## Aparência e movimento

- Grade ou lista, três densidades, largura mínima dos cartões, tamanho das fontes e dos ícones.
- Descrições, categorias, agrupamento, boas-vindas e documentos recentes podem ser mostrados ou ocultados.
- Tema do sistema, claro ou escuro; cor livre, fundo em degradê ou plano.
- Liquid Glass, superfície fosca ou opaca, com transparência ajustável.
- Animações de navegação, transição e cartões, estilos suave/elástico/rápido, duração e ampliação ao passar o mouse.
- Reduzir Movimento e Reduzir Transparência, do macOS, prevalecem sobre os efeitos correspondentes.
- Perfis Vidro, Foco e Conforto, com prévia do cartão real.

Os efeitos se aplicam às superfícies e navegação do aplicativo. Menus e diálogos do sistema mantêm o comportamento fornecido pelo macOS.

## Ferramentas e navegação

Cada ferramenta pode receber nome e ícone diferentes, mudar de posição ou ficar oculta. Categorias também podem ser ocultadas. Favoritos são escolhidos pela estrela. Um estado vazio informa quando filtros ou preferências ocultam os itens.

As seções da barra lateral permitem renomear, escolher ícones, reordenar, ocultar e ajustar largura. A apresentação pode usar ícones, texto ou ambos. Início permanece acessível para permitir recuperar a navegação.

## Leitor e anotações

Modos de uma ou duas páginas, apresentação contínua, direção horizontal/vertical, área recortada ou folha completa, fundo, ajuste automático, zoom e separação entre páginas. É possível mostrar/ocultar navegação lateral, barra de anotações e controles individuais das barras.

Realce, notas e desenho têm cores próprias; a espessura do desenho vai de 0,5 a 20 pontos. Esses padrões afetam novas anotações. Para modificar uma anotação existente, selecione-a na página ou no inspector e ajuste conteúdo, cor, traço e geometria. O histórico de desfazer/refazer pertence a cada documento. A busca é assíncrona, cancelável e percorre as ocorrências encontradas. Cancelar ou fechar o documento libera as referências mantidas aos resultados.

Novas abas começam com o zoom e o ajuste automático escolhidos nas preferências. Abas existentes e recuperações mantêm páginas, zoom e marcadores independentes; alternar rapidamente entre elas não aplica o zoom de uma aba anterior. O painel de referência recebe as mesmas opções de direção, área, fundo e separação de páginas, conservando sua navegação. É possível escolher uma aba de referência e apresentar os dois documentos lado a lado ou empilhados. A recuperação automática é configurável; a lista de recuperações permite restaurar, excluir ou localizar os arquivos preservados. PDFs protegidos exigem novamente a senha para restauração.

## Arquivos e configurações por ferramenta

A pasta preferida, o prefixo e o modelo de nome são usados por todos os painéis de exportação: ferramentas, leitor, OCR, digitalizações, IA, Pages, assinaturas, verificações, benchmark, personalização e presets. O nome sugerido de saída aceita `{original}`, `{ferramenta}`, `{data}` e `{hora}`. Componentes de caminho inválidos são removidos e a extensão é aplicada uma vez. A escolha final do destino continua explícita, e arquivos existentes não são sobrescritos pelo motor.

Nas 24 ferramentas com parâmetros reutilizáveis, **Suas configurações desta ferramenta** permite salvar opções, escolher uma configuração padrão, importar, exportar e excluir. Inclui resolução, papel, orientação, fonte, cores, posições e demais parâmetros pertinentes à ferramenta. Word, Excel e detecção de formulários permitem escolher origem automática/vetorial/OCR, idioma, resolução e limiar de confiança. Operações sem esses parâmetros não apresentam uma configuração vazia.

Senhas, textos dos documentos, preenchimentos, páginas selecionadas e caminhos de arquivos não são gravados nos presets. Uma biblioteca inválida pode ser exportada para recuperação antes de uma restauração explícita.

## Transferir para outro Mac

**Exportar** em Personalizar grava aparência, menus, ferramentas, leitor e estilos de anotação em JSON. **Importar** verifica conteúdo, tamanhos e limites antes de aplicar qualquer alteração. Configurações por ferramenta e fluxos possuem exportações próprias. Destinos locais de arquivos permanecem específicos de cada Mac.

As verificações nativas exercitam persistência, ida e volta do JSON, compatibilidade com configurações anteriores, rejeição sem alteração parcial, restauração e preferências de acessibilidade. As capturas reais e o resultado do CI estão em [VALIDACAO.md](VALIDACAO.md).

A relação de ampliações solicitada pelo usuário, com prioridades e critérios de verificação, está em [MELHORIAS.md](MELHORIAS.md).
