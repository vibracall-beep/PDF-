# Originais sintéticos CoreGraphics / PDFKit

Estes dois PDFs são os bytes originais de `PDF-qpdf-crypto/fixtures/plain.pdf`,
extraídos dos artefatos autenticados da execução GitHub Actions
[40133464239, tentativa 1](https://github.com/vibracall-beep/PDF-/actions/runs/40133464239),
commit `55eab2ed4c2e323b01faa91f1cab4b2bd421f6e1`.
A fonte é `diagnostics/QPDFCryptoFixture.swift`: CGContext, NSFont.systemFont,
NSColor.black, seguido de serialização PDFKit. São documentos sintéticos, sem
conteúdo do usuário. Os ZIPs foram conferidos contra os digests da API GitHub.

| Arquivo | Artefato | SHA-256 do ZIP | SHA-256 do PDF |
|---|---|---|---|
| macos-26.pdf (7512 bytes) | 12575841661 | aa823dee9b3879cdf3ac0eb3012a05d56a415d2b0436d51326faab237c78d0cd | 396a5c61a8497d47d39b78fb4751be67e6193b98ddab14c822f0f71d73707df1 |
| xcode-27.pdf (7492 bytes) | 12575184841 | 4da77e0e214ec32826207b3fcba969b2a44e6d4322ccbceb998dd5491d2da9f8 | c84bf9016b70a1b39d0aa4b7c3f534a46d6e873c73e96d7f51220e12fccbd6ee |

Os testes mantêm esses originais imutáveis. Variantes temporárias trocam somente
`/Cs1 cs 0 sc` por `/Cs1 cs 0.4 sc` para provar preservação além do preto;
outras variantes acrescentam página independente/recorte parcial, explicitamente.
O perfil original é Generic Gray Gamma 2.2, SHA-256
`73d504558e7d03ef4ff2676ba62c7553ee5bd856b45da2d330e33e012ad61fb3`.

A recomposição pode requerer substituição consentida de fonte: o nome que MuPDF
expõe é truncado, e as métricas/kerning diferem do recurso original. Os testes
comprovam perfil, componentes, cor renderizada e preservação fora da área; não
alegam geometria de glifos idêntica, fidelidade tipográfica irrestrita ou aprovação
do aplicativo pela antiga execução de diagnóstico.
