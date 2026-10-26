import Foundation
import AppKit
import Vision

let started = ProcessInfo.processInfo.systemUptime
func fail() -> Never {
    FileHandle.standardError.write(Data("OCR failed\n".utf8))
    exit(1)
}
guard CommandLine.arguments.count == 2,
      let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fail() }
let bitmap = NSBitmapImageRep(cgImage: cg)
var minimum = 1.0, maximum = 0.0
for y in stride(from: 0, to: bitmap.pixelsHigh, by: max(1, bitmap.pixelsHigh / 40)) {
    for x in stride(from: 0, to: bitmap.pixelsWide, by: max(1, bitmap.pixelsWide / 40)) {
        if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB) {
            let light = (color.redComponent + color.greenComponent + color.blueComponent) / 3
            minimum = min(minimum, light); maximum = max(maximum, light)
        }
    }
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([request]) } catch { fail() }
struct Line {
    var text: String
    var x: Double
    var y: Double
    var w: Double
    var h: Double
    var confidence: Float
}
let lines: [Line] = (request.results ?? []).compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    return Line(text: candidate.string, x: box.minX, y: 1 - box.maxY,
                w: box.width, h: box.height, confidence: candidate.confidence)
}
var rows: [[Line]] = []
for line in lines.sorted(by: { $0.y < $1.y }) {
    if let index = rows.firstIndex(where: { abs($0[0].y - line.y) <= min($0[0].h, line.h) / 2 }) {
        rows[index].append(line)
    } else { rows.append([line]) }
}
let ordered = rows.flatMap { $0.sorted(by: { $0.x < $1.x }) }
let output: [String: Any] = [
    "text": ordered.map { $0.text }.joined(separator: "\n"),
    "lines": ordered.map { ["text": $0.text, "bbox": [$0.x, $0.y, $0.w, $0.h], "confidence": $0.confidence] as [String: Any] },
    "ms": Int((ProcessInfo.processInfo.systemUptime - started) * 1000),
    "uniform": maximum - minimum < 0.015
]
do {
    let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch { fail() }
