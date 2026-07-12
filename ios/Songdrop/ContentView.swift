import SwiftUI

struct ContentView: View {
    @AppStorage("serverURL") private var serverURL = ""
    @State private var selectedTab = 0
    @State private var showOnboarding = false

    var body: some View {
        TabView(selection: $selectedTab) {
            SearchView(onRequested: { selectedTab = 1 })
                .tabItem { Label("Search", systemImage: "magnifyingglass") }
                .tag(0)
            RequestsView()
                .tabItem { Label("Requests", systemImage: "tray.full") }
                .tag(1)
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
                .tag(2)
        }
        .onAppear {
            if serverURL.isEmpty { showOnboarding = true }
            // Test hook: lets automation open on a specific tab (simctl launch env).
            switch ProcessInfo.processInfo.environment["SD_INITIAL_TAB"] {
            case "requests": selectedTab = 1
            case "settings": selectedTab = 2
            default: break
            }
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingView(onConnected: {
                showOnboarding = false
                selectedTab = 0
            })
        }
    }
}
