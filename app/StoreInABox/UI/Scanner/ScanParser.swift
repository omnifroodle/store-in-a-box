import Foundation

/// One unit label, parsed from its QR payload `<SKU>#<serial>` (decision D3).
struct ScanResult: Equatable {
    let unit: UnitID
    let sku: String
    let serial: String
}

/// Why a scan was not taken. The screen shows `reason`.
enum ScanRejection: Error, Equatable {
    case malformed(String)
    case unknownSKU(String)
    case sameUnitTwice(UnitID)
    case notRecorded(String)

    var reason: String {
        switch self {
        case .malformed(let payload): "Not a unit label: \(payload.isEmpty ? "(empty)" : payload)"
        case .unknownSKU(let sku): "Unknown SKU \(sku)"
        case .sameUnitTwice(let unit): "\(unit) is already in this basket"
        case .notRecorded(let why): "Not recorded: \(why)"
        }
    }
}

enum ScanConfig {
    /// One label is one scan: the camera reports a label many times a second while it is in view, so the label counts
    /// as gone only after no sighting for this long. Tuning constants for stage light (blueprint, Verification).
    static let goneSeconds: TimeInterval = 0.5
    /// And a label scans again no sooner than this after it was last taken, so a camera that loses a held label for
    /// a moment does not take it twice.
    static let repeatSeconds: TimeInterval = 1.0
}

enum ScanParser {
    /// `unit_id` in contracts/schemas/common.schema.json: an upper-case SKU, `#`, a three-digit serial.
    static let unitPattern = #/^([A-Z0-9]+(?:-[A-Z0-9]+)*)#([0-9]{3})$/#

    /// The grammar only. Surrounding whitespace (a scanner's trailing newline) is ignored; nothing else is
    /// normalised, so a lower-case label is malformed.
    static func parse(_ payload: String) -> Result<ScanResult, ScanRejection> {
        let text = payload.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let match = text.wholeMatch(of: unitPattern) else { return .failure(.malformed(text)) }
        return .success(ScanResult(unit: text, sku: String(match.1), serial: String(match.2)))
    }

    /// The grammar, then the catalog.
    static func parse(_ payload: String, knownSKU: (String) -> Bool) -> Result<ScanResult, ScanRejection> {
        parse(payload).flatMap { knownSKU($0.sku) ? .success($0) : .failure(.unknownSKU($0.sku)) }
    }
}

/// Drops repeat reads of a label still in front of the camera, and takes a deliberate second scan of the same label
/// (moved away and back) as a second scan (#119 item 9). Time is passed in, so tests use virtual time.
struct ScanDebouncer {
    var gone: TimeInterval
    var repeatAfter: TimeInterval
    private var lastSeen: [String: TimeInterval] = [:]
    private var lastTaken: [String: TimeInterval] = [:]

    init(gone: TimeInterval = ScanConfig.goneSeconds, repeatAfter: TimeInterval = ScanConfig.repeatSeconds) {
        self.gone = gone
        self.repeatAfter = repeatAfter
    }

    /// True when `payload` should be taken as a new scan: the first sighting, or the first after the label was out
    /// of view for `gone`, at least `repeatAfter` after it was last taken. A label held in view is one scan however
    /// long it stays there.
    mutating func admit(_ payload: String, at now: TimeInterval) -> Bool {
        let returned = lastSeen[payload].map { now - $0 >= gone } ?? true
        let fresh = returned && (lastTaken[payload].map { now - $0 >= repeatAfter } ?? true)
        lastSeen[payload] = now
        if fresh { lastTaken[payload] = now }
        let forget = max(gone, repeatAfter)
        lastSeen = lastSeen.filter { now - $0.value < forget || $0.key == payload }
        lastTaken = lastTaken.filter { now - $0.value < forget || $0.key == payload }
        return fresh
    }
}
