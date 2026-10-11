import SIABCore
import SwiftUI

/// Stage typography: read from the back of a room. Body text is at least 20 pt, counts at least 44 pt, the mode
/// header at least 28 pt bold, and the status bar at least 17 pt. Colour never carries information alone: every
/// coloured mark also has a word and an icon.
enum Stage {
    static let body = Font.system(size: 22)
    static let bodyBold = Font.system(size: 22, weight: .semibold)
    static let small = Font.system(size: 20)
    static let count = Font.system(size: 48, weight: .bold).monospacedDigit()
    static let total = Font.system(size: 44, weight: .bold).monospacedDigit()
    static let header = Font.system(size: 30, weight: .bold)
    static let status = Font.system(size: 18, weight: .medium)
    /// Amber with black text: legible in light and dark mode.
    static let amber = Color(red: 1.0, green: 0.72, blue: 0.0)

    /// Money is integer cents (decision 003); the screen divides by 100.
    static func money(_ money: Money) -> String {
        (Decimal(money.cents) / 100).formatted(.currency(code: money.currency))
    }

    /// The wall-clock time an HLC was stamped at, `HH:mm:ss`.
    static func time(hlc: String) -> String {
        guard let clock = HLC(hlc) else { return hlc }
        return Date(timeIntervalSince1970: Double(clock.ms) / 1000).formatted(.dateTime.hour().minute().second())
    }
}

/// The mode, named in words at the top of every screen, so the room knows what the next scan will do.
struct ModeHeader: View {
    let text: String
    var detail: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(text).font(Stage.header).accessibilityIdentifier("mode-header")
            if let detail { Text(detail).font(Stage.small).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The amber tag on a line whose movement the record disagrees with. The scan was accepted and the movement stands.
struct RecordDisagreesTag: View {
    var body: some View {
        Label("record disagrees", systemImage: "exclamationmark.triangle.fill")
            .font(Stage.small.weight(.semibold))
            .foregroundStyle(.black)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(Stage.amber, in: Capsule())
            .accessibilityIdentifier("record-disagrees")
    }
}

/// Side by side on an iPad, stacked on a phone.
struct AdaptiveStack<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    @ViewBuilder let content: () -> Content

    var body: some View {
        if sizeClass == .regular {
            HStack(alignment: .top, spacing: 24, content: content)
        } else {
            VStack(alignment: .leading, spacing: 16, content: content)
        }
    }
}
