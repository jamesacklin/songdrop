import SwiftUI

struct SearchView: View {
    var onRequested: () -> Void

    @State private var query = ""
    @State private var results: [SearchResult] = []
    @State private var isSearching = false
    @State private var errorMessage: String?
    @State private var selectedTrack: SearchResult?
    @State private var showManualSheet = false
    @State private var hasSearched = false

    var body: some View {
        NavigationStack {
            Group {
                if isSearching {
                    ProgressView("Searching…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if results.isEmpty {
                    if hasSearched {
                        ContentUnavailableView {
                            Label("No matches", systemImage: "magnifyingglass")
                        } description: {
                            Text("We couldn't find this one in the metadata catalog. You can still send a request to your server by entering the artist and title yourself.")
                        } actions: {
                            Button("Request Manually") { showManualSheet = true }
                                .buttonStyle(.borderedProminent)
                        }
                    } else {
                        ContentUnavailableView(
                            "Find a song",
                            systemImage: "music.note.list",
                            description: Text("Search by song title, artist, or both — e.g. “Midnight City M83”.")
                        )
                    }
                } else {
                    List {
                        ForEach(results) { track in
                            Button {
                                selectedTrack = track
                            } label: {
                                TrackRow(track: track)
                            }
                            .buttonStyle(.plain)
                        }
                        Section {
                            Button {
                                showManualSheet = true
                            } label: {
                                Label("Not here? Request manually…", systemImage: "square.and.pencil")
                            }
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Songdrop")
            .searchable(text: $query, prompt: "Song, artist…")
            .onSubmit(of: .search) { Task { await runSearch() } }
            .onChange(of: query) { _, newValue in
                if newValue.trimmingCharacters(in: .whitespaces).isEmpty {
                    results = []
                    hasSearched = false
                }
            }
            .alert("Search failed", isPresented: .constant(errorMessage != nil)) {
                Button("OK") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
            .sheet(item: $selectedTrack) { track in
                AddRequestSheet(track: track) {
                    selectedTrack = nil
                    onRequested()
                }
            }
            .sheet(isPresented: $showManualSheet) {
                ManualRequestSheet(prefillTitle: query) {
                    showManualSheet = false
                    onRequested()
                }
            }
        }
    }

    private func runSearch() async {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        isSearching = true
        defer { isSearching = false }
        do {
            results = try await APIClient.shared.search(q)
            hasSearched = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct TrackRow: View {
    let track: SearchResult

    var body: some View {
        HStack(spacing: 12) {
            AsyncImage(url: track.cover.flatMap(URL.init)) { image in
                image.resizable().aspectRatio(contentMode: .fill)
            } placeholder: {
                ZStack {
                    Color.secondary.opacity(0.2)
                    Image(systemName: "music.note").foregroundStyle(.secondary)
                }
            }
            .frame(width: 52, height: 52)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 2) {
                Text(track.title).font(.body).lineLimit(1)
                Text(track.artist).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                Text(track.album).font(.caption).foregroundStyle(.tertiary).lineLimit(1)
            }
            Spacer()
            Image(systemName: "plus.circle.fill")
                .font(.title3)
                .foregroundStyle(.tint)
        }
        .contentShape(Rectangle())
    }
}
