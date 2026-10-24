import Foundation
import AppKit
import PDFKit
import Darwin

/// Real private PDF copies, two independent stores and an explicit exchange
/// folder exercise persistence and conflicts. No user's Application Support,
/// files, cloud provider or generated-model answer participates in these tests.
enum LibraryAuditChecks {
    @MainActor static func run() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-Library-Audit-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: root) }
        var count = 0
        func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
            count += 1
            guard try condition() else { throw NSError(domain: "PDF.LibraryAudit", code: count, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func rejects(_ action: () async throws -> Void) async -> Bool {
            do { try await action(); return false } catch { return true }
        }
        func make(_ name: String, text: String) throws -> URL {
            let url = root.appendingPathComponent(name)
            let data = NSMutableData()
            guard let consumer = CGDataConsumer(data: data as CFMutableData) else { throw LibraryFailure.invalidPDF }
            var bounds = CGRect(x: 0, y: 0, width: 400, height: 500)
            guard let context = CGContext(consumer: consumer, mediaBox: &bounds, nil) else { throw LibraryFailure.invalidPDF }
            context.beginPDFPage(nil)
            NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
            (text as NSString).draw(at: CGPoint(x: 30, y: 400), withAttributes: [.font: NSFont.systemFont(ofSize: 14), .foregroundColor: NSColor.black])
            NSGraphicsContext.restoreGraphicsState(); context.endPDFPage(); context.closePDF()
            try LibraryFiles.publish(data as Data, to: url); return url
        }
        let source = try make("Contrato.pdf", text: "O pagamento vence em trinta dias. A ação preserva o contrato.")
        let changedA = try make("Revisão A.pdf", text: "A revisão A define pagamento em quarenta dias.")
        let changedB = try make("Revisão B.pdf", text: "A revisão B define pagamento em sessenta dias.")
        let original = try Data(contentsOf: source)
        let directoryA = root.appendingPathComponent("Mac-A"), directoryB = root.appendingPathComponent("Mac-B")
        let storeA = DocumentLibraryStore(directory: directoryA), storeB = DocumentLibraryStore(directory: directoryB)
        let imported = try await storeA.importFiles([source], collection: "Contratos", tags: ["AÇÃO", "2026"])
        try require(imported.imported == 1 && imported.duplicate == 0, "A primeira importação não criou um documento.")
        let id = imported.catalog.documents[0].id, initial = imported.catalog.documents[0].current
        try require(initial.fingerprint == LibraryFiles.hash(original) && initial.pages == 1 && !initial.encrypted, "A importação perdeu bytes, páginas ou proteção.")
        let duplicate = try await storeA.importFiles([source])
        try require(duplicate.imported == 0 && duplicate.duplicate == 1 && duplicate.catalog.documents.count == 1, "A cópia idêntica criou outra entrada.")
        let reloaded = try await DocumentLibraryStore(directory: directoryA).list()
        try require(reloaded == duplicate.catalog, "O catálogo não sobreviveu a uma nova instância.")
        let copiedURL = try await storeA.verifiedURL(document: id)
        try require(try Data(contentsOf: copiedURL) == original, "A biblioteca reescreveu o PDF original.")
        let pointerBeforeFailure = try LibraryFiles.read(directoryA.appendingPathComponent("current.json"), maximum: 1_024)
        let malformed = root.appendingPathComponent("invalid.pdf"); try LibraryFiles.publish(Data("invalid".utf8), to: malformed)
        let invalidRefused = await rejects { _ = try await storeA.importFiles([changedA, malformed]) }
        try require(invalidRefused, "Uma importação parcial publicou um PDF inválido.")
        try require(try LibraryFiles.read(directoryA.appendingPathComponent("current.json"), maximum: 1_024) == pointerBeforeFailure, "Uma importação incompleta mudou o catálogo ativo.")
        let fifo = root.appendingPathComponent("pipe.pdf")
        guard mkfifo(fifo.path, 0o600) == 0 else { throw POSIXError(.EIO) }
        let fifoRefused = await rejects { _ = try await storeA.importFiles([fifo]) }
        try require(fifoRefused, "A biblioteca tentou consumir um pipe em vez de PDF regular.")
        let symbolic = root.appendingPathComponent("link.pdf")
        try FileManager.default.createSymbolicLink(at: symbolic, withDestinationURL: source)
        let linkRefused = await rejects { _ = try await storeA.importFiles([symbolic]) }
        try require(linkRefused, "A importação seguiu um link simbólico.")
        let badRoot = root.appendingPathComponent("linked-library")
        try FileManager.default.createSymbolicLink(at: badRoot, withDestinationURL: directoryA)
        let linkedStoreRefused = await rejects { _ = try await DocumentLibraryStore(directory: badRoot).list() }
        try require(linkedStoreRefused, "Uma raiz de biblioteca simbólica foi aceita.")
        let export = root.appendingPathComponent("restored-copy.pdf")
        try await storeA.export(document: id, to: export)
        let overwriteRefused = await rejects { try await storeA.export(document: id, to: export) }
        try require(overwriteRefused && (try Data(contentsOf: export)) == original, "A exportação substituiu um destino existente.")
        let secretLink = root.appendingPathComponent("export-link.pdf")
        try FileManager.default.createSymbolicLink(at: secretLink, withDestinationURL: source)
        let outputLinkRefused = await rejects { try await storeA.export(document: id, to: secretLink) }
        try require(outputLinkRefused && (try Data(contentsOf: source)) == original, "A exportação seguiu um link para o original.")

        let edited = try await storeA.updateLabels(document: id, title: "Contrato principal", collection: "Clientes", tags: ["ação", "Revisar"])
        try require(edited.documents[0].revisions.count == 2 && edited.documents[0].current.fingerprint == initial.fingerprint, "Organizar modificou bytes ou perdeu o histórico.")
        var filter = LibrarySmartFilter(); filter.text = "CONTRATO AÇÃO"; filter.collection = "Clientes"; filter.tag = "ação"
        try require(filter.apply(edited.documents).count == 1, "Os filtros perderam normalização portuguesa ou etiquetas.")
        filter.mode = .protected; try require(filter.apply(edited.documents).isEmpty, "O filtro protegido incluiu um PDF sem proteção.")
        filter.mode = .all
        filter.modifiedAfter = edited.documents[0].current.created.addingTimeInterval(-60)
        filter.modifiedBefore = edited.documents[0].current.created.addingTimeInterval(60)
        let savedFolders = try await storeA.saveSmartFolder(name: "Contratos em revisão", filter: filter)
        guard let savedFolder = savedFolders.first else { throw LibraryFailure.missing }
        let loadedFolders = try await DocumentLibraryStore(directory: directoryA).smartFolders()
        try require(loadedFolders == savedFolders && loadedFolders[0].filter.apply(edited.documents).map(\.id) == [id], "A pasta inteligente perdeu regras, datas ou persistência entre instâncias.")
        let smartPointer = directoryA.appendingPathComponent("smart-folders.json")
        let savedPointer = try LibraryFiles.read(smartPointer, maximum: 1_024)
        let sameName = await rejects { _ = try await storeA.saveSmartFolder(name: "CONTRATOS EM REVISAO", filter: filter) }
        try require(sameName && (try LibraryFiles.read(smartPointer, maximum: 1_024)) == savedPointer, "Um nome equivalente substituiu silenciosamente uma regra salva.")
        var invalidDates = filter; invalidDates.modifiedAfter = filter.modifiedBefore?.addingTimeInterval(1)
        let reversedDates = await rejects { _ = try await storeA.saveSmartFolder(name: "Datas inválidas", filter: invalidDates) }
        invalidDates.modifiedAfter = Date(timeIntervalSince1970: .infinity)
        let nonfiniteDates = await rejects { _ = try await storeA.saveSmartFolder(name: "Datas infinitas", filter: invalidDates) }
        try require(reversedDates && nonfiniteDates && (try LibraryFiles.read(smartPointer, maximum: 1_024)) == savedPointer, "Datas inválidas entraram nas regras ou modificaram o estado anterior.")
        var excluded = filter; excluded.modifiedAfter = edited.documents[0].current.created.addingTimeInterval(1); excluded.modifiedBefore = nil
        try require(excluded.apply(edited.documents).isEmpty, "A data inicial não foi aplicada à versão atual.")
        excluded = filter; excluded.modifiedAfter = nil; excluded.modifiedBefore = edited.documents[0].current.created.addingTimeInterval(-1)
        try require(excluded.apply(edited.documents).isEmpty, "A data final não foi aplicada à versão atual.")
        var rolling = LibrarySmartFilter(); rolling.mode = .recent
        try require(rolling.apply(edited.documents, now: edited.documents[0].current.created.addingTimeInterval(8 * 86_400)).isEmpty, "A regra relativa de sete dias congelou os resultados ao ser salva.")
        var updatedRule = filter; updatedRule.mode = .protected
        let updatedFolders = try await storeA.saveSmartFolder(id: savedFolder.id, name: "PDFs protegidos", filter: updatedRule)
        try require(updatedFolders.count == 1 && updatedFolders[0].id == savedFolder.id && updatedFolders[0].filter.apply(edited.documents).isEmpty, "A atualização explícita não preservou a identidade ou alterou os critérios errados.")
        let protectedPointer = try LibraryFiles.read(smartPointer, maximum: 1_024)
        guard let pointerObject = try JSONSerialization.jsonObject(with: protectedPointer) as? [String: Any], let rulesHash = pointerObject["hash"] as? String else { throw LibraryFailure.corrupt }
        let rulesURL = directoryA.appendingPathComponent("smart-folders/" + rulesHash + ".json")
        let rulesBackup = try LibraryFiles.read(rulesURL, maximum: LibrarySmartFolders.maximumBytes)
        try Data("{}".utf8).write(to: rulesURL)
        let damagedRules = await rejects { _ = try await storeA.smartFolders() }
        try require(damagedRules, "Regras adulteradas passaram pela verificação de integridade.")
        try rulesBackup.write(to: rulesURL)
        try Data("{\"version\":1,\"hash\":\"../../outside\"}".utf8).write(to: smartPointer)
        let rulesTraversal = await rejects { _ = try await storeA.smartFolders() }
        try require(rulesTraversal, "O ponteiro das regras aceitou travessia de caminho.")
        try protectedPointer.write(to: smartPointer)
        try FileManager.default.removeItem(at: smartPointer)
        try FileManager.default.createSymbolicLink(at: smartPointer, withDestinationURL: source)
        let linkedRules = await rejects { _ = try await storeA.smartFolders() }
        try require(linkedRules && (try Data(contentsOf: source)) == original, "A leitura das regras seguiu um link ou alterou o PDF original.")
        try FileManager.default.removeItem(at: smartPointer); try LibraryFiles.publish(protectedPointer, to: smartPointer)
        let removedFolders = try await storeA.deleteSmartFolder(id: savedFolder.id)
        let catalogAfterRuleDeletion = try await storeA.list()
        try require(removedFolders.isEmpty && catalogAfterRuleDeletion == edited && (try Data(contentsOf: copiedURL)) == original, "Remover uma pasta inteligente removeu documentos ou histórico.")
        let tooManyRules = (0..<65).map { LibrarySmartFolder(id: UUID(), name: "Regra \($0)", filter: LibrarySmartFilter(), modified: Date()) }
        let rulesQuota = await rejects { try LibrarySmartFolders.validate(.init(version: 1, folders: tooManyRules)) }
        let unknownMode = await rejects { _ = try JSONDecoder().decode(LibrarySmartFilter.self, from: Data("{\"text\":\"\",\"collection\":\"\",\"tag\":\"\",\"mode\":\"execute-script\"}".utf8)) }
        try require(rulesQuota && unknownMode, "A validação aceitou regras excessivas ou uma categoria desconhecida.")
        let searchSource = try await storeA.excerpts(documentIDs: [id], cancellation: NativeCancellation())
        let retrieval = LibraryRetrieval()
        let result = try await retrieval.search(question: "PAGAMENTO AÇÃO", source: searchSource, useEmbeddings: false)
        try require(!result.sources.isEmpty && result.sources.allSatisfy { $0.documentID == id && $0.fingerprint == initial.fingerprint && $0.page == 1 }, "A busca perdeu origem, hash ou página.")
        try require(result.sources.allSatisfy { searchSource.excerpts.contains($0) }, "A busca inventou uma citação.")
        let absent = try await retrieval.search(question: "galáxia extraterrestre", source: searchSource, useEmbeddings: false)
        try require(absent.sources.isEmpty && absent.response.contains("Não encontrei"), "A busca sem apoio exibiu uma conclusão.")
        let absentAnswer = try await LibraryAnswering.respond(to: absent)
        try require(absentAnswer.citations.isEmpty && absentAnswer.text.contains("não fornecem"), "Uma pergunta sem fontes chegou à geração de resposta.")
        let empty = try await retrieval.search(question: "de o a e", source: searchSource, useEmbeddings: false)
        try require(empty.sources.isEmpty && empty.comparisonSources.isEmpty && LibraryAnswering.comparisonDocumentCount(empty) == 0, "Termos vazios selecionaram fontes arbitrárias.")
        let dominantDocument = UUID(), otherDocument = UUID(), comparisonRevision = UUID()
        let dominantSources = (0..<8).map { index in
            LibraryExcerpt(documentID: dominantDocument, revisionID: comparisonRevision, fingerprint: initial.fingerprint,
                           title: "Fonte A", page: index + 1, part: 0,
                           text: "Prazo pagamento em trinta dias. " + String(repeating: "Contexto literal. ", count: 45) + " Final A\(index).")
        }
        let lowerRankedSource = LibraryExcerpt(documentID: otherDocument, revisionID: UUID(), fingerprint: initial.fingerprint,
                                               title: "Fonte B", page: 1, part: 0,
                                               text: "Pagamento em sessenta dias. " + String(repeating: "Contexto literal. ", count: 45) + " Final B.")
        let irrelevantSource = LibraryExcerpt(documentID: UUID(), revisionID: UUID(), fingerprint: initial.fingerprint,
                                              title: "Fonte sem apoio", page: 1, part: 0, text: "A astronomia observa galáxias distantes.")
        let comparisonInput = dominantSources + [lowerRankedSource, irrelevantSource]
        let diverseResult = try await retrieval.search(question: "prazo pagamento", source: .init(excerpts: comparisonInput, skipped: []), useEmbeddings: false)
        try require(diverseResult.sources == dominantSources, "A seleção de comparação alterou os oito resultados normais ou sua ordem de relevância.")
        try require(diverseResult.comparisonSources.count == 8 && diverseResult.comparisonSources.first == dominantSources[0]
                    && diverseResult.comparisonSources[1] == lowerRankedSource && diverseResult.comparisonSources.allSatisfy { comparisonInput.contains($0) }
                    && !diverseResult.comparisonSources.contains(irrelevantSource), "A comparação perdeu uma fonte relevante, reordenou sua prioridade ou inventou apoio de outro documento.")
        let diverseContext = try LibraryAnswering.comparisonContext(diverseResult)
        let ordinaryContext = try LibraryAnswering.context(diverseResult)
        let visibleComparison = try LibraryAnswering.comparisonExcerpts(diverseResult)
        let contextCharacters = diverseContext.excerpts.reduce(0) { $0 + $1.text.count + $1.id.count + 60 }
        try require(contextCharacters <= 4_500 && diverseContext.excerpts.count < diverseResult.comparisonSources.count
                    && LibraryAnswering.comparisonDocumentCount(diverseResult) == 2
                    && visibleComparison[0].quote == dominantSources[0].text && visibleComparison[1].quote == lowerRankedSource.text
                    && visibleComparison[1].source == lowerRankedSource && !ordinaryContext.excerpts.contains(where: { $0.id == diverseContext.excerpts[1].id }), "O corte de contexto eliminou a segunda fonte, excedeu o orçamento ou mudou o contexto da resposta comum.")
        let diversePair = LibraryComparisonResponse.Pair(topic: "Possível diferença de prazo",
            first: .init(claim: "Prazo pagamento em trinta dias.", excerpt: diverseContext.excerpts[0].id, quote: "Prazo pagamento em trinta dias."),
            second: .init(claim: "Pagamento em sessenta dias.", excerpt: diverseContext.excerpts[1].id, quote: "Pagamento em sessenta dias."))
        let diverseValidated = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [diversePair]), result: diverseResult)
        try require(diverseValidated.pairs.first?.second.citation.source == lowerRankedSource, "A validação não encontrou a proveniência da fonte adicional de comparação.")
        let ordinaryAnswerLeak = await rejects {
            _ = try LibraryAnswering.validate(.init(supported: true, answer: "Pagamento em sessenta dias.", citations: [.init(excerpt: diverseContext.excerpts[1].id, quote: "Pagamento em sessenta dias.")]), result: diverseResult)
        }
        let duplicateComparisonSources = LibrarySearchResult(question: diverseResult.question, sources: diverseResult.sources, method: diverseResult.method, skipped: [], comparisonSources: [lowerRankedSource, lowerRankedSource])
        let duplicateComparisonRejected = await rejects { _ = try LibraryAnswering.comparisonContext(duplicateComparisonSources) }
        let excessiveComparisonSources = LibrarySearchResult(question: diverseResult.question, sources: diverseResult.sources, method: diverseResult.method, skipped: [], comparisonSources: dominantSources + [lowerRankedSource])
        let excessiveComparisonRejected = await rejects { _ = try LibraryAnswering.comparisonContext(excessiveComparisonSources) }
        try require(ordinaryAnswerLeak && duplicateComparisonRejected && excessiveComparisonRejected, "As fontes de comparação escaparam para a resposta normal ou fontes malformadas desapareceram pela truncagem.")
        guard let firstSource = result.sources.first, let secondPDF = PDFDocument(url: changedB), let secondText = secondPDF.page(at: 0)?.string else { throw LibraryFailure.invalidPDF }
        let secondSource = LibraryExcerpt(documentID: UUID(), revisionID: UUID(), fingerprint: LibraryFiles.hash(try Data(contentsOf: changedB)),
                                           title: "Outra fonte real", page: 1, part: 0, text: secondText)
        let multiDocument = LibrarySearchResult(question: "Quais os prazos de pagamento?", sources: [firstSource, secondSource], method: "Auditoria estrutural, sem inferência de modelo", skipped: [])
        let context = try LibraryAnswering.context(multiDocument)
        let grounded = GroundedAnswer(supported: true, answer: "Os trechos apresentam prazos diferentes.", citations: [
            ModelCitation(excerpt: context.excerpts[0].id, quote: firstSource.text),
            ModelCitation(excerpt: context.excerpts[1].id, quote: secondText)
        ])
        let groundedResult = try LibraryAnswering.validate(grounded, result: multiDocument)
        try require(Set(groundedResult.citations.map { $0.source.documentID }).count == 2 && groundedResult.citations.allSatisfy { $0.source.page == 1 }, "Documentos diferentes com página 1 compartilharam a identidade da citação.")
        let wrongSource = GroundedAnswer(supported: true, answer: "Atribuição errada", citations: [ModelCitation(excerpt: context.excerpts[1].id, quote: firstSource.text)])
        let falseAttribution = await rejects { _ = try LibraryAnswering.validate(wrongSource, result: multiDocument) }
        try require(falseAttribution, "Uma citação de outro documento foi aceita por compartilhar o número da página.")
        let unsupported = try LibraryAnswering.validate(GroundedAnswer(supported: false, answer: "Sem apoio", citations: []), result: multiDocument)
        try require(unsupported.citations.isEmpty && unsupported.text.contains("evidências suficientes"), "A resposta sem apoio não foi recusada.")

        let firstClaim = LibraryComparisonResponse.Claim(claim: firstSource.text, excerpt: context.excerpts[0].id, quote: firstSource.text)
        let secondClaim = LibraryComparisonResponse.Claim(claim: secondText, excerpt: context.excerpts[1].id, quote: secondText)
        let comparisonPair = LibraryComparisonResponse.Pair(topic: "Prazo de pagamento", first: firstClaim, second: secondClaim)
        let comparison = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [comparisonPair]), result: multiDocument)
        guard let checkedPair = comparison.pairs.first else { throw LibraryFailure.corrupt }
        try require(comparison.pairs.count == 1 && checkedPair.first.citation.source.documentID != checkedPair.second.citation.source.documentID && checkedPair.first.citation.source.page == 1 && checkedPair.second.citation.source.page == 1 && checkedPair.first.citation.source.revisionID == firstSource.revisionID && checkedPair.second.citation.source.fingerprint == secondSource.fingerprint, "A comparação confundiu documentos na mesma página ou perdeu versão e impressão digital.")
        try require(comparison.explanation.contains("Possíveis divergências") && Data(checkedPair.first.citation.quote.utf8) == Data(firstSource.text.utf8), "Uma hipótese de contradição foi apresentada como verdade ou perdeu sua citação literal.")
        let forgedClaim = LibraryComparisonResponse.Claim(claim: firstSource.text, excerpt: "s" + String(repeating: "0", count: 64), quote: firstSource.text)
        let forgedComparison = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Prazo", first: forgedClaim, second: secondClaim)]), result: multiDocument) }
        let swappedClaim = LibraryComparisonResponse.Claim(claim: firstSource.text, excerpt: context.excerpts[1].id, quote: firstSource.text)
        let swappedComparison = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Prazo", first: firstClaim, second: swappedClaim)]), result: multiDocument) }
        let inventedQuote = LibraryComparisonResponse.Claim(claim: "O prazo de pagamento é de duzentos dias.", excerpt: context.excerpts[1].id, quote: "O prazo de pagamento é de duzentos dias.")
        let inventedComparison = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Prazo", first: firstClaim, second: inventedQuote)]), result: multiDocument) }
        try require(forgedComparison && swappedComparison && inventedComparison, "A comparação aceitou ID inventado, atribuição cruzada ou texto inexistente.")
        try require(firstSource.text.contains("trinta") && firstSource.text.contains("vence"), "A fixture não contém os termos para auditar quantidade e negação.")
        let alteredAmount = LibraryComparisonResponse.Claim(claim: firstSource.text.replacingOccurrences(of: "trinta", with: "duzentos"), excerpt: firstClaim.excerpt, quote: firstSource.text)
        let alteredNegation = LibraryComparisonResponse.Claim(claim: firstSource.text.replacingOccurrences(of: "vence", with: "não vence"), excerpt: firstClaim.excerpt, quote: firstSource.text)
        let fabricatedAmount = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Valor fabricado", first: alteredAmount, second: secondClaim)]), result: multiDocument) }
        let fabricatedNegation = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Negação fabricada", first: alteredNegation, second: secondClaim)]), result: multiDocument) }
        try require(fabricatedAmount && fabricatedNegation, "Uma afirmação inventada foi aceita por acompanhar uma citação autêntica.")
        let sameDocumentSource = LibraryExcerpt(documentID: firstSource.documentID, revisionID: secondSource.revisionID, fingerprint: secondSource.fingerprint, title: "Outra versão, mesmo documento", page: 1, part: 0, text: secondText)
        let sameDocumentResult = LibrarySearchResult(question: multiDocument.question, sources: [firstSource, sameDocumentSource], method: multiDocument.method, skipped: [])
        let sameDocumentContext = try LibraryAnswering.context(sameDocumentResult)
        let sameDocumentClaim = LibraryComparisonResponse.Claim(claim: secondClaim.claim, excerpt: sameDocumentContext.excerpts[1].id, quote: secondText)
        let sameDocumentRejected = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Mesmo documento", first: firstClaim, second: sameDocumentClaim)]), result: sameDocumentResult) }
        let reversedPair = LibraryComparisonResponse.Pair(topic: "Repetição invertida", first: secondClaim, second: firstClaim)
        let repeatedComparison = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [comparisonPair, reversedPair]), result: multiDocument) }
        let inconsistentRefusal = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: false, pairs: [comparisonPair]), result: multiDocument) }
        let emptyPositive = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: []), result: multiDocument) }
        try require(sameDocumentRejected && repeatedComparison && inconsistentRefusal && emptyPositive, "A comparação aceitou fontes iguais, pares repetidos ou um contrato de resposta inconsistente.")
        let noComparison = try await LibraryAnswering.compare(absent)
        let oneDocumentComparison = try await LibraryAnswering.compare(sameDocumentResult)
        let unsupportedComparison = try LibraryAnswering.validateComparison(.init(supported: false, pairs: []), result: multiDocument)
        try require(noComparison.pairs.isEmpty && oneDocumentComparison.pairs.isEmpty && unsupportedComparison.explanation.contains("não comprova"), "A recusa sem duas fontes tentou inferência ou declarou concordância sem provas.")
        let changedRevision = LibraryExcerpt(documentID: secondSource.documentID, revisionID: UUID(), fingerprint: secondSource.fingerprint, title: secondSource.title, page: 1, part: 0, text: secondText)
        let changedRevisionResult = LibrarySearchResult(question: multiDocument.question, sources: [firstSource, changedRevision], method: multiDocument.method, skipped: [])
        let staleReference = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [comparisonPair]), result: changedRevisionResult) }
        try require(staleReference, "Uma comparação reaproveitou a identidade de uma revisão fora da consulta atual.")
        let alteredWhitespace = LibraryComparisonResponse.Claim(claim: firstClaim.quote.replacingOccurrences(of: " ", with: "  "), excerpt: firstClaim.excerpt, quote: firstClaim.quote.replacingOccurrences(of: " ", with: "  "))
        let nonliteralWhitespace = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [.init(topic: "Citação alterada", first: alteredWhitespace, second: secondClaim)]), result: multiDocument) }
        let excessivePairs = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: Array(repeating: comparisonPair, count: 5)), result: multiDocument) }
        try require(nonliteralWhitespace && excessivePairs, "A comparação aceitou alteração dos bytes da citação ou excedeu o limite de pares.")
        let longSources = (0..<6).map { index in
            LibraryExcerpt(documentID: UUID(), revisionID: UUID(), fingerprint: initial.fingerprint, title: "Fonte sintética \(index)", page: 1, part: 0,
                           text: String(repeating: "Conteúdo de contexto limitado. ", count: 28) + " Fim exclusivo da fonte \(index).")
        }
        let longResult = LibrarySearchResult(question: "Comparar as condições", sources: longSources, method: "Contrato sintético do limite de contexto", skipped: [])
        let endpoints = try LibraryAnswering.context(.init(question: longResult.question, sources: [longSources[0], longSources[5]], method: longResult.method, skipped: []))
        let outsideContext = LibraryComparisonResponse.Pair(topic: "Trecho não enviado", first: .init(claim: "Conteúdo de contexto limitado.", excerpt: endpoints.excerpts[0].id, quote: "Conteúdo de contexto limitado."), second: .init(claim: "Fim exclusivo da fonte 5.", excerpt: endpoints.excerpts[1].id, quote: "Fim exclusivo da fonte 5."))
        let limitedComparisonContext = try LibraryAnswering.comparisonContext(longResult)
        try require(!limitedComparisonContext.excerpts.contains(where: { $0.id == endpoints.excerpts[1].id && $0.text.contains("Fim exclusivo da fonte 5.") }), "A fixture de limite deixou a citação negativa dentro do contexto enviado.")
        let omittedContext = await rejects { _ = try LibraryAnswering.validateComparison(.init(supported: true, pairs: [outsideContext]), result: longResult) }
        try require(omittedContext, "A comparação aceitou uma citação da consulta que não foi enviada ao modelo por limite de contexto.")

        let exchange = root.appendingPathComponent("Chosen Sync Folder")
        try LibraryFiles.directory(exchange, create: true)
        let bookmarks = PDFReadingExchangeSnapshot(documentHash: initial.fingerprint, title: "Contrato principal", pageCount: 1,
                                                   bookmarks: [1], page: 1, zoom: 1.5, autoScale: false)
        let bookmarkPayload = try JSONEncoder().encode(bookmarks)
        let configA = try await storeA.publishConfiguration(kind: "bookmarks", payload: bookmarkPayload)
        let duplicateConfig = try await storeA.publishConfiguration(kind: "bookmarks", payload: bookmarkPayload)
        try require(configA.id == duplicateConfig.id, "Um snapshot de ajustes idêntico foi duplicado.")
        let secretConfiguration = await rejects { _ = try await storeA.publishConfiguration(kind: "preferences", payload: Data("{\"password\":\"must-not-persist\"}".utf8)) }
        try require(secretConfiguration, "A troca de ajustes aceitou uma chave de senha.")
        _ = try await storeA.synchronize(with: exchange)
        let received = try await storeB.synchronize(with: exchange)
        try require(received.catalog.documents.count == 1 && received.catalog.documents[0].current.labels.title == "Contrato principal", "O segundo Mac não recebeu a coleção.")
        let receivedConfiguration = try await storeB.loadConfiguration(configA)
        try require(received.configurationsReceived == 1 && receivedConfiguration == bookmarkPayload, "Os marcadores perderam integridade na transferência.")
        var differentBookmarks = bookmarks; differentBookmarks.bookmarks = []; differentBookmarks.zoom = 2
        _ = try await storeB.publishConfiguration(kind: "bookmarks", payload: JSONEncoder().encode(differentBookmarks))
        let bURL = try await storeB.verifiedURL(document: id)
        try require(try Data(contentsOf: bURL) == original, "A sincronização modificou o PDF.")
        _ = try await storeA.addVersion(document: id, source: changedA)
        _ = try await storeB.addVersion(document: id, source: changedB)
        _ = try await storeA.synchronize(with: exchange)
        let divergent = try await storeB.synchronize(with: exchange)
        try require(divergent.conflicts == 1 && divergent.catalog.documents[0].heads.count == 2, "Versões independentes foram sobrescritas silenciosamente.")
        let resolvedA = try await storeA.synchronize(with: exchange)
        try require(resolvedA.conflicts == 1 && resolvedA.catalog.documents[0].heads.count == 2, "O conflito não chegou ao primeiro Mac.")
        let alternativeSettings = try await storeA.configurationSnapshots()
        try require(alternativeSettings.count == 2 && Set(alternativeSettings.map(\.payloadHash)).count == 2, "Snapshots divergentes de ajustes foram substituídos silenciosamente.")
        let conflictFolder = exchange.appendingPathComponent("PDF Library Exchange/conflicts/" + id.uuidString)
        let conflictCopies = try FileManager.default.contentsOfDirectory(at: conflictFolder, includingPropertiesForKeys: nil).filter { $0.pathExtension == "pdf" }
        try require(conflictCopies.count == 2, "O conflito não preservou duas cópias PDF independentes.")
        let wantedHash = LibraryFiles.hash(try Data(contentsOf: changedB))
        guard let wanted = resolvedA.catalog.documents[0].heads.first(where: { $0.fingerprint == wantedHash }) else { throw LibraryFailure.missing }
        let resolved = try await storeA.resolve(document: id, revision: wanted.id)
        try require(resolved.documents[0].heads.count == 1 && resolved.documents[0].current.fingerprint == wantedHash, "A resolução explícita não reuniu as ramificações.")
        try require(resolved.documents[0].revisions.count == 5, "A resolução removeu uma versão histórica.")
        _ = try await storeA.synchronize(with: exchange)
        let converged = try await storeB.synchronize(with: exchange)
        try require(converged.conflicts == 0 && converged.catalog.documents[0].current.fingerprint == wantedHash, "A resolução não convergiu no segundo Mac.")
        let restored = try await storeA.restore(document: id, revision: initial.id)
        try require(restored.documents[0].revisions.count == 6 && restored.documents[0].current.fingerprint == initial.fingerprint, "Restaurar não criou uma versão com os bytes históricos.")
        try require(try Data(contentsOf: source) == original, "Uma operação da biblioteca alterou o arquivo original.")

        // Tamper with an existing immutable PDF. Every read/export must reject
        // it, rather than silently repair it or publish changed content.
        try Data("%PDF-corrupt".utf8).write(to: copiedURL)
        let corruptRead = await rejects { _ = try await storeA.verifiedURL(document: id, revision: initial.id) }
        try require(corruptRead, "Um PDF alterado passou pela verificação SHA-256.")
        let corruptCachedSearch = await rejects { _ = try await storeA.excerpts(documentIDs: [id], cancellation: NativeCancellation()) }
        try require(corruptCachedSearch, "O cache de busca reutilizou texto sem verificar os bytes da versão atual.")
        try original.write(to: copiedURL)
        let beforeBadSync = try LibraryFiles.read(directoryA.appendingPathComponent("current.json"), maximum: 1_024)
        let remoteObject = exchange.appendingPathComponent("PDF Library Exchange/objects/" + initial.fingerprint + ".pdf")
        try Data("%PDF-corrupt-peer".utf8).write(to: remoteObject)
        let corruptSync = await rejects { _ = try await storeA.synchronize(with: exchange) }
        try require(corruptSync, "Um objeto remoto danificado foi ignorado ou substituído silenciosamente.")
        try require(try LibraryFiles.read(directoryA.appendingPathComponent("current.json"), maximum: 1_024) == beforeBadSync, "Uma sincronização incompleta publicou outro catálogo.")
        try original.write(to: remoteObject)
        let configPath = directoryA.appendingPathComponent("configurations/" + configA.id + ".json")
        let configBackup = try Data(contentsOf: configPath)
        try Data("{}".utf8).write(to: configPath)
        let configurationCorruption = await rejects { _ = try await storeA.loadConfiguration(configA) }
        try require(configurationCorruption, "Um snapshot de configuração adulterado passou pela verificação.")
        try configBackup.write(to: configPath)
        let manifests = exchange.appendingPathComponent("PDF Library Exchange/manifests")
        let forged = manifests.appendingPathComponent(String(repeating: "a", count: 64) + ".json")
        try LibraryFiles.publish(Data("{}".utf8), to: forged)
        let forgedRefused = await rejects { _ = try await storeA.synchronize(with: exchange) }
        try require(forgedRefused, "Um manifesto com nome/hash incompatíveis foi aceito.")
        try FileManager.default.removeItem(at: forged)
        var bad = restored
        let old = bad.documents[0].current
        let traversal = LibraryRevision(id: UUID(), parents: [old.id], fingerprint: "../../outside", byteCount: old.byteCount, pages: old.pages,
                                        encrypted: old.encrypted, created: Date(), note: "Synthetic invalid path", labels: old.labels)
        bad.documents[0].revisions.append(traversal); bad.documents[0].preferred = traversal.id
        let invalidManifest = try LibraryFiles.encode(bad)
        let invalidPath = manifests.appendingPathComponent(LibraryFiles.hash(invalidManifest) + ".json")
        try LibraryFiles.publish(invalidManifest, to: invalidPath)
        let traversalRefused = await rejects { _ = try await storeA.synchronize(with: exchange) }
        try require(traversalRefused, "Um hash usado como travessia de caminho entrou na biblioteca.")
        try FileManager.default.removeItem(at: invalidPath)
        let firstCycleID = UUID(), secondCycleID = UUID()
        let firstCycle = LibraryRevision(id: firstCycleID, parents: [secondCycleID], fingerprint: old.fingerprint,
                                         byteCount: old.byteCount, pages: old.pages, encrypted: old.encrypted, created: Date(), note: "Cycle A", labels: old.labels)
        let secondCycle = LibraryRevision(id: secondCycleID, parents: [firstCycleID], fingerprint: old.fingerprint,
                                          byteCount: old.byteCount, pages: old.pages, encrypted: old.encrypted, created: Date(), note: "Cycle B", labels: old.labels)
        let cyclic = LibraryCatalog(device: UUID(), documents: [LibraryDocument(id: UUID(), preferred: firstCycleID, revisions: [firstCycle, secondCycle])])
        let cycleRefused = await rejects { try LibraryFiles.validate(cyclic) }
        try require(cycleRefused, "Um ciclo de versões foi aceito.")
        // A correctly hashed manifest can still contradict an immutable revision
        // ID. Hash validation alone is insufficient for this conflict.
        var conflicting = restored
        let existing = conflicting.documents[0].revisions[0]
        let contradictory = LibraryRevision(id: existing.id, parents: existing.parents, fingerprint: existing.fingerprint,
                                            byteCount: existing.byteCount, pages: existing.pages, encrypted: existing.encrypted,
                                            created: existing.created, note: "A different immutable record", labels: existing.labels)
        conflicting.documents[0].revisions[0] = contradictory
        let conflictingBytes = try LibraryFiles.encode(conflicting)
        let conflictingPath = manifests.appendingPathComponent(LibraryFiles.hash(conflictingBytes) + ".json")
        try LibraryFiles.publish(conflictingBytes, to: conflictingPath)
        let revisionCollision = await rejects { _ = try await storeA.synchronize(with: exchange) }
        try require(revisionCollision, "Duas versões diferentes compartilharam silenciosamente o mesmo identificador.")
        try FileManager.default.removeItem(at: conflictingPath)
        let remoteBackup = try Data(contentsOf: remoteObject)
        try FileManager.default.removeItem(at: remoteObject)
        let emptyReceiver = DocumentLibraryStore(directory: root.appendingPathComponent("Mac-Incomplete-Transfer"))
        let emptyCatalog = try await emptyReceiver.list()
        let incomplete = await rejects { _ = try await emptyReceiver.synchronize(with: exchange) }
        let stillEmpty = try await emptyReceiver.list()
        try require(incomplete && stillEmpty == emptyCatalog, "Uma transferência incompleta publicou um catálogo com objetos ausentes.")
        try LibraryFiles.publish(remoteBackup, to: remoteObject)
        let privateStore = DocumentLibraryStore(directory: root.appendingPathComponent("Protected-Library"))
        guard let plain = PDFDocument(data: original) else { throw LibraryFailure.invalidPDF }
        guard let secondPage = plain.page(at: 0)?.copy() as? PDFPage else { throw LibraryFailure.invalidPDF }
        plain.insert(secondPage, at: 1)
        let secret = "library-audit-password-123"
        let protectedBytes = try NativePDFSerialization.finish(NativePDFSerialization.prepare(document: plain, password: secret))
        let protectedFile = root.appendingPathComponent("Protected.pdf")
        try LibraryFiles.publish(protectedBytes, to: protectedFile)
        let protectedImport = try await privateStore.importFiles([protectedFile])
        let protectedID = protectedImport.catalog.documents[0].id
        try require(protectedImport.catalog.documents[0].current.encrypted, "A biblioteca perdeu a marca de proteção.")
        let protectedCopy = try await privateStore.verifiedURL(document: protectedID)
        try require(try Data(contentsOf: protectedCopy) == protectedBytes, "A importação protegida reescreveu ou descriptografou o arquivo.")
        let protectedWithoutSecret = try await privateStore.excerpts(documentIDs: [protectedID], cancellation: NativeCancellation())
        try require(protectedWithoutSecret.excerpts.isEmpty && protectedWithoutSecret.skipped.count == 1, "Uma fonte sem senha foi consultada silenciosamente.")
        let protectedWithSecret = try await privateStore.excerpts(documentIDs: [protectedID], passwords: [protectedID: secret], cancellation: NativeCancellation())
        try require(!protectedWithSecret.excerpts.isEmpty && protectedWithSecret.excerpts.allSatisfy { $0.fingerprint == LibraryFiles.hash(protectedBytes) }, "A consulta autenticada perdeu a proveniência do PDF protegido original.")
        let manifestText = String(decoding: try LibraryFiles.encode(protectedImport.catalog), as: UTF8.self)
        try require(!manifestText.contains(secret) && !manifestText.contains("pagamento vence"), "O catálogo persistiu senha ou texto extraído.")
        let suite = "PDF.Library.ReaderAudit." + UUID().uuidString
        guard let defaults = UserDefaults(suiteName: suite) else { throw LibraryFailure.corrupt }
        defer { defaults.removePersistentDomain(forName: suite) }
        let reader = Workspace(defaults: defaults, recoveryStore: RecoveryStore(directory: root.appendingPathComponent("Reader-Recovery")), enableRecoveryPolling: false)
        reader.open(url: protectedFile, page: 2, displayTitle: "Fonte citada · página 2")
        await reader.waitForPendingOpen()
        try require(reader.needsPassword && reader.sessions.isEmpty, "A abertura de uma referência protegida ignorou a autenticação.")
        reader.documentPassword = secret; reader.unlockPendingDocument(); await reader.waitForPendingOpen()
        try require(reader.currentPage == 2 && reader.activeSession?.page == 2 && reader.activeSession?.displayTitle == "Fonte citada · página 2" && reader.url == protectedFile && reader.activeSession?.password == secret, "A autenticação perdeu página, título, URL ou credencial original da citação.")
        reader.open(url: protectedFile, page: nil, displayTitle: "Título sem mudar a posição")
        try require(reader.currentPage == 2 && reader.activeSession?.displayTitle == "Título sem mudar a posição", "Um título importado alterou indevidamente a página de uma aba já aberta.")
        let otherProtected = root.appendingPathComponent("Cancelled-Reference.pdf")
        try LibraryFiles.publish(protectedBytes, to: otherProtected)
        reader.open(url: otherProtected, page: 2, displayTitle: "Destino a cancelar"); await reader.waitForPendingOpen()
        try require(reader.needsPassword, "O segundo pedido de referência não ficou aguardando a senha.")
        reader.cancelPendingUnlock()
        reader.open(url: otherProtected); await reader.waitForPendingOpen()
        reader.documentPassword = secret; reader.unlockPendingDocument(); await reader.waitForPendingOpen()
        try require(reader.url == otherProtected && reader.currentPage == 1 && reader.activeSession?.displayTitle == nil, "Uma referência cancelada contaminou outra abertura comum.")
        reader.open(url: source)
        guard let editedSession = reader.activeSession, let editedPage = editedSession.document.page(at: 0) else { throw LibraryFailure.invalidPDF }
        let localNote = PDFAnnotation(bounds: CGRect(x: 20, y: 20, width: 40, height: 40), forType: .text, withProperties: nil)
        localNote.contents = "Private unsaved annotation"; editedPage.addAnnotation(localNote); editedSession.hasEdits = true; reader.hasEdits = true
        reader.open(url: source, page: 1, displayTitle: "Fonte original verificada")
        try require(reader.activeSessionID != editedSession.id && editedSession.document.page(at: 0)?.annotations.contains(where: { $0 === localNote }) == true && reader.document?.page(at: 0)?.annotations.isEmpty == true, "A citação exibiu uma aba alterada ou descartou as alterações da aba anterior.")

        // Replace an on-disk object after validation. Verified readers must use
        // the original immutable snapshot, including while asking for a password.
        let pinned = try await storeA.verifiedBytes(document: id, revision: initial.id)
        let replacementBytes = try Data(contentsOf: changedB)
        try replacementBytes.write(to: pinned.url)
        reader.open(url: pinned.url)
        guard let substitutedSession = reader.activeSession else { throw LibraryFailure.invalidPDF }
        try require(substitutedSession.document.string?.contains("sessenta") == true, "A fixture de troca do arquivo não abriu os bytes substituídos.")
        reader.openVerified(data: pinned.data, url: pinned.url, sha: pinned.fingerprint, page: 1, title: "Citação com bytes fixos")
        await reader.waitForPendingOpen()
        guard let pinnedSession = reader.activeSession else { throw LibraryFailure.invalidPDF }
        try require(pinnedSession.id != substitutedSession.id && pinnedSession.sourceFingerprint == pinned.fingerprint && pinnedSession.document.string?.contains("trinta") == true && pinnedSession.document.string?.contains("sessenta") == false, "Uma troca após a verificação mudou o conteúdo exibido sob o hash da citação.")
        try require(substitutedSession.document.string?.contains("sessenta") == true && (try Data(contentsOf: pinned.url)) == replacementBytes, "A abertura verificada contaminou outra aba ou reescreveu a URL adversarial.")
        let pinnedNote = PDFAnnotation(bounds: CGRect(x: 20, y: 20, width: 30, height: 30), forType: .text, withProperties: nil)
        pinnedNote.contents = "Unsaved change in a verified-source tab"
        pinnedSession.document.page(at: 0)?.addAnnotation(pinnedNote); pinnedSession.hasEdits = true; reader.hasEdits = true
        reader.openVerified(data: pinned.data, url: pinned.url, sha: pinned.fingerprint, page: 1, title: "Bytes originais novamente")
        await reader.waitForPendingOpen()
        try require(reader.activeSessionID != pinnedSession.id && reader.document?.page(at: 0)?.annotations.isEmpty == true && pinnedSession.document.page(at: 0)?.annotations.contains(where: { $0 === pinnedNote }) == true, "Uma aba verificada mas alterada foi reutilizada como fonte original.")
        let validSessionID = reader.activeSessionID, countBeforeMismatch = reader.sessions.count
        reader.openVerified(data: replacementBytes, url: pinned.url, sha: pinned.fingerprint, page: 1, title: "Hash incompatível")
        await reader.waitForPendingOpen()
        try require(reader.sessions.count == countBeforeMismatch && reader.activeSessionID == validSessionID && reader.message.contains("impressão digital"), "O leitor aceitou bytes diferentes do SHA declarado ou substituiu a aba após rejeitar a referência.")
        // Same URL, different verified payloads must not share a queue identity.
        reader.openVerified(data: pinned.data, url: pinned.url, sha: pinned.fingerprint, page: 1, title: "Primeiro payload")
        let replacementHash = LibraryFiles.hash(replacementBytes)
        reader.openVerified(data: replacementBytes, url: pinned.url, sha: replacementHash, page: 1, title: "Segundo payload")
        await reader.waitForPendingOpen()
        try require(reader.activeSession?.sourceFingerprint == replacementHash && reader.document?.string?.contains("sessenta") == true, "A fila descartou bytes distintos por compartilharem a mesma URL.")
        try pinned.data.write(to: pinned.url)

        let pinnedProtected = try await privateStore.verifiedBytes(document: protectedID)
        try replacementBytes.write(to: pinnedProtected.url)
        reader.openVerified(data: pinnedProtected.data, url: pinnedProtected.url, sha: pinnedProtected.fingerprint, page: 2, title: "Citação protegida com bytes fixos")
        await reader.waitForPendingOpen()
        try require(reader.needsPassword, "A abertura verificada seguiu a URL substituída por plaintext em vez dos bytes protegidos.")
        try Data(contentsOf: changedA).write(to: pinnedProtected.url)
        reader.documentPassword = "intentionally-wrong-verified-password"; reader.unlockPendingDocument(); await reader.waitForPendingOpen()
        try require(reader.needsPassword && reader.activeSession?.sourceFingerprint != pinnedProtected.fingerprint, "Uma senha incorreta publicou ou substituiu uma fonte verificada protegida.")
        reader.documentPassword = secret; reader.unlockPendingDocument(); await reader.waitForPendingOpen()
        guard let verifiedProtectedSession = reader.activeSession else { throw LibraryFailure.invalidPDF }
        try require(verifiedProtectedSession.sourceFingerprint == pinnedProtected.fingerprint && verifiedProtectedSession.sourceURL == pinnedProtected.url && verifiedProtectedSession.password == secret && reader.currentPage == 2 && reader.document?.isEncrypted == true && reader.document?.string?.contains("trinta") == true, "O pedido de senha releu a URL ou perdeu bytes, hash, página ou proteção da referência.")
        reader.openVerified(data: pinnedProtected.data, url: pinnedProtected.url, sha: pinnedProtected.fingerprint, page: 1, title: "Fonte protegida já autenticada")
        await reader.waitForPendingOpen()
        try require(!reader.needsPassword && reader.activeSessionID == verifiedProtectedSession.id && reader.currentPage == 1, "Uma fonte autenticada com bytes idênticos não pôde ser reutilizada para comparar versões.")
        try pinnedProtected.data.write(to: pinnedProtected.url)
        for session in reader.sessions { reader.closeSession(session.id, discardChanges: true) }
        let cancel = NativeCancellation(); cancel.cancel()
        let cancellationRespected = await rejects { _ = try await storeA.excerpts(documentIDs: [id], cancellation: cancel) }
        try require(cancellationRespected, "Uma consulta cancelada continuou a extrair texto.")
        let task = Task { try Task.checkCancellation(); _ = try await storeA.synchronize(with: exchange) }
        task.cancel()
        let taskCancelled = await rejects { try await task.value }
        try require(taskCancelled, "A sincronização ignorou o cancelamento antes da execução.")
        let tooManyManifests = await rejects { try LibraryFiles.validateManifestBudget(count: 512, bytes: 100_000, addedBytes: 100) }
        let excessiveMetadata = await rejects { try LibraryFiles.validateManifestBudget(count: 20, bytes: 64 * 1_024 * 1_024 - 10, addedBytes: 11) }
        try require(tooManyManifests && excessiveMetadata, "A publicação excedeu o próprio limite da pasta de sincronização.")
        try LibraryFiles.validateManifestBudget(count: 512, bytes: 64 * 1_024 * 1_024, addedBytes: 0)
        print("PDF LIBRARY: \(count) verificações de cópias, coleções, histórico, fontes, conflitos, integridade e caminhos concluídas.")
    }
}
