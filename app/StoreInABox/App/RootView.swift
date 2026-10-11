import SIABCore
import SwiftUI

/// Paired: the status bar over the tab bar (Sell, Shelf, Custody, Exceptions), with Diagnostics behind the gear.
/// Not paired: Diagnostics, where pairing starts.
struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var diagnostics = false

    var body: some View {
        if let screens = model.screens, let sync = model.sync {
            VStack(spacing: 0) {
                StatusBar(sync: sync, device: screens.identity.device) { diagnostics = true }
                MainTabs(screens: screens, exceptions: screens.exceptions)
            }
            .sheet(isPresented: $diagnostics) {
                NavigationStack {
                    DiagnosticsView()
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { diagnostics = false } } }
                }
                .environmentObject(model)
            }
        } else {
            NavigationStack { DiagnosticsView() }
        }
    }
}

private struct MainTabs: View {
    let screens: Screens
    @ObservedObject var exceptions: ExceptionsViewModel

    var body: some View {
        TabView {
            SellView(model: screens.sell, station: screens.scanner)
                .tabItem { Label("Sell", systemImage: "cart.fill") }
            ShelfView(model: screens.shelf, device: screens.identity.device, box: screens.identity.box)
                .tabItem { Label("Shelf", systemImage: "square.grid.3x2.fill") }
            CustodyView(model: screens.custody, station: screens.scanner)
                .tabItem { Label("Custody", systemImage: "arrow.left.arrow.right") }
            ExceptionsView(model: exceptions)
                .tabItem { Label("Exceptions", systemImage: "exclamationmark.triangle.fill") }
                .badge(exceptions.disputes.count)
        }
    }
}
