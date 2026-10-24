import Foundation

/// Registers the entire async operation, including deferred cleanup, before it
/// can start. Cancellation requested before task installation is retained.
enum ApplicationTask {
    @MainActor @discardableResult static func start(
        cancel: @escaping @Sendable () -> Void = {},
        operation: @escaping @MainActor () async -> Void
    ) -> Task<Void, Never> {
        let control = ApplicationTaskControl(cancel: cancel)
        let ticket = ApplicationWork.begin { control.cancel() }
        let task = Task { @MainActor in
            defer { control.clear(); ticket.finish() }
            await operation()
        }
        control.install { task.cancel() }
        return task
    }

    /// Async callers such as App Intents retain their result and error contract;
    /// the registered child is still awaited when their own task is cancelled.
    @MainActor static func run<Value: Sendable>(
        cancel: @escaping @Sendable () -> Void = {},
        operation: @escaping @MainActor () async throws -> Value
    ) async throws -> Value {
        guard ApplicationWork.isAcceptingWork else { throw CancellationError() }
        let control = ApplicationTaskControl(cancel: cancel)
        let ticket = ApplicationWork.begin { control.cancel() }
        let task = Task { @MainActor in
            defer { control.clear(); ticket.finish() }
            try Task.checkCancellation()
            return try await operation()
        }
        control.install { task.cancel() }
        return try await withTaskCancellationHandler(operation: { try await task.value }, onCancel: { control.cancel() })
    }
}

private final class ApplicationTaskControl: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelTask: (@Sendable () -> Void)?
    private var cancelled = false
    private var onCancel: (@Sendable () -> Void)?
    init(cancel: @escaping @Sendable () -> Void) { onCancel = cancel }
    func install(_ cancel: @escaping @Sendable () -> Void) {
        lock.lock(); cancelTask = cancel; let shouldCancel = cancelled; lock.unlock()
        if shouldCancel { cancel() }
    }
    func cancel() {
        lock.lock()
        guard !cancelled else { lock.unlock(); return }
        cancelled = true
        let task = cancelTask, action = onCancel
        lock.unlock()
        action?(); task?()
    }
    func clear() {
        lock.lock(); cancelTask = nil; onCancel = nil; lock.unlock()
    }
}
