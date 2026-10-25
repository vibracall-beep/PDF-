# Auditoria independente de escopo e preservação — 37f5b65

Produto: `37f5b65e35a9f70c716cfcd64db7ba69837f5c21`. Documentação: `e4f6c056058d3482b18cdcc24011ccdc96327004`. Revisão estática, somente leitura; nenhum arquivo do produto/documentação alterado.

Não encontrei novo bloqueador concreto de ligação de ferramentas nem retirada de função. Isso não significa atendimento integral, execução comprovada de todos os percursos ou entrega definitiva. O pacote/cross/entrega precisam de seus gates próprios.

71 IDs únicos; 54 legados preservados; mesma ordem de817; 33 rotas nativas/navegação e38 configurações resolvidas no motor; 71 linhas na matriz sem omissões. 362 links locais dos quatro documentos existem. O leitor permanece fora dos71 cartões.

O motor `engine/` não mudou entre81769db e37f5b65. HEAD e4 difere de37 somente em documentação. As alterações de produto posteriores são ciclo/apresentação da janela, comandos, auditorias e instalação/CI; essa identidade de implementação não substitui validação do pacote novo.

## Achados e limites que impedem declarar tudo definitivo

- **D01 — current_status_omission_not_false_historical_result**: MATRIZ-0.7.md ainda abre com o resultado6f0a68b e diz que a correção está em implementação, sem incorporar a fonte37f5b65. O histórico é correto e não deve ser apagado; falta consolidar o resultado final37 quando a matriz/portátil/cross/entrega realmente concluírem. Evidência: [docs/MATRIZ-0.7.md:3](/workspace/PDF-/docs/MATRIZ-0.7.md:3), [docs/MATRIZ-0.7.md:7](/workspace/PDF-/docs/MATRIZ-0.7.md:7).
- **L01 — known_implementation_limits**: Requisitos originais de tradução preservando universalmente fontes/layout, edição abrangente de objetos, personalização irrestrita e conformidade PDF/X completa não estão integralmente implementados. As recusas conservadoras documentadas são corretas, mas não satisfazem todos esses casos. Evidência: [docs/REQUISITOS.md:68](/workspace/PDF-/docs/REQUISITOS.md:68), [engine/print_inspection.py:687](/workspace/PDF-/engine/print_inspection.py:687), [engine/pdf_content.py:318](/workspace/PDF-/engine/pdf_content.py:318).
- **L02 — hardware_human_external_pending**: M4 físico/energia/NPU, modelo Apple real em português, VoiceOver humano, scanner/Pages/Atalhos externos e produção CA/TSA/provedor/doisMacs não são comprovados pela revisão estática nem pela existência de testes. Evidência: [docs/MATRIZ-0.7.md:142](/workspace/PDF-/docs/MATRIZ-0.7.md:142), [Sources/PDF/LocalAIAudit.swift:25](/workspace/PDF-/Sources/PDF/LocalAIAudit.swift:25).
- **L03 — known_scope_boundary**: Recuperação cobre fronteiras definidas; drafts das ferramentas continuam em memória. Não há cobertura universal de interrupções em todos os writes. Evidência: [Sources/PDF/ToolDraftRegistry.swift:4](/workspace/PDF-/Sources/PDF/ToolDraftRegistry.swift:4), [docs/MATRIZ-0.7.md:146](/workspace/PDF-/docs/MATRIZ-0.7.md:146).
- **L04 — delivery_not_yet_approved_here**: A coordenação informou37early+installedGUI nos dois sistemas e44gruposstandalone aprovados, com portátil em curso. Esta revisão não consultou nem extrapolou CI e não aprova pacote/cross/entrega antes de seus resultados próprios.
- **L05 — known_unsupported_appearances**: Formulários possuem nomes/valores byte-exatos, mas criação/preenchimento de aparências exige glifosLatin-1 disponíveis e não oferece implementação geral XFA/JavaScript. Não confundir conjunto de tipos de campo com compatibilidade universal. Evidência: [engine/pdf_engine.py:1218](/workspace/PDF-/engine/pdf_engine.py:1218), [docs/MATRIZ-0.7.md:66](/workspace/PDF-/docs/MATRIZ-0.7.md:66).

MELHORIAS é explicitamente um snapshot5a11c07; AMPLIACOES preserva o histórico0.6 e aponta à auditoria0.7. Não tratei os limites antigos desses snapshots como regressões atuais. REQUISITOS continua sendo a especificação integral do usuário.

## Sete áreas prioritárias

