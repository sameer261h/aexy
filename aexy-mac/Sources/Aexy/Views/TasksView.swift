import SwiftUI
import AexyCore

struct TasksView: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Tasks").font(.title2).bold()
                Spacer()
                if !state.workspaces.isEmpty {
                    Picker("Workspace", selection: Binding(
                        get: { state.selectedWorkspaceId ?? state.workspaces.first?.id ?? "" },
                        set: { state.selectedWorkspaceId = $0 }
                    )) {
                        ForEach(state.workspaces) { ws in
                            Text(ws.name).tag(ws.id)
                        }
                    }
                    .fixedSize()
                }
            }
            .padding(20)

            if !state.isSignedIn {
                ContentUnavailable(title: "Not signed in", message: "Sign in from the menu bar.")
            } else {
                List(visibleTasks) { task in
                    TaskRow(task: task) { status in
                        Task { await state.setStatus(task, status) }
                    }
                    .listRowSeparator(.hidden)
                }
                .listStyle(.plain)
            }
        }
    }

    private var visibleTasks: [FlowTask] {
        guard let ws = state.selectedWorkspaceId else { return state.tasks }
        // Tasks without a workspace id (older payloads) stay visible.
        return state.tasks.filter { $0.workspaceId == nil || $0.workspaceId == ws }
    }
}
