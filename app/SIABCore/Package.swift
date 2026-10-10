// swift-tools-version: 5.10
import PackageDescription

// Couchbase Lite edition. Community Edition by default; Enterprise Edition only when the runner opts in with
// `SIAB_CBL_EDITION=enterprise` in the environment of the build (app/README.md, "Couchbase Lite edition"). The
// Multipeer Replicator (device-to-device sync) ships only in Enterprise Edition, so the mesh code is compiled only
// under the `COUCHBASE_ENTERPRISE` condition this sets.
let edition = Context.environment["SIAB_CBL_EDITION"] ?? "community"
guard ["community", "enterprise"].contains(edition) else {
    fatalError("SIAB_CBL_EDITION must be `community` or `enterprise`, not `\(edition)`")
}
let enterprise = edition == "enterprise"
let couchbase = enterprise ? "couchbase-lite-swift-ee" : "couchbase-lite-swift"

let package = Package(
    name: "SIABCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "SIABCore", targets: ["SIABCore"]),
    ],
    dependencies: [
        // Both editions ship the same `CouchbaseLiteSwift` product at the same version.
        .package(url: "https://github.com/couchbase/\(couchbase).git", exact: "4.1.2"),
    ],
    targets: [
        .target(
            name: "SIABCore",
            dependencies: [.product(name: "CouchbaseLiteSwift", package: couchbase)],
            swiftSettings: enterprise ? [.define("COUCHBASE_ENTERPRISE")] : []
        ),
        .testTarget(
            name: "SIABCoreTests",
            dependencies: ["SIABCore"],
            // Symlinks into the repository (contracts/fixtures/ledger, ports/box-agent.md), copied at build time.
            resources: [.copy("Fixtures/ledger"), .copy("Fixtures/box-agent.md")],
            swiftSettings: enterprise ? [.define("COUCHBASE_ENTERPRISE")] : []
        ),
    ]
)
