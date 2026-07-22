import SwiftUI

/// First-run setup. Frames Songdrop honestly for what it is: a remote control
/// for a music library server you run yourself. The app does nothing until it's
/// pointed at your own server — there is no built-in catalog or content.
struct OnboardingView: View {
    var onConnected: () -> Void

    @AppStorage("serverURL") private var serverURL = ""
    @AppStorage("apiKey") private var apiKey = ""

    @State private var isConnecting = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        Image(systemName: "music.note.house.fill")
                            .font(.system(size: 44))
                            .foregroundStyle(.tint)
                        Text("Welcome to Songdrop")
                            .font(.largeTitle.bold())
                        Text("A remote for your personal music library server.")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 16) {
                        InfoRow(
                            icon: "server.rack",
                            title: "Connect to your own server",
                            detail: "Songdrop is a companion app. It talks only to a Songdrop server that you run at home — it has no catalog or content of its own and does nothing until it's connected."
                        )
                        InfoRow(
                            icon: "magnifyingglass",
                            title: "Search and request",
                            detail: "Look up a track's details and send a request to your server. Your server handles finding, tagging, and filing it into your library."
                        )
                        InfoRow(
                            icon: "checkmark.seal",
                            title: "Your library, your rules",
                            detail: "Use it to organize music you own, tidy metadata, and manage playlists on your own Plex library. You're responsible for what you add and for respecting copyright."
                        )
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text("Connect")
                            .font(.headline)
                        TextField("Server address (https://…)", text: $serverURL)
                            .keyboardType(.URL)
                            .textContentType(.URL)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .padding(12)
                            .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
                        SecureField("Access key", text: $apiKey)
                            .padding(12)
                            .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))

                        if let errorMessage {
                            Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                                .font(.callout)
                                .foregroundStyle(.red)
                        }

                        Button {
                            Task { await connect() }
                        } label: {
                            HStack {
                                Spacer()
                                if isConnecting {
                                    ProgressView().tint(.white)
                                } else {
                                    Text("Connect").bold()
                                }
                                Spacer()
                            }
                            .padding(.vertical, 6)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(serverURL.isEmpty || isConnecting)

                        Text("Don't have a server yet? Songdrop is open-source software you install on your own machine. See the project's setup guide to get started.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding()
            }
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func connect() async {
        isConnecting = true
        defer { isConnecting = false }
        errorMessage = nil
        do {
            // getConfig requires the access key, so a wrong key fails here rather
            // than passing against the unauthenticated health check.
            _ = try await APIClient.shared.getConfig()
            onConnected()
        } catch APIError.server(401, _) {
            errorMessage = "That access key was rejected. Check it and try again."
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct InfoRow: View {
    let icon: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(.tint)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }
}