| Área | Estado da implementação | Limites preservados |
|---|---|---|
| Editor e conversões | partial — Texto, imagens e vetores delimitados; reconstrução Office; auditoria de reexportação. | Edição de objetos gerais, curvas/CMYK/estados gráficos arbitrários, notas/estilos/layouts universais e tradução integralmente fiel não estão concluídos. |
| OCR e acessibilidade | partial — Tesseract/Vision, revisão de palavras, geometrias/tabelas e edição real de tags/associações. | Documentos difíceis/manuscritos e reconstrução semântica automática arbitrária não cobertos; VoiceOver humano pendente. |
| Recuperação | partial — Gerações cifradas, falhas/SIGKILL em fronteiras enumeradas, diário do atualizador e da biblioteca. | Não cobre cada gravação/power-loss; rascunhos de editor/OCR/acessibilidade são memória e se perdem após crash. |
| Personalização | implemented_with_limits — Ferramentas, modos de visualização, temas, Liquid Glass, animações, leitor, saídas, menus internos, barras, atalhos e perfis. | Menus do sistema/atalhos reservados e semântica/metadados arbitrários dos arquivos não têm personalização irrestrita; PNG não prova animações/interação. |
| IA e M4+ | implementation_present_target_validation_pending — Apple Silicon arm64, Core Image/Metal, NaturalLanguage/FoundationModels, orçamento adaptativo e benchmark reproduzível. | Geração real em português depende de modelo elegível; M4 físico, energia/Neural Engine e vantagem sobre concorrentes não medidos. |
| Assinaturas e integrações | implemented_with_external_dependencies — PAdES B-B/T/LT/LTA, OCSP/CRL, envio/status/download por Dropbox Sign, Atalhos/Finder, biblioteca sincronizada e scanner. | Produção CA/TSA/provedor, scanner/iPhone, Pages real, interface Atalhos e dois Macs físicos ainda dependem de ensaio; Sign.com é link. |
| Impressão profissional | partial — Checks estruturais independentes, limites ICC, avisos de separações/sobreimpressão e cobertura renderizada; candidato PDF/X-3. | conformant=null, sem certificação ISO PDF/X completa nem prova física de cor/separações/overprint para qualquer documento. |

## Dez melhorias

| Nº | Melhoria | Estado / limite |
|---|---|---|
| M1 | Abas e dois documentos | implemented_with_limits: Sessões/posição/zoom e leitor comparativo preservados. Interação humana integral e documentos arbitrariamente grandes não comprovados. |
| M2 | Recuperação automática | partial: Snapshots/estado/criptografia e ensaios de falhas reais ampliados. Não cobre todos os writes nem rascunhos de ferramentas após crash. |
| M3 | Assinaturas e verificação | implemented_with_external_dependencies: PKCS12/PAdES e confiança/revogação/tempo separados. Certificados e serviços de produção não ensaiados; qualificação jurídica não inferida. |
| M4 | PDF/A independente | implemented_with_limits: veraPDF oficial valida bytes/perfil e conserva relatório. Conformidade vale apenas para arquivo/perfil testado. |
| M5 | Benchmark M4+ | target_validation_pending: Medição implementada, identificando hardware/backend. M4 físico/energia/NPU/concorrentes não medidos. |
| M6 | Editar anotações existentes | implemented_with_limits: Seleção, geometria, estilo, undo/redo e serialização. Tipos enumerados; drag/alças/VoiceOver não integralmente ensaiados. |
| M7 | Tabelas e formulários OCR | partial: Grades/mesclas/alinhamento e revisão de campos. Tabelas complexas/manuscritos/semântica não universais. |
| M8 | Busca semântica e referências | implemented_with_model_dependency: Ranking lexical/embedding e referências verificadas. Referência literal não prova inferência; geração real pendente. |
| M9 | Lotes com exportação terminal | implemented_with_limits: Etapas PDF e exportações Word/Excel/PPT/Markdown/imagens. Allowlist preserva exigências de revisão; nem toda ferramenta pode entrar automaticamente. |
| M10 | PDF/UA e VoiceOver | partial: veraPDF UA e árvore AX; correção estrutural separada. VoiceOver humano/semântica assistiva não certificados. |

## Dezessete ampliações

