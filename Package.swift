// swift-tools-version: 6.2
import PackageDescription
let package = Package(name: "PDF", platforms: [.macOS(.v26)], products: [.executable(name: "PDF", targets: ["PDF"])], targets: [.executableTarget(name: "PDF")], swiftLanguageModes: [.v5])
