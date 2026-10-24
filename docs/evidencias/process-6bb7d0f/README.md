# Diagnóstico de grupos de processos — 6bb7d0f

A [execução 40128200878](https://github.com/vibracall-beep/PDF-/actions/runs/40128200878), tentativa 1, commit **`6bb7d0fd843c3da2df89ac48a6cd8e23e06d1bf2`**, aprovou os controles sintéticos nos dois sistemas. **Não executou Java/veraPDF nem aprovou o aplicativo ou o pacote portátil.** A [falha integrada de ecae663](../ecae663/README.md) continua sendo um resultado distinto.

Foram conferidos **oito controles reais**, quatro em cada runner Apple M1 Virtual. Cada controle criou um grupo próprio, observou o término do líder sem recolhê-lo e comparou as consultas nativas com uma consulta independente de membros feita fora do sandbox. Os relatórios originais registram `measurementComplete=true`, `candidateControlMatched=true` e `productApproved=false`.

| Controle, repetido nos dois sistemas | Estado inicial | Consulta nativa: todos zumbis | SIGTERM / SIGKILL | Consulta por `/bin/ps` dentro do controle |
|---|---|---|---|---|
| Sem sandbox, líder sozinho | Líder `Z` | Sim, nas duas APIs | Ambos recusados com `EPERM` | Executada |
| Com sandbox, líder sozinho | Líder `Z` | Sim, nas duas APIs | Ambos recusados com `EPERM` | Execução recusada com `EPERM` |
| Sem sandbox, descendente vivo | Líder `Z` + descendente `S` | Não, nas duas APIs | Ambos aceitos; pipe fecha após KILL | Executada |
| Com sandbox, descendente vivo | Líder `Z` + descendente `S` | Não, nas duas APIs | Ambos aceitos; pipe fecha após KILL | Execução recusada com `EPERM` |

No caso com descendente vivo, ele confirmou o recebimento de TERM e permaneceu vivo até KILL. O recolhimento posterior do líder preservou seu status **7** em todos os controles. A composição observada por `libproc` e `sysctl` coincidiu com a consulta externa nos oito casos. O `/bin/ps` desses runners pertence a root e tem modo **04755**; sua execução foi recusada dentro do sandbox. Isso não torna toda falha de execução uma prova de ausência de processos.

O diagnóstico também distingue as variantes da API: `proc_pidinfo(PROC_PIDTBSDINFO, arg=0)` não devolveu os dados do zumbi, enquanto `arg=1` devolveu a estrutura completa de 136 bytes. A consulta `sysctl(KERN_PROC_PGRP)` usou o tamanho de estrutura de 648 bytes do SDK. O grupo com um membro vivo continuou classificado como vivo pelas duas consultas. **`EPERM` isolado não autoriza ignorar um processo:** esta evidência não cobre grupos inacessíveis, leituras incompletas, identidade incerta ou uma integração posterior sem esses controles.

## Originais e procedência

Esta pasta preserva três arquivos originais, sem reformatar relatórios nem alterar logs:

- [Relatório macOS 26](macos-26/report.json), artefato Actions **12572764854**.
- [Relatório macOS 27](xcode-27/report.json), artefato Actions **12574065323**.
- [ZIP oficial dos logs da tentativa](actions-attempt-1-logs.zip), **34.602 bytes**, SHA-256 **`23368173ea654ed1fb48ff2c4e7a4cf2a76c0771f4b9c2eacea60cc810e5d7b5`**.

O [manifesto derivado](provenance.json) registra origem, commit, IDs, tamanhos, hashes, comparação independente dos controles e limites. Os dois ZIPs de artefatos foram conferidos contra os digests fornecidos pelo Actions; o ZIP oficial dos logs não tem digest fornecido pela API, portanto seu hash identifica os bytes recebidos. Os executáveis Mach-O foram conferidos contra os hashes dos relatórios, mas **não foram copiados para o repositório**.

O campo original `policySHA256` identifica a string passada a `sandbox-exec -p`. O arquivo `production.sb` no artefato contém essa string mais uma quebra de linha final. Ambos foram conferidos separadamente; seus hashes diferentes estão identificados no manifesto. Não foi alterado o relatório para fazê-los coincidir.

A varredura de **50 entradas textuais** dos artefatos e logs não encontrou os padrões verificados de tokens, URLs assinadas, cabeçalhos de autorização ou chaves privadas. Nenhuma redação foi aplicada aos originais. Essa busca por padrões não prova ausência de todo valor potencialmente sensível. A aprovação do diagnóstico não substitui a matriz integrada de processos, Java, encerramento, captura e instalação portátil, nem um ensaio em M4 físico.
