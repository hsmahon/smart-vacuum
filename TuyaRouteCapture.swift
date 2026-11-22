import Darwin
import Foundation

/// Keep this object alive in the signed-in app while recording.
/// Create it, start it, and stop it on the main thread.
final class TuyaRouteCapture: NSObject, ThingSmartSweeperDeviceDelegate {
    enum CaptureError: Error {
        case fileAlreadyExists
        case deviceUnavailable
    }

    private struct Packet: Encodable {
        let received_at: String
        let frame_hex: String
    }

    private let sweeper: ThingSmartSweeperDevice
    private let output: FileHandle
    private let writer = DispatchQueue(label: "routeCapture.writer")
    private let clock = ISO8601DateFormatter()
    private let encoder = JSONEncoder()
    private var recording = false
    private var finished = false
    private let onError: (Error) -> Void

    init(deviceID: String, outputURL: URL, onError: @escaping (Error) -> Void) throws {
        guard let sweeper = ThingSmartSweeperDevice(deviceId: deviceID) else {
            throw CaptureError.deviceUnavailable
        }
        // An exclusive open prevents accidentally overwriting an earlier run.
        let fd = try Self.openCapture(at: outputURL)
        self.sweeper = sweeper
        self.output = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        self.onError = onError
        super.init()
        clock.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        sweeper.delegate = self
    }

    private static func openCapture(at url: URL) throws -> Int32 {
        let descriptor = url.withUnsafeFileSystemRepresentation { path -> Int32 in
            guard let path = path else { return -1 }
            return Darwin.open(path, O_WRONLY | O_CREAT | O_EXCL, S_IRUSR | S_IWUSR)
        }
        guard descriptor >= 0 else {
            let error = errno
            if error == EEXIST { throw CaptureError.fileAlreadyExists }
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(error))
        }
        return descriptor
    }

    func start() {
        let shouldSubscribe = writer.sync {
            guard !recording && !finished else { return false }
            recording = true
            return true
        }
        if shouldSubscribe { sweeper.subscribeDeviceDataTransfer() }
    }

    func stop() throws {
        sweeper.unsubscribeDeviceDataTransfer()
        sweeper.delegate = nil
        try writer.sync {
            guard !finished else { return }
            recording = false
            finished = true
            try output.close()
        }
    }

    func sweeperDevice(_ sweeperDevice: ThingSmartSweeperDevice, didReceiveStreamData data: Data) {
        let receivedAt = Date()
        writer.async {
            guard self.recording else { return }
            do {
                let packet = Packet(
                    received_at: self.clock.string(from: receivedAt),
                    frame_hex: data.map { String(format: "%02x", $0) }.joined()
                )
                var line = try self.encoder.encode(packet)
                line.append(0x0a)
                try self.output.write(contentsOf: line)
            } catch {
                self.recording = false
                DispatchQueue.main.async { self.onError(error) }
            }
        }
    }
}
