const bridge = window.AstrBotPluginView;
await bridge.ready();
const form = document.querySelector('#a-settings'), notice = document.querySelector('#notice');
const restartWindow = document.querySelector('#incident-restart-window');
const incidentCapacity = document.querySelector('#incident-capacity');
const incidentForm = document.querySelector('#incident-settings');
const sections = document.querySelectorAll('.settings-nav a');
function markSection() {
  const current = Array.from(sections).find(link => link.hash === location.hash) ?? sections[0];
  for (const link of sections) {
    if (link === current) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  }
}
markSection();
window.addEventListener('hashchange', markSection);
let host = null, poll = null;
function show(text, error = false) { notice.textContent = text; notice.classList.toggle('error', error); }
async function api(method, path, data) {
  const response = method === 'GET' ? await bridge.apiGet(path) : await bridge.apiPost(path, data ?? {});
  if (response.status === 'error' || response.error) throw new Error(response.message || response.error);
  return response.data ?? response;
}
async function action(button, call) { button.disabled = true; try { await call(); } catch (error) { show(error.message, true); } finally { button.disabled = false; } }
function values() {
  const result = {};
  for (const element of form.elements) {
    if (!element.name) continue;
    result[element.name] = element.type === 'checkbox' ? element.checked : element.type === 'number' ? Number(element.value) : element.tagName === 'TEXTAREA' ? element.value.split(/[\s,，]+/).filter(Boolean) : element.value;
  }
  if (!result.host_token) delete result.host_token;
  if (!result.curseforge_api_key) delete result.curseforge_api_key;
  return result;
}
async function loadA() {
  const data = await api('GET', 'settings');
  for (const name of ['provider_id', 'review_provider_id']) {
    const select = form.elements[name];
    select.replaceChildren(new Option(name === 'provider_id' ? '使用当前群模型' : '请选择审核模型', ''));
    for (const item of data.providers) select.add(new Option(`${item.name} · ${item.model} · ${item.type} (${item.id})`, item.id));
  }
  for (const [key, value] of Object.entries(data.config)) {
    const element = form.elements[key]; if (!element) continue;
    if (element.type === 'checkbox') element.checked = value;
    else element.value = Array.isArray(value) ? value.join('\n') : value;
  }
  form.elements.host_token.value = '';
  form.elements.host_token.placeholder = data.host_token_configured ? '已配置；留空保留' : '填写共享令牌';
  form.elements.curseforge_api_key.value = '';
  form.elements.curseforge_api_key.placeholder = data.curseforge_configured ? 'A 已配置；留空保留' : '填写 CurseForge API 密钥';
  document.querySelector('#curseforge-state').textContent = data.curseforge_configured ? 'A 已保存密钥；不会回传原值。' : 'A 尚未配置 CurseForge 密钥。';
}
async function saveA() { await api('POST', 'settings', values()); }
form.addEventListener('submit', event => { event.preventDefault(); action(event.submitter, async () => { await saveA(); show('A 配置已保存并生效。'); }); });
document.querySelector('#connection-test').onclick = function () { action(this, async () => { const result = await api('POST', 'connection/test', values()); show(`连接成功，B 配置了 ${result.instances} 个服务端。`); }); };
function field(container, label, value, key) {
  const wrapper = document.createElement('label'); wrapper.append(document.createTextNode(label));
  const input = document.createElement('input'); input.type = key === 'test_port' || key === 'stop_timeout' ? 'number' : 'text'; input.value = value ?? ''; input.dataset.key = key; wrapper.append(input); container.append(wrapper); return input;
}
const instanceAlerts = {
  alert_window: ['托管窗口掉线告警', true],
  alert_window_minutes: ['窗口连续掉线分钟数', 3],
  alert_disk: ['磁盘空间告警', true],
  alert_disk_gib: ['磁盘剩余阈值（GiB）', 10],
  alert_performance: ['Probe 性能告警', false],
  alert_mspt: ['平均 MSPT 阈值（毫秒）', 50],
  alert_performance_minutes: ['性能持续偏低分钟数', 3],
};
function instance(name = '', config = {}, state = {}) {
  const card = document.createElement('article'); card.className = 'instance';
  const heading = document.createElement('header'), identity = document.createElement('div');
  heading.className = 'instance-heading';
  const title = document.createElement('strong'), status = document.createElement('span'), remove = document.createElement('button');
  title.textContent = name || '新服务端';
  status.className = 'instance-state';
  status.textContent = !name ? '未保存' : state.state_unknown ? '状态待确认' : state.running ? '运行中' : '已停服';
  if (name && !state.window_online) status.textContent += ' · 无托管连接';
  if (state.configuration_pending) status.textContent += ' · 配置待生效';
  if (state.selectable === false) status.textContent += ' · 待移除';
  status.classList.toggle('running', !!state.running && !state.state_unknown);
  remove.type = 'button'; remove.className = 'quiet'; remove.textContent = '移除配置'; remove.onclick = () => card.remove();
  identity.append(title, status); heading.append(identity, remove); card.append(heading);
  const basics = document.createElement('div'); basics.className = 'columns'; card.append(basics);
  field(basics, '配置名', name, 'name'); field(basics, '说明／群内叫法', config.description, 'description');
  field(card, '服务端目录（其中使用 start.bat）', config.directory, 'directory');
  const advanced = document.createElement('details'), summary = document.createElement('summary');
  const body = document.createElement('div'), options = document.createElement('div');
  summary.textContent = '高级选项'; body.className = 'details-body'; options.className = 'columns';
  advanced.append(summary, body); body.append(options);
  for (const [key, label] of Object.entries({ java_path: '实例 Java 路径（可选）', encoding: 'BAT 编码（默认 auto）', stop_timeout: '停服超时秒（默认 120）', stop_command: 'MC 停服命令（默认 stop）', restart_prompt: '自动重启提示（默认约定提示）', test_address: '测试服可达地址', test_port: '测试服专用端口' })) field(options, label, config[key], key);
  const paths = document.createElement('label'); paths.append('试服复制清单（每行一个相对路径）');
  const list = document.createElement('textarea'); list.dataset.key = 'test_copy_paths'; list.value = (config.test_copy_paths ?? []).join('\n'); paths.append(list); body.append(paths);
  const watch = document.createElement('label'); watch.className = 'toggle';
  const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.dataset.key = 'incident_watch'; toggle.checked = config.incident_watch ?? false; watch.append(toggle, '主动保留故障现场'); body.append(watch);
  const alerts = document.createElement('div'); alerts.className = 'columns';
  for (const [key, [label, initial]] of Object.entries(instanceAlerts)) {
    const input = field(alerts, label, config[key] ?? initial, key);
    if (typeof initial === 'boolean') {
      input.type = 'checkbox'; input.checked = config[key] ?? initial;
      input.parentElement.className = 'toggle'; input.parentElement.prepend(input);
    } else {
      input.type = 'number'; input.step = 'any';
    }
  }
  body.append(alerts);
  card.append(advanced); document.querySelector('#instances').append(card);
}
async function loadHost() {
  host = await api('GET', 'host'); document.querySelector('#instances').replaceChildren();
  for (const [name, config] of Object.entries(host.instances)) instance(name, config, host.state.find(item => item.instance === name));
  for (const state of host.state.filter(item => item.selectable === false)) { const p = document.createElement('p'); p.textContent = `${state.instance}：待移除，当前进程与操作仍可管理。`; document.querySelector('#instances').append(p); }
  document.querySelector('#powershell-path').value = host.powershell_path; document.querySelector('#world-java').value = host.world_tools.java_path ?? ''; document.querySelector('#operations-memory').value = host.operations_memory_limit_mib ?? 8192;
  showIncidentSettings(host);
  if (host.error) show(`实例热重载错误：${host.error}`, true);
  else if (host.restart_required) show(`主机配置已保存，重启 B 后生效。当前运行：PowerShell ${host.effective.powershell_path}；存档 Java 配置 ${host.effective.world_tools.java_path || '默认'}；额度 ${host.effective.operations_memory_limit_mib} MiB。`);
}
document.querySelector('#load-host').onclick = function () { action(this, loadHost); };
document.querySelector('#add-instance').onclick = () => instance();
document.querySelector('#save-instances').onclick = function () {
  action(this, async () => {
    if (!host) throw new Error('请先刷新 B 配置。'); const instances = {};
    for (const card of document.querySelectorAll('.instance')) {
      const config = {}; let name = '';
      for (const input of card.querySelectorAll('input, textarea')) {
        const key = input.dataset.key;
        if (key === 'name') name = input.value.trim();
        else if (key === 'incident_watch') { if (input.checked) config[key] = true; }
        else if (key in instanceAlerts) config[key] = input.type === 'checkbox' ? input.checked : Number(input.value || instanceAlerts[key][1]);
        else if (key === 'test_copy_paths') { if (input.value.trim()) config[key] = input.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean); }
        else if (input.value.trim()) config[key] = input.type === 'number' ? Number(input.value) : input.value;
      }
      if (!name || instances[name]) throw new Error('配置名不能为空或重复。'); instances[name] = config;
    }
    await api('POST', 'host', { instances, revision: host.revision }); await loadHost(); show('服务端配置已保存；运行中的启动变更会等待空闲。');
  });
};
document.querySelector('#test-key').onclick = function () { action(this, async () => { await api('POST', 'host/curseforge/test'); show('CurseForge 凭据已从 A 端验证。'); }); };
document.querySelector('#clear-key').onclick = function () { action(this, async () => { const result = values(); result.curseforge_api_key = ''; await api('POST', 'settings', result); await loadA(); show('A 端 CurseForge 密钥已清空。'); }); };
document.querySelector('#save-host').onclick = function () {
  action(this, async () => {
    if (!host) throw new Error('请先刷新 B 配置。');
    const data = {};
    const memory = Number(document.querySelector('#operations-memory').value);
    const powerShell = document.querySelector('#powershell-path').value;
    const java = document.querySelector('#world-java').value;
    if (memory !== (host.operations_memory_limit_mib ?? 8192)) data.operations_memory_limit_mib = memory;
    if (powerShell !== host.powershell_path) data.powershell_path = powerShell;
    if (java !== (host.world_tools.java_path ?? '')) data.world_tools = { java_path: java };
    if (!Object.keys(data).length) { show('主机设置没有改动。'); return; }
    const result = await api('POST', 'host', data);
    Object.assign(host, data);
    show(result.restart_required
      ? '主机设置已保存。PowerShell、存档 Java 或内存额度需重启 B 后生效。'
      : '主机设置已保存并生效。');
  });
};
function showIncidentSettings(data, loadValues = true) {
  if (loadValues) {
    restartWindow.value = data.incident_restart_window_seconds;
    incidentCapacity.value = data.incident_capacity_mib;
  }
  incidentForm.querySelector('[type=submit]').disabled = false;
  const active = data.effective.incident_capacity_mib;
  const pending = active === data.incident_capacity_mib ? '' : `；已保存 ${data.incident_capacity_mib} MiB，尚未生效`;
  document.querySelector('#incident-usage').textContent =
    `留证数据库已用 ${(data.incident_db_bytes / 1048576).toFixed(2)} / ${active} MiB${pending}`;
}
incidentForm.addEventListener('submit', event => {
  event.preventDefault();
  action(event.submitter, async () => {
    const result = await api('POST', 'host', {
      incident_restart_window_seconds: Number(restartWindow.value || restartWindow.placeholder),
      incident_capacity_mib: Number(incidentCapacity.value || incidentCapacity.placeholder),
    });
    if (result.application_error) {
      show(`留证容量 ${result.incident_capacity_mib} MiB 已保存，当前仍为 ${result.effective.incident_capacity_mib} MiB。处理错误后重新保存：${result.application_error}`, true);
      return;
    }
    showIncidentSettings(await api('GET', 'host'));
    show('主动留证设置已保存并生效。');
  });
});
document.querySelector('#refresh-incident-usage').onclick = function () {
  action(this, async () => showIncidentSettings(await api('GET', 'host'), !host));
};
const names = { conversation: '普通对话', image: '图片识别', stream: '流式响应', function_call: '工具调用与续接', reasoning_effort: '排障思考强度', web_search: 'API 托管搜索', web_search_preview: '兼容托管搜索', alpha_search: '独立搜索', alpha_open: '独立搜索打开网页', alpha_find: '独立搜索页内查找', progress: '执行进度汇报', review_json: '审核模型与 JSON' };
const statuses = { testing: '测试中', passed: '验证通过', unsupported: '明确不支持', unobserved: '本次未观察到', failed: '请求失败' };
async function readTest() {
  const data = await api('GET', 'capabilities'), container = document.querySelector('#capabilities'); container.replaceChildren();
  if (data.stale) { const p = document.createElement('p'); p.textContent = '模型配置已变化，需要重新测试。'; container.append(p); }
  for (const [name, item] of Object.entries(data.result?.items ?? {})) { const row = document.createElement('div'); row.className = 'capability'; row.textContent = `${names[name] ?? name}：${statuses[item.status] ?? item.status}${item.error ? '\n' + item.error : ''}`; container.append(row); }
  if (data.result?.error) show(data.result.error, true);
  if (!data.running) { clearInterval(poll); poll = null; if (data.result?.complete) await loadA(); }
  return data;
}
function startPolling() { if (!poll) poll = setInterval(() => readTest().catch(error => { clearInterval(poll); poll = null; show(error.message, true); }), 1000); }
document.querySelector('#test-model').onclick = function () { action(this, async () => { await saveA(); await api('POST', 'capabilities'); show('正在测试模型能力，结果将逐项显示。'); startPolling(); }); };
document.querySelector('#cancel-test').onclick = function () { action(this, async () => { await api('POST', 'capabilities/cancel'); await readTest(); show('能力测试已取消。'); }); };
const ruleLabels = { latest: '已是最新', unmodified: '有新模板（用户未修改）', modified: '有新模板（用户已修改）', unknown: '基线未知' };
const adoptRuleDialog = document.querySelector('#adopt-rule-dialog');
async function loadRules() {
  const rules = await api('GET', 'rules'), container = document.querySelector('#rule-list');
  container.replaceChildren();
  for (const [name, rule] of Object.entries(rules)) {
    const card = document.createElement('article'); card.className = 'rule-card';
    const heading = document.createElement('strong'); heading.textContent = `${name}：${ruleLabels[rule.status]}`;
    const buttons = document.createElement('div'); buttons.className = 'actions';
    const diff = document.createElement('button'), adopt = document.createElement('button'), merged = document.createElement('button');
    for (const button of [diff, adopt, merged]) button.type = 'button';
    diff.className = merged.className = 'secondary';
    diff.textContent = '查看差异'; adopt.textContent = '采用新模板'; merged.textContent = '已人工合并';
    adopt.disabled = merged.disabled = !rule.update_available;
    const preview = document.createElement('pre'); preview.className = 'rule-diff'; preview.hidden = true;
    diff.onclick = () => action(diff, async () => {
      if (preview.hidden) {
        const result = await api('POST', 'rules', { name, action: 'diff' });
        preview.textContent = result.diff || '当前文件与打包模板没有文本差异。';
      }
      preview.hidden = !preview.hidden;
      diff.textContent = preview.hidden ? '查看差异' : '收起差异';
    });
    const update = (button, choice) => action(button, async () => {
      const result = await api('POST', 'rules', {
        name, action: choice, template_sha256: rule.template_sha256, file_sha256: rule.file_sha256,
      });
      await loadRules();
      show(choice === 'adopt' ? `${name} 已采用新模板，备份：${result.backup}` : `${name} 的基线已更新，规则文件未改动。`);
    });
    merged.onclick = () => update(merged, 'merged');
    adopt.onclick = () => {
      document.querySelector('#adopt-rule-message').textContent = `将先在同一目录备份 ${name}，再用新模板覆盖原文件。是否继续？`;
      adoptRuleDialog.returnValue = '';
      adoptRuleDialog.addEventListener('close', () => {
        if (adoptRuleDialog.returnValue === 'adopt') update(adopt, 'adopt');
      }, { once: true });
      adoptRuleDialog.showModal();
    };
    buttons.append(diff, adopt, merged);
    card.append(heading, buttons, preview);
    container.append(card);
  }
}
async function loadDiagnostics() {
  const data = await api('GET', 'diagnostics'), select = document.querySelector('#diagnostics-tasks');
  const { pending, latest_error, items } = data.outbox;
  document.querySelector('#outbox-status').textContent = `尚未送达：${pending} 条${latest_error ? `；最近错误：${latest_error}` : ''}`;
  const outbox = document.querySelector('#outbox-list');
  const dialog = document.querySelector('#discard-outbox-dialog');
  const table = storageTable('未送达的群消息', ['任务', '目标群', '正文首行', '尝试次数', '最近错误', '下次重试', '单条故障', '操作'], items.map(item => [
    item.task_name, item.origin.split(':').at(-1), item.first_line, item.attempts, item.error ?? '—',
    item.failed ? '已停用' : item.retry_at ? new Date(item.retry_at * 1000).toLocaleString() : '等待发送',
    item.single_fault ? '是' : '否', '',
  ]));
  const rows = table.querySelector('tbody').rows;
  for (const [index, item] of items.entries()) {
    const retry = document.createElement('button'), discard = document.createElement('button');
    retry.type = discard.type = 'button';
    retry.className = discard.className = 'secondary';
    retry.textContent = '立即重试';
    discard.textContent = '丢弃';
    retry.onclick = () => action(retry, async () => {
      await api('POST', 'diagnostics/outbox', { id: item.id, action: 'retry' });
      await loadDiagnostics();
      show('消息已安排重试。');
    });
    discard.onclick = () => {
      document.querySelector('#discard-outbox-message').textContent = `丢弃「${item.task_name}」发往群 ${item.origin.split(':').at(-1)} 的这条消息？`;
      dialog.returnValue = '';
      dialog.addEventListener('close', () => {
        if (dialog.returnValue !== 'discard') return;
        action(discard, async () => {
          await api('POST', 'diagnostics/outbox', { id: item.id, action: 'discard', confirm: true });
          await loadDiagnostics();
          show('消息已丢弃。');
        });
      }, { once: true });
      dialog.showModal();
    };
    rows[index].cells[7].append(retry, discard);
  }
  outbox.replaceChildren(table);
  select.replaceChildren();
  for (const task of data.tasks) select.add(new Option(`${task.name} · 群 ${task.group} · ${task.state}`, task.id));
  for (const question of data.questions) select.add(new Option(`只读问答：${question.name} · 群 ${question.group}`, question.id));
}
const storageLabels = {
  traces: '任务留痕', audit: 'audit.jsonl', state: 'state.sqlite3（含 WAL）', knowledge: '经验',
  workspaces: '工作区', downloads: '下载', exports: '导出', backups: '备份', jobs: '后台结果',
  incidents: 'incidents.sqlite3（含 WAL）', execution_log: 'execution.log', test_servers: '试服目录',
};
const storageStates = {
  running: '运行中', waiting: '等待', applying: '修复中', paused: '已暂停', done: '已验收', stopped: '已停止',
  pending: '排队中', completed: '已完成', failed: '失败', interrupted: '中断', cancelled: '已取消',
};
function diskSize(bytes) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return `${bytes.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${units[i]}`;
}
function storageTable(title, columns, rows) {
  const block = document.createElement('div'); block.className = 'storage-table';
  const table = document.createElement('table'); block.append(table);
  table.createCaption().textContent = title;
  const header = table.createTHead().insertRow();
  for (const column of columns) {
    const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = column;
    header.append(cell);
  }
  const body = table.createTBody();
  for (const values of rows.length ? rows : [['暂无记录']]) {
    const row = body.insertRow();
    for (const value of values) row.insertCell().textContent = value;
    if (!rows.length) row.cells[0].colSpan = columns.length;
  }
  return block;
}
async function loadStorage(side, endpoint) {
  const report = document.querySelector(`#storage-${side}`);
  report.textContent = '正在统计…';
  try {
    const data = await api('GET', endpoint);
    const localTime = value => new Date(value * 1000).toLocaleString();
    const stamp = document.createElement('p'); stamp.className = 'hint';
    stamp.textContent = `统计时间：${localTime(data.scanned_at)}`;
    if (side === 'b') stamp.textContent += `；B 数据盘剩余 ${diskSize(data.disk_free_bytes)}`;
    else stamp.textContent += `；当前审计日志已统计 ${data.categories.audit.lines} 行，任务留痕 ${data.categories.traces.tasks} 个任务`;
    stamp.textContent += `；状态数据库可回收 ${diskSize(data.categories.state.reclaimable_bytes)}`;
    report.replaceChildren(stamp, storageTable('文件占用', ['类别', '大小', '文件数', '范围'], Object.entries(data.categories).map(
      ([key, item]) => [storageLabels[key], diskSize(item.bytes), item.files, item.complete ? '完整' : '部分'],
    )));
    const state = key => storageStates[key] ?? key ?? '未知';
    if (side === 'a') {
      report.append(storageTable('占用最大的任务留痕（最多 10 个）', ['任务', '状态', '大小'], data.largest_traces.map(
        row => [row.name ?? row.task_id, state(row.state), diskSize(row.bytes)],
      )));
      report.append(storageTable(`数据库记录正文${data.records_complete ? '' : '（部分）'}`, ['类别', '记录数', '正文大小'], data.record_kinds.map(
        row => [row.kind, row.count, diskSize(row.bytes)],
      )));
    } else {
      if (data.scheduled_backups) {
        const { path, usage } = data.scheduled_backups;
        report.append(storageTable('另盘定时备份', ['目录', '大小', '文件数', '范围'], [[
          path, usage && (usage.complete || usage.files) ? diskSize(usage.bytes) : '—',
          usage && (usage.complete || usage.files) ? usage.files : '—',
          usage?.complete ? '完整' : '未能完整统计；另盘目录需单独监控',
        ]]));
      }
      report.append(storageTable(`备份${data.backup_metadata_complete ? '' : '（部分元数据）'}`, ['操作编号', '时间', '实例', '任务编号', 'B 所见状态', '大小'], data.backups.map(
        row => [row.operation_id, localTime(row.time), row.instance ?? '未知', row.task_id ?? '未知', state(row.task_status), diskSize(row.bytes) + (row.complete ? '' : '（部分）')],
      )));
    }
  } catch (error) {
    report.textContent = `读取失败：${error.message}`;
  }
}
async function loadModelUsage() {
  const { daily, tasks } = await api('GET', 'model/usage');
  const costs = [...daily, ...tasks].some(row => row.cost.length);
  const columns = ['请求', '输入 token', '输出 token', '缓存命中 token', '未返回用量', ...(costs ? ['估算费用'] : [])];
  const cells = row => [
    row.requests, row.input_tokens, row.output_tokens,
    `${row.cached_tokens}${row.cache_missing ? `（${row.cache_missing} 次未提供）` : ''}`,
    row.no_usage, ...(costs ? [row.cost.join('、') || '—'] : []),
  ];
  document.querySelector('#model-usage').replaceChildren(
    storageTable('最近 30 天', ['日期', '提供商', '模型', ...columns], daily.map(row => [row.date, row.provider, row.model, ...cells(row)])),
    storageTable('用量最高的 10 个任务', ['任务', '群', '审核请求', ...columns], tasks.map(row => [row.name, row.group, row.review_requests, ...cells(row)])),
  );
}
document.querySelector('#refresh-model-usage').onclick = function () { action(this, loadModelUsage); };
document.querySelector('#refresh-storage').onclick = function () {
  action(this, () => Promise.all([loadStorage('a', 'storage'), loadStorage('b', 'storage/host')]));
};
for (const button of document.querySelectorAll('[data-vacuum]')) {
  button.onclick = () => action(button, async () => {
    const side = button.dataset.vacuum;
    const result = await api('POST', 'storage/vacuum', { side });
    show(`${side.toUpperCase()} 数据库压缩完成：${diskSize(result.before.bytes)} → ${diskSize(result.after.bytes)}`);
    await loadStorage(side, side === 'a' ? 'storage' : 'storage/host');
  });
}
const logsSide = document.querySelector('#logs-side'), logsMonth = document.querySelector('#logs-month');
const logsOpen = document.querySelector('#open-logs'), logsDialog = document.querySelector('#logs-dialog');
async function loadLogs() {
  logsOpen.disabled = true;
  const side = logsSide.value;
  const { archives } = await api('GET', `storage/logs?side=${side}`);
  if (side !== logsSide.value) return;
  document.querySelector('#log-archives').replaceChildren(storageTable('已轮转日志', ['月份', '文件', '大小'],
    archives.map(item => [item.month, item.path, diskSize(item.bytes)])));
  logsMonth.replaceChildren(...Array.from(new Set(archives.map(item => item.month))).sort().reverse().map(month => new Option(month, month)));
  logsOpen.disabled = !logsMonth.value;
}
document.querySelector('#refresh-logs').onclick = function () { action(this, loadLogs); };
logsSide.onchange = () => {
  logsOpen.disabled = true;
  logsMonth.replaceChildren();
  document.querySelector('#log-archives').replaceChildren();
};
logsOpen.onclick = () => {
  const side = logsSide.value, month = logsMonth.value;
  document.querySelector('#logs-confirm').textContent = `永久删除 ${side.toUpperCase()} 端 ${month} 月的压缩日志？删除后诊断导出无法读到这些记录。`;
  logsDialog.returnValue = '';
  logsDialog.addEventListener('close', async () => {
    if (logsDialog.returnValue !== 'delete') return;
    await action(logsOpen, async () => {
      const result = await api('POST', 'storage/logs', { side, month, confirm: true });
      show(`已删除 ${result.paths.length} 个归档，释放 ${diskSize(result.bytes)}。`);
      await loadLogs();
    });
    logsOpen.disabled = !logsMonth.value;
  }, { once: true });
  logsDialog.showModal();
};
const cleanupSelection = document.querySelector('#cleanup-selection'), cleanupTask = document.querySelector('#cleanup-task');
const cleanupMode = document.querySelector('#cleanup-mode'), cleanupDays = document.querySelector('#cleanup-days');
const cleanupResult = document.querySelector('#cleanup-result'), cleanupPreview = document.querySelector('#cleanup-preview');
const openCleanup = document.querySelector('#open-cleanup'), cleanupDialog = document.querySelector('#cleanup-dialog');
const backupConfirm = document.querySelector('#confirm-cleanup-backups');
const cleanupPath = 'storage/cleanup';
let cleanupPlan = null;
function resetCleanup(message = '') {
  cleanupPlan = null;
  openCleanup.disabled = true;
  cleanupPreview.replaceChildren();
  cleanupResult.textContent = message;
}
function cleanupScope() {
  const target = cleanupMode.value === 'batch' ? { days: Number(cleanupDays.value) } : { task_id: cleanupTask.value };
  return { ...target, categories: Array.from(cleanupSelection.querySelectorAll('input[type=checkbox]:checked')).map(item => item.value) };
}
cleanupSelection.addEventListener('change', () => {
  const batch = cleanupMode.value === 'batch';
  document.querySelector('#cleanup-task-label').hidden = batch;
  document.querySelector('#cleanup-days-label').hidden = !batch;
  document.querySelector('#refresh-cleanup').hidden = batch;
  resetCleanup();
});
const cleanupLabels = { ...storageLabels, web_page: '网页记录', workspace: '工作区', outbox: '发件记录' };
function skippedTasks(title, rows) {
  return storageTable(title, ['任务', '原因'], rows.map(row => [row.name, row.reason]));
}
document.querySelector('#refresh-cleanup').onclick = function () {
  action(this, async () => {
    resetCleanup();
    const data = await api('GET', cleanupPath);
    cleanupTask.replaceChildren(new Option(data.tasks.length ? '选择任务' : '没有已结算任务', ''));
    for (const task of data.tasks) {
      cleanupTask.add(new Option(`${task.name} · 群 ${task.group} · ${storageStates[task.state]} · ${task.id}`, task.id));
    }
  });
};
document.querySelector('#preview-cleanup').onclick = function () {
  action(this, async () => {
    resetCleanup();
    const scope = cleanupScope();
    try {
      const preview = await api('POST', cleanupPath, { ...scope, action: 'preview' });
      if (JSON.stringify(scope) !== JSON.stringify(cleanupScope())) return;
      if ('days' in scope) {
        cleanupPreview.append(storageTable('待清理任务', ['任务', '结算时间', '各类别大小'], preview.tasks.map(row =>
          [row.name, new Date(row.settled_at * 1000).toLocaleString(), Object.entries(row.categories).map(([kind, bytes]) => {
            const records = row.records[kind];
            return `${cleanupLabels[kind]} ${diskSize(bytes)}${records ? `（记录 ${records.count} 条 · ${diskSize(records.bytes)}）` : ''}`;
          }).join('；')])));
        if (preview.skipped.length) cleanupPreview.append(skippedTasks('跳过的任务', preview.skipped));
        if (preview.tasks.length) {
          cleanupPlan = { ...scope, token: preview.token };
          openCleanup.disabled = false;
        }
        return;
      }
      const rows = [...preview.a.map(item => ['A', item]), ...preview.b.map(item => ['B', item])];
      cleanupPreview.append(storageTable('待删除数据', ['位置', '类别', '路径或记录', '操作编号', '实例', '总大小', '数据库记录'], rows.map(
        ([side, item]) => [side, cleanupLabels[item.kind], item.path, item.operation_id ?? '—', item.instance ?? '—', diskSize(item.bytes), item.records ? `${item.records} 条 · ${diskSize(item.record_bytes)}` : '—'],
      )));
      if (rows.length) {
        cleanupPlan = { ...scope, token: preview.token };
        openCleanup.disabled = false;
      }
    } catch (error) { resetCleanup(error.message); }
  });
};
openCleanup.onclick = () => {
  backupConfirm.checked = false;
  backupConfirm.required = cleanupPlan.categories.includes('backups');
  document.querySelector('#cleanup-backup-warning').hidden = !backupConfirm.required;
  cleanupDialog.returnValue = '';
  cleanupDialog.showModal();
};
cleanupDialog.addEventListener('close', async () => {
  if (cleanupDialog.returnValue !== 'execute' || !cleanupPlan) return;
  const body = { ...cleanupPlan, action: 'execute', confirm_backups: backupConfirm.checked };
  resetCleanup('正在清理，请等待结果…');
  const controls = [...cleanupSelection.querySelectorAll('input, select'), document.querySelector('#refresh-cleanup'), document.querySelector('#preview-cleanup')];
  controls.forEach(control => { control.disabled = true; });
  try {
    const result = await api('POST', cleanupPath, body);
    if ('days' in body) {
      const bytes = result.completed.reduce((sum, row) => sum + row.bytes, 0);
      cleanupResult.textContent = `完成 ${result.completed.length} 个任务，移除 ${diskSize(bytes)}；跳过 ${result.skipped.length} 个，失败 ${result.failed.length} 个。`;
      if (result.skipped.length) cleanupPreview.append(skippedTasks('跳过的任务', result.skipped));
      if (result.failed.length) cleanupPreview.append(skippedTasks('未完成，请重新预览', result.failed));
      return;
    }
    const size = result.a.bytes + result.b.reduce((sum, item) => sum + item.bytes, 0);
    cleanupResult.textContent = `清理完成：${diskSize(size)}。${result.a.archive ? `归档：${result.a.archive}` : ''}`;
  } catch (error) { cleanupResult.textContent = error.message; }
  finally { controls.forEach(control => { control.disabled = false; }); }
});
document.querySelector('#refresh-diagnostics').onclick = function () { action(this, loadDiagnostics); };
document.querySelector('#export-diagnostics').onclick = function () {
  action(this, async () => {
    const start = document.querySelector('#diagnostics-start').value, end = document.querySelector('#diagnostics-end').value;
    const result = await api('POST', 'diagnostics', { start: start ? new Date(start).getTime() / 1000 : 0, end: end ? new Date(end).getTime() / 1000 : null, task_ids: Array.from(document.querySelector('#diagnostics-tasks').selectedOptions, option => option.value) });
    const reordered = result.reordered_files?.length ? `。以下日志时间倒序，已在临时副本中排序：${result.reordered_files.join('、')}` : '';
    document.querySelector('#diagnostics-result').textContent = `已保存 ${result.entries} 条事件：${result.path}${reordered}`;
    await bridge.download('diagnostics/file', { filename: result.filename }, result.filename);
  });
};
try { await loadA(); const test = await readTest(); if (test.running) startPolling(); await loadRules(); await loadDiagnostics(); await loadModelUsage(); await loadHost(); } catch (error) { show(`读取失败：${error.message}`, true); }
