import AppKit
let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:1200,pixelsHigh:260,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
NSColor.white.setFill()
NSRect(x:0,y:0,width:1200,height:260).fill()
let attributes: [NSAttributedString.Key:Any]=[.font:NSFont.systemFont(ofSize:58),.foregroundColor:NSColor.black]
("NOESIS TEST 2026" as NSString).draw(at:NSPoint(x:40,y:145),withAttributes:attributes)
("中文识别 测试文字" as NSString).draw(at:NSPoint(x:40,y:50),withAttributes:attributes)
try bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:CommandLine.arguments[1]))
