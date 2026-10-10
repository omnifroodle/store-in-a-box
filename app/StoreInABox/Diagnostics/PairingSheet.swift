import AVFoundation
import SwiftUI
import UIKit

/// Pairing: scan the box's QR with the camera, or paste its text (the simulator has no camera). Either way the text
/// goes to `AppModel.pair`, which refuses a malformed payload.
struct PairingSheet: View {
    let onPayload: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    private let hasCamera = AVCaptureDevice.default(for: .video) != nil

    var body: some View {
        NavigationStack {
            Form {
                if hasCamera {
                    Section("Scan the box's pairing QR") {
                        QRScannerView(onCode: onPayload)
                            .frame(height: 280)
                            .listRowInsets(EdgeInsets())
                    }
                }
                Section("Or paste the pairing text") {
                    TextEditor(text: $text)
                        .font(.system(.footnote, design: .monospaced))
                        .frame(minHeight: 140)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .accessibilityIdentifier("pairing-text")
                    Button("Paste from clipboard") { text = UIPasteboard.general.string ?? "" }
                    Button("Pair") { onPayload(text) }.disabled(text.isEmpty)
                }
            }
            .navigationTitle("Pair")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
        }
    }
}

/// A camera preview that reports the first QR code it reads. WS6 reuses it for unit QRs.
struct QRScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> Scanner {
        let scanner = Scanner()
        scanner.onCode = onCode
        return scanner
    }

    func updateUIViewController(_ scanner: Scanner, context: Context) { scanner.onCode = onCode }

    final class Scanner: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
        var onCode: ((String) -> Void)?
        private let session = AVCaptureSession()
        private var reported = false

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

        override func viewWillAppear(_ animated: Bool) {
            super.viewWillAppear(animated)
            let session = session
            DispatchQueue.global(qos: .userInitiated).async { session.startRunning() }
        }

        override func viewWillDisappear(_ animated: Bool) {
            super.viewWillDisappear(animated)
            session.stopRunning()
        }

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject],
                            from connection: AVCaptureConnection) {
            guard !reported, let code = objects.compactMap({ ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }).first
            else { return }
            reported = true
            onCode?(code)
        }
    }
}
