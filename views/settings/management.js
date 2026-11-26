import { button, node, options } from './controls.js';

const $ = selector => document.querySelector(selector);
const time = seconds => seconds == null ? '—' : new Date(seconds * 1000).toLocaleString();
const lines = value => value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
const numbers = value => value.split(/[\s,，]+/).filter(Boolean).map(Number);
const labels = { start: '启动', stop: '停止', restart: '重启', forcestop: '强制停止', forcerestart: '强制重启', active: '已启用', paused: '已暂停', pending: '排队中', running: '运行中', waiting: '等待中', applying: '执行方案中', done: '已验收', stopped: '已中止', completed: '已完成', not_accepted: 'B 未受理', failed: '失败', cancelled: '已取消' };
const eventKinds = { exit: '意外退出', restart: '连续启动失败', unresponsive: '无响应', alert: '健康告警', schedule: '定时维护', connection: 'B 连接' };
const alertReasons = { window_offline: '托管窗口掉线', disk_low: '磁盘空间不足', performance_low: 'Probe 性能偏低' };
const format = value => typeof value === 'object' && value !== null ? JSON.stringify(value, null, 2) : String(value ?? '—');
const detail = value => node('pre', format(value), 'text-preview');

export function pendingConfiguration(row) {
  const fields = row.pending_fields || [];
  const reopen = fields.filter(field => ['directory', 'java_path', 'encoding'].includes(field));
  const synchronize = fields.filter(field => !reopen.includes(field));
  return [
    reopen.length ? `配置待生效（需停服重开托管窗口：${reopen.join('、')}）` : '',
    synchronize.length ? `配置待生效（等待窗口重连或当前操作结束：${synchronize.join('、')}）` : '',
  ].filter(Boolean).join(' · ');
}

export function usageCells(row) {
  return [
    row.requests.toLocaleString(), row.input_tokens.toLocaleString(), row.output_tokens.toLocaleString(),
    `${row.cached_tokens.toLocaleString()}${row.cache_missing ? `（${row.cache_missing.toLocaleString()} 次未提供）` : ''}`,
    row.no_usage.toLocaleString(), row.cost.join('、') || '—',
  ];
}
export function usageTableCells(row) {
  const cached = node('div', row.cached_tokens.toLocaleString());
  if (row.cache_missing) cached.append(node('span', `${row.cache_missing.toLocaleString()} 次未提供`, 'cell-sub'));
  const cost = row.cost.length ? node('div', null, 'cell-stack') : '—';
  if (row.cost.length) for (const entry of row.cost) cost.append(node('div', entry));
  return [
    { value: row.requests.toLocaleString(), cls: 'num' },
    { value: row.input_tokens.toLocaleString(), cls: 'num' },
    { value: row.output_tokens.toLocaleString(), cls: 'num' },
    { value: cached, cls: 'num' },
    { value: row.no_usage.toLocaleString(), cls: 'num' },
    { value: cost, cls: 'num nowrap' },
  ];
}
export const usageColumns = ['请求', '输入', '输出', '缓存命中', '未返回', '估算费用'];

function item(title, description, status) {
  const row = node('article', null, 'data-item');
  const heading = node('h3', title);
  if (status) heading.append(' ', node('span', labels[status] || status, `badge${status === 'failed' ? ' danger' : ''}`));
  row.append(heading);
  if (description) row.append(node('p', description));
  return row;
}

function facts(container, rows) {
  container.replaceChildren(...rows.map(([key, value]) => {
    const row = node('div'); row.append(node('strong', key), node('p', format(value))); return row;
  }));
}

