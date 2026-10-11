import AudioToolbox
import Foundation
import UIKit

/// What the screen shows under the scanner after a scan.
enum ScanNotice: Equatable {
    case accepted(String)
    case rejected(String)
}

/// Haptic and tone on accept, haptic on reject. Tests pass a silent one.
protocol ScanFeedback {
    func accepted()
    func rejected()
}

struct DeviceScanFeedback: ScanFeedback {
    func accepted() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        AudioServicesPlaySystemSound(1057)  // the short "Tink" tone
    }

    func rejected() { UINotificationFeedbackGenerator().notificationOccurred(.error) }
}

/// The scanner, shared by every screen: debounce, grammar, catalog, then the screen's own handler, then feedback.
/// A handler returns the words to show on success or the reason it refused.
@MainActor
final class ScanStation: ObservableObject {
    typealias Handler = (ScanResult) -> Result<String, ScanRejection>
    @Published private(set) var notice: ScanNotice?
    private var debouncer = ScanDebouncer()
    private let catalog: ProductCatalog
    private let feedback: ScanFeedback
    private let now: () -> TimeInterval

    init(catalog: ProductCatalog, feedback: ScanFeedback = DeviceScanFeedback(),
         now: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.catalog = catalog
        self.feedback = feedback
        self.now = now
    }

    /// A camera read (debounced), or a typed payload (`debounce: false`: each Return is a deliberate scan).
    func receive(_ payload: String, debounce: Bool = true, handler: Handler) {
        if debounce, !debouncer.admit(payload, at: now()) { return }
        let catalog = catalog
        switch ScanParser.parse(payload, knownSKU: { catalog.current[$0] != nil }).flatMap(handler) {
        case .success(let words):
            notice = .accepted(words)
            feedback.accepted()
        case .failure(let rejection):
            notice = .rejected(rejection.reason)
            feedback.rejected()
        }
    }

    func clear() { notice = nil }
}
