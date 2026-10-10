import AVFoundation
import SwiftUI
import UIKit

/// The scanner on a screen: the camera (QR only), a typed-payload field in Debug builds (the simulator has no camera),
/// and the last scan's result in words.
struct ScannerPanel: View {
    @ObservedObject var station: ScanStation
    let handler: ScanStation.Handler
    @State private var typed = ""
    @State private var visible = false
    @FocusState private var typing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if UnitCamera.available {
                UnitCamera(running: visible) { station.receive($0, handler: handler) }
                    .frame(minHeight: 220, maxHeight: 320)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
                    .accessibilityLabel("Camera: point it at a unit label")
            }
            #if DEBUG
            TextField("Type a label: SKU#serial", text: $typed)
                .font(Stage.body)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
                .submitLabel(.go)
                .focused($typing)
                .onSubmit {
                    // Return on an empty field puts the keyboard away; after a label, stay ready for the next one.
                    guard !typed.trimmingCharacters(in: .whitespaces).isEmpty else {
                        typing = false
                        return
                    }
                    station.receive(typed, debounce: false, handler: handler)
                    typed = ""
                    typing = true
                }
                .accessibilityIdentifier("scan-text")
            #endif
            if let notice = station.notice { NoticeLine(notice: notice) }
        }
        .onAppear {
            visible = true
            station.clear()
        }
        .onDisappear { visible = false }
    }
}

private struct NoticeLine: View {
    let notice: ScanNotice

    var body: some View {
        switch notice {
        case .accepted(let words):
            Label(words, systemImage: "checkmark.circle.fill").font(Stage.bodyBold)
                .accessibilityIdentifier("scan-accepted")
        case .rejected(let reason):
            Label("Refused: \(reason)", systemImage: "xmark.octagon.fill").font(Stage.bodyBold)
                .foregroundStyle(.red)
                .accessibilityIdentifier("scan-rejected")
        }
    }
}

/// A camera preview that reports every QR code it reads; `ScanStation`'s debounce makes one label one scan.
struct UnitCamera: UIViewControllerRepresentable {
    static var available: Bool { AVCaptureDevice.default(for: .video) != nil }
    let running: Bool
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> Controller {
        let controller = Controller()
        controller.onCode = onCode
        return controller
    }

    func updateUIViewController(_ controller: Controller, context: Context) {
        controller.onCode = onCode
        controller.setRunning(running)
    }

    final class Controller: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
        var onCode: ((String) -> Void)?
        private let session = AVCaptureSession()

        override func viewDidLoad() {
            super.viewDidLoad()
            guard let camera = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: camera), session.canAddInput(input) else { return }
            session.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else { return }
            session.addOutput(output)
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]
            let preview = AVCaptureVideoPreviewLayer(session: session)
            preview.videoGravity = .resizeAspectFill
            view.layer.addSublayer(preview)
        }

        override func viewDidLayoutSubviews() {
            super.viewDidLayoutSubviews()
            view.layer.sublayers?.forEach { $0.frame = view.bounds }
        }

        /// Only the visible screen's camera runs.
        func setRunning(_ running: Bool) {
            let session = session
            guard running != session.isRunning else { return }
            DispatchQueue.global(qos: .userInitiated).async { running ? session.startRunning() : session.stopRunning() }
        }

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject],
                            from connection: AVCaptureConnection) {
            for case let code as AVMetadataMachineReadableCodeObject in objects {
                if let text = code.stringValue { onCode?(text) }
            }
        }
    }
}
