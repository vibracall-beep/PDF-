# a0a3c0c — controle nativo aprovado; compilação reprovada

[40129073067](https://github.com/vibracall-beep/PDF-/actions/runs/40129073067), tentativa 1, fonte `a0a3c0c94e17550d2b5042390e7487556da16323`. Ambos os sistemas aprovaram **120 métodos de scripts: 119 aprovados e um skip Linux**, em 26,578 s no macOS 26 e 23,850 s no macOS 27. O novo método compilou o helper de produção e exercitou os quatro controles zumbi/vivo × irrestrito/sandbox; não foi ignorado.

A compilação reprovou em `PDFApp.swift:136`: o SDK exige `CFRunLoopMode.defaultMode` no lugar de `kCFRunLoopDefaultMode`. O aviso da checagem física de thread em contexto assíncrono foi corrigido usando `pthread_main_np`, preservando o guard; o `try` redundante do teste Pages foi removido. O diagnóstico legado Vision conserva uma chamada obsoleta deliberada, distinta da política de produção.

Não houve núcleo/integrações instalados, smoke, janela, OCR ou validação portátil dessa rodada. O resultado do helper isolado não aprova Java nem o bundle completo. [ZIP oficial sem alteração](actions-attempt-1-logs.zip) e [tamanho/hash/procedência](provenance.json). As correções exigem nova execução.
