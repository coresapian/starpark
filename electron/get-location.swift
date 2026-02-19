import CoreLocation
import Foundation

class Locator: NSObject, CLLocationManagerDelegate {
    private let mgr = CLLocationManager()
    private var done = false

    override init() {
        super.init()
        mgr.delegate = self
        mgr.desiredAccuracy = kCLLocationAccuracyBest
    }

    func start() {
        mgr.startUpdatingLocation()

        // Timeout after 10 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
            if !self.done {
                self.finish(json: "{\"error\": \"Location request timed out\"}")
            }
        }

        CFRunLoopRun()
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        finish(json: "{\"lat\": \(loc.coordinate.latitude), \"lon\": \(loc.coordinate.longitude), \"accuracy\": \(loc.horizontalAccuracy)}")
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(json: "{\"error\": \"\(error.localizedDescription)\"}")
    }

    private func finish(json: String) {
        guard !done else { return }
        done = true
        mgr.stopUpdatingLocation()
        print(json)
        CFRunLoopStop(CFRunLoopGetCurrent())
    }
}

let locator = Locator()
locator.start()
