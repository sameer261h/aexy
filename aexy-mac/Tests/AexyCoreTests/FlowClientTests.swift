import XCTest
@testable import AexyCore

// Pure request-building tests for the Aexy Flow API client (no network).
final class FlowClientTests: XCTestCase {
    private func client() -> FlowClient {
        FlowClient(
            apiBaseURL: URL(string: "https://server.aexy.io/api/v1")!,
            bearerToken: "tok123"
        )
    }

    func testGetRequestCarriesPathQueryAndAuth() {
        let req = client().makeRequest(
            "GET",
            "developers/me/assigned-tasks",
            query: [URLQueryItem(name: "include_done", value: "false")]
        )
        XCTAssertEqual(req.httpMethod, "GET")
        let url = req.url!.absoluteString
        XCTAssertTrue(url.hasPrefix("https://server.aexy.io/api/v1/developers/me/assigned-tasks"))
        XCTAssertTrue(url.contains("include_done=false"))
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer tok123")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Accept"), "application/json")
        XCTAssertNil(req.httpBody)
    }

    func testPostRequestSetsBodyAndContentType() throws {
        let body = try FlowClient.encoder.encode(LogTimeRequest(durationMinutes: 30, taskId: "t1"))
        let req = client().makeRequest("POST", "tracking/time", body: body)
        XCTAssertEqual(req.httpMethod, "POST")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Content-Type"), "application/json")
        XCTAssertNotNil(req.httpBody)
        // snake_case encoding: durationMinutes -> duration_minutes, taskId -> task_id
        let json = String(data: req.httpBody!, encoding: .utf8)!
        XCTAssertTrue(json.contains("duration_minutes"))
        XCTAssertTrue(json.contains("task_id"))
    }

    func testStatusPatchPathIncludesIds() {
        let req = client().makeRequest("PATCH", "workspaces/ws1/tasks/task1/status")
        XCTAssertEqual(req.httpMethod, "PATCH")
        XCTAssertTrue(req.url!.absoluteString.hasSuffix("/workspaces/ws1/tasks/task1/status"))
    }

    func testTaskDecodesIgnoringUnknownFields() throws {
        // The real API returns many extra fields; the model must tolerate them.
        let raw = """
        {"id":"t1","title":"Fix bug","status":"in_progress","story_points":3,"extra":true}
        """.data(using: .utf8)!
        let task = try FlowClient.decoder.decode(FlowTask.self, from: raw)
        XCTAssertEqual(task.id, "t1")
        XCTAssertEqual(task.status, "in_progress")
    }

    func testBoardTaskDecodesExtendedFields() throws {
        let raw = """
        {"id":"t1","title":"Ship board","status":"todo","status_id":"st_9","priority":"high",
         "story_points":5,"labels":["ui","mac"],"assignee_name":"Dev","sprint_id":"sp1",
         "end_date":"2026-07-01T00:00:00Z","identifier":"WS-12","unknown":true}
        """.data(using: .utf8)!
        let task = try FlowClient.decoder.decode(FlowTask.self, from: raw)
        XCTAssertEqual(task.statusId, "st_9")
        XCTAssertEqual(task.storyPoints, 5)
        XCTAssertEqual(task.labels, ["ui", "mac"])
        XCTAssertEqual(task.assigneeName, "Dev")
        XCTAssertEqual(task.identifier, "WS-12")
    }

    func testTaskStatusDecodes() throws {
        let raw = """
        {"id":"st1","name":"In Review","slug":"review","category":"in_progress","color":"#abc","position":2}
        """.data(using: .utf8)!
        let s = try FlowClient.decoder.decode(FlowTaskStatus.self, from: raw)
        XCTAssertEqual(s.slug, "review")
        XCTAssertEqual(s.category, "in_progress")
        XCTAssertEqual(s.position, 2)
    }

    func testTaskUpdateFieldsEncodesSnakeCase() throws {
        var f = TaskUpdateFields()
        f.storyPoints = 8
        f.assigneeId = "dev1"
        let json = String(data: try FlowClient.encoder.encode(f), encoding: .utf8)!
        XCTAssertTrue(json.contains("story_points"))
        XCTAssertTrue(json.contains("assignee_id"))
    }

    func testProjectsResponseUnwraps() throws {
        let raw = """
        {"projects":[{"id":"p1","name":"Core","slug":"core","color":"#111"}]}
        """.data(using: .utf8)!
        let resp = try FlowClient.decoder.decode(FlowProjectsResponse.self, from: raw)
        XCTAssertEqual(resp.projects.first?.name, "Core")
    }
}