export function createManagement({ api, hostApi, bridge, action, show, loadHost, ensureHost, diskSize, storageTable }) {
  const dialog = $('#management-dialog');
  const dialogBody = $('#management-dialog-body');
  const dialogActions = $('#management-dialog-actions');
  let serverTimer, serverPending = false, trialOperations = 0;
  let serverRequest = 0;
  const probes = new Map();
  const post = (name, data) => api('POST', `management/${name}`, data);
  const run = (label, handle, cls) => {
    const control = button(label, () => action(control, handle), cls);
    return control;
  };
  const listen = (selector, handler) => {
    const control = $(selector); control.onclick = () => action(control, handler);
  };
  const load = (selector, callback) => {
    const area = $(selector);
    area.textContent = '正在读取…';
    return callback(area).catch(error => { area.textContent = `读取失败：${error.message}`; });
  };
  function modal(title, ...children) {
    const opts = children[0] && !(children[0] instanceof Node) && typeof children[0] === 'object' ? children.shift() : {};
    dialog.classList.toggle('wide', !!opts.wide);
    $('#management-dialog-title').textContent = title;
    dialogBody.replaceChildren(...children);
    $('#management-dialog-error').hidden = true;
    dialogActions.querySelectorAll(':scope > button').forEach(control => control.remove());
    if (!dialog.open) dialog.showModal();
    clearTimeout(serverTimer);
  }
  function confirm(title, description, callback) {
    modal(title, node('p', description));
    dialogActions.prepend(run('确认', async () => { try { await callback(); dialog.close(); } catch (error) { dialogBody.querySelector('.modal-error')?.remove(); dialogBody.append(node('p', error.message, 'modal-error')); } }, 'primary'));
  }
  function usageDetails(name, usage) {
    const table = storageTable('', [
      { text: '阶段', cls: 'nowrap' },
      '提供商',
      '模型',
      ...usageColumns.map((text, idx) => ({ text, cls: idx === 5 ? 'num nowrap' : 'num' })),
    ], usage.stages.map(row => [
      { value: row.purpose, cls: 'nowrap strong-cell' },
      { value: row.provider, cls: 'model-cell' },
      { value: row.model, cls: 'model-cell' },
      ...usageTableCells(row),
    ]));
    modal(`${name} · 模型用量`, { wide: true }, node('p', '按阶段、提供商与模型统计（用量单位：tokens）', 'hint'), table);
  }

  function renderProbe(area, result) {
    const probe = result.probe;
    if (!probe.available) { area.textContent = probe.reason; return; }
    const spark = probe.integrations?.spark;
    const values = [
      `Probe ${probe.version ?? '已安装'} · ${probe.loader ?? '加载器未知'}${probe.stale ? ' · 心跳已过期' : ''}`,
      `spark：${spark?.available ? '就绪' : spark?.installed ? `已安装（${spark.reason ?? '未就绪'}）` : '未集成'}`,
    ];
    if (result.error) values.push(result.error);
    if (Array.isArray(result.players)) values.push(`在线玩家（${result.players.length}）：${result.players.map(player => player.name).join('、') || '无'}`);
    else if (result.players?.error) values.push(`玩家查询失败：${result.players.error}`);
    if (Array.isArray(result.metrics)) {
      const sample = result.metrics[0];
      values.push(sample ? `近 10 秒：TPS ${sample.tps?.toFixed(2) ?? '—'} · MSPT ${sample.tick_ms?.mean?.toFixed(2) ?? '—'}` : '近 10 秒没有指标样本');
    } else if (result.metrics?.error) values.push(`TPS / MSPT 查询失败：${result.metrics.error}`);
    area.textContent = values.join('\n');
  }
  async function queryControl(row, area) {
    const result = await post('host', { action: 'control_status', instance: row.instance, directory: row.canonical_directory });
    area.textContent = `${result.id} · ${labels[result.status] || result.status}${result.error ? `：${result.error}` : ''}`;
    if (!['pending', 'running'].includes(result.status)) {
      show(area.textContent, result.status === 'failed');
      await servers();
    }
  }
  function scheduleServerRefresh() {
    clearTimeout(serverTimer);
    if (!$('#servers').hidden && !document.hidden && !dialog.open && (serverPending || trialOperations)) {
      serverTimer = setTimeout(() => servers(true), 2000);
    }
  }
  dialog.addEventListener('close', scheduleServerRefresh);
  document.addEventListener('visibilitychange', scheduleServerRefresh);
  async function servers(background = false) {
    clearTimeout(serverTimer);
    if (background && ($('#servers').hidden || document.hidden || dialog.open)) return;
    const area = $('#server-runtime');
    const request = ++serverRequest;
    try {
      const currentServers = (await hostApi('servers')).items;
      if (request !== serverRequest || background && ($('#servers').hidden || document.hidden || dialog.open)) return;
      serverPending = currentServers.some(row => row.web_control || row.tests?.some(trial => trial.has_stopping || trial.has_deleting));
      if (!background) probes.clear();
      area.replaceChildren();
      if (!currentServers.length) area.textContent = 'B 尚未登记正式服。';
      for (const row of currentServers) {
        const state = row.state_unknown ? '状态待确认' : row.running ? '运行中' : '已停服';
        const pids = (row.java_processes || []).map(process => process.pid).join('、');
        const pending = pendingConfiguration(row);
        const card = item(row.instance, `${row.directory}\n托管窗口：${row.window_online ? '在线' : '离线'} · 会话 ${row.session_id || '—'} · Java PID ${pids || '—'}\n实例：${row.selectable ? '可选' : '待移除'}${pending ? ` · ${pending}` : ''}`, state);
        if (row.occupant) {
          const owner = node('p', `活动任务：${row.occupant.name}（${row.occupant.id}） · `);
          const link = node('a', '打开任务看板'); link.href = '#tasks'; owner.append(link); card.append(owner);
        }
        for (const trial of row.tests || []) {
          const trialState = trial.has_deleting ? '正在清理' : trial.has_stopping ? '正在停服' : trial.state_unknown ? '状态待确认' : trial.running || trial.java_running ? '运行中' : '已停服';
          const windowState = trial.window_online ? '在线' : trial.window_exists ? '离线，尚未退出' : '已退出';
          const trialPids = (trial.java_pids || []).join('、');
          const active = trial.task_active ? ` · 所属任务仍在进行（${labels[trial.task_state] || trial.task_state}）` : '';
          card.append(node('p', `隔离试服：${trial.task_name}（${trial.task_id}） · ${trial.address}:${trial.port} · ${trialState}${active}\n窗口：${windowState} · Java PID ${trialPids || '—'} · 目录${trial.directory_exists ? '存在' : '已缺失'}\n${trial.directory}`));
          const trialActions = node('div', null, 'data-actions');
          const command = async (action, success, extra) => {
            trialOperations++;
            scheduleServerRefresh();
            try {
              await post('host', { action, task_id: trial.task_id, instance: row.instance, directory: row.canonical_directory, ...extra });
              show(success);
            } finally {
              trialOperations--;
              await servers();
            }
          };
          if (trial.can_stop) trialActions.append(run('停止试服', () => command('stop_test', '试服已停止。')));
          if (trial.can_force_stop) trialActions.append(button('强制停止试服', () => confirm('强制停止试服', '如有停服等待，将先取消等待再强制结束试服进程。', () => command('force_stop_test', '试服已强制停止。')), 'quiet'));
          if (trial.can_close) trialActions.append(run('关闭试服窗口', () => command('close_test', '试服窗口已关闭，可打开其他任务的试服。')));
          if (trial.can_delete) {
            const force = trial.running || trial.java_running || trial.window_online || trial.window_exists;
            const warning = force ? '试服仍在运行或窗口在线，确认将强制停止、关闭窗口并永久删除副本。' : '确认永久删除试服副本。';
            trialActions.append(button('删除试服', () => confirm('删除试服', warning, () => command('delete_test', '试服副本已删除。', { force })), 'quiet'));
          }
          if (trialActions.childElementCount) card.append(trialActions);
        }
        let probe = probes.get(row.instance);
        if (!probe) {
          probe = node('p', '正在读取 Probe 状态…');
          probes.set(row.instance, probe);
          hostApi('probe', { instance: row.instance }).then(result => renderProbe(probe, result), error => { probe.textContent = `Probe 状态读取失败：${error.message}`; });
        }
        const tracking = node('p', row.web_control ? `待核对：${row.web_control.id} · ${labels[row.web_control.status] || '状态待确认'}` : '');
        const actions = node('div', null, 'data-actions');
        actions.append(run('刷新在线玩家与 TPS', async () => {
          probe.textContent = '正在读取实时指标…';
          try { renderProbe(probe, await hostApi('probe', { instance: row.instance, live: '1' })); }
          catch (error) { probe.textContent = error.message; }
        }));
        const controlStatus = run('核对操作状态', () => queryControl(row, tracking));
        controlStatus.hidden = !row.web_control;
        for (const command of ['start', 'stop', 'restart', 'forcestop', 'forcerestart']) {
          const force = command.startsWith('force');
          const target = pids ? `当前 Java PID：${pids}` : `当前启动链 PID：${(row.launcher_processes || []).map(process => process.pid).join('、') || '—'}`;
          const escalate = row.web_control?.can_escalate_force;
          const warning = force ? `${target}。强制结束可能丢失未保存的数据。${escalate ? '会先取消当前停止/重启等待，再强制结束进程。' : ''}` : '';
          const control = button(labels[command], () => confirm(`${labels[command]} ${row.instance}`, `${warning}操作会在 B 的托管窗口执行，提交后可按原编号核对。`, async () => {
            try {
              const result = await post('host', { action: command, instance: row.instance, directory: row.canonical_directory });
              show(result.message || `操作 ${result.id} · ${labels[result.status] || result.status}`);
              await servers();
            } catch (error) { await servers(); throw error; }
          }), force ? 'quiet' : 'secondary');
          control.disabled = !row.selectable || !row.window_online || row.state_unknown || row.target_mismatch || !!row.occupant || row.maintenance_active || (!!row.web_control && !(force && escalate)) || (force && ((!row.running && !row.java_running) || (row.java_processes || []).length > 1));
          actions.append(control);
        }
        actions.append(controlStatus);
        card.append(probe, actions, tracking); area.append(card);
      }
    } catch (error) {
      if (request === serverRequest && !background) area.textContent = `读取失败：${error.message}`;
    } finally {
      if (request === serverRequest) scheduleServerRefresh();
    }
  }
  listen('#refresh-servers', servers);
  listen('#reload-host', async () => { await post('host', { action: 'reload' }); await Promise.all([loadHost(), servers()]); show('B 实例配置已重载。'); });

  const scheduleForm = $('#schedule-form');
  const scheduleFields = scheduleForm.elements;
  let scheduleRows = [];
  function scheduleMode() {
    const isBackup = scheduleFields.kind.value === 'backup';
    for (const name of ['mode', 'retain', 'paths', 'announce_minutes']) scheduleFields[name].closest('label').hidden = (name === 'announce_minutes') === isBackup;
    scheduleFields.paths.required = isBackup;
  }
  function editSchedule(row) {
    const spec = row?.spec || {};
    scheduleFields.id.value = row?.id || '';
    scheduleFields.instance.disabled = !!row;
    scheduleFields.instance.value = row?.instance ?? scheduleFields.instance.options[0]?.value ?? '';
    scheduleFields.kind.value = spec.kind || 'backup';
    scheduleFields.at.value = spec.at || '';
    scheduleFields.weekdays.value = (spec.weekdays || []).join(',');
    scheduleFields.mode.value = spec.mode || 'online';
    scheduleFields.retain.value = spec.retain || 3;
    scheduleFields.paths.value = (spec.paths || []).join('\n');
    scheduleFields.announce_minutes.value = (spec.announce_minutes ?? [10, 1]).join('\n');
    scheduleFields.notify_success.checked = !!spec.notify_success;
    $('#schedule-error').textContent = '';
    scheduleMode(); scheduleForm.hidden = false; scheduleFields.at.focus();
  }
  scheduleFields.kind.onchange = scheduleMode;
  function drawSchedules() {
    const area = $('#schedules');
    const kind = $('#schedule-kind-filter').value, instance = $('#schedule-instance-filter').value;
    const rows = scheduleRows.filter(row => (!kind || row.spec.kind === kind) && (!instance || row.instance === instance));
    area.replaceChildren();
    if (!rows.length) area.textContent = '没有符合条件的计划。';
    for (const row of rows) {
      const spec = row.spec;
      const backup = spec.kind === 'backup';
      const periodic = spec.weekdays?.map(day => '一二三四五六日'[day - 1]).join('、');
      const scope = backup ? `${spec.mode === 'online' ? '在线' : '停服'} · 保留 ${spec.retain} 份\n路径：${spec.paths.join('、')}` : `公告：${spec.announce_minutes.join('、') || '无'}${spec.announce_minutes.length ? ' 分钟前' : ''}`;
      const result = row.last_result ? `${row.last_result.status}：${row.last_result.message || '—'}` : '尚无结果';
      const card = item(`${row.instance} · 定时${backup ? '备份' : '重启'}`, `${row.id} · ${periodic ? `每周${periodic}` : '每天'} ${spec.at}（B 本地）\n${scope}\n${spec.notify_success ? '成功也通知' : '仅通知异常'} · 下次 ${row.next_local || '—'}\n上次：${result}`, row.state);
      const actions = node('div', null, 'data-actions');
      const update = async command => { await post('host', { action: 'schedule', command, id: row.id }); await schedules(); };
      actions.append(button('编辑', () => editSchedule(row)), run(row.state === 'paused' ? '恢复' : '暂停', () => update(row.state === 'paused' ? 'resume' : 'pause')), button('删除', () => confirm('删除定时计划', `${row.instance} · ${row.id}。已启动的维护仍会结算。`, () => update('delete')), 'quiet'));
      card.append(actions); area.append(card);
    }
  }
  async function schedules() {
    await load('#schedules', async () => {
      const [result, servers] = await Promise.all([hostApi('schedules'), hostApi('servers')]);
      scheduleRows = result.items;
      const selectable = servers.items.filter(row => row.selectable).map(row => [row.instance, row.instance]);
      options(scheduleFields.instance, selectable);
      const names = new Set([...servers.items, ...scheduleRows].map(row => row.instance));
      options($('#schedule-instance-filter'), [['', '全部实例'], ...[...names].map(name => [name, name])]);
      $('#schedule-health').textContent = `调度器：${result.health.status === 'ready' ? '就绪' : '降级'}（${result.health.status}）${result.health.error ? ` · ${result.health.error}` : ''}`;
      $('#new-schedule').disabled = !scheduleFields.instance.options.length;
      drawSchedules();
    });
  }
  $('#new-schedule').disabled = true;
  $('#new-schedule').onclick = () => editSchedule();
  $('#cancel-schedule').onclick = () => { scheduleForm.hidden = true; };
  $('#schedule-kind-filter').onchange = $('#schedule-instance-filter').onchange = drawSchedules;
  listen('#refresh-schedules', schedules);
  scheduleForm.onsubmit = event => {
    event.preventDefault();
    action(event.submitter, async () => {
      const errorArea = $('#schedule-error'); errorArea.textContent = '';
      const f = scheduleFields, id = f.id.value, kind = f.kind.value;
      const spec = { kind, at: f.at.value, notify_success: f.notify_success.checked };
      const weekdays = numbers(f.weekdays.value);
      if (weekdays.length) spec.weekdays = weekdays;
      if (kind === 'backup') Object.assign(spec, { mode: f.mode.value, retain: Number(f.retain.value), paths: lines(f.paths.value) });
      else spec.announce_minutes = numbers(f.announce_minutes.value);
      try {
        if ([...weekdays, ...(spec.announce_minutes || [])].some(value => !Number.isInteger(value))) throw new Error('星期及公告分钟须填写整数。');
        await post('host', { action: 'schedule', command: id ? 'edit' : 'create', id, instance: f.instance.value, spec });
        scheduleForm.hidden = true; await schedules(); show('定时计划已保存。');
      } catch (error) { errorArea.textContent = error.message; }
    });
  };

  function tasks(page = 1) {
    return load('#task-board', async area => {
      const { items, count } = await api('GET', 'management/tasks', { state: $('#task-filter').value, search: $('#task-search').value, page });
      area.replaceChildren();
      for (const row of items) {
        const tokens = row.usage.input_tokens + row.usage.output_tokens;
        const [, input, output, cached] = usageCells(row.usage);
        const usage = `模型 ${row.usage.requests.toLocaleString()} 次（审核 ${row.usage.review_requests.toLocaleString()} 次） · 输入 ${input} / 输出 ${output} / 缓存 ${cached} tokens${row.token_limit ? ` · 输入与输出共 ${tokens.toLocaleString()} / ${row.token_limit.toLocaleString()}（${Math.round(tokens * 100 / row.token_limit)}%）` : ''}${row.usage.cost.length ? ` · 估算费用 ${row.usage.cost.join('、')}` : ''}`;
        const card = item(row.name, `任务 ${row.id} · 群 ${row.group} · 实例 ${row.instance || '待识别'}\n${usage}${row.active_provider_slot === 'backup' && row.active_provider_id ? `\n当前模型通道：备用 API（${row.active_provider_id}）` : ''}${row.pause_reason ? `\n暂停原因：${row.pause_reason}` : ''}${row.pause_after_operation ? '\n修复结算后暂停' : ''}`, row.state);
        if (row.model_retry) {
          const slotLabel = row.model_retry.slot === 'backup' ? '（备用 API）' : row.model_retry.slot === 'primary' && row.model_retry.slot_errors?.backup ? '（主备轮流重试）' : '';
          card.append(node('p', `最近模型重试${slotLabel}：${row.model_retry.error || row.model_retry.category || format(row.model_retry)}`));
        }
        if (row.archive_error) card.append(node('p', `归档错误：${row.archive_error}`, 'modal-error'));
        if (row.continuation) card.append(node('p', `多轮授权 ${row.continuation_status}${row.continuation.planned_stages?.length ? `\n后续规划：${row.continuation.planned_stages.join('；')}` : ''}\n范围：${row.continuation.scope}\n完成条件：${row.continuation.completion}`));
        if (row.cancel_pending) card.append(node('p', '正在结算取消；实例仍被占用。'));
        const actions = node('div', null, 'data-actions');
        const update = async (action, data = {}) => { const result = await post('tasks', { id: row.id, action, ...data }); await tasks(page); return result; };
        if (row.usage.requests) actions.append(button('用量明细', () => usageDetails(row.name, row.usage)));
        if (!row.cancel_pending && !['done', 'stopped'].includes(row.state)) {
          const say = node('label', null, 'switch-row');
          const input = node('input', null, 'switch'); input.type = 'checkbox'; input.checked = !row.say_paused; input.setAttribute('role', 'switch');
          input.onchange = () => action(input, async () => { try { await update('say', { enabled: input.checked }); } catch (error) { input.checked = !row.say_paused; throw error; } });
          say.append(node('span', '接收成员 say'), input);
          const pause = row.state === 'paused';
          actions.append(say, run(pause ? '续接' : '暂停', () => update(pause ? 'resume' : 'pause')), button('中止', () => confirm('中止任务', row.name, () => update('stop')), 'quiet'), button('验收', () => confirm('验收任务', row.name, () => update('done'))));
        }
        if (row.plan) {
          actions.append(button('查看待批准方案', () => {
            const code = node('input'); code.placeholder = '输入当前方案短码'; code.setAttribute('aria-label', '当前方案短码');
            const error = node('p', '', 'modal-error');
            modal(row.name, detail(row.plan.text), node('p', `短码：${row.plan.code}`), code, error);
            dialogActions.prepend(run('批准方案', async () => {
              try { await update('approve', { code: code.value }); dialog.close(); }
              catch (exc) { error.textContent = exc.message; }
            }, 'primary'));
          }));
        }
        if (row.state === 'done' && row.archive_error) actions.append(run('重试归档', async () => { await update('archive'); show('归档已排队，刷新任务查看结果。'); }));
        card.append(actions); area.append(card);
      }
      pages(area, page, count, tasks);
    });
  }
  function pages(area, page, count, callback) {
    if (!count) { area.append(node('p', '暂无记录。')); return; }
    const max = Math.ceil(count / 30);
    const pager = node('div', null, 'data-actions');
    const previous = run('上一页', () => callback(page - 1)); previous.disabled = page <= 1;
    const next = run('下一页', () => callback(page + 1)); next.disabled = page >= max;
    pager.append(previous, node('span', `第 ${page} / ${max} 页 · ${count} 条`), next); area.append(pager);
  }
  listen('#refresh-tasks', () => tasks());
  $('#task-filter').onchange = $('#task-search').onchange = () => tasks();

  function logReader(id, mode, attachment) {
    const section = node('section', null, 'log-reader');
    const output = node('div', null, 'text-preview');
    let cursor = 0;
    const next = run(mode === 'file' ? '预览附件' : '读取控制台', async () => {
      const request = { id, mode, ...(attachment ? { attachment } : {}) };
      const page = await hostApi('event', { ...request, after: cursor });
      output.replaceChildren();
      for (const line of page.items) {
        const row = node('div');
        const text = node('pre', `${line.seq}  ${line.body.output}`);
        row.append(text);
        if (line.next_offset != null) {
          let offset = line.next_offset;
          const more = run('读取本行后续', async () => {
            const result = await hostApi('event', { ...request, line: line.seq, offset });
            text.textContent = `${line.seq} · 偏移 ${offset}\n${result.body.output}`;
            offset = result.next_offset;
            more.hidden = offset == null;
          });
          row.append(more);
        }
        output.append(row);
      }
      if (!page.items.length) output.textContent = '没有可显示的内容。';
      cursor = page.next_cursor ?? 0;
      next.textContent = page.next_cursor == null ? '返回第一页' : '下一页';
    });
    section.append(next, output);
    return section;
  }

  async function eventDetail(row) {
    const entry = await hostApi('event', { id: row.id });
    const title = `${entry.instance} · ${eventKinds[entry.type || entry.reason] || entry.type || entry.reason}`;
    const summary = node('div', null, 'info-grid');
    facts(summary, [['原因', entry.summary], ['时间', time(entry.time)], ['编号', entry.id], ['涉事 Java PID', entry.affected_java?.map?.(process => process.pid ?? process).join('、') || entry.affected_java?.pid || '—'], ['受影响操作', entry.operations?.join('、') || entry.operation_id || '—'], ['控制台', `${entry.console_status} · ${entry.console_count ?? 0} 行`], ['性能留证', entry.performance_status]]);
    modal(title, summary);
    if (entry.performance?.length) {
      const performance = node('details'); performance.append(node('summary', '故障前 Probe 性能指标'), detail(entry.performance)); dialogBody.append(performance);
    }
    if (entry.console_count) dialogBody.append(logReader(entry.id, 'console'));
    for (const launch of entry.launches) {
      const section = node('section', null, 'data-item');
      section.append(node('h4', `Java PID ${launch.pid} · ${time(launch.created)} → ${time(launch.exited_at)}`));
      for (const file of launch.attachments) {
        const block = node('details');
        block.append(node('summary', `${file.path} · ${file.status}`));
        if (file.status === 'saved') {
          const filename = `${file.path.split('/').at(-1)}.gz`;
          const fields = node('div', null, 'info-grid');
          facts(fields, [['原文大小', diskSize(file.bytes)], ['SHA-256', file.sha256]]);
          const fileActions = node('div', null, 'data-actions');
          fileActions.append(run('下载 gzip', () => bridge.download('management/attachment', { id: entry.id, attachment: file.id }, filename)));
          block.append(fields, fileActions, logReader(entry.id, 'file', file.id));
        } else if (file.reason) block.append(node('p', file.reason));
        section.append(block);
      }
      dialogBody.append(section);
    }
  }

  async function events(cursors = []) {
    await load('#events', async area => {
      const select = $('#event-instance');
      const filters = { instance: select.value, kind: $('#event-kind').value };
      if ($('#event-existing-only').checked) filters.existing_only = '1';
      if (cursors.length) filters.before = cursors.at(-1);
      const data = await hostApi('events', filters);
      if (data.instances) options(select, [['', '全部实例'], ...data.instances.map(value => [value, data.existing_instances?.includes(value) ? value : `${value}（已删除）`])]);
      area.replaceChildren(node('h3', '活跃健康告警'));
      if (!data.active.length) area.append(node('p', '当前没有活跃健康告警。', 'hint'));
      for (const alert of data.active) {
        const row = item(`${alert.instance} · ${alertReasons[alert.reason] || alert.reason}`, `自 ${time(alert.since)} · ${alert.id}`, '活跃');
        const detailActions = node('div', null, 'data-actions');
        detailActions.append(run('查看详情', () => eventDetail(alert)));
        row.append(detailActions); area.append(row);
      }
      area.append(node('h3', '事故与事件历史'));
      if (!data.items.length) area.append(node('p', '当前筛选没有事件。', 'hint'));
      for (const record of data.items) {
        const row = item(`${record.instance} · ${eventKinds[record.type || record.reason] || record.reason}`, `${time(record.time)} · ${record.summary}`, record.type === 'alert' ? record.recovered ? '已恢复' : '告警' : record.status);
        const detailActions = node('div', null, 'data-actions');
        detailActions.append(run('查看详情', () => eventDetail(record)));
        row.append(detailActions); area.append(row);
      }
      const pager = node('div', null, 'data-actions');
      if (cursors.length) pager.append(run('上一页', () => events(cursors.slice(0, -1))));
      if (data.next_cursor != null) pager.append(run('下一页', () => events([...cursors, data.next_cursor])));
      area.append(pager);
    });
  }
  function connectionEvents(page = 1) {
    return load('#connection-events', async area => {
      const data = await api('GET', 'management/connections', { page });
      area.replaceChildren(node('h3', 'B 失联与恢复（A 本地记录）'));
      for (const row of data.items) area.append(item(row.summary, `${time(row.time)} · 自 ${time(row.since)} · ${row.error_category ?? '—'}`, row.recovered ? '已恢复' : '失联'));
      pages(area, page, data.count, connectionEvents);
    });
  }
  const refreshEvents = () => Promise.all([events(), connectionEvents()]);
  listen('#refresh-events', refreshEvents);
  $('#event-instance').onchange = $('#event-kind').onchange = $('#event-existing-only').onchange = () => events();

  const documentEditor = $('#knowledge-text'), indexEditor = $('#knowledge-index-text');
  const fileSelect = $('#knowledge-file');
  const normalize = text => text.replace(/\r\n?/g, '\n');
  const dirty = (editor, version) => !!version && editor.value !== normalize(version.text);
  let documentVersion, indexVersion, loadNumber = 0, casePage = 0;
  function saveFromModal(label, callback) {
    dialogActions.prepend(run(label, async () => { await callback(); dialog.close(); }, 'primary'));
  }
  function inputLabel(label, value = '', tag = 'input') {
    const wrapper = node('label', label), input = node(tag);
    input.value = value;
    wrapper.append(input);
    return [wrapper, input];
  }
  function associationEditor(action, row, indexRevision) {
    const [nameLabel, name] = inputLabel('实例名', row?.title);
    const [directoryLabel, directory] = inputLabel('规范目录（B 上的绝对路径）', row?.directory || '');
    modal(action === 'create_server_doc' ? '新建服务端关联' : '设置目录关联', nameLabel, directoryLabel);
    saveFromModal('保存关联', async () => {
      const result = await post('knowledge', {
        action, file: row?.file, directory: directory.value.trim(),
        instance_name: name.value.trim() || undefined, index_revision: indexRevision,
      });
      await refreshKnowledge(result.file);
    });
  }
  function renderAssociations(data) {
    const buttonNew = button('新建服务端关联', () => associationEditor('create_server_doc', null, data.index_revision));
    buttonNew.disabled = !!data.index_error;
    const associations = $('#knowledge-links');
    const topActions = node('div', null, 'actions');
    topActions.append(buttonNew);
    associations.replaceChildren(node('h3', '目录关联管理'), topActions);
    if (data.index_error) associations.append(node('p', data.index_error, 'modal-error'));
    const rows = data.items.flatMap(row => {
      const directories = data.entries.filter(entry => entry.file === row.file).map(entry => entry.directory);
      return (directories.length ? directories : [null]).map(directory => {
        const edit = button(directory ? '修改目录' : '关联目录',
          () => associationEditor('set_association', { ...row, directory }, data.index_revision));
        const remove = directory
          ? button('解除关联', () => confirm('解除目录关联', directory, async () => {
            await post('knowledge', { action: 'remove_association', directory, index_revision: data.index_revision });
            await refreshKnowledge();
          }))
          : button('删除孤立文档', () => confirm('删除孤立文档', row.file, async () => {
            if (row.file === documentVersion?.name && dirty(documentEditor, documentVersion)) throw new Error('请先保存或放弃当前 Markdown 修改。');
            await post('knowledge', { action: 'delete_orphan', file: row.file, revision: row.revision });
            await refreshKnowledge();
          }));
        edit.disabled = remove.disabled = !!data.index_error;
        const controls = node('div', null, 'data-actions');
        controls.append(edit, remove);
        return [row.title, directory || '未关联', row.file, row.case_count, controls];
      });
    });
    associations.append(storageTable('服务端文档关联', ['实例名', '规范目录', '文档路径', '经验数', '操作'], rows));
  }
  function renderCases() {
    const filter = $('#knowledge-filter').value.trim().toLowerCase();
    const area = $('#knowledge-cases');
    area.replaceChildren();
    const cases = [...documentVersion.cases].reverse().filter(row => `${row.title} ${row.id} ${row.category} ${row.keywords.join(' ')} ${row.body}`.toLowerCase().includes(filter));
    const pages = Math.max(1, Math.ceil(cases.length / 20));
    casePage = Math.min(casePage, pages - 1);
    const paging = node('div', null, 'data-actions');
    const previous = button('上一页', () => { casePage--; renderCases(); });
    const next = button('下一页', () => { casePage++; renderCases(); });
    previous.disabled = casePage === 0;
    next.disabled = casePage + 1 >= pages;
    paging.append(node('span', `共 ${cases.length} 条 / 全部 ${documentVersion.cases.length} 条 · 第 ${casePage + 1}/${pages} 页`), previous, next);
    area.append(paging);
    if (!cases.length) area.append(node('p', filter ? '没有匹配的经验。' : '暂无经验，可新增人工经验。', 'hint'));
    for (const row of cases.slice(casePage * 20, (casePage + 1) * 20)) {
      const card = item(row.title, [row.date, row.id].filter(Boolean).join(' · '));
      if (row.category) card.append(node('span', row.category, 'badge'));
      if (row.status === 'superseded') card.append(node('span', `已过时${row.superseded_by.length ? `（被 ${row.superseded_by.join('、')} 替代）` : ''}`, 'badge'));
      const body = node('div', null, 'knowledge-body');
      for (const [i, block] of row.body.split(/^\s*```[^\n]*$/m).entries()) {
        if (!block.trim()) continue;
        if (i % 2) body.append(node('pre', block.trim(), 'text-preview'));
        else for (const paragraph of block.trim().split(/\n\s*\n|\n(?=#{1,6} )/)) {
          const heading = /^#{1,6} (.+)/.exec(paragraph);
          if (heading) body.append(node('h4', heading[1]));
          const text = heading ? paragraph.slice(heading[0].length).trim() : paragraph;
          if (text) body.append(node('p', text));
        }
      }
      const controls = node('div', null, 'data-actions');
      controls.append(button('编辑', () => caseEditor(row)), button('删除', () => confirm('删除经验案例', row.title, () => saveCase({ action: 'delete_case', case_id: row.id }))));
      card.append(body, controls);
      area.append(card);
    }
  }
  function caseEditor(row) {
    const [titleLabel, title] = inputLabel('标题', row?.title);
    const [dateLabel, date] = inputLabel('日期（可选，ISO 日期或时间）', row?.date || '');
    const [bodyLabel, body] = inputLabel('正文（Markdown）', row?.body, 'textarea');
    body.rows = 12;
    modal(row ? '编辑经验' : '新增人工经验', titleLabel, dateLabel, bodyLabel);
    saveFromModal('保存经验', () => saveCase({
      action: 'upsert_case', case_id: row?.id, title: title.value, date: date.value.trim(), body: body.value,
    }));
  }
  async function saveCase(data) {
    await post('knowledge', { ...data, name: documentVersion.name, revision: documentVersion.revision });
    await refreshKnowledge();
  }
  async function openDocument(name, source = false) {
    const number = ++loadNumber;
    const version = name ? await api('GET', 'management/knowledge', { name }) : null;
    if (number !== loadNumber) return;
    fileSelect.value = name;
    documentVersion = version;
    casePage = 0;
    $('#knowledge-editor').hidden = !version;
    $('#knowledge-revision').textContent = version ? `${version.directory || '未关联'} · ${name}` : '暂无服务端文档，可从目录关联管理新建。';
    if (version) {
      documentEditor.value = normalize(version.text);
      renderCases();
      showSource(source);
    }
  }
  function showSource(source) {
    $('#knowledge-source').hidden = !source;
    $('#knowledge-structured').hidden = source;
    $('#toggle-knowledge-source').textContent = source ? '返回经验案例' : '切换 Markdown 源码';
  }
  async function refreshKnowledge(preferred, discard = false, source = false) {
    const data = await api('GET', 'management/knowledge');
    renderAssociations(data);
    options(fileSelect, data.items.map(row => [
      row.file, row.linked ? `${row.title} · ${row.directory}（${row.case_count} 条经验）` : `${row.title}（未关联 · ${row.case_count} 条经验）`,
    ]));
    if (!discard && dirty(documentEditor, documentVersion)) {
      fileSelect.value = documentVersion.name;
      return;
    }
    const name = preferred || documentVersion?.name;
    await openDocument(data.items.some(row => row.file === name) ? name : data.items[0]?.file || '', source);
  }
  function discardDocument(callback) {
    if (dirty(documentEditor, documentVersion)) confirm('放弃未保存的 Markdown 修改', '继续将丢弃当前文档的修改。', callback);
    else return callback();
  }
  fileSelect.onchange = () => {
    const name = fileSelect.value;
    if (documentVersion) fileSelect.value = documentVersion.name;
    action(fileSelect, () => discardDocument(() => openDocument(name)));
  };
  listen('#refresh-knowledge', () => discardDocument(() => refreshKnowledge(undefined, true)));
  listen('#new-knowledge-case', () => caseEditor());
  $('#knowledge-filter').oninput = () => { casePage = 0; renderCases(); };
  listen('#toggle-knowledge-source', () => $('#knowledge-source').hidden
    ? showSource(true) : discardDocument(() => openDocument(documentVersion.name)));
  listen('#save-knowledge', async () => {
    await post('knowledge', { name: documentVersion.name, revision: documentVersion.revision, text: documentEditor.value });
    await refreshKnowledge(documentVersion.name, true, true);
    show('经验文档已保存。');
  });
  async function loadIndex() {
    indexVersion = await api('GET', 'management/knowledge', { name: 'index.md' });
    indexEditor.disabled = $('#save-knowledge-index').disabled = false;
    indexEditor.value = normalize(indexVersion.text);
  }
  listen('#load-knowledge-index', () => {
    if (dirty(indexEditor, indexVersion)) confirm('重新读取索引', '继续将丢弃未保存的索引修改。', loadIndex);
    else return loadIndex();
  });
  listen('#save-knowledge-index', async () => {
    await post('knowledge', { name: indexVersion.name, revision: indexVersion.revision, text: indexEditor.value });
    await Promise.all([loadIndex(), refreshKnowledge()]);
    show('经验索引已保存。');
  });

  const version = value => value.ready ? `${value.version} · ${value.path}` : `未就绪${value.path ? ` · ${value.path}` : ''} · ${value.error}`;
  function environment(side) {
    return load(side === 'a' ? '#a-environment' : '#host-environment', async area => {
      if (side === 'a') {
        const data = await api('GET', 'management/environment');
        facts(area, [['PowerShell 7', version(data.powershell)], ['工作区辅助操作额度', `${data.memory_mib} MiB`], ...['HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'].map(key => [key, data.proxy[key] || '未设置'])]);
      } else {
        const data = await hostApi('environment');
        facts(area, [['协议 / 版本', `${data.protocol} / ${data.version}`], ['监听地址', `${data.listen}:${data.port}`], ['数据目录', data.data_dir], ['证书 SHA-256', data.fingerprint], ['PowerShell 7', version(data.powershell)], ['存档 Java', version(data.java)], ...Object.entries(data.jars).map(([key, ready]) => [key, ready ? '就绪' : '缺失'])]);
      }
    });
  }
  listen('#check-a-environment', () => environment('a'));
  listen('#check-b-environment', () => environment('b'));
  listen('#test-modrinth', async () => { await post('modrinth'); show('A 已用当前代理设置访问 Modrinth API。'); });

  function storage() {
    return load('#storage-detail', async area => {
      const data = await hostApi('storage');
      area.replaceChildren(node('h3', '备份清单'));
      if (!data.backups.length) area.append(node('p', '没有可读的备份清单。'));
      for (const row of data.backups) {
        const label = row.schedule_id ? `定时计划备份 · 计划 ${row.schedule_id}` : '修复备份';
        const card = item(`${row.instance || '—'} · ${label}`, `${time(row.time)} · ${row.operation_id}`);
        const cardActions = node('div', null, 'data-actions');
        cardActions.append(run('查看覆盖范围', async () => {
          const manifest = await hostApi('backup', { id: row.operation_id });
          modal('备份覆盖范围', node('p', row.path), detail(manifest.files));
        }));
        card.append(cardActions);
        area.append(card);
      }
      area.append(node('h3', '当前及最近后台作业'));
      if (!data.jobs.length) area.append(node('p', '没有后台作业。'));
      for (const row of data.jobs) {
        const card = item(`${row.instance} · ${row.kind}`, `${row.id} · 任务 ${row.task_id}\n${time(row.created)}${row.error ? ` · ${row.error}` : ''}`, row.status);
        const cardActions = node('div', null, 'data-actions');
        cardActions.append(button('详情', () => modal('作业状态', detail(row))));
        if (['running', 'pending'].includes(row.status)) cardActions.append(button('取消作业', () => confirm('取消后台作业', `${row.instance} · ${row.id}`, async () => { await post('host', { action: 'job_cancel', id: row.id }); await storage(); })));
        card.append(cardActions);
        area.append(card);
      }
      area.append(node('h3', '暂存下载'));
      if (!data.download_items.length) area.append(node('p', '没有暂存下载。'));
      for (const row of data.download_items) area.append(item(row.filename, `来源 ${row.source} · 大小 ${diskSize(row.size)} · 任务 ${row.task_id}\nSHA-256 ${row.sha256}\n${row.referenced ? '已有安装引用' : '无安装引用'}`, row.ready ? '已暂存' : '等待上传'));
    });
  }
  listen('#refresh-storage-detail', storage);

  const opened = new Set();
  return { modal, usageDetails, open(hash) {
    if (hash !== '#servers') clearTimeout(serverTimer);
    if (hash === '#knowledge') {
      if (!dirty(documentEditor, documentVersion)) refreshKnowledge().catch(error => show(error.message, true));
      return;
    }
    if (opened.has(hash)) return;
    const run = {
      '#servers': servers,
      '#server-configs': ensureHost,
      '#connection': () => environment('a'),
      '#host': () => Promise.all([ensureHost(), environment('b')]),
      '#maintenance': schedules,
      '#tasks': tasks,
      '#incidents': () => Promise.all([refreshEvents(), ensureHost()]),
    }[hash];
    if (run) {
      opened.add(hash);
      run().catch(error => show(error.message, true)).finally(() => opened.delete(hash));
    }
  } };
}
