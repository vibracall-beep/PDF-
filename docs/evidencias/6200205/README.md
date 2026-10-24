# Evidências de 6200205 — compilação aprovada, testes Python reprovados

A [execução 40129433128](https://github.com/vibracall-beep/PDF-/actions/runs/40129433128), tentativa 1, commit **`62002051d708eaec412218324db1dc05dd2ea001`**, terminou **reprovada nos dois sistemas**. A compilação passou nos dois SDKs. A instalação parou na suíte de núcleo Python, antes das integrações e dos smokes do aplicativo.

| Conjunto | macOS 26 | macOS 27 |
|---|---:|---:|
| Scripts | 119 aprovados + um skip · 20,813 s | 119 aprovados + um skip · 20,354 s |
| Compilação Swift | Aprovada | Aprovada |
| Núcleo Python | 311 métodos · 83,255 s | 311 métodos · 86,214 s |
| Métodos do núcleo sem falha | 309 | 309 |
| Métodos do núcleo com falha | Dois, com cinco registros de falha | Dois, com cinco registros de falha |
| Integrações, smokes e captura | Não executados | Não executados |
| Montagem e validação portátil | Não executadas | Não executadas |

O skip dos scripts exige `/dev/full` do Linux. O teste real de consenso de grupos de processos passou em ambos os Macs, incluindo os controles com líder zumbi e descendente vivo, dentro e fora do sandbox. Esse resultado não aprova o Java, o aplicativo ou a distribuição portátil.

## As cinco falhas pertencem a dois métodos

`test_pdfkit_and_office_cli_cancel_real_groups_and_release_descendant_locks` falhou nos quatro subcasos: drivers PDFKit/Office × SIGINT/SIGTERM. Em todos, a asserção de prontidão constatou que o descendente não havia criado seu marcador de posse do lock. A fixture escrevia `#!` seguido diretamente de `sys.executable`; o intérprete instalado está sob `Library/Application Support/PDF`, e esse caminho com espaços não funciona como intérprete de shebang. Uma reprodução isolada com intérprete existente em caminho com espaços confirmou a falha de início. Os controles de cancelamento não chegaram a ser exercitados nesses quatro subcasos; isso não deve ser registrado como cancelamento aprovado ou enfraquecido removendo a asserção.

`test_bundle_requires_fixed_regular_unprivileged_executable_without_path_override` comparou o caminho canônico devolvido pelo helper, iniciado por `/private/var`, com o caminho lexical da fixture, iniciado por `/var`. O log preserva a desigualdade. A correção do teste precisa comparar a mesma identidade e continuar recusando executáveis ausentes, permissões indevidas e links no arquivo final.

O `unittest` registrou **311 métodos e `FAILED (failures=5)`**. Quatro registros pertencem ao primeiro método e um ao segundo; portanto são **309 métodos sem falha e dois métodos reprovados**, não 306 aprovados e cinco métodos diferentes. As correções posteriores dessas fixtures não fazem parte deste resultado.

## Originais e limites

O [ZIP oficial da tentativa](actions-attempt-1-logs.zip) está preservado sem alterações: **157.636 bytes**, SHA-256 **`dfdf2a42e62a063a676b2bcf3b08b39b13b2b9b9c8b74591d0d1b29859045b37`**. O [manifesto derivado](provenance.json) registra commit, jobs, contagens, tempos, linhas relevantes e hashes dos dois logs completos de topo. Esses dois arquivos também coincidiram byte a byte com os logs obtidos pelos endpoints individuais de jobs. A API dos logs não fornece digest de origem; o hash identifica os bytes recebidos pelo endpoint oficial.

A varredura de **38 entradas textuais** do ZIP não encontrou os padrões verificados de tokens, URLs assinadas, cabeçalhos de autorização ou chaves privadas. Nenhum trecho foi ocultado ou alterado. Essa busca por padrões não garante ausência de todo valor potencialmente sensível.

**Não existem capturas, relatórios AX, PDF/JSON de OCR da prévia, resultados Vision/IA/benchmark ou smokes nativos desta rodada.** As quantidades previstas desses ensaios não foram tratadas como resultados. Os arquivos sintéticos da suíte Python e os controles C de scripts não substituem a execução do aplicativo nem a validação de instalação/atualização binária.
