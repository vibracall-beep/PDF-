# Revisão dos logs oficiais — 81769db

Execução 40229486932, tentativa 1, fonte 81769dbfcd1ce87d06cfd5424d8d5fbcd4d19ca5. O ZIP original foi obtido pela API autenticada; identidade e sucesso dos dois jobs foram reconfirmados antes e depois. O GitHub não fornece digest independente para esse endpoint de logs; o SHA-256 aqui identifica o arquivo recebido, com CRC e limites de todos os membros conferidos.

Por Mac: 143 testes de scripts (142 aprovados e um skip Linux /dev/full), 510 testes de núcleo e 60 integrações aprovados: 712 aprovações Python, 713 casos incluindo o skip. São 43 grupos nativos distintos executados nove vezes por plataforma, totalizando 387 aprovações de grupos por Mac; não são 387 grupos distintos.

As nove execuções nativas se distribuem em duas no instalador de fontes, uma na validação instalada, uma no isolamento portátil e cinco na instalação/atualização do binário. Ambos os logs registram duas instalações validadas e recusa do checksum adulterado. Os seis flags de validação foram conferidos nos relatórios originais dos binários já autenticados pelo coletor do root.

Os FAILED do PDFKit bruto são diagnósticos de referência: nove no macOS26 e 27 no macOS27. Não são saídas publicadas pelo produto. As verificações estruturais das saídas tratadas passaram. Os seis avisos genéricos CoreGraphics em cada Mac aparecem entre a recusa deliberada de stream inválido e a normalização que passa no qpdf. Não houve Native check failed ou marcador de erro fatal de etapa.

Existem avisos de compilação por retorno de drop não utilizado e pelo uso diagnóstico de usesCPUOnly obsoleto. O probe appintentsmetadataprocessor --help rejeitou opções uma vez em cada Mac; a verificação final dos metadados do aplicativo passou separadamente. Esses avisos não foram apagados dos originais.

Apple Vision passou no macOS26 e falhou na capacidade nativa do runner macOS27; neste, OCR funcional usou Tesseract. IA gerativa local ficou indisponível nos dois runners virtuais. Esta revisão não aprova hardware M4 físico, utilização NPU/GPU, energia, VoiceOver humano ou notarização Apple.

Arquivos: collector-attempt-1-logs.zip (original integral), collector-attempt-1-logs/*.txt (dois logs completos), collector-counts-complete-logs.json (contagens e membros), collector-log-review.json (classificação e referências).
