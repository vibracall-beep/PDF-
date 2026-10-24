import Foundation

extension Notification.Name {
    static let applicationWorkStopping = Notification.Name("PDF.ApplicationWork.stopping")
    static let applicationWorkResumed = Notification.Name("PDF.ApplicationWork.resumed")
}

/// Explicit lifetime for work that does not run through Workspace.execute.
/// A ticket ends only after its worker and private-file cleanup have finished.
/// UI disappearance or a cancellation request is not completion.
enum ApplicationWork {
    final class Ticket: @unchecked Sendable {
        fileprivate let id = UUID()
        private let lock = NSLock()
        private var cancellation: (@Sendable () -> Void)?
        private var cancellationRequested = false
        private var finished = false
        fileprivate init(cancel: @escaping @Sendable () -> Void) { cancellation = cancel }
        func cancel() {
            lock.lock()
            guard !finished, !cancellationRequested else { lock.unlock(); return }
            cancellationRequested = true
            let action = cancellation
            lock.unlock()
            action?()
        }
        func finish() {
            lock.lock()
            guard !finished else { lock.unlock(); return }
            finished = true; cancellation = nil
            lock.unlock()
            ApplicationWork.remove(id)
        }
    }
    private static let lock = NSLock()
    private static var tickets: [UUID: Ticket] = [:]
    private static var stopping = false
    static func begin(cancelWhenStopping: Bool = true, cancel: @escaping @Sendable () -> Void) -> Ticket {
        let ticket = Ticket(cancel: cancel)
        lock.lock(); tickets[ticket.id] = ticket; let cancelImmediately = stopping; lock.unlock()
        if cancelImmediately && cancelWhenStopping { ticket.cancel() }
        return ticket
    }
    static var activeCount: Int { lock.lock(); defer { lock.unlock() }; return tickets.count }
    static var isAcceptingWork: Bool { lock.lock(); defer { lock.unlock() }; return !stopping }
    static func cancelAll() {
        lock.lock(); let changed = !stopping; stopping = true; let pending = Array(tickets.values); lock.unlock()
        if changed { NotificationCenter.default.post(name: .applicationWorkStopping, object: nil) }
        for ticket in pending { ticket.cancel() }
    }
    /// A refused quit keeps the application usable; existing cancelled work
    /// remains registered until its own completion, never silently discarded.
    static func resumeAcceptingWork() {
        lock.lock(); let changed = stopping; stopping = false; lock.unlock()
        if changed { NotificationCenter.default.post(name: .applicationWorkResumed, object: nil) }
    }
    private static func remove(_ id: UUID) { lock.lock(); tickets[id] = nil; lock.unlock() }
}
