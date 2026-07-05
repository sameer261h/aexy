import SwiftUI
import AexyCore

// Reusable task detail — opened from the board, table, or Today. Shows status
// quick-change, description, and comments/activity (sprint-scoped). Editing
// fields beyond status uses the sprint-scoped update; comments require a sprint.
struct TaskDetailView: View {
    @ObservedObject var state: AppState
    let task: FlowTask
    @Environment(\.dismiss) private var dismiss

    @State private var activities: [FlowActivity] = []
    @State private var comment = ""
    @State private var loading = false

    // Editable fields (seeded once from the task).
    @State private var priority = "medium"
    @State private var points = 0
    @State private var labelsText = ""
    @State private var assigneeId = ""   // "" = unassigned
    @State private var dueEnabled = false
    @State private var dueDate = Date()
    @State private var seeded = false
    @State private var saving = false

    private let priorities = ["low", "medium", "high", "critical"]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(task.title).font(.title3).bold()
                    if let id = task.identifier { Text(id).font(.caption).foregroundStyle(.secondary) }
                }
                Spacer()
                Button(action: { dismiss() }) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.cancelAction)
                .help("Close")
            }

            // Status quick-change
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(state.columns, id: \.slug) { col in
                        Button(col.name) { Task { await state.moveTask(task, toStatus: col.slug) } }
                            .buttonStyle(.bordered)
                            .tint(task.status == col.slug ? .accentColor : .gray)
                    }
                }
            }

            if let desc = task.description, !desc.isEmpty {
                Text(desc).font(.callout).foregroundStyle(.secondary)
            }

            if state.editable(task) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 16) {
                        Picker("Priority", selection: $priority) {
                            ForEach(priorities, id: \.self) { Text($0.capitalized).tag($0) }
                        }
                        .fixedSize()
                        Stepper("\(points) SP", value: $points, in: 0...21)
                            .fixedSize()
                    }
                    if !state.members.isEmpty {
                        Picker("Assignee", selection: $assigneeId) {
                            Text("Unassigned").tag("")
                            ForEach(state.members) { m in Text(m.displayName).tag(m.developerId) }
                        }
                        .fixedSize()
                    }
                    HStack(spacing: 12) {
                        Toggle("Due date", isOn: $dueEnabled)
                        if dueEnabled {
                            DatePicker("", selection: $dueDate, displayedComponents: .date)
                                .labelsHidden()
                        }
                    }
                    HStack {
                        TextField("Labels (comma-separated)", text: $labelsText)
                            .textFieldStyle(.roundedBorder)
                        Button("Save") { Task { await save() } }
                            .disabled(saving)
                    }
                }
            } else {
                HStack(spacing: 12) {
                    if let p = task.priority { Label(p.capitalized, systemImage: "flag") }
                    if let sp = task.storyPoints { Label("\(sp) SP", systemImage: "number") }
                    if let a = task.assigneeName { Label(a, systemImage: "person") }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Divider()
            Text("Comments & activity").font(.headline)

            if loading {
                ProgressView()
            } else if activities.isEmpty {
                Text(state.commentable(task) ? "No activity yet." : "Comments unavailable for this task.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(activities) { a in ActivityRow(activity: a) }
                    }
                }
                .frame(maxHeight: 220)
            }

            if state.commentable(task) {
                HStack {
                    TextField("Add a comment…", text: $comment).textFieldStyle(.roundedBorder)
                    Button("Send") {
                        Task {
                            await state.addComment(task, comment)
                            comment = ""
                            await reload()
                        }
                    }
                    .disabled(comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .padding(20)
        .frame(width: 540, height: 600)
        .task { await reload() }
        .onAppear(perform: seed)
    }

    private func seed() {
        guard !seeded else { return }
        seeded = true
        priority = task.priority ?? "medium"
        points = task.storyPoints ?? 0
        labelsText = (task.labels ?? []).joined(separator: ", ")
        assigneeId = task.assigneeId ?? ""
        if let due = task.endDate ?? task.dueDate {
            dueEnabled = true
            if let iso = ISO8601DateFormatter().date(from: due) {
                dueDate = iso
            } else {
                let f = DateFormatter()
                f.dateFormat = "yyyy-MM-dd"
                dueDate = f.date(from: String(due.prefix(10))) ?? Date()
            }
        }
    }

    private func save() async {
        saving = true
        var fields = TaskUpdateFields()
        fields.priority = priority
        fields.storyPoints = points
        fields.labels = labelsText
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        if !assigneeId.isEmpty { fields.assigneeId = assigneeId }
        if dueEnabled { fields.endDate = ISO8601DateFormatter().string(from: dueDate) }
        await state.updateTaskFields(task, fields)
        // Explicit unassign needs a null-capable update (separate call).
        if assigneeId.isEmpty, task.assigneeId != nil { await state.unassign(task) }
        await reload()
        saving = false
    }

    private func reload() async {
        loading = true
        activities = await state.loadActivities(task)
        loading = false
    }
}

struct ActivityRow: View {
    let activity: FlowActivity
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(activity.actorName ?? "Someone").font(.caption).bold()
                if let action = activity.action, action != "comment" {
                    Text(summary(action)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if let ts = activity.createdAt { Text(String(ts.prefix(10))).font(.caption2).foregroundStyle(.secondary) }
            }
            if let c = activity.comment, !c.isEmpty {
                Text(c).font(.callout)
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.06))
        .cornerRadius(8)
    }

    private func summary(_ action: String) -> String {
        let field = activity.fieldName ?? action.replacingOccurrences(of: "_", with: " ")
        if let old = activity.oldValue, let new = activity.newValue {
            return "changed \(field): \(old) → \(new)"
        }
        return action.replacingOccurrences(of: "_", with: " ")
    }
}
