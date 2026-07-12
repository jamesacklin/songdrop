import Foundation

struct SearchResult: Codable, Identifiable, Hashable {
    let id: Int
    let title: String
    let artist: String
    let album: String
    let cover: String?
    let duration: Int?
    let source: String?      // "deezer" | "itunes"
    let coverXl: String?     // full-size art URL for tagging
    let trackNo: Int?
    let year: String?

    var isDeezer: Bool { (source ?? "deezer") == "deezer" }
}

struct SearchResponse: Codable {
    let results: [SearchResult]
}

struct TrackRequest: Codable, Identifiable, Hashable {
    let id: Int
    let artist: String
    let title: String
    let album: String?
    let status: String
    let detail: String?
    let error: String?
    let playlist: String?
    let filePath: String?
    let createdAt: Double?
    let nextRetryAt: Double?
    let retryCount: Int?

    /// Actively being worked on right now (spinner-worthy).
    var isInFlight: Bool {
        !["done", "failed", "queued", "waiting"].contains(status)
    }

    var isDeletable: Bool {
        ["queued", "done", "failed", "waiting"].contains(status)
    }

    var isRetryable: Bool {
        ["failed", "waiting"].contains(status)
    }
}

struct RequestsResponse: Codable {
    let requests: [TrackRequest]
    /// Server unix time at response; used to correct countdowns for clock skew.
    let now: Double?
}

struct PlaylistsResponse: Codable {
    let playlists: [String]
}

struct NewRequest: Codable {
    let artist: String
    let title: String
    let album: String?
    let deezerId: Int?
    let playlist: String?
    var coverUrl: String? = nil
    var trackNo: Int? = nil
    var year: String? = nil
    var youtubeUrl: String? = nil
    var discNo: Int? = nil
}

struct AlbumTrack: Codable, Identifiable, Hashable {
    let position: Int      // unique, sequential across discs — stable list id
    let title: String
    let trackNo: Int?      // per-disc track number for tagging
    let discNo: Int?       // set only for multi-disc releases
    var id: Int { position }
}

struct AlbumResponse: Codable, Hashable {
    let title: String
    let artist: String
    let year: String?
    let cover: String?
    let coverXl: String?
    let source: String?
    let tracks: [AlbumTrack]
}

struct BulkResponse: Codable, Hashable {
    let created: Int
    let skipped: Int
}

struct ComponentStatus: Codable, Hashable {
    let ok: Bool
    let detail: String?
}

/// slskd/Plex connection settings managed on the server (PUT /api/config).
struct ServerConfig: Codable, Hashable {
    var slskdUrl: String?
    var slskdApiKey: String?
    var slskdUsername: String?
    var slskdPassword: String?
    var plexUrl: String?
    var plexToken: String?
    var plexSection: String?
}

struct ServerStatus: Codable, Hashable {
    let ok: Bool
    let slskd: ComponentStatus
    let plex: ComponentStatus
}
