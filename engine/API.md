# Local engine API

`python3 engine/pdf_engine.py OPERATION INPUT... --output NEW_PATH` accepts JSON options through `--options` or, preferably, `PDF_OPTIONS_STDIN=1` and standard input. Passwords must use standard input. `--capabilities` reports the operation list and detected dependencies. Success writes one JSON object with `ok` and `output`; failures write JSON to stderr and exit nonzero; cancellation uses code `Cancelled` and exit 130.

## Preservation and cancellation

Inputs are never overwritten. Results are staged in a private temporary directory on the destination filesystem and published with an atomic no-replace primitive. Existing destinations and symlinks are refused, including creation races. Failed operations leave no final output. File publication uses hard links; directory publication uses macOS `renamex_np(RENAME_EXCL)` or Linux `renameat2(RENAME_NOREPLACE)`. Filesystems must support those primitives.

Existing PDF encryption is retained for PDF modifications. Merge, multi-input organize and split rebuild protection with AES-256, a supplied password and preserved permissions. Merged permissions are the intersection of protected inputs. An explicit output_password chooses the resulting credential; differing protected input credentials require it. Unlock is an explicit operation. PDF/A rejects encrypted sources because PDF/A cannot be encrypted: precede conversion with an explicit unlock. Non-PDF exports necessarily use the destination format's normal protection characteristics.

External converters run in a dedicated process group. Interrupting or terminating the engine terminates and reaps that group; temporary staging is cleaned. Operations become committed when atomic publication succeeds; cancelling after that point does not delete a completed result.

## Shared options

- `password`: input PDF password; `second_password`: second comparison input password when different. Merge/organize accept `input_passwords:["", "secret", ...]`, exactly one credential per input, and optional `output_password` (8–40 characters). Values must be sent through stdin, not command-line arguments.
- `pages`: one-based selector such as `1,3-5,8-6`; omission means all pages. `organize`, `extract-pages` and split groups preserve duplicate selections and ordering; other operations deduplicate. Repeated output pages have independent page objects, so a later edit to one copy does not change another.
- Coordinates are points from the upper-left of the visible, unrotated page, relative to its existing crop box. `rect: [x0,y0,x1,y1]` or `x,y,width,height` defines a bounded area. Rotated page bounds are derotated before validating edits.
- Text accepts `text,font_size,font,color,opacity,position,margin`; colors are `#RRGGBB` or RGB components 0–1. Supported `position` values: `top-left`, `top-center`, `top-right`, `center`, `bottom-left`, `bottom-center`, `bottom-right`. `font` uses PDF standard names (`helv`, `hebo`, `heit`, `tiro`, `cour`, etc.); overlays can use `font_file` for custom fonts. Unicode overlays and replacement text use MuPDF HTML shaping and its bundled fallback fonts; unavailable glyphs or text that cannot fit are refused. An explicit font file must contain every requested glyph. `rect` uses a bounded textbox; otherwise `x,y` overrides the baseline position.

## Operation-specific contracts

