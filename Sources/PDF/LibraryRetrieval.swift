import Foundation
import NaturalLanguage

struct LibraryExcerpt: Sendable, Identifiable, Equatable {
    let documentID: UUID
    let revisionID: UUID
    let fingerprint: String
    let title: String
    let page: Int
    let part: Int
    let text: String
    var id: String { documentID.uuidString + ":" + revisionID.uuidString + ":\(page):\(part)" }
}

struct LibrarySearchSource: Sendable {
    let excerpts: [LibraryExcerpt]
    let skipped: [String]
}

struct LibrarySearchResult: Sendable {
    let question: String
    let sources: [LibraryExcerpt]
    let method: String
    let skipped: [String]
    var response: String {
        sources.isEmpty
            ? "Não encontrei trechos de apoio nos documentos consultados. Reformule a busca, selecione outras fontes ou faça OCR nos arquivos digitalizados."
            : "Trechos encontrados nas fontes selecionadas. As citações abaixo reproduzem o texto extraído; a proximidade na busca não comprova uma conclusão."
    }
}

struct LibrarySmartFilter: Sendable {
    var text = ""
    var collection = ""
    var tag = ""
    var mode: Mode = .all
    enum Mode: String, CaseIterable, Identifiable {
        case all, recent, protected, duplicates, conflicts
        var id: String { rawValue }
        var title: String {
            switch self {
            case .all: return "Todos"
            case .recent: return "Últimos 7 dias"
            case .protected: return "Protegidos"
            case .duplicates: return "Conteúdo repetido"
            case .conflicts: return "Versões em conflito"
            }
        }
    }
    func apply(_ documents: [LibraryDocument], now: Date = Date()) -> [LibraryDocument] {
        let hashes = Dictionary(grouping: documents, by: { $0.current.fingerprint })
        let terms = SemanticRanking.words(text)
        return documents.filter { document in
            let current = document.current
            let labels = current.labels
            let haystack = SemanticRanking.words(([labels.title, labels.collection] + labels.tags).joined(separator: " "))
            guard terms.isSubset(of: haystack), collection.isEmpty || labels.collection == collection,
                  tag.isEmpty || labels.tags.contains(tag) else { return false }
            switch mode {
            case .all: return true
            case .recent: return current.created >= now.addingTimeInterval(-7 * 86_400)
            case .protected: return current.encrypted
            case .duplicates: return (hashes[current.fingerprint]?.count ?? 0) > 1
            case .conflicts: return document.heads.count > 1
            }
        }.sorted {
            if $0.current.created == $1.current.created { return $0.id.uuidString < $1.id.uuidString }
            return $0.current.created > $1.current.created
        }
    }
}

/// Search returns authentic excerpts rather than a generated factual answer.
/// Portuguese accent/case normalization is deterministic; installed Apple
/// embeddings can improve ranking but never manufacture quotes or provenance.
actor LibraryRetrieval {
    func search(question: String, source: LibrarySearchSource, useEmbeddings: Bool = true) throws -> LibrarySearchResult {
        try Task.checkCancellation()
        let query = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query.count <= 2_000, source.excerpts.count <= 50_000 else { throw LibraryFailure.tooLarge }
        guard !SemanticRanking.words(query).isEmpty else {
            return LibrarySearchResult(question: query, sources: [], method: "Busca por termos em português", skipped: source.skipped)
        }
        let mode = useEmbeddings ? LocalSemanticIndex.embedding(for: query) : nil
        let queryVector = mode?.vector(query)
        var candidates: [SemanticRanking.Candidate] = [], index: [String: LibraryExcerpt] = [:], embedded = 0, attempts = 0
        for excerpt in source.excerpts {
            try Task.checkCancellation()
            guard LibraryFiles.validHash(excerpt.fingerprint), excerpt.page > 0, index[excerpt.id] == nil,
                  !excerpt.text.isEmpty, excerpt.text.count <= 900 else { throw LibraryFailure.corrupt }
            index[excerpt.id] = excerpt
            // Bound local inference separately from text extraction. Lexical
            // candidates always include every selected excerpt.
            var vector: [Double]?
            if queryVector != nil && attempts < 2_000 { attempts += 1; vector = mode?.vector(excerpt.text) }
            if vector != nil { embedded += 1 }
            candidates.append(.init(excerpt: SourceExcerpt(id: excerpt.id, page: excerpt.page, text: excerpt.text), vector: vector))
        }
        let ranked = SemanticRanking.rank(question: query, vector: queryVector, candidates: candidates)
        var selected: [LibraryExcerpt] = [], characters = 0
        for match in ranked {
            guard let original = index[match.id], original.text == match.text, original.page == match.page else { throw LibraryFailure.corrupt }
            if selected.count == 8 || characters + original.text.count > 7_200 { break }
            selected.append(original); characters += original.text.count
        }
        let method = embedded > 0 ? "Termos pt-BR + NaturalLanguage local (até 2.000 trechos com vetores)" : "Termos pt-BR · sem modelo semântico nesta consulta"
        return LibrarySearchResult(question: query, sources: selected, method: method, skipped: source.skipped)
    }
}
