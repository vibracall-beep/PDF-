# Evidências de validação

## Linux: executado

- 61 testes funcionais do motor: aprovados, sem falhas ou testes ignorados.
- Oito testes com integrações externas: aprovados, sem falhas ou testes ignorados.
- Verificações incluem alteração de documentos, formulários, criptografia, redaction, preservação de originais, publicação sem sobrescrita, cancelamento de processos, conversões Office, HTML, OCR e PDF/A.
- Casos de tradução do motor verificam inserção de texto traduzido fornecido no teste; não demonstram geração pelo modelo Apple.
- PDF/A foi gerado e seu identificador XMP foi verificado. Isso não substitui um validador independente de conformidade.
- Sintaxe shell verificada. Código Swift analisado por parser; esse resultado não substitui compilação ou checagem de tipos no SDK Apple.
- Empacotamento de fontes verificado quanto a reprodutibilidade, checksums, exclusões e não sobrescrita.
- Novos casos incluem transparência PNG, EPUB, TXT Unicode e palavras de 5.000 caracteres sem perda, achatamento com aparência preservada, exclusão/extração protegidas, ODT, RTF e CSV com campos longos, multilinha e fórmulas tratadas como texto.
- Catálogo conferido: 49 identificadores únicos, nenhum comando de motor sem correspondência. Os 45 itens da terceira imagem estão mapeados em `FERRAMENTAS.md`; o leitor possui acesso permanente na barra lateral.

## macOS: execução real pelo GitHub Actions

O usuário autorizou GitHub Actions. `.github/workflows/macos.yml` usa runner Apple Silicon `macos-26`, compila o aplicativo, instala as dependências, executa os testes e valida o bundle assinado localmente. O fluxo também gera uma imagem da interface nativa para revisão. O instalador requer macOS 26 e Swift 6.2 ou posteriores.

`PDF --smoke-test` contém verificações de PDFKit, busca, formulários, persistência de anotações, renderização, Vision OCR a partir de página sem texto, melhoria de imagem Core Image/Metal, divisão e recuperação de contexto para IA, validação estrutural de questões, exportação PDF, criptografia, importação de capturas e publicação atômica.

A versão ampliada do commit `9884ed14006ba76546dbca4966f3daf7cd08acbb` foi aprovada integralmente na execução [40015439670](https://github.com/vibracall-beep/PDF-/actions/runs/40015439670), em 23/10/2026:

| Verificação | Resultado |
|---|---|
| Compilação Swift arm64 release | Aprovada |
| Motor Python | 61/61 aprovados |
| Integrações externas | 8/8 aprovadas |
| Arquitetura, assinatura ad hoc e dependências | Aprovadas |
| Runtime instalado e Chromium | Aprovados |
| Testes nativos antes/depois da ativação | Aprovados nas duas execuções |
| Ativação do aplicativo | Aprovada |
| Capturas nativas da tela inicial e do leitor | Geradas |
| Pacote de fontes e checksum | Gerados |

Ambiente real: macOS **26.6.2**, Xcode **26.6**, SDK **26.5**, processador **Apple M1 (Virtual)** com três CPUs. O contexto gráfico identificado foi **Apple Paravirtual device**. Esse ambiente confirma execução nativa arm64 e dos frameworks testados; não é uma medição em M4 físico nem comprova utilização do Neural Engine.

Artefatos da execução: [preview nativo](https://github.com/vibracall-beep/PDF-/actions/runs/40015439670/artifacts/12527928020) e [fontes](https://github.com/vibracall-beep/PDF-/actions/runs/40015439670/artifacts/12528422243). SHA-256 do pacote dessa execução: `9139827c73c170a235e8d5744ec9928e05b74478f05e06238c5247aa4d475441`. A revisão visual do preview depende do acesso ao host de download dos artefatos; gerar o arquivo não equivale a inspecioná-lo.

Scanner físico, iPhone/Continuity Camera, respostas Foundation Models, exportação real pelo Pages e desempenho no hardware do usuário requerem dispositivos/aplicativos/capacidades disponíveis no ambiente de validação; um teste de disponibilidade não comprova a execução dessas funções. O acesso ao Sign.com é uma abertura de serviço externo, sem simulação de integração com conta ou API.

## Uso de memória observado em Linux

A comparação visual e a exportação Markdown passaram a gravar partes da saída à medida que são produzidas. Em uma amostra de 32 páginas de 400 × 400 pontos, com uma imagem RGB de ruído de 400 × 400 pixels reutilizada e uma linha de texto por página:

| Operação | Pico de RSS antes | Pico de RSS depois |
|---|---:|---:|
| Comparação visual do arquivo consigo mesmo, 96 DPI | 282.732 KiB | 69.884 KiB |
| Markdown com imagens incorporadas | 101.044 KiB | 61.144 KiB |

Medição por processos separados com `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss`, Linux x86_64, Python 3.12.14, PyMuPDF 1.26.5 e Pillow 12.0.0. Os números foram registrados na saída das ferramentas durante o desenvolvimento; não há log de RSS arquivado no repositório. A comparação é entre a implementação acumuladora de `953be71` e a implementação em fluxo de `2f8a853`.

Os arquivos antes/depois foram novamente comparados por SHA-256: HTML de 68.608.827 bytes (`ddfd7e3c141a05eb172c29db72a4863338ea2879c4481535839f1be432f0a3fa`) e Markdown de 20.509.892 bytes (`89ddcbd236f81266193922bc691b79042f513faf96af356a0130f958164ebf85`) são idênticos. Os hashes demonstram equivalência dessa saída, não validam sozinhos as medições de memória. Estes resultados não são benchmarks M4 nem medições do Neural Engine.

## Alcance da entrega

O instalador de fontes foi executado com sucesso no runner macOS. A instalação recompila e prepara o runtime no próprio computador; não existe uma alegação de bundle portátil ou notarizado. Os comandos estão em `INSTALACAO.md`. O usuário pediu para testar somente após a conclusão: as verificações de desenvolvimento foram realizadas pelo processo de implementação, sem transferi-las ao usuário.

Compatibilidade visual e execução específicas em **macOS 27.0.1**, equipamentos físicos, Apple Intelligence e Pages permanecem fora das evidências disponíveis. Portanto, não se declara validação total de todos os requisitos originais nem uma versão universalmente livre de erros.
