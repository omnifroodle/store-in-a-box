import XCTest
@testable import SIABCore

final class FakeClock: Clock {
    var ms: Int64
    init(_ ms: Int64 = 1_792_328_400_000) { self.ms = ms }
    func nowMs() -> Int64 { ms }
    func advance(_ delta: Int64) { ms += delta }
}

/// The same cases as tests/ledger/test_hlc.py, under a fake clock.
final class HLCTests: XCTestCase {
    func testFormatAndParseRoundTrip() {
        let value = HLC(ms: 1_792_328_410_000, counter: 0x1A, device: "tablet-a")
        XCTAssertEqual(value.string, "1792328410000-001a-tablet-a")
        XCTAssertEqual(HLC(value.string), value)
        XCTAssertEqual(HLC(value.string)?.counter, 0x1A)
        for bad in ["1792328410000-001A-tablet-a", "179232841000-0000-tablet-a", "1792328410000-0000-Tablet", ""] {
            XCTAssertNil(HLC(bad), bad)
        }
    }

    func testMonotonicUnderFakeClock() {
        let clock = FakeClock()
        var issued = [HLC.now(clock: clock, last: nil, device: "tablet-a")]
        XCTAssertEqual(issued[0].string, "1792328400000-0000-tablet-a")
        for step: Int64 in [0, 0, 5, -10_000, 0, 1, -1, 20_000] {
            clock.advance(step)
            issued.append(HLC.now(clock: clock, last: issued.last, device: "tablet-a"))
        }
        XCTAssertEqual(issued, issued.sorted())
        XCTAssertEqual(Set(issued).count, issued.count)
        XCTAssertEqual(issued[1].string, "1792328400000-0001-tablet-a")
        XCTAssertEqual(issued.last?.string, "1792328410005-0000-tablet-a")
    }

    func testCounterOverflowCarriesIntoTheMilliseconds() {
        let clock = FakeClock()
        let last = HLC(ms: clock.ms, counter: 0xFFFF, device: "tablet-a")
        let next = HLC.now(clock: clock, last: last, device: "tablet-a")
        XCTAssertEqual(next, HLC(ms: clock.ms + 1, counter: 0, device: "tablet-a"))
        XCTAssertGreaterThan(next, last)
    }

    func testReceiveIsAfterBoth() {
        let clock = FakeClock()
        let local = HLC.now(clock: clock, last: nil, device: "tablet-a")
        let remote = HLC("1792328999000-0003-tablet-b")!
        let merged = HLC.receive(local: local, remote: remote, clock: clock, device: "tablet-a")
        XCTAssertEqual(merged.string, "1792328999000-0004-tablet-a")
        XCTAssertGreaterThan(merged, local)

        let sameMs = HLC.receive(local: HLC("1792328999000-0007-tablet-a"), remote: HLC("1792328999000-0002-tablet-b")!,
                                 clock: clock, device: "tablet-a")
        XCTAssertEqual(sameMs.string, "1792328999000-0008-tablet-a")

        clock.advance(1_000_000)
        XCTAssertEqual(HLC.receive(local: merged, remote: remote, clock: clock, device: "tablet-a"),
                       HLC(ms: clock.ms, counter: 0, device: "tablet-a"))
        XCTAssertEqual(HLC.receive(local: nil, remote: remote, clock: FakeClock(0), device: "phone-1").string,
                       "1792328999000-0004-phone-1")
    }

    func testSendReceivePreservesCausality() {
        let a = HLC.now(clock: FakeClock(1_792_328_400_000), last: nil, device: "tablet-a")
        let bClock = FakeClock(1_792_328_000_000)  // 400 s behind
        let b = HLC.receive(local: nil, remote: a, clock: bClock, device: "tablet-b")
        let b2 = HLC.now(clock: bClock, last: b, device: "tablet-b")
        XCTAssertTrue(a < b && b < b2)
    }
}
