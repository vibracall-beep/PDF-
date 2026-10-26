# Pacote fonte9d78ab9 — falha original e preflight local de árvore suja

Referência base `9d78ab9e38c8d4b0d63c98f18241d1735be7b3cb`. **Esta retenção não aprova um pacote distribuível.** O log original do root registra recusa por limite de tamanho. Depois, o produtor e consumidores modificados foram exercitados numa árvore suja baseada em9d; o novo limite permitiu a inspeção local, mas a guarda de identidade/árvore limpa continuou recusando entrega. Um pacote futuro gerado de commit limpo terá evidência separada.

| Evidência | Resultado preservado |
|---|---|
| Log original do root |`Os fontes excedem os limites do pacote de instalação.` |
| Preflight modificado |Árvore suja; não representa o commit base sem modificações |
| Carga reportada |147.879.150 bytes |
| TAR descomprimido reportado |149.350.400 bytes |
| gzip referenciado |77.212.676 bytes, SHA `92cf860022fa5269678ccc794f9d3887c0a3feb3d0e33d342ee7233180bf2308` |
| Contagem |1.508 arquivos de carga;1.510 membros incluindo BUILD-INFO.json e manifesto |
| Testes locais |18 instalação +18 arquivos +16 entrega =52 PASS |
| Guarda de entrega |Recusou `Source build identity or clean-tree evidence differs.` |
| Aprovação de pacote limpo/entrega |Não |

Os novos limites registrados no preflight são240MiB para a carga,256MiB para gzip/TAR expandido,272MiB para ZIP de transporte,32MiB por arquivo e10.000 membros. O JSON original contém valores em bytes, margens, hashes dos sete arquivos modificados e o resultado do extrator. A afirmação de que os1.510 membros materializados coincidem com os originais pertence à revisão do autor; esta retenção não repetiu extração ou geração de pacote.

Os sete arquivos pequenos do catálogo foram reconferidos por tamanho/SHA, e os52 testes foram recontados nos três logs originais. O TAR já existente foi somente lido em blocos para conferir seu SHA; **não foi copiado, aberto como TAR, extraído ou executado**. Os hashes atuais dos sete arquivos modificados coincidem com os da medição congelada. Nenhum arquivo de produto foi editado.

`originals/` conserva o log de falha e os logs/JSON congelados; `provenance/` conserva o catálogo do autor; `review.json` distingue verificações desta retenção das alegações dos relatórios originais. O log da falha original tem56 bytes e não registra por si só exit code ou transcript completo. Não se apresentou a geração suja como artefato limpo do commit9d.

Não há TAR77MB, extração, ZIP contendo checkout ou árvore de fontes aqui. Isso evita incorporar o próprio checkout novamente às evidências e inflar artificialmente os pacotes. A aprovação do focal de aparência9d não aprova este pacote, a recuperação ou a instalação; nenhuma aprovação foi transferida.

`inventory.json` registra bytes/SHA/origem. `SHA256SUMS` cobre os arquivos e o índice; confira com `sha256sum -c SHA256SUMS`.
