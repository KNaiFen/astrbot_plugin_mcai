export function node(tag, text, cls) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (cls) element.className = cls;
  return element;
}

export function button(text, handler, cls = 'secondary') {
  const element = node('button', text, cls);
  element.type = 'button';
  element.onclick = handler;
  return element;
}

export function options(select, rows, fallback = '') {
  const current = select.value || fallback;
  select.replaceChildren(...rows.map(([value, text]) => new Option(text, value)));
  if (rows.some(([value]) => value === current)) select.value = current;
}

export function styleSettings(root) {
  for (const label of root.querySelectorAll('label')) {
    if (label.classList.contains('setting-row') || label.closest('.toolbar')) continue;
    const control = label.querySelector(':scope > input, :scope > select, :scope > textarea');
    if (!control) continue;
    const title = label.querySelector(':scope > span') || node('span');
    if (!title.parentNode) {
      const text = [...label.childNodes].filter(child => child.nodeType === Node.TEXT_NODE);
      title.textContent = text.map(child => child.textContent).join('').trim();
      text.forEach(child => child.remove());
    }
    label.prepend(title);
    label.classList.add('setting-row');
    if (control.type === 'checkbox') {
      control.classList.add('switch');
      control.setAttribute('role', 'switch');
    } else if (control.type === 'password') {
      const wrap = node('span', null, 'secret-control');
      control.before(wrap);
      const toggle = button('显示', () => {
        const visible = control.type === 'password';
        control.type = visible ? 'text' : 'password';
        toggle.textContent = visible ? '隐藏' : '显示';
        toggle.setAttribute('aria-pressed', visible);
      }, 'quiet');
      toggle.setAttribute('aria-pressed', 'false');
      wrap.append(control, toggle);
    }
    const description = label.nextElementSibling;
    if (description?.classList.contains('hint') && !description.id && !description.querySelector('button, input')) title.append(description);
  }
}

function tagEditor(textarea) {
  const label = textarea.closest('label');
  label.classList.add('tag-setting');
  label.dataset.editor = 'tags';
  textarea.hidden = true;
  const container = node('div', null, 'tag-editor');
  const tags = node('div', null, 'tags');
  const entry = node('input'); entry.placeholder = '输入后按回车，或粘贴多行';
  entry.setAttribute('aria-label', label.querySelector('span').textContent);
  const paths = textarea.dataset.key === 'test_copy_paths';
  const split = value => value.split(paths ? /\r?\n/ : /[\s,，]+/).map(row => row.trim()).filter(Boolean);
  const draw = () => {
    const values = split(textarea.value);
    tags.replaceChildren(...values.map((value, i) => button(`${value} ×`, () => {
      values.splice(i, 1); textarea.value = values.join('\n'); draw();
    }, 'tag')));
  };
  const add = value => {
    textarea.value = [...new Set([...split(textarea.value), ...split(value)])].join('\n');
    entry.value = ''; draw();
  };
  entry.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); add(entry.value); } };
  entry.onblur = () => add(entry.value);
  entry.onpaste = event => {
    const text = event.clipboardData.getData('text');
    if (split(text).length > 1) { event.preventDefault(); add(text); }
  };
  textarea.oninput = draw;
  container.append(tags, entry);
  label.append(container);
  draw();
}

