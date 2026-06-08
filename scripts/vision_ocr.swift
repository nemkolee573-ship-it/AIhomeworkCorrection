import AppKit
import Foundation
import PDFKit
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

struct OCRResult {
    var text: String
    var lines: [[String: Any]]
    var averageConfidence: Double
}

func recognize(cgImage: CGImage) throws -> OCRResult {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.minimumTextHeight = 0.01

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    try handler.perform([request])

    let observations = request.results ?? []
    var lines: [[String: Any]] = []
    var confidenceSum = 0.0
    var count = 0.0

    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        let confidence = Double(candidate.confidence)
        confidenceSum += confidence
        count += 1
        lines.append([
            "text": candidate.string,
            "confidence": confidence
        ])
    }

    let text = lines.compactMap { $0["text"] as? String }.joined(separator: "\n")
    let average = count > 0 ? confidenceSum / count : 0
    return OCRResult(text: text, lines: lines, averageConfidence: average)
}

func imageToCGImage(_ image: NSImage) -> CGImage? {
    var rect = CGRect(origin: .zero, size: image.size)
    return image.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func renderPDFPage(_ page: PDFPage, scale: CGFloat = 3.0) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let width = Int(bounds.width * scale)
    let height = Int(bounds.height * scale)
    guard width > 0, height > 0 else { return nil }

    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return nil
    }

    context.setFillColor(NSColor.white.cgColor)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    return context.makeImage()
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

func splitWidePageForReading(_ image: CGImage) -> [(String, CGImage)] {
    let contentRect = contentBoundingBox(image)
    let trimmed = image.cropping(to: contentRect) ?? image
    let width = trimmed.width
    let height = trimmed.height
    guard width > Int(Double(height) * 1.15) else {
        return [("", trimmed)]
    }

    let splitX = bestVerticalSplitX(trimmed)
    let leftRect = CGRect(x: 0, y: 0, width: splitX, height: height)
    let rightRect = CGRect(x: splitX, y: 0, width: width - splitX, height: height)
    var chunks: [(String, CGImage)] = []
    if let left = trimmed.cropping(to: leftRect) {
        chunks.append(("左页", left))
    }
    if let right = trimmed.cropping(to: rightRect) {
        chunks.append(("右页", right))
    }
    return chunks.isEmpty ? [("", trimmed)] : chunks
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    fail("usage: swift vision_ocr.swift [--json] <image-or-pdf>")
}

let jsonMode = args.contains("--json")
let pathArg = args.last!
let url = URL(fileURLWithPath: pathArg)
let ext = url.pathExtension.lowercased()
var chunks: [String] = []
var allLines: [[String: Any]] = []
var confidenceSum = 0.0
var confidenceCount = 0.0

do {
    if ext == "pdf" {
        guard let document = PDFDocument(url: url) else {
            fail("无法读取 PDF 文件")
        }

        for index in 0..<document.pageCount {
            guard let page = document.page(at: index), let cgImage = renderPDFPage(page) else {
                continue
            }
            for (label, pageImage) in splitWidePageForReading(cgImage) {
                let result = try recognize(cgImage: pageImage)
                if !result.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    let pageLabel = label.isEmpty ? "第 \(index + 1) 页" : "第 \(index + 1) 页（\(label)）"
                    chunks.append(pageLabel + "\n" + result.text)
                    for var line in result.lines {
                        line["page"] = pageLabel
                        allLines.append(line)
                    }
                    confidenceSum += result.averageConfidence * Double(result.lines.count)
                    confidenceCount += Double(result.lines.count)
                }
            }
        }
    } else {
        guard let image = NSImage(contentsOf: url), let cgImage = imageToCGImage(image) else {
            fail("无法读取图片文件")
        }
        let result = try recognize(cgImage: cgImage)
        chunks.append(result.text)
        allLines.append(contentsOf: result.lines)
        confidenceSum += result.averageConfidence * Double(result.lines.count)
        confidenceCount += Double(result.lines.count)
    }
} catch {
    fail("OCR 失败：\(error.localizedDescription)")
}

let text = chunks.joined(separator: "\n\n")
let averageConfidence = confidenceCount > 0 ? confidenceSum / confidenceCount : 0

if jsonMode {
    let payload: [String: Any] = [
        "text": text,
        "average_confidence": averageConfidence,
        "line_count": allLines.count,
        "low_confidence_count": allLines.filter {
            guard let value = $0["confidence"] as? Double else { return false }
            return value < 0.65
        }.count,
        "lines": allLines
    ]
    let data = try JSONSerialization.data(withJSONObject: payload, options: [])
    print(String(data: data, encoding: .utf8)!)
} else {
    print(text)
}
