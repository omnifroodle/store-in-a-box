import Foundation

/// Unix milliseconds. Injected everywhere a time is read, so tests drive it with a fake clock.
public protocol Clock { func nowMs() -> Int64 }

public struct SystemClock: Clock {
    public init() {}
    public func nowMs() -> Int64 { Int64((Date().timeIntervalSince1970 * 1000).rounded(.down)) }
}

/// Hybrid logical clock, `<unix_ms:13>-<counter:4 hex>-<device>` (ports/ledger.md, "HLC"). The fields are fixed
/// width, so string order is causal order.
public struct HLC: Comparable, Codable, Hashable, CustomStringConvertible {
    public let string: String
    public let ms: Int64
    public let counter: Int
    public let device: String

    static let maxMs: Int64 = 9_999_999_999_999
    static let maxCounter = 0xFFFF

    public init?(_ string: String) {
        let parts = string.split(separator: "-", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0].count == 13, parts[0].allSatisfy(\.isASCIIDigit),
              parts[1].count == 4, parts[1].allSatisfy(\.isLowerHex),
              let ms = Int64(parts[0]), let counter = Int(parts[1], radix: 16), HLC.isDeviceID(String(parts[2]))
        else { return nil }
        self.string = string
        self.ms = ms
        self.counter = counter
        self.device = String(parts[2])
    }

    public init(ms: Int64, counter: Int, device: String) {
        precondition((0...HLC.maxMs).contains(ms), "hlc milliseconds out of range: \(ms)")
        precondition((0...HLC.maxCounter).contains(counter), "hlc counter out of range: \(counter)")
        precondition(HLC.isDeviceID(device), "not a device id: \(device)")
        let digits = String(ms)
        let hex = String(counter, radix: 16)
        self.string = String(repeating: "0", count: 13 - digits.count) + digits + "-"
            + String(repeating: "0", count: 4 - hex.count) + hex + "-" + device
        self.ms = ms
        self.counter = counter
        self.device = device
    }

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        guard let value = HLC(raw) else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "not an hlc: \(raw)"))
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(string)
    }

    public var description: String { string }
    public static func < (a: HLC, b: HLC) -> Bool { a.string < b.string }
    public static func == (a: HLC, b: HLC) -> Bool { a.string == b.string }
    public func hash(into hasher: inout Hasher) { hasher.combine(string) }

    /// `^[a-z][a-z0-9-]*$`
    public static func isDeviceID(_ s: String) -> Bool {
        guard let first = s.unicodeScalars.first, ("a"..."z").contains(first) else { return false }
        return s.unicodeScalars.allSatisfy { ("a"..."z").contains($0) || ("0"..."9").contains($0) || $0 == "-" }
    }

    /// The next (ms, counter): a full counter carries into the milliseconds rather than blocking a scan.
    private static func advance(_ ms: Int64, _ counter: Int) -> (Int64, Int) {
        counter < maxCounter ? (ms, counter + 1) : (ms + 1, 0)
    }

    /// `hlc_now`: a local event. Strictly greater than `last`; follows the clock when it moves ahead.
    public static func now(clock: Clock, last: HLC?, device: String) -> HLC {
        let pt = clock.nowMs()
        guard let last, pt <= last.ms else { return HLC(ms: pt, counter: 0, device: device) }
        let (ms, c) = advance(last.ms, last.counter)
        return HLC(ms: ms, counter: c, device: device)
    }

    /// `hlc_receive`: merge a remote HLC. Strictly greater than both; the device is always the local one.
    public static func receive(local: HLC?, remote: HLC, clock: Clock, device: String) -> HLC {
        let pt = clock.nowMs()
        let (lMs, lC) = local.map { ($0.ms, $0.counter) } ?? (-1, 0)
        let ms = max(lMs, remote.ms, pt)
        let next: (Int64, Int)
        if ms == lMs && ms == remote.ms {
            next = advance(ms, max(lC, remote.counter))
        } else if ms == lMs {
            next = advance(ms, lC)
        } else if ms == remote.ms {
            next = advance(ms, remote.counter)
        } else {
            next = (ms, 0)
        }
        return HLC(ms: next.0, counter: next.1, device: device)
    }
}

private extension Character {
    var isASCIIDigit: Bool { ("0"..."9").contains(self) }
    var isLowerHex: Bool { isASCIIDigit || ("a"..."f").contains(self) }
}
