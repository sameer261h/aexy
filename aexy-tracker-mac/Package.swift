// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "AexyTracker",
    platforms: [.macOS(.v13)],
    targets: [
        // Platform-free-ish core: capture model, buffer, uploader, scheduler.
        // Depends on AppKit/CoreGraphics for collectors but holds no UI.
        .target(name: "AexyTrackerCore"),
        // Menu-bar app entry point.
        .executableTarget(
            name: "AexyTracker",
            dependencies: ["AexyTrackerCore"]
        ),
        .testTarget(
            name: "AexyTrackerCoreTests",
            dependencies: ["AexyTrackerCore"]
        ),
    ]
)
