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
        let searchSource = try await storeA.excerpts(documentIDs: [id], cancellation: NativeCancellation())
        let retrieval = LibraryRetrieval()
        let result = try await retrieval.search(question: "PAGAMENTO AÇÃO", source: searchSource, useEmbeddings: false)
        try require(!result.sources.isEmpty && result.sources.allSatisfy { $0.documentID == id && $0.fingerprint == initial.fingerprint && $0.page == 1 }, "A busca perdeu origem, hash ou página.")
        try require(result.sources.allSatisfy { searchSource.excerpts.contains($0) }, "A busca inventou uma citação.")
        let absent = try await retrieval.search(question: "galáxia extraterrestre", source: searchSource, useEmbeddings: false)
        try require(absent.sources.isEmpty && absent.response.contains("Não encontrei"), "A busca sem apoio exibiu uma conclusão.")
        let empty = try await retrieval.search(question: "de o a e", source: searchSource, useEmbeddings: false)
        try require(empty.sources.isEmpty, "Termos vazios selecionaram fontes arbitrárias.")

        let exchange = root.appendingPathComponent("Chosen Sync Folder")
        try LibraryFiles.directory(exchange, create: true)
        _ = try await storeA.synchronize(with: exchange)
        let received = try await storeB.synchronize(with: exchange)
        try require(received.catalog.documents.count == 1 && received.catalog.documents[0].current.labels.title == "Contrato principal", "O segundo Mac não recebeu a coleção.")
        let bURL = try await storeB.verifiedURL(document: id)
        try require(try Data(contentsOf: bURL) == original, "A sincronização modificou o PDF.")
        _ = try await storeA.addVersion(document: id, source: changedA)
        _ = try await storeB.addVersion(document: id, source: changedB)
        _ = try await storeA.synchronize(with: exchange)
        let divergent = try await storeB.synchronize(with: exchange)
        try require(divergent.conflicts == 1 && divergent.catalog.documents[0].heads.count == 2, "Versões independentes foram sobrescritas silenciosamente.")
        let resolvedA = try await storeA.synchronize(with: exchange)
        try require(resolvedA.conflicts == 1 && resolvedA.catalog.documents[0].heads.count == 2, "O conflito não chegou ao primeiro Mac.")
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
        try original.write(to: copiedURL)
        let beforeBadSync = try LibraryFiles.read(directoryA.appendingPathComponent("current.json"), maximum: 1_024)
        let remoteObject = exchange.appendingPathComponent("PDF Library Exchange/objects/" + initial.fingerprint + ".pdf")
        try Data("%PDF-corrupt-peer".utf8).write(to: remoteObject)
        let corruptSync = await rejects { _ = try await storeA.synchronize(with: exchange) }
        try require(corruptSync, "Um objeto remoto danificado foi ignorado ou substituído silenciosamente.")
        try require(try LibraryFiles.read(directoryA.appendingPathComponent("current.json"), maximum: 1_024) == beforeBadSync, "Uma sincronização incompleta publicou outro catálogo.")
        try original.write(to: remoteObject)
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
