# Independent validation fixture

`pdfua1-minimal.pdf` contains an original synthetic heading and paragraph, no
personal documents or credentials. It was generated locally with
LibreOfficeDev 26.8.0.0.alpha0 (`2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`),
Writer PDF export with `PDFUACompliance=true` and `UseTaggedPDF=true` from a
DOCX with title metadata and `en-US` document language.

SHA-256: `f48a7b685c95bbf731854fee43aa507a569bc718d7ccddd3d54db7f4468fcf09`.

veraPDF 1.30.3 independently passed this sample against PDF/UA-1: 106 rules,
288 checks, zero failures. This fixture exercises a **positive automatic**
validation path. It does not establish that all generated documents are
accessible or replace the human checks required by PDF/UA.
