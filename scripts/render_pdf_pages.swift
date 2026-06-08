import AppKit
import Foundation
import PDFKit

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

func renderPDFPage(_ page: PDFPage, scale: CGFloat = 3.0) -> NSImage? {
    let bounds = page.bounds(for: .mediaBox)
    let size = NSSize(width: bounds.width * scale, height: bounds.height * scale)
    guard size.width > 0, size.height > 0 else { return nil }

    let image = NSImage(size: size)
    image.lockFocus()
    NSColor.white.setFill()
    NSRect(origin: .zero, size: size).fill()
    let context = NSGraphicsContext.current?.cgContext
    context?.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context!)
    image.unlockFocus()
    return image
}

func nsImageToCGImage(_ image: NSImage) -> CGImage? {
    var rect = CGRect(origin: .zero, size: image.size)
    return image.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func cgImageToNSImage(_ image: CGImage) -> NSImage {
    return NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
}

func rgbaBuffer(_ image: CGImage) -> (data: [UInt8], width: Int, height: Int, bytesPerRow: Int)? {
    let width = image.width
    let height = image.height
    let bytesPerRow = width * 4
    var data = [UInt8](repeating: 255, count: bytesPerRow * height)
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: &data,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: bytesPerRow,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return nil
    }
    context.setFillColor(NSColor.white.cgColor)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return (data, width, height, bytesPerRow)
}

func isInk(_ data: [UInt8], _ bytesPerRow: Int, _ x: Int, _ y: Int, threshold: Int = 245) -> Bool {
    let offset = y * bytesPerRow + x * 4
    if offset + 2 >= data.count { return false }
    let red = Int(data[offset])
    let green = Int(data[offset + 1])
    let blue = Int(data[offset + 2])
    let luminance = (red * 299 + green * 587 + blue * 114) / 1000
    return luminance < threshold
}

func contentBoundingBox(_ image: CGImage) -> CGRect {
    guard let buffer = rgbaBuffer(image) else {
        return CGRect(x: 0, y: 0, width: image.width, height: image.height)
    }
    let step = max(2, min(buffer.width, buffer.height) / 900)
    var minX = buffer.width
    var minY = buffer.height
    var maxX = 0
    var maxY = 0
    for y in stride(from: 0, to: buffer.height, by: step) {
        for x in stride(from: 0, to: buffer.width, by: step) {
            if isInk(buffer.data, buffer.bytesPerRow, x, y) {
                minX = min(minX, x)
                minY = min(minY, y)
                maxX = max(maxX, x)
                maxY = max(maxY, y)
            }
        }
    }
    if minX >= maxX || minY >= maxY {
        return CGRect(x: 0, y: 0, width: image.width, height: image.height)
    }
    let pad = max(24, min(buffer.width, buffer.height) / 120)
    let x = max(0, minX - pad)
    let y = max(0, minY - pad)
    let width = min(buffer.width, maxX + pad) - x
    let height = min(buffer.height, maxY + pad) - y
    return CGRect(x: x, y: y, width: width, height: height)
}

func bestVerticalSplitX(_ image: CGImage) -> Int {
    guard let buffer = rgbaBuffer(image) else {
        return image.width / 2
    }
    let start = Int(Double(buffer.width) * 0.35)
    let end = Int(Double(buffer.width) * 0.72)
    let maxY = Int(Double(buffer.height) * 0.88)
    var bestX = buffer.width / 2
    var bestScore = Int.max
    var bestDistance = Int.max
    for x in start..<max(end, start + 1) {
        var score = 0
        for y in stride(from: 0, to: maxY, by: 3) {
            if isInk(buffer.data, buffer.bytesPerRow, x, y, threshold: 230) {
                score += 1
            }
        }
        let distance = abs(x - buffer.width / 2)
        if score < bestScore || (score == bestScore && distance < bestDistance) {
            bestScore = score
            bestDistance = distance
            bestX = x
        }
    }
    return bestX
}

func cropImage(_ image: NSImage, rect: NSRect) -> NSImage? {
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let cgImage = bitmap.cgImage?.cropping(to: CGRect(x: rect.origin.x, y: rect.origin.y, width: rect.width, height: rect.height)) else {
        return nil
    }
    let cropped = NSImage(cgImage: cgImage, size: rect.size)
    return cropped
}

func splitWidePageForReading(_ image: NSImage) -> [(String, NSImage)] {
    guard let cgImage = nsImageToCGImage(image) else {
        return [("", image)]
    }
    let contentRect = contentBoundingBox(cgImage)
    let trimmedCG = cgImage.cropping(to: contentRect) ?? cgImage
    let trimmed = cgImageToNSImage(trimmedCG)
    let width = CGFloat(trimmedCG.width)
    let height = CGFloat(trimmedCG.height)
    guard width > height * 1.15 else {
        return [("", trimmed)]
    }

    let splitX = CGFloat(bestVerticalSplitX(trimmedCG))
    var chunks: [(String, NSImage)] = []
    if let left = cropImage(trimmed, rect: NSRect(x: 0, y: 0, width: splitX, height: height)) {
        chunks.append(("left", left))
    }
    if let right = cropImage(trimmed, rect: NSRect(x: splitX, y: 0, width: width - splitX, height: height)) {
        chunks.append(("right", right))
    }
    return chunks.isEmpty ? [("", trimmed)] : chunks
}

func writePNG(_ image: NSImage, to url: URL) -> Bool {
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let data = bitmap.representation(using: .png, properties: [:]) else {
        return false
    }
    do {
        try data.write(to: url)
        return true
    } catch {
        return false
    }
}

let args = CommandLine.arguments
guard args.count >= 3 else {
    fail("usage: swift render_pdf_pages.swift <pdf> <out-dir> [max-pages] [scale]")
}

let pdfURL = URL(fileURLWithPath: args[1])
let outDir = URL(fileURLWithPath: args[2], isDirectory: true)
let maxPages = args.count >= 4 ? (Int(args[3]) ?? 6) : 6
let renderScale = args.count >= 5 ? (Double(args[4]) ?? 3.0) : 3.0

guard let document = PDFDocument(url: pdfURL) else {
    fail("无法读取 PDF 文件")
}

try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
var outputs: [String] = []
let pageCount = min(document.pageCount, maxPages)

for index in 0..<pageCount {
    guard let page = document.page(at: index),
          let image = renderPDFPage(page, scale: CGFloat(renderScale)) else {
        continue
    }
    for (label, pageImage) in splitWidePageForReading(image) {
        let suffix = label.isEmpty ? "" : "-\(label)"
        let outputURL = outDir.appendingPathComponent(String(format: "page-%03d%@.png", index + 1, suffix))
        if writePNG(pageImage, to: outputURL) {
            outputs.append(outputURL.path)
        }
    }
}

let data = try JSONSerialization.data(withJSONObject: outputs, options: [])
print(String(data: data, encoding: .utf8)!)
