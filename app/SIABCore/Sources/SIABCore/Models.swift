import Foundation

// Mirrors of contracts/schemas/store/*.schema.json. Each document carries its id as `_id` when encoded, as the
// fixtures do; `CodingUserInfoKey.omitDocumentID` leaves it out (Couchbase Lite keeps the id outside the body).
// Nullable fields encode as `null`, never as a missing key, because the schemas require every field.

public enum Custodian {
    public static let store = "store-richmond"
    public static let customer = "customer"
    public static let unknown = "unknown"
    public static let hq = "hq"
}

public extension CodingUserInfoKey {
    static let omitDocumentID = CodingUserInfoKey(rawValue: "siab.omitDocumentID")!
}

extension Encoder {
    var includesDocumentID: Bool { (userInfo[.omitDocumentID] as? Bool) != true }
}

public struct Money: Codable, Hashable {
    public var cents: Int
    public var currency: String
    public init(cents: Int, currency: String = "USD") { self.cents = cents; self.currency = currency }
}

public struct Tender: Codable, Hashable {
    public enum Kind: String, Codable { case cash, cardSimulated = "card_simulated" }
    public var kind: Kind
    public var amount: Money
    public init(kind: Kind, amount: Money) { self.kind = kind; self.amount = amount }
}

public enum MovementKind: String, Codable { case checkOut = "check_out", checkIn = "check_in", sale }

public struct Transaction: Codable, Identifiable, Hashable {
    public var id: String
    public var v = 1
    public var type = "transaction"
    public var trip: String
    public var box: String?
    public var kind: MovementKind
    public var unitID: String
    public var sku: String
    public var fromCustodian: String
    public var toCustodian: String
    public var prevTxn: String?
    public var fromAllocation: String?
    public var toAllocation: String?
    public var device: String
    public var hlc: String
    public var deviceClock: String
    public var boxClock: String?
    public var basket: String?
    public var price: Money?
    public var tender: Tender?

    enum CodingKeys: String, CodingKey {
        case id = "_id", v, type, trip, box, kind, unitID = "unit_id", sku, fromCustodian = "from_custodian",
             toCustodian = "to_custodian", prevTxn = "prev_txn", fromAllocation = "from_allocation",
             toAllocation = "to_allocation", device, hlc, deviceClock = "device_clock", boxClock = "box_clock",
             basket, price, tender
    }

    public init(id: String, trip: String, box: String?, kind: MovementKind, unitID: String, sku: String,
                fromCustodian: String, toCustodian: String, prevTxn: String?, fromAllocation: String?,
                toAllocation: String?, device: String, hlc: String, deviceClock: String, boxClock: String? = nil,
                basket: String? = nil, price: Money? = nil, tender: Tender? = nil) {
        self.id = id; self.trip = trip; self.box = box; self.kind = kind; self.unitID = unitID; self.sku = sku
        self.fromCustodian = fromCustodian; self.toCustodian = toCustodian; self.prevTxn = prevTxn
        self.fromAllocation = fromAllocation; self.toAllocation = toAllocation; self.device = device
        self.hlc = hlc; self.deviceClock = deviceClock; self.boxClock = boxClock; self.basket = basket
        self.price = price; self.tender = tender
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        if encoder.includesDocumentID { try c.encode(id, forKey: .id) }
        try c.encode(v, forKey: .v); try c.encode(type, forKey: .type); try c.encode(trip, forKey: .trip)
        try c.encode(box, forKey: .box); try c.encode(kind, forKey: .kind); try c.encode(unitID, forKey: .unitID)
        try c.encode(sku, forKey: .sku); try c.encode(fromCustodian, forKey: .fromCustodian)
        try c.encode(toCustodian, forKey: .toCustodian); try c.encode(prevTxn, forKey: .prevTxn)
        try c.encode(fromAllocation, forKey: .fromAllocation); try c.encode(toAllocation, forKey: .toAllocation)
        try c.encode(device, forKey: .device); try c.encode(hlc, forKey: .hlc)
        try c.encode(deviceClock, forKey: .deviceClock); try c.encode(boxClock, forKey: .boxClock)
        try c.encode(basket, forKey: .basket); try c.encode(price, forKey: .price); try c.encode(tender, forKey: .tender)
    }
}

public struct Allocation: Codable, Identifiable, Hashable {
    public enum Status: String, Codable { case active, closed }
    public var id: String
    public var v = 1
    public var type = "allocation"
    public var trip: String
    public var box: String
    public var sku: String
    public var custodian: String
    public var parent: String?
    public var fromCustodian: String
    public var openedBy: String
    public var openedAt: String
    public var closedAt: String?
    public var status: Status

    enum CodingKeys: String, CodingKey {
        case id = "_id", v, type, trip, box, sku, custodian, parent, fromCustodian = "from_custodian",
             openedBy = "opened_by", openedAt = "opened_at", closedAt = "closed_at", status
    }

