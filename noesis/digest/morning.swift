import AppKit
import CoreGraphics
import WebKit

// A local viewer and unlock observer. Model/network work stays in the Python CLI.
final class MorningApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow?
    private var timer: Timer?
    private var task: Process?
    private var eligibleDay: String?
    private var wasLocked = false
    private var pending: [String: Any]?
    private var loading: [String: Any]?
    private var presentedDay: String?
    private var freshUnlock = true
    private let info = Bundle.main.infoDictionary ?? [:]
    private var root: String { info["NOESISDataDirectory"] as? String ?? "" }
    private var executable: String { info["NOESISExecutable"] as? String ?? "" }
    private var today: String {
        let formatter = DateFormatter()
        formatter.timeZone = TimeZone(identifier: info["NOESISTimezone"] as? String ?? "Asia/Shanghai")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: Date())
    }
    private var locked: Bool {
        guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return true }
        return (session["CGSSessionScreenIsLocked"] as? Bool ?? false)
            || !(session[kCGSessionOnConsoleKey as String] as? Bool ?? false)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let args = CommandLine.arguments
        if args.count == 3 && args[1] == "--preview" {
            show(args[2])
            return
        }
        let center = DistributedNotificationCenter.default()
        // macOS lock/unlock distributed notifications are not a public contract;
        // also observe session switches and poll lock transitions for recovery.
        center.addObserver(self, selector: #selector(didUnlock), name: NSNotification.Name("com.apple.screenIsUnlocked"), object: nil)
        center.addObserver(self, selector: #selector(didLock), name: NSNotification.Name("com.apple.screenIsLocked"), object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(didUnlock), name: NSWorkspace.sessionDidBecomeActiveNotification, object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(didLock), name: NSWorkspace.sessionDidResignActiveNotification, object: nil)
        wasLocked = locked
        if !wasLocked { eligibleDay = today } // Login, or first installation in an active session.
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in self?.tick() }
        tick()
    }

    @objc private func didLock(_ notification: Notification) { wasLocked = true }
    @objc private func didUnlock(_ notification: Notification) {
        eligibleDay = today
        freshUnlock = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.tick() }
    }

    private func tick() {
        let current = locked
        if wasLocked && !current { eligibleDay = today; freshUnlock = true }
        wasLocked = current
        guard !current, eligibleDay == today, presentedDay != today, task == nil, loading == nil else { return }
        if let result = pending { present(result); return }
        var args = ["morning-run", "--unlocked", "--data-dir", root]
        if freshUnlock { args.append("--unlock-event"); freshUnlock = false }
        launch(args) { result in
            if result?["status"] as? String == "busy" { self.freshUnlock = true }
            if result?["status"] as? String == "already_presented" { self.presentedDay = self.today }
            guard let result = result, result["show"] is String else { return }
            self.pending = result
            if !self.locked { self.present(result) }
        }
    }

    private func present(_ result: [String: Any]) {
        guard result["delivery_day"] as? String == today, let path = result["show"] as? String else {
            pending = nil
            return
        }
        loading = result
        guard show(path) else { loading = nil; return }
        pending = nil
    }

    private func launch(_ args: [String], completion: @escaping ([String: Any]?) -> Void) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = args
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.standardError // launchd owns a private diagnostic log.
        process.terminationHandler = { [weak self] _ in
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            DispatchQueue.main.async { self?.task = nil; completion(result) }
        }
        task = process
        do { try process.run() } catch {
            fputs("morning_process_start_failed\n", stderr)
            task = nil
            completion(nil)
        }
    }

    @discardableResult private func show(_ path: String) -> Bool {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        let allowed = URL(fileURLWithPath: root).appendingPathComponent("briefings").standardizedFileURL.path + "/"
        guard url.path.hasPrefix(allowed), url.pathExtension == "html", FileManager.default.fileExists(atPath: url.path) else { return false }
        let preferences = WKWebpagePreferences()
        preferences.allowsContentJavaScript = false
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences = preferences
        configuration.websiteDataStore = .nonPersistent()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.loadFileURL(url, allowingReadAccessTo: url)
        if window == nil {
            window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 960, height: 760),
                styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window?.isReleasedWhenClosed = false
            window?.center()
        }
        window?.title = "NOESIS · 昨日总结与今日重点"
        window?.contentView = webView
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        return true
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = navigationAction.request.url
        if navigationAction.navigationType == .linkActivated,
           let url = url, ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(url?.isFileURL == true && url?.path.hasPrefix(root + "/briefings/") == true ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let result = loading else { return }
        loading = nil
        guard !locked else { pending = result; window?.orderOut(nil); return }
        let failure = result["failure"] as? Bool == true
        var args = ["morning-ack", result["delivery_day"] as? String ?? "", "--data-dir", root]
        if failure { args.append("--failure") }
        launch(args) { response in
            if !failure && response?["status"] as? String == "acknowledged" { self.presentedDay = self.today }
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        pending = loading
        loading = nil
    }
}

if CommandLine.arguments.contains("--version") {
    print("NOESIS Morning 1")
} else {
    let app = NSApplication.shared
    let delegate = MorningApp()
    app.delegate = delegate
    app.run()
}
