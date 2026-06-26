import Foundation
import Speech

// macspeech-helper — on-device Apple Speech transcription helper.
//
// This binary is meant to run INSIDE a `MacSpeech.app` bundle launched via
// LaunchServices (`open -W -n MacSpeech.app --args ...`). Launching the bare
// binary directly hard-crashes on the TCC check (missing
// NSSpeechRecognitionUsageDescription) because a directly-exec'd binary's
// responsible process resolves to the shell, which has no usage string. Only
// `open` makes the .app its own responsible process. The .app's Info.plist
// (AppInfo.plist) supplies NSSpeechRecognitionUsageDescription.
//
// `open` discards stdout, so results/errors are written to an output-file path
// passed as an argument; the Python wrapper reads that file.
//
// Modes:
//   1. Status (passive, never prompts):
//        macspeech-helper --status <out.json>
//      Writes {"authorizationStatus": <rawValue>} where
//      0=notDetermined, 1=denied, 2=restricted, 3=authorized.
//
//   2. Transcribe:
//        macspeech-helper <audio> <locale> <out.json> \
//          [--contextual-strings-file <path>] [--punctuation 0|1] [--timeout <seconds>]
//      Writes {"transcript": <str>, "words": [{text,start,end,confidence}, ...]}.
//      On any failure writes {"error": <str>} and exits non-zero.
//      The internal watchdog deadline tracks --timeout (the caller's value) so a
//      long transcription is never silently capped; it defaults to 300s.

let rawArgs = CommandLine.arguments

func writeResult(_ obj: [String: Any], to outPath: String, exitCode: Int32) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
    let str = String(data: data, encoding: .utf8)!
    if outPath.isEmpty {
        let handle = exitCode == 0 ? FileHandle.standardOutput : FileHandle.standardError
        handle.write((str + "\n").data(using: .utf8)!)
    } else {
        try? str.write(toFile: outPath, atomically: true, encoding: .utf8)
    }
    exit(exitCode)
}

// ---- Status mode: passive authorization read, never calls requestAuthorization ----
if rawArgs.count >= 2 && rawArgs[1] == "--status" {
    let outPath = rawArgs.count >= 3 ? rawArgs[2] : ""
    let status = SFSpeechRecognizer.authorizationStatus()
    writeResult(["authorizationStatus": status.rawValue], to: outPath, exitCode: 0)
}

// ---- Transcribe mode ----
// Positional: <audio> <locale> <out.json>; then optional named flags.
let audioPath = rawArgs.count >= 2 ? rawArgs[1] : ""
let localeId = rawArgs.count >= 3 ? rawArgs[2] : "en-US"
let outPath = rawArgs.count >= 4 ? rawArgs[3] : ""

var contextualStringsFile = ""
var addsPunctuation = true
var timeoutSeconds: Double = 300

var idx = 4
while idx < rawArgs.count {
    let arg = rawArgs[idx]
    switch arg {
    case "--contextual-strings-file":
        if idx + 1 < rawArgs.count {
            contextualStringsFile = rawArgs[idx + 1]
            idx += 2
        } else {
            idx += 1
        }
    case "--punctuation":
        if idx + 1 < rawArgs.count {
            addsPunctuation = rawArgs[idx + 1] != "0"
            idx += 2
        } else {
            idx += 1
        }
    case "--timeout":
        if idx + 1 < rawArgs.count, let parsed = Double(rawArgs[idx + 1]), parsed > 0 {
            timeoutSeconds = parsed
            idx += 2
        } else {
            idx += 1
        }
    default:
        idx += 1
    }
}

func fail(_ msg: String) -> Never { writeResult(["error": msg], to: outPath, exitCode: 2) }

guard !audioPath.isEmpty else { fail("usage: macspeech-helper <audio-file> <locale> <out-json-path> [--contextual-strings-file <path>] [--punctuation 0|1]") }
guard FileManager.default.fileExists(atPath: audioPath) else { fail("audio file not found: \(audioPath)") }

// Load contextual strings (one phrase per line) if a file was supplied.
var contextualStrings: [String] = []
if !contextualStringsFile.isEmpty {
    guard let raw = try? String(contentsOfFile: contextualStringsFile, encoding: .utf8) else {
        fail("contextual-strings file not readable: \(contextualStringsFile)")
    }
    contextualStrings = raw
        .split(whereSeparator: { $0 == "\n" || $0 == "\r" })
        .map { $0.trimmingCharacters(in: .whitespaces) }
        .filter { !$0.isEmpty }
}

func transcribe() {
    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeId)) else { fail("no recognizer for locale \(localeId)") }
    guard recognizer.isAvailable else { fail("recognizer unavailable for \(localeId)") }
    let request = SFSpeechURLRecognitionRequest(url: URL(fileURLWithPath: audioPath))
    request.shouldReportPartialResults = false

    if !contextualStrings.isEmpty {
        request.contextualStrings = contextualStrings
    }

    if #available(macOS 13.0, *) {
        request.addsPunctuation = addsPunctuation
    }

    if recognizer.supportsOnDeviceRecognition {
        request.requiresOnDeviceRecognition = true
    } else {
        fail("on-device recognition not supported for \(localeId)")
    }

    recognizer.recognitionTask(with: request) { result, error in
        if let error = error { fail("recognition error: \(error.localizedDescription)") }
        guard let result = result, result.isFinal else { return }
        let transcription = result.bestTranscription
        var words: [[String: Any]] = []
        for seg in transcription.segments {
            words.append([
                "text": seg.substring,
                "start": seg.timestamp,
                "end": seg.timestamp + seg.duration,
                "confidence": seg.confidence,
            ])
        }
        writeResult(["transcript": transcription.formattedString, "words": words], to: outPath, exitCode: 0)
    }
}

SFSpeechRecognizer.requestAuthorization { status in
    guard status == .authorized else {
        fail("Speech Recognition not authorized (status=\(status.rawValue)). Grant access in System Settings > Privacy & Security > Speech Recognition.")
    }
    transcribe()
}

DispatchQueue.main.asyncAfter(deadline: .now() + timeoutSeconds) {
    fail("recognition timed out after \(Int(timeoutSeconds))s (no grant?)")
}
RunLoop.main.run()
