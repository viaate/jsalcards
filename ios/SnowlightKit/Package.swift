// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SnowlightKit",
    platforms: [.iOS("26.0")],
    products: [.library(name: "SnowlightKit", targets: ["SnowlightKit"])],
    dependencies: [.package(path: "../SnowlightCore")],
    targets: [
        .target(
            name: "SnowlightKit",
            dependencies: [.product(name: "SnowlightCore", package: "SnowlightCore")],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
