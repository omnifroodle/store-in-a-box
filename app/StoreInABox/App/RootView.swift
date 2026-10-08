import SIABCore
import SwiftUI

/// Placeholder root until WS6's screens and the Diagnostics screen land: who this device is and the live counts.
struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationStack {
            List {
                Section("Device") {
                    if let identity = model.identity {
                        LabeledContent("Device", value: identity.device)
                        LabeledContent("Box", value: identity.box)
                        LabeledContent("Trip", value: identity.trip)
                    } else {
                        Text(model.problem ?? "Not paired")
                    }
                }
                Section("Counts") {
                    ForEach(model.state.counts.keys.sorted(), id: \.self) { key in
                        LabeledContent("\(key.custodian)  \(key.sku)", value: "\(model.state.counts[key] ?? 0)")
                    }
                }
            }
            .navigationTitle("Store in a Box")
        }
    }
}
