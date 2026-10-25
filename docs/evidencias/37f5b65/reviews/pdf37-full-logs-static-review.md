# Revisão estática curta do coletor de logs 37f5b65

Arquivo: `/tmp/pdf_collect_37_logs.py`. Revisão de leitura em 2026-10-25; coletor não executado, nenhuma rede ou extração realizada, nenhum produto/documento do repositório alterado.

Foram encontrados dois defeitos concretos nos critérios automatizados de contagem. Eles não demonstram falha nos logs reais, ainda não coletados por esta revisão, mas podem produzir classificação indevidamente favorável:

1. **Cobertura nativa por etapa incompleta não é detectada.** O laço verifica somente os membros presentes no ZIP. Não exige a presença das quatro etapas de `expected_repeats` nem compara os Counters somados dessas etapas com o agregado. Um inventário contendo agregados com 44 grupos × 9 execuções, os três resumos Python e somente o log nativo de Build com duas execuções pode ficar sem `reviewIssues`, apesar de faltarem as três etapas nativas restantes. Correção sugerida: exigir exatamente a cobertura esperada de etapas, detectar duplicatas e comparar os multiconjuntos somados de inícios/aprovações por etapa com os agregados.

2. **Resultado Python de uma suíte pode capturar OK da suíte seguinte.** `python_suites` procura `OK` e `FAILED` nas cinco linhas seguintes e dá prioridade a `OK`. A sequência `Ran 1 test in 0.1s`, `FAILED (failures=1)`, `Ran 0 tests in 0.0s`, `OK` classifica a primeira como `status=passed`. Correção sugerida: considerar somente o primeiro resultado terminal da própria suíte, interromper no próximo `Ran` e reconhecer a linha inteira após retirar timestamp/ANSI.

Nos demais pontos solicitados, não identifiquei bloqueador concreto: identidade da fonte/run/tentativa e dois jobs é conferida antes/depois; o resultado terminal pode ser falha sem convertê-lo em sucesso; ZIP original tem limites de download, diretório central, quantidade, tipos, nomes, CRC e expansão; somente nomes agregados restritos são extraídos; o validador é comparado ao blob do commit exato antes de importar. O relatório exclui explicitamente aprovação cross, entrega privada e testes físicos/humanos.

## Verificação das correções

Os dois achados foram corrigidos pelo autor e a correção foi confirmada por nova leitura estática do script:

- Agora os Counters de inícios/aprovações somados por etapa são comparados aos agregados. Em run com sucesso, a cobertura de etapas deve ser exatamente o multiconjunto das quatro etapas esperadas, uma ocorrência de cada, e a distribuição de repetições permanece verificada. Jobs/etapas API sem sucesso também são registrados como divergência.
- O parser Python reconhece a linha inteira do resultado após remover timestamp/ANSI, interrompe a busca antes do próximo resumo `Ran` e aceita somente um resultado terminal. Um `FAILED` não recebe mais o `OK` da suíte seguinte; múltiplos resultados ficam não reconhecidos.

**Resultado final deste escopo: os dois defeitos relatados estão resolvidos; nenhum bloqueador concreto restante identificado nesta revisão focal.** O autor informou testes sintéticos e compatibilidade com os logs históricos 817; esses testes não foram reexecutados por este revisor. O script de coleta atual continua sem execução por esta revisão. Este parecer não confirma execução ou resultados da matriz.
