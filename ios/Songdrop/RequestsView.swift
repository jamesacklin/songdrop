import SwiftUI

struct RequestsView: View {
    @State private var requests: [TrackRequest] = []
    @State private var serverStatus: ServerStatus?
    @State private var clockOffset: TimeInterval = 0  // server time − device time
    @State private var errorMessage: String?
    @State private var hasLoaded = false
    @State private var loadError: String?
    @State private var isLoading = false
    @State private var isVisible = false
    @State private var lastStatusCheck: Date = .distantPast
    @State private var purgeTarget: TrackRequest?

    private let refreshTimer = Timer.publish(every: 4, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let status = serverStatus, !status.slskd.ok {
                    SourceOfflineBanner(detail: status.slskd.detail)
                }
                content
            }
            .navigationTitle("Requests")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("Clear Completed") { Task { await clear(["done"]) } }
                        Button("Clear Failed") { Task { await clear(["failed"]) } }
                        Button("Clear Completed & Failed") { Task { await clear(["done", "failed"]) } }
                    } label: {
                        Label("Clear", systemImage: "ellipsis.circle")
                    }
                    .disabled(!requests.contains { ["done", "failed"].contains($0.status) })
                }
            }
            .refreshable {
                await load()
                await checkStatus(force: true)
            }
            .task {
                await load()
                await checkStatus(force: true)
            }
            .onAppear { isVisible = true }
            .onDisappear { isVisible = false }
            .onReceive(refreshTimer) { _ in
                guard isVisible else { return }
                Task {
                    await load()
                    await checkStatus(force: false)
                }
            }
            .alert("Error", isPresented: .constant(errorMessage != nil)) {
                Button("OK") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
            .confirmationDialog(
                "Delete “\(purgeTarget?.title ?? "")” from your library?",
                isPresented: .constant(purgeTarget != nil),
                titleVisibility: .visible
            ) {
                Button("Delete File from Disk & Plex", role: .destructive) {
                    if let target = purgeTarget {
                        Task { await purge(target) }
                    }
                    purgeTarget = nil
                }
                Button("Cancel", role: .cancel) { purgeTarget = nil }
            } message: {
                Text("Removes the audio file from disk, takes it out of Plex and any playlists, and clears this entry.")
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if requests.isEmpty {
            if let loadError, hasLoaded {
                ContentUnavailableView(
                    "Can't reach the server",
                    systemImage: "wifi.exclamationmark",
                    description: Text(loadError)
                )
            } else if hasLoaded {
                ContentUnavailableView(
                    "No requests yet",
                    systemImage: "tray",
                    description: Text("Songs you add from Search will show up here.")
                )
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        } else {
            List {
                ForEach(requests) { request in
                    RequestRow(request: request, clockOffset: clockOffset)
                        .swipeActions(edge: .trailing) {
                            if request.isDeletable {
                                if request.status == "done", request.filePath?.isEmpty == false {
                                    Button(role: .destructive) {
                                        purgeTarget = request
                                    } label: {
                                        Label("Delete File", systemImage: "trash.fill")
                                    }
                                    Button {
                                        Task { await remove(request) }
                                    } label: {
                                        Label("Clear Entry", systemImage: "xmark.circle")
                                    }
                                    .tint(.gray)
                                } else {
                                    Button(role: .destructive) {
                                        Task { await remove(request) }
                                    } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                            }
                            if request.isRetryable {
                                Button {
                                    Task { await retry(request) }
                                } label: {
                                    Label("Search Now", systemImage: "arrow.clockwise")
                                }
                                .tint(.orange)
                            }
                        }
                }
            }
            .listStyle(.plain)
        }
    }

    private func load() async {
        guard !isLoading else { return }  // don't let slow polls overlap and race
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.requests()
            requests = response.requests
            if let serverNow = response.now {
                clockOffset = serverNow - Date().timeIntervalSince1970
            }
            loadError = nil
            hasLoaded = true
        } catch {
            loadError = error.localizedDescription
            hasLoaded = true
        }
    }

    /// slskd status is polled gently (every 30s) so we don't hammer it.
    /// A failed probe keeps the last known status instead of hiding a warning.
    private func checkStatus(force: Bool) async {
        guard force || Date().timeIntervalSince(lastStatusCheck) > 30 else { return }
        lastStatusCheck = Date()
        if let status = try? await APIClient.shared.status() {
            serverStatus = status
        }
    }

    private func retry(_ request: TrackRequest) async {
        do {
            _ = try await APIClient.shared.retry(request.id)
        } catch APIError.server(409, _) {
            // The worker beat us to it — the row is already in flight.
        } catch {
            errorMessage = error.localizedDescription
        }
        await load()
    }

    private func remove(_ request: TrackRequest) async {
        do {
            try await APIClient.shared.delete(request.id)
        } catch APIError.server(409, _) {
            // Started processing since the last poll; it can't be removed now.
        } catch {
            errorMessage = error.localizedDescription
        }
        await load()
    }

    private func purge(_ request: TrackRequest) async {
        do {
            try await APIClient.shared.delete(request.id, purge: true)
        } catch {
            errorMessage = error.localizedDescription
        }
        await load()
    }

    private func clear(_ statuses: [String]) async {
        do {
            _ = try await APIClient.shared.clear(statuses: statuses)
        } catch {
            errorMessage = error.localizedDescription
        }
        await load()
    }
}

struct SourceOfflineBanner: View {
    let detail: String?

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text("Your server's source is offline").font(.subheadline).bold()
                Text(detail ?? "Requests will wait until it's back.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.orange.opacity(0.12))
    }
}

struct RequestRow: View {
    let request: TrackRequest
    var clockOffset: TimeInterval = 0

    var body: some View {
        HStack(spacing: 12) {
            statusIcon
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 2) {
                Text(request.title).font(.body).lineLimit(1)
                Text(request.artist).font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                subtitle
                if let playlist = request.playlist, !playlist.isEmpty {
                    Label(playlist, systemImage: "music.note.list")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var subtitle: some View {
        switch request.status {
        case "failed":
            Text(request.error?.isEmpty == false ? request.error! : "Failed")
                .font(.caption).foregroundStyle(.red).lineLimit(2)
        case "waiting":
            RetryCountdown(
                nextRetryAt: request.nextRetryAt,
                retryCount: request.retryCount,
                clockOffset: clockOffset
            )
        default:
            if let detail = request.detail, !detail.isEmpty {
                Text(detail).font(.caption).foregroundStyle(.tertiary).lineLimit(1)
            }
        }
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch request.status {
        case "done":
            Image(systemName: "checkmark.circle.fill")
                .font(.title3)
                .foregroundStyle(.green)
        case "failed":
            Image(systemName: "exclamationmark.circle.fill")
                .font(.title3)
                .foregroundStyle(.red)
        case "queued":
            Image(systemName: "clock")
                .font(.title3)
                .foregroundStyle(.secondary)
        case "waiting":
            Image(systemName: "clock.arrow.circlepath")
                .font(.title3)
                .foregroundStyle(.orange)
        default:
            ProgressView()
        }
    }
}

/// Live "searching again in M:SS" countdown for waiting requests.
/// `clockOffset` (server − device time) corrects for skewed clocks.
struct RetryCountdown: View {
    let nextRetryAt: Double?
    let retryCount: Int?
    var clockOffset: TimeInterval = 0

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            Text(label(at: context.date))
                .font(.caption)
                .foregroundStyle(.orange)
                .monospacedDigit()
        }
    }

    private func label(at date: Date) -> String {
        let attempt = (retryCount ?? 0) > 0 ? " (searched \(retryCount ?? 0)×)" : ""
        guard let at = nextRetryAt else {
            return "No results yet — will search again\(attempt)"
        }
        let serverNow = date.timeIntervalSince1970 + clockOffset
        let remaining = Int(at - serverNow)
        guard remaining > 0 else {
            return "No results yet — searching again now…\(attempt)"
        }
        return String(format: "No results yet — next search in %d:%02d%@", remaining / 60, remaining % 60, attempt)
    }
}
