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

    func testPeerCountLeavesOutOfflinePeers() {
        let peers: [PeerLink.State] = [.online, .replicating, .offline]
        XCTAssertEqual(StatusText.peers(.running, peers), "2 peers")
        XCTAssertEqual(StatusText.peers(.running, Array(peers.prefix(1))), "1 peer")
        XCTAssertEqual(StatusText.peers(.unavailable("Community Edition"), []), "no mesh")
    }
}
