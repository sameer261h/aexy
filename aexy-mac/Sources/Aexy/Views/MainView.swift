import SwiftUI
import AexyCore

// Resolves the Aexy web app origin (AEXY_WEB_URL env, else https://aexy.io).
enum AexyWeb {
    static var url: URL {
        if let env = ProcessInfo.processInfo.environment["AEXY_WEB_URL"],
           let url = URL(string: env) {
            return url
        }
        return URL(string: "https://aexy.io")!
    }
}

struct NavEntry: Identifiable, Hashable {
    let id: String
    let label: String
    let icon: String
    let route: String?   // nil ⇒ native section
}

// Aexy main window. Signed out → web login. Signed in → the native sidebar is
// the only navigation: native sections (Today/Board/Table) + "More in Aexy"
// entries that load the web app chromeless. A global workspace/project switcher
// drives the board (and seeds the embedded web's workspace).
struct MainView: View {
    @ObservedObject var state: AppState
    @State private var selectedId: String? = "today"

    static let nativeItems: [NavEntry] = [
        NavEntry(id: "today", label: "Today", icon: "sun.max", route: nil),
        NavEntry(id: "board", label: "Board", icon: "rectangle.split.3x1", route: nil),
        NavEntry(id: "table", label: "Table", icon: "tablecells", route: nil),
        NavEntry(id: "docs", label: "Docs", icon: "doc.text", route: nil),
        NavEntry(id: "time", label: "Time", icon: "clock", route: nil),
        NavEntry(id: "standups", label: "Standups", icon: "bubble.left.and.bubble.right", route: nil),
    ]
    static let webItems: [NavEntry] = [
        NavEntry(id: "web-crm", label: "CRM", icon: "person.2", route: "/crm"),
        NavEntry(id: "web-analytics", label: "Analytics", icon: "chart.bar", route: "/analytics"),
        NavEntry(id: "web-agents", label: "Agents", icon: "sparkles", route: "/agents"),
        NavEntry(id: "web-settings", label: "Settings", icon: "gearshape", route: "/settings"),
    ]

    var body: some View {
        if !state.isSignedIn {
            LoginWebView(webURL: AexyWeb.url) { token in
                Task { await state.completeWebLogin(token: token) }
            }
            .frame(minWidth: 820, minHeight: 600)
        } else {
            NavigationSplitView {
                VStack(spacing: 0) {
                    ProjectSwitcher(state: state).padding(8)
                    Divider()
                    List(selection: $selectedId) {
                        Section("Workspace") {
                            ForEach(Self.nativeItems) { item in
                                Label(item.label, systemImage: item.icon).tag(item.id)
                            }
                        }
                        Section("More in Aexy") {
                            ForEach(Self.webItems) { item in
                                Label(item.label, systemImage: item.icon).tag(item.id)
                            }
                        }
                    }
                }
                .navigationTitle("Aexy")
            } detail: {
                detail
            }
            .frame(minWidth: 980, minHeight: 600)
            .task { await state.loadProjectsAndBoard() }
        }
    }

    @ViewBuilder private var detail: some View {
        switch selectedId ?? "today" {
        case "today": TodayView(state: state)
        case "board": BoardView(state: state)
        case "table": BoardTableView(state: state)
        case "docs": DocsView(app: state)
        case "time": TimeView(app: state)
        case "standups": StandupsView(app: state)
        default:
            if let item = Self.webItems.first(where: { $0.id == selectedId }), let route = item.route {
                EmbeddedWebView(route: route, workspaceId: state.selectedWorkspaceId)
                    // Reload when the selected workspace changes.
                    .id(item.id + "|" + (state.selectedWorkspaceId ?? ""))
            } else {
                TodayView(state: state)
            }
        }
    }
}

// Global workspace + project switcher (drives the native board + embedded web).
struct ProjectSwitcher: View {
    @ObservedObject var state: AppState
    static let allProjectsTag = "__all__"

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !state.workspaces.isEmpty {
                Picker("Workspace", selection: Binding(
                    get: { state.selectedWorkspaceId ?? state.workspaces.first?.id ?? "" },
                    set: { ws in
                        state.selectedWorkspaceId = ws
                        state.selectedProjectId = nil
                        Task { await state.loadProjectsAndBoard() }
                    }
                )) {
                    ForEach(state.workspaces) { ws in Text(ws.name).tag(ws.id) }
                }
                .labelsHidden()
            }
            if !state.projects.isEmpty {
                Picker("Project", selection: Binding(
                    get: { state.selectedProjectId ?? Self.allProjectsTag },
                    set: { value in
                        if value == Self.allProjectsTag { state.selectAllProjects() }
                        else { state.selectProject(value) }
                    }
                )) {
                    Text("All projects").tag(Self.allProjectsTag)
                    ForEach(state.projects) { p in Text(p.name).tag(p.id) }
                }
                .labelsHidden()
            }
        }
    }
}
