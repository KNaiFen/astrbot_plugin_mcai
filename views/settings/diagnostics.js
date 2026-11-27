import { node } from './controls.js';

const categories = { tasks: '排障任务', questions: '只读问答' };
const rangeError = '开始时间不能晚于结束时间';

function timestamp(value, precise, end = false) {
  if (!value) return null;
  const local = precise
    ? value.slice(0, 16) + (end ? ':59.999' : ':00.000')
    : value + (end ? 'T23:59:59.999' : 'T00:00:00.000');
  return new Date(local).getTime() / 1000;
}

function localDate(date) {
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function rangeSummary(start, end) {
  return start && end ? `${start} ~ ${end}` : start ? `${start} 起` : end ? `至 ${end}` : '';
}

export function createDiagnosticsState(storageStates) {
  return {
    scope: 'tasks', search: '', start: '', end: '', precise: false, clipSelected: false,
    records: { tasks: [], questions: [] }, selected: new Set(),

    refresh({ tasks, questions }) {
      this.records = { tasks, questions };
      const ids = new Set([...tasks, ...questions].map(row => row.id));
      for (const id of this.selected) if (!ids.has(id)) this.selected.delete(id);
    },

    setPrecise(precise) {
      this.precise = precise;
      this.start = this.start ? this.start.slice(0, 10) + (precise ? 'T00:00' : '') : '';
      this.end = this.end ? this.end.slice(0, 10) + (precise ? 'T23:59' : '') : '';
    },

    setPreset(days, today = new Date()) {
      if (!days) { this.start = this.end = ''; return; }
      const first = new Date(today);
      first.setDate(first.getDate() - days + 1);
      this.start = localDate(first) + (this.precise ? 'T00:00' : '');
      this.end = localDate(today) + (this.precise ? 'T23:59' : '');
    },

    get range() {
      const start = timestamp(this.start, this.precise), end = timestamp(this.end, this.precise, true);
      return { start, end, active: start !== null || end !== null, invalid: start !== null && end !== null && start > end };
    },

    get keywords() {
      const query = this.scope === 'all' ? '' : this.search.trim().toLowerCase();
      return query ? query.split(/\s+/) : [];
    },

    get visible() {
      const { start, end, active, invalid } = this.range, words = this.keywords;
      return Object.fromEntries(Object.entries(this.records).map(([scope, rows]) => [scope, rows.filter(row => {
        if (invalid) return false;
        if (active) {
          if (!Number.isFinite(row.created)) return false;
          const settled = scope === 'tasks' && Number.isFinite(row.settled_at) && row.settled_at >= row.created;
          if (row.created > (end ?? Infinity) || (settled ? row.settled_at : row.created) < (start ?? -Infinity)) return false;
        }
        if (!words.length) return true;
        const fields = [row.name, row.id, row.group];
        if (scope === 'tasks') fields.push(row.instance, row.state, storageStates[row.state]);
        const text = fields.join(' ').toLowerCase();
        return words.every(word => text.includes(word));
      })]));
    },

    select(id, checked) {
      if (checked) this.selected.add(id);
      else this.selected.delete(id);
    },

    selectCurrent(checked) {
      for (const row of this.visible[this.scope]) this.select(row.id, checked);
    },

    get selectionCounts() {
      return Object.fromEntries(Object.entries(this.records).map(([scope, rows]) => [scope,
        rows.filter(row => this.selected.has(row.id)).length,
      ]));
    },

    get usesRange() { return !this.selected.size || this.clipSelected; },

    exportPayload() {
      const { start, end, invalid } = this.range;
      if (this.usesRange && invalid) throw new Error(rangeError);
      const task_ids = [...this.selected];
      return {
        start: this.usesRange ? start ?? 0 : 0,
        end: this.usesRange ? end : null,
        task_ids,
        ...(task_ids.length ? {} : { scope: this.scope }),
      };
    },
  };
}

export function setupDiagnostics(storageStates) {
  const state = createDiagnosticsState(storageStates);
  const $ = id => document.getElementById(`diagnostics-${id}`);
  const tabs = [...document.querySelectorAll('.diag-tabs [role="tab"]')];
  const search = $('search'), searchPlaceholder = search.placeholder;
  const datePanel = $('date-panel'), dateToggle = $('date-toggle'), quickClear = $('date-clear-quick');
  const start = $('start'), end = $('end'), dateError = $('date-error');
  const list = $('list'), clearSelected = $('clear-selected');
  const selectCurrent = $('select-current'), unselectCurrent = $('unselect-current');

  function renderSelection(visible) {
    const { size } = state.selected, counts = state.selectionCounts;
    const description = `${size} 项（排障任务 ${counts.tasks}、只读问答 ${counts.questions}）`;
    for (const tab of tabs) {
      const scope = tab.dataset.scope;
      if (scope === 'all') continue;
      const badge = tab.lastElementChild;
      badge.hidden = !counts[scope];
      badge.textContent = counts[scope] ? `已选 ${counts[scope]}` : '';
    }
    selectCurrent.disabled = !visible?.some(row => !state.selected.has(row.id));
    unselectCurrent.disabled = !visible?.some(row => state.selected.has(row.id));
    clearSelected.disabled = !size;
    $('selection-summary').textContent = size ? `已选 ${description}` : '未勾选具体项';
    $('all-warning').hidden = !size;
    $('all-warning-text').textContent = `已勾选 ${size} 项，直接导出将仅导出这 ${size} 项；如需导出全部与全局日志，请先点击「清空全部已选」。`;

    const { active, invalid } = state.range;
    const time = rangeSummary(state.start.replace('T', ' '), state.end.replace('T', ' ')) || '不限时间';
    let hint;
    if (state.usesRange && invalid) {
      hint = `无法导出：${rangeError}。`;
    } else if (size) {
      hint = state.clipSelected && active
        ? `将导出已勾选的 ${description}，并按所设时间范围截取日志事件。`
        : `将导出已勾选的 ${description}的完整日志。`;
    } else if (state.scope === 'all') {
      hint = `未勾选具体项：将导出全部排障任务、只读问答及全局无任务日志（${time}）。`;
    } else {
      const other = state.scope === 'tasks' ? 'questions' : 'tasks';
      hint = `未勾选具体项：将导出全部${categories[state.scope]}（${time}），不含${categories[other]}与全局日志。`;
      if (state.keywords.length) hint += '搜索词仅用于筛选列表，如需仅导出当前搜索结果请先点击「全选当前」。';
    }
    $('export-hint').textContent = hint;
  }

  function render() {
    const { scope } = state, all = scope === 'all';
    const { active, invalid } = state.range, visible = state.visible;
    search.disabled = all;
    search.placeholder = all ? '切换到排障任务或只读问答后可按关键词搜索' : searchPlaceholder;
    const summary = rangeSummary(state.start.slice(5).replace('T', ' '), state.end.slice(5).replace('T', ' '));
    dateToggle.textContent = `${summary || '日期筛选'} ${datePanel.hidden ? '▾' : '▴'}`;
    dateToggle.classList.toggle('is-active', active);
    dateToggle.setAttribute('aria-expanded', String(!datePanel.hidden));
    quickClear.hidden = !active;
    dateError.hidden = !invalid;
    dateError.textContent = invalid ? rangeError : '';

    for (const tab of tabs) {
      const category = tab.dataset.scope, current = category === scope;
      tab.setAttribute('aria-selected', String(current));
      tab.tabIndex = current ? 0 : -1;
      if (current) $('records').setAttribute('aria-labelledby', tab.id);
      if (category === 'all') continue;
      const total = state.records[category].length;
      const count = active || state.keywords.length ? `${visible[category].length}/${total}` : total;
      tab.firstElementChild.textContent = `${categories[category]} (${count})`;
    }
    $('selection-actions').hidden = all;
    $('all').hidden = !all;
    list.hidden = all;
    list.replaceChildren();
    if (all) {
      $('all-count').textContent = invalid ? rangeError : `当前时间范围：排障任务 ${visible.tasks.length} 个 · 只读问答 ${visible.questions.length} 条`;
    } else if (invalid || !visible[scope].length) {
      const empty = state.records[scope].length ? '当前搜索或日期筛选下没有匹配记录' : `暂无${categories[scope]}`;
      list.append(node('p', invalid ? rangeError : empty, invalid ? 'modal-error' : 'hint'));
    } else {
      const rows = document.createDocumentFragment();
      for (const row of visible[scope]) {
        const item = node('label', null, 'diag-item'), checkbox = node('input');
        checkbox.type = 'checkbox';
        checkbox.checked = state.selected.has(row.id);
        checkbox.value = row.id;
        checkbox.onchange = () => { state.select(row.id, checkbox.checked); renderSelection(visible[scope]); };
        const info = node('span'), title = node('span', null, 'diag-item-title');
        title.append(node('span', row.name || '未命名'));
        if (scope === 'tasks') title.append(node('span', storageStates[row.state] ?? row.state ?? '状态未知', 'badge'));
        const time = Number.isFinite(row.created) ? new Date(row.created * 1000).toLocaleString() : '时间未知';
        const instance = scope === 'tasks' ? ` · 实例 ${row.instance || '待识别'}` : '';
        const meta = node('span', `${time} · 群 ${row.group ?? '未知'}${instance} · `, 'hint diag-item-meta');
        const id = node('span', scope === 'tasks' ? row.id.slice(0, 8) : row.id);
        id.title = row.id;
        meta.append(id);
        info.append(title, meta);
        item.append(checkbox, info);
        rows.append(item);
      }
      list.append(rows);
    }
    renderSelection(visible[scope]);
  }

  for (const [index, tab] of tabs.entries()) {
    tab.onclick = () => { state.scope = tab.dataset.scope; render(); };
    tab.onkeydown = event => {
      const last = tabs.length - 1;
      const next = { ArrowLeft: index ? index - 1 : last, ArrowRight: index === last ? 0 : index + 1, Home: 0, End: last }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      tabs[next].click();
      tabs[next].focus();
    };
  }
  search.oninput = () => { state.search = search.value; render(); };
  dateToggle.onclick = () => { datePanel.hidden = !datePanel.hidden; render(); };
  start.oninput = end.oninput = () => { state.start = start.value; state.end = end.value; render(); };
  function syncDates() { start.value = state.start; end.value = state.end; render(); }
  function preset(days) { state.setPreset(days); syncDates(); }
  quickClear.onclick = () => { preset(0); dateToggle.focus(); };
  for (const button of $('date-presets').children) button.onclick = () => preset(Number(button.dataset.days));
  $('precise-time').onchange = event => {
    state.setPrecise(event.target.checked);
    start.type = end.type = state.precise ? 'datetime-local' : 'date';
    $('start-label').textContent = state.precise ? '开始时间' : '开始日期';
    $('end-label').textContent = state.precise ? '结束时间' : '结束日期';
    syncDates();
  };
  $('clip-selected').onchange = event => { state.clipSelected = event.target.checked; render(); };
  function syncSelection() {
    for (const checkbox of list.querySelectorAll('input')) checkbox.checked = state.selected.has(checkbox.value);
    renderSelection(state.visible[state.scope]);
  }
  selectCurrent.onclick = () => { state.selectCurrent(true); syncSelection(); };
  unselectCurrent.onclick = () => { state.selectCurrent(false); syncSelection(); };
  clearSelected.onclick = $('all-clear').onclick = () => { state.selected.clear(); syncSelection(); };
  render();
  return {
    refresh(data) { state.refresh(data); render(); },
    exportPayload: () => state.exportPayload(),
  };
}
