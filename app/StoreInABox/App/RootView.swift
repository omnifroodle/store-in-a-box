import SIABCore
import SwiftUI

/// Paired: the status bar over the tab bar (Sell, Shelf, Custody, Exceptions), with Diagnostics behind the gear.
/// Not paired: Diagnostics, where pairing starts.
struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var diagnostics = false

    var body: some View {
        content.preferredColorScheme(Stage.colorScheme)
    }

    @ViewBuilder private var content: some View {
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

/// The four screens behind a stage-sized tab bar: the system tab bar's labels are below the 17 pt floor and cannot be
/// sized on iPadOS (#119 item 6).
private struct MainTabs: View {
    let screens: Screens
    @ObservedObject var exceptions: ExceptionsViewModel
    @State private var tab = StageTab.sell

    var body: some View {
        VStack(spacing: 0) {
            StageTabBar(selection: $tab, exceptions: exceptions.disputes.count)
            Divider()
            Group {
                switch tab {
                case .sell: SellView(model: screens.sell, station: screens.scanner)
                case .shelf: ShelfView(model: screens.shelf, device: screens.identity.device, box: screens.identity.box)
                case .custody: CustodyView(model: screens.custody, station: screens.scanner)
                case .exceptions: ExceptionsView(model: exceptions)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
    }
}

enum StageTab: String, CaseIterable, Identifiable {
    case sell, shelf, custody, exceptions

    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var icon: String {
        switch self {
        case .sell: "cart.fill"
        case .shelf: "square.grid.3x2.fill"
        case .custody: "arrow.left.arrow.right"
        case .exceptions: "exclamationmark.triangle.fill"
        }
    }
}

/// Labels at 20 pt (17 pt on a phone). The selected tab is a filled, bold capsule (shape and weight, not colour alone) and carries the
/// selected trait; Exceptions shows its open count as a number.
private struct StageTabBar: View {
    @Binding var selection: StageTab
    let exceptions: Int

    var body: some View {
        ViewThatFits(in: .horizontal) {
            row(compact: false)
            row(compact: true)  // a phone: titles only, at the 17 pt floor
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity)
    }

    private func row(compact: Bool) -> some View {
        HStack(spacing: compact ? 4 : 8) {
            ForEach(StageTab.allCases) { tab in
                let selected = tab == selection
                Button { selection = tab } label: {
                    HStack(spacing: 8) {
                        if !compact { Image(systemName: tab.icon) }
                        Text(tab.title)
                        if tab == .exceptions, exceptions > 0 {
                            Text("\(exceptions)")
                                .monospacedDigit()
                                .padding(.horizontal, 8)
                                .background(selected ? Color.white : Stage.amber, in: Capsule())
                                .foregroundStyle(.black)
                        }
                    }
                    .font((compact ? Stage.status : Stage.tab).weight(selected ? .bold : .semibold))
                    .lineLimit(1)
                    .fixedSize()
                    .padding(.horizontal, compact ? 10 : 16)
                    .frame(minHeight: 48)
                    .foregroundStyle(selected ? Color.white : Color.primary)
                    .background(selected ? Color.accentColor : Color.clear, in: Capsule())
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
                .accessibilityIdentifier("tab-\(tab.rawValue)")
            }
        }
    }
}
