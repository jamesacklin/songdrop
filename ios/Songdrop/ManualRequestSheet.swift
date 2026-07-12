import SwiftUI

/// Freeform request for tracks the metadata catalog doesn't list — obscure
/// remixes, CD-only tracks. Sends the details to your server to locate.
struct ManualRequestSheet: View {
    var prefillTitle: String = ""
    var onAdded: () -> Void

    @Environment(\.dismiss) private var dismiss
    @AppStorage("defaultPlaylist") private var defaultPlaylist = ""

    @State private var artist = ""
    @State private var title = ""
    @State private var album = ""
    @State private var youtubeURL = ""
    @State private var playlists: [String] = []
    @State private var selectedPlaylist = ""
    @State private var newPlaylistName = ""
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    private let createNew = "__new__"

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Artist (required)", text: $artist)
                        .textInputAutocapitalization(.words)
                    TextField("Song title (required)", text: $title)
                        .textInputAutocapitalization(.words)
                    TextField("Album (optional)", text: $album)
                        .textInputAutocapitalization(.words)
                } footer: {
                    Text("Your server matches on the artist and exact title — include qualifiers like “(Indifferent Remix)” if you want a specific version. Album is used for tagging and the folder name.")
                }

                Section {
                    TextField("Direct source link (optional)", text: $youtubeURL)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } footer: {
                    Text("If your server supports fetching from a specific web link, paste it here to point at an exact source. Leave empty to let your server locate the track.")
                }

                Section("Playlist (optional)") {
                    Picker("Add to playlist", selection: $selectedPlaylist) {
                        Text("None").tag("")
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
            .navigationTitle("Manual Request")
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
                            .disabled(artist.trimmingCharacters(in: .whitespaces).isEmpty
                                      || title.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .task {
                title = prefillTitle
                await loadPlaylists()
            }
        }
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
            let trimmedAlbum = album.trimmingCharacters(in: .whitespaces)
            let trimmedURL = youtubeURL.trimmingCharacters(in: .whitespaces)
            _ = try await APIClient.shared.addRequest(
                NewRequest(
                    artist: artist.trimmingCharacters(in: .whitespaces),
                    title: title.trimmingCharacters(in: .whitespaces),
                    album: trimmedAlbum.isEmpty ? nil : trimmedAlbum,
                    deezerId: nil,
                    playlist: chosenPlaylist,
                    youtubeUrl: trimmedURL.isEmpty ? nil : trimmedURL
                )
            )
            if let playlist = chosenPlaylist { defaultPlaylist = playlist }
            onAdded()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
