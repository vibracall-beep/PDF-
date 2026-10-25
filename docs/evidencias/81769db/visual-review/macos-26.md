# Revisão visual independente — 81769db, macOS 26

Foram abertos os 33 PNGs originais com `view_image`. A evidência é do runner `macos-26`, execução `40229486932`, fonte `81769db`; o download autenticado e as verificações de integridade foram informados pelo coordenador. O JSON adjacente contém nomes, SHA-256, dimensões e nota individual de cada imagem.

Não confirmei bloqueador visual nas regiões exibidas: não há sobreposição impeditiva nem rótulo essencial visível ilegível. Isso não aprova fluxos completos, controles fora da captura, comportamento de acessibilidade ou o aplicativo inteiro.

## Áreas prioritárias

- Editor: objeto selecionado, lista, edição de texto, página/zoom e exportação legíveis. Estilos e aplicação inferiores exigem rolagem.
- Acessibilidade: hierarquia Document/Table/TR/TH/TD e campos de cabeçalho, escopo e extensão de linhas/colunas visíveis. O botão final permanece visível, mas a ação de aplicar alterações da tag fica abaixo da viewport inicial.
- Impressão: os quatro painéis mostram os parâmetros iniciais sem sobreposição. PDF/X é descrito como candidato, e a inspeção não é apresentada como certificação completa.
- Personalização: as oito abas foram abertas em imagens distintas; nomes, ícones, visibilidade, ordem, atalhos, aparência, leitura e perfis aparecem legíveis.
- OCR: imagem, caixas das palavras, confiança e trecho selecionado aparecem. O idioma ativo é Inglês para uma amostra em português; a captura não comprova avaliação de qualidade de OCR em português. A aplicação inferior exige rolagem.
- Integrações: os requisitos de serviço/chave, o aviso sobre emails reais em modo de teste, a configuração de assinatura e a automação são legíveis. Não há execução desses serviços demonstrada.

## Limites e verificações ainda dependentes de interação

1. Editor, acessibilidade, OCR, solicitação de assinaturas e fluxo em lote têm controles inferiores fora da viewport inicial. Existem barras de rolagem; as imagens não demonstram inacessibilidade nem a conclusão desses fluxos.
2. As barras do leitor transbordam horizontalmente; com o inspetor de anotações aberto, controles à direita aparecem parcialmente cortados. A barra horizontal da primeira linha é visível. Acesso por rolagem/teclado depende de interação, não desta revisão estática.
3. Não há captura específica de criação/preenchimento de formulários, scanner, diálogo de sincronização, resposta real de IA ou resultado de impressão.
4. Animações, material Liquid Glass em movimento, arraste, persistência, VoiceOver e desempenho em M4 físico não podem ser aprovados por imagens estáticas.

Nenhum arquivo de produto foi alterado nesta revisão.

## Arquivos efetivamente abertos

