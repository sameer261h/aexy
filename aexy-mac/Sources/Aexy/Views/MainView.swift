import SwiftUI

// Resolves the Aexy web app origin (AEXY_WEB_URL env, else https://aexy.io).
// The backend lives at server.aexy.io; the web app is the apex domain.
enum AexyWeb {
    static var url: URL {
        if let env = ProcessInfo.processInfo.environment["AEXY_WEB_URL"],
           let url = URL(string: env) {
            return url
        }
        return URL(string: "https://aexy.io")!
    }
}

// Aexy main window: web sign-in when signed out; otherwise a sidebar of native
// sections plus an embedded web view for deep features.
struct MainView: View {
    @ObservedObject var state: AppState

    enum Section: String, CaseIterable, Identifiable {
        case today = "Today"
        case tasks = "Tasks"
        case web = "Open in Aexy"
        var id: String { rawValue }
        var systemImage: String {
            switch self {
            case .today: return "sun.max"
            case .tasks: return "checklist"
            case .web: return "globe"
            }
        }
    }

    @State private var section: Section? = .today

    var body: some View {
        if !state.isSignedIn {
            LoginWebView(webURL: AexyWeb.url) { token in
                Task { await state.completeWebLogin(token: token) }
            }
            .frame(minWidth: 760, minHeight: 560)
        } else {
            NavigationSplitView {
                List(Section.allCases, selection: $section) { s in
                    Label(s.rawValue, systemImage: s.systemImage).tag(s)
                }
                .navigationTitle("Aexy")
            } detail: {
                Group {
                    switch section ?? .today {
                    case .today: TodayView(state: state)
                    case .tasks: TasksView(state: state)
                    case .web: AexyWebView()
                    }
                }
            }
            .frame(minWidth: 760, minHeight: 500)
            .task { await state.refresh() }
        }
    }
}