function rowEditor(field, type, data, fetchServers, priceCatalog) {
  const label = field.closest('label');
  label.dataset.editor = 'rows';
  field.hidden = true;
  const table = node('div', null, 'editor-table');
  const headings = type === 'routes' ? ['实例', '平台', '群号'] : ['提供商', '货币', '输入 (每 1M)', '输出 (每 1M)', '缓存命中 (每 1M)'];
  const header = node('div', null, `editor-row ${type} editor-heading`);
  header.append(...headings.map(name => node('strong', name)));
  if (type === 'prices') header.append(node('strong', '倍率 / 上游来源'));
  header.append(node('span'));
  table.append(header);
  const group = node('datalist'); group.id = 'allowed-groups';
  let servers = [];
  const rows = [];
  const rowBody = node('div', null, 'editor-rows');
  function update() {
    field.value = rows.flatMap(({ controls }) => {
      const values = controls.map(control => control.value.trim());
      if (values.every(value => !value)) return [];
      const [id, ...rest] = values;
      if (type === 'routes') return `${id}=${rest[0]}:GroupMessage:${rest[1]}`;
      return `${id}=${rest.join(':')}`;
    }).join('\n');
  }
  const withCurrent = (entries, selected) => entries.some(([id]) => id === selected) || !selected ? entries : [...entries, [selected, `${selected}（当前保存值）`]];
  function add(values) {
    const wrapper = node('div', null, `editor-row ${type}`);
    const controls = headings.map((heading, i) => {
      const selectable = i === 0 || (type === 'routes' && i === 1);
      const control = node(selectable ? 'select' : 'input');
      control.setAttribute('aria-label', heading);
      control.title = heading;
      if (selectable) {
        const candidates = type === 'prices' ? data.providers.map(item => [item.id, item.name]) : i === 1 ? data.platforms.map(item => [item.id, `${item.name} · ${item.id}`]) : servers;
        options(control, [['', heading], ...withCurrent(candidates, values[i])], values[i]);
      } else {
        control.value = values[i] || '';
        control.placeholder = heading;
        if (type === 'routes') control.setAttribute('list', group.id);
        if (type === 'prices' && i > 1) { control.type = 'number'; control.min = '0'; control.step = 'any'; }
      }
      control.oninput = update;
      return control;
    });
    const row = { controls };
    rows.push(row);
    wrapper.append(...controls);
    if (type === 'prices') {
      row.binding = data.bindings[values[0]];
      const sources = node('div', null, 'price-source');
      const label = node('span', '', 'hint');
      const multiplier = node('input'); multiplier.type = 'number'; multiplier.min = '0'; multiplier.step = 'any';
      multiplier.setAttribute('aria-label', '上游价格倍率');
      const recalculate = () => {
        const binding = row.binding;
        if (!binding || multiplier.value === '' || !multiplier.validity.valid) return;
        binding.multiplier = Number(multiplier.value);
        for (const [index, key] of ['base_input', 'base_output', 'base_cache'].entries()) {
          controls[index + 2].value = Number((binding[key] * binding.multiplier).toFixed(6)).toString();
        }
        label.textContent = `来源：${binding.source_name} · 倍率 ${binding.multiplier}`;
        update();
      };
      const apply = (entry, ratio = 1, currency = 'USD') => {
        row.binding = {
          source_provider: entry.provider, source_model: entry.model, source_name: entry.name,
          base_currency: 'USD', base_input: entry.input, base_output: entry.output, base_cache: entry.cache,
          multiplier: ratio,
        };
        controls[1].value = currency;
        render();
        recalculate();
      };
      const pick = button('选择模型', () => {
        const provider = data.providers.find(item => item.id === controls[0].value);
        priceCatalog.pick(provider?.model || '', apply);
      });
      const refresh = button('应用最新价', () => {
        const { source_provider, source_model, multiplier } = row.binding;
        const entry = priceCatalog.models().find(model => model.provider === source_provider && model.model === source_model);
        if (entry) apply(entry, multiplier, controls[1].value);
        else label.textContent = '缓存中找不到该模型，当前单价已保留。';
      });
      function render() {
        const binding = row.binding;
        pick.disabled = !controls[0].value;
        label.textContent = binding ? `来源：${binding.source_name} · 倍率 ${binding.multiplier}` : '自定义';
        multiplier.hidden = refresh.hidden = !binding;
        multiplier.disabled = !binding;
        multiplier.value = binding?.multiplier ?? '';
      }
      controls[0].oninput = () => { row.binding = undefined; render(); update(); };
      controls.slice(2).forEach(control => { control.oninput = () => { row.binding = undefined; render(); update(); }; });
      multiplier.oninput = recalculate;
      const sourceActions = node('div', null, 'actions');
      sourceActions.append(pick, refresh);
      sources.append(label, multiplier, sourceActions);
      wrapper.append(sources);
      render();
    }
    wrapper.append(button('移除', () => { rows.splice(rows.indexOf(row), 1); wrapper.remove(); update(); }, 'quiet'));
    rowBody.append(wrapper);
  }
  for (const line of field.value.split(/\r?\n/).filter(Boolean)) {
    const [key, value = ''] = line.split('=', 2);
    add([key, ...(type === 'routes' ? value.split(':GroupMessage:') : value.split(':'))]);
  }
  const footer = node('div', null, 'actions');
  footer.append(button('添加一行', () => { add([]); update(); }));
  if (type === 'routes') {
    const refresh = button('读取实例', async () => {
      refresh.disabled = true;
      try {
        servers = (await fetchServers()).items.filter(item => item.selectable).map(item => [item.instance, item.instance]);
        for (const { controls: [control] } of rows) options(control, [['', '实例'], ...withCurrent(servers, control.value)]);
        refresh.textContent = '刷新实例';
      } catch (error) { refresh.textContent = `读取实例失败：${error.message}`; }
      finally { refresh.disabled = false; }
    });
    footer.append(refresh);
    const allowed = field.form.elements.group_ids;
    const populate = () => group.replaceChildren(...allowed.value.split(/\s+/).filter(Boolean).map(id => new Option(id, id)));
    table.onfocusin = populate;
    populate();
    table.append(group);
  }
  table.append(rowBody, footer);
  label.append(table);
  if (type === 'prices') return () => Object.fromEntries(rows
    .filter(row => row.controls[0].value && row.binding)
    .map(row => [row.controls[0].value, row.binding]));
}

export function setupEditors(root, data, fetchServers, priceCatalog) {
  for (const textarea of root.querySelectorAll('textarea[name="admin_ids"], textarea[name="group_ids"], textarea[data-key="test_copy_paths"]')) {
    if (textarea.hidden) textarea.dispatchEvent(new Event('input'));
    else tagEditor(textarea);
  }
  if (!data) return;
  let priceBindings;
  for (const [name, type] of [['incident_routes', 'routes'], ['model_prices', 'prices']]) {
    const field = root.elements[name];
    field.parentNode.querySelector('.editor-table')?.remove();
    const read = rowEditor(field, type, data, fetchServers, priceCatalog);
    if (type === 'prices') priceBindings = read;
  }
  return priceBindings;
}