    public init(trip: String, box: String, sku: String, custodian: String, parent: String?, fromCustodian: String,
                openedBy: String, openedAt: String) {
        self.id = "alloc::" + openedAt; self.trip = trip; self.box = box; self.sku = sku; self.custodian = custodian
        self.parent = parent; self.fromCustodian = fromCustodian; self.openedBy = openedBy; self.openedAt = openedAt
        self.closedAt = nil; self.status = .active
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        if encoder.includesDocumentID { try c.encode(id, forKey: .id) }
        try c.encode(v, forKey: .v); try c.encode(type, forKey: .type); try c.encode(trip, forKey: .trip)
        try c.encode(box, forKey: .box); try c.encode(sku, forKey: .sku); try c.encode(custodian, forKey: .custodian)
        try c.encode(parent, forKey: .parent); try c.encode(fromCustodian, forKey: .fromCustodian)
        try c.encode(openedBy, forKey: .openedBy); try c.encode(openedAt, forKey: .openedAt)
        try c.encode(closedAt, forKey: .closedAt); try c.encode(status, forKey: .status)
    }
}

public enum ExceptionKind: String, Codable {
    case oversell, doubleScan = "double_scan", unexpectedCheckIn = "unexpected_check_in",
         foreignMovement = "foreign_movement"
}

public struct ExceptionDoc: Codable, Identifiable, Hashable {
    public struct Branch: Codable, Hashable {
        public var txn: String
        public var device: String
        public var kind: MovementKind
        public var toCustodian: String
        public var hlc: String
        enum CodingKeys: String, CodingKey { case txn, device, kind, toCustodian = "to_custodian", hlc }
    }

    public struct ProposedResolution: Codable, Hashable {
        public var action: String
        public var note: String
    }

    public struct Resolution: Codable, Hashable {
        public var by: String
        public var at: String
        public var hlc: String?
        public var chosenTxn: String?
        public var note: String
        enum CodingKeys: String, CodingKey { case by, at, hlc, chosenTxn = "chosen_txn", note }
        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(by, forKey: .by); try c.encode(at, forKey: .at); try c.encode(hlc, forKey: .hlc)
            try c.encode(chosenTxn, forKey: .chosenTxn); try c.encode(note, forKey: .note)
        }
    }

    public var id: String
    public var v = 1
    public var type = "exception"
    public var trip: String
    public var box: String?
    public var kind: ExceptionKind
    public var unitID: String
    public var sku: String
    public var disputeKey: String
    public var forkTxn: String?
    public var transactions: [String]
    public var branches: [Branch]
    public var proposedResolution: ProposedResolution
    public var status: String
    public var resolution: Resolution?
    public var detectedBy: String
    /// The detector's hlc; left out of the fixtures' expected documents, always set on a written one.
    public var detectedAt: String?

    enum CodingKeys: String, CodingKey {
        case id = "_id", v, type, trip, box, kind, unitID = "unit_id", sku, disputeKey = "dispute_key",
             forkTxn = "fork_txn", transactions, branches, proposedResolution = "proposed_resolution", status,
             resolution, detectedBy = "detected_by", detectedAt = "detected_at"
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        if encoder.includesDocumentID { try c.encode(id, forKey: .id) }
        try c.encode(v, forKey: .v); try c.encode(type, forKey: .type); try c.encode(trip, forKey: .trip)
        try c.encode(box, forKey: .box); try c.encode(kind, forKey: .kind); try c.encode(unitID, forKey: .unitID)
        try c.encode(sku, forKey: .sku); try c.encode(disputeKey, forKey: .disputeKey)
        try c.encode(forkTxn, forKey: .forkTxn); try c.encode(transactions, forKey: .transactions)
        try c.encode(branches, forKey: .branches); try c.encode(proposedResolution, forKey: .proposedResolution)
        try c.encode(status, forKey: .status); try c.encode(resolution, forKey: .resolution)
        try c.encode(detectedBy, forKey: .detectedBy)
        try c.encodeIfPresent(detectedAt, forKey: .detectedAt)
    }
}

/// Written by HQ only; the tablet reads it.
public struct Product: Codable, Identifiable, Hashable {
    public var id: String
    public var v: Int
    public var type: String
    public var sku: String
    public var name: String
    public var price: Money
    public var category: String
    public var categoryFamily: String
    public var size: String?
    public var color: String?
    public var tags: [String]
    public var regions: [String]
    enum CodingKeys: String, CodingKey {
        case id = "_id", v, type, sku, name, price, category, categoryFamily = "category_family", size, color, tags,
             regions
    }
}

/// Written by HQ only; the tablet reads it.
public struct Trip: Codable, Identifiable, Hashable {
    public struct Venue: Codable, Hashable { public var name: String; public var city: String; public var state: String }
    public var id: String
    public var v: Int
    public var type: String
    public var tripID: String
    public var store: String
    public var box: String
    public var region: String
    public var venue: Venue
    public var starts: String
    public var ends: String
    public var status: String
    public var devices: [String]
    enum CodingKeys: String, CodingKey {
        case id = "_id", v, type, tripID = "trip_id", store, box, region, venue, starts, ends, status, devices
    }
}

/// `inventory` (Capella only): the HQ-side input to `Ledger.conservation`.
public struct Inventory: Codable, Hashable {
    public var id: String?
    public var store: String
    public var sku: String
    public var openingOnHand: Int
    public var received: Int
    enum CodingKeys: String, CodingKey {
        case id = "_id", store, sku, openingOnHand = "opening_on_hand", received
    }
}
