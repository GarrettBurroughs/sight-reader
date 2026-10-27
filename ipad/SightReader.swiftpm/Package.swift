// swift-tools-version: 5.9

// Swift Playgrounds app project. Open this .swiftpm folder in Swift Playgrounds on the iPad.

import PackageDescription
import AppleProductTypes

let package = Package(
    name: "SightReader",
    platforms: [
        .iOS("16.0")
    ],
    products: [
        .iOSApplication(
            name: "SightReader",
            targets: ["AppModule"],
            bundleIdentifier: "com.garrettburroughs.SightReader",
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .music),
            accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [
                .pad
            ],
            supportedInterfaceOrientations: [
                .landscapeRight,
                .landscapeLeft,
                .portrait,
                .portraitUpsideDown
            ],
            capabilities: [
                // Lets the shell load the dev server from the PC over Wi-Fi.
                .localNetwork(purposeString: "Load the practice app from my PC.")
            ]
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: "."
        )
    ]
)
