// Records only one application's windows on the main display, with no cursor, to an H.264 MP4.
//
// usage: swift screen_capture.swift OUTPUT FPS WIDTH HEIGHT BUNDLE_ID
//
// ScreenCaptureKit composites just the windows of BUNDLE_ID (PowerPoint), so nothing another
// process draws -- a system prompt, a notification, the Dock, the menu bar, the screen-recording
// indicator, another app's window -- can reach the recording. Frames are written at a constant
// FPS; when the screen is idle the last image repeats.
//
// stderr carries `firstFrameEpochMs=<ms>` once the first frame is written (the wall-clock time
// of the recording's t=0) and `captureComplete` after the file is finalized. The recording
// stops on `q` or end of file on stdin, or on SIGINT.
import AVFoundation
import CoreMedia
import Darwin
import Foundation
import ScreenCaptureKit

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("ScreenCaptureKit: \(message)\n".utf8))
    exit(1)
}

let encoderTimeout = 5.0

final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
    let queue = DispatchQueue(label: "powerpoint-slide-recorder.capture")
    let fps: Int32
    let width: Int
    let height: Int
    let bundleID: String
    let writer: AVAssetWriter
    var input: AVAssetWriterInput!
    var adaptor: AVAssetWriterInputPixelBufferAdaptor!
    var stream: SCStream!
    var first: CMTime?
    var lastBuffer: CVPixelBuffer?
    var nextFrame: Int64 = 0
    var pending: [(CMTime, CVPixelBuffer)] = []
    var frameTimer: DispatchSourceTimer?
    var stopping = false
    var stopRequested = false

    init(path: String, fps: Int32, width: Int, height: Int, bundleID: String) throws {
        self.fps = fps
        self.width = width
        self.height = height
        self.bundleID = bundleID
        writer = try AVAssetWriter(outputURL: URL(fileURLWithPath: path), fileType: .mp4)
        super.init()
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first(where: { $0.displayID == CGMainDisplayID() }) else { fail("main display unavailable") }
        let apps = content.applications.filter { $0.bundleIdentifier == bundleID }
        guard !apps.isEmpty else { fail("\(bundleID) is not running") }
        let configuration = SCStreamConfiguration()
        configuration.width = width
        configuration.height = height
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: fps)
        configuration.showsCursor = false
        configuration.queueDepth = 8
        configuration.pixelFormat = kCVPixelFormatType_32BGRA
        configuration.capturesAudio = false
        input = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width, AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [AVVideoExpectedSourceFrameRateKey: fps,
                AVVideoAllowFrameReorderingKey: false, AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
                AVVideoAverageBitRateKey: 20_000_000],
        ])
        input.expectsMediaDataInRealTime = true
        guard writer.canAdd(input) else { fail("cannot configure H.264 writer") }
        writer.add(input)
        adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
        guard writer.startWriting() else { fail("writer start: \(String(describing: writer.error))") }
        writer.startSession(atSourceTime: .zero)
        let filter = SCContentFilter(display: display, including: apps, exceptingWindows: [])
        stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try await stream.startCapture()
    }

    func append(_ buffer: CVPixelBuffer) {
        let deadline = ProcessInfo.processInfo.systemUptime + encoderTimeout
        while !input.isReadyForMoreMediaData {
            if writer.status == .failed || ProcessInfo.processInfo.systemUptime >= deadline { fail("encoder stalled at frame \(nextFrame): \(String(describing: writer.error))") }
            usleep(1000)
        }
        guard adaptor.append(buffer, withPresentationTime: CMTime(value: nextFrame, timescale: fps)) else {
            fail("encoder append: \(String(describing: writer.error))")
        }
        nextFrame += 1
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, !stopping, CMSampleBufferIsValid(sampleBuffer),
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let status = attachments.first?[.status] as? Int, status == SCFrameStatus.complete.rawValue,
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        guard let clock = stream.synchronizationClock else { fail("stream synchronization clock unavailable") }
        let pts = CMSyncConvertTime(CMSampleBufferGetPresentationTimeStamp(sampleBuffer), from: clock, to: CMClockGetHostTimeClock())
        guard pts.isValid, !pts.isIndefinite else { fail("invalid frame presentation time") }
        if first == nil {
            first = pts
            let hostNow = CMClockGetTime(CMClockGetHostTimeClock())
            let epoch = Date().timeIntervalSince1970 - CMTimeGetSeconds(hostNow - pts)
            append(buffer)
            FileHandle.standardError.write(Data("firstFrameEpochMs=\(Int64((epoch * 1000).rounded()))\n".utf8))
            lastBuffer = buffer
            let timer = DispatchSource.makeTimerSource(queue: queue)
            let delay = max(0, CMTimeGetSeconds(pts - CMClockGetTime(CMClockGetHostTimeClock()))) + 1 / Double(fps)
            timer.schedule(deadline: .now() + delay, repeating: 1 / Double(fps))
            timer.setEventHandler { self.emitFrames(until: CMClockGetTime(CMClockGetHostTimeClock()), includeCurrent: true) }
            frameTimer = timer
            timer.resume()
        } else {
            pending.append((pts, buffer))
        }
    }

    func emitFrames(until time: CMTime, includeCurrent: Bool) {
        guard let first = first else { return }
        let elapsed = CMTimeConvertScale(time - first, timescale: fps, method: includeCurrent ? .roundTowardNegativeInfinity : .roundTowardPositiveInfinity)
        let end = elapsed.value + (includeCurrent ? 1 : 0)
        while nextFrame < end {
            let presentation = first + CMTime(value: nextFrame, timescale: fps)
            while let sample = pending.first, sample.0 <= presentation {
                lastBuffer = sample.1
                pending.removeFirst()
            }
            guard let buffer = lastBuffer else { fail("frame clock has no native image") }
            append(buffer)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) { fail("stream stopped: \(error)") }

    func stop() async {
        let proceed = queue.sync { () -> Bool in
            if stopRequested { return false }
            stopRequested = true
            return true
        }
        guard proceed else { return }
        let requestedAt = CMClockGetTime(CMClockGetHostTimeClock())
        queue.sync {
            stopping = true
            frameTimer?.cancel()
            frameTimer = nil
            guard first != nil else { fail("stopped without a complete frame") }
            emitFrames(until: requestedAt, includeCurrent: false)
            input.markAsFinished()
        }
        do { try await stream.stopCapture() } catch { fail("stop: \(error)") }
        await writer.finishWriting()
        guard writer.status == .completed else { fail("finalization: \(String(describing: writer.error))") }
        FileHandle.standardError.write(Data("captureComplete\n".utf8))
        exit(0)
    }
}

let arguments = CommandLine.arguments
guard arguments.count == 6, let fps = Int32(arguments[2]), fps > 0,
      let width = Int(arguments[3]), width > 0, let height = Int(arguments[4]), height > 0 else {
    fail("usage: screen_capture.swift OUTPUT FPS WIDTH HEIGHT BUNDLE_ID")
}
let recorder: Recorder
do { recorder = try Recorder(path: arguments[1], fps: fps, width: width, height: height, bundleID: arguments[5]) } catch { fail("writer: \(error)") }
signal(SIGINT, SIG_IGN)
let interrupt = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
interrupt.setEventHandler { Task { await recorder.stop() } }
interrupt.resume()
Thread {
    // `q` or end of input stops the recording, the same contract ffmpeg's stdin has.
    while true {
        let data = FileHandle.standardInput.availableData
        if data.isEmpty || data.contains(UInt8(ascii: "q")) { break }
    }
    Task { await recorder.stop() }
}.start()
Task { do { try await recorder.start() } catch { fail("start: \(error)") } }
RunLoop.main.run()
