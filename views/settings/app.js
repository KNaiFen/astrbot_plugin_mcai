const bridge = window.AstrBotPluginView;
await bridge.ready();
const form = document.querySelector('#a-settings'), notice = document.querySelector('#notice');
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
}
async function saveA() { await api('POST', 'settings', values()); }
form.addEventListener('submit', event => { event.preventDefault(); action(event.submitter, async () => { await saveA(); show('A 配置已保存并生效。'); }); });
document.querySelector('#connection-test').onclick = function () { action(this, async () => { const result = await api('POST', 'connection/test', values()); show(`连接成功，B 配置了 ${result.instances} 个服务端。`); }); };
function field(container, label, value, key) {
  const wrapper = document.createElement('label'); wrapper.append(document.createTextNode(label));
  const input = document.createElement('input'); input.value = value ?? ''; input.dataset.key = key; wrapper.append(input); container.append(wrapper); return input;
}
function instance(name = '', config = {}, state = {}) {
  const card = document.createElement('article'); card.className = 'instance';
  const heading = document.createElement('header'), title = document.createElement('strong'), remove = document.createElement('button');
  title.textContent = name || '新服务端'; remove.type = 'button'; remove.className = 'secondary'; remove.textContent = '移除配置'; remove.onclick = () => card.remove(); heading.append(title, remove); card.append(heading);
  const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = state.state_unknown ? '状态待确认' : state.running ? '运行中' : '已停服'; if (!state.window_online) hint.textContent += ' · 无托管连接';
  if (state.configuration_pending) hint.textContent += ' · 配置待生效'; if (state.selectable === false) hint.textContent += ' · 待移除'; card.append(hint);
  field(card, '配置名', name, 'name'); field(card, '说明／群内叫法', config.description, 'description'); field(card, '服务端目录（其中使用 start.bat）', config.directory, 'directory');
  const advanced = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = '高级选项'; advanced.append(summary);
  for (const [key, label] of Object.entries({ java_path: '实例 Java 路径（可选）', encoding: 'BAT 编码（默认 auto）', stop_timeout: '停服超时秒（默认 120）', stop_command: 'MC 停服命令（默认 stop）', restart_prompt: '自动重启提示（默认约定提示）' })) field(advanced, label, config[key], key);
  card.append(advanced); document.querySelector('#instances').append(card);
}
async function loadHost() {
  host = await api('GET', 'host'); document.querySelector('#instances').replaceChildren();
  for (const [name, config] of Object.entries(host.instances)) instance(name, config, host.state.find(item => item.instance === name));
  for (const state of host.state.filter(item => item.selectable === false)) { const p = document.createElement('p'); p.textContent = `${state.instance}：待移除，当前进程与操作仍可管理。`; document.querySelector('#instances').append(p); }
  document.querySelector('#curseforge-state').textContent = host.curseforge_configured ? 'B 已保存密钥；不会回传原值。' : 'B 尚未配置 CurseForge 密钥。';
  document.querySelector('#powershell-path').value = host.powershell_path; document.querySelector('#world-java').value = host.world_tools.java_path ?? ''; document.querySelector('#operations-memory').value = host.operations_memory_limit_mib ?? 8192;
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
      for (const input of card.querySelectorAll('input')) { const key = input.dataset.key; if (key === 'name') name = input.value.trim(); else if (input.value.trim()) config[key] = key === 'stop_timeout' ? Number(input.value) : input.value; }
      if (!name || instances[name]) throw new Error('配置名不能为空或重复。'); instances[name] = config;
    }
    await api('POST', 'host', { instances, revision: host.revision }); await loadHost(); show('服务端配置已保存；运行中的启动变更会等待空闲。');
  });
};
document.querySelector('#save-key').onclick = function () { action(this, async () => { const input = document.querySelector('#curseforge-key'); if (!input.value) throw new Error('填写新密钥，或使用清空按钮。'); await api('POST', 'host', { curseforge_api_key: input.value }); input.value = ''; await loadHost(); show('密钥已保存到 B。'); }); };
document.querySelector('#clear-key').onclick = function () { action(this, async () => { await api('POST', 'host', { curseforge_api_key: '' }); await loadHost(); show('B 的 CurseForge 密钥已清空。'); }); };
document.querySelector('#test-key').onclick = function () { action(this, async () => { await api('POST', 'host/curseforge/test'); show('CurseForge 凭据可正常访问官方 API。'); }); };
document.querySelector('#save-host').onclick = function () { action(this, async () => { const result = await api('POST', 'host', { operations_memory_limit_mib: Number(document.querySelector('#operations-memory').value), powershell_path: document.querySelector('#powershell-path').value, world_tools: { java_path: document.querySelector('#world-java').value } }); show(result.restart_required ? '已保存，重启 B 后生效。' : '已保存。'); }); };
const names = { conversation: '普通对话', stream: '流式响应', function_call: '工具调用与续接', reasoning_effort: '排障思考强度', web_search: 'API 托管搜索', web_search_preview: '兼容托管搜索', alpha_search: '独立搜索', alpha_open: '独立搜索打开网页', alpha_find: '独立搜索页内查找', reasoning_summary: 'API 思考摘要', review_json: '审核模型与 JSON' };
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
try { await loadA(); const test = await readTest(); if (test.running) startPolling(); await loadHost(); } catch (error) { show(`配置读取失败：${error.message}`, true); }
