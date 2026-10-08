// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "SIABCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "SIABCore", targets: ["SIABCore"]),
    ],
    dependencies: [
        // Enterprise Edition: MultipeerReplicator (device-to-device sync) ships only in EE.
        .package(url: "https://github.com/couchbase/couchbase-lite-swift-ee.git", exact: "4.1.2"),
    ],
    targets: [
        .target(
            name: "SIABCore",
            dependencies: [.product(name: "CouchbaseLiteSwift", package: "couchbase-lite-swift-ee")]
        ),
        .testTarget(
            name: "SIABCoreTests",
            dependencies: ["SIABCore"],
            // Symlinks into the repository (contracts/fixtures/ledger, ports/box-agent.md), copied at build time.
            resources: [.copy("Fixtures/ledger"), .copy("Fixtures/box-agent.md")]
        ),
    ]
)
