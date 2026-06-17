import Foundation
import UserNotifications

// Thin wrapper over UNUserNotificationCenter for surfacing Aexy notifications
// as native macOS notifications.
enum NativeNotifier {
    // UNUserNotificationCenter requires a bundled app with a valid bundle
    // identifier; under `swift run` (no .app bundle) `current()` raises an
    // NSException and aborts. Guard so dev runs don't crash — notifications
    // light up once the app is packaged as a signed .app.
    static var isAvailable: Bool { Bundle.main.bundleIdentifier != nil }

    static func requestAuthorization() {
        guard isAvailable else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    static func post(id: String, title: String, body: String, actionUrl: String?) {
        guard isAvailable else { return }
        let content = UNMutableNotificationContent()
        content.title = title.isEmpty ? "Aexy" : title
        content.body = body
        if let actionUrl { content.userInfo = ["action_url": actionUrl] }
        // nil trigger → deliver immediately.
        let request = UNNotificationRequest(identifier: id, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
