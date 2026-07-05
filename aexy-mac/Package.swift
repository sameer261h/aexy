// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Aexy",
    platforms: [.macOS(.v13)],
    dependencies: [
        // Self-update framework (Sparkle 2). Guarded by `#if canImport(Sparkle)`
        // in source so the app still builds if this can't be resolved offline.
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.6.0"),
    ],
    targets: [
        // Platform-free-ish core: capture model, buffer, uploader, scheduler.
        // Depends on AppKit/CoreGraphics for collectors but holds no UI.
        .target(name: "AexyCore"),
        // Menu-bar app entry point.
        .executableTarget(
            name: "Aexy",
            dependencies: [
                "AexyCore",
                .product(name: "Sparkle", package: "Sparkle"),
            ]
        ),
        .testTarget(
            name: "AexyCoreTests",
            dependencies: ["AexyCore"]
        ),
    ]
)
