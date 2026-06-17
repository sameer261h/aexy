import Foundation
import CryptoKit
import Security

// Enterprise offline read: cache document detail (title + plain text) on disk,
// encrypted at rest with AES-GCM. The 256-bit key lives in the Keychain, so the
// cache files are unreadable as plaintext. Only docs the server actually returned
// are cached (permission-faithful — never widens access).

public struct CachedDoc: Codable, Sendable {
    public let detail: DocDetail
    public let cachedAt: Date
}

public final class DocCache: @unchecked Sendable {
    private let dir: URL
    private let key: SymmetricKey

    public init() {
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Aexy/doccache", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        self.dir = base
        self.key = DocCache.loadOrCreateKey()
    }

    private func fileURL(_ id: String) -> URL {
        // Hash the id so filenames don't leak doc UUIDs.
        let digest = SHA256.hash(data: Data(id.utf8)).map { String(format: "%02x", $0) }.joined()
        return dir.appendingPathComponent(digest + ".enc")
    }

    public func save(_ detail: DocDetail) {
        guard let plain = try? JSONEncoder().encode(CachedDoc(detail: detail, cachedAt: Date())),
              let sealed = try? AES.GCM.seal(plain, using: key).combined else { return }
        try? sealed.write(to: fileURL(detail.id), options: .atomic)
    }

    public func load(_ id: String) -> CachedDoc? {
        guard let blob = try? Data(contentsOf: fileURL(id)),
              let box = try? AES.GCM.SealedBox(combined: blob),
              let plain = try? AES.GCM.open(box, using: key),
              let cached = try? JSONDecoder().decode(CachedDoc.self, from: plain) else { return nil }
        return cached
    }

    /// Wipe the cache (call on sign-out so a former session leaves nothing).
    public func clear() {
        try? FileManager.default.removeItem(at: dir)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    // MARK: - Keychain-backed key

    private static let keyService = "io.aexy.doccache"
    private static let keyAccount = "cache-key"

    private static func loadOrCreateKey() -> SymmetricKey {
        if let data = readKey(), data.count == 32 { return SymmetricKey(data: data) }
        let key = SymmetricKey(size: .bits256)
        let data = key.withUnsafeBytes { Data(Array($0)) }
        writeKey(data)
        return key
    }

    private static func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keyService,
            kSecAttrAccount as String: keyAccount,
        ]
    }

    private static func readKey() -> Data? {
        var query = baseQuery()
        query[kSecReturnData as String] = kCFBooleanTrue
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess else { return nil }
        return item as? Data
    }

    private static func writeKey(_ data: Data) {
        SecItemDelete(baseQuery() as CFDictionary)
        var attrs = baseQuery()
        attrs[kSecValueData as String] = data
        attrs[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(attrs as CFDictionary, nil)
    }
}

// Minimal local audit log for compliance: doc opens / edits / exports.
public final class DocAudit: @unchecked Sendable {
    private let url: URL

    public init() {
        let base = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Aexy", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        self.url = base.appendingPathComponent("doc-audit.log")
    }

    public func log(_ action: String, docId: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date()))\t\(action)\t\(docId)\n"
        guard let data = line.data(using: .utf8) else { return }
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(data)
            try? handle.close()
        } else {
            try? data.write(to: url, options: .atomic)
        }
    }
}
