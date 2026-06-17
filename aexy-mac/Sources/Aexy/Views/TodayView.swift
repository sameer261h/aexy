import SwiftUI
import AexyCore

struct TodayView: View {
    @ObservedObject var state: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("Today").font(.title2).bold()
                    Spacer()
                    if state.unreadCount > 0 {
                        Label("\(state.unreadCount)", systemImage: "bell.badge")
                            .foregroundStyle(.secondary)
                    }
                    Button {
                        Task { await state.refresh() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .buttonStyle(.borderless)
                }

                if !state.isSignedIn {
                    ContentUnavailable(
                        title: "Not signed in",
                        message: "Use the menu bar → Sign in to connect your account."
                    )
                } else if let err = state.errorMessage {
                    Text(err).foregroundStyle(.red).font(.callout)
                } else if state.isLoading && state.tasks.isEmpty {
                    ProgressView()
                } else if state.tasks.isEmpty {
                    ContentUnavailable(
                        title: "Nothing assigned",
                        message: "You have no open tasks. Enjoy the focus time."
                    )
                } else {
                    Text("My open tasks").font(.headline)
                    ForEach(state.tasks) { task in
                        TaskRow(task: task) { status in
                            Task { await state.setStatus(task, status) }
                        }
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct TaskRow: View {
    let task: FlowTask
    let onStatus: (String) -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(task.title).fontWeight(.medium)
                HStack(spacing: 6) {
                    if let s = task.status { Text(s).font(.caption).foregroundStyle(.secondary) }
                    if let p = task.priority { Text(p).font(.caption).foregroundStyle(.secondary) }
                }
            }
            Spacer()
            Menu("Status") {
                ForEach(["todo", "in_progress", "done"], id: \.self) { s in
                    Button(s) { onStatus(s) }
                }
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .padding(12)
        .background(Color.secondary.opacity(0.06))
        .cornerRadius(10)
    }
}

/// Minimal empty-state (avoids depending on macOS 14's ContentUnavailableView).
struct ContentUnavailable: View {
    let title: String
    let message: String
    var body: some View {
        VStack(spacing: 6) {
            Text(title).font(.headline)
            Text(message).font(.callout).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40)
    }
}
