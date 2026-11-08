import AppKit
import WebKit

// Dock app for the todo board. The Python CLI owns data and serving; this window only hosts the page.
final class TodoApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    private var window: NSWindow?
    private var webView: WKWebView?
    private var server: Process?
    private var board: URL?
    private var buffer = ""
    private let info = Bundle.main.infoDictionary ?? [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.mainMenu = mainMenu()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "noesis")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self
        view.uiDelegate = self
        view.loadHTMLString("<body style='font:13px -apple-system;color:#8f959e;padding:40px'>正在启动…</body>", baseURL: nil)
        webView = view
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "NOESIS 待办"
        window.contentView = view
        window.center()
        window.setFrameAutosaveName("NOESISTodoWindow")
        window.makeKeyAndOrderFront(nil)
        self.window = window
        NSApp.activate(ignoringOtherApps: true)
        startServer()
    }

    private func mainMenu() -> NSMenu {
        // WKWebView text fields only get ⌘C/⌘V/⌘A/⌘Z through an Edit menu.
        let menu = NSMenu()
        let app = NSMenu()
        app.addItem(withTitle: "隐藏 NOESIS 待办", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(withTitle: "退出 NOESIS 待办", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "拷贝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        let view = NSMenu(title: "显示")
        view.addItem(withTitle: "刷新", action: #selector(reload), keyEquivalent: "r")
        for (title, submenu) in [("NOESIS 待办", app), ("编辑", edit), ("显示", view)] {
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            item.submenu = submenu
            menu.addItem(item)
        }
        return menu
    }

    @objc private func reload() { if board != nil { webView?.reload() } }

    private func startServer() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: info["NOESISExecutable"] as? String ?? "")
        process.arguments = ["todo", "--data-dir", info["NOESISDataDirectory"] as? String ?? "", "--no-open", "--exit-on-stdin-eof"]
        // The server exits when this pipe closes, so a crash here never leaves it running.
        process.standardInput = Pipe()
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let text = String(decoding: handle.availableData, as: UTF8.self)
            DispatchQueue.main.async { self?.consume(text) }
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.serverStopped() }
        }
        server = process
        do { try process.run() } catch { serverStopped() }
    }

    private func consume(_ text: String) {
        guard board == nil else { return }
        buffer += text
        guard let range = buffer.range(of: "http://127\\.0\\.0\\.1:[0-9]+/\\?token=[A-Za-z0-9_-]+", options: .regularExpression),
              let url = URL(string: String(buffer[range])) else { return }
        board = url
        buffer = ""
        webView?.load(URLRequest(url: url))
    }

    private func serverStopped() {
        guard server != nil else { return }
        server = nil
        let alert = NSAlert()
        alert.messageText = "待办服务已停止"
        alert.informativeText = "请重新运行 scripts/install.sh 更新运行包，或运行 noesis doctor 检查数据目录。"
        alert.runModal()
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        let process = server
        server = nil
        process?.terminate()
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { return decisionHandler(.cancel) }
        if url.scheme == "about" || (board != nil && url.host == board?.host && url.port == board?.port) {
            return decisionHandler(.allow)
        }
        if ["http", "https"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "确定")
        alert.addButton(withTitle: "取消")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, board != nil, let window = window,
              (message.body as? [String: Any])?["action"] as? String == "pickFolder" else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "关联"
        panel.message = "选择要关联的文件夹"
        panel.beginSheetModal(for: window) { [weak self] response in
            var result: [String: Any] = ["status": "cancelled"]
            if response == .OK, let url = panel.url { result = ["status": "picked", "path": url.path] }
            guard let data = try? JSONSerialization.data(withJSONObject: result),
                  let json = String(data: data, encoding: .utf8) else { return }
            self?.webView?.evaluateJavaScript("window.noesisPicked && window.noesisPicked(\(json))")
        }
    }
}

if CommandLine.arguments.contains("--version") {
    print("NOESIS Todo 1")
} else {
    let app = NSApplication.shared
    let delegate = TodoApp()
    app.delegate = delegate
    app.run()
}
