import SwiftUI

struct AddRequestSheet: View {
    let track: SearchResult
    var onAdded: () -> Void

    @Environment(\.dismiss) private var dismiss
    @AppStorage("defaultPlaylist") private var defaultPlaylist = ""

    @State private var playlists: [String] = []
    @State private var selectedPlaylist = ""
    @State private var newPlaylistName = ""
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @State private var detent: PresentationDetent = .medium
    @State private var detentBeforeAlbum: PresentationDetent?

    private let noPlaylist = ""
    private let createNew = "__new__"

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 12) {
                        AsyncImage(url: track.cover.flatMap(URL.init)) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: {
                            Color.secondary.opacity(0.2)
                        }
                        .frame(width: 64, height: 64)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                        VStack(alignment: .leading, spacing: 2) {
                            Text(track.title).font(.headline)
                            Text(track.artist).foregroundStyle(.secondary)
                            Text(track.album).font(.caption).foregroundStyle(.tertiary)
                        }
                    }
                }

                if !track.album.isEmpty {
                    Section {
                        NavigationLink {
                            AlbumTracksView(
                                artist: track.artist,
                                albumName: track.album,
                                playlist: { chosenPlaylist }
                            )
                            // Tracklists need room: go full-height on push,
                            // snap back to the prior height on pop.
                            .onAppear {
                                if detentBeforeAlbum == nil { detentBeforeAlbum = detent }
                                detent = .large
                            }
                            .onDisappear {
                                if let previous = detentBeforeAlbum {
                                    detent = previous
                                    detentBeforeAlbum = nil
                                }
                            }
                        } label: {
                            Label("View Full Album", systemImage: "opticaldisc")
                        }
                    } footer: {
                        Text("The complete tracklist — including versions streaming services leave out.")
                    }
                }

                Section("Playlist (optional)") {
                    Picker("Add to playlist", selection: $selectedPlaylist) {
                        Text("None").tag(noPlaylist)
                        ForEach(playlists, id: \.self) { name in
                            Text(name).tag(name)
                        }
                        Text("New playlist…").tag(createNew)
                    }
                    if selectedPlaylist == createNew {
                        TextField("New playlist name", text: $newPlaylistName)
                            .textInputAutocapitalization(.words)
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Add to Library")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSubmitting {
                        ProgressView()
                    } else {
                        Button("Add") { Task { await submit() } }
                            .bold()
                    }
                }
            }
            .task { await loadPlaylists() }
        }
        .presentationDetents([.medium, .large], selection: $detent)
    }

    private var chosenPlaylist: String? {
        if selectedPlaylist == createNew {
            let name = newPlaylistName.trimmingCharacters(in: .whitespaces)
            return name.isEmpty ? nil : name
        }
        return selectedPlaylist.isEmpty ? nil : selectedPlaylist
    }

    private func loadPlaylists() async {
        playlists = (try? await APIClient.shared.playlists()) ?? []
        if !defaultPlaylist.isEmpty, playlists.contains(defaultPlaylist) {
            selectedPlaylist = defaultPlaylist
        }
    }

    private func submit() async {
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            _ = try await APIClient.shared.addRequest(
                NewRequest(
                    artist: track.artist,
                    title: track.title,
                    album: track.album.isEmpty ? nil : track.album,
                    deezerId: track.isDeezer ? track.id : nil,
                    playlist: chosenPlaylist,
                    coverUrl: track.isDeezer ? nil : track.coverXl,
                    trackNo: track.isDeezer ? nil : track.trackNo,
                    year: track.isDeezer ? nil : track.year
                )
            )
            if let playlist = chosenPlaylist { defaultPlaylist = playlist }
            onAdded()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
