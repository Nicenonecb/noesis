"""Single-file todo board page in a Bitable-style grid; shipped as Python so the .pyz bundle carries it."""

PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NOESIS 待办</title>
<style>
:root {
  --text: #1f2329; --text-2: #646a73; --text-3: #8f959e; --line: #dee0e3; --line-2: #eff0f1;
  --bg: #ffffff; --bg-hover: #f5f6f7; --bg-head: #ffffff; --blue: #3370ff; --blue-bg: #e1eaff;
  --red: #d83931; --orange: #ff8800; --yellow: #dc9b04; --gray: #8f959e; --green: #34c724;
  --row: 32px;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text);
  font: 13px/1.5 -apple-system, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif; }
button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; }
.top { display: flex; align-items: center; gap: 12px; padding: 14px 20px 10px; border-bottom: 1px solid var(--line-2); }
.top h1 { font-size: 16px; font-weight: 600; margin: 0 8px 0 0; }
.top .sub { color: var(--text-3); font-size: 12px; }
.spacer { flex: 1; }
.search { height: 28px; width: 220px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; font: inherit; outline: none; }
.search:focus { border-color: var(--blue); }
.btn { height: 28px; padding: 0 12px; border-radius: 6px; border: 1px solid var(--line); background: #fff; }
.btn:hover { background: var(--bg-hover); }
.btn.primary { background: var(--blue); border-color: var(--blue); color: #fff; }
.btn.primary:hover { background: #4e83fd; }
.btn.danger { color: var(--red); }
.btn[hidden] { display: none; }
.wrap { overflow: auto; height: calc(100vh - 53px); padding: 0 0 40px; }
.grid { display: inline-block; min-width: 100%; }
.row { display: flex; min-height: var(--row); }
.cell { flex: none; border-right: 1px solid var(--line-2); border-bottom: 1px solid var(--line-2);
  padding: 0 8px; display: flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden; background: inherit; }
.cell.frozen { position: sticky; left: 0; z-index: 2; border-right: 1px solid var(--line); }
.head { position: sticky; top: 0; z-index: 4; background: var(--bg-head); }
.head .cell { height: 36px; color: var(--text-2); border-bottom: 1px solid var(--line); background: var(--bg-head); }
.head .cell.frozen { z-index: 5; }
.head .icon { color: var(--text-3); font-size: 12px; width: 16px; text-align: center; flex: none; }
.data { background: #fff; }
.data:hover, .data.selected { background: var(--bg-hover); }
.data .cell { cursor: default; }
.data .cell.editable:hover { box-shadow: inset 0 0 0 1px #bacefd; }
.c-title { width: 500px; } .c-tag { width: 150px; } .c-status { width: 112px; } .c-cat { width: 150px; }
.c-note { width: 240px; } .c-folder { width: 280px; } .c-dur { width: 170px; } .c-upd { width: 150px; }
.c-crt { width: 150px; } .c-parent { width: 160px; } .c-add { width: 56px; border-right: 0; }
.idx { width: 36px; flex: none; color: var(--text-3); font-size: 12px; text-align: center; position: relative; }
.idx input { display: none; margin: 0; }
.data:hover .idx .num, .data.selected .idx .num { display: none; }
.data:hover .idx input, .data.selected .idx input { display: inline-block; }
.head .idx input { display: inline-block; }
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
  font-size: 12px; white-space: nowrap; line-height: 20px; }
.tag-urgent_important { background: var(--red); color: #fff; }
.tag-important { background: var(--orange); color: #fff; }
.tag-urgent { background: var(--yellow); color: #fff; }
.tag-neither { background: var(--gray); color: #fff; }
.st-todo { background: var(--blue-bg); color: #1f2329; }
.st-doing { background: #fff1d6; color: #8f5c00; }
.st-done { background: var(--green); color: #fff; }
.muted { color: var(--text-3); }
.clip { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.folders { display: flex; gap: 4px; align-items: center; min-width: 0; overflow: hidden; flex: 1; }
.chip { display: inline-flex; align-items: center; gap: 4px; height: 22px; max-width: 170px; padding: 0 6px;
  border-radius: 4px; background: #f0f1f2; color: var(--text); font-size: 12px; flex: none; }
.chip:hover { background: var(--blue-bg); color: var(--blue); }
.chip .x { display: none; color: var(--text-3); padding: 0 1px; }
.chip:hover .x { display: inline; }
.chip .x:hover { color: var(--red); }
.chip.missing { text-decoration: line-through; color: var(--text-3); }
.add-folder { display: none; flex: none; width: 22px; height: 22px; border-radius: 4px; color: var(--text-2); font-size: 15px; }
.data:hover .add-folder, .add-folder.always { display: inline-block; }
.add-folder:hover { background: var(--line); color: var(--blue); }
.group { margin: 12px 0 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.ghead { display: flex; height: 36px; background: #fff; }
.ghead .cell { border-bottom: 0; }
.ghead .cell.rest { flex: 1; border-right: 0; }
.ghead .fold { width: 20px; color: var(--text-2); font-size: 10px; }
.ghead .count { margin-left: auto; color: var(--text-3); font-size: 12px; }
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
</style>
</head>
<body>
<div class="top">
  <h1>待办</h1><span class="sub">NOESIS · 本机保存，可关联文件夹</span>
  <span class="spacer"></span>
  <input class="search" id="search" placeholder="搜索任务、类别、备忘">
  <button class="btn danger" id="bulk" hidden>删除所选</button>
  <button class="btn primary" id="create">＋ 新建任务</button>
</div>
<div class="wrap" id="wrap"><div class="grid" id="grid"></div></div>
<script>
'use strict';
const TOKEN = '__TOKEN__';
const TAG_ICON = {urgent_important: '🔥', important: '🚀', urgent: '⚡', neither: '🍃'};
const ORDER = ['todo', 'doing', 'done'];
const COLS = [
  ['c-tag', '◎', '任务标签'], ['c-status', '◎', '状态'], ['c-cat', '◎', '任务类别'],
  ['c-note', 'A≡', '解决办法/备忘'], ['c-folder', '▭', '关联文件夹'], ['c-dur', 'ƒx', '任务耗时'],
  ['c-upd', '◷', '任务更新时间'], ['c-crt', '◷', '任务创建时间'], ['c-parent', '⇡', '父记录'],
];
let state = {todos: [], folders: {}, tags: {}, statuses: {}, now: null};
const selected = new Set();
const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
function remembered(key) { try { return new Set(JSON.parse(store.getItem(key) || '[]')); } catch (e) { return new Set(); } }
function remember(key, set) { try { store.setItem(key, JSON.stringify([...set])); } catch (e) {} }
const expanded = remembered('noesis.todo.expanded');
const folded = remembered('noesis.todo.folded');
const foldedDefault = !store || store.getItem('noesis.todo.folded') === null;
if (foldedDefault) folded.add('done');

async function api(method, path, body) {
  const response = await fetch(path, {method, headers: {'Content-Type': 'application/json', 'X-Noesis-Token': TOKEN},
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || '操作失败，请重试。');
  return data;
}
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
function day(iso) { return iso ? iso.slice(0, 10).replaceAll('-', '/') : ''; }
function duration(item) {
  const end = item.status === 'done' && item.done_at ? item.done_at : state.now;
  const days = Math.max(0, (new Date(end) - new Date(item.created_at)) / 86400000);
  const value = Math.floor(days * 10) / 10;
  return (item.status === 'done' ? '已完成' : '未完成') + '，耗时' + (Number.isInteger(value) ? value : value.toFixed(1)) + '天';
}
function children(id) { return state.todos.filter(item => item.parent === id); }
function descendants(id) { return children(id).reduce((n, child) => n + 1 + descendants(child.id), 0); }
function matches(item, query) {
  if (!query) return true;
  const hay = [item.title, item.category, item.note, ...item.folders].join('\n').toLowerCase();
  return hay.includes(query) || children(item.id).some(child => matches(child, query));
}

function headRow() {
  const row = el('div', 'row head');
  const first = el('div', 'cell frozen c-title');
  const idx = el('span', 'idx');
  const all = el('input'); all.type = 'checkbox';
  all.checked = state.todos.length > 0 && selected.size === state.todos.length;
  all.onchange = () => { selected.clear(); if (all.checked) state.todos.forEach(t => selected.add(t.id)); render(); };
  idx.append(all);
  first.append(idx, el('span', 'icon', 'A≡'), el('span', '', '任务名称'));
  row.append(first);
  for (const [cls, icon, label] of COLS) {
    const cell = el('div', 'cell ' + cls); cell.append(el('span', 'icon', icon), el('span', 'clip', label)); row.append(cell);
  }
  row.append(el('div', 'cell c-add'));
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
      remember('noesis.todo.expanded', expanded); render(); };
    caret.append(toggle);
  }
  first.append(caret);
  first.append(el('span', 'title' + (item.title ? '' : ' empty'), item.title || '未命名任务'));
  const tools = el('span', 'rowtools');
  const sub = el('button', 'tool', '＋ 子任务');
  sub.onclick = async event => { event.stopPropagation(); expanded.add(item.id); remember('noesis.todo.expanded', expanded);
    const made = await act('POST', '/api/todos', {parent: item.id, status: item.status === 'done' ? 'todo' : item.status});
    if (made) editTextById(made.id, 'title'); };
  const del = el('button', 'tool', '删除');
  del.onclick = event => { event.stopPropagation(); remove([item.id]); };
  tools.append(sub, del);
  first.append(tools);
  if (kids.length) first.append(el('span', 'subcount', '↳ ' + descendants(item.id)));
  first.onclick = () => editText(first, item, 'title', 200);
  first.dataset.id = item.id; first.dataset.field = 'title';
  row.append(first);

  const tag = el('div', 'cell c-tag editable');
  if (item.tag) { const pill = el('span', 'pill tag-' + item.tag, TAG_ICON[item.tag] + ' ' + state.tags[item.tag]); tag.append(pill); }
  tag.onclick = () => choose(tag, Object.entries(state.tags).map(([key, label]) => [key, TAG_ICON[key] + ' ' + label, 'tag-' + key]),
    value => act('PATCH', '/api/todos/' + item.id, {tag: value}), true);
  const status = el('div', 'cell c-status editable');
  status.append(el('span', 'pill st-' + item.status, state.statuses[item.status]));
  status.onclick = () => choose(status, ORDER.map(key => [key, state.statuses[key], 'st-' + key]),
    value => act('PATCH', '/api/todos/' + item.id, {status: value}), false);
  const cat = el('div', 'cell c-cat editable');
  if (item.category) cat.append(el('span', 'pill st-todo', item.category));
  cat.onclick = () => editText(cat, item, 'category', 40);
  const note = el('div', 'cell c-note editable'); note.append(el('span', 'clip', item.note.replaceAll('\n', ' ')));
  note.title = item.note;
  note.onclick = () => editText(note, item, 'note', 2000, true);
  row.append(tag, status, cat, note, folderCell(item));
  row.append(el('div', 'cell c-dur', duration(item)), el('div', 'cell c-upd', day(item.updated_at)),
    el('div', 'cell c-crt', day(item.created_at)));
  const parent = state.todos.find(other => other.id === item.parent);
  const pc = el('div', 'cell c-parent'); if (parent) pc.append(el('span', 'clip', parent.title || '未命名任务'));
  row.append(pc, el('div', 'cell c-add'));
  return row;
}

function folderCell(item) {
  const cell = el('div', 'cell c-folder');
  const list = el('span', 'folders');
  item.folders.forEach((path, index) => {
    const info = state.folders[path] || {};
    const name = path.split('/').filter(Boolean).pop() || '/';
    const chip = el('button', 'chip' + (info.exists === false ? ' missing' : ''));
    chip.append(el('span', '', '📁'), el('span', 'clip', name));
    chip.title = path + (info.exists === false ? '\n文件夹已不存在' : '') + (info.project ? '\n项目：' + info.project : '') + (info.last_activity ? '\n最近活动：' + info.last_activity.slice(0, 16).replace('T', ' ') : '') + '\n点击在访达中打开';
    const x = el('span', 'x', '×'); x.title = '取消关联';
    x.onclick = event => { event.stopPropagation();
      act('PATCH', '/api/todos/' + item.id, {folders: item.folders.filter((_, i) => i !== index)}); };
    chip.append(x);
    chip.onclick = () => act('POST', '/api/open-folder', {id: item.id, index});
    list.append(chip);
  });
  const add = el('button', 'add-folder', '＋'); add.title = '关联文件夹';
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
  bulk.hidden = selected.size === 0; bulk.textContent = '删除所选（' + selected.size + '）';
  grid.replaceChildren(headRow());
  const ids = new Set(state.todos.map(t => t.id));
  const roots = state.todos.filter(item => !item.parent || !ids.has(item.parent));
  for (const key of ORDER) {
    const top = roots.filter(item => item.status === key && matches(item, query));
    const group = el('div', 'group' + (folded.has(key) ? ' collapsed' : ''));
    const head = el('div', 'ghead');
    const left = el('div', 'cell frozen c-title');
    const fold = el('button', 'fold', folded.has(key) ? '▶' : '▼');
    const count = top.reduce((n, item) => n + 1 + descendants(item.id), 0);
    left.append(fold, el('span', 'pill st-' + key, state.statuses[key]), el('span', 'count', count + ' 条记录'));
    left.style.cursor = 'pointer';
    left.onclick = () => { folded.has(key) ? folded.delete(key) : folded.add(key); remember('noesis.todo.folded', folded); render(); };
    head.append(left, el('div', 'cell rest'));
    const rows = el('div', 'rows');
    let number = 0;
    const walk = (item, depth) => {
      rows.append(dataRow(item, depth, ++number));
      if (expanded.has(item.id)) children(item.id).filter(c => matches(c, query)).forEach(child => walk(child, depth + 1));
    };
    top.forEach(item => walk(item, 0));
    const addRow = el('div', 'row addrow');
    const plus = el('div', 'cell frozen c-title', '＋'); plus.title = '在「' + state.statuses[key] + '」中新建任务';
    plus.onclick = () => createIn(key);
    addRow.append(plus, el('div', 'cell rest')); addRow.lastChild.style.flex = '1'; addRow.lastChild.style.borderRight = '0';
    rows.append(addRow);
    group.append(head, rows);
    grid.append(group);
  }
  if (!state.todos.length) grid.append(el('div', 'empty-board', '还没有任务。点击右上角「新建任务」，或在分组底部点击 ＋。'));
}

function pickFolder() {
  // Inside the NOESIS app the native panel answers; a plain browser falls back to the server's chooser.
  const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.noesis;
  if (!bridge) return act('POST', '/api/pick-folder', {});
  return new Promise(resolve => { window.noesisPicked = resolve; bridge.postMessage({action: 'pickFolder'}); });
}
async function createIn(status) {
  folded.delete(status); remember('noesis.todo.folded', folded);
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
function place(node, cell, minHeight) {
  const box = cell.getBoundingClientRect();
  node.style.left = box.left + 'px'; node.style.top = box.top + 'px';
  node.style.width = Math.max(box.width, 160) + 'px'; node.style.minHeight = (minHeight || box.height) + 'px';
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
  place(input, cell, multiline ? 120 : 0);
  if (multiline) input.style.width = Math.max(cell.getBoundingClientRect().width, 360) + 'px';
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
  if (clearable) { const clear = el('button', 'clear', '清除'); clear.onclick = () => { menu.remove(); onPick(null); }; menu.append(clear); }
  const box = cell.getBoundingClientRect();
  menu.style.left = box.left + 'px'; menu.style.top = (box.bottom + 4) + 'px';
  document.body.append(menu);
  const below = menu.getBoundingClientRect();
  if (below.bottom > innerHeight) menu.style.top = Math.max(8, box.top - below.height - 4) + 'px';
  setTimeout(() => document.addEventListener('mousedown', function away(event) {
    if (!menu.contains(event.target)) { menu.remove(); document.removeEventListener('mousedown', away); }
  }), 0);
}
async function remove(ids) {
  const total = ids.reduce((n, id) => n + 1 + descendants(id), 0);
  if (!confirm('删除 ' + total + ' 条记录（含子任务）？此操作不可撤销。')) return;
  ids.forEach(id => selected.delete(id));
  await act('POST', '/api/delete', {ids});
}
document.getElementById('create').onclick = () => createIn('todo');
document.getElementById('bulk').onclick = () => remove([...selected]);
document.getElementById('search').oninput = render;
document.getElementById('wrap').addEventListener('scroll', closeFloating);
window.addEventListener('focus', () => { if (!document.querySelector('.editor, .menu')) load(); });
load();
</script>
</body>
</html>
'''
