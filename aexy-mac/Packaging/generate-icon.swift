// Generates Resources/AppIcon.icns — a simple branded mark (rounded purple
// square + white "A"). Headless CoreGraphics (no WindowServer needed), so it
// runs in CI: `swift Packaging/generate-icon.swift`.
import Foundation
import CoreGraphics
import CoreText
import ImageIO
import UniformTypeIdentifiers

let here = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let iconset = here.appendingPathComponent("AppIcon.iconset")
try? FileManager.default.removeItem(at: iconset)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func render(_ px: Int) -> CGImage {
    let space = CGColorSpaceCreateDeviceRGB()
    let ctx = CGContext(
        data: nil, width: px, height: px, bitsPerComponent: 8, bytesPerRow: 0,
        space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    )!
    let rect = CGRect(x: 0, y: 0, width: px, height: px)
    // Rounded square background.
    let inset = CGFloat(px) * 0.06
    let radius = CGFloat(px) * 0.22
    let bg = CGPath(
        roundedRect: rect.insetBy(dx: inset, dy: inset),
        cornerWidth: radius, cornerHeight: radius, transform: nil
    )
    ctx.addPath(bg)
    ctx.setFillColor(CGColor(red: 0.42, green: 0.30, blue: 0.93, alpha: 1)) // Aexy purple
    ctx.fillPath()

    // Centered white "A".
    let size = CGFloat(px) * 0.6
    let font = CTFontCreateWithName("Helvetica-Bold" as CFString, size, nil)
    let attrs: [NSAttributedString.Key: Any] = [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String):
            CGColor(red: 1, green: 1, blue: 1, alpha: 1),
    ]
    let line = CTLineCreateWithAttributedString(NSAttributedString(string: "A", attributes: attrs))
    let bounds = CTLineGetImageBounds(line, ctx)
    ctx.textPosition = CGPoint(
        x: (CGFloat(px) - bounds.width) / 2 - bounds.minX,
        y: (CGFloat(px) - bounds.height) / 2 - bounds.minY
    )
    CTLineDraw(line, ctx)
    return ctx.makeImage()!
}

func write(_ image: CGImage, _ name: String) {
    let url = iconset.appendingPathComponent(name)
    let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dest, image, nil)
    CGImageDestinationFinalize(dest)
}

for base in [16, 32, 128, 256, 512] {
    write(render(base), "icon_\(base)x\(base).png")
    write(render(base * 2), "icon_\(base)x\(base)@2x.png")
}

// iconset → icns
let p = Process()
p.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
p.arguments = ["-c", "icns", iconset.path, "-o", here.appendingPathComponent("Resources/AppIcon.icns").path]
try FileManager.default.createDirectory(at: here.appendingPathComponent("Resources"), withIntermediateDirectories: true)
try p.run()
p.waitUntilExit()
try? FileManager.default.removeItem(at: iconset)
print(p.terminationStatus == 0 ? "✓ Resources/AppIcon.icns" : "icns generation failed")
