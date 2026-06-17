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
    @StateObject private var web = WebNavigator()
    @State private var selectedId: String? =
        UserDefaults.standard.string(forKey: MainView.selKey) ?? "today"

    static let selKey = "aexy.nav.selectedId"

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

    // Longest route-prefix match: which top-level web section owns a path.
    static func webSection(for path: String) -> NavEntry? {
        webItems
            .filter { item in item.route.map { path == $0 || path.hasPrefix($0 + "/") } ?? false }
            .max(by: { ($0.route?.count ?? 0) < ($1.route?.count ?? 0) })
    }

    private func isWebSection(_ id: String?) -> Bool {
        Self.webItems.contains { $0.id == id }
    }

    /// Active web section shows the live page title; others keep their base label.
    private func label(for item: NavEntry) -> String {
        if item.id == selectedId, isWebSection(selectedId), !web.currentTitle.isEmpty {
            return web.currentTitle
        }
        return item.label
    }

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
                                Label(label(for: item), systemImage: item.icon).tag(item.id)
                            }
                        }
                        if !web.recents.isEmpty {
                            Section("Recent") {
                                ForEach(web.recents) { r in
                                    Button { openRecent(r) } label: {
                                        Label(r.title, systemImage: Self.webSection(for: r.path)?.icon ?? "clock.arrow.circlepath")
                                            .lineLimit(1)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                }
                .navigationTitle("Aexy")
            } detail: {
                detail
            }
            .frame(minWidth: 980, minHeight: 600)
            .task {
                await state.loadProjectsAndBoard()
                web.configure(workspaceId: state.selectedWorkspaceId)
                // Resume: if we left off on a web section, reopen the exact route.
                if isWebSection(selectedId) {
                    let route = Self.webItems.first { $0.id == selectedId }?.route ?? "/"
                    web.navigate(to: web.currentPath.isEmpty ? route : web.currentPath)
                }
            }
            .onChange(of: selectedId) { newValue in
                UserDefaults.standard.set(newValue, forKey: Self.selKey)
                // Selecting a web section loads its base route unless we're already
                // inside it (preserves a resumed/deeper route).
                if let id = newValue,
                   let route = Self.webItems.first(where: { $0.id == id })?.route,
                   Self.webSection(for: web.currentPath)?.id != id {
                    web.navigate(to: route)
                }
            }
            .onChange(of: web.currentPath) { path in
                // Follow in-web navigation that crosses into another section.
                if isWebSection(selectedId), let sec = Self.webSection(for: path), sec.id != selectedId {
                    selectedId = sec.id
                }
            }
            .onChange(of: state.selectedWorkspaceId) { ws in
                web.reloadForWorkspace(ws)
            }
        }
    }

    private func openRecent(_ r: WebRecent) {
        web.navigate(to: r.path)
        if let sec = Self.webSection(for: r.path) {
            selectedId = sec.id
        }
    }

    @ViewBuilder private var detail: some View {
        if isWebSection(selectedId) {
            WebContainerView(navigator: web)
        } else {
            switch selectedId ?? "today" {
            case "today": TodayView(state: state)
            case "board": BoardView(state: state)
            case "table": BoardTableView(state: state)
            case "docs": DocsView(app: state)
            case "time": TimeView(app: state)
            case "standups": StandupsView(app: state)
            default: TodayView(state: state)
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
