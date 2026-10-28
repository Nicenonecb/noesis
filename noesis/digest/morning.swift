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
    private var focusDialogOpen = false
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
        guard !current, eligibleDay == today, presentedDay != today, task == nil, loading == nil, !focusDialogOpen else { return }
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

    private func isBriefing(_ url: URL) -> Bool {
        let directory = URL(fileURLWithPath: root).appendingPathComponent("briefings").resolvingSymlinksInPath().path + "/"
        let resolved = url.resolvingSymlinksInPath()
        return url.isFileURL && resolved.path.hasPrefix(directory) && resolved.pathExtension == "html"
    }

    @discardableResult private func show(_ path: String) -> Bool {
        let url = URL(fileURLWithPath: path).resolvingSymlinksInPath()
        guard isBriefing(url), FileManager.default.fileExists(atPath: url.path) else { return false }
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
        if url?.scheme == "noesis-focus" {
            decisionHandler(.cancel)
            if navigationAction.navigationType == .linkActivated, let url = url {
                handleFocus(url)
            }
            return
        }
        if navigationAction.navigationType == .linkActivated,
           let url = url, ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(url.map(isBriefing) == true ? .allow : .cancel)
    }

    private func handleFocus(_ url: URL) {
        guard task == nil, loading == nil, !focusDialogOpen, !locked,
              let action = url.host, ["add", "done", "missed", "snoozed", "pause"].contains(action),
              url.fragment == nil,
              let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
              query.count == 1, query[0].name == "day", let day = query[0].value else { return }
        if day != today {
            let stale = NSAlert()
            stale.messageText = "这份提醒已跨日"
            stale.informativeText = "请重新打开今天的晨报再反馈。"
            stale.runModal()
            return
        }
        let identity = String(url.path.dropFirst())
        guard action == "add" || identity.range(of: "^[a-f0-9]{12}$", options: .regularExpression) != nil else { return }
        focusDialogOpen = true
        defer { focusDialogOpen = false }
        let alert = NSAlert()
        alert.messageText = action == "add" ? "设置你想发展的方向" : "记录这次行动"
        let labels = ["done": "已完成今天的行动，明天继续跟进。", "missed": "如实记录阻碍，明天再走一小步。",
                      "snoozed": "延后到明天提醒。", "pause": "暂停后不再提醒，可用 noesis focus resume 恢复。"]
        alert.informativeText = labels[action] ?? "填写一个方向和一个具体行动，从明天开始在晨报中跟进。最多启用 3 个方向。"
        let placeholders = action == "add" ? ["名称（最多 80 字）", "想发展的方向（最多 300 字）", "一个具体行动（最多 200 字）"]
            : action == "pause" ? [] : ["可选：记录进展或阻碍（最多 200 字）"]
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.spacing = 10
        stack.frame = NSRect(x: 0, y: 0, width: 420, height: max(0, placeholders.count * 34 - 10))
        let fields = placeholders.map { placeholder -> NSTextField in
            let field = NSTextField(string: "")
            field.placeholderString = placeholder
            field.widthAnchor.constraint(equalToConstant: 420).isActive = true
            field.heightAnchor.constraint(equalToConstant: 24).isActive = true
            stack.addArrangedSubview(field)
            return field
        }
        if !fields.isEmpty { alert.accessoryView = stack }
        alert.addButton(withTitle: "保存")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        var args = ["focus", "--data-dir", root]
        if action == "add" {
            args += ["add", "--title", fields[0].stringValue, "--direction", fields[1].stringValue, "--step", fields[2].stringValue]
        } else if action == "pause" {
            args += ["pause", identity]
        } else {
            args += ["checkin", identity, "--outcome", action, "--note", fields[0].stringValue]
        }
        args += ["--expected-day", day]
        launch(args) { result in
            guard result?["status"] as? String == "saved", let path = result?["path"] as? String else {
                let failure = NSAlert()
                failure.messageText = "暂未保存成功"
                failure.informativeText = "请检查字段长度、启用方向是否已达 3 个，或方向是否已暂停。可运行 noesis focus list 核对当前状态。"
                failure.runModal()
                return
            }
            self.show(path)
            self.window?.title = action == "pause" ? "NOESIS · 已暂停此方向"
                : "NOESIS · 已保存，下次跟进 " + (result?["next_due"] as? String ?? "")
        }
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
