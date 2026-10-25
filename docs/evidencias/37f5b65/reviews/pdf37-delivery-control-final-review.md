# Revisão final independente do controle de entrega

Revisão estática em 2026-10-25, para o produto `37f5b65` e a matriz `40239018570`. Não constitui aprovação dessa matriz, do cross ou da futura entrega: seus resultados completos precisam ser autenticados pelos controles existentes.

**Resultado: nenhum bloqueador concreto identificado na integração final dos coletores.**

Escopo revisado: `/tmp/pdf_collect_scene_delivery.py`, seus requisitos, formatos produzidos por `/tmp/pdf_collect_scene_binary.py` e `/tmp/pdf_collect_scene_cross.py`, e controle de entrega `d83cccbe5c493e42f522530f7972ec9e15d8ecfd` (`deliver_binary.py`, `delivery_lifecycle.py`, `delivery_archives.py` e workflow). O SHA-256 do coletor confere: `d429887cf6d10728a6757aa57abbd6888fc5cecf64af42025d802977711e14dc`. Os 17 hashes fixados foram comparados aos objetos Git locais do controle revisado, sem divergências. Os quatro arquivos de controle acima permanecem sem diferenças em relação a d83.

## Pontos verificados

- O estado binário esperado é o objeto `{schemaVersion, configuration, attempts}` efetivamente escrito pelo coletor atual. O registro selecionado exige origem, tentativa, job macOS 26, validação concluída, medição de todos os arquivos contra o manifesto e ausência de erro. Seus quatro metadados são rehashados; o tar grande permanece dentro do ZIP e não é reaberto pelo coletor de entrega.
- O estado cross esperado é a lista de dois registros atuais, com `artifactID`, `archive:{bytes,sha256}` e `files` como objeto. Configuração, resumo, fonte, controlador, job, tentativa, tar e flags GUI/lifecycle são vinculados; a normalização não fabrica flags de um formato antigo.
- A política `window-lifecycle-v1` e a proveniência de schema 2 são obrigatórias. São autenticados e revalidados três ZIPs distintos de lifecycle, com inventários 6/6/3 e limites de extração. A evidência revalidada precisa corresponder integralmente à proveniência da entrega.
- Os hashes do executável e Info.plist da execução cross são vinculados ao manifesto do tar entregue. Os executáveis early/installed compilados na fonte não são falsamente equiparados ao binário portátil, preservando diferenças legítimas de assinatura e empacotamento. O plist continua vinculado à fonte autenticada.
- Os três runs e seus jobs, tentativas, etapas, eventos, repositório e commits precisam estar completos com sucesso. O controle de entrega autentica os artefatos de origem e seus intervalos de jobs. O coletor só aceita um resultado final de entrega presente no log completo do job correspondente e reconfirma identidades/estado dos runs e assets ao terminar.
- O inventário exige nomes exatos, não somente contagem. As 76 entradas aplicam-se ao contrato de tar único. Entrega dividida recusa antes do primeiro GET se a coleta binária anterior não contiver hashes de partes medidos do tar autenticado; o escritor atual não produz essa aprovação automaticamente.
- O recibo distingue a releitura de todos os assets pelo workflow aprovado da coleta independente limitada a controles pequenos, três ZIPs lifecycle, logs e metadados. Não há alegação de nova leitura/download do tar, avaliação humana ou medição física de M4/Neural Engine.

## Pré-condições preservadas

Antes de despacho cross/entrega ou coleta final, o responsável precisa verificar o sucesso integral da matriz final e preencher os IDs, tentativas, commits completos, artefato e hash/tamanho realmente autenticados. Os originais e recibos native/cross devem existir nos diretórios dedicados previstos. O coletor não substitui esses passos nem aprova matrizes parciais. Os objetos Git locais dos controladores e da fonte precisam corresponder aos subconjuntos fixados; mudanças exigem nova revisão.

Não foram executados o coletor, consultas de rede, downloads, despachos ou mutações de releases. Nenhum arquivo do repositório foi alterado por esta revisão. A verificação realizada foi leitura estática e comparação local de hashes; não equivale a execução ponta a ponta da entrega.
