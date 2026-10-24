/// Count labels used by the Portuguese interface. Keep the number unchanged;
/// only the noun and its agreeing words vary for exactly one item.
enum PortugueseCount {
    static func form(_ count: Int, _ singular: String, _ plural: String) -> String {
        count == 1 ? singular : plural
    }

    static func label(_ count: Int, _ singular: String, _ plural: String) -> String {
        "\(count) \(form(count, singular, plural))"
    }
}
