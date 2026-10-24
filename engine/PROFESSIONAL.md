# Assinaturas, solicitações e estrutura acessível

Todas as operações usam a transação de saída do motor: não substituem a origem nem um destino existente. As operações de rede abaixo são ações explícitas; a preparação de solicitações e a edição de tags são locais.

## Assinaturas PAdES

`digital-sign` mantém `certificate`, `certificate_password`, `field_name`, `reason` e `location`. `profile` aceita `B-B`, `B-T`, `B-LT` e `B-LTA`. B-T/LT/LTA exigem `tsa_url` HTTPS. LT/LTA também exigem raízes explícitas e evidência de revogação válida. A implementação usa pyHanko para assinatura incremental, DSS e carimbo documental LTA; não aplica uma identificação PDF/A/PDF/UA nem atribui validade jurídica.

`verify-signatures` continua offline por padrão. Opções adicionais:

| Opção | Efeito |
|---|---|
| `trust_roots: [path]` | Autoridades explicitamente reconhecidas pelo usuário. |
| `revocation_mode`: `"offline"` ou `"require"` | `require` exige evidência para cada certificado não âncora, inclusive quando não há URL OCSP/CRL no certificado. |
| `crls: [path]`, `ocsp_responses: [path]` | Evidência local DER/PEM, limitada e verificada criptograficamente. |
| `allow_revocation_network: true` | Autoriza somente os endpoints selecionados abaixo. |
| `revocation_endpoints: [{kind, url: "https://…"}]` | `kind` é `crl` (GET) ou `ocsp` (POST, vinculando certificado/emissor ao endpoint declarado no certificado). Não segue redirecionamentos, proxies ambientais nem AIA automaticamente. |
| `validate_lta: true` | Exige estrutura PAdES/LTA e executa avaliação AdES-LTA sobre provas embutidas, sem rede. Resultado separado em `long_term_validation` e `all_lta_proofs_valid`. |

Evidência DSS também é validada; estar embutida não a torna confiável. Carimbos documentais são verificados como RFC3161, separados das assinaturas comuns. Certificado revogado, resposta expirada, resposta forjada, ausência de prova ou confiança não estabelecida não produz confirmação de não revogação. Os perfis dependem das cadeias reais da autoridade e da TSA; preservar por muitos anos exige renovar provas antes de expiração/obsolescência. Endpoints HTTP não são consultados; nesses casos é possível fornecer evidência local verificada.

Testes em `test_signature_long_term.py` usam PKI temporária e servidor HTTPS local real para OCSP good/revoked, CRL good/revoked/expired/forged e RFC3161. Produzem B-LT/B-LTA reais, inspecionam DSS/carimbo documental e validam AdES-LTA offline. Não substituem ensaios com o certificado/TSA de produção do usuário.

## Solicitação integrada — Dropbox Sign

Contrato confirmado no [SDK oficial](https://github.com/hellosign/dropbox-sign-python/blob/main/docs/SignatureRequestApi.md), [modelo de envio](https://github.com/hellosign/dropbox-sign-python/blob/main/docs/SignatureRequestSendRequest.md) e [campos posicionados](https://github.com/hellosign/dropbox-sign-python/blob/main/docs/SubFormFieldsPerDocumentBase.md). Origem fixa `https://api.hellosign.com/v3`; API key em Basic Authentication, senha HTTP vazia. A chave vem do Chaves do macOS, entrada privada do processo ou `PDF_DROPBOX_SIGN_API_KEY`; nunca dos argumentos de CLI, rascunhos, preferências ou recibos.

- `signature-request-prepare`: entrada PDF, saída JSON. Opções `signers:[{name,email_address}]`, `fields:[{type:"signature"|"initials"|"date_signed",signer:0,page:1,x,y,width,height}]`, `title`, `subject`, `message`, `test_mode` (padrão `true`). Um campo de assinatura é obrigatório por destinatário. Máximo local de 40 MiB/20 destinatários/200 campos. PDFs criptografados são recusados, inclusive com senha de usuário vazia e restrições de proprietário. Coordenadas por página em pixels a 72 DPI, correspondentes aos pontos PDF, conforme o [editor de campos oficial](https://github.com/hellosign/dropbox-sign-api-demo/blob/d60fa159b9c68dc3d8dd89d1f40992be6a05a216/public/main.js#L1987) e a [transferência para API](https://github.com/hellosign/dropbox-sign-api-demo/blob/d60fa159b9c68dc3d8dd89d1f40992be6a05a216/src/routes/signing.js#L1130). O retângulo completo deve caber na página visível; a preparação não redimensiona, altera nem envia o documento. Posicionamento efetivo no serviço ainda exige ensaio com uma conta real.
- `signature-request-send`: recebe o PDF original, `draft` (JSON revisado), `confirmed_sha256`, `confirmed_draft_sha256`, `confirm_send:true` e credencial. Verifica ambos os hashes, envia multipart com `files[0]`, signers e `form_fields_per_document`. **Modo de teste ainda pode enviar emails reais.** Não use esta operação em fluxos automáticos/agendamentos.
- `signature-request-status`: `request_id` e credencial; GET da solicitação. A entrada posicional é ignorada. Retorna somente campos permitidos, sem URLs de assinatura nem tokens.

O envio grava antes do POST um recibo exclusivo e sincronizado `.pdf-signature-attempt-<draft-id>.json`, com permissão 0600, hashes/data e, quando confirmado, identificador do serviço. O recibo impede repetir o mesmo rascunho após resposta perdida, reinício ou falha de publicação local. Não contém credenciais, nomes, emails nem texto do PDF. Uma falha pode significar que o provedor recebeu a solicitação: consultar o recibo/conta antes de preparar outra. Não há repetição automática, inclusive em HTTP 429. Não há envio externo durante os testes de desenvolvimento; `test_signature_requests.py` verifica HTTP/multipart contra servidor local controlado.

## Correção explícita de acessibilidade

- `accessibility-inspect`: JSON com SHA-256, idioma e árvore (`id`, `parent`, `role`, `page`, `alt`, `actual_text`, `title`, `language`, `scope`, `children`, `content`). Limites de profundidade/tamanho; ciclos e identidades ambíguas são recusados.
- `accessibility-remediate`: exige `input_sha256` da inspeção. `edits:[{id,role?,alt?,actual_text?,title?,language?,scope?,children?}]` altera tags existentes. `scope` só aceita Row/Column/Both em TH. `children` deve ser uma permutação completa dos filhos estruturais do mesmo pai; não move nem elimina MCIDs. Idioma vazio da tag remove a substituição local e deixa valer o idioma herdado.
- `create_page_tags:[{page,role,alt?}]` cria uma estrutura somente em PDF sem tags nem conteúdo marcado preexistente: cada página inteira vira **um bloco manualmente declarado**, com MCID e ParentTree reais. É obrigatório cobrir todas as páginas uma vez; a lista define a ordem de leitura. Não cria tabelas ou semântica complexa automaticamente. Documento assinado/criptografado é recusado para esta edição.

O editor oferece papéis/títulos, alternativas, ActualText, idioma, Scope e ordem entre irmãos; a cópia pode ser validada por veraPDF na mesma interface. Significado, leitura de colunas, tabelas complexas e descrições úteis continuam exigindo revisão humana. `integration_accessibility.py` comprova que uma cópia com tags reais ainda pode falhar PDF/UA e não recebe declaração falsa de conformidade.
