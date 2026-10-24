import Foundation

/// Local, named queries. Their matches are recomputed against the current
/// catalog; saving/deleting a folder never moves or removes a PDF.
struct LibrarySmartFolder: Codable, Sendable, Equatable, Identifiable {
    let id: UUID
    var name: String
    var filter: LibrarySmartFilter
    let modified: Date
}

enum LibrarySmartFolders {
    static let maximumBytes = 256 * 1_024
    struct Snapshot: Codable {
        let version: Int
        let folders: [LibrarySmartFolder]
    }
    static func nameKey(_ name: String) -> String {
        name.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "pt_BR"))
    }
    static func validDate(_ value: Date) -> Bool {
        let seconds = value.timeIntervalSince1970
        return seconds.isFinite && (0...32_503_680_000).contains(seconds)
    }
    static func validate(_ snapshot: Snapshot) throws {
        guard snapshot.version == 1, snapshot.folders.count <= 64,
              Set(snapshot.folders.map(\.id)).count == snapshot.folders.count,
              Set(snapshot.folders.map { nameKey($0.name) }).count == snapshot.folders.count else { throw LibraryFailure.invalidMetadata }
        func text(_ string: String, maximum: Int, empty: Bool = true) -> Bool {
            (empty || !string.isEmpty) && string.count <= maximum && string.utf8.count <= maximum * 4 &&
            !string.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains)
        }
        for folder in snapshot.folders {
            let filter = folder.filter
            guard text(folder.name, maximum: 80, empty: false), folder.name == folder.name.trimmingCharacters(in: .whitespacesAndNewlines),
                  validDate(folder.modified), text(filter.text, maximum: 200), text(filter.collection, maximum: 80),
                  text(filter.tag, maximum: 40), filter.modifiedAfter.map(validDate) ?? true,
                  filter.modifiedBefore.map(validDate) ?? true else { throw LibraryFailure.invalidMetadata }
            if let lower = filter.modifiedAfter, let upper = filter.modifiedBefore, lower > upper { throw LibraryFailure.invalidMetadata }
        }
    }
}
