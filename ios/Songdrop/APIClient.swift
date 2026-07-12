import Foundation

extension CharacterSet {
    /// urlQueryAllowed minus the sub-delimiters that carry meaning in a query
    /// value ("+" decodes to space, "&"/"=" separate params).
    static let sdQueryValue = CharacterSet.urlQueryAllowed.subtracting(
        CharacterSet(charactersIn: "+&=?")
    )
}

enum APIError: LocalizedError {
    case notConfigured
    case badURL
    case server(Int, String)

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "Set your server URL in Settings."
        case .badURL: return "The server URL is invalid."
        case .server(let code, let message): return "Server error \(code): \(message)"
        }
    }
}

struct APIClient {
    static var shared: APIClient {
        APIClient(
            baseURL: UserDefaults.standard.string(forKey: "serverURL") ?? "",
            apiKey: UserDefaults.standard.string(forKey: "apiKey") ?? ""
        )
    }

    let baseURL: String
    let apiKey: String

    private func request(_ path: String, method: String = "GET", body: Data? = nil) throws -> URLRequest {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw APIError.notConfigured }
        guard let url = URL(string: trimmed.hasSuffix("/") ? String(trimmed.dropLast()) + path : trimmed + path) else {
            throw APIError.badURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.httpBody = body
        if !apiKey.isEmpty {
            req.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        }
        if body != nil {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return req
    }

    private func send<T: Decodable>(_ req: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let message = String(data: data, encoding: .utf8) ?? ""
            throw APIError.server(status, String(message.prefix(200)))
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: data)
    }

    /// Builds a query string that also percent-encodes "+" — URLComponents
    /// leaves it literal, and servers decode a literal "+" as a space, so a
    /// title like "+ (Ed Sheeran)" or "C++" would otherwise search wrong.
    private func queryString(_ items: [String: String]) -> String {
        items.map { key, value in
            let encoded = value
                .addingPercentEncoding(withAllowedCharacters: .sdQueryValue) ?? value
            return "\(key)=\(encoded)"
        }.joined(separator: "&")
    }

    func search(_ query: String) async throws -> [SearchResult] {
        let req = try request("/api/search?\(queryString(["q": query]))")
        return try await send(req, as: SearchResponse.self).results
    }

    func requests() async throws -> RequestsResponse {
        let req = try request("/api/requests")
        return try await send(req, as: RequestsResponse.self)
    }

    func clear(statuses: [String]) async throws -> Int {
        struct ClearBody: Codable { let statuses: [String] }
        struct Cleared: Codable { let cleared: Int }
        let body = try JSONEncoder().encode(ClearBody(statuses: statuses))
        let req = try request("/api/requests/clear", method: "POST", body: body)
        return try await send(req, as: Cleared.self).cleared
    }

    func album(artist: String, album: String) async throws -> AlbumResponse {
        let req = try request("/api/album?\(queryString(["artist": artist, "album": album]))")
        return try await send(req, as: AlbumResponse.self)
    }

    func playlists() async throws -> [String] {
        let req = try request("/api/playlists")
        return try await send(req, as: PlaylistsResponse.self).playlists
    }

    func addRequest(_ newRequest: NewRequest) async throws -> TrackRequest {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try encoder.encode(newRequest)
        let req = try request("/api/requests", method: "POST", body: body)
        return try await send(req, as: TrackRequest.self)
    }

    func bulkAdd(_ newRequests: [NewRequest]) async throws -> BulkResponse {
        struct BulkBody: Codable { let requests: [NewRequest] }
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try encoder.encode(BulkBody(requests: newRequests))
        let req = try request("/api/requests/bulk", method: "POST", body: body)
        return try await send(req, as: BulkResponse.self)
    }

    func retry(_ id: Int) async throws -> TrackRequest {
        let req = try request("/api/requests/\(id)/retry", method: "POST")
        return try await send(req, as: TrackRequest.self)
    }

    func delete(_ id: Int, purge: Bool = false) async throws {
        let req = try request("/api/requests/\(id)\(purge ? "?purge=true" : "")", method: "DELETE")
        let (data, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw APIError.server(status, String(data: data, encoding: .utf8) ?? "")
        }
    }

    func health() async throws -> Bool {
        struct Health: Codable { let ok: Bool }
        let req = try request("/api/health")
        return try await send(req, as: Health.self).ok
    }

    func status() async throws -> ServerStatus {
        let req = try request("/api/status")
        return try await send(req, as: ServerStatus.self)
    }

    func getConfig() async throws -> ServerConfig {
        let req = try request("/api/config")
        return try await send(req, as: ServerConfig.self)
    }

    func saveConfig(_ config: ServerConfig) async throws -> ServerConfig {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try encoder.encode(config)
        let req = try request("/api/config", method: "PUT", body: body)
        return try await send(req, as: ServerConfig.self)
    }
}