| Operation | Options / output |
|---|---|
| `merge` | Multiple PDFs, input order retained. One PDF output. Per-input credentials and explicit output credential as above. |
| `split` | Directory of PDFs. `groups:["1-3","4,6"]` optionally defines each result's pages; default one selected page per file. |
| `compress` | Lossless stream reorganization by default. `image_dpi` and JPEG `quality` enable image downsampling; masked images are preserved. Shared images retain resolution for their largest placement anywhere in the document; images also used by unselected pages are not recompressed. Size reduction is not guaranteed. |
| `word` | DOCX with styled text, images and detected tables. Reading order/layout are approximate. |
| `powerpoint` | `mode:"editable"` creates text/image objects; `mode:"image"` renders page images. Rotated pages transform text/image positions and rotations; mixed page proportions are centered without distortion. Editable mode does not reconstruct every vector effect. |
| `excel` | Detected tables or extracted lines in XLSX. Formula-like PDF text is escaped. |
| `office`, `odt`, `rtf` | LibreOffice PDF conversion, including ODT and RTF sources. XLSX supports `fit_width:true` and `orientation:"portrait"|"landscape"`; source workbook is copied before page setup changes. |
| `text` | New text overlay. Fails if text does not fit. |
| `edit` | `search,replacement,font_size,min_font_size`; replaces matched text, preserves overlapping graphics/images. Fails atomically if replacement cannot fit, rather than silently deleting text. |
| `image`, `signature` | `image` file path and placement rectangle; `opacity`, `overlay`. Signature is visual, not cryptographic. |
| `shape` | `shape:"rectangle"|"ellipse"|"line"`, rectangle, `color`, optional `fill`, `line_width`, `opacity`. |
| `jpg`, `png` | Directory; default renders selected pages with `dpi` 36–600. `png` supports `alpha:true` for a transparent background. `mode:"embedded"` extracts unique embedded images; PNG retains image transparency masks. `jpg` with `format:"png"` is an alias. |
| `txt` | Strictly decoded text (`encoding:"utf-8-sig"` default) to Unicode PDF with automatic pagination. Supports `paper`, `margin`, `font_size`, `landscape`/`orientation`; source markup is escaped. Over-wide ASCII tokens receive invisible wrapping opportunities; content that still exceeds page bounds is refused instead of cropped. Limit 10,000 pages. |
| `epub` | Reflows an unencrypted EPUB with MuPDF into paginated PDF. Supports `paper`, `margin`, `font_size`, `landscape`/`orientation`; does not remove DRM. |
| `csv` | CSV to PDF through a temporary safe-string XLSX and LibreOffice. Auto-detects comma/semicolon/tab/pipe separators or accepts `delimiter`; strict `encoding` defaults UTF-8 with optional BOM. Supports `fit_width` (true default), `orientation`/`landscape`. Source values never become spreadsheet formulas. Column widths and wrapped row heights are set to preserve cell contents. `max_column_width` defaults 60 (12–120 allowed); rows needing more than 400 points are refused with guidance instead of clipped. |
| `images` | Multiple images → PDF. Optional `paper:"a4"`, `margin`, `orientation` or `landscape`. Without page settings, preserves image page dimensions. |
| `watermark` | Text settings or `image` path/rectangle. |
| `numbers` | `start`, `format` with `{n}` and `{total}`, standard text placement. |
| `rotate` | `degrees`, multiple of 90. |
| `html` | Self-contained local HTML or HTTP(S) URL; Chromium. Local relative file resources are not resolved. Optional `paper`, `landscape`. |
| `protect` | `new_password` 8–40 characters, AES-256. |
| `unlock` | Known `password`, produces explicitly unencrypted PDF. |
| `flatten` | Bakes annotation and widget appearances into regular PDF page content; fields and annotations become noninteractive. `annotations` and `widgets` booleans both default true. Whole-document operation; preserves encryption. |
| `delete-pages` | Deletes selected `pages` ranges while preserving the remaining order. Refuses deletion of all pages and retains encryption. |
| `extract-pages` | Creates a PDF containing selected `pages` in the requested order, including explicit duplicates. Retains encryption. |
| `organize` | One or more PDFs; `pages` required, numbered across inputs concatenated in input order. Ranges, reverse ranges, duplicates and omissions. Per-input/output credentials supported; single-input metadata is retained. Multi-input document-level metadata/outline reconciliation is not attempted. |
| `repair` | Rewrites documents the parser can recover; does not promise recovery of arbitrary corruption. |
| `ocr`, `pdfa` | OCRmyPDF; `language` defaults `por+eng`. External language data required. PDF/A still needs independent validation for conformance claims. |
| `compare` | Two PDFs → textual diff. |
| `compare-visual` | Two PDFs → self-contained HTML with original, comparison and pixel difference images at 96 DPI. `compare` with `mode:"visual"` is an alias. |
| `redact` | `text` search or `rects` regions; removes page content plus overlapping widgets, annotations and links. Matched annotation/widget values on selected pages are removed too. Purges metadata, XML metadata, embedded-file name-tree attachments, JavaScript and thumbnails; matching outline titles become `[Removido]`. Existing pending redaction annotations cause refusal so unrelated marks are never applied accidentally. Content outside selected areas/pages, including other file-attachment annotations, still needs disclosure review. |
| `crop` | `margin` or `rect`; visual crop does not remove hidden content. |
| `forms` | JSON array of existing widgets including page/name/value/type/rect/choices/readonly. Radio groups produce one record with choices, selected value, and `buttons:[{page,rect,value}]`. |
| `form-create` | `fields:[{name,page,type,rect,value,choices,font_size,multiline}]`; types `text`, `checkbox`, `choice` (combo), `list` (single selection), `radio`. Names must be unique. Radio uses `choices:[{value,rect,page?,label?,label_rect?}]`, at least two unique values other than `Off`; one real AcroForm parent controls exclusive selection. Optional labels are inserted to the right and must fit. Text/combo/list widget appearances currently support Latin-1; unsupported alphabets are explicitly refused rather than substituted. This restriction does not apply to text overlays or radio export values. |
| `form-fill` | `values:{fieldName:value}`; matches existing names and rejects unknown names/choices, read-only fields and unsupported signature/push-button assignments. Radio accepts a choice string. Empty strings clear text/combo/list/radio values and their appearances. |
| `form-detect` | JSON `{heuristic:true,review_required:true,fields:[...]}` suggestions from vector blank boxes/lines. No raster OCR inference; review candidates before passing to `form-create`. |
| `markdown` | Heuristic headings, styled reading order, detected tables, self-contained images and links; exact semantic preservation is not guaranteed. |
| `layout-extract` | JSON array `[{id,page,rect,text,font_size,color}]`, page one-based. |
| `translate-layout` | `edits` same shape as extracted blocks, with translated `text`. Optional `source_text` rejects stale blocks; `min_font_size` default min(8, original size). Removes block text only, preserves images/vectors, Unicode layout with bounded shrinking. Overlapping blocks and text that cannot fit cause atomic failure. Translation itself occurs in native Apple Foundation Models, not this engine. |
| `workflow` | `steps:[{operation,options}]`, 1–64 stages; intermediate stages must output one PDF. Input `password`, including an explicit step override, propagates; merge/organize output_password changes it, protect changes it, and unlock clears it. Options for each stage must be JSON objects. |

Aliases: `edit_text`, `form_create`, `form_fill`, `compare_visual`, `delete`/`delete_pages`, `extract`/`extract_pages`.

This engine does not claim PDF reconstruction fidelity, certified signatures, AI correctness, scanner hardware support or GPU/Neural Engine acceleration. Those capabilities require separate native integrations and validation.
