import AppKit
import PDFKit
import NaturalLanguage

struct LocalAICheck: Codable, Sendable, Identifiable {
    let id: String
    let passed: Bool
    let detail: String
}
struct LocalAICitationEvidence: Codable, Sendable {
    let sourceID: String
    let documentID: UUID
    let revisionID: UUID
    let documentSHA256: String
    let title: String
    let page: Int
    let quote: String
    let literalAfterWhitespaceNormalization: Bool
}
struct LocalAIAuditItem: Codable, Sendable, Identifiable {
    let id: String
    let question: String
    let expectation: String
    let status: String
    let modelAttempted: Bool
    let milliseconds: Double
    let retrievalMethod: String
    let retrievedSourceIDs: [String]
    let response: String?
    let detectedLanguage: String?
    let citations: [LocalAICitationEvidence]
    let checks: [LocalAICheck]
    let error: String?
}
struct LocalAIFixtureEvidence: Codable, Sendable {
    let title: String
    let documentID: UUID
    let revisionID: UUID
    let sha256: String
    let pages: Int
}
struct LocalAIReport: Codable, Sendable {
    let schemaVersion: Int
    let createdAt: Date
    let status: String
    let model: String
    let availabilityReason: String?
    let language: String
    let operatingSystem: String
    let hardware: String
    let fixtureVersion: String
    let documents: [LocalAIFixtureEvidence]
    let items: [LocalAIAuditItem]
    let totalMilliseconds: Double
    let methodology: String
    let limitations: [String]
}