- `PDF-preview.editor-conteudo.png` — SHA-256 `a5dd137cfdc16c5a47b5c269d807835c3a9bdd1a3546668d74a406462f283eb6`
- `PDF-preview.corrigir-acessibilidade.png` — SHA-256 `cd230eba4c7ec45d7dfacad414445e9d330d761d75caf27205e2a02575596873`
- `PDF-preview.configuracao-ferramenta.png` — SHA-256 `f0f07f1ea94c10ba3f1d1ed6541260c5248de1e5724b1a4da8fe894d175b338a`
- `PDF-preview.revisao-ocr.png` — SHA-256 `119675073fc4f066dc21427429648e19f2e986f1c375aa089e66a0f9f13e34b4`
- `PDF-preview.producao-print-preflight.png` — SHA-256 `c2630c2ec96c9249bfca7698b5be6b35f30cdabc19c0944cfa39dedd50448fb1`
- `PDF-preview.producao-pdfx.png` — SHA-256 `14ffab59b726bcfbe7dd5fc298b9c47c10b8e4d7d03e21845e1e1e1ea7abefc9`
- `PDF-preview.producao-bates.png` — SHA-256 `390e8ff9de2e46cc957200e4a94d724b1f092d976c8c6b6363261754563731a7`
- `PDF-preview.producao-measure.png` — SHA-256 `f23a69b7cc88c88c1fa61ee98d593a62249682e0fb7d51e29a0bb23f37744aa2`
- `PDF-preview.solicitar-assinaturas.png` — SHA-256 `ed3153117498882bd7727936d2fecdfb724acd35c5af3aff4a8b4d92d057dafe`
- `PDF-preview.assinatura-digital.png` — SHA-256 `96bf99a028edac865a2b378330a7459db6638b74598652f9520578bd497eab8b`
- `PDF-preview.verificar-assinaturas.png` — SHA-256 `9b97ce5fcbe08823e7d29ddc7917089eb14099ebd11e0429bc8d6c1f8c0309f7`
- `PDF-preview.automacao.png` — SHA-256 `e86301c350608686c653a532d6264cf43a9662bf937fc6a585eb2773e23dab9e`
- `PDF-preview.personalizar.png` — SHA-256 `9191514015309549dd74c2effaf15915a26a86a3304ec950679de795e4e832e5`
- `PDF-preview.menus.png` — SHA-256 `9ad3fd64e2209200d52c192fb49356f16a05353c7aa7e1ebf5955596a086b4a5`
- `PDF-preview.atalhos.png` — SHA-256 `2d251e30325d1edd021bbf6bde1e52a89193509b1493cd68aed9828f81241df3`
- `PDF-preview.perfis.png` — SHA-256 `12e1789ee3a569602e4701bcf61f1b5f419b526f96ecfb27832f20ca5d3b5df0`
- `PDF-preview.ferramentas.png` — SHA-256 `5cf2d8f68b5e42cf83bf7c8235a6dd8628b3201f016dbf3cc46fffbb61bdf5c6`
- `PDF-preview.navegacao.png` — SHA-256 `a9396e2490149fb5cfdcc553d12b652aa8adfabc04952e228b942f76bcfa119f`
- `PDF-preview.opcoes-leitura.png` — SHA-256 `ecee24a41fd1aad72b3e6cd4d4142d287954316491c36d451806f341e9aaab3f`
- `PDF-preview.arquivos.png` — SHA-256 `a8fe7b7e3418ce2289d3554b0f1ac3721557ddf082c9a5be59db770509a38b49`
- `PDF-preview.anotacoes.png` — SHA-256 `a414e0083c73cf27547638b45ebc19bcd888bba45464f45babdc02fbeaf210d4`
- `PDF-preview.leitor.png` — SHA-256 `8ff027aefee3ba7d343475457b5f7a82c4bbe589912b5ee714bf6e765623c491`
- `PDF-preview.abas.png` — SHA-256 `8b59fef2f330cec8b671a1018eecf455e74ed9e5654add5a5032904f40c0df58`
- `PDF-preview.lado-a-lado.png` — SHA-256 `f9bf140109371164adaa988a0ce52f1bb324f7cffc97336b67b41c45119dc5dd`
- `PDF-preview.biblioteca.png` — SHA-256 `09ff575038c2f3fce69c4e9212eedd3fb66d95e94b9387d91037b808b57283ca`
- `PDF-preview.fluxo-lote.png` — SHA-256 `7b58ff7ea4801595227f5212141d2c07d2c959f1a5cd56bd31dc8645d505ad0d`
- `PDF-preview.recuperacao.png` — SHA-256 `7d1048624f010e454911bc9b45cbba7bb044b0dcb543d32ebceb210155600707`
- `PDF-preview.validar-pdfa.png` — SHA-256 `9cf0bdcf82f346cbb0d9be66deb96101bd1e16cbae361352643b3bd1db8edd30`
- `PDF-preview.auditar-pdfua.png` — SHA-256 `8dde7c59314eaac2a771225ae9cfaacc33ef574073493719b1aa125a57f0b4bf`
- `PDF-preview.png` — SHA-256 `c104766d414a3cd14721fa5edc15cf87bb8cb460d2240291e51469e3936186f3`
- `PDF-preview.escuro.png` — SHA-256 `94ef50b5eae0243083ad00f59f3b7a59e045099097a86af8ca60f542c7aa579e`
- `PDF-preview.lista.png` — SHA-256 `5a4cd2d84e251fd7c41fcc22a8f7743c99721e0c7d5d300c79936a56bc6d29b0`
- `PDF-preview.paleta.png` — SHA-256 `2a6e44f58b18e159d88c8489272f4e8cef21bff511353de116b89e424d8cfc61`
