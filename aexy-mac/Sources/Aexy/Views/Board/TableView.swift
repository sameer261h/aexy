import SwiftUI
import AexyCore

// Table view of the same filtered board tasks (shares AppState filters + detail).
struct BoardTableView: View {
    @ObservedObject var state: AppState
    @State private var detailTask: FlowTask?
    @State private var selection: FlowTask.ID?

    private var rows: [FlowTask] {
        state.columns.flatMap { state.tasks(inColumn: $0.slug) }
    }

    var body: some View {
        VStack(spacing: 0) {
            BoardFiltersBar(state: state)
            Divider()
            Table(rows, selection: $selection) {
                TableColumn("Task") { (t: FlowTask) in
                    Text(t.title).lineLimit(1)
                }
                TableColumn("Status") { (t: FlowTask) in
                    Text(statusName(t.status)).foregroundStyle(.secondary)
                }
                TableColumn("Priority") { (t: FlowTask) in
                    if let p = t.priority { PriorityTag(priority: p) } else { Text("—") }
                }
                TableColumn("Points") { (t: FlowTask) in
                    Text(t.storyPoints.map(String.init) ?? "—")
                }
                TableColumn("Assignee") { (t: FlowTask) in
                    Text(t.assigneeName ?? "—").foregroundStyle(.secondary)
                }
            }
        }
        .task { await state.loadProjectsAndBoard() }
        .onChange(of: selection) { id in
            if let id, let task = rows.first(where: { $0.id == id }) {
                detailTask = task
                selection = nil
            }
        }
        .sheet(item: $detailTask) { task in TaskDetailView(state: state, task: task) }
    }

    private func statusName(_ slug: String?) -> String {
        guard let slug else { return "—" }
        return state.columns.first { $0.slug == slug }?.name ?? slug
    }
}
