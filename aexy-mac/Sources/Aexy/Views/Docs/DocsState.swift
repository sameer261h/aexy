import Foundation
import Combine
import AexyCore

// State for the native Docs shell: spaces, tree, favorites, search, selection,
// plus the encrypted offline cache + audit log. The editor itself is the
// embedded web view; this drives navigation + offline read.
@MainActor
final class DocsState: ObservableObject {
    @Published var spaces: [DocSpace] = []
    @Published var selectedSpaceId: String?
    @Published var tree: [DocNode] = []
    @Published var favorites: [DocNode] = []
    @Published var searchQuery = ""
    @Published var searchResults: [DocListItem] = []
    @Published var selectedDocId: String?
    @Published var offline = false
    @Published var loading = false
    @Published var errorMessage: String?

    private let cache = DocCache()
    private let audit = DocAudit()
    private var client: FlowClient?
    private(set) var workspaceId: String?

    func configure(client: FlowClient?, workspaceId: String?) {
        self.client = client
        self.workspaceId = workspaceId
    }

    func load() async {
        guard let client, let ws = workspaceId else { return }
        loading = true
        errorMessage = nil
        do {
            spaces = try await client.docSpaces(workspaceId: ws)
            tree = try await client.docTree(workspaceId: ws, spaceId: selectedSpaceId)
            favorites = (try? await client.docFavorites(workspaceId: ws)) ?? []
            offline = false
        } catch {
            errorMessage = "\(error)"
            offline = true
        }
        loading = false
    }

    func selectSpace(_ id: String?) {
        selectedSpaceId = id
        Task { await load() }
    }

    func search() async {
        guard let client, let ws = workspaceId, !searchQuery.isEmpty else {
            searchResults = []
            return
        }
        searchResults = (try? await client.searchDocuments(workspaceId: ws, query: searchQuery)) ?? []
    }

    @discardableResult
    func createDoc(title: String) async -> String? {
        guard let client, let ws = workspaceId else { return nil }
        let item = try? await client.createDocument(workspaceId: ws, title: title, spaceId: selectedSpaceId)
        await load()
        if let id = item?.id { open(id) }
        return item?.id
    }

    func open(_ id: String) {
        selectedDocId = id
        audit.log("opened", docId: id)
        Task { await prefetch(id) }
    }

    /// Fetch + cache the doc detail so it's readable offline later.
    private func prefetch(_ id: String) async {
        guard let client, let ws = workspaceId else { return }
        if let detail = try? await client.document(workspaceId: ws, documentId: id) {
            cache.save(detail)
        }
    }

    /// Native title for a doc id (tree → favorites → search → cache).
    func title(for id: String) -> String {
        func find(_ nodes: [DocNode]) -> String? {
            for n in nodes {
                if n.id == id { return n.title }
                if let kids = n.children, let hit = find(kids) { return hit }
            }
            return nil
        }
        if let t = find(tree), !t.isEmpty { return t }
        if let t = favorites.first(where: { $0.id == id })?.title, !t.isEmpty { return t }
        if let t = searchResults.first(where: { $0.id == id })?.title, !t.isEmpty { return t }
        if let t = cachedDetail(id)?.title, !t.isEmpty { return t }
        return "Untitled"
    }

    func cachedDetail(_ id: String) -> DocDetail? { cache.load(id)?.detail }
    func cachedAt(_ id: String) -> Date? { cache.load(id)?.cachedAt }

    /// Markdown export of a cached doc's plain text (audited).
    func markdownExport(_ id: String) -> (name: String, text: String)? {
        guard let detail = cachedDetail(id) else { return nil }
        audit.log("exported", docId: id)
        let body = detail.contentText ?? ""
        return ("\(detail.title).md", "# \(detail.title)\n\n\(body)\n")
    }
}
