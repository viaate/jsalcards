// The machine probe: one screen of the picture tour that answers a question about the
// machine, not about the app. Debug builds only, and reachable only through the tour
// (a launch with -tour.screen probe).
//
// The question: does a Metal view show in a picture of the simulator's screen on a hosted
// Mac? The map will be drawn with Metal, so the answer decides whether the map can be
// judged from such pictures at all.
//
// What the screen holds:
//
//   - the top half of the screen is a Metal view, cleared to one teal (#12a594, the app's
//     light `chance` color, the same in both looks) and presented once: one frame, then
//     the view is paused and never draws again, as a map at rest would be;
//   - in the middle of that half, over the Metal view: one button in the system's glass
//     style and one label with the glass effect, each a system symbol and no word;
//   - the lower half is the page color.
//
// What it writes in place of words, to Documents/tour/<picture>.txt:
//
//     metal device: <the device's name>     or     metal device: none
//     drawable presented: yes               or     drawable presented: no
//
// "yes" means: the view handed over a drawable, the drawable was sent to be presented,
// and the frame's commands completed. Whether the teal then shows in the picture is not
// something the app can know: a script outside reads the picture's color at a point of
// the top half, away from the middle (ios/tools/pixels.swift).
//
// Both lines are facts about the machine. They are printed and uploaded, and never
// compared with a committed file.

#if DEBUG

import Foundation
import Metal
import MetalKit
import SnowlightCore
import SwiftUI
import UIKit

/// The probe screen. It stands in place of the shell on the one launch that asks for it.
struct MetalProbeScreen: View {
    let plan: TourPlan

    var body: some View {
        GeometryReader { space in
            VStack(spacing: 0) {
                MetalSurface()
                    .frame(height: space.size.height / 2)
                    .overlay {
                        GlassPair()
                    }
                Color.token(.page)
            }
        }
        .ignoresSafeArea()
        .onAppear {
            guard Tour.begin() else {
                return
            }
            UIView.setAnimationsEnabled(false)
            MetalProbe.begin(for: plan)
        }
    }
}

/// The two glass controls, side by side. Neither holds a word, and the button does nothing.
struct GlassPair: View {
    var body: some View {
        HStack(spacing: 28) {
            Button {
                // Nothing: the button is here to be looked at.
            } label: {
                Image(systemName: "snowflake")
                    .font(.title2)
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.glass)
            Image(systemName: "cloud.snow")
                .font(.title2)
                .frame(width: 56, height: 56)
                .glassEffect()
        }
    }
}

/// The Metal view, as SwiftUI holds it.
struct MetalSurface: UIViewRepresentable {
    func makeCoordinator() -> ProbeRenderer {
        ProbeRenderer(device: MetalProbe.device)
    }

    func makeUIView(context: Context) -> MTKView {
        let view = MTKView(frame: .zero, device: MetalProbe.device)
        view.clearColor = MetalProbe.teal
        // Eight plain bits a channel, so the bytes cleared are the color's own.
        view.colorPixelFormat = .bgra8Unorm
        view.isUserInteractionEnabled = false
        // The view only holds its delegate weakly; SwiftUI keeps the coordinator alive.
        view.delegate = context.coordinator
        return view
    }

    func updateUIView(_ view: MTKView, context: Context) {
        // Nothing changes after the view is made.
    }
}

/// Draws the Metal view's one frame: a clear to the view's color, presented once. On the
/// main actor, as the view and both of its delegate's calls are.
@MainActor
final class ProbeRenderer: NSObject, MTKViewDelegate {
    private let queue: (any MTLCommandQueue)?
    private var sent = false
    private var asked = 0

    init(device: (any MTLDevice)?) {
        queue = device?.makeCommandQueue()
        super.init()
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {
        // Nothing to do: the one frame is a plain clear, whatever its size.
    }

    /// The view asks for a frame on every tick of the screen until it is paused. The
    /// first time a drawable is there, it is cleared and sent to be presented, and the
    /// view is paused for good.
    func draw(in view: MTKView) {
        if sent {
            return
        }
        asked += 1
        guard let queue = queue,
              let pass = view.currentRenderPassDescriptor,
              let drawable = view.currentDrawable,
              let buffer = queue.makeCommandBuffer(),
              let encoder = buffer.makeRenderCommandEncoder(descriptor: pass) else {
            return
        }
        // No shape is drawn. Ending the pass is what clears the drawable to the color.
        encoder.endEncoding()
        buffer.present(drawable)
        // Called on a thread of Metal's own when the frame's commands have ended. It
        // touches nothing of the renderer: it reads how they ended and hands that on.
        buffer.addCompletedHandler { finished in
            let completed = finished.status == .completed
            DispatchQueue.main.async {
                MetalProbe.frameEnded(completed: completed)
            }
        }
        buffer.commit()
        sent = true
        view.isPaused = true
        let size = view.drawableSize
        let width = String(Int(size.width))
        let height = String(Int(size.height))
        Tour.note("one drawable of " + width + " x " + height + " pixels was sent to be presented, on the view's request number " + String(asked))
    }
}

/// What the probe found out, and the one file it writes.
enum MetalProbe {
    /// This machine's Metal device, or nil when it has none. Asked for once.
    static let device: (any MTLDevice)? = MTLCreateSystemDefaultDevice()

    /// #12a594: the same value the script that reads the picture is given.
    static let teal = MTLClearColor(red: 18.0 / 255.0, green: 165.0 / 255.0, blue: 148.0 / 255.0, alpha: 1.0)

    /// How long the file waits for the frame before it says no.
    private static let patience: TimeInterval = 20

    private static var written = false

    /// Called once, when the probe screen appears.
    static func begin(for plan: TourPlan) {
        Tour.note("showing " + plan.screenName + " for the picture " + plan.name)
        Tour.note("the Metal device is " + deviceName)
        // The script outside waits for the file, so it is written even if no frame ever
        // ends: then it says no.
        DispatchQueue.main.asyncAfter(deadline: .now() + MetalProbe.patience) {
            if !MetalProbe.written {
                Tour.note("no frame of the Metal view ended in time")
            }
            MetalProbe.finish(presented: false)
        }
    }

    /// Called on the main thread when the one frame's commands have ended.
    static func frameEnded(completed: Bool) {
        if completed {
            Tour.note("the frame's commands completed")
        } else {
            Tour.note("the frame's commands ended in an error")
        }
        // A little time for the presented drawable to reach the screen, as the other
        // screens of the tour are given before their file is written.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            MetalProbe.finish(presented: completed)
        }
    }

    private static var deviceName: String {
        guard let device = device else {
            return "none"
        }
        return device.name
    }

    /// Writes the two lines, once. What comes later changes nothing.
    private static func finish(presented: Bool) {
        if written {
            return
        }
        guard let plan = TourPlan.ofThisLaunch else {
            return
        }
        written = true
        Tour.write(
            [
                "metal device: " + deviceName,
                "drawable presented: " + (presented ? "yes" : "no"),
            ],
            for: plan
        )
    }
}

#endif
