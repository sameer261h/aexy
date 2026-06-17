import SwiftUI
import AexyCore

// Native project Kanban (standup view): columns = project statuses, drag-to-move,
// filters, and tap-to-open task detail. Mirrors the web project board.
struct BoardView: View {
    @ObservedObject var state: AppState
    @State private var detailTask: FlowTask?
    @State private var showingNew = false
    @State private var newTitle = ""
    @State private var newStatus = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                BoardFiltersBar(state: state)
                Button {
                    newStatus = state.columns.first?.slug ?? "backlog"
                    showingNew = true
                } label: { Label("New task", systemImage: "plus") }
                .disabled(state.selectedProjectId == nil)   // needs a project (team)
                .help(state.selectedProjectId == nil ? "Pick a project to create a task" : "New task")
                .padding(.trailing, 10)
            }
            Divider()
            if state.boardLoading && state.board.isEmpty {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView(.horizontal, showsIndicators: true) {
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(state.columns, id: \.slug) { col in
                            BoardColumn(state: state, slug: col.slug, name: col.name) { detailTask = $0 }
                        }
                    }
                    .padding(12)
                }
            }
        }
        .task { await state.loadProjectsAndBoard() }
        .sheet(item: $detailTask) { task in
            TaskDetailView(state: state, task: task)
        }
        .sheet(isPresented: $showingNew) {
            NewTaskSheet(state: state, title: $newTitle, status: $newStatus) {
                let created = await state.createBoardTask(title: newTitle, status: newStatus)
                newTitle = ""
                showingNew = false
                if let created { detailTask = created }
            }
        }
    }
}

struct NewTaskSheet: View {
    @ObservedObject var state: AppState
    @Binding var title: String
    @Binding var status: String
    let onCreate: () async -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("New task").font(.headline)
            TextField("Title", text: $title).textFieldStyle(.roundedBorder)
            Picker("Status", selection: $status) {
                ForEach(state.columns, id: \.slug) { Text($0.name).tag($0.slug) }
            }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Create") { Task { await onCreate() } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 380)
    }
}

struct BoardColumn: View {
    @ObservedObject var state: AppState
    let slug: String
    let name: String
    let onOpen: (FlowTask) -> Void

    var body: some View {
        let tasks = state.tasks(inColumn: slug)
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(name).font(.subheadline).bold()
                Text("\(tasks.count)").font(.caption).foregroundStyle(.secondary)
                Spacer()
            }
            ForEach(tasks) { task in
                TaskCard(task: task)
                    .onTapGesture { onOpen(task) }
                    .draggable(task.id)
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .frame(width: 280, alignment: .top)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Color.secondary.opacity(0.06))
        .cornerRadius(12)
        .dropDestination(for: String.self) { ids, _ in
            guard let id = ids.first, let task = state.board.first(where: { $0.id == id }) else {
                return false
            }
            Task { await state.moveTask(task, toStatus: slug) }
            return true
        }
    }
}

struct BoardFiltersBar: View {
    @ObservedObject var state: AppState
    private let priorities = ["critical", "high", "medium", "low"]

    private func toggle(_ set: inout Set<String>, _ value: String) {
        if set.contains(value) { set.remove(value) } else { set.insert(value) }
    }

    var body: some View {
        HStack(spacing: 10) {
            TextField("Search tasks…", text: $state.filterSearch)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 260)
                .onSubmit { Task { await state.loadBoard() } }

            Menu {
                ForEach(priorities, id: \.self) { p in
                    Button {
                        if state.filterPriorities.contains(p) { state.filterPriorities.remove(p) }
                        else { state.filterPriorities.insert(p) }
                        Task { await state.loadBoard() }
                    } label: {
                        Label(p.capitalized, systemImage: state.filterPriorities.contains(p) ? "checkmark" : "")
                    }
                }
            } label: {
                Label(
                    state.filterPriorities.isEmpty ? "Priority" : "Priority (\(state.filterPriorities.count))",
                    systemImage: "line.3.horizontal.decrease.circle"
                )
            }
            .fixedSize()

            if !state.members.isEmpty {
                Menu {
                    ForEach(state.members) { m in
                        Button {
                            toggle(&state.filterAssignees, m.developerId)
                            Task { await state.loadBoard() }
                        } label: {
                            Label(m.displayName, systemImage: state.filterAssignees.contains(m.developerId) ? "checkmark" : "")
                        }
                    }
                } label: {
                    Label(
                        state.filterAssignees.isEmpty ? "Assignee" : "Assignee (\(state.filterAssignees.count))",
                        systemImage: "person.crop.circle"
                    )
                }
                .fixedSize()
            }

            if !state.availableLabels.isEmpty {
                Menu {
                    ForEach(state.availableLabels, id: \.self) { label in
                        Button {
                            toggle(&state.filterLabels, label)
                            Task { await state.loadBoard() }
                        } label: {
                            Label(label, systemImage: state.filterLabels.contains(label) ? "checkmark" : "")
                        }
                    }
                } label: {
                    Label(
                        state.filterLabels.isEmpty ? "Labels" : "Labels (\(state.filterLabels.count))",
                        systemImage: "tag"
                    )
                }
                .fixedSize()
            }

            if !state.sprints.isEmpty {
                Menu {
                    ForEach(state.sprints) { s in
                        Button {
                            toggle(&state.filterSprintIds, s.id)
                            Task { await state.loadBoard() }
                        } label: {
                            Label(s.name, systemImage: state.filterSprintIds.contains(s.id) ? "checkmark" : "")
                        }
                    }
                } label: {
                    Label(
                        state.filterSprintIds.isEmpty ? "Sprint" : "Sprint (\(state.filterSprintIds.count))",
                        systemImage: "flag.checkered"
                    )
                }
                .fixedSize()
            }

            Spacer()
            Button { Task { await state.loadBoard() } } label: { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.borderless)
        }
        .padding(10)
    }
}
