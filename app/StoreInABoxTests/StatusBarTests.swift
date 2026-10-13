import SIABCore
import XCTest
@testable import StoreInABox

final class StatusBarTests: XCTestCase {
    func testBoxLinkInWords() {
        XCTAssertEqual(StatusText.box(.connected("ws://box/retail"), name: "box-07"), "box-07 connected")
        XCTAssertEqual(StatusText.box(.offline(lastSeenMs: nil), name: "box-07"), "box-07 offline")
        let seen: Int64 = 1_792_328_400_000
        XCTAssertEqual(StatusText.box(.offline(lastSeenMs: seen), name: "box-07"),
                       "box-07 offline since \(StatusText.clock(seen))")
        XCTAssertEqual(StatusText.box(.error("refused"), name: "box-07"), "box-07 link error")
    }

    /// #161: `N dropped` only when N > 0.
    func testDroppedLabelOnlyWhenSomethingWasDropped() {
        XCTAssertNil(StatusText.dropped(0))
        XCTAssertEqual(StatusText.dropped(1), "1 dropped")
        XCTAssertEqual(StatusText.dropped(250), "250 dropped")
    }

    /// Diagnostics' Dropped documents lines, in HQ's words.
    func testDroppedSectionInWords() {
        let drop = Drop(id: "txn::1792328500000-0000-tablet-b", collection: "transaction", code: .version, detail: "v: 2, not 1")
        let record = DropRecord(drop, source: "peer", firstSeen: "2026-10-18T13:00:00.000Z",
                                lastSeen: "2026-10-18T13:02:00.000Z")
        XCTAssertEqual(DroppedSection.count(1), "dropped: 1 documents")
        XCTAssertEqual(DroppedSection.line(record),
                       "newer schema: update the app · peer · \(Clock24.string(1_792_328_520_000))")
    }

    func testPeerCountLeavesOutOfflinePeers() {
        let peers: [PeerLink.State] = [.online, .replicating, .offline]
        XCTAssertEqual(StatusText.peers(.running, peers), "2 peers")
        XCTAssertEqual(StatusText.peers(.running, Array(peers.prefix(1))), "1 peer")
        XCTAssertEqual(StatusText.peers(.unavailable("Community Edition"), []), "no mesh")
    }
}
