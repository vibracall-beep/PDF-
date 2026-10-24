# Entrega verificada em rascunho privado

A [execução 40143091839, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40143091839), controle `3c81e0bb9d3407f9b3cca5e51cc2b8dd1b130a1f`, terminou **com sucesso nos três jobs**. O pacote e suas evidências foram retidos no **rascunho 423043552, com 71 assets**, e todos os arquivos enviados foram baixados novamente e conferidos pelo fluxo de entrega.

**[Abrir o rascunho autenticado do proprietário](https://github.com/vibracall-beep/PDF-/releases/tag/untagged-46d8b6e9889cc9181621)**. Essa é a URL real retornada pelo GitHub. O rascunho exige acesso autenticado e **não foi publicado como release pública**.

| Identidade | Valor |
| --- | --- |
| Aplicativo | `437a8f4d6bb6ebb003859f769e3756fce30c9da3` |
| Matriz de origem | [40137438618](../437a8f4/README.md) |
| Binário26 executado no27 | [40141728214](../cross-437a8f4/README.md), controle `6daf46294b10f35ec8252fd473f1d0865cd4bf8f` |
| Tag do rascunho | `delivery-437a8f4d6bb6-40137438618-40141728214` |
| Tar preservado | 1.448.521.887 bytes, sem recompilação ou modificação |
| Assets | 71, inventário exato e leitura de volta aprovada |

## Arquivos principais e hashes

| Asset | ID | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `PDF-arm64.tar.gz` | 673587240 | 1.448.521.887 | `7dabd68ffcc1b65ea551efd51bb17f9194bb6d3990261f6c52e33735d96cb7ad` |
| [install-binary.sh](install-binary.sh) | 673584998 | 3.344 | `53ecfd803797d72111a0c51050a49a0db75d00dc310c8066a35888400509a211` |
| [delivery-provenance.json](delivery-provenance.json) | 673589140 | 162.577 | `44b053192569c6d46b24bb84c4153589e6a9c018e7be791f610d7e724735c35d` |
| [DELIVERY-SHA256SUMS](DELIVERY-SHA256SUMS) | 673589170 | 6.698 | `cdd94465a7064abfb4046848ab89bc625c8f111a8731d1ef7aee18991d69299b` |
| [INSTALLATION.txt](INSTALLATION.txt) | 673589117 | 980 | `844c298adf69e1cd8348caa09a288e8541c1d7b775d00f33915d4bfaa5d15dba` |

O instalador é byte a byte igual ao validado na matriz de origem. O tar cabe em um único asset; a entrega não precisou dividi-lo. As [instruções gerais de instalação](../../INSTALACAO.md) incluem a conferência do script antes da execução. O arquivo `INSTALLATION.txt` acima é a cópia original das instruções do rascunho.

## O que foi conferido

O fluxo autenticou a conclusão da matriz e do cruzamento, seus commits, o SHA independente do tar e os artefatos do mesmo repositório. Comparou o manifesto interno com o publicado, vinculou o instalador ao código-fonte autenticado e verificou os recibos da GUI instalada. O pacote, os originais e os avisos de terceiros foram preservados; não foi acrescentada uma licença para o aplicativo nem alterada a assinatura ad hoc.

Depois do envio, o fluxo verificou **o inventário exato dos 71 assets e os bytes de cada um**, incluindo o tar. A conclusão registrada aparece no [resultado extraído do log original](pipeline-result.json), cuja origem é o [ZIP oficial da tentativa](attempt-1-logs.zip). O [manifesto original da entrega](delivery-provenance.json) mantém a cadeia matriz → binário → cruzamento → arquivos enviados.

Nesta coleta local posterior foram baixados **somente cinco controles pequenos**, confrontados com os digests do GitHub e `DELIVERY-SHA256SUMS`. O inventário completo coincidiu com a procedência, e **65 assets também coincidiram com originais locais já autenticados**. O tar grande **não foi baixado novamente**: sua leitura de volta pertence ao fluxo aprovado, e seu hash já havia sido calculado independentemente na coleta da matriz. Essa distinção consta na [verificação local](local-verification.json).

Os controles de recomposição executaram **16 testes no macOS26 (1,132 s)** e **16 no macOS27 (1,684 s)**, usando Bash e utilitários do sistema, sem rede. No job de entrega passaram três suítes de **41/14/9 métodos**, em **3,756/0,202/0,018 s**. São verificações da entrega, separadas dos 491 métodos da matriz principal e dos testes cruzados; não foram somadas para inflar a cobertura do aplicativo.

## Originais, derivados e limites

- [ZIP oficial dos logs](attempt-1-logs.zip): **41.707 bytes**, SHA-256 `e14b789d779f6c2b072f3f19d6ea73da834755bb93381297b7ffd09060ab7764`. Os três logs completos recebidos por job são idênticos aos membros de topo desse ZIP.
- [Resposta original da API da release](release-original.json), incluindo estado de rascunho, URL real e assets.
- Cinco assets pequenos originais: os quatro controles apresentados na tabela, além do [relatório original de validação da distribuição](distribution-validation.json).
- Derivados locais: [inventário dos assets](asset-inventory.json), [verificação](local-verification.json), [contagens por linha dos logs](final-counts.json) e [resultado do fluxo](pipeline-result.json).
- [Procedência desta coleta e hashes de cada arquivo](provenance.json).

Foram preservados **sete originais e quatro derivados**. Os bytes originais não foram reformatados ou redigidos. A triagem de 33 entradas de texto não encontrou os padrões selecionados de tokens, URLs temporárias assinadas, valores de autorização ou chaves privadas; essa triagem não garante ausência de toda forma possível de segredo.

Esta etapa comprova a retenção dos bytes após os testes especificados. Ela não acrescenta medição de M4 físico, uso da Neural Engine, energia, VoiceOver humano, dispositivos externos ou serviços reais com credenciais. Os relatórios de origem continuam registrando a indisponibilidade de Apple Intelligence nos runners e os limites do OCR. A assinatura permanece **ad hoc, sem notarização Apple**. O estado final aqui documentado é **rascunho privado verificado**, não publicação pública.
