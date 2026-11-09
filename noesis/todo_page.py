"""Single-file NOESIS app page (todo grid, daily logs, settings); shipped as Python so the .pyz bundle carries it."""

PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NOESIS</title>
<style>
:root {
  --text: #1f2329; --text-2: #646a73; --text-3: #8f959e; --line: #dee0e3; --line-2: #eff0f1;
  --bg: #ffffff; --bg-hover: #f5f6f7; --bg-side: #f5f6f7; --blue: #3370ff; --blue-bg: #e1eaff;
  --red: #d83931; --orange: #ff8800; --yellow: #dc9b04; --gray: #8f959e; --green: #34c724;
  --row: 34px;
}
* { box-sizing: border-box; scrollbar-width: none; }
*::-webkit-scrollbar { display: none; width: 0; height: 0; }
html, body { margin: 0; height: 100%; overflow: hidden; background: var(--bg); color: var(--text);
  font: 13px/1.5 -apple-system, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif; }
button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; }
.app { display: flex; height: 100vh; }
.side { width: 208px; flex: none; background: var(--bg-side); border-right: 1px solid var(--line); padding: 16px 8px 12px;
  display: flex; flex-direction: column; gap: 2px; }
.brand { font-size: 15px; font-weight: 600; padding: 2px 10px 18px; letter-spacing: .5px; }
.brand small { color: var(--text-3); font-weight: 400; margin-left: 6px; font-size: 12px; letter-spacing: 0; }
.nav { display: flex; align-items: center; gap: 10px; width: 100%; height: 36px; padding: 0 10px; border-radius: 6px; text-align: left; }
.nav svg { width: 16px; height: 16px; flex: none; stroke: currentColor; fill: none; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.nav:hover { background: #e9eaec; }
.nav.active { background: var(--blue-bg); color: var(--blue); font-weight: 500; }
.nav .badge { margin-left: auto; color: var(--text-3); font-size: 12px; font-weight: 400; }
.side .bottom { margin-top: auto; }
main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.view { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.view[hidden] { display: none; }
.top { display: flex; align-items: center; gap: 12px; height: 56px; flex: none; padding: 0 20px; border-bottom: 1px solid var(--line-2); }
.top h1 { font-size: 16px; font-weight: 600; margin: 0; white-space: nowrap; }
.top .sub { color: var(--text-3); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.spacer { flex: 1; }
.search { height: 30px; width: 220px; min-width: 120px; flex: 0 1 220px; border: 1px solid var(--line); border-radius: 6px;
  padding: 0 10px; font: inherit; outline: none; }
.search:focus { border-color: var(--blue); }
.btn { height: 30px; padding: 0 12px; border-radius: 6px; border: 1px solid var(--line); background: #fff; white-space: nowrap; flex: none; }
.btn:hover { background: var(--bg-hover); }
.btn.primary { background: var(--blue); border-color: var(--blue); color: #fff; }
.btn.primary:hover { background: #4e83fd; }
.btn.danger { color: var(--red); }
.btn[hidden] { display: none; }
.wrap { flex: 1; min-height: 0; overflow: auto; padding: 0 0 32px; }

/* Columns share the window width; minimums only overflow on very narrow windows. */
/* Columns share the window width; minimums only overflow on very narrow windows. */
.grid { width: 100%; min-width: 1150px; }
.row { display: flex; min-height: var(--row); }
.cell { border-right: 1px solid var(--line-2); border-bottom: 1px solid var(--line-2); padding: 0 8px;
  display: flex; align-items: center; gap: 6px; overflow: hidden; background: inherit; }
.c-title { flex: 5 1 0; min-width: 240px; } .c-tag { flex: 0 0 116px; } .c-status { flex: 0 0 82px; }
.c-cat { flex: 1 1 0; min-width: 100px; } .c-note { flex: 2 1 0; min-width: 120px; } .c-folder { flex: 2 1 0; min-width: 140px; }
.c-dur { flex: 0 0 146px; } .c-upd { flex: 0 0 100px; } .c-crt { flex: 0 0 100px; border-right: 0; }
.c-parent { flex: 1 1 0; min-width: 100px; border-right: 0; display: none; }
/* The indented tree already shows parentage; the column returns when there is room for it. */
@media (min-width: 1600px) { .c-parent { display: flex; } .c-crt { border-right: 1px solid var(--line-2); } }
.cell.frozen { position: sticky; left: 0; z-index: 2; border-right: 1px solid var(--line); }
.head { position: sticky; top: 0; z-index: 4; background: #fff; }
.head .cell { height: 36px; color: var(--text-2); border-bottom: 1px solid var(--line); background: #fff; }
.head .cell.frozen { z-index: 5; }
.head .icon { color: var(--text-3); font-size: 12px; width: 16px; text-align: center; flex: none; }
.data { background: #fff; }
.data:hover, .data.selected { background: var(--bg-hover); }
.data .cell.editable { cursor: pointer; }
.data .cell.editable:hover { box-shadow: inset 0 0 0 1px #bacefd; }
.idx { width: 28px; flex: none; color: var(--text-3); font-size: 12px; text-align: center; }
.idx input { display: none; margin: 0; }
.data:hover .idx .num, .data.selected .idx .num { display: none; }
.data:hover .idx input, .data.selected .idx input, .head .idx input { display: inline-block; }
.caret { width: 16px; flex: none; color: var(--text-2); font-size: 10px; text-align: center; }
.caret button { width: 16px; height: 16px; border-radius: 3px; }
.caret button:hover { background: var(--line); }
.title { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.title.empty { color: var(--text-3); }
.subcount { color: var(--text-3); font-size: 12px; flex: none; }
.rowtools { display: none; gap: 4px; flex: none; }
.data:hover .rowtools { display: flex; }
.tool { height: 22px; padding: 0 6px; border: 1px solid var(--line); border-radius: 4px; background: #fff;
  color: var(--text-2); font-size: 12px; white-space: nowrap; }
.tool:hover { color: var(--blue); border-color: var(--blue); }
.pill { display: inline-flex; align-items: center; gap: 3px; height: 20px; padding: 0 8px; border-radius: 10px;
  font-size: 12px; white-space: nowrap; line-height: 20px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.tag-urgent_important { background: var(--red); color: #fff; }
.tag-important { background: var(--orange); color: #fff; }
.tag-urgent { background: var(--yellow); color: #fff; }
.tag-neither { background: var(--gray); color: #fff; }
.st-todo { background: var(--blue-bg); color: #1f2329; }
.st-doing { background: #fff1d6; color: #8f5c00; }
.st-done { background: var(--green); color: #fff; }
.muted { color: var(--text-3); }
.clip { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.folders { display: flex; gap: 4px; align-items: center; min-width: 0; overflow: hidden; flex: 1; }
.chip { display: inline-flex; align-items: center; gap: 4px; height: 22px; max-width: 150px; padding: 0 6px;
  border-radius: 4px; background: #f0f1f2; font-size: 12px; flex: none; }
.chip:hover { background: var(--blue-bg); color: var(--blue); }
.chip .x { display: none; color: var(--text-3); padding: 0 1px; }
.chip:hover .x { display: inline; }
.chip .x:hover { color: var(--red); }
.chip.missing { text-decoration: line-through; color: var(--text-3); }
.add-folder { visibility: hidden; flex: none; width: 22px; height: 22px; border-radius: 4px; color: var(--text-2); font-size: 15px; }
.data:hover .add-folder { visibility: visible; }
.add-folder:hover { background: var(--line); color: var(--blue); }
.group { margin: 12px 0 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.ghead { display: flex; height: 36px; background: #fff; }
.ghead .cell { border-bottom: 0; }
.ghead .cell.frozen { cursor: pointer; }
.cell.rest { flex: 1 1 0; border-right: 0; }
.ghead .fold { width: 20px; color: var(--text-2); font-size: 10px; flex: none; }
.ghead .count { margin-left: auto; color: var(--text-3); font-size: 12px; white-space: nowrap; }
.ghead + .rows .data:first-child .cell, .ghead + .rows .addrow .cell { border-top: 1px solid var(--line-2); }
.addrow .cell { color: var(--text-3); font-size: 16px; border-bottom: 0; }
.addrow .cell.frozen { cursor: pointer; }
.addrow .cell.frozen:hover { color: var(--blue); background: var(--bg-hover); }
.collapsed .rows { display: none; }
.editor { position: fixed; z-index: 20; border: 2px solid var(--blue); background: #fff; font: inherit; padding: 5px 8px;
  outline: none; resize: none; border-radius: 2px; box-shadow: 0 4px 12px rgba(31,35,41,.12); }
.menu { position: fixed; z-index: 20; background: #fff; border: 1px solid var(--line); border-radius: 8px;
  box-shadow: 0 6px 24px rgba(31,35,41,.12); padding: 4px; min-width: 160px; }
.menu button { display: flex; width: 100%; align-items: center; padding: 6px 8px; border-radius: 4px; }
.menu button:hover { background: var(--bg-hover); }
.menu .clear { color: var(--text-2); }
.toast { position: fixed; left: 50%; top: 16px; transform: translateX(-50%); background: #1f2329; color: #fff;
  padding: 8px 14px; border-radius: 6px; z-index: 30; font-size: 13px; }
.empty-board { padding: 60px 20px; text-align: center; color: var(--text-3); }

.daily { flex: 1; min-height: 0; display: flex; }
.days { width: 184px; flex: none; border-right: 1px solid var(--line-2); overflow: auto; padding: 4px 8px 24px; }
.month { color: var(--text-3); font-size: 12px; padding: 12px 10px 4px; }
.day { display: flex; justify-content: space-between; width: 100%; padding: 7px 10px; border-radius: 6px; }
.day:hover { background: var(--bg-hover); }
.day.active { background: var(--blue-bg); color: var(--blue); }
.day .week { color: var(--text-3); font-size: 12px; }
.doc { flex: 1; min-width: 0; overflow: auto; padding: 28px 48px 80px; }
.doc article { max-width: 880px; margin: 0 auto; font-size: 14px; line-height: 1.75; overflow-wrap: anywhere; }
.doc h1 { font-size: 22px; margin: 0 0 16px; }
.doc h2 { font-size: 17px; margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line-2); }
.doc h3 { font-size: 15px; margin: 22px 0 8px; }
.doc h4 { font-size: 14px; margin: 16px 0 6px; color: var(--text-2); }
.doc ul { padding-left: 22px; margin: 6px 0; }
.doc a { color: var(--blue); text-decoration: none; }
.doc a:hover { text-decoration: underline; }
.doc code { background: #f2f3f5; border-radius: 4px; padding: 1px 4px; font-size: 12.5px; }
.doc pre { background: #f5f6f7; border-radius: 6px; padding: 10px 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.doc table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; table-layout: fixed; }
.doc th, .doc td { border: 1px solid var(--line); padding: 6px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.doc th { background: #f5f6f7; font-weight: 500; }
.doc .empty-board { padding-top: 120px; }
.doc li h1, .doc li h2, .doc li h3, .doc li h4, .doc li h5, .doc li h6 { font-size: 14px; margin: 10px 0 4px; padding: 0; border: 0; color: var(--text); }
.doc li p { margin: 4px 0; }
.doc li table, .doc li pre { margin: 6px 0; }

.settings { flex: 1; overflow: auto; padding: 28px 40px; }
.card { max-width: 640px; border: 1px solid var(--line); border-radius: 8px; }
.setting { display: flex; align-items: center; gap: 16px; padding: 16px 20px; }
.setting + .setting { border-top: 1px solid var(--line-2); }
.setting .label { font-weight: 500; }
.setting .hint { color: var(--text-3); font-size: 12px; margin-top: 2px; }
.segment { margin-left: auto; display: inline-flex; padding: 2px; background: #f0f1f2; border-radius: 6px; flex: none; }
.segment button { height: 28px; padding: 0 14px; border-radius: 5px; color: var(--text-2); }
.segment button.on { background: #fff; color: var(--text); font-weight: 500; box-shadow: 0 1px 2px rgba(31,35,41,.12); }
</style>
</head>
<body>
<div class="app">
<nav class="side">
  <div class="brand">NOESIS<small data-t="brand"></small></div>
  <button class="nav" data-view="todo"><svg viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="12" rx="2.5"/><path d="M5 8.2l2 2 4-4.2"/></svg><span data-t="todo"></span><span class="badge" id="todo-count"></span></button>
  <button class="nav" data-view="daily"><svg viewBox="0 0 16 16"><rect x="2.5" y="1.5" width="11" height="13" rx="2"/><path d="M5 5h6M5 8h6M5 11h3.5"/></svg><span data-t="daily"></span><span class="badge" id="daily-count"></span></button>
  <button class="nav bottom" data-view="settings"><svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M3.6 12.4l1.1-1.1M11.3 4.7l1.1-1.1"/></svg><span data-t="settings"></span></button>
</nav>
<main>
<section class="view" id="view-todo">
  <div class="top">
    <h1 data-t="todo"></h1><span class="sub" data-t="todoSub"></span>
    <span class="spacer"></span>
    <input class="search" id="search" data-t-placeholder="search">
    <button class="btn danger" id="bulk" hidden></button>
    <button class="btn primary" id="create" data-t="create"></button>
  </div>
  <div class="wrap" id="wrap"><div class="grid" id="grid"></div></div>
</section>
<section class="view" id="view-daily" hidden>
  <div class="top"><h1 data-t="daily"></h1><span class="sub" data-t="dailySub"></span></div>
  <div class="daily"><div class="days" id="days"></div><div class="doc" id="doc"></div></div>
</section>
<section class="view" id="view-settings" hidden>
  <div class="top"><h1 data-t="settings"></h1></div>
  <div class="settings">
    <div class="card">
      <div class="setting">
        <div><div class="label" data-t="language"></div><div class="hint" data-t="languageHint"></div></div>
        <div class="segment" id="lang"><button data-lang="zh">中文</button><button data-lang="en">English</button></div>
      </div>
    </div>
  </div>
</section>
</main>
</div>
<script>
'use strict';
const TOKEN = '__TOKEN__';
// Interface text only; task contents and daily logs stay as written.
const TEXT = {
  zh: {
    brand: '求是', todo: '待办', daily: '日报', settings: '设置', todoSub: '本机保存，可关联文件夹', dailySub: '每日活动日志',
    search: '搜索任务、类别、备忘', create: '＋ 新建任务', bulk: n => '删除所选（' + n + '）',
    cols: {title: '任务名称', tag: '任务标签', status: '状态', cat: '任务类别', note: '解决办法/备忘', folder: '关联文件夹',
      dur: '任务耗时', upd: '更新时间', crt: '创建时间', parent: '父记录'},
    tags: {urgent_important: '重要紧急', important: '重要不紧急', urgent: '紧急不重要', neither: '不重要不紧急'},
    statuses: {todo: '未开始', doing: '进行中', done: '已完成'},
    duration: (done, d) => (done ? '已完成' : '未完成') + '，耗时' + d + '天',
    untitled: '未命名任务', subtask: '＋ 子任务', delete: '删除', clear: '清除', records: n => n + ' 条记录',
    newIn: s => '在「' + s + '」中新建任务', emptyTodo: '还没有任务。点击右上角「新建任务」，或在分组底部点击 ＋。',
    confirmDelete: n => '删除 ' + n + ' 条记录（含子任务）？此操作不可撤销。',
    folderGone: '文件夹已不存在', project: '项目：', lastActivity: '最近活动：', openFinder: '点击在访达中打开',
    unlink: '取消关联', link: '关联文件夹', failed: '操作失败，请重试。',
    month: (y, m) => y + ' 年 ' + m + ' 月', dayLabel: (m, d) => m + ' 月 ' + d + ' 日', week: '周日 周一 周二 周三 周四 周五 周六'.split(' '),
    emptyDaily: '还没有日报。运行 noesis build-daily 或等待后台任务生成。',
    language: '界面语言', languageHint: '仅切换界面文字；任务内容和日报保持原文。',
  },
  en: {
    brand: 'Seek truth', todo: 'To-do', daily: 'Daily', settings: 'Settings', todoSub: 'Stored locally · link folders to tasks',
    dailySub: 'Daily activity logs', search: 'Search tasks, categories, notes', create: '＋ New task', bulk: n => 'Delete selected (' + n + ')',
    cols: {title: 'Task', tag: 'Priority', status: 'Status', cat: 'Category', note: 'Notes', folder: 'Folders',
      dur: 'Time spent', upd: 'Updated', crt: 'Created', parent: 'Parent'},
    tags: {urgent_important: 'Critical', important: 'Important', urgent: 'Urgent', neither: 'Low'},
    statuses: {todo: 'To do', doing: 'Doing', done: 'Done'},
    duration: (done, d) => (done ? 'Done' : 'Open') + ' · ' + d + (d === 1 ? ' day' : ' days'),
    untitled: 'Untitled task', subtask: '＋ Subtask', delete: 'Delete', clear: 'Clear', records: n => n + (n === 1 ? ' record' : ' records'),
    newIn: s => 'New task in “' + s + '”', emptyTodo: 'No tasks yet. Click “New task” or the ＋ under a group.',
    confirmDelete: n => 'Delete ' + n + ' record(s), including subtasks? This cannot be undone.',
    folderGone: 'Folder no longer exists', project: 'Project: ', lastActivity: 'Last activity: ', openFinder: 'Click to open in Finder',
    unlink: 'Unlink', link: 'Link a folder', failed: 'Something went wrong. Please try again.',
    month: (y, m) => ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1] + ' ' + y,
    dayLabel: (m, d) => ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1] + ' ' + d,
    week: 'Sun Mon Tue Wed Thu Fri Sat'.split(' '),
    emptyDaily: 'No daily logs yet. Run noesis build-daily or wait for the background job.',
    language: 'Language', languageHint: 'Changes interface text only; tasks and daily logs keep their original wording.',
  },
};
let prefs = {lang: 'zh', view: 'todo', folded: ['done'], expanded: []};
const T = () => TEXT[prefs.lang] || TEXT.zh;
const TAG_ICON = {urgent_important: '🔥', important: '🚀', urgent: '⚡', neither: '🍃'};
const ORDER = ['todo', 'doing', 'done'];
const COLS = [['tag', '◎'], ['status', '◎'], ['cat', '◎'], ['note', 'A≡'], ['folder', '▭'], ['dur', 'ƒx'],
  ['upd', '◷'], ['crt', '◷'], ['parent', '⇡']];
let state = {todos: [], folders: {}, now: null};
const selected = new Set();
let expanded = new Set();
let folded = new Set();

async function api(method, path, body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json', 'X-Noesis-Token': TOKEN},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  // Server validation messages are Chinese; English mode shows a generic message instead.
  if (!response.ok) throw new Error(prefs.lang === 'zh' && data.error ? data.error : T().failed);
  return data;
}
function savePrefs(changes) {
  Object.assign(prefs, changes);
  api('PUT', '/api/prefs', changes).catch(error => toast(error.message));
}
function saveExpanded() { savePrefs({expanded: [...expanded]}); }
function saveFolded() { savePrefs({folded: [...folded]}); }
function toast(text) {
  const node = el('div', 'toast', text); document.body.append(node); setTimeout(() => node.remove(), 2600);
}
async function act(method, path, body) {
  try { const result = await api(method, path, body); await load(); return result; }
  catch (error) { toast(error.message); return null; }
}
async function load() {
  try { state = await api('GET', '/api/todos'); render(); } catch (error) { toast(error.message); }
}
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function shortDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-');
  return (state.now && state.now.startsWith(y) ? '' : y + '/') + m + '/' + d;
}
function duration(item) {
  const end = item.status === 'done' && item.done_at ? item.done_at : state.now;
  const days = Math.max(0, (new Date(end) - new Date(item.created_at)) / 86400000);
  const value = Math.floor(days * 10) / 10;
  return T().duration(item.status === 'done', Number.isInteger(value) ? value : Number(value.toFixed(1)));
}
function children(id) { return state.todos.filter(item => item.parent === id); }
function descendants(id) { return children(id).reduce((n, child) => n + 1 + descendants(child.id), 0); }
function matches(item, query) {
  if (!query) return true;
  const hay = [item.title, item.category, item.note, ...item.folders].join('\n').toLowerCase();
  return hay.includes(query) || children(item.id).some(child => matches(child, query));
}
function applyText() {
  document.documentElement.lang = prefs.lang === 'en' ? 'en' : 'zh-CN';
  document.querySelectorAll('[data-t]').forEach(node => { node.textContent = T()[node.dataset.t]; });
  document.querySelectorAll('[data-t-placeholder]').forEach(node => { node.placeholder = T()[node.dataset.tPlaceholder]; });
  document.querySelectorAll('#lang button').forEach(node => node.classList.toggle('on', node.dataset.lang === prefs.lang));
  const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.noesis;
  if (bridge) bridge.postMessage({action: 'language', lang: prefs.lang});  // Native menus follow the page.
}

function headRow() {
  const row = el('div', 'row head');
  const first = el('div', 'cell frozen c-title');
  const idx = el('span', 'idx');
  const all = el('input'); all.type = 'checkbox';
  all.checked = state.todos.length > 0 && selected.size === state.todos.length;
  all.onchange = () => { selected.clear(); if (all.checked) state.todos.forEach(t => selected.add(t.id)); render(); };
  idx.append(all);
  first.append(idx, el('span', 'icon', 'A≡'), el('span', 'clip', T().cols.title));
  row.append(first);
  for (const [key, icon] of COLS) {
    const cell = el('div', 'cell c-' + key); cell.append(el('span', 'icon', icon), el('span', 'clip', T().cols[key])); row.append(cell);
  }
  return row;
}

function dataRow(item, depth, number) {
  const row = el('div', 'row data' + (selected.has(item.id) ? ' selected' : ''));
  const first = el('div', 'cell frozen c-title editable');
  const idx = el('span', 'idx');
  const box = el('input'); box.type = 'checkbox'; box.checked = selected.has(item.id);
  box.onclick = event => event.stopPropagation();
  box.onchange = () => { box.checked ? selected.add(item.id) : selected.delete(item.id); render(); };
  idx.append(el('span', 'num', String(number)), box);
  first.append(idx);
  const indent = el('span'); indent.style.width = (depth * 20) + 'px'; indent.style.flex = 'none'; first.append(indent);
  const caret = el('span', 'caret');
  const kids = children(item.id);
  if (kids.length) {
    const toggle = el('button', '', expanded.has(item.id) ? '▼' : '▶');
    toggle.onclick = event => { event.stopPropagation(); expanded.has(item.id) ? expanded.delete(item.id) : expanded.add(item.id);
      saveExpanded(); render(); };
    caret.append(toggle);
  }
  first.append(caret);
  first.append(el('span', 'title' + (item.title ? '' : ' empty'), item.title || T().untitled));
  const tools = el('span', 'rowtools');
  const sub = el('button', 'tool', T().subtask);
  sub.onclick = async event => { event.stopPropagation(); expanded.add(item.id); saveExpanded();
    const made = await act('POST', '/api/todos', {parent: item.id, status: item.status === 'done' ? 'todo' : item.status});
    if (made) editTextById(made.id, 'title'); };
  const del = el('button', 'tool', T().delete);
  del.onclick = event => { event.stopPropagation(); remove([item.id]); };
  tools.append(sub, del);
  first.append(tools);
  if (kids.length) first.append(el('span', 'subcount', '↳ ' + descendants(item.id)));
  first.onclick = () => editText(first, item, 'title', 200);
  first.dataset.id = item.id; first.dataset.field = 'title';
  row.append(first);

  const tag = el('div', 'cell c-tag editable');
  if (item.tag) tag.append(el('span', 'pill tag-' + item.tag, TAG_ICON[item.tag] + ' ' + T().tags[item.tag]));
  tag.onclick = () => choose(tag, Object.keys(TAG_ICON).map(key => [key, TAG_ICON[key] + ' ' + T().tags[key], 'tag-' + key]),
    value => act('PATCH', '/api/todos/' + item.id, {tag: value}), true);
  const status = el('div', 'cell c-status editable');
  status.append(el('span', 'pill st-' + item.status, T().statuses[item.status]));
  status.onclick = () => choose(status, ORDER.map(key => [key, T().statuses[key], 'st-' + key]),
    value => act('PATCH', '/api/todos/' + item.id, {status: value}), false);
  const cat = el('div', 'cell c-cat editable');
  if (item.category) cat.append(el('span', 'pill st-todo', item.category));
  cat.onclick = () => editText(cat, item, 'category', 40);
  const note = el('div', 'cell c-note editable'); note.append(el('span', 'clip', item.note.replaceAll('\n', ' ')));
  note.title = item.note;
  note.onclick = () => editText(note, item, 'note', 2000, true);
  row.append(tag, status, cat, note, folderCell(item));
  row.append(el('div', 'cell c-dur', duration(item)), el('div', 'cell c-upd', shortDate(item.updated_at)),
    el('div', 'cell c-crt', shortDate(item.created_at)));
  const parent = state.todos.find(other => other.id === item.parent);
  const pc = el('div', 'cell c-parent'); if (parent) pc.append(el('span', 'clip', parent.title || T().untitled));
  row.append(pc);
  return row;
}

function folderCell(item) {
  const cell = el('div', 'cell c-folder');
  const list = el('span', 'folders');
  item.folders.forEach((path, index) => {
    const info = state.folders[path] || {};
    const chip = el('button', 'chip' + (info.exists === false ? ' missing' : ''));
    chip.append(el('span', '', '📁'), el('span', 'clip', path.split('/').filter(Boolean).pop() || '/'));
    chip.title = [path, info.exists === false ? T().folderGone : '', info.project ? T().project + info.project : '',
      info.last_activity ? T().lastActivity + info.last_activity.slice(0, 16).replace('T', ' ') : '', T().openFinder]
      .filter(Boolean).join('\n');
    const x = el('span', 'x', '×'); x.title = T().unlink;
    x.onclick = event => { event.stopPropagation();
      act('PATCH', '/api/todos/' + item.id, {folders: item.folders.filter((_, i) => i !== index)}); };
    chip.append(x);
    chip.onclick = () => act('POST', '/api/open-folder', {id: item.id, index});
    list.append(chip);
  });
  const add = el('button', 'add-folder', '＋'); add.title = T().link;
  add.onclick = async () => {
    const picked = await pickFolder();
    if (picked && picked.status === 'picked') act('PATCH', '/api/todos/' + item.id, {folders: [...item.folders, picked.path]});
  };
  cell.append(list, add);
  return cell;
}

function render() {
  const grid = document.getElementById('grid');
  const query = document.getElementById('search').value.trim().toLowerCase();
  for (const id of [...selected]) if (!state.todos.some(t => t.id === id)) selected.delete(id);
  const bulk = document.getElementById('bulk');
  bulk.hidden = selected.size === 0; bulk.textContent = T().bulk(selected.size);
  grid.replaceChildren(headRow());
  const ids = new Set(state.todos.map(t => t.id));
  const roots = state.todos.filter(item => !item.parent || !ids.has(item.parent));
  for (const key of ORDER) {
    const top = roots.filter(item => item.status === key && matches(item, query));
    const group = el('div', 'group' + (folded.has(key) ? ' collapsed' : ''));
    const head = el('div', 'ghead');
    const left = el('div', 'cell frozen c-title');
    const count = top.reduce((n, item) => n + 1 + descendants(item.id), 0);
    left.append(el('button', 'fold', folded.has(key) ? '▶' : '▼'), el('span', 'pill st-' + key, T().statuses[key]),
      el('span', 'count', T().records(count)));
    left.onclick = () => { folded.has(key) ? folded.delete(key) : folded.add(key); saveFolded(); render(); };
    head.append(left, el('div', 'cell rest'));
    const rows = el('div', 'rows');
    let number = 0;
    const walk = (item, depth) => {
      rows.append(dataRow(item, depth, ++number));
      if (expanded.has(item.id)) children(item.id).filter(c => matches(c, query)).forEach(child => walk(child, depth + 1));
    };
    top.forEach(item => walk(item, 0));
    const addRow = el('div', 'row addrow');
    const plus = el('div', 'cell frozen c-title', '＋'); plus.title = T().newIn(T().statuses[key]);
    plus.onclick = () => createIn(key);
    addRow.append(plus, el('div', 'cell rest'));
    rows.append(addRow);
    group.append(head, rows);
    grid.append(group);
  }
  document.getElementById('todo-count').textContent = state.todos.filter(t => t.status !== 'done').length || '';
  if (!state.todos.length) grid.append(el('div', 'empty-board', T().emptyTodo));
}

function pickFolder() {
  // Inside the NOESIS app the native panel answers; a plain browser falls back to the server's chooser.
  const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.noesis;
  if (!bridge) return act('POST', '/api/pick-folder', {});
  return new Promise(resolve => { window.noesisPicked = resolve; bridge.postMessage({action: 'pickFolder'}); });
}
async function createIn(status) {
  if (folded.delete(status)) saveFolded();
  const made = await act('POST', '/api/todos', {status});
  if (made) editTextById(made.id, 'title');
}
function editTextById(id, field) {
  const cell = document.querySelector('[data-id="' + id + '"][data-field="' + field + '"]');
  const item = state.todos.find(t => t.id === id);
  if (cell && item) { cell.scrollIntoView({block: 'nearest'}); editText(cell, item, field, 200); }
}
function closeFloating() {
  document.querySelector('.editor')?.blur();  // Saves through the editor's blur handler.
  document.querySelectorAll('.editor, .menu').forEach(node => node.remove());
}
function editText(cell, item, field, limit, multiline) {
  closeFloating();
  const input = el(multiline ? 'textarea' : 'input', 'editor');
  input.value = item[field] || ''; input.maxLength = limit;
  if (field === 'category') {
    const list = el('datalist'); list.id = 'cats';
    [...new Set(state.todos.map(t => t.category).filter(Boolean))].forEach(c => { const o = el('option'); o.value = c; list.append(o); });
    document.body.append(list); input.setAttribute('list', 'cats');
  }
  const box = cell.getBoundingClientRect();
  const width = Math.min(Math.max(box.width, multiline ? 360 : 160), innerWidth - 16);
  input.style.left = Math.min(box.left, innerWidth - width - 8) + 'px'; input.style.top = box.top + 'px';
  input.style.width = width + 'px'; input.style.minHeight = (multiline ? 120 : box.height) + 'px';
  document.body.append(input); input.focus(); input.select();
  let done = false;
  const finish = save => {
    if (done) return; done = true; input.remove(); document.getElementById('cats')?.remove();
    if (save && input.value.trim() !== (item[field] || '')) act('PATCH', '/api/todos/' + item.id, {[field]: input.value});
  };
  input.onblur = () => finish(true);
  input.onkeydown = event => {
    if (event.key === 'Escape') finish(false);
    if (event.key === 'Enter' && !event.isComposing && (!multiline || event.metaKey || event.ctrlKey)) { event.preventDefault(); finish(true); }
  };
}
function choose(cell, options, onPick, clearable) {
  closeFloating();
  const menu = el('div', 'menu');
  for (const [value, label, cls] of options) {
    const button = el('button'); button.append(el('span', 'pill ' + cls, label));
    button.onclick = () => { menu.remove(); onPick(value); }; menu.append(button);
  }
  if (clearable) { const clear = el('button', 'clear', T().clear); clear.onclick = () => { menu.remove(); onPick(null); }; menu.append(clear); }
  const box = cell.getBoundingClientRect();
  menu.style.left = box.left + 'px'; menu.style.top = (box.bottom + 4) + 'px';
  document.body.append(menu);
  const below = menu.getBoundingClientRect();
  if (below.bottom > innerHeight) menu.style.top = Math.max(8, box.top - below.height - 4) + 'px';
  if (below.right > innerWidth) menu.style.left = Math.max(8, innerWidth - below.width - 8) + 'px';
  setTimeout(() => document.addEventListener('mousedown', function away(event) {
    if (!menu.contains(event.target)) { menu.remove(); document.removeEventListener('mousedown', away); }
  }), 0);
}
async function remove(ids) {
  const total = ids.reduce((n, id) => n + 1 + descendants(id), 0);
  if (!confirm(T().confirmDelete(total))) return;
  ids.forEach(id => selected.delete(id));
  await act('POST', '/api/delete', {ids});
}

let days = [];
let currentDay = null;
async function loadDays() {
  try { days = (await api('GET', '/api/daily')).days; } catch (error) { toast(error.message); return; }
  document.getElementById('daily-count').textContent = days.length || '';
  const list = document.getElementById('days');
  list.replaceChildren();
  let month = '';
  for (const value of days) {
    const [y, m, d] = value.split('-').map(Number);
    if (y * 100 + m !== month) { month = y * 100 + m; list.append(el('div', 'month', T().month(y, m))); }
    const button = el('button', 'day' + (value === currentDay ? ' active' : ''));
    button.append(el('span', '', T().dayLabel(m, d)), el('span', 'week', T().week[new Date(y, m - 1, d).getDay()]));
    button.onclick = () => { location.hash = 'daily/' + value; };
    list.append(button);
  }
}
async function openDay(value) {
  const doc = document.getElementById('doc');
  if (!value) { doc.replaceChildren(el('div', 'empty-board', T().emptyDaily)); return; }
  currentDay = value;
  try {
    const result = await api('GET', '/api/daily/' + value);
    // Server output is escaped Markdown that only keeps http(s) links.
    const article = el('article'); article.innerHTML = result.html;
    article.querySelectorAll('a[href^="http"]').forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
    doc.replaceChildren(article); doc.scrollTop = 0;
  } catch (error) { doc.replaceChildren(el('div', 'empty-board', error.message)); }
  await loadDays();
}
async function route() {
  const [view, day] = location.hash.slice(1).split('/');
  const name = ['daily', 'settings'].includes(view) ? view : 'todo';
  closeFloating();
  for (const key of ['todo', 'daily', 'settings']) document.getElementById('view-' + key).hidden = name !== key;
  document.querySelectorAll('.nav').forEach(node => node.classList.toggle('active', node.dataset.view === name));
  document.title = 'NOESIS · ' + T()[name];
  if (prefs.view !== name) savePrefs({view: name});
  if (name === 'daily') {
    if (!days.length) await loadDays();
    const wanted = /^\d{4}-\d{2}-\d{2}$/.test(day || '') ? day : (currentDay || days[0]);
    if (wanted && wanted !== day) history.replaceState(null, '', '#daily/' + wanted);
    await openDay(wanted);
  }
}
function setLanguage(lang) {
  if (lang === prefs.lang) return;
  savePrefs({lang});
  applyText(); render(); loadDays(); route();
}

document.getElementById('create').onclick = () => createIn('todo');
document.getElementById('bulk').onclick = () => remove([...selected]);
document.getElementById('search').oninput = render;
document.getElementById('wrap').addEventListener('scroll', closeFloating);
document.querySelectorAll('#lang button').forEach(node => node.onclick = () => setLanguage(node.dataset.lang));
document.querySelectorAll('.nav').forEach(node => node.onclick = () => {
  const view = node.dataset.view;
  location.hash = view === 'daily' && currentDay ? 'daily/' + currentDay : view;
});
window.addEventListener('hashchange', route);
window.addEventListener('resize', closeFloating);
window.addEventListener('focus', () => {
  if (!document.querySelector('.editor, .menu')) load();
  loadDays();
});
(async () => {
  try { prefs = await api('GET', '/api/prefs'); } catch (error) { toast(error.message); }
  expanded = new Set(prefs.expanded);
  folded = new Set(prefs.folded);
  if (!location.hash && prefs.view !== 'todo') history.replaceState(null, '', '#' + prefs.view);
  applyText();
  await Promise.all([load(), loadDays()]);
  route();
})();
</script>
</body>
</html>
'''
