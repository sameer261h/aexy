// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Aexy",
    platforms: [.macOS(.v13)],
    targets: [
        // Platform-free-ish core: capture model, buffer, uploader, scheduler.
        // Depends on AppKit/CoreGraphics for collectors but holds no UI.
        .target(name: "AexyCore"),
        // Menu-bar app entry point.
        .executableTarget(
            name: "Aexy",
            dependencies: ["AexyCore"]
        ),
        .testTarget(
            name: "AexyCoreTests",
            dependencies: ["AexyCore"]
        ),
    ]
)
