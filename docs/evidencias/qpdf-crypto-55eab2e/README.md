# Diagnóstico causal de qpdf e OpenSSL — 55eab2e

A [execução 40133464239, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40133464239), do commit [`55eab2ed4c2e323b01faa91f1cab4b2bd421f6e1`](https://github.com/vibracall-beep/PDF-/commit/55eab2ed4c2e323b01faa91f1cab4b2bd421f6e1), confirmou nos dois Macs a causa investigada: o qpdf relocado precisava localizar o provider `legacy` do OpenSSL 4 dentro do pacote. A biblioteca e sua versão foram identificadas pelas dependências Mach-O reais; o diagnóstico usou o módulo da mesma instalação.

**O diagnóstico passou; o aplicativo e o pacote completo não foram aprovados por esta execução.** Os relatórios mantêm `productApproved: false`. A integração da correção exige outra matriz completa, incluindo o smoke portátil que falhou na [rodada e9af24a](../e9af24a/README.md).

## Controles comprovados

Cada sequência foi executada no macOS 26 e no SDK/macOS 27, tanto com o qpdf direto quanto com seu wrapper. Os hashes do executável e do PDF protegido permaneceram iguais entre os controles.

| Controle sobre o PDF protegido sintético | Código de saída nos quatro pares sistema/transporte |
| --- | --- |
| Fora do sandbox | `0` |
| Dentro, descoberta padrão do provider | `2`, erro explícito ao carregar o provider `legacy` |
| Dentro, `OPENSSL_MODULES` aponta para os módulos privados corretos | `0` |
| Dentro, aponta para uma pasta vazia | `2`, mesmo erro do provider |
| Dentro, módulos corretos restaurados | `0` |
| Dentro, variável removida novamente | `2`, mesmo erro do provider |
| Dentro, módulos corretos e senha errada | `2`, senha inválida |

O PDF sem criptografia passou dentro do sandbox (`0`). As referências originais escritas pelo PDFKit, sem criptografia e protegida, passaram no qpdf de origem (`0`) nos dois sistemas. Assim, os controles distinguem falha de descoberta do provider, senha inválida e estrutura da fixture.

A criação de uma saída AES-256 também passou: qpdf confirmou `R=6`, `V=5`, 256 bits e `AESv3`, com a senha do usuário aceita e distinta da senha do proprietário. A inspeção independente pelo PDFKit reabriu uma página com o texto esperado, aceitou a senha correta e recusou as senhas vazia e errada. Os testes de criação, leitura e inspeção terminaram com código `0`.

O runtime foi movido e a localização anterior removida. O manifesto dos arquivos permaneceu igual antes/depois, as assinaturas foram verificadas e todos os subprocessos tiveram limpeza confirmada. A pasta temporária do diagnóstico foi removida. Nenhum documento do usuário ou pedido externo de assinatura participou dos ensaios.

## Originais preservados

- [ZIP oficial dos logs da tentativa](attempt-1-logs.zip), sem alteração: 38.095 bytes, SHA-256 `9a4a6a550b9f1e5ed3d7950b0fb17c99a332aa3314dd95bfbde5bccb53d6d609`.
- [Relatório original do macOS 26](macos-26-report.json), extraído do artefato **12575841661**. ZIP: 193.186 bytes, SHA-256 `aa823dee9b3879cdf3ac0eb3012a05d56a415d2b0436d51326faab237c78d0cd`.
- [Relatório original do SDK/macOS 27](xcode-27-report.json), extraído do artefato **12575184841**. ZIP: 195.865 bytes, SHA-256 `4da77e0e214ec32826207b3fcba969b2a44e6d4322ccbceb998dd5491d2da9f8`.
- [Procedência e verificações independentes](provenance.json), incluindo hashes dos relatórios, vínculo à fonte e resultados dos controles.

Os dois ZIPs de artefatos foram obtidos pela API normal do GitHub e conferidos contra seus digests. Os JSONs acima preservam os bytes dos membros `PDF-qpdf-crypto/report.json`; **não são reconstruções dos logs**. O JSON impresso depois de `FINAL QPDF CRYPTO DIAGNOSTIC REPORT` foi comparado estruturalmente com cada original como verificação adicional. Os artefatos completos continuam associados à execução enquanto vigorar sua retenção; executáveis e PDFs sintéticos não foram copiados para esta pasta.

A triagem de 26 entradas de texto não encontrou os padrões selecionados de tokens, URLs temporárias assinadas, valores de autorização, chaves privadas ou credenciais sintéticas da fixture. Os originais não foram redigidos. Essa triagem por padrões não garante a ausência de toda forma possível de segredo.
