# Escopo do ajuste do observador — após focal 2f3134a

O focal 2f3134a não concluiu medições nativas: encontrou AXToolbar, mas não os três controles selecionáveis. Este ajuste reutiliza os mesmos getters modernos e atributos legacy publicamente anunciados de AccessibilityAudit, além dos filhos de navegação deduplicados. A topologia real dos filhos diretos agora é registrada em cada Snapshot. Classes são evidência diagnóstica; não selecionam controles.

Não se inicia consulta AX ao próprio processo, não se ativa VoiceOver, não se amplia espera e não se modifica aparência, controles ou pixels. A seleção continua exigindo exatamente os três providers corretos e visíveis da mesma janela; os bounds tipados, identidades, aparência efetiva e contraste central mínimo3:1 continuam obrigatórios. Os sete PNGs e doze checks focais, assim como o contrato normal33PNG/7AX/2OCR, permanecem. MacPreview.swift não foi editado por este ajuste.

Somente depois do PNG de customization, uma observação opcional registra NSPopUpButton reais da janela: título, quantidade de itens, bounds nativos convertidos para janela/tela, hidden, alpha e aparência efetiva. O limite é64providers; excedê-lo registra erro. A lista vazia não prova inexistência de controles virtuais SwiftUI. Esses metadados não aprovam legibilidade do seletor Espaçamento ou do menu Restaurar e não substituem revisão da imagem original.

Validação local: git diff --check. Este Linux não possui Swift; compilação, seleção real de providers e resultado visual exigem novo focal nativo. Nenhuma melhora é declarada validada apenas a partir deste patch.

Hashes dos arquivos desta frente:

- `Sources/PDF/ToolbarRenderingAudit.swift`: `e18446d734d746ee1d6dcb0aea4d357599ffdf5209618a0d8d97e6c33941ba0a`
- `Sources/PDF/AccessibilityAudit.swift`: `608eb3c419f3d2332e34fc72cb925f7b6c7e1e2bcd5e2ceccaf014481951d303`
- `Sources/PDF/MacPreview.swift`: `949d02248e49abee7cf6dc96708c9bbd6a4d4a41119e9df3d2a0fbfee27a5860`
