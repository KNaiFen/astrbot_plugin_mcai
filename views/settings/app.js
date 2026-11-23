import { createManagement, pendingConfiguration, usageColumns, usageTableCells } from './management.js';
import { styleSettings, button, node, setupEditors } from './controls.js';

const bridge = window.AstrBotPluginView;
function applyTheme(context = {}) {
  const query = new URLSearchParams(location.search).get('theme');
  document.documentElement.dataset.theme = (context.isDark ?? (query === 'dark')) ? 'dark' : 'light';
}
applyTheme();
await bridge.ready();
bridge.onContext(applyTheme);
const form = document.querySelector('#a-settings'), notice = document.querySelector('#notice');
const restartWindow = document.querySelector('#incident-restart-window');
const incidentCapacity = document.querySelector('#incident-capacity');
const incidentForm = document.querySelector('#incident-settings');
const sections = document.querySelectorAll('.settings-nav a');
function markSection() {
  const current = Array.from(sections).find(link => link.hash === (location.hash || '#servers')) ?? sections[0];
  for (const link of sections) {
    if (link === current) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
    document.querySelector(link.hash).hidden = link !== current;
  }
}
markSection();
window.addEventListener('hashchange', () => { markSection(); window.scrollTo(0, 0); });
let host = null, poll = null;
let catalog, readPriceBindings;
function show(text, error = false) {
  const dialogError = document.querySelector('#management-dialog-error');
  if (error && dialogError.closest('dialog').open) { dialogError.hidden = false; dialogError.textContent = text; return; }
  notice.textContent = text; notice.classList.toggle('error', error);
}
async function api(method, path, data) {
  const response = method === 'GET' ? await bridge.apiGet(path, data) : await bridge.apiPost(path, data ?? {});
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
  if (readPriceBindings) result.model_price_meta = readPriceBindings();
  return result;
}
function showCatalog(data) {
  catalog = data;
  document.querySelector('#model-price-status').textContent = catalog
    ? `上次同步：${new Date(catalog.updated_at * 1000).toLocaleString()} · ${catalog.count.toLocaleString()} 个模型 · ${catalog.source}`
    : '尚未同步上游价格，可手动填写单价。';
}
function pickPrice(model, apply) {
  const search = node('input');
  search.type = 'search';
  search.setAttribute('aria-label', '搜索上游模型');
  search.placeholder = '模型 ID、名称或上游提供商';
  const entries = catalog?.models || [];
  search.value = model && entries.some(entry => entry.model.toLowerCase().includes(model.toLowerCase())) ? model : '';
  const results = node('div', null, 'data-list');
  function render() {
    const keywords = search.value.toLowerCase().trim().split(/\s+/);
    const rows = entries.filter(entry => {
      const text = `${entry.model} ${entry.name} ${entry.provider} ${entry.provider_name}`.toLowerCase();
      return keywords.every(word => text.includes(word));
    });
    results.replaceChildren(node('p', entries.length ? `找到 ${rows.length} 个模型${rows.length > 50 ? '，显示前 50 个。' : '。'}` : '先同步上游模型价格，再搜索选用。', 'hint'));
    for (const row of rows.slice(0, 50)) {
      const control = button(`${row.name} · ${row.model} · ${row.provider_name} · USD ${row.input} / ${row.output} / ${row.cache}`, () => {
        apply(row);
        control.closest('dialog').close();
      });
      results.append(control);
    }
  }
  search.oninput = render;
  render();
  management.modal('选择上游模型', search, results);
  search.focus();
}
async function loadA() {
  const [data, prices] = await Promise.all([api('GET', 'settings'), api('GET', 'model/catalog')]);
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
  showCatalog(prices.catalog);
  readPriceBindings = setupEditors(form, { ...data, bindings: prices.bindings }, () => hostApi('servers'),
    { pick: pickPrice, models: () => catalog?.models || [] });
}
async function saveA() { await api('POST', 'settings', values()); }
form.addEventListener('submit', event => { event.preventDefault(); action(event.submitter, async () => {
  await saveA();
  show('A 配置已保存并生效。');
  await loadModelUsage();
}); });
document.querySelector('#connection-test').onclick = function () { action(this, async () => { const result = await api('POST', 'connection/test', values()); show(`连接成功，B 配置了 ${result.instances} 个服务端。`); }); };
function field(container, label, value, key, placeholder = '') {
  const wrapper = document.createElement('label'); wrapper.append(document.createTextNode(label));
  const input = document.createElement('input'); input.type = key === 'stop_timeout' ? 'number' : 'text';
  if (key === 'stop_timeout') input.min = '1';
  if (placeholder) input.placeholder = placeholder;
  input.value = value ?? ''; input.dataset.key = key; wrapper.append(input); container.append(wrapper); return input;
}
const instanceAlerts = {
  alert_window: ['托管窗口掉线告警', true],
  alert_window_minutes: ['窗口连续掉线分钟数', 3],
  alert_disk: ['磁盘空间告警', true],
  alert_disk_gib: ['磁盘剩余阈值（GiB）', 10],
  alert_performance: ['Probe 性能告警', false],
  alert_mspt: ['瓶颈 MSPT 阈值（毫秒）', 50],
  alert_performance_minutes: ['性能持续偏低分钟数', 3],
};
const newInstanceDefaults = {
  stop_timeout: 180,
  incident_watch: true,
  alert_window: false,
  alert_window_minutes: 3,
  alert_disk: false,
  alert_disk_gib: 10,
  alert_performance: false,
  alert_mspt: 66,
  alert_performance_minutes: 3,
};
function instance(name = '', config = {}, state = {}) {
  const isNew = !name;
  const effective = isNew ? { ...newInstanceDefaults, ...config } : config;
  const card = document.createElement('article'); card.className = 'instance';
  if (isNew) card.dataset.isNew = '1';
  const heading = document.createElement('header'), identity = document.createElement('div');
  heading.className = 'instance-heading'; identity.className = 'instance-identity';
  const title = node('strong', name || '新服务端', 'instance-title'), status = document.createElement('span'), remove = document.createElement('button');
  status.className = 'instance-state';
  status.textContent = isNew ? '未保存' : state.state_unknown ? '状态待确认' : state.running ? '运行中' : '已停服';
  if (!isNew && !state.window_online) status.textContent += ' · 无托管连接';
  if (state.configuration_pending) status.textContent += ` · ${pendingConfiguration(state)}`;
  if (state.selectable === false) status.textContent += ' · 待移除';
  status.classList.toggle('running', !!state.running && !state.state_unknown);
  remove.type = 'button'; remove.className = 'quiet'; remove.textContent = '移除配置'; remove.onclick = () => card.remove();
  identity.append(title, status); heading.append(identity, remove); card.append(heading);
  const instanceBody = node('div', null, 'instance-body');
  const basics = node('div', null, 'setting-group');
  field(basics, '配置名', name, 'name', '英文或简短标识，如 cti');
  field(basics, '说明／群内叫法', effective.description, 'description', '如 主城生存服');
  field(basics, '服务端目录（其中使用 start.bat）', effective.directory, 'directory', 'B 主机上的绝对路径');
  instanceBody.append(basics);
  const advanced = node('details', null, 'instance-advanced'), summary = document.createElement('summary');
  const body = node('div', null, 'advanced-body');
  summary.textContent = '高级选项';
  advanced.append(summary, body);
  body.append(node('h4', '启动与停服', 'group-title'));
  const startupGroup = node('div', null, 'setting-group');
  for (const [key, label, placeholder] of [
    ['java_path', '实例 Java 路径（可选）', '留空继承系统环境'],
    ['encoding', 'BAT 编码（默认 auto）', 'auto'],
    ['stop_timeout', '停服超时秒（留空默认 120）', '120'],
    ['stop_command', 'MC 停服命令（默认 stop）', 'stop'],
    ['restart_prompt', '自动重启提示（默认约定提示）', '留空使用默认提示'],
  ]) field(startupGroup, label, effective[key], key, placeholder);
  body.append(startupGroup);
  body.append(node('h4', '试服与故障留证', 'group-title'));
  const trialGroup = node('div', null, 'setting-group');
  const paths = document.createElement('label'); paths.append('试服复制清单（每行一个相对路径）');
  const list = document.createElement('textarea'); list.dataset.key = 'test_copy_paths'; list.value = (effective.test_copy_paths ?? []).join('\n'); paths.append(list);
  const watch = document.createElement('label'); watch.className = 'toggle';
  const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.dataset.key = 'incident_watch'; toggle.checked = effective.incident_watch ?? false; watch.append(toggle, '主动保留故障现场');
  trialGroup.append(paths, watch);
  body.append(trialGroup);
  body.append(node('h4', '健康告警', 'group-title'));
  const alerts = node('div', null, 'setting-group');
  for (const [key, [label, initial]] of Object.entries(instanceAlerts)) {
    const current = effective[key] ?? initial;
    const input = field(alerts, label, current, key);
    if (typeof initial === 'boolean') {
      input.type = 'checkbox'; input.checked = current;
      input.parentElement.className = 'toggle'; input.parentElement.prepend(input);
    } else {
      input.type = 'number'; input.step = 'any';
    }
  }
  body.append(alerts);
  instanceBody.append(advanced);
  card.append(instanceBody);
  styleSettings(card);
  setupEditors(card);
  document.querySelector('#instances').append(card);
}
async function loadHost() {
  host = await api('GET', 'host'); document.querySelector('#instances').replaceChildren();
  for (const [name, config] of Object.entries(host.instances)) instance(name, config, host.state.find(item => item.instance === name));
  for (const state of host.state.filter(item => item.selectable === false)) { const p = node('p', `${state.instance}：待移除，当前进程与操作仍可管理。`, 'hint'); document.querySelector('#instances').append(p); }
  document.querySelector('#powershell-path').value = host.powershell_path; document.querySelector('#world-java').value = host.world_tools.java_path ?? ''; document.querySelector('#operations-memory').value = host.operations_memory_limit_mib ?? 8192; document.querySelector('#scheduled-backup-dir').value = host.scheduled_backup_dir ?? ''; document.querySelector('#host-workspace-dir').value = host.workspace_dir ?? ''; document.querySelector('#download-max-bytes').value = host.download_max_bytes;
  document.querySelector('#host-test-address').value = host.test_address ?? '';
  document.querySelector('#host-test-port').value = host.test_port ?? '';
  const legacy = document.querySelector('#legacy-test-fields');
  legacy.hidden = !host.legacy_test_fields?.length;
  legacy.textContent = legacy.hidden ? '' : `${host.legacy_test_fields.join('、')} 的旧试服地址和端口已忽略。请在「B 主机」设置全局地址和端口；保存服务端列表时会移除旧字段。`;
  updateDownloadHint();
  document.querySelector('#effective-storage-paths').textContent = `当前 B 使用：备份 ${host.effective.scheduled_backup_dir}；试服 ${host.effective.workspace_dir}；单文件 ${diskSize(host.effective.download_max_bytes)}。`;
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
        if (!key) continue;
        if (key === 'name') name = input.value.trim();
        else if (key === 'incident_watch') { if (input.checked) config[key] = true; }
        else if (key in instanceAlerts) config[key] = input.type === 'checkbox' ? input.checked : Number(input.value || (card.dataset.isNew && key in newInstanceDefaults ? newInstanceDefaults[key] : instanceAlerts[key][1]));
        else if (key === 'test_copy_paths') { if (input.value.trim()) config[key] = input.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean); }
        else if (input.value.trim()) config[key] = input.type === 'number' ? Number(input.value) : input.value;
      }
      if (!name || instances[name]) throw new Error('配置名不能为空或重复。'); instances[name] = config;
    }
    await api('POST', 'host', { instances, revision: host.revision }); await loadHost(); show('服务端配置已保存。待生效的字段会在实例卡片标出。');
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
    const backupDir = document.querySelector('#scheduled-backup-dir').value;
    const workspaceDir = document.querySelector('#host-workspace-dir').value;
    const downloadMax = Number(document.querySelector('#download-max-bytes').value);
    const address = document.querySelector('#host-test-address').value.trim();
    const port = document.querySelector('#host-test-port').value;
    if (address !== (host.test_address ?? '')) data.test_address = address;
    if ((port ? Number(port) : null) !== (host.test_port ?? null)) data.test_port = port ? Number(port) : null;
    if (!Number.isSafeInteger(downloadMax) || downloadMax <= 0) throw new Error('单文件下载上限须为正整数（字节）。');
    if (memory !== (host.operations_memory_limit_mib ?? 8192)) data.operations_memory_limit_mib = memory;
    if (powerShell !== host.powershell_path) data.powershell_path = powerShell;
    if (java !== (host.world_tools.java_path ?? '')) data.world_tools = { java_path: java };
    if (backupDir !== (host.scheduled_backup_dir ?? '')) data.scheduled_backup_dir = backupDir;
    if (workspaceDir !== (host.workspace_dir ?? '')) data.workspace_dir = workspaceDir;
    if (downloadMax !== (host.download_max_bytes ?? 2 * 1024 ** 3)) data.download_max_bytes = downloadMax;
    if (!Object.keys(data).length) { show('主机设置没有改动。'); return; }
    const result = await api('POST', 'host', data);
    await loadHost();
    show(result.restart_required
      ? '主机设置已保存，重启 B 后生效。'
      : '主机设置已保存并生效。');
  });
};
function updateDownloadHint() {
  const bytes = Number(document.querySelector('#download-max-bytes').value);
  document.querySelector('#download-size-hint').textContent = bytes > 0 ? `约 ${diskSize(bytes)}。1 MiB = 1,048,576 字节。` : '';
}
document.querySelector('#download-max-bytes').addEventListener('input', updateDownloadHint);
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
  for (const [name, item] of Object.entries(data.result?.items ?? {})) {
    const row = document.createElement('details'); row.className = 'capability';
    const summary = document.createElement('summary'); summary.textContent = `${names[name] ?? name}：${statuses[item.status] ?? item.status}`;
    const detail = document.createElement('p'); detail.textContent = item.error || '本项由保存的模型配置发起。';
    const retry = button('单项重测', () => action(retry, async () => { await api('POST', 'capabilities', { only: name }); show(`正在重测${names[name] ?? name}。`); startPolling(); }));
    retry.disabled = data.running;
    row.append(summary, detail, retry); container.append(row);
  }
  if (data.result?.error) show(data.result.error, true);
  if (!data.running && poll) { clearInterval(poll); poll = null; if (data.result?.complete && Object.keys(data.result.applied ?? {}).length) await loadA(); }
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
    const rowActions = node('div', null, 'data-actions');
    rowActions.append(retry, discard);
    rows[index].cells[7].append(rowActions);
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
  if (title) table.createCaption().textContent = title;
  const header = table.createTHead().insertRow();
  for (const column of columns) {
    const cell = document.createElement('th'); cell.scope = 'col';
    if (typeof column === 'object' && column !== null) {
      cell.textContent = column.text;
      if (column.cls) cell.className = column.cls;
    } else cell.textContent = column;
    header.append(cell);
  }
  const body = table.createTBody();
  for (const values of rows.length ? rows : [['暂无记录']]) {
    const row = body.insertRow();
    for (const item of values) {
      const cell = row.insertCell();
      const shaped = item && typeof item === 'object' && !(item instanceof Node);
      const value = shaped ? item.value : item;
      if (shaped && item.cls) cell.className = item.cls;
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value;
    }
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
  const { daily, tasks, daily_summary, non_task_summary } = await api('GET', 'model/usage');
  const container = document.querySelector('#model-usage');
  const search = node('input'); search.type = 'search'; search.placeholder = '按任务、编号、群或状态搜索';
  search.setAttribute('aria-label', '筛选模型用量任务');
  const scope = node('select'); scope.add(new Option('全部任务', 'all')); scope.add(new Option('前 10', 'top'));
  scope.setAttribute('aria-label', '任务展示范围');
  search.value = container.querySelector('input')?.value || '';
  scope.value = container.querySelector('select')?.value || 'top';
  const taskSection = node('div', null, 'usage-tasks');
  const usageHeadings = usageColumns.map((text, idx) => ({ text, cls: idx === 5 ? 'num nowrap' : 'num' }));
  const render = () => {
    const query = search.value.trim().toLowerCase();
    const match = tasks.filter(row => `${row.name} ${row.id} ${row.group} ${row.state}`.toLowerCase().includes(query));
    const table = storageTable('', [
      '任务',
      { text: '群', cls: 'nowrap num' },
      { text: '状态', cls: 'nowrap' },
      { text: '请求', cls: 'num' },
      { text: '审核', cls: 'num' },
      ...usageHeadings.slice(1),
      { text: '操作', cls: 'nowrap' },
    ], (scope.value === 'top' ? match.slice(0, 10) : match).map(row => [
      { value: row.name, cls: 'task-cell strong-cell' },
      { value: row.group, cls: 'nowrap num' },
      { value: node('span', storageStates[row.state] ?? row.state, 'badge'), cls: 'nowrap' },
      { value: row.requests.toLocaleString(), cls: 'num' },
      { value: row.review_requests.toLocaleString(), cls: 'num' },
      ...usageTableCells(row).slice(1),
      { value: button('阶段明细', () => management.usageDetails(row.name, row)), cls: 'nowrap' },
    ]));
    taskSection.replaceChildren(node('h4', `任务用量 · 匹配 ${match.length.toLocaleString()} 项`, 'group-title'), toolbar, table);
  };
  search.oninput = scope.onchange = render;
  const toolbar = node('div', null, 'toolbar');
  toolbar.append(search, scope);
  const byDay = node('details', null, 'instance-advanced');
  byDay.append(node('summary', '按天与模型查看'),
    storageTable('', [{ text: '日期', cls: 'nowrap' }, '提供商', '模型', ...usageHeadings], daily.map(row => [
      { value: row.date, cls: 'nowrap' },
      { value: row.provider, cls: 'model-cell' },
      { value: row.model, cls: 'model-cell' },
      ...usageTableCells(row),
    ])));
  container.replaceChildren(
    node('h4', '最近 30 天用量汇总', 'group-title'),
    storageTable('', ['范围', ...usageHeadings], [
      [{ value: '全部请求', cls: 'strong-cell nowrap' }, ...usageTableCells(daily_summary)],
      [{ value: '非任务请求', cls: 'strong-cell nowrap' }, ...usageTableCells(non_task_summary)],
    ]),
    node('p', '用量单位为 tokens；1 K = 1,000，1 M = 1,000,000。', 'hint'),
    byDay,
    taskSection,
  );
  render();
}
document.querySelector('#refresh-model-usage').onclick = function () { action(this, loadModelUsage); };
document.querySelector('#sync-model-prices').onclick = function () {
  action(this, async () => {
    showCatalog((await api('POST', 'model/catalog/sync')).catalog);
    show('价格目录已同步。可选模型，或在已绑定行应用最新价。');
  });
};
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
  const { archives } = await api('GET', 'storage/logs', { side });
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
    const result = await api('POST', 'diagnostics', {
      start: start ? new Date(start).getTime() / 1000 : 0,
      end: end ? new Date(end).getTime() / 1000 : null,
      task_ids: Array.from(document.querySelector('#diagnostics-tasks').selectedOptions, option => option.value),
      include_raw_api: document.querySelector('#diagnostics-raw-api').checked,
    });
    const reordered = result.reordered_files?.length ? `。以下日志时间倒序，已在临时副本中排序：${result.reordered_files.join('、')}` : '';
    document.querySelector('#diagnostics-result').textContent = `已保存 ${result.entries} 条事件：${result.path}${reordered}`;
    await bridge.download('diagnostics/file', { filename: result.filename }, result.filename);
  });
};
const hostApi = (view, params = {}) => api('GET', 'management/host', { view, ...params });
const management = createManagement({ api, hostApi, bridge, action, show, loadHost, ensureHost: () => host ? Promise.resolve() : loadHost(), diskSize, storageTable });
styleSettings(document);
management.open(location.hash || '#servers');
window.addEventListener('hashchange', () => management.open(location.hash || '#servers'));
const initial = await Promise.allSettled([loadA(), readTest(), loadRules(), loadDiagnostics(), loadModelUsage()]);
if (initial[1].status === 'fulfilled' && initial[1].value.running) startPolling();
for (const result of initial) if (result.status === 'rejected') show(result.reason.message, true);
