import SwiftUI

/// Until WS6's screens land the root is the Diagnostics screen; WS6 puts it behind a gear icon.
struct RootView: View {
    var body: some View {
        NavigationStack {
            DiagnosticsView()
        }
    }
}
