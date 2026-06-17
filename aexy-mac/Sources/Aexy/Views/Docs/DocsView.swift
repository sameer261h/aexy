import SwiftUI
import AppKit
import AexyCore

// Native Docs: a tree/search/create shell on the left, the embedded (chromeless)
// web editor on the right — full parity (collaboration, slash, mentions, inline
// DBs, versions, AI proposals) with native navigation + offline read.
struct DocsView: View {
    @ObservedObject var app: AppState
    @StateObject private var docs = DocsState()

    var body: some View {
        HSplitView {
            DocTreeView(docs: docs)
                .frame(minWidth: 190, idealWidth: 230, maxWidth: 300)
            DocEditorPane(docs: docs, workspaceId: app.selectedWorkspaceId)
                .frame(minWidth: 460, maxWidth: .infinity)
        }
        .task {
            docs.configure(client: app.flowClient, workspaceId: app.selectedWorkspaceId)
            await docs.load()
        }
        .onChange(of: app.selectedWorkspaceId) { ws in
            docs.configure(client: app.flowClient, workspaceId: ws)
            Task { await docs.load() }
        }
    }
}

struct DocTreeView: View {
    @ObservedObject var docs: DocsState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Docs").font(.headline)
                Spacer()
                Button {
                    Task { await docs.createDoc(title: "Untitled") }
                } label: { Image(systemName: "plus") }
                .buttonStyle(.borderless)
                .help("New doc")
            }

            if !docs.spaces.isEmpty {
                Picker("Space", selection: Binding(
                    get: { docs.selectedSpaceId ?? "" },
                    set: { docs.selectSpace($0.isEmpty ? nil : $0) }
                )) {
                    Text("All spaces").tag("")
                    ForEach(docs.spaces) { s in Text(s.name).tag(s.id) }
                }
                .labelsHidden()
            }

            TextField("Search docs…", text: $docs.searchQuery)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await docs.search() } }

            if docs.offline {
                Label("Offline — showing cached docs", systemImage: "wifi.slash")
                    .font(.caption).foregroundStyle(.orange)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    if !docs.searchQuery.isEmpty {
                        ForEach(docs.searchResults) { item in
                            DocRow(title: item.title, icon: item.icon, selected: docs.selectedDocId == item.id) {
                                docs.open(item.id)
                            }
                        }
                    } else {
                        if !docs.favorites.isEmpty {
                            Text("Favorites").font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                            ForEach(docs.favorites) { node in
                                DocRow(title: node.title, icon: node.icon, selected: docs.selectedDocId == node.id) {
                                    docs.open(node.id)
                                }
                            }
                            Divider().padding(.vertical, 4)
                        }
                        OutlineGroup(docs.tree, children: \.children) { node in
                            DocRow(title: node.title, icon: node.icon, selected: docs.selectedDocId == node.id) {
                                docs.open(node.id)
                            }
                        }
                    }
                }
            }
        }
        .padding(10)
        .frame(maxHeight: .infinity, alignment: .top)
    }
}

struct DocRow: View {
    let title: String
    let icon: String?
    let selected: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 6) {
                Text(icon ?? "📄")
                Text(title.isEmpty ? "Untitled" : title).lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 3).padding(.horizontal, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Color.accentColor.opacity(0.15) : .clear)
            .cornerRadius(6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct DocEditorPane: View {
    @ObservedObject var docs: DocsState
    let workspaceId: String?
    @State private var editedTitle = ""

    var body: some View {
        if let id = docs.selectedDocId {
            VStack(spacing: 0) {
                // Single native header — editable title (the embedded web's own
                // title header is hidden in embed mode).
                HStack(spacing: 8) {
                    TextField("Untitled", text: $editedTitle)
                        .textFieldStyle(.plain)
                        .font(.headline)
                        .onSubmit { Task { await docs.renameDoc(id, editedTitle) } }
                    Spacer()
                    Menu {
                        Button("Markdown (.md)") { exportMarkdown(id) }
                        Button("PDF (.pdf)") { exportPDF(id) }
                    } label: { Label("Export", systemImage: "square.and.arrow.up") }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                }
                .padding(.horizontal, 12).padding(.vertical, 8)
                .onAppear { editedTitle = docs.title(for: id) }
                .onChange(of: docs.selectedDocId) { newId in
                    editedTitle = docs.title(for: newId ?? "")
                }
                Divider()
                if docs.offline {
                    OfflineDocView(docs: docs, id: id)
                } else {
                    EmbeddedWebView(route: "/docs/\(id)", workspaceId: workspaceId)
                }
            }
        } else {
            VStack(spacing: 6) {
                Image(systemName: "doc.text").font(.largeTitle).foregroundStyle(.secondary)
                Text("Select a doc, or create one").foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func exportMarkdown(_ id: String) {
        guard let out = docs.markdownExport(id) else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = out.name
        panel.begin { resp in
            if resp == .OK, let url = panel.url {
                try? out.text.data(using: .utf8)?.write(to: url)
            }
        }
    }

    private func exportPDF(_ id: String) {
        guard let detail = docs.cachedDetail(id) else { return }
        let full = "\(detail.title)\n\n\(detail.contentText ?? "")"
        let width: CGFloat = 540
        let textView = NSTextView(frame: NSRect(x: 0, y: 0, width: width, height: 10))
        textView.string = full
        textView.font = NSFont.systemFont(ofSize: 12)
        if let lm = textView.layoutManager, let tc = textView.textContainer {
            lm.ensureLayout(for: tc)
            let h = lm.usedRect(for: tc).height + 40
            textView.frame = NSRect(x: 0, y: 0, width: width, height: h)
        }
        let pdf = textView.dataWithPDF(inside: textView.bounds)
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "\(detail.title).pdf"
        panel.begin { resp in
            if resp == .OK, let url = panel.url { try? pdf.write(to: url) }
        }
    }
}

// Read-only offline view backed by the encrypted cache.
struct OfflineDocView: View {
    @ObservedObject var docs: DocsState
    let id: String

    var body: some View {
        if let detail = docs.cachedDetail(id) {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(detail.title).font(.title2).bold()
                    if let at = docs.cachedAt(id) {
                        Text("Offline — last synced \(at.formatted())").font(.caption).foregroundStyle(.secondary)
                    }
                    Text(detail.contentText ?? "(no cached text)")
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(20)
            }
        } else {
            VStack(spacing: 6) {
                Image(systemName: "wifi.slash").font(.largeTitle).foregroundStyle(.secondary)
                Text("Not available offline — open it once while online to cache it.")
                    .foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity).padding()
        }
    }
}
