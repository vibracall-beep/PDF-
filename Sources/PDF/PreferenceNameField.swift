import SwiftUI

/// Typing may temporarily produce an empty value or a trailing space. Keep
/// that text in the field without replacing it with the persisted fallback.
struct PreferenceNameDraft {
    var text: String
    let maximum: Int
    private func valid(_ value:String) -> Bool {
        !value.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && value.count <= maximum &&
            value.unicodeScalars.allSatisfy { !CharacterSet.controlCharacters.contains($0) }
    }
    var liveValue:String? { valid(text) ? text : nil }
    func committedValue(fallback:String) throws -> String {
        let trimmed = text.trimmingCharacters(in:.whitespacesAndNewlines)
        let candidate = trimmed.isEmpty ? fallback : trimmed
        guard valid(candidate) else { throw PreferenceError.invalid("Use um nome de até \(maximum) caracteres, sem caracteres de controle.") }
        return candidate
    }
}

struct PreferenceNameField: View {
    let label:String
    @Binding var value:String
    let fallback:String
    @State private var draft:PreferenceNameDraft
    @State private var validation = ""
    @FocusState private var focused:Bool
    init(_ label:String,value:Binding<String>,maximum:Int,fallback:String) {
        self.label = label; _value = value; self.fallback = fallback
        _draft = State(initialValue:PreferenceNameDraft(text:value.wrappedValue,maximum:maximum))
    }
    var body:some View {
        TextField(label,text:Binding(get:{ draft.text },set:{ text in
            draft.text = text; validation = ""
            if let valid = draft.liveValue { value = valid }
        })).textFieldStyle(.roundedBorder)
            .focused($focused).onSubmit { commit() }
            .onChange(of:focused) { wasFocused,isFocused in if wasFocused && !isFocused { commit() } }
            .onChange(of:value) { _,newValue in if !focused { draft.text = newValue; validation = "" } }
            .accessibilityLabel(label)
            .accessibilityHint(validation)
            .help(validation.isEmpty ? "O nome muda enquanto você digita. Confirme com Return; deixe vazio e confirme para restaurar o nome original." : validation)
            .overlay { if !validation.isEmpty { RoundedRectangle(cornerRadius:5).stroke(.red,lineWidth:1).allowsHitTesting(false).accessibilityHidden(true) } }
    }
    private func commit() {
        do {
            let committed = try draft.committedValue(fallback:fallback)
            value = committed; draft.text = committed; validation = ""
        } catch { validation = error.localizedDescription }
    }
}
