import AppIntents
import Foundation
import UniformTypeIdentifiers

@MainActor enum AppIntentsAuditChecks {
    static func run() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-AppIntents-Audit-"+UUID().uuidString,isDirectory:true)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:false)
        defer { try? FileManager.default.removeItem(at:folder) }
        func check(_ value:Bool,_ detail:String) throws { if !value { throw PreferenceError.invalid("App Intents: "+detail) } }
        let source = folder.appendingPathComponent("Fonte.pdf")
        try MacBenchmark.fixture(pages:2,to:source)
        let original = try Data(contentsOf:source)
        let file = IntentFile(fileURL:source,filename:"../"+String(repeating:"文",count:180)+".pdf",type:.pdf)
        let input = try PDFShortcutInput.prepare(file)
        defer { input.remove() }
        try check(input.url.deletingLastPathComponent() == input.directory,"nomes recebidos não podem sair da pasta privada")
        try check(input.url.lastPathComponent.utf8.count <= 184,"nomes Unicode precisam respeitar o limite em bytes")
        try check(try Data(contentsOf:input.url) == original,"a cópia deve preservar os bytes originais")
        try check(input.fingerprint == LibraryFiles.hash(original),"a identidade deve corresponder aos bytes recebidos")
        let mode = try FileManager.default.attributesOfItem(atPath:input.url.path)[.posixPermissions] as? NSNumber
        let directoryMode = try FileManager.default.attributesOfItem(atPath:input.directory.path)[.posixPermissions] as? NSNumber
        try check(mode?.intValue == 0o600 && directoryMode?.intValue == 0o700,"a entrada do Atalho precisa de permissões privadas")
        let link = folder.appendingPathComponent("link.pdf")
        try FileManager.default.createSymbolicLink(at:link,withDestinationURL:source)
        var rejected = false
        do { let unexpected = try PDFShortcutInput.prepare(IntentFile(fileURL:link,type:.pdf)); unexpected.remove() } catch { rejected = true }
        try check(rejected,"a transferência por arquivo não deve seguir link simbólico")
        rejected = false
        do { let unexpected = try PDFShortcutInput.prepare(IntentFile(data:Data("Not a PDF".utf8),filename:"invalid.pdf",type:.pdf)); unexpected.remove() } catch { rejected = true }
        try check(rejected,"conteúdo inválido deve ser recusado antes de criar uma cópia")
        input.remove()
        try check(!FileManager.default.fileExists(atPath:input.directory.path),"a limpeza deve remover a cópia transitória")
        try check(try Data(contentsOf:source) == original,"o original deve continuar intacto após a limpeza")
        print("App Intents input audit passed: bounded Unicode names, exact bytes, source preservation, private permissions, invalid input and symlink refusal; OS discovery requires metadata verification")
    }
}
