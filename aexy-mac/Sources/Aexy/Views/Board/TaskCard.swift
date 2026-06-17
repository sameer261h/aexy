import SwiftUI
import AexyCore

// A Kanban card mirroring the web TaskCardPremium: title, priority, story
// points, assignee initials, labels, and a due-date badge (overdue in red).
struct TaskCard: View {
    let task: FlowTask

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(task.title).font(.callout).fontWeight(.medium).lineLimit(3)

            HStack(spacing: 6) {
                if let p = task.priority { PriorityTag(priority: p) }
                if let sp = task.storyPoints { Text("\(sp) SP").font(.caption2).foregroundStyle(.secondary) }
                if let id = task.identifier { Text(id).font(.caption2).foregroundStyle(.secondary) }
                Spacer()
                if let name = task.assigneeName { Avatar(name: name) }
            }

            if let labels = task.labels, !labels.isEmpty {
                HStack(spacing: 4) {
                    ForEach(labels.prefix(3), id: \.self) { label in
                        Text(label)
                            .font(.caption2)
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(Color.blue.opacity(0.12))
                            .foregroundStyle(.blue)
                            .clipShape(Capsule())
                    }
                }
            }

            if let due = task.endDate ?? task.dueDate {
                Text(DueDate.format(due))
                    .font(.caption2)
                    .foregroundStyle(DueDate.isOverdue(due, done: task.status == "done") ? .red : .secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.15)))
        .cornerRadius(10)
    }
}

struct PriorityTag: View {
    let priority: String
    private var color: Color {
        switch priority {
        case "critical": return .red
        case "high": return .orange
        case "medium": return .yellow
        default: return .blue
        }
    }
    var body: some View {
        Text(priority).font(.caption2).foregroundStyle(color)
    }
}

struct Avatar: View {
    let name: String
    private var initials: String {
        let parts = name.split(separator: " ")
        let chars = parts.prefix(2).compactMap { $0.first }
        return String(chars).uppercased()
    }
    var body: some View {
        Text(initials)
            .font(.system(size: 9, weight: .semibold))
            .frame(width: 20, height: 20)
            .background(Color.secondary.opacity(0.2))
            .clipShape(Circle())
    }
}

enum DueDate {
    static func format(_ iso: String) -> String {
        String(iso.prefix(10))  // YYYY-MM-DD
    }
    static func isOverdue(_ iso: String, done: Bool) -> Bool {
        guard !done else { return false }
        return String(iso.prefix(10)) < String(ISO8601DateFormatter().string(from: Date()).prefix(10))
    }
}
