// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SnowlightCore",
    platforms: [.iOS("26.0"), .macOS("14.0")],
    products: [.library(name: "SnowlightCore", targets: ["SnowlightCore"])],
    targets: [
        .target(
            name: "SnowlightCore",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "SnowlightCoreTests",
            dependencies: ["SnowlightCore"],
            resources: [.copy("Fixtures")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
