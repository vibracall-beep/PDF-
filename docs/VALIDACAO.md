# Evidências de validação

## Linux: executado

- 45 testes funcionais do motor: aprovados, sem falhas ou testes ignorados.
- Cinco testes com integrações externas: aprovados, sem falhas ou testes ignorados.
- Verificações incluem alteração de documentos, formulários, criptografia, redaction, preservação de originais, publicação sem sobrescrita, cancelamento de processos, conversões Office, HTML, OCR e PDF/A.
- Casos de tradução do motor verificam inserção de texto traduzido fornecido no teste; não demonstram geração pelo modelo Apple.
- PDF/A foi gerado e seu identificador XMP foi verificado. Isso não substitui um validador independente de conformidade.
- Sintaxe shell verificada. Código Swift analisado por parser; esse resultado não substitui compilação ou checagem de tipos no SDK Apple.
- Empacotamento de fontes verificado quanto a reprodutibilidade, checksums, exclusões e não sobrescrita.

## macOS: fluxo preparado, ainda sem execução confirmada

O usuário autorizou GitHub Actions. `.github/workflows/macos.yml` usa runner Apple Silicon `macos-26`, compila o aplicativo, instala as dependências, executa os testes e valida o bundle assinado localmente. O fluxo também gera uma imagem da interface nativa para revisão.

`PDF --smoke-test` contém verificações de PDFKit, busca, formulários, persistência de anotações, renderização, Vision OCR a partir de página sem texto, melhoria de imagem Core Image/Metal, divisão de texto para IA, exportação PDF e publicação atômica.

Ainda precisam de evidência em macOS: compilação, instalação completa, testes nativos e renderização da interface. Scanner físico, iPhone/Continuity Camera, respostas Foundation Models e desempenho no hardware do usuário requerem dispositivos/capacidades disponíveis no ambiente de validação; um teste de disponibilidade não comprova a execução dessas funções.

## Instalação definitiva

Não há nesta evidência um binário macOS aprovado para instalação definitiva. O usuário pediu para testar somente após a conclusão; os testes de desenvolvimento são responsabilidade do processo de implementação, não uma transferência de validação ao usuário.
