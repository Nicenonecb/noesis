-- The installer substitutes absolute executable and data paths.
local executable = __NOESIS_EXECUTABLE__
local dataDir = __NOESIS_DATA_DIR__
local askNote = __NOESIS_ASK_NOTE__
local lastCapture = 0
local tasks = {}
local function run(arguments, callback)
  local task
  task = hs.task.new(executable, function(code, stdout, stderr)
    tasks[task] = nil
    local ok, value = pcall(hs.json.decode, stdout)
    callback(code, ok and value or nil)
  end, arguments)
  if task then tasks[task] = true; task:start() else callback(1, nil) end
end
local function notify(message)
  hs.notify.new({title = "NOESIS · 求是", informativeText = message}):send()
end
local function capture(region)
  local now = hs.timer.secondsSinceEpoch()
  if now - lastCapture < 1 then return end
  lastCapture = now
  local win = hs.window.focusedWindow()
  local args = {"capture", "--data-dir", dataDir}
  if region then table.insert(args, "--region") end
  if win then
    table.insert(args, "--window-id"); table.insert(args, tostring(win:id()))
    table.insert(args, "--app"); table.insert(args, win:application():bundleID() or "")
    table.insert(args, "--app-name"); table.insert(args, win:application():name() or "")
    table.insert(args, "--window-title"); table.insert(args, win:title() or "")
  end
  run(args, function(code, value)
    if code ~= 0 or not value then notify("收藏失败或已取消，请检查权限与日志"); return end
    if not askNote then notify("已收藏：" .. (value.title or "")); return end
    local button, note = hs.dialog.textPrompt("为什么存这个？", value.title or "", "", "保存备注", "跳过")
    if button == "保存备注" and note ~= "" then
      run({"annotate", value.id, "--note", note, "--data-dir", dataDir}, function(status)
        notify(status == 0 and ("已收藏：" .. (value.title or "")) or "截图已保存，备注写入失败")
      end)
    else notify("已收藏：" .. (value.title or "")) end
    if value.warning then notify("正文暂未获取；请检查浏览器自动化与 JavaScript 权限") end
  end)
end
local bindings = {
  hs.hotkey.bind({"alt", "cmd"}, "S", function() capture(false) end),
  hs.hotkey.bind({"alt", "cmd", "shift"}, "S", function() capture(true) end)
}
return {bindings = bindings, tasks = tasks}