| Nº | Melhoria | Estado / limite |
|---|---|---|
| E1 | Editor visual original | partial: Objetos/tipografia/estados suportados são delimitados; não há edição universal de parágrafos/vetores. |
| E2 | Conversões fiéis | partial: DOCX/XLSX/PPTX e reexportação existem; reconstrução geral de notas/layouts complexos permanece parcial. |
| E3 | Instalador autocontido/atualização | pipeline_validation_pending: Implementado, hash/diário/rollback/ad hoc; portabilidade e entrega da fonte37 ainda em curso nesta auditoria. |
| E4 | Recuperação em falhas | partial: SIGKILL/ENOSPC/fronteiras enumeradas, sem cobertura de todos os writes ou falha elétrica. |
| E5 | Histórico de documentos | implemented_with_limits: Versões importadas/adicionadas na biblioteca; não captura cada tecla em todo arquivo externo. |
| E6 | Personalização profunda | implemented_with_limits: Arraste/atalhos/perfis/paleta/menus internos; restrições do sistema preservadas. |
| E7 | Biblioteca | implemented_with_limits: Coleções/etiquetas/duplicados/pastas inteligentes; importação e limites explícitos. |
| E8 | IA portuguesa/coleções | implementation_present_target_validation_pending: Citações e contradições implementadas; modelo real e qualidade geral não validados. |
| E9 | OCR com revisão visual | partial: Palavras/geometria/revisão implementadas; não cobre qualquer qualidade/manuscrito. |
| E10 | Corrigir acessibilidade | partial: Tags/grupos/tabelas editáveis; sem reconstrução semântica automática universal. |
| E11 | Revogação/PAdES LT-LTA | implemented_with_external_dependencies: PKI/HTTPS/TSA controlados; produção e renovação periódica automática ausentes. |
| E12 | Solicitação integrada | implemented_with_external_dependencies: Preparar/enviar/status/download existem; serviço de produção não exercitado e Sign.com permanece externo. |
| E13 | Otimização M4+ | target_validation_pending: Concorrência/GPU e medição implementadas; M4 físico/energia/NPU sem prova. |
| E14 | Atalhos/Finder/pastas | implemented_with_external_dependencies: Integração e metadados reais; app aberto necessário e interação humana externa pendente. |
| E15 | Sincronização entre Macs | implemented_with_external_dependencies: Pasta escolhida e conflitos; sem backend próprio/E2EE adicional nem ensaio em dois Macs físicos. |
| E16 | Impressão profissional | partial: Candidato PDF/X-3 e preflight parcial; não certificação ISO/cores/impresso. |
| E17 | Jurídico/técnico | implemented_with_limits: Bates/dossiê/carimbos/medidas presentes; não cadeia de custódia/escala física certificada. |

## Todas as ferramentas — cobertura estática

Cada linha verifica catálogo → rota → implementação, não um resultado universal da ferramenta. O JSON conserva, porID, os controles e limites da linha correspondente de MATRIZ-0.7, além de referências de código.

