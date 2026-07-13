import SwiftUI

struct SettingsView: View {
    @AppStorage("serverURL") private var serverURL = ""
    @AppStorage("apiKey") private var apiKey = ""
    @AppStorage("defaultPlaylist") private var defaultPlaylist = ""

    @State private var serverResult: TestResult?
    @State private var serverStatus: ServerStatus?
    @State private var isTestingServer = false
    @State private var configLoaded = false

    // slskd
    @State private var slskdUrl = ""
    @State private var slskdUsername = ""
    @State private var slskdPassword = ""
    @State private var slskdApiKey = ""
    @State private var isSavingSlskd = false
    @State private var slskdError: String?

    // Plex
    @State private var plexUrl = ""
    @State private var plexToken = ""
    @State private var plexSection = ""
    @State private var isSavingPlex = false
    @State private var plexError: String?

    enum TestResult {
        case success
        case failure(String)
    }

    var body: some View {
        NavigationStack {
            Form {
                serverSection
                if configLoaded {
                    slskdSection
                    plexSection2
                }
                defaultsSection
            }
            .navigationTitle("Settings")
            .task {
                if !serverURL.isEmpty { await connectToServer() }
            }
        }
    }

    // MARK: Track Summon server

    private var serverSection: some View {
        Section {
            TextField("https://tracksummon.example.com", text: $serverURL)
                .keyboardType(.URL)
                .textContentType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            SecureField("API key", text: $apiKey)
            Button {
                Task { await connectToServer() }
            } label: {
                if isTestingServer {
                    ProgressView()
                } else {
                    Text("Test Connection")
                }
            }
            .disabled(serverURL.isEmpty || isTestingServer)

            if let serverResult {
                switch serverResult {
                case .success:
                    StatusRow(name: "Track Summon server", ok: true, detail: "connected")
                case .failure(let message):
                    StatusRow(name: "Track Summon server", ok: false, detail: message)
                }
            }
        } header: {
            Text("Track Summon Server")
        } footer: {
            Text("The base URL of your Track Summon server. Use HTTPS or a VPN (Tailscale/WireGuard) to reach it away from home. Once connected, slskd and Plex are configured below — no server restart needed.")
        }
    }

    // MARK: slskd (Soulseek)

    private var slskdSection: some View {
        Section {
            TextField("http://slskd:5030", text: $slskdUrl)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            TextField("Username", text: $slskdUsername)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            SecureField("Password", text: $slskdPassword)
            SecureField("API key (optional, used instead of login)", text: $slskdApiKey)

            saveButton(isSaving: isSavingSlskd, title: "Save & Test slskd") {
                Task { await saveSlskd() }
            }
            if let status = serverStatus {
                StatusRow(name: "slskd", ok: status.slskd.ok, detail: status.slskd.detail)
            }
            if let slskdError {
                Text(slskdError).font(.caption).foregroundStyle(.red)
            }
        } header: {
            Text("slskd (Soulseek)")
        } footer: {
            Text("Where downloads come from. The URL is from the server's point of view — on the same Docker host, \"http://host.docker.internal:5030\" usually works.")
        }
    }

    // MARK: Plex

    private var plexSection2: some View {
        Section {
            TextField("http://plex:32400", text: $plexUrl)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            SecureField("Plex token", text: $plexToken)
            TextField("Library section name (optional)", text: $plexSection)
                .textInputAutocapitalization(.words)

            saveButton(isSaving: isSavingPlex, title: "Save & Test Plex") {
                Task { await savePlex() }
            }
            if let status = serverStatus {
                StatusRow(name: "Plex", ok: status.plex.ok, detail: status.plex.detail)
            }
            if let plexError {
                Text(plexError).font(.caption).foregroundStyle(.red)
            }
        } header: {
            Text("Plex")
        } footer: {
            Text("Used to scan new tracks into your library and manage playlists. Leave the section name empty to auto-detect the music library.")
        }
    }

    private var defaultsSection: some View {
        Section {
            TextField("Default playlist (optional)", text: $defaultPlaylist)
                .textInputAutocapitalization(.words)
        } header: {
            Text("Defaults")
        } footer: {
            Text("Pre-selected when adding a song. Updated automatically to the last playlist you used.")
        }
    }

    private func saveButton(isSaving: Bool, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            if isSaving {
                ProgressView()
            } else {
                Text(title)
            }
        }
        .disabled(isSaving)
    }

    // MARK: actions

    private func connectToServer() async {
        isTestingServer = true
        defer { isTestingServer = false }
        serverResult = nil
        do {
            // /api/config requires the API key, so this validates the key too —
            // unlike /api/health, which is open and would pass with a wrong key.
            let config = try await APIClient.shared.getConfig()
            serverResult = .success
            applyConfig(config)
            serverStatus = try? await APIClient.shared.status()
        } catch APIError.server(401, _) {
            serverResult = .failure("Wrong API key")
            configLoaded = false
        } catch {
            serverResult = .failure(error.localizedDescription)
            configLoaded = false
        }
    }

    /// Populate the editable fields from the server — but only once, so a
    /// re-test or tab re-entry can't wipe edits the user hasn't saved yet.
    private func applyConfig(_ config: ServerConfig) {
        guard !configLoaded else { return }
        slskdUrl = config.slskdUrl ?? ""
        slskdUsername = config.slskdUsername ?? ""
        slskdPassword = config.slskdPassword ?? ""
        slskdApiKey = config.slskdApiKey ?? ""
        plexUrl = config.plexUrl ?? ""
        plexToken = config.plexToken ?? ""
        plexSection = config.plexSection ?? ""
        configLoaded = true
    }

    private func saveSlskd() async {
        isSavingSlskd = true
        defer { isSavingSlskd = false }
        slskdError = nil
        do {
            _ = try await APIClient.shared.saveConfig(
                ServerConfig(
                    slskdUrl: slskdUrl,
                    slskdApiKey: slskdApiKey,
                    slskdUsername: slskdUsername,
                    slskdPassword: slskdPassword
                )
            )
        } catch {
            slskdError = error.localizedDescription
            return
        }
        // Save succeeded; the status probe is separate — a failed probe means
        // slskd is unreachable, which the status row shows, not a save error.
        serverStatus = try? await APIClient.shared.status()
    }

    private func savePlex() async {
        isSavingPlex = true
        defer { isSavingPlex = false }
        plexError = nil
        do {
            _ = try await APIClient.shared.saveConfig(
                ServerConfig(
                    plexUrl: plexUrl,
                    plexToken: plexToken,
                    plexSection: plexSection
                )
            )
        } catch {
            plexError = error.localizedDescription
            return
        }
        serverStatus = try? await APIClient.shared.status()
    }
}

struct StatusRow: View {
    let name: String
    let ok: Bool
    let detail: String?

    var body: some View {
        HStack {
            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundStyle(ok ? .green : .red)
            Text(name)
            Spacer()
            if let detail {
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
    }
}
