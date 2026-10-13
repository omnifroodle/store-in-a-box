import XCTest
@testable import SIABCore

final class JSONValueTests: XCTestCase {
    /// `{"cents": 12.5}` is a value, not a parse failure, so rule 0 can say why the sale fails: `invalid_value`.
    func testDoubleParsesAndIsInvalidValue() throws {
        let money = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"cents": 12.5, "currency": "USD"}"#.utf8))
        XCTAssertEqual(money, .object(["cents": .double(12.5), "currency": .string("USD")]))
        XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: Data("12900".utf8)), .int(12900))

        let url = DocumentCheckTests.contracts.appendingPathComponent("fixtures/docs/transaction/valid/sale.json")
        var sale = DocumentCheckTests.object(try DocumentCheckTests.read(url))
        sale["price"] = money
        let result = DocumentCheck.ingest([("txn::1792329000000-0000-tablet-a", sale)], collection: "transaction",
                                          as: Transaction.self)
        XCTAssertEqual(result.accepted, [])
        XCTAssertEqual(result.drops.map(\.code), [.invalidValue])
        XCTAssertTrue(result.drops[0].detail.hasPrefix("price"), result.drops[0].detail)
    }

    /// The canonical form prints a float as Python's `json.dumps` does.
    func testCanonicalDoubleIsPythonRepr() {
        let cases: [(Double, String)] = [(12.5, "12.5"), (12.0, "12.0"), (1e15, "1000000000000000.0"), (1e16, "1e+16"),
                                         (1e-5, "1e-05"), (0.0001, "0.0001"), (-0.0, "-0.0"), (.nan, "NaN"),
                                         (.infinity, "Infinity")]
        for (value, python) in cases { XCTAssertEqual(JSONValue.double(value).canonical, python) }
        XCTAssertEqual(JSONValue.object(["b": .double(0.1), "a": .int(1)]).canonical, #"{"a":1,"b":0.1}"#)
    }
}
