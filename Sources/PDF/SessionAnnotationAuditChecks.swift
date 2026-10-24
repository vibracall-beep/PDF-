import AppKit
import PDFKit
import CoreGraphics
import SwiftUI

@MainActor enum SessionAnnotationAuditChecks {
    static func run() async throws {
        func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
            guard try condition() else { throw NSError(domain: "PDF.SessionAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func rejects(_ body: () throws -> Void) -> Bool { do { try body(); return false } catch { return true } }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PDF-session-audit-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let suite = "PDF.SessionAudit.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else { throw NSError(domain: "PDF.SessionAudit", code: 2) }
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set(false, forKey: "recoveryEnabled")
        defaults.set(false, forKey: "readerAutoScale"); defaults.set(1.5, forKey: "readerZoom")
        let store = RecoveryStore(directory: directory.appendingPathComponent("Recovery", isDirectory: true))
        let firstURL = directory.appendingPathComponent("first.pdf"), secondURL = directory.appendingPathComponent("second.pdf")
        guard let first = PDFDocument(data: try IntelligenceText.PDF("Primeiro documento — sessão de teste.")),
              let firstPage = first.page(at: 0), let secondPage = firstPage.copy() as? PDFPage else { throw NSError(domain: "PDF.SessionAudit", code: 3) }
        first.insert(secondPage, at: 1)
        let widget = PDFAnnotation(bounds: CGRect(x: 70, y: 600, width: 180, height: 25), forType: .widget, withProperties: nil)
        widget.widgetFieldType = .text; widget.fieldName = "session-field"; widget.widgetStringValue = "Original"
        firstPage.addAnnotation(widget)
        guard let firstBytes = first.dataRepresentation() else { throw NSError(domain: "PDF.SessionAudit", code: 4) }
        try NativeOutput.write(firstBytes, to: firstURL)
        try NativeOutput.write(IntelligenceText.PDF("Segundo documento independente."), to: secondURL)
        let workspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        workspace.open(url: firstURL)
        await workspace.waitForPendingOpen()
        guard let firstSession = workspace.activeSession, let openedPage = workspace.document?.page(at: 0) else { throw NSError(domain: "PDF.SessionAudit", code: 5) }
        try require(workspace.message == "2 páginas · first.pdf", "A abertura não identificou a primeira sessão no rodapé.")
        try require(firstSession.zoom == 1.5 && !firstSession.autoScale,
                    "Uma nova sessão ignorou o zoom e o ajuste automático escolhidos nas preferências.")
        let view = PDFView(frame: CGRect(x: 0, y: 0, width: 800, height: 600)); view.document = workspace.document
        workspace.pdfView = view; view.autoScales = false; view.scaleFactor = 1.75
        workspace.currentPage = 2; workspace.bookmarks = [2]
        openedPage.annotations.first { $0.fieldName == "session-field" }?.widgetStringValue = "Alterado na primeira aba"
        defaults.set(true, forKey: "readerAutoScale"); defaults.set(2.25, forKey: "readerZoom")
        workspace.open(url: secondURL)
        await workspace.waitForPendingOpen()
        guard let secondSession = workspace.activeSession else { throw NSError(domain: "PDF.SessionAudit", code: 6) }
        try require(workspace.message == "1 página · second.pdf", "A abertura da segunda sessão manteve a identidade da primeira no rodapé.")
        try require(secondSession.zoom == 2.25 && secondSession.autoScale && !firstSession.autoScale,
                    "As preferências de uma nova aba sobrescreveram o estado da aba já aberta.")
        try require(workspace.sessions.count == 2 && firstSession.isDirty && !secondSession.isDirty, "Abrir outra aba perdeu o documento ou alterações de formulário.")
        try require(firstSession.page == 2 && abs(firstSession.zoom - 1.75) < 0.01 && firstSession.bookmarks == [2], "A primeira aba perdeu página, zoom ou marcas.")
        workspace.activateSession(firstSession.id)
        try require(workspace.document === firstSession.document && workspace.currentPage == 2 && workspace.hasUnsavedChanges, "Selecionar a aba não restaurou documento e alterações.")
        try require(workspace.message == "2 páginas · first.pdf", "Reativar a primeira aba deixou o nome do documento anterior no rodapé.")
        workspace.busy = true; workspace.message = "Convertendo documento de teste…"
        workspace.activateSession(secondSession.id)
        try require(workspace.busy && workspace.message == "Convertendo documento de teste…", "Trocar aba substituiu a mensagem da operação em andamento.")
        workspace.busy = false; workspace.lastOutput = secondURL; workspace.message = "Concluído: resultado de teste.pdf"
        workspace.activateSession(firstSession.id)
        try require(workspace.message == "Concluído: resultado de teste.pdf" && workspace.lastOutput == secondURL,
                    "Trocar aba apagou a mensagem ou o destino de uma operação concluída.")
        workspace.message = "Não foi possível exportar o documento de teste."
        workspace.activateSession(secondSession.id)
        try require(workspace.message == "Não foi possível exportar o documento de teste.", "Trocar aba ocultou uma mensagem de erro.")
        workspace.message = ""; workspace.lastOutput = nil
        workspace.activateSession(firstSession.id)
        try require(workspace.message == "2 páginas · first.pdf", "Um rodapé vazio não retomou a identidade da aba ativa.")
        workspace.comparisonSessionID = secondSession.id
        secondSession.page = 1; secondSession.zoom = 2.1; secondSession.autoScale = false
        try require(workspace.currentPage == 2 && firstSession.zoom != secondSession.zoom, "O documento de referência alterou a navegação principal.")
        do {
            defaults.set("horizontal", forKey: "readerDirection"); defaults.set("media", forKey: "readerDisplayBox")
            defaults.set("#204060", forKey: "readerPageBackground"); defaults.set(false, forKey: "readerDisplayPageBreaks")
            let host = NSHostingView(rootView: SessionComparisonReader(session: secondSession, mode: 2).defaultAppStorage(defaults))
            host.frame = NSRect(x: 0, y: 0, width: 800, height: 600); host.layoutSubtreeIfNeeded()
            // A queue barrier lets the real SwiftUI/representable work already
            // scheduled above finish; no polling or manual run loop is used.
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                DispatchQueue.main.async { continuation.resume() }
            }
            host.layoutSubtreeIfNeeded()
            func findPDFView(_ view: NSView) -> PDFView? {
                if let pdf = view as? PDFView { return pdf }
                return view.subviews.lazy.compactMap(findPDFView).first
            }
            guard let reference = findPDFView(host), let color = reference.backgroundColor.usingColorSpace(.sRGB) else {
                throw NSError(domain: "PDF.SessionAudit", code: 15, userInfo: [NSLocalizedDescriptionKey: "O leitor real de referência não foi montado para verificar as preferências."])
            }
            try require(reference.document === secondSession.document && reference.displayMode == .twoUpContinuous &&
                        reference.displayDirection == .horizontal && reference.displayBox == .mediaBox && !reference.displaysPageBreaks,
                        "O leitor de referência ignorou modo, direção, caixa de página ou separação configurados.")
            try require(!reference.autoScales && abs(Double(reference.scaleFactor) - 2.1) < 0.01 &&
                        abs(color.redComponent - 32.0 / 255) < 0.001 && abs(color.greenComponent - 64.0 / 255) < 0.001 &&
                        abs(color.blueComponent - 96.0 / 255) < 0.001,
                        "O leitor de referência perdeu o zoom próprio ou o fundo personalizado.")
        }
        try workspace.checkpointRecoveryNow()
        let records = try store.list()
        try require(records.count == 2, "A recuperação não preservou as duas sessões.")
        guard let firstRecord = records.first(where: { $0.id == firstSession.id }), let recovered = PDFDocument(data: try store.load(firstRecord)) else { throw NSError(domain: "PDF.SessionAudit", code: 7) }
        try require(recovered.page(at: 0)?.annotations.first { $0.fieldName == "session-field" }?.widgetStringValue == "Alterado na primeira aba", "A recuperação perdeu valores preenchidos no formulário.")
        let restoredWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try restoredWorkspace.refreshRecoveryNow(); restoredWorkspace.restoreRecovery(id: firstSession.id)
        await restoredWorkspace.waitForPendingOpen()
        try require(restoredWorkspace.currentPage == 2 && restoredWorkspace.activeSession?.isDirty == true && restoredWorkspace.bookmarks == [2], "A restauração não recuperou o estado de leitura e a proteção contra descarte.")
        try require(abs((restoredWorkspace.activeSession?.zoom ?? 0) - 1.75) < 0.01 && restoredWorkspace.activeSession?.autoScale == false,
                    "Restaurar a sessão aplicou as preferências atuais no lugar do zoom e ajuste automático recuperados.")
        try require(try Data(contentsOf: firstURL) == firstBytes, "Sessões/recuperação alteraram o documento original.")
        let generationsBeforeNavigation = try FileManager.default.contentsOfDirectory(atPath: store.directory.path).sorted()
        workspace.currentPage = 1; workspace.bookmarks = []; view.scaleFactor = 2.75
        try workspace.checkpointRecoveryNow()
        let generationsAfterNavigation = try FileManager.default.contentsOfDirectory(atPath: store.directory.path).sorted()
        try require(generationsAfterNavigation == generationsBeforeNavigation, "Navegar sem editar serializou novas gerações dos PDFs.")
        let navigationWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try navigationWorkspace.refreshRecoveryNow(); navigationWorkspace.restoreRecovery(id: firstSession.id)
        await navigationWorkspace.waitForPendingOpen()
        try require(navigationWorkspace.currentPage == 1 && navigationWorkspace.bookmarks.isEmpty && abs((navigationWorkspace.activeSession?.zoom ?? 0) - 2.75) < 0.01,
                    "Uma nova sessão não recuperou o sidecar de página, zoom e marcadores.")
        let staleTaskID = firstSession.beginRecoveryTask()
        firstSession.recoveryTask = Task { }
        firstSession.cancelRecoveryTask()
        let replacementTaskID = firstSession.beginRecoveryTask()
        firstSession.recoveryTask = Task { }
        firstSession.recoveryWrite = Task<RecoveryRecord?, Error> { firstRecord }
        // Reproduce the old task's deferred cleanup arriving after a new task
        // was installed: it must not erase the new cancellation handles.
        firstSession.finishRecoveryTask(staleTaskID)
        try require(firstSession.recoveryTaskID == replacementTaskID && firstSession.recoveryTask != nil && firstSession.recoveryWrite != nil,
                    "A conclusão de uma tarefa cancelada apagou a tarefa de recuperação mais recente.")
        firstSession.finishRecoveryTask(replacementTaskID)
        try require(firstSession.recoveryTaskID == nil && firstSession.recoveryTask == nil && firstSession.recoveryWrite == nil,
                    "Concluir a tarefa atual não limpou seus próprios identificadores.")

        // Inspect our explicit ownership boundary; PDFKit may retain its own
        // internal caches, so the test never relies on framework deinit timing.
        let searchWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        searchWorkspace.open(url: firstURL); await searchWorkspace.waitForPendingOpen()
        guard let searchedSession = searchWorkspace.activeSession else { throw NSError(domain: "PDF.SessionAudit", code: 14) }
        searchWorkspace.search("Primeiro", animate: false)
        try require(searchWorkspace.hasSearchResources, "A busca não criou o estado real exigido pelo cenário de liberação.")
        searchWorkspace.cancelSearch()
        try require(!searchWorkspace.hasSearchResources && !searchWorkspace.searching,
                    "Cancelar a busca manteve referências ao PDF, resultados ou observadores.")
        searchWorkspace.search("documento", animate: false)
        try require(searchWorkspace.hasSearchResources, "A segunda busca não restaurou o estado real do leitor.")
        searchWorkspace.closeSession(searchedSession.id, discardChanges: true)
        try require(searchWorkspace.sessions.isEmpty && searchWorkspace.document == nil && !searchWorkspace.hasSearchResources &&
                    !searchWorkspace.searching && !searchWorkspace.hasUnsavedChanges,
                    "Fechar a última aba reteve recursos de busca ou deixou um estado de formulário modificado sem documento.")
        let statusWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        statusWorkspace.open(url: secondURL); await statusWorkspace.waitForPendingOpen()
        guard let statusSession = statusWorkspace.activeSession else { throw NSError(domain: "PDF.SessionAudit", code: 20) }
        statusWorkspace.closeSession(statusSession.id, discardChanges: true)
        try require(statusWorkspace.message.isEmpty, "Fechar a última aba manteve uma identidade de documento inexistente no rodapé.")

        // These spellings have equal UTF-8 lengths and compare equal as Swift
        // Strings, but changing their codepoint order is still a real edit.
        do {
            let beforeValue = "e\u{0301}\u{0327}", afterValue = "e\u{0327}\u{0301}"
            try require(beforeValue == afterValue && beforeValue.utf8.count == afterValue.utf8.count &&
                        !beforeValue.utf8.elementsEqual(afterValue.utf8), "A amostra de marcas combinantes não exerce igualdade canônica com bytes distintos de mesmo tamanho.")
            guard let source = PDFDocument(data: firstBytes), let field = source.page(at: 0)?.annotations.first(where: { $0.fieldName == "session-field" }) else {
                throw NSError(domain: "PDF.SessionAudit", code: 16)
            }
            field.widgetStringValue = beforeValue
            let sourceURL = directory.appendingPathComponent("combining-mark-order.pdf")
            try NativeOutput.write(NativePDFSerialization.serialize(document: source), to: sourceURL)
            let unicodeState = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
            unicodeState.open(url: sourceURL); await unicodeState.waitForPendingOpen()
            guard let session = unicodeState.activeSession, let restoredField = session.document.page(at: 0)?.annotations.first(where: { $0.fieldName == "session-field" }) else {
                throw NSError(domain: "PDF.SessionAudit", code: 17)
            }
            try require((restoredField.widgetStringValue ?? "").utf8.elementsEqual(beforeValue.utf8) && !unicodeState.hasUnsavedChanges,
                        "A amostra inicial não preservou a ordem original das marcas combinantes ou começou suja.")
            try unicodeState.checkpointRecoveryNow()
            guard let previous = session.recoveryRecord else { throw NSError(domain: "PDF.SessionAudit", code: 18) }
            let previousBytes = try store.load(previous)
            let previousState = PDFDocumentSession.widgetState(session.document)
            restoredField.widgetStringValue = afterValue
            try require((restoredField.widgetStringValue ?? "").utf8.elementsEqual(afterValue.utf8) &&
                        previousState != PDFDocumentSession.widgetState(session.document) && session.refreshDirty() && unicodeState.hasUnsavedChanges,
                        "A mudança de bytes canonicamente equivalentes não alterou a impressão do formulário nem marcou a sessão como modificada.")
            try unicodeState.checkpointRecoveryNow()
            guard let replacement = session.recoveryRecord else { throw NSError(domain: "PDF.SessionAudit", code: 19) }
            let replacementBytes = try store.load(replacement)
            guard let saved = PDFDocument(data: replacementBytes) else { throw NSError(domain: "PDF.SessionAudit", code: 19) }
            let value = saved.page(at: 0)?.annotations.first(where: { $0.fieldName == "session-field" })?.widgetStringValue ?? ""
            try require(replacementBytes != previousBytes && value.utf8.elementsEqual(afterValue.utf8),
                        "A recuperação reutilizou a geração anterior ou perdeu os bytes da edição Unicode de mesmo tamanho.")
        }

        // The original password stays in memory; recovered bytes must require it again.
        let password = "native-session-recovery-123"
        let encryptedData = try NativePDFSerialization.serialize(document: first, password: password)
        let encrypted = try NativePDFSerialization.open(data: encryptedData, password: password)
        let protectedSession = PDFDocumentSession(document: encrypted, sourceURL: nil, password: password)
        let safeBytes = try protectedSession.recoveryData()
        let verification = PDFDocument(data: safeBytes)
        try require(verification?.isEncrypted == true && verification?.isLocked == true && verification?.unlock(withPassword: "") == false,
                    "A recuperação de documento protegido ficou legível sem senha.")
        try QPDFStructuralAudit.verifyAES256(safeBytes, password: password)
        protectedSession.password = nil
        try require(rejects { _ = try protectedSession.recoveryData() }, "A recuperação caiu silenciosamente para texto sem proteção quando não havia senha.")

        // Cancelling a protected recovery must not redirect the next file's
        // password to the previously requested recovery document.
        let protectedID = UUID()
        try store.save(documentData: safeBytes, sourceURL: nil, sessionID: protectedID, encrypted: true,
                       title: "Recuperação protegida", state: RecoverySessionState())
        let passwordWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try passwordWorkspace.refreshRecoveryNow(); passwordWorkspace.restoreRecovery(id: protectedID)
        await passwordWorkspace.waitForPendingOpen()
        try require(passwordWorkspace.needsPassword, "A recuperação protegida não solicitou a senha.")
        passwordWorkspace.documentPassword = "senha a descartar"; passwordWorkspace.cancelPendingUnlock()
        try require(!passwordWorkspace.needsPassword && passwordWorkspace.documentPassword.isEmpty, "Cancelar não limpou a solicitação e a senha pendentes.")
        // Repeat the pending state to check replacement even if the alert is
        // dismissed by the system instead of its explicit Cancel button.
        passwordWorkspace.restoreRecovery(id: protectedID)
        await passwordWorkspace.waitForPendingOpen()
        let otherPassword = "different-source-password-456"
        let otherURL = directory.appendingPathComponent("other-protected.pdf")
        let otherData = try NativePDFSerialization.serialize(document: first, password: otherPassword)
        try NativeOutput.write(otherData, to: otherURL)
        passwordWorkspace.open(url: otherURL)
        await passwordWorkspace.waitForPendingOpen()
        passwordWorkspace.documentPassword = otherPassword; passwordWorkspace.unlockPendingDocument()
        await passwordWorkspace.waitForPendingOpen()
        try require(passwordWorkspace.url == otherURL && passwordWorkspace.document?.isLocked == false && !passwordWorkspace.needsPassword,
                    "A senha do novo arquivo foi encaminhada a uma recuperação anteriormente solicitada.")
        let savedPassword = "published-copy-password-789"
        guard let sourceToSave = passwordWorkspace.document else { throw NSError(domain: "PDF.SessionAudit", code: 11) }
        let saveBytes = try NativePDFSerialization.serialize(document: sourceToSave, password: savedPassword)
        passwordWorkspace.didEdit()
        try require(rejects { try passwordWorkspace.publishSavedCopy(saveBytes, to: otherURL, password: savedPassword) }, "Salvar uma cópia sobrescreveu a origem protegida.")
        try require(passwordWorkspace.activeSession?.password == otherPassword && passwordWorkspace.savedDocumentURL == nil && passwordWorkspace.hasUnsavedChanges,
                    "Uma publicação recusada alterou a senha de recuperação ou marcou alterações como salvas.")
        try require(try Data(contentsOf: otherURL) == otherData, "A tentativa de publicação alterou os bytes originais protegidos.")
        let savedURL = directory.appendingPathComponent("saved-protected-copy.pdf")
        try passwordWorkspace.publishSavedCopy(saveBytes, to: savedURL, password: savedPassword)
        try require(passwordWorkspace.activeSession?.password == savedPassword && passwordWorkspace.savedDocumentURL == savedURL && !passwordWorkspace.hasUnsavedChanges,
                    "A publicação bem-sucedida não atualizou senha e estado da sessão.")
        let savedData = try Data(contentsOf: savedURL)
        let savedVerification = try NativePDFSerialization.open(data: savedData, password: savedPassword)
        try require(PDFDocument(data: savedData)?.isLocked == true && savedVerification.isEncrypted && !savedVerification.isLocked,
                    "A cópia publicada não manteve a nova senha.")
        try require(try Data(contentsOf: otherURL) == otherData, "Salvar a cópia protegida alterou a origem.")

        // Exercise the actual asynchronous reader and recovery paths with a
        // full-length UTF-8 credential, without a window or fake unlock result.
        let unicodePassword = String(repeating: "🔑", count: 31) + "abc"
        let unicodeData = try NativePDFSerialization.serialize(document: first, password: unicodePassword)
        try QPDFStructuralAudit.verifyAES256(unicodeData, password: unicodePassword)
        let unicodeURL = directory.appendingPathComponent("unicode-protected.pdf")
        try NativeOutput.write(unicodeData, to: unicodeURL)
        let unicodeWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        unicodeWorkspace.open(url: unicodeURL)
        await unicodeWorkspace.waitForPendingOpen()
        try require(unicodeWorkspace.needsPassword && unicodeWorkspace.document == nil,
                    "O leitor abriu um arquivo Unicode protegido sem solicitar autenticação.")
        unicodeWorkspace.documentPassword = "incorrect-unicode-audit"; unicodeWorkspace.unlockPendingDocument()
        await unicodeWorkspace.waitForPendingOpen()
        try require(unicodeWorkspace.needsPassword && unicodeWorkspace.document == nil,
                    "Uma senha incorreta instalou o documento protegido no leitor.")
        unicodeWorkspace.documentPassword = unicodePassword; unicodeWorkspace.unlockPendingDocument()
        await unicodeWorkspace.waitForPendingOpen()
        guard let unicodeSession = unicodeWorkspace.activeSession else { throw NSError(domain: "PDF.SessionAudit", code: 12) }
        try require(unicodeSession.document.isEncrypted && !unicodeSession.document.isLocked &&
                    unicodeSession.document.pageCount == 2 && (unicodeSession.document.string ?? "").contains("Primeiro documento"),
                    "O leitor Unicode não manteve proteção, páginas e conteúdo após autenticar.")
        try unicodeWorkspace.checkpointRecoveryNow()
        guard let unicodeRecord = try store.list().first(where: { $0.id == unicodeSession.id }) else {
            throw NSError(domain: "PDF.SessionAudit", code: 13)
        }
        let unicodeSnapshot = try store.load(unicodeRecord)
        try QPDFStructuralAudit.verifyAES256(unicodeSnapshot, password: unicodePassword)
        let unicodeRecovery = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try unicodeRecovery.refreshRecoveryNow(); unicodeRecovery.restoreRecovery(id: unicodeRecord.id)
        await unicodeRecovery.waitForPendingOpen()
        try require(unicodeRecovery.needsPassword && unicodeRecovery.document == nil,
                    "A recuperação Unicode não exigiu autenticação novamente.")
        unicodeRecovery.documentPassword = unicodePassword; unicodeRecovery.unlockPendingDocument()
        await unicodeRecovery.waitForPendingOpen()
        try require(unicodeRecovery.document?.isEncrypted == true && unicodeRecovery.document?.isLocked == false &&
                    unicodeRecovery.document?.pageCount == 2 && unicodeRecovery.document?.page(at: 0)?.annotations.contains {
                        $0.fieldName == "session-field" && $0.widgetStringValue == "Original"
                    } == true, "A recuperação Unicode perdeu proteção, páginas ou campo editável.")
        try require(try store.load(unicodeRecord) == unicodeSnapshot && Data(contentsOf: unicodeURL) == unicodeData,
                    "Abrir ou restaurar o PDF Unicode alterou os bytes originais ou o snapshot persistido.")

        // Two selections made before the first worker completes must retain
        // their distinct password prompts. Cancel the first, then authenticate
        // the second with its own credential and original URL.
        let queuedWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        queuedWorkspace.open(url: otherURL); queuedWorkspace.open(url: unicodeURL)
        await queuedWorkspace.waitForPendingOpen()
        try require(queuedWorkspace.needsPassword && queuedWorkspace.sessions.isEmpty,
                    "A fila de documentos protegidos instalou uma sessão antes da autenticação.")
        queuedWorkspace.cancelPendingUnlock()
        await queuedWorkspace.waitForPendingOpen()
        try require(queuedWorkspace.needsPassword, "Cancelar a primeira senha descartou o segundo arquivo da fila.")
        queuedWorkspace.documentPassword = unicodePassword; queuedWorkspace.unlockPendingDocument()
        await queuedWorkspace.waitForPendingOpen()
        try require(queuedWorkspace.sessions.count == 1 && queuedWorkspace.url == unicodeURL &&
                    queuedWorkspace.activeSession?.password == unicodePassword && queuedWorkspace.document?.isLocked == false,
                    "A fila encaminhou a senha ao arquivo errado ou persistiu a credencial temporária de compatibilidade.")

        // Cancel while a worker is outstanding, then immediately open another
        // source. Await both current and retired work; stale completion must
        // not install a document or overwrite the second source's prompt.
        let cancelledWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        cancelledWorkspace.open(url: otherURL); cancelledWorkspace.cancelDocumentOpenings()
        cancelledWorkspace.open(url: unicodeURL)
        await cancelledWorkspace.waitForPendingOpen()
        try require(cancelledWorkspace.needsPassword && cancelledWorkspace.sessions.isEmpty,
                    "A conclusão de uma abertura cancelada instalou uma sessão obsoleta.")
        cancelledWorkspace.documentPassword = unicodePassword; cancelledWorkspace.unlockPendingDocument()
        await cancelledWorkspace.waitForPendingOpen()
        try require(cancelledWorkspace.sessions.count == 1 && cancelledWorkspace.url == unicodeURL &&
                    cancelledWorkspace.activeSession?.password == unicodePassword,
                    "A tarefa cancelada substituiu o documento ou a senha da abertura seguinte.")
        try require(try Data(contentsOf: unicodeURL) == unicodeData && Data(contentsOf: otherURL) == otherData,
                    "Enfileirar ou cancelar aberturas modificou um dos documentos protegidos originais.")

        // Real PDFKit annotation changes, independent per-document undo and persisted redo.
        let page = firstSession.document.page(at: 0)!
        let annotation = PDFAnnotation(bounds: CGRect(x: 80, y: 300, width: 100, height: 50), forType: .freeText, withProperties: nil)
        annotation.contents = "Original"; page.addAnnotation(annotation)
        firstSession.history.inserted(annotation, on: page, name: "Inserir texto")
        try require(firstSession.history.undoManager.groupingLevel == 0 && firstSession.history.undoManager.undoActionName == "Inserir texto", "Inserir não encerrou o próprio grupo com o título correto.")
        firstSession.history.undoManager.undo()
        try require(!page.annotations.contains(where: { $0 === annotation }), "Desfazer não removeu a anotação criada.")
        try require(firstSession.history.undoManager.redoActionName == "Inserir texto", "Desfazer inserção perdeu o título da ação inversa.")
        firstSession.history.undoManager.redo()
        try require(page.annotations.contains(where: { $0 === annotation }), "Refazer não restaurou a anotação criada.")
        try require(firstSession.history.undoManager.groupingLevel == 0 && firstSession.history.undoManager.undoActionName == "Inserir texto", "Refazer inserção deixou grupo aberto ou perdeu o título.")
        let before = PDFAnnotationState(annotation)
        EditableAnnotations.resize(annotation, to: CGRect(x: 100, y: 320, width: 140, height: 70))
        annotation.contents = "Editado"; annotation.color = .systemRed
        let border = PDFBorder(); border.lineWidth = 6; annotation.border = border
        firstSession.history.changed(annotation, before: before)
        try require(firstSession.history.undoManager.groupingLevel == 0 && firstSession.history.undoManager.undoActionName == "Editar anotação", "Editar não encerrou o próprio grupo com o título correto.")
        firstSession.history.undoManager.undo()
        try require(annotation.bounds == before.bounds && annotation.contents == "Original", "Desfazer não restaurou geometria e conteúdo.")
        try require(firstSession.history.undoManager.redoActionName == "Editar anotação", "Restaurar propriedades perdeu o título de refazer.")
        firstSession.history.undoManager.redo()
        try require(annotation.contents == "Editado" && annotation.bounds.width == 140 && annotation.border?.lineWidth == 6, "Refazer perdeu propriedades editadas.")
        try require(firstSession.history.undoManager.groupingLevel == 0 && firstSession.history.undoManager.undoActionName == "Editar anotação", "Refazer edição deixou grupo aberto ou perdeu o título.")
        try require(!secondSession.history.undoManager.canUndo, "Uma edição de outra aba contaminou o histórico do documento de referência.")
        firstSession.history.remove(annotation, from: page)
        try require(firstSession.history.undoManager.groupingLevel == 0 && firstSession.history.undoManager.undoActionName == "Excluir anotação", "Excluir não encerrou o próprio grupo com o título correto.")
        firstSession.history.undoManager.undo()
        try require(page.annotations.contains(where: { $0 === annotation }), "Desfazer exclusão não restaurou a anotação.")
        try require(firstSession.history.undoManager.redoActionName == "Excluir anotação", "Desfazer exclusão perdeu o título de refazer.")
        firstSession.history.undoManager.redo()
        try require(!page.annotations.contains(where: { $0 === annotation }) && firstSession.history.undoManager.undoActionName == "Excluir anotação", "Refazer exclusão não preservou conteúdo e título.")
        firstSession.history.undoManager.undo()
        try require(page.annotations.contains(where: { $0 === annotation }) && firstSession.history.undoManager.groupingLevel == 0, "Restaurar a exclusão refeita perdeu a anotação ou deixou um grupo aberto.")

        // Exercise an explicitly grouped selection without a window or a run-loop event.
        // The inner registrations must leave the caller's group open and undo both marks together.
        let groupedPage = PDFPage()
        let groupedHistory = AnnotationHistory()
        var groupedChanges = 0
        groupedHistory.onChange = { groupedChanges += 1 }
        let marks = [CGFloat(220), CGFloat(260)].map { y in
            PDFAnnotation(bounds: CGRect(x: 50, y: y, width: 100, height: 20), forType: .highlight, withProperties: nil)
        }
        groupedHistory.undoManager.beginUndoGrouping()
        for mark in marks {
            groupedPage.addAnnotation(mark)
            groupedHistory.inserted(mark, on: groupedPage, name: "Realçar seleção")
            try require(groupedHistory.undoManager.groupingLevel == 1, "Uma inserção encerrou o grupo externo da seleção.")
        }
        groupedHistory.undoManager.endUndoGrouping()
        try require(groupedChanges == 2 && groupedHistory.undoManager.undoActionName == "Realçar seleção", "O grupo de realces não concluiu as notificações ou perdeu o título.")
        groupedHistory.undoManager.undo()
        try require(groupedPage.annotations.isEmpty && !groupedHistory.undoManager.canUndo && groupedHistory.undoManager.redoActionName == "Realçar seleção", "Desfazer a seleção não removeu os dois realces em uma única ação nomeada.")
        groupedHistory.undoManager.redo()
        try require(marks.allSatisfy { mark in groupedPage.annotations.contains { $0 === mark } } && groupedPage.annotations.count == 2, "Refazer a seleção não restaurou exatamente os dois realces.")
        try require(groupedChanges == 6 && groupedHistory.undoManager.groupingLevel == 0 && groupedHistory.undoManager.undoActionName == "Realçar seleção", "Refazer a seleção perdeu notificações, título ou equilíbrio dos grupos.")
        try require(!EditableAnnotations.accepts(widget), "O editor genérico permitiu transformar campos de formulário como anotações gráficas.")
        try require(rejects { try EditableAnnotations.validate(CGRect(x: -20, y: 0, width: 10, height: 10), on: page) }, "O editor aceitou uma anotação fora da página.")
        try auditQuadrilateralPersistence()
        guard let final = firstSession.document.dataRepresentation(), let finalPage = PDFDocument(data: final)?.page(at: 0) else { throw NSError(domain: "PDF.SessionAudit", code: 9) }
        try require(finalPage.annotations.contains { PDFAnnotationKind.matches($0, .freeText) && $0.contents == "Editado" && $0.bounds.width == 140 }, "Salvar/reabrir perdeu as alterações refeitas.")
        workspace.closeSession(secondSession.id, discardChanges: true)
        try require(workspace.sessions.count == 1 && workspace.comparisonSessionID == nil && !(try store.list()).contains(where: { $0.id == secondSession.id }), "Fechar uma aba deixou recuperação ou referência abandonada.")
        print("Session audit: independent tabs/page/zoom/forms, safe recovery, encrypted snapshots, named annotation groups/edit/undo/redo/persistence passed")
    }

    /// Check the PDF dictionaries actually written, not just PDFKit's cached
    /// NSValue arrays. The former regression never attached its markup to a page.
    private static func auditQuadrilateralPersistence() throws {
        func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
            guard condition() else { throw NSError(domain: "PDF.QuadPointsAudit", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func phase(_ text: String) { FileHandle.standardOutput.write(Data(("QuadPoints audit: " + text + "\n").utf8)) }
        guard let document = PDFDocument(data: try IntelligenceText.PDF("Annotation geometry persistence")), let page = document.page(at: 0) else {
            throw NSError(domain: "PDF.QuadPointsAudit", code: 2)
        }
        phase("non-markup properties")
        let note = PDFAnnotation(bounds: CGRect(x: 50, y: 500, width: 100, height: 40), forType: .freeText, withProperties: nil)
        note.contents = "Keep text geometry"
        let noteBefore = PDFAnnotationState(note)
        try require(noteBefore.quadrilaterals == nil, "FreeText foi tratado como anotação com quadriláteros.")
        EditableAnnotations.resize(note, to: CGRect(x: 60, y: 510, width: 150, height: 60))
        noteBefore.apply(to: note); page.addAnnotation(note)
        let line = PDFAnnotation(bounds: CGRect(x: 50, y: 400, width: 100, height: 100), forType: .line, withProperties: nil)
        line.startPoint = NSPoint(x: 10, y: 20); line.endPoint = NSPoint(x: 80, y: 90)
        let lineBefore = PDFAnnotationState(line)
        try require(lineBefore.quadrilaterals == nil, "Line foi tratada como anotação com quadriláteros.")
        EditableAnnotations.resize(line, to: CGRect(x: 60, y: 400, width: 200, height: 50))
        try require(line.startPoint == NSPoint(x: 20, y: 10) && line.endPoint == NSPoint(x: 160, y: 45), "O redimensionamento não transformou os extremos da linha.")
        page.addAnnotation(line)
        let subtypes: [PDFAnnotationSubtype] = [.highlight, .underline, .strikeOut]
        var expected: [String: [CGFloat]] = [:]
        for (index, subtype) in subtypes.enumerated() {
            phase("markup " + subtype.rawValue)
            let y = CGFloat(100 + index * 70)
            let markup = PDFAnnotation(bounds: CGRect(x: 50, y: y, width: 100, height: 20), forType: subtype, withProperties: nil)
            markup.quadrilateralPoints = [NSPoint(x: 0, y: 20), NSPoint(x: 100, y: 20), .zero, NSPoint(x: 100, y: 0)].map(NSValue.init(point:))
            page.addAnnotation(markup)
            let before = PDFAnnotationState(markup)
            EditableAnnotations.resize(markup, to: CGRect(x: 70, y: y + 20, width: 200, height: 40))
            try require(markup.quadrilateralPoints?[1].pointValue == NSPoint(x: 200, y: 40), "O redimensionamento não manteve coordenadas relativas da marcação.")
            let after = PDFAnnotationState(markup)
            before.apply(to: markup)
            try require(markup.bounds == before.bounds && markup.quadrilateralPoints?[1].pointValue == NSPoint(x: 100, y: 20), "Restaurar a marcação não recuperou geometria e quadrilátero.")
            after.apply(to: markup)
            let type = PDFAnnotationKind.normalizedName(subtype.rawValue)!
            expected[type] = [70, y + 60, 270, y + 60, 70, y + 20, 270, y + 20]
        }
        phase("serialize and inspect PDF dictionaries")
        guard let bytes = document.dataRepresentation(), let provider = CGDataProvider(data: bytes as CFData),
              let serialized = CGPDFDocument(provider), let serializedPage = serialized.page(at: 1), let pageDictionary = serializedPage.dictionary else {
            throw NSError(domain: "PDF.QuadPointsAudit", code: 3)
        }
        var annotations: CGPDFArrayRef?
        try require(CGPDFDictionaryGetArray(pageDictionary, "Annots", &annotations), "O PDF salvo não contém as anotações de geometria.")
        guard let annotations else { throw NSError(domain: "PDF.QuadPointsAudit", code: 4) }
        try require(CGPDFArrayGetCount(annotations) == 5, "Salvar perdeu ou duplicou anotações.")
        var seen = Set<String>()
        for index in 0..<CGPDFArrayGetCount(annotations) {
            var entry: CGPDFDictionaryRef?
            try require(CGPDFArrayGetDictionary(annotations, index, &entry), "Uma anotação não é um dicionário PDF.")
            guard let entry else { throw NSError(domain: "PDF.QuadPointsAudit", code: 5) }
            var subtype: UnsafePointer<CChar>?
            try require(CGPDFDictionaryGetName(entry, "Subtype", &subtype), "A anotação perdeu seu subtipo.")
            guard let subtype else { throw NSError(domain: "PDF.QuadPointsAudit", code: 6) }
            let name = String(cString: subtype)
            if let coordinates = expected[name] {
                var array: CGPDFArrayRef?
                try require(CGPDFDictionaryGetArray(entry, "QuadPoints", &array), "A marcação \(name) perdeu QuadPoints na serialização.")
                guard let array else { throw NSError(domain: "PDF.QuadPointsAudit", code: 7) }
                try require(CGPDFArrayGetCount(array) == 8, "QuadPoints precisa de oito números por quadrilátero.")
                for coordinate in 0..<8 {
                    var value: CGPDFReal = 0
                    try require(CGPDFArrayGetNumber(array, coordinate, &value), "QuadPoints contém um valor que não é numérico.")
                    try require(value.isFinite && abs(CGFloat(value) - coordinates[coordinate]) < 0.01, "QuadPoints não preservou a geometria em coordenadas da página.")
                }
                seen.insert(name)
            } else {
                var unexpected: CGPDFObjectRef?
                try require(!CGPDFDictionaryGetObject(entry, "QuadPoints", &unexpected), "A edição escreveu QuadPoints em \(name), que não é marcação de texto.")
            }
        }
        try require(seen.count == 3, "Nem todos os subtipos de marcação foram conferidos.")
        guard let reopenedDocument = PDFDocument(data: bytes), let reopened = reopenedDocument.page(at: 0) else { throw NSError(domain: "PDF.QuadPointsAudit", code: 8) }
        for subtype in subtypes {
            guard let markup = reopened.annotations.first(where: { PDFAnnotationKind.matches($0, subtype) }) else { throw NSError(domain: "PDF.QuadPointsAudit", code: 9) }
            try require(markup.quadrilateralPoints?.count == 4 && markup.quadrilateralPoints?[1].pointValue == NSPoint(x: 200, y: 40), "Reabrir perdeu os pontos relativos da marcação.")
        }
        phase("numeric serialization and reopened geometry verified")
    }

}
