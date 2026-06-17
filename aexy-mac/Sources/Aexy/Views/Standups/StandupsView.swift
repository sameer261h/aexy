import SwiftUI
import Combine
import AexyCore

@MainActor
final class StandupsState: ObservableObject {
    @Published var recent: [FlowStandup] = []
    @Published var yesterday = ""
    @Published var today = ""
    @Published var blockers = ""
    @Published var drafting = false
    @Published var submitting = false
    @Published var message: String?

    private var client: FlowClient?
    func configure(_ client: FlowClient?) { self.client = client }

    func load() async {
        recent = (try? await client?.myStandups()) ?? []
    }

    func draft() async {
        guard let client else { return }
        drafting = true
        if let text = try? await client.draftStandup(), !text.isEmpty {
            // The AI draft summarizes the day's tracked work — seed "yesterday".
            yesterday = text
        }
        drafting = false
    }

    func submit() async {
        guard let client else { return }
        submitting = true
        do {
            try await client.submitStandup(
                StandupRequest(yesterdaySummary: yesterday, todayPlan: today, blockersSummary: blockers)
            )
            yesterday = ""; today = ""; blockers = ""
            message = "Submitted"
            await load()
        } catch {
            message = "Couldn't submit standup"
        }
        submitting = false
    }
}

struct StandupsView: View {
    @ObservedObject var app: AppState
    @StateObject private var standups = StandupsState()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Standups").font(.title2).bold()
                    Spacer()
                    Button {
                        Task { await standups.draft() }
                    } label: {
                        Label(standups.drafting ? "Drafting…" : "AI Draft", systemImage: "sparkles")
                    }
                    .disabled(standups.drafting)
                }

                field("Yesterday", text: $standups.yesterday)
                field("Today", text: $standups.today)
                field("Blockers", text: $standups.blockers)

                HStack {
                    if let m = standups.message { Text(m).font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                    Button("Submit standup") { Task { await standups.submit() } }
                        .keyboardShortcut(.defaultAction)
                        .disabled(standups.submitting)
                }

                Divider()
                Text("Recent").font(.headline)
                ForEach(standups.recent) { s in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.standupDate ?? String((s.submittedAt ?? "").prefix(10)))
                            .font(.caption).foregroundStyle(.secondary)
                        if let y = s.yesterdaySummary, !y.isEmpty { Text("Yesterday: \(y)").font(.callout).lineLimit(2) }
                        if let t = s.todayPlan, !t.isEmpty { Text("Today: \(t)").font(.callout).lineLimit(2) }
                    }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.secondary.opacity(0.06))
                    .cornerRadius(8)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task { standups.configure(app.flowClient); await standups.load() }
    }

    private func field(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.subheadline).bold()
            TextEditor(text: text)
                .frame(minHeight: 60)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.25)))
        }
    }
}
