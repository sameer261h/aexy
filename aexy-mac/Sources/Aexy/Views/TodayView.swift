import SwiftUI
import AexyCore

struct TodayView: View {
    @ObservedObject var state: AppState
    @State private var detailTask: FlowTask?

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

                if state.isSignedIn {
                    CheckInCard(state: state)
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
                        TaskRow(
                            task: task,
                            onStatus: { status in Task { await state.setStatus(task, status) } },
                            onOpen: { detailTask = task }
                        )
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .sheet(item: $detailTask) { task in TaskDetailView(state: state, task: task) }
    }
}

struct TaskRow: View {
    let task: FlowTask
    let onStatus: (String) -> Void
    var onOpen: (() -> Void)?

    var body: some View {
        HStack(spacing: 12) {
            // Tapping the task (anywhere but the Status menu) opens detail.
            Button(action: { onOpen?() }) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(task.title).fontWeight(.medium)
                    HStack(spacing: 6) {
                        if let s = task.status { Text(s).font(.caption).foregroundStyle(.secondary) }
                        if let p = task.priority { Text(p).font(.caption).foregroundStyle(.secondary) }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

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

/// Check-in / check-out with progress toward the daily target. Check-in drives
/// the background capture loop (same as the menu bar); the target is resolved
/// from admin settings (developer → project → workspace default).
struct CheckInCard: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Circle()
                    .fill(state.isCheckedIn ? Color.green : Color.secondary.opacity(0.6))
                    .frame(width: 10, height: 10)
                Text(state.isCheckedIn ? "Checked in" : "Checked out")
                    .font(.headline)
                Spacer()
                Button(state.isCheckedIn ? "Check out" : "Check in") {
                    state.toggleCheckIn()
                }
                .buttonStyle(.borderedProminent)
                .disabled(!state.captureEnrolled)
            }

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(hms(state.checkedInSecondsToday)).font(.subheadline).bold()
                        .monospacedDigit()
                    Text("of \(hoursLabel(state.targetHoursPerDay)) target")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text("\(Int(state.checkInProgress * 100))%")
                        .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                }
                ProgressView(value: state.checkInProgress)
                    .tint(state.checkInProgress >= 1 ? .green : .accentColor)
            }

            if !state.captureEnrolled {
                Text("Check-in starts once an admin enables the Tracker for one of your projects.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .background(Color.secondary.opacity(0.06))
        .cornerRadius(12)
    }

    /// Elapsed time as "Xh Ym" (or "Ym" under an hour).
    private func hms(_ seconds: Double) -> String {
        let total = Int(seconds)
        let h = total / 3600
        let m = (total % 3600) / 60
        return h > 0 ? "\(h)h \(m)m" : "\(m)m"
    }

    /// Target hours like "8h" or "7h 30m".
    private func hoursLabel(_ hours: Double) -> String {
        let h = Int(hours)
        let m = Int((hours - Double(h)) * 60 + 0.5)
        return m > 0 ? "\(h)h \(m)m" : "\(h)h"
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
