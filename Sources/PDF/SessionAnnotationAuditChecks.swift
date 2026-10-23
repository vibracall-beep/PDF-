import AppKit
import PDFKit

@MainActor enum SessionAnnotationAuditChecks {
    static func run() throws {
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
        guard let firstSession = workspace.activeSession, let openedPage = workspace.document?.page(at: 0) else { throw NSError(domain: "PDF.SessionAudit", code: 5) }
        let view = PDFView(frame: CGRect(x: 0, y: 0, width: 800, height: 600)); view.document = workspace.document
        workspace.pdfView = view; view.autoScales = false; view.scaleFactor = 1.75
        workspace.currentPage = 2; workspace.bookmarks = [2]
        openedPage.annotations.first { $0.fieldName == "session-field" }?.widgetStringValue = "Alterado na primeira aba"
        workspace.open(url: secondURL)
        guard let secondSession = workspace.activeSession else { throw NSError(domain: "PDF.SessionAudit", code: 6) }
        try require(workspace.sessions.count == 2 && firstSession.isDirty && !secondSession.isDirty, "Abrir outra aba perdeu o documento ou alterações de formulário.")
        try require(firstSession.page == 2 && abs(firstSession.zoom - 1.75) < 0.01 && firstSession.bookmarks == [2], "A primeira aba perdeu página, zoom ou marcas.")
        workspace.activateSession(firstSession.id)
        try require(workspace.document === firstSession.document && workspace.currentPage == 2 && workspace.hasUnsavedChanges, "Selecionar a aba não restaurou documento e alterações.")
        workspace.comparisonSessionID = secondSession.id
        secondSession.page = 1; secondSession.zoom = 2.1; secondSession.autoScale = false
        try require(workspace.currentPage == 2 && firstSession.zoom != secondSession.zoom, "O documento de referência alterou a navegação principal.")
        try workspace.checkpointRecoveryNow()
        let records = try store.list()
        try require(records.count == 2, "A recuperação não preservou as duas sessões.")
        guard let firstRecord = records.first(where: { $0.id == firstSession.id }), let recovered = PDFDocument(data: try store.load(firstRecord)) else { throw NSError(domain: "PDF.SessionAudit", code: 7) }
        try require(recovered.page(at: 0)?.annotations.first { $0.fieldName == "session-field" }?.widgetStringValue == "Alterado na primeira aba", "A recuperação perdeu valores preenchidos no formulário.")
        let restoredWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try restoredWorkspace.refreshRecoveryNow(); restoredWorkspace.restoreRecovery(id: firstSession.id)
        try require(restoredWorkspace.currentPage == 2 && restoredWorkspace.activeSession?.isDirty == true && restoredWorkspace.bookmarks == [2], "A restauração não recuperou o estado de leitura e a proteção contra descarte.")
        try require(try Data(contentsOf: firstURL) == firstBytes, "Sessões/recuperação alteraram o documento original.")
        let generationsBeforeNavigation = try FileManager.default.contentsOfDirectory(atPath: store.directory.path).sorted()
        workspace.currentPage = 1; workspace.bookmarks = []; view.scaleFactor = 2.75
        try workspace.checkpointRecoveryNow()
        let generationsAfterNavigation = try FileManager.default.contentsOfDirectory(atPath: store.directory.path).sorted()
        try require(generationsAfterNavigation == generationsBeforeNavigation, "Navegar sem editar serializou novas gerações dos PDFs.")
        let navigationWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try navigationWorkspace.refreshRecoveryNow(); navigationWorkspace.restoreRecovery(id: firstSession.id)
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

        // The original password stays in memory; recovered bytes must require it again.
        let password = "native-session-recovery-123"
        guard let encryptedData = first.dataRepresentation(options: [AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): password,
              AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): password]), let encrypted = PDFDocument(data: encryptedData),
              encrypted.unlock(withPassword: password) else { throw NSError(domain: "PDF.SessionAudit", code: 8) }
        let protectedSession = PDFDocumentSession(document: encrypted, sourceURL: nil, password: password)
        let safeBytes = try protectedSession.recoveryData()
        let verification = PDFDocument(data: safeBytes)
        try require(verification?.isEncrypted == true && verification?.isLocked == true && verification?.unlock(withPassword: "") == false,
                    "A recuperação de documento protegido ficou legível sem senha.")
        protectedSession.password = nil
        try require(rejects { _ = try protectedSession.recoveryData() }, "A recuperação caiu silenciosamente para texto sem proteção quando não havia senha.")

        // Cancelling a protected recovery must not redirect the next file's
        // password to the previously requested recovery document.
        let protectedID = UUID()
        try store.save(documentData: safeBytes, sourceURL: nil, sessionID: protectedID, encrypted: true,
                       title: "Recuperação protegida", state: RecoverySessionState())
        let passwordWorkspace = Workspace(defaults: defaults, recoveryStore: store, enableRecoveryPolling: false)
        try passwordWorkspace.refreshRecoveryNow(); passwordWorkspace.restoreRecovery(id: protectedID)
        try require(passwordWorkspace.needsPassword, "A recuperação protegida não solicitou a senha.")
        passwordWorkspace.documentPassword = "senha a descartar"; passwordWorkspace.cancelPendingUnlock()
        try require(!passwordWorkspace.needsPassword && passwordWorkspace.documentPassword.isEmpty, "Cancelar não limpou a solicitação e a senha pendentes.")
        // Repeat the pending state to check replacement even if the alert is
        // dismissed by the system instead of its explicit Cancel button.
        passwordWorkspace.restoreRecovery(id: protectedID)
        let otherPassword = "different-source-password-456"
        let otherURL = directory.appendingPathComponent("other-protected.pdf")
        guard let otherData = first.dataRepresentation(options: [AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): otherPassword,
              AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): otherPassword]) else { throw NSError(domain: "PDF.SessionAudit", code: 10) }
        try NativeOutput.write(otherData, to: otherURL)
        passwordWorkspace.open(url: otherURL); passwordWorkspace.documentPassword = otherPassword; passwordWorkspace.unlockPendingDocument()
        try require(passwordWorkspace.url == otherURL && passwordWorkspace.document?.isLocked == false && !passwordWorkspace.needsPassword,
                    "A senha do novo arquivo foi encaminhada a uma recuperação anteriormente solicitada.")
        let savedPassword = "published-copy-password-789"
        guard let saveBytes = passwordWorkspace.document?.dataRepresentation(options: [AnyHashable(PDFDocumentWriteOption.userPasswordOption.rawValue): savedPassword,
              AnyHashable(PDFDocumentWriteOption.ownerPasswordOption.rawValue): savedPassword]) else { throw NSError(domain: "PDF.SessionAudit", code: 11) }
        passwordWorkspace.didEdit()
        try require(rejects { try passwordWorkspace.publishSavedCopy(saveBytes, to: otherURL, password: savedPassword) }, "Salvar uma cópia sobrescreveu a origem protegida.")
        try require(passwordWorkspace.activeSession?.password == otherPassword && passwordWorkspace.savedDocumentURL == nil && passwordWorkspace.hasUnsavedChanges,
                    "Uma publicação recusada alterou a senha de recuperação ou marcou alterações como salvas.")
        try require(try Data(contentsOf: otherURL) == otherData, "A tentativa de publicação alterou os bytes originais protegidos.")
        let savedURL = directory.appendingPathComponent("saved-protected-copy.pdf")
        try passwordWorkspace.publishSavedCopy(saveBytes, to: savedURL, password: savedPassword)
        try require(passwordWorkspace.activeSession?.password == savedPassword && passwordWorkspace.savedDocumentURL == savedURL && !passwordWorkspace.hasUnsavedChanges,
                    "A publicação bem-sucedida não atualizou senha e estado da sessão.")
        let savedVerification = PDFDocument(url: savedURL)
        try require(savedVerification?.isLocked == true && savedVerification?.unlock(withPassword: savedPassword) == true,
                    "A cópia publicada não manteve a nova senha.")
        try require(try Data(contentsOf: otherURL) == otherData, "Salvar a cópia protegida alterou a origem.")

        // Real PDFKit annotation changes, independent per-document undo and persisted redo.
        let page = firstSession.document.page(at: 0)!
        let annotation = PDFAnnotation(bounds: CGRect(x: 80, y: 300, width: 100, height: 50), forType: .freeText, withProperties: nil)
        annotation.contents = "Original"; page.addAnnotation(annotation)
        firstSession.history.inserted(annotation, on: page, name: "Inserir texto")
        firstSession.history.undoManager.undo()
        try require(!page.annotations.contains(where: { $0 === annotation }), "Desfazer não removeu a anotação criada.")
        firstSession.history.undoManager.redo()
        try require(page.annotations.contains(where: { $0 === annotation }), "Refazer não restaurou a anotação criada.")
        let before = PDFAnnotationState(annotation)
        EditableAnnotations.resize(annotation, to: CGRect(x: 100, y: 320, width: 140, height: 70))
        annotation.contents = "Editado"; annotation.color = .systemRed
        let border = PDFBorder(); border.lineWidth = 6; annotation.border = border
        firstSession.history.changed(annotation, before: before)
        firstSession.history.undoManager.undo()
        try require(annotation.bounds == before.bounds && annotation.contents == "Original", "Desfazer não restaurou geometria e conteúdo.")
        firstSession.history.undoManager.redo()
        try require(annotation.contents == "Editado" && annotation.bounds.width == 140 && annotation.border?.lineWidth == 6, "Refazer perdeu propriedades editadas.")
        try require(!secondSession.history.undoManager.canUndo, "Uma edição de outra aba contaminou o histórico do documento de referência.")
        firstSession.history.remove(annotation, from: page)
        firstSession.history.undoManager.undo()
        try require(page.annotations.contains(where: { $0 === annotation }), "Desfazer exclusão não restaurou a anotação.")
        try require(!EditableAnnotations.accepts(widget), "O editor genérico permitiu transformar campos de formulário como anotações gráficas.")
        try require(rejects { try EditableAnnotations.validate(CGRect(x: -20, y: 0, width: 10, height: 10), on: page) }, "O editor aceitou uma anotação fora da página.")
        let mark = PDFAnnotation(bounds: CGRect(x: 50, y: 200, width: 100, height: 20), forType: .highlight, withProperties: nil)
        mark.quadrilateralPoints = [NSPoint(x: 0, y: 20), NSPoint(x: 100, y: 20), .zero, NSPoint(x: 100, y: 0)].map(NSValue.init(point:))
        let markBefore = PDFAnnotationState(mark)
        EditableAnnotations.resize(mark, to: CGRect(x: 70, y: 220, width: 200, height: 40))
        try require(mark.quadrilateralPoints?[1].pointValue == NSPoint(x: 200, y: 40), "O redimensionamento não transformou o quadrilátero do realce.")
        markBefore.apply(to: mark)
        try require(mark.quadrilateralPoints?[1].pointValue == NSPoint(x: 100, y: 20), "Restaurar o realce não recuperou o quadrilátero original.")
        let line = PDFAnnotation(bounds: CGRect(x: 0, y: 0, width: 100, height: 100), forType: .line, withProperties: nil)
        line.startPoint = NSPoint(x: 10, y: 20); line.endPoint = NSPoint(x: 80, y: 90)
        EditableAnnotations.resize(line, to: CGRect(x: 10, y: 10, width: 200, height: 50))
        try require(line.startPoint == NSPoint(x: 20, y: 10) && line.endPoint == NSPoint(x: 160, y: 45), "O redimensionamento não transformou os extremos da linha.")
        guard let final = firstSession.document.dataRepresentation(), let finalPage = PDFDocument(data: final)?.page(at: 0) else { throw NSError(domain: "PDF.SessionAudit", code: 9) }
        try require(finalPage.annotations.contains { PDFAnnotationKind.matches($0, .freeText) && $0.contents == "Editado" && $0.bounds.width == 140 }, "Salvar/reabrir perdeu as alterações refeitas.")
        workspace.closeSession(secondSession.id, discardChanges: true)
        try require(workspace.sessions.count == 1 && workspace.comparisonSessionID == nil && !(try store.list()).contains(where: { $0.id == secondSession.id }), "Fechar uma aba deixou recuperação ou referência abandonada.")
        print("Session audit: independent tabs/page/zoom/forms, safe recovery, encrypted snapshots, annotation edit/undo/redo/persistence passed")
    }
}