| ID | Rota concreta | Operações do motor / natureza |
|---|---|---|
| `conversion-audit` | ProductionToolsView | `conversion-audit` |
| `merge` | ToolConfigurationView | `merge` |
| `split` | ToolConfigurationView | `split` |
| `compress` | ToolConfigurationView | `compress` |
| `word` | ToolConfigurationView | `word` |
| `powerpoint` | ToolConfigurationView | `powerpoint` |
| `excel` | ToolConfigurationView | `excel` |
| `word-pdf` | ToolConfigurationView | `office` |
| `powerpoint-pdf` | ToolConfigurationView | `office` |
| `excel-pdf` | ToolConfigurationView | `office` |
| `edit` | ToolConfigurationView | `text`, `image`, `shape`, `edit` |
| `jpg` | ToolConfigurationView | `jpg` |
| `images` | ToolConfigurationView | `images` |
| `signature` | ToolConfigurationView | `signature` |
| `watermark` | ToolConfigurationView | `watermark` |
| `rotate` | ToolConfigurationView | `rotate` |
| `html` | ToolConfigurationView | `html` |
| `unlock` | ToolConfigurationView | `unlock` |
| `protect` | ToolConfigurationView | `protect` |
| `organize` | ToolConfigurationView | `organize` |
| `pdfa` | ToolConfigurationView | `pdfa` |
| `repair` | ToolConfigurationView | `repair` |
| `numbers` | ToolConfigurationView | `numbers` |
| `scan` | NativeFeaturesView/ImageCaptureCore/ContinuityCapture | Implementação nativa/navegação/serviço; não é comando Python independente |
| `ocr` | ToolConfigurationView | `ocr` |
| `compare` | ToolConfigurationView | `compare`, `compare-visual` |
| `redact` | ToolConfigurationView | `redact` |
| `crop` | ToolConfigurationView | `crop` |
| `forms` | ToolConfigurationView | `forms`, `form-detect`, `form-create`, `form-fill` |
| `summary` | IntelligenceView/FoundationModels | Implementação nativa/navegação/serviço; não é comando Python independente |
| `translate` | IntelligenceView/FoundationModels | `layout-extract`, `translate-layout` |
| `markdown` | ToolConfigurationView | `markdown` |
| `workflow` | WorkflowView | `workflow` |
| `png` | ToolConfigurationView | `png` |
| `odt-pdf` | ToolConfigurationView | `odt` |
| `txt-pdf` | ToolConfigurationView | `txt` |
| `rtf-pdf` | ToolConfigurationView | `rtf` |
| `epub-pdf` | ToolConfigurationView | `epub` |
| `csv-pdf` | ToolConfigurationView | `csv` |
| `pages-pdf` | PagesConversionView/AppleScript/Pages | Implementação nativa/navegação/serviço; não é comando Python independente |
| `flatten` | ToolConfigurationView | `flatten` |
| `delete-pages` | ToolConfigurationView | `delete-pages` |
| `extract-pages` | ToolConfigurationView | `extract-pages` |
| `converter` | ContentView: category=Converter (navigation only) | Implementação nativa/navegação/serviço; não é comando Python independente |
| `share` | SharePDFView/ShareLink | Implementação nativa/navegação/serviço; não é comando Python independente |
| `annotate` | ReaderWorkspaceView/PDFKit/AnnotationEditing | Implementação nativa/navegação/serviço; não é comando Python independente |
| `fill-forms` | ToolConfigurationView | `forms`, `form-fill` |
| `chat` | IntelligenceView/SemanticRetrieval/FoundationModels | Implementação nativa/navegação/serviço; não é comando Python independente |
| `quiz` | IntelligenceView/FoundationModels | Implementação nativa/navegação/serviço; não é comando Python independente |
| `sign-service` | ExternalSigningView/Link(Sign.com) | Implementação nativa/navegação/serviço; não é comando Python independente |
| `digital-sign` | VerificationView | `digital-sign` |
| `verify-signatures` | VerificationView | `verify-signatures` |
| `validate-pdfa` | VerificationView | `validate-pdfa` |
| `validate-pdfua` | VerificationView | `validate-pdfua` |
| `benchmark` | BenchmarkView/MacBenchmark | Implementação nativa/navegação/serviço; não é comando Python independente |
| `content-editor` | AdvancedContentEditorView | `content-inspect`, `content-apply` |
| `ocr-review` | OCRReviewView | `ocr-review`, `ocr-apply` |
| `library` | DocumentLibraryView/DocumentLibraryStore | Implementação nativa/navegação/serviço; não é comando Python independente |
| `document-history` | DocumentLibraryView/DocumentLibraryStore | Implementação nativa/navegação/serviço; não é comando Python independente |
| `collection-research` | DocumentLibraryView/LibraryRetrieval/LibraryAnswering | Implementação nativa/navegação/serviço; não é comando Python independente |
| `sync-library` | DocumentLibraryView/DocumentLibraryStore | Implementação nativa/navegação/serviço; não é comando Python independente |
| `accessibility-edit` | AccessibilityRemediationView | `accessibility-inspect`, `accessibility-remediate` |
| `signature-request` | SignatureRequestView | `signature-request-prepare`, `signature-request-send`, `signature-request-status`, `signature-request-download` |
| `print-preflight` | ProductionToolsView | `print-preflight` |
| `print-prepare` | ProductionToolsView | `print-prepare` |
| `pdfx` | ProductionToolsView | `pdfx` |
| `bates` | ProductionToolsView | `bates` |
| `dossier` | ProductionToolsView | `dossier` |
| `stamp` | ProductionToolsView | `stamp` |
| `measure` | ProductionToolsView | `measure` |
| `automation` | AutomationView/AutomationCoordinator/PDFAppIntents | Implementação nativa/navegação/serviço; não é comando Python independente |

**Leitor:** ContentView(section=Leitor) -> ReaderWorkspaceView -> PDFKit/DocumentSessions. abas, lado a lado, busca, miniaturas/sumário, zoom, marcadores, formulários, anotações/undo-redo, salvar cópia/criptografia/recuperação. Presença dos percursos não comprova cada PDF ou interação humana; cena37 foi corrigida e tem evidência nativa separada, ainda sem conclusão portátil nesta tarefa.

## Evidência e alcance

- Arquivo estruturado completo: [pdf37-final-scope-audit.json](/tmp/pdf37-final-scope-audit.json).
- A coordenação informou diagnósticoGUI inicial/instalado e44 grupos standalone aprovados nos dois Macs; portátil ainda em curso. Esta revisão não recontou nem substituiu os logs da CI.
- Não executei nova suíte, fuzzing especulativo, serviços de produção ou interação humana. A existência de catálogo/controle de teste é distinta de execução funcional, qualidade geral e atendimento integral.
- Nenhuma aprovação foi transferida de uma fonte histórica para37; especialmente as falhas6f0a68b e cross817 permanecem falhas de seus snapshots.