/// This is a real, small acceptance experiment, not a mocked model score. The
/// ordinary library importer, PDF extractor, retriever and answering validators
/// process two private synthetic PDFs. No response is substituted when the local
/// Apple model is absent or fails, and no user's library/defaults are touched.
@MainActor enum LocalAIAudit {
    private struct Question {
        let id: String
        let text: String
        let expectation: String
    }
    private static let questions = [
        Question(id: "responsavel", text: "Quem é a responsável técnica do Projeto Aurora?", expectation: "Beatriz Lima, com citação do Plano operacional, página 1."),
        Question(id: "orcamento", text: "Qual é o orçamento aprovado do Projeto Aurora?", expectation: "R$ 48.000, com citação do Plano operacional, página 1."),
        Question(id: "participantes", text: "Quantos participantes a oficina do Projeto Aurora admite?", expectation: "24 participantes, com citação do Plano operacional, página 2."),
        Question(id: "sem-apoio", text: "Qual é o CPF de Beatriz Lima, responsável técnica do Projeto Aurora?", expectation: "Recusa explícita por falta de evidência; nenhuma citação apresentada como apoio ao CPF."),
        Question(id: "divergencia", text: "Os documentos do Projeto Aurora apresentam prazos diferentes para a entrega contratada? Compare as datas sem decidir qual prevalece.", expectation: "Possível divergência: 18 de novembro de 2026 no Plano operacional e 25 de novembro de 2026 na Revisão de cronograma; documentos e citações distintos.")
    ]
    static func run(to output: URL) async throws -> LocalAIReport {
        guard !FileManager.default.fileExists(atPath: output.path) else { throw PreferenceError.invalid("O relatório de IA já existe. Escolha um novo destino.") }
        let report = try await measure(workDirectory: output.deletingLastPathComponent())
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]; encoder.dateEncodingStrategy = .iso8601
        try NativeOutput.write(encoder.encode(report), to: output)
        return report
    }
    static func measure(workDirectory: URL? = nil) async throws -> LocalAIReport {
        let started = ProcessInfo.processInfo.systemUptime
        let directory = (workDirectory ?? FileManager.default.temporaryDirectory).appendingPathComponent("PDF-LocalAI-Audit-"+UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = directory.appendingPathComponent("Plano operacional.pdf")
        let second = directory.appendingPathComponent("Revisão de cronograma.pdf")
        try fixture(pages: [
            ["Projeto Aurora — plano operacional", "A entrega contratada é em 18 de novembro de 2026.", "O orçamento aprovado é de R$ 48.000.", "A responsável técnica é Beatriz Lima."],
            ["Projeto Aurora — oficina", "A oficina admite 24 participantes.", "A inscrição encerra em 10 de novembro de 2026.", "O CPF da responsável técnica não consta neste documento."]
        ], to: first)
        try fixture(pages: [
            ["Projeto Aurora — revisão de cronograma", "A entrega contratada é em 25 de novembro de 2026.", "Este documento não informa qual prazo prevalece.", "A revisão foi registrada em 2 de outubro de 2026."],
            ["Projeto Aurora — pagamento", "O pagamento será feito em duas parcelas de R$ 24.000.", "Nenhum número de CPF foi registrado nesta revisão."]
        ], to: second)
        let library = DocumentLibraryStore(directory: directory.appendingPathComponent("library", isDirectory: true))
        let imported = try await library.importFiles([first, second])
        let documents = imported.catalog.documents.map { item in
            LocalAIFixtureEvidence(title: item.current.labels.title, documentID: item.id, revisionID: item.current.id,
                sha256: item.current.fingerprint, pages: item.current.pages)
        }
        guard documents.count == 2, documents.allSatisfy({ $0.pages == 2 }) else { throw LibraryFailure.invalidPDF }
        let source = try await library.excerpts(documentIDs: Set(documents.map(\.documentID)), cancellation: NativeCancellation())
        guard source.skipped.isEmpty, Set(source.excerpts.map(\.documentID)).count == 2 else { throw LibraryFailure.invalidPDF }
        let unavailable = LibraryAnswering.availabilityMessage
        var items: [LocalAIAuditItem] = []
        for question in questions {
            try Task.checkCancellation()
            items.append(await evaluate(question, source: source, unavailable: unavailable))
        }
        let status = unavailable != nil && items.allSatisfy({ $0.status == "unavailable" }) ? "unavailable" : (items.allSatisfy({ $0.status == "passed" }) ? "sample_passed" : "sample_failed")
        return LocalAIReport(schemaVersion: 1, createdAt: Date(), status: status,
            model: "Apple FoundationModels · SystemLanguageModel.default · geração local real", availabilityReason: unavailable,
            language: "pt-BR", operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString, hardware: AppleHardware.summary,
            fixtureVersion: "aurora-pt-BR-v1", documents: documents, items: items,
            totalMilliseconds: (ProcessInfo.processInfo.systemUptime-started)*1_000,
            methodology: "Dois PDFs sintéticos de duas páginas são criados, importados em biblioteca privada, extraídos e pesquisados pelo pipeline de produção. Cinco solicitações independentes usam LibraryAnswering.respond/compare e o modelo Apple disponível. Cada citação é revalidada por identidade, revisão, SHA, página e trecho literal após normalização de espaços/NFC. Gabaritos verificam fatos controlados e atribuição à fonte; não há resposta simulada, rede, download de modelo nem documentos do usuário.",
            limitations: ["Cinco casos e uma amostra por caso não estimam a qualidade geral, variabilidade entre execuções ou desempenho em documentos complexos.", "Os testes de fatos usam vocabulário afirmativo controlado e recusam negações, nomes e números adicionais. Esse critério conservador pode reprovar uma formulação correta mais complexa; passar não prova entailment geral nem substitui revisão humana.", "O idioma é identificado automaticamente apenas em respostas com pelo menos 60 caracteres; respostas curtas ficam sem avaliação linguística.", "Tempos incluem busca e validação, sem aquecimento; refletem este Mac, versão do sistema e disponibilidade corrente do modelo.", "Se Apple Intelligence estiver indisponível, todos os itens registram unavailable e nenhuma qualidade de geração é aprovada."])
    }
    private static func evaluate(_ question: Question, source: LibrarySearchSource, unavailable: String?) async -> LocalAIAuditItem {
        let started = ProcessInfo.processInfo.systemUptime
        var result: LibrarySearchResult?
        var attempted = false
        do {
            let search = try await LibraryRetrieval().search(question: question.text, source: source)
            result = search
            guard !search.sources.isEmpty else { throw PreferenceError.invalid("A busca não recuperou o contexto necessário para avaliar este caso; nenhum resultado vazio será contado como recusa do modelo.") }
            if let unavailable {
                return item(question, status: "unavailable", attempted: false, started: started, result: search, error: unavailable)
            }
            try Task.checkCancellation(); attempted = true
            let text: String
            let citations: [LibraryAnswerCitation]
            var checks: [LocalAICheck]
            if question.id == "divergencia" {
                guard Set(search.sources.map(\.documentID)).count == 2 else { throw PreferenceError.invalid("A busca não recuperou ambos os documentos para a comparação.") }
                let response = try await LibraryAnswering.compare(search)
                text = response.pairs.map { "\($0.topic): \($0.first.claim) / \($0.second.claim)" }.joined(separator: "\n")
                citations = response.pairs.flatMap { [$0.first.citation, $0.second.citation] }
                let expected = response.pairs.contains { pair in
                    let claims = [pair.first, pair.second]
                    return claims.contains(where: { expectedDate($0.claim, day: "18") && $0.citation.source.title == "Plano operacional" && expectedDate($0.citation.quote, day: "18") })
                        && claims.contains(where: { expectedDate($0.claim, day: "25") && $0.citation.source.title == "Revisão de cronograma" && expectedDate($0.citation.quote, day: "25") })
                        && pair.first.citation.source.documentID != pair.second.citation.source.documentID
                }
                checks = [.init(id: "golden-divergence-attribution", passed: expected, detail: question.expectation)]
            } else {
                let response = try await LibraryAnswering.respond(to: search)
                text = response.text; citations = response.citations
                checks = answerChecks(question, answer: response)
            }
            let evidence = citations.map { citation in Self.evidence(citation, search: search, source: source) }
            checks.append(.init(id: "citation-identities-and-literal", passed: evidence.allSatisfy(\.literalAfterWhitespaceNormalization), detail: "Todas as referências pertencem à consulta e ao texto extraído da página/hash indicados; somente espaços e NFC são normalizados."))
            let language = detectedLanguage(text)
            if text.count >= 60 { checks.append(.init(id: "portuguese-language", passed: language == "pt", detail: "Idioma dominante identificado automaticamente em texto com pelo menos 60 caracteres: \(language ?? "indeterminado").")) }
            return item(question, status: checks.allSatisfy(\.passed) ? "passed" : "failed", attempted: true, started: started,
                result: search, response: text, language: language, citations: evidence, checks: checks)
        } catch {
            return item(question, status: error is CancellationError ? "cancelled" : "error", attempted: attempted, started: started, result: result, error: error.localizedDescription)
        }
    }
    private static func answerChecks(_ question: Question, answer: LibraryGeneratedAnswer) -> [LocalAICheck] {
        if question.id == "sem-apoio" {
            return [.init(id: "golden-abstention", passed: answer.citations.isEmpty && answer.text.contains("não fornecem evidências suficientes"), detail: question.expectation)]
        }
        func containsFact(_ text: String) -> Bool {
            let value = folded(text)
            switch question.id {
            case "responsavel": return value.contains("beatriz lima")
            case "orcamento": return budgetMatches(value, requireOnlyExpectedNumbers: false)
            default: return value.range(of: "(?<![0-9])24(?![0-9])", options: .regularExpression) != nil || value.contains("vinte e quatro")
            }
        }
        let page = question.id == "participantes" ? 2 : 1
        let correctSource = answer.citations.contains { $0.source.title == "Plano operacional" && $0.source.page == page && containsFact($0.quote) }
        return [.init(id: "golden-fact", passed: containsFact(answer.text), detail: question.expectation),
                .init(id: "controlled-affirmative-answer", passed: controlledAffirmative(answer.text, questionID: question.id, page: page), detail: "Formulação afirmativa dentro do vocabulário controlado, sem negação, nomes ou valores adicionais; formulações complexas exigem revisão humana."),
                .init(id: "golden-source-page-and-quote", passed: correctSource, detail: "A resposta deve citar o fato esperado no Plano operacional, página \(page).")]
    }
    private static func controlledAffirmative(_ text: String, questionID: String, page: Int) -> Bool {
        // A token-presence score would incorrectly accept “não é 48.000”. This
        // deliberately conservative fixture evaluator accepts only affirmative
        // wording for the single requested fact, not arbitrary generated prose.
        guard !text.contains("?") else { return false }
        let value = folded(text).replacingOccurrences(of: "chama-se", with: "chama")
            .replacingOccurrences(of: "\\bpagina +\(page)\\b", with: "", options: .regularExpression)
        if questionID == "orcamento", !budgetMatches(value, requireOnlyExpectedNumbers: true) { return false }
        let words = Set(value.split { !$0.isLetter && !$0.isNumber }.map(String.init))
        let common = Set("a o as os um uma de da do das dos e em no na nos nas para por com que qual quais como foi sao ao aos segundo conforme acordo documento documentos plano operacional projeto aurora informacao informacoes fornecido fornecida fornecidos fornecidas consta citado citada indicado indicada indica informa identifica especifica registrado registrada descrito descrita mencionado mencionada apresentado apresentada esta esse este essa refere ser sendo tem possui cujo cuja seu sua pela pelo texto fonte dados".split(separator: " ").map(String.init))
        let specific: String
        switch questionID {
        case "responsavel": specific = "beatriz lima responsavel tecnica nome profissional responsabilidade funcao exerce ocupa nomeada nomeado chama"
        case "orcamento": specific = "orcamento aprovado aprovada valor montante total totaliza corresponde reais real r rs 48 000 00 48000 mil quarenta oito"
        default: specific = "oficina admite participantes participante pessoas pessoa capacidade limite total ate 24 vinte quatro"
        }
        let allowed = common.union(specific.split(separator: " ").map(String.init))
        return !words.isEmpty && words.isSubset(of: allowed)
    }
    private static func budgetMatches(_ value: String, requireOnlyExpectedNumbers: Bool) -> Bool {
        // Read an entire numeric token, including every grouping/decimal part.
        // Splitting on punctuation would confuse 48.000.000 with 48.000.
        guard let expression = try? NSRegularExpression(pattern: "[0-9]+(?:[., ]+[0-9]+)*") else { return false }
        let source = value as NSString
        let matches = expression.matches(in: value, range: NSRange(location: 0, length: source.length))
        let expected = matches.map { match -> Bool in
            let token = source.substring(with: match.range)
                .replacingOccurrences(of: ".", with: "").replacingOccurrences(of: " ", with: "")
            if ["48000", "48000,00"].contains(token) { return true }
            let suffix = source.substring(from: NSMaxRange(match.range))
            return token == "48" && suffix.range(of: "^ +mil\\b", options: .regularExpression) != nil
        }
        let written = value.range(of: "\\bquarenta e oito mil\\b", options: .regularExpression) != nil
        return (written || expected.contains(true)) && (!requireOnlyExpectedNumbers || expected.allSatisfy { $0 })
    }
    private static func evidence(_ citation: LibraryAnswerCitation, search: LibrarySearchResult, source: LibrarySearchSource) -> LocalAICitationEvidence {
        let known = source.excerpts.contains(citation.source) && search.sources.contains(citation.source)
        let literal = SemanticEvidence.normalized(citation.source.text).contains(SemanticEvidence.normalized(citation.quote)) && citation.quote.count >= 12
        return LocalAICitationEvidence(sourceID: citation.source.id, documentID: citation.source.documentID,
            revisionID: citation.source.revisionID, documentSHA256: citation.source.fingerprint, title: citation.source.title,
            page: citation.source.page, quote: citation.quote, literalAfterWhitespaceNormalization: known && literal)
    }
    private static func item(_ question: Question, status: String, attempted: Bool, started: Double, result: LibrarySearchResult?, response: String? = nil, language: String? = nil, citations: [LocalAICitationEvidence] = [], checks: [LocalAICheck] = [], error: String? = nil) -> LocalAIAuditItem {
        LocalAIAuditItem(id: question.id, question: question.text, expectation: question.expectation, status: status,
            modelAttempted: attempted, milliseconds: (ProcessInfo.processInfo.systemUptime-started)*1_000,
            retrievalMethod: result?.method ?? "Busca não concluída", retrievedSourceIDs: result?.sources.map(\.id) ?? [],
            response: response, detectedLanguage: language, citations: citations, checks: checks, error: error)
    }
    private static func expectedDate(_ text: String, day: String) -> Bool {
        let value = folded(text)
        let pattern = "(?<![0-9])\(day)(?: de novembro de |/11/|-11-)2026(?![0-9])"
        return value.range(of: pattern, options: .regularExpression) != nil
    }
    private static func folded(_ text: String) -> String { SemanticEvidence.normalized(text).folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "pt_BR")) }
    private static func detectedLanguage(_ text: String) -> String? {
        guard text.count >= 60 else { return nil }
        let recognizer = NLLanguageRecognizer(); recognizer.processString(text); return recognizer.dominantLanguage?.rawValue
    }
    private static func fixture(pages: [[String]], to url: URL) throws {
        var bounds = CGRect(x: 0, y: 0, width: 595, height: 842)
        guard let context = CGContext(url as CFURL, mediaBox: &bounds, nil) else { throw LibraryFailure.invalidPDF }
        for lines in pages {
            context.beginPDFPage(nil); NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
            for (index, line) in lines.enumerated() {
                (line as NSString).draw(at: NSPoint(x: 40, y: CGFloat(780-index*34)), withAttributes: [.font: NSFont.systemFont(ofSize: index == 0 ? 15 : 12), .foregroundColor: NSColor.black])
            }
            NSGraphicsContext.restoreGraphicsState(); context.endPDFPage()
        }
        context.closePDF()
    }
    /// These negative checks validate the evaluator, without invoking a model
    /// or treating constructed answers as evidence of actual AI quality.
    static func validateCriteria() throws {
        func require(_ value: Bool, _ message: String) throws { if !value { throw PreferenceError.invalid("Critério da avaliação IA: "+message) } }
        let text = "O orçamento aprovado é de R$ 48.000. A responsável técnica é Beatriz Lima."
        let source = LibraryExcerpt(documentID: UUID(), revisionID: UUID(), fingerprint: String(repeating: "a", count: 64), title: "Plano operacional", page: 1, part: 0, text: text)
        let reference = LibraryAnswerCitation(source: source, quote: "O orçamento aprovado é de R$ 48.000.")
        let question = questions.first { $0.id == "orcamento" }!
        let valid = LibraryGeneratedAnswer(text: "O orçamento aprovado é de R$ 48.000.", citations: [reference])
        try require(answerChecks(question, answer: valid).allSatisfy(\.passed), "gabarito controlado válido foi recusado")
        for amount in ["48000", "48.000", "48 000", "48.000,00", "48000,00", "48 mil", "quarenta e oito mil"] {
            try require(answerChecks(question, answer: .init(text: "O orçamento aprovado é R$ \(amount).", citations: [reference])).allSatisfy(\.passed), "formato válido de 48 mil foi recusado: \(amount)")
        }
        for amount in ["48.000.000", "48 000 000", "48.000.000,00", "48.000,01", "48.000,000", "48.000 e 48.000.000"] {
            try require(!answerChecks(question, answer: .init(text: "O orçamento aprovado é R$ \(amount).", citations: [reference])).allSatisfy(\.passed), "token numérico completo divergente foi aceito: \(amount)")
        }
        let falseNumber = LibraryGeneratedAnswer(text: "O orçamento é de R$ 148.000.", citations: [reference])
        try require(!answerChecks(question, answer: falseNumber).allSatisfy(\.passed), "número com substring do gabarito foi aceito")
        for text in ["O orçamento NÃO é R$ 48.000; é R$ 99.000.", "O orçamento é R$ 48.000 e R$ 99.000.", "O orçamento de R$ 48.000 está incorreto.", "O orçamento é R$ 48.000?", "Se o orçamento é R$ 48.000."] {
            try require(!answerChecks(question, answer: .init(text: text, citations: [reference])).allSatisfy(\.passed), "negação ou valor conflitante foi aceito junto do gabarito")
        }
        let responsible = questions.first { $0.id == "responsavel" }!
        let personReference = LibraryAnswerCitation(source: source, quote: "A responsável técnica é Beatriz Lima.")
        try require(answerChecks(responsible, answer: .init(text: "Beatriz Lima é a responsável técnica do Projeto Aurora.", citations: [personReference])).allSatisfy(\.passed), "formulação afirmativa do nome foi recusada")
        for text in ["Beatriz Lima não é a responsável técnica.", "Beatriz Lima consta no documento. Ana Costa é a responsável técnica."] {
            try require(!answerChecks(responsible, answer: .init(text: text, citations: [personReference])).allSatisfy(\.passed), "negação ou pessoa adicional foi aceita")
        }
        let wrongQuote = LibraryGeneratedAnswer(text: valid.text, citations: [.init(source: source, quote: "A responsável técnica é Beatriz Lima.")])
        try require(!answerChecks(question, answer: wrongQuote).allSatisfy(\.passed), "citação sem o fato esperado foi aceita")
        let search = LibrarySearchResult(question: question.text, sources: [source], method: "Validação estrutural sem modelo", skipped: [])
        let all = LibrarySearchSource(excerpts: [source], skipped: [])
        let fabricated = LibraryAnswerCitation(source: source, quote: "O orçamento aprovado é de R$ 99.000.")
        try require(!evidence(fabricated, search: search, source: all).literalAfterWhitespaceNormalization, "trecho fabricado foi aceito")
        let other = LibraryExcerpt(documentID: UUID(), revisionID: UUID(), fingerprint: source.fingerprint, title: source.title, page: source.page, part: 0, text: text)
        try require(!evidence(.init(source: other, quote: reference.quote), search: search, source: all).literalAfterWhitespaceNormalization, "identidade de documento alheio foi aceita")
        try require(!expectedDate("28 de novembro de 2026", day: "18"), "prazo divergente foi aceito como gabarito")
        try require(!expectedDate("118/11/20260", day: "18"), "substring de data inválida foi aceita")
        print("Local AI evaluator criteria passed with negative fixtures; no model was invoked and no AI quality claim is made")
    }
}
