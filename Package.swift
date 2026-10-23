// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "PDF", platforms: [.macOS(.v15)], products: [.executable(name: "PDF", targets: ["PDF"])], targets: [.executableTarget(name: "PDF")], swiftLanguageModes: [.v5])
