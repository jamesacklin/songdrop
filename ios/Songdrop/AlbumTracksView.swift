import SwiftUI

/// Full album tracklist (MusicBrainz-backed, so it includes tracks streaming
/// catalogs omit). Tap any track to request it into the current playlist —
/// multiple tracks can be queued in one visit.
struct AlbumTracksView: View {
    let artist: String
    let albumName: String
    /// Reads the playlist currently chosen in the parent sheet at request time.
    var playlist: () -> String?

    @State private var album: AlbumResponse?
    @State private var isLoading = true
    @State private var loadError: String?
    @State private var requestedPositions: Set<Int> = []
    @State private var pendingPosition: Int?
    @State private var isBulkAdding = false
    @State private var bulkSummary: String?
    @State private var errorMessage: String?

    var body: some View {
        Group {
            if isLoading {
                ProgressView("Looking up album…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let album {
                List {
                    Section {
                        HStack(spacing: 12) {
                            AsyncImage(url: album.cover.flatMap(URL.init)) { image in
                                image.resizable().aspectRatio(contentMode: .fill)
                            } placeholder: {
                                ZStack {
                                    Color.secondary.opacity(0.2)
                                    Image(systemName: "opticaldisc").foregroundStyle(.secondary)
                                }
                            }
                            .frame(width: 72, height: 72)
                            .clipShape(RoundedRectangle(cornerRadius: 8))

                            VStack(alignment: .leading, spacing: 2) {
                                Text(album.title).font(.headline)
                                Text(album.artist).foregroundStyle(.secondary)
                                HStack(spacing: 6) {
                                    if let year = album.year { Text(year) }
                                    Text("\(album.tracks.count) tracks")
                                    if album.source == "musicbrainz" {
                                        Text("via MusicBrainz")
                                    }
                                }
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                            }
                        }

                        Button {
                            Task { await requestAll(album) }
                        } label: {
                            HStack {
                                if isBulkAdding {
                                    ProgressView()
                                } else if allRequested(album) {
                                    Label("All Tracks Requested", systemImage: "checkmark.circle.fill")
                                } else {
                                    Label("Request All \(album.tracks.count) Tracks", systemImage: "plus.square.on.square")
                                }
                                Spacer()
                            }
                        }
                        .disabled(isBulkAdding || allRequested(album))
                    } footer: {
                        if let bulkSummary {
                            Text(bulkSummary)
                        }
                    }
                    Section {
                        ForEach(album.tracks) { track in
                            Button {
                                Task { await request(track, from: album) }
                            } label: {
                                HStack {
                                    Text("\(track.position)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .frame(width: 24, alignment: .trailing)
                                    Text(track.title).lineLimit(2)
                                    Spacer()
                                    if requestedPositions.contains(track.position) {
                                        Image(systemName: "checkmark.circle.fill")
                                            .foregroundStyle(.green)
                                    } else if pendingPosition == track.position {
                                        ProgressView()
                                    } else {
                                        Image(systemName: "plus.circle")
                                            .foregroundStyle(.tint)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                            .disabled(requestedPositions.contains(track.position) || pendingPosition != nil || isBulkAdding)
                        }
                    } footer: {
                        Text("Tap a track to add it to your library\(playlist().map { " and “\($0)”" } ?? "").")
                    }
                }
            } else {
                ContentUnavailableView(
                    "Album not found",
                    systemImage: "opticaldisc",
                    description: Text(loadError ?? "Neither MusicBrainz nor Deezer knows this album.")
                )
            }
        }
        .navigationTitle(albumName)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .alert("Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private func load() async {
        defer { isLoading = false }
        do {
            album = try await APIClient.shared.album(artist: artist, album: albumName)
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func allRequested(_ album: AlbumResponse) -> Bool {
        requestedPositions.count >= album.tracks.count
    }

    private func requestAll(_ album: AlbumResponse) async {
        isBulkAdding = true
        defer { isBulkAdding = false }
        let pending = album.tracks.filter { !requestedPositions.contains($0.position) }
        let batch = pending.map { track in
            NewRequest(
                artist: album.artist,
                title: track.title,
                album: album.title,
                deezerId: nil,
                playlist: playlist(),
                coverUrl: album.coverXl,
                trackNo: track.trackNo ?? track.position,
                year: album.year,
                discNo: track.discNo
            )
        }
        do {
            // The server caps bulk at 100 items; chunk so box sets don't 422.
            var created = 0, skipped = 0
            for chunk in stride(from: 0, to: batch.count, by: 100).map({ start in
                Array(batch[start..<min(start + 100, batch.count)])
            }) {
                let result = try await APIClient.shared.bulkAdd(chunk)
                created += result.created
                skipped += result.skipped
            }
            requestedPositions.formUnion(pending.map(\.position))
            var summary = "Queued \(created) track\(created == 1 ? "" : "s")"
            if skipped > 0 {
                summary += " — \(skipped) already requested or in your library"
            }
            bulkSummary = summary + "."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func request(_ track: AlbumTrack, from album: AlbumResponse) async {
        pendingPosition = track.position
        defer { pendingPosition = nil }
        do {
            _ = try await APIClient.shared.addRequest(
                NewRequest(
                    artist: album.artist,
                    title: track.title,
                    album: album.title,
                    deezerId: nil,
                    playlist: playlist(),
                    coverUrl: album.coverXl,
                    trackNo: track.trackNo ?? track.position,
                    year: album.year,
                    discNo: track.discNo
                )
            )
            requestedPositions.insert(track.position)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
