import SwiftUI
import AppKit
import Combine
import AexyCore

@MainActor
final class TimeState: ObservableObject {
    @Published var entries: [FlowTimeEntry] = []
    @Published var runningStart: Date?
    @Published var runningNote = ""
    @Published var loading = false

    private var client: FlowClient?
    func configure(_ client: FlowClient?) { self.client = client }

    func load() async {
        guard let client else { return }
        loading = true
        let r = try? await client.myTimeEntries(start: Self.ymd(-6), end: Self.ymd(0))
        entries = r?.entries ?? []
        loading = false
    }

    func start(note: String) {
        runningNote = note
        runningStart = Date()
    }

    func stop() async {
        guard let client, let start = runningStart else { return }
        let minutes = max(1, Int(Date().timeIntervalSince(start) / 60))
        _ = try? await client.logTime(
            LogTimeRequest(durationMinutes: minutes, description: runningNote.isEmpty ? nil : runningNote)
        )
        runningStart = nil
        runningNote = ""
        await load()
    }

    func logManual(minutes: Int, note: String) async {
        guard let client, minutes > 0 else { return }
        _ = try? await client.logTime(
            LogTimeRequest(durationMinutes: minutes, description: note.isEmpty ? nil : note)
        )
        await load()
    }

    var totalMinutes: Int { entries.reduce(0) { $0 + $1.durationMinutes } }

    /// Invoice-friendly CSV grouped by day.
    func csv() -> String {
        var rows = ["date,minutes,hours,description"]
        for e in entries.sorted(by: { ($0.entryDate ?? "") < ($1.entryDate ?? "") }) {
            let hours = String(format: "%.2f", Double(e.durationMinutes) / 60)
            let desc = (e.description ?? "").replacingOccurrences(of: ",", with: " ")
            rows.append("\(e.entryDate ?? ""),\(e.durationMinutes),\(hours),\(desc)")
        }
        return rows.joined(separator: "\n") + "\n"
    }

    static func ymd(_ offset: Int) -> String {
        let d = Calendar.current.date(byAdding: .day, value: offset, to: Date()) ?? Date()
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }
}

struct TimeView: View {
    @ObservedObject var app: AppState
    @StateObject private var time = TimeState()
    @State private var manualMinutes = ""
    @State private var manualNote = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Time").font(.title2).bold()

                // Timer
                GroupBox("Timer") {
                    VStack(alignment: .leading, spacing: 8) {
                        TextField("What are you working on?", text: $time.runningNote)
                            .textFieldStyle(.roundedBorder)
                            .disabled(time.runningStart != nil)
                        HStack {
                            if let start = time.runningStart {
                                Label("Running since \(start.formatted(date: .omitted, time: .shortened))",
                                      systemImage: "record.circle").foregroundStyle(.red)
                                Spacer()
                                Button("Stop & log") { Task { await time.stop() } }
                            } else {
                                Button("Start timer") { time.start(note: time.runningNote) }
                                Spacer()
                            }
                        }
                    }.padding(6)
                }

                // Manual entry
                GroupBox("Log time manually") {
                    HStack {
                        TextField("Minutes", text: $manualMinutes).frame(width: 80).textFieldStyle(.roundedBorder)
                        TextField("Description", text: $manualNote).textFieldStyle(.roundedBorder)
                        Button("Add") {
                            Task {
                                await time.logManual(minutes: Int(manualMinutes) ?? 0, note: manualNote)
                                manualMinutes = ""; manualNote = ""
                            }
                        }.disabled((Int(manualMinutes) ?? 0) <= 0)
                    }.padding(6)
                }

                // Timesheet
                HStack {
                    Text("Last 7 days — \(fmtMinutes(time.totalMinutes))").font(.headline)
                    Spacer()
                    Button { exportCSV() } label: { Label("Export CSV", systemImage: "square.and.arrow.up") }
                        .disabled(time.entries.isEmpty)
                }
                if time.loading { ProgressView() }
                ForEach(time.entries) { e in
                    HStack {
                        Text(e.entryDate ?? "—").font(.caption).foregroundStyle(.secondary).frame(width: 90, alignment: .leading)
                        Text(e.description ?? "—").lineLimit(1)
                        Spacer()
                        Text(fmtMinutes(e.durationMinutes)).tabular()
                    }
                    .padding(.vertical, 4)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task { time.configure(app.flowClient); await time.load() }
    }

    private func fmtMinutes(_ m: Int) -> String {
        m < 60 ? "\(m)m" : "\(m / 60)h \(m % 60)m"
    }

    private func exportCSV() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "aexy-timesheet.csv"
        panel.begin { resp in
            if resp == .OK, let url = panel.url {
                try? time.csv().data(using: .utf8)?.write(to: url)
            }
        }
    }
}

private extension Text {
    func tabular() -> some View { self.monospacedDigit().foregroundStyle(.secondary) }
}
