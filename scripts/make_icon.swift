// Render noesis/assets/icon.svg into noesis/assets/NOESIS.icns (run after editing the SVG).
import AppKit

let assets = URL(fileURLWithPath: CommandLine.arguments[1])
guard let svg = NSImage(contentsOf: assets.appendingPathComponent("icon.svg")) else { fatalError("cannot load icon.svg") }
let set = FileManager.default.temporaryDirectory.appendingPathComponent("NOESIS.iconset")
try? FileManager.default.removeItem(at: set)
try FileManager.default.createDirectory(at: set, withIntermediateDirectories: true)
for base in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let px = base * scale
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                                   samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        svg.draw(in: NSRect(x: 0, y: 0, width: px, height: px))
        NSGraphicsContext.restoreGraphicsState()
        let name = scale == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
        try rep.representation(using: .png, properties: [:])!.write(to: set.appendingPathComponent(name))
    }
}
let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
task.arguments = ["-c", "icns", set.path, "-o", assets.appendingPathComponent("NOESIS.icns").path]
try task.run(); task.waitUntilExit()
exit(task.terminationStatus)
