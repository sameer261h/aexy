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
        // Chat = the embedded communicator (Threads / Notifications / Activity / AI).
        NavEntry(id: "web-chat", label: "Chat", icon: "bubble.left.and.bubble.right", route: "/communicator"),
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

    /// The active web section shows the live page name only when navigated deeper
    /// than its root (e.g. CRM → "CRM · Deals"); otherwise it keeps its base label.
    private func label(for item: NavEntry) -> String {
        if item.id == selectedId, isWebSection(selectedId), let route = item.route,
           web.currentPath.hasPrefix(route + "/"), !web.currentTitle.isEmpty {
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
                                Label(label(for: item), systemImage: item.icon)
                                    .tag(item.id)
                                    .badge(
                                        item.id == "web-chat" && state.communicatorUnread > 0
                                            ? Text("\(state.communicatorUnread)") : nil
                                    )
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
                if let pending = state.pendingSection {
                    state.pendingSection = nil
                    goToSection(pending)
                } else if isWebSection(selectedId) {
                    // Resume: if we left off on a web section, reopen the exact route.
                    let route = Self.webItems.first { $0.id == selectedId }?.route ?? "/"
                    web.navigate(to: web.currentPath.isEmpty ? route : web.currentPath)
                }
            }
            .onChange(of: state.pendingSection) { pending in
                guard let pending else { return }
                state.pendingSection = nil
                goToSection(pending)
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

    /// Select a sidebar section, navigating the web container only if we're not
    /// already inside it (so a deep-link doesn't needlessly reload the page).
    private func goToSection(_ id: String) {
        selectedId = id
        if let route = Self.webItems.first(where: { $0.id == id })?.route,
           Self.webSection(for: web.currentPath)?.id != id {
            web.navigate(to: route)
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
// Styled as two rounded "pill" menus with icons so the sidebar header reads as a
// proper account/context switcher rather than raw form controls.
struct ProjectSwitcher: View {
    @ObservedObject var state: AppState
    static let allProjectsTag = "__all__"

    private var workspaceName: String {
        state.workspaces.first { $0.id == state.selectedWorkspaceId }?.name
            ?? state.workspaces.first?.name ?? "Workspace"
    }
    private var projectName: String {
        guard let pid = state.selectedProjectId else { return "All projects" }
        return state.projects.first { $0.id == pid }?.name ?? "All projects"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !state.workspaces.isEmpty {
                Menu {
                    ForEach(state.workspaces) { ws in
                        Button(ws.name) {
                            state.selectedWorkspaceId = ws.id
                            state.selectedProjectId = nil
                            Task { await state.loadProjectsAndBoard() }
                        }
                    }
                } label: {
                    pill(icon: "building.2.fill", title: workspaceName)
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if !state.projects.isEmpty {
                Menu {
                    Button("All projects") { state.selectAllProjects() }
                    Divider()
                    ForEach(state.projects) { p in
                        Button(p.name) { state.selectProject(p.id) }
                    }
                } label: {
                    pill(icon: "folder.fill", title: projectName, muted: state.selectedProjectId == nil)
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func pill(icon: String, title: String, muted: Bool = false) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 12))
                .foregroundStyle(muted ? Color.secondary : Color.accentColor)
            Text(title)
                .fontWeight(.medium)
                .lineLimit(1)
                .foregroundStyle(.primary)
            Spacer(minLength: 4)
            Image(systemName: "chevron.up.chevron.down")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color.secondary.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .contentShape(Rectangle())
    }
}
