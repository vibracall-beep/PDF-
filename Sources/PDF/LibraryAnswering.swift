import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

struct LibraryAnswerCitation: Sendable, Identifiable {
    let source: LibraryExcerpt
    let quote: String
    var id: String { source.id + ":" + quote }
}

struct LibraryGeneratedAnswer: Sendable {
    let text: String
    let citations: [LibraryAnswerCitation]
}

enum LibraryAnswering {
    private static func sourceID(_ source: LibraryExcerpt) -> String {
        "s" + LibraryFiles.hash(Data((source.id + ":" + source.fingerprint).utf8))
    }
    static func context(_ result: LibrarySearchResult) throws -> SemanticContext {
        guard !result.question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              result.question.count <= 800, result.question.utf8.count <= 4_096, result.sources.count <= 8,
              Set(result.sources.map(\.id)).count == result.sources.count,
              result.sources.allSatisfy({ LibraryFiles.validHash($0.fingerprint) && $0.page > 0 && !$0.text.isEmpty && $0.text.count <= 900 && $0.text.utf8.count <= 8_192 }) else {
            throw SemanticEvidence.failure("A resposta local exige uma pergunta de até 800 caracteres e fontes válidas desta consulta.")
        }
        let excerpts = result.sources.map { SourceExcerpt(id: sourceID($0), page: $0.page, text: $0.text) }
        guard Set(excerpts.map(\.id)).count == excerpts.count else { throw LibraryFailure.corrupt }
        return SemanticEvidence.bounded(excerpts, budget: 4_500, method: result.method)
    }
    static func validate(_ answer: GroundedAnswer, result: LibrarySearchResult) throws -> LibraryGeneratedAnswer {
        let context = try context(result)
        let (text, references) = try answer.validated(in: context)
        let sources = Dictionary(uniqueKeysWithValues: result.sources.map { (sourceID($0), $0) })
        let citations = try references.map { reference -> LibraryAnswerCitation in
            guard let source = sources[reference.excerpt], source.page == reference.page else { throw LibraryFailure.corrupt }
            return LibraryAnswerCitation(source: source, quote: reference.quote)
        }
        return LibraryGeneratedAnswer(text: text, citations: citations)
    }
    @MainActor static var availabilityMessage: String? {
        #if canImport(FoundationModels)
        switch SystemLanguageModel.default.availability {
        case .available: return nil
        case .unavailable(let reason): return "Apple Intelligence indisponível neste Mac: \(reason). A busca e as citações continuam disponíveis."
        }
        #else
        return "Esta compilação não inclui o modelo local Apple. A busca e as citações continuam disponíveis."
        #endif
    }
    @MainActor static func respond(to result: LibrarySearchResult) async throws -> LibraryGeneratedAnswer {
        try Task.checkCancellation()
        let context = try context(result)
        guard !context.isEmpty else {
            return LibraryGeneratedAnswer(text: "As fontes consultadas não fornecem trechos de apoio para responder. Selecione documentos ou reformule a pergunta.", citations: [])
        }
        if let unavailable = availabilityMessage { throw SemanticEvidence.failure(unavailable) }
        #if canImport(FoundationModels)
        let instructions = GroundedPrompt.trust + """

        Responda em português à pergunta usando exclusivamente as fontes desta consulta, que podem pertencer a documentos distintos. Nunca combine afirmações de documentos diferentes como se fossem um único fato. Cada afirmação factual deve ter apoio nas citações. Retorne somente JSON válido: {"supported":true,"answer":"resposta concisa em português","citations":[{"excerpt":"ID exato de um trecho fornecido","quote":"frase literal de pelo menos 12 caracteres que apoia a resposta"}]}. Não invente IDs, documentos, páginas ou conteúdo. Se os trechos forem insuficientes, retorne supported false, citations [] e uma explicação da insuficiência no campo answer.
        """
        let session = LanguageModelSession(instructions: instructions)
        let prompt = "Pergunta do usuário: \(result.question)\n" + (try GroundedPrompt.data(context.excerpts))
        let response = try await session.respond(to: prompt)
        try Task.checkCancellation()
        let answer = try IntelligenceText.decodeJSON(response.content, as: GroundedAnswer.self)
        return try validate(answer, result: result)
        #else
        throw SemanticEvidence.failure("O modelo local Apple não está disponível nesta compilação.")
        #endif
    }
}
