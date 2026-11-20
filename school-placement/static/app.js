'use strict';

const STORAGE_KEY = 'school-placement.scenarios.v1';
const PAGE_SIZE = 50;
const MODES = ['baseline', 'scenario', 'change'];

const $ = (id) => document.getElementById(id);

const el = {
  loading: $('loading'),
  topbarMeta: $('topbar-meta'),
  selectedBadge: $('selected-badge'),
  selectedContent: $('selected-content'),
  placementsCount: $('placements-count'),
  manualBlock: $('manual-block'),
  manualCapacity: $('manual-capacity'),
  addSchool: $('add-school'),
  placementsList: $('placements-list'),
  calculateScenario: $('calculate-scenario'),
  resetScenario: $('reset-scenario'),
  manualStatus: $('manual-status'),
  autoCapacity: $('auto-capacity'),
  autoStart: $('auto-start'),
  autoProgress: $('auto-progress'),
  autoProgressBar: $('auto-progress-bar'),
  autoProgressText: $('auto-progress-text'),
  autoCancel: $('auto-cancel'),
  autoResult: $('auto-result'),
  autoBestCount: $('auto-best-count'),
  experimentButtons: $('experiment-buttons'),
  saveName: $('save-name'),
  saveScenario: $('save-scenario'),
  savedScenarios: $('saved-scenarios'),
  kpis: $('kpis'),
  modeButtons: $('mode-buttons'),
  legend: $('legend'),
  blocksTable: $('blocks-table'),
  blocksTableBody: $('blocks-table-body'),
  tableSubtitle: $('table-subtitle'),
  tableSearch: $('table-search'),
  exportCsv: $('export-csv'),
  blocksPagination: $('blocks-pagination'),
  autoTableCard: $('auto-table-card'),
  autoTable: $('auto-table'),
  autoTableBody: $('auto-table-body'),
  autoTableSubtitle: $('auto-table-subtitle'),
  autoTableSearch: $('auto-table-search'),
  comparisonTableBody: $('comparison-table-body'),
  toast: $('toast'),
  map: $('map'),
};

const state = {
  meta: null,
  geojson: null,
  featuresById: new Map(),
  baselineRows: [],
  baselineById: new Map(),
  rows: [],
  rowsById: new Map(),
  populationTotal: 0,
  scenarios: {},
  scenario: null,
  scenarioLabel: '',
  manualPlacements: [],
  selectedId: null,
  mode: 'baseline',
  sortKey: 'population',
  sortDir: 'desc',
  page: 1,
  tableFilter: '',
  auto: null,
  autoRunning: false,
  autoSortKey: 'rank',
  autoSortDir: 'asc',
  autoFilter: '',
  autoJobId: null,
  autoTimer: null,
  saved: [],
  toastTimer: null,
  mapInstance: null,
  geoLayer: null,
  layersById: new Map(),
  centers: new Map(),
  selectionLayer: null,
  schoolLayer: null,
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => {
    const replacements = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    };
    return replacements[character];
  });
}

function numOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, digits = 0) {
  const number = numOrNull(value);
  if (number === null) return '—';
  const formatter = new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
  return formatter.format(Math.abs(number) < 10 ** (-digits) / 2 ? 0 : number);
}

function formatPercent(value) {
  const number = numOrNull(value);
  if (number === null) return '—';
  return `${formatNumber(number * 100, 1)}%`;
}

function formatChange(value) {
  const number = numOrNull(value);
  if (number === null) return '—';
  const points = number * 100;
  if (Math.abs(points) < 0.05) return '0,0 п.п.';
  return `${points > 0 ? '+' : '−'}${formatNumber(Math.abs(points), 1)} п.п.`;
}

function signedNumber(value, digits = 0) {
  const number = numOrNull(value);
  if (number === null) return '—';
  if (Math.abs(number) < 10 ** (-digits) / 2) return formatNumber(0, digits);
  return `${number > 0 ? '+' : '−'}${formatNumber(Math.abs(number), digits)}`;
}

function candidateCount() {
  return Number(state.meta?.display_block_count) || Number(state.meta?.block_count) || 0;
}

function pluralSchools(count) {
  const lastTwo = count % 100;
  const last = count % 10;
  if (last === 1 && lastTwo !== 11) return 'школа';
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return 'школы';
  return 'школ';
}

function baselineRow(properties) {
  const baselineCapacity = numOrNull(properties.baseline_capacity) ?? 0;
  const baselineProvision = numOrNull(properties.baseline_provision);
  const baselineDeficit = numOrNull(properties.baseline_deficit) ?? 0;
  return {
    block_id: Number(properties.block_id),
    population: numOrNull(properties.population) ?? 0,
    baseline_capacity: baselineCapacity,
    baseline_provision: baselineProvision,
    baseline_deficit: baselineDeficit,
    land_use: properties.land_use || 'не определено',
    morphotype: properties.morphotype || 'не определено',
    area_ha: numOrNull(properties.area_ha),
    scenario_capacity: baselineCapacity,
    added_capacity: 0,
    scenario_provision: baselineProvision,
    provision_change: baselineProvision === null ? null : 0,
    scenario_deficit: baselineDeficit,
    deficit_reduction: baselineDeficit === null ? null : 0,
  };
}

function reindexRows() {
  state.rowsById = new Map(state.rows.map((row) => [row.block_id, row]));
}

function resetRows() {
  state.rows = state.baselineRows.map((row) => baselineRow(row));
  reindexRows();
}

function applyScenarioRows(blocks) {
  const scenarioById = new Map(blocks.map((row) => [Number(row.block_id), row]));
  state.rows = state.baselineRows.map((base) => {
    const scenario = scenarioById.get(base.block_id);
    if (!scenario) return baselineRow(base);
    return {
      ...base,
      ...scenario,
      block_id: base.block_id,
      population: numOrNull(scenario.population) ?? base.population,
      baseline_capacity: numOrNull(scenario.baseline_capacity) ?? base.baseline_capacity,
      scenario_capacity: numOrNull(scenario.scenario_capacity) ?? base.baseline_capacity,
      added_capacity: numOrNull(scenario.added_capacity) ?? 0,
      baseline_provision: numOrNull(scenario.baseline_provision),
      scenario_provision: numOrNull(scenario.scenario_provision),
      provision_change: numOrNull(scenario.provision_change),
      baseline_deficit: numOrNull(scenario.baseline_deficit),
      scenario_deficit: numOrNull(scenario.scenario_deficit),
      deficit_reduction: numOrNull(scenario.deficit_reduction),
      land_use: scenario.land_use || base.land_use,
      morphotype: scenario.morphotype || base.morphotype,
      area_ha: base.area_ha,
    };
  });
  reindexRows();
}

function currentSummary() {
  return state.scenario ? state.scenario.summary : state.meta.baseline;
}

function updateTopbar() {
  const verification = state.meta.verification || {};
  const verificationText = verification.ok ? 'baseline проверен' : 'baseline не проверен';
  el.topbarMeta.innerHTML = [
    `${escapeHtml(state.meta.city)} · ${formatNumber(state.meta.block_count)} кварталов · жилых для размещения: ${formatNumber(state.meta.display_block_count)} · ${verificationText}`,
    `${escapeHtml(state.meta.source)} · ${escapeHtml(state.meta.method)}`,
  ].join('<br>');
}

function renderKpis() {
  const baseline = state.meta.baseline;
  const active = state.mode === 'baseline' ? baseline : currentSummary();
  const cards = [
    {
      label: 'Кварталов в расчёте',
      value: formatNumber(active.blocks),
      sub: `жилых для размещения: ${formatNumber(state.meta.display_block_count)}`,
      className: '',
    },
    {
      label: 'Население',
      value: formatNumber(state.populationTotal),
      sub: `спрос: ${formatNumber(active.demand)} мест`,
      className: '',
    },
    {
      label: 'Вместимость',
      value: formatNumber(active.capacity),
      sub: active.added_capacity > 0
        ? `+${formatNumber(active.added_capacity)} к исходной`
        : 'исходная',
      className: 'accent',
    },
    {
      label: 'Дефицит',
      value: formatNumber(active.deficit),
      sub: active.deficit_reduction > 0
        ? `−${formatNumber(active.deficit_reduction)} к исходному`
        : 'исходный',
      className: 'bad',
    },
    {
      label: 'Обеспеченность',
      value: formatPercent(active.provision),
      sub: active.provision_change > 0
        ? `+${formatNumber(active.provision_change * 100, 1)} п.п.`
        : 'исходная',
      className: 'good',
    },
  ];
  el.kpis.innerHTML = cards
    .map(
      (card) => `
      <div class="kpi ${card.className}">
        <div class="label">${card.label}</div>
        <div class="value">${card.value}</div>
        <div class="sub">${card.sub}</div>
      </div>`,
    )
    .join('');
}

function selectedStat(label, value) {
  return `<div class="selected-stat"><span>${label}</span><strong>${value}</strong></div>`;
}

function renderSelected() {
  const row = state.selectedId === null ? null : state.rowsById.get(state.selectedId);
  if (!row) {
    el.selectedBadge.textContent = 'не выбран';
    el.selectedBadge.classList.add('muted');
    el.selectedContent.innerHTML = '<p class="muted small">Выберите квартал для размещения в ручном сценарии, на карте или в таблице.</p>';
    return;
  }
  el.selectedBadge.textContent = `квартал ${row.block_id}`;
  el.selectedBadge.classList.remove('muted');
  el.selectedContent.innerHTML = `
    <div class="selected-title">
      <h3>Квартал ${row.block_id}</h3>
      <span class="land-use" title="Тип использования: ${escapeHtml(row.land_use)}">жилой</span>
    </div>
    <div class="selected-grid">
      ${selectedStat('Население', `${formatNumber(row.population)} чел.`)}
      ${selectedStat('Площадь', row.area_ha === null ? '—' : `${formatNumber(row.area_ha, 2)} га`)}
      ${selectedStat('Вместимость исходная', formatNumber(row.baseline_capacity))}
      ${selectedStat('Вместимость сценария', formatNumber(row.scenario_capacity))}
      ${selectedStat('Обеспеченность исходная', formatPercent(row.baseline_provision))}
      ${selectedStat('Обеспеченность сценария', formatPercent(row.scenario_provision))}
      ${selectedStat('Дефицит исходный', formatNumber(row.baseline_deficit, 1))}
      ${selectedStat('Дефицит сценария', formatNumber(row.scenario_deficit, 1))}
      ${selectedStat('Δ обеспеченности', formatChange(row.provision_change))}
      ${selectedStat('Сокращение дефицита в квартале', signedNumber(row.deficit_reduction, 1))}
    </div>
    <p class="muted small" style="margin: 8px 0 0">Морфотип: ${escapeHtml(row.morphotype)}</p>
  `;
}

function renderPlacements() {
  const count = state.manualPlacements.length;
  el.placementsCount.textContent = `${count} ${pluralSchools(count)}`;
  el.addSchool.disabled = state.selectedId === null;
  if (!count) {
    el.placementsList.innerHTML = '<div class="placements-empty">Школы не добавлены. Пустой сценарий совпадает с исходным состоянием.</div>';
    return;
  }
  const sorted = state.manualPlacements.slice().sort((a, b) => a.block_id - b.block_id);
  el.placementsList.innerHTML = sorted
    .map((placement) => `
      <div class="placement-item">
        <span>Квартал <strong>${placement.block_id}</strong> — ${formatNumber(placement.capacity)} мест</span>
        <button type="button" data-remove-block="${placement.block_id}" title="Удалить школу">×</button>
      </div>`)
    .join('');
}

function setManualStatus(text, kind = '') {
  el.manualStatus.textContent = text;
  el.manualStatus.className = `status-text ${kind}`.trim();
}

function markScenarioStale() {
  if (state.scenario) {
    setManualStatus('Размещения изменены. Нажмите «Рассчитать сценарий», чтобы обновить результат.', 'error');
  } else {
    setManualStatus('Размещения изменены. Нажмите «Рассчитать сценарий».', '');
  }
}

function compareValues(left, right, direction) {
  const leftNull = left === null || left === undefined || (typeof left === 'number' && !Number.isFinite(left));
  const rightNull = right === null || right === undefined || (typeof right === 'number' && !Number.isFinite(right));
  if (leftNull && rightNull) return 0;
  if (leftNull) return 1;
  if (rightNull) return -1;
  let comparison = 0;
  if (typeof left === 'string' || typeof right === 'string') {
    comparison = String(left).localeCompare(String(right), 'ru');
  } else {
    comparison = Number(left) - Number(right);
  }
  return direction === 'asc' ? comparison : -comparison;
}

function populateBlockSelect(preferredId = state.selectedId) {
  const rows = state.rows
    .slice()
    .sort((left, right) => (
      (right.population ?? 0) - (left.population ?? 0) || left.block_id - right.block_id
    ));
  const options = ['<option value="">Выберите квартал</option>'];
  for (const row of rows) {
    options.push(
      `<option value="${row.block_id}">Квартал ${row.block_id} · ${formatNumber(row.population)} чел. · дефицит ${formatNumber(row.baseline_deficit, 1)}</option>`,
    );
  }
  el.manualBlock.innerHTML = options.join('');
  const preferred = preferredId === null ? '' : String(preferredId);
  el.manualBlock.value = rows.some((row) => String(row.block_id) === preferred) ? preferred : '';
  el.addSchool.disabled = el.manualBlock.value === '';
}

function filteredBlockRows() {
  const filter = state.tableFilter.trim().toLowerCase();
  let rows = state.rows.filter((row) => {
    if (!filter) return true;
    return (
      String(row.block_id).includes(filter) ||
      String(row.land_use).toLowerCase().includes(filter) ||
      String(row.morphotype).toLowerCase().includes(filter)
    );
  });
  rows = rows.slice().sort((left, right) => compareValues(left[state.sortKey], right[state.sortKey], state.sortDir));
  return rows;
}

function paginationHtml(start, end, total, pages) {
  if (!total) {
    return '<span>Показано 0 из 0</span><button disabled>‹</button><button disabled>›</button>';
  }
  const pageButtons = [];
  for (let page = 1; page <= pages; page += 1) {
    pageButtons.push(
      `<button type="button" data-page="${page}" class="${page === state.page ? 'active' : ''}">${page}</button>`,
    );
  }
  return [
    `<span>Показано ${start + 1}–${end} из ${total}</span>`,
    `<button type="button" data-page="${state.page - 1}" ${state.page === 1 ? 'disabled' : ''}>‹</button>`,
    pageButtons.join(''),
    `<button type="button" data-page="${state.page + 1}" ${state.page === pages ? 'disabled' : ''}>›</button>`,
  ].join('');
}

function renderTable() {
  const rows = filteredBlockRows();
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  state.page = Math.min(Math.max(1, state.page), totalPages);
  const start = (state.page - 1) * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, rows.length);
  const pageRows = rows.slice(start, end);

  if (!pageRows.length) {
    el.blocksTableBody.innerHTML = '<tr><td colspan="8" class="muted">Ничего не найдено. Измените поисковый запрос.</td></tr>';
  } else {
    el.blocksTableBody.innerHTML = pageRows
      .map((row) => {
        const selectedClass = row.block_id === state.selectedId ? 'selected' : '';
        const addedClass = row.added_capacity > 0 ? 'num-good' : '';
        const changeClass = (row.provision_change ?? 0) > 0 ? 'num-good' : '';
        const reductionClass = (row.deficit_reduction ?? 0) > 0 ? 'num-good' : '';
        const deficitClass = (row.scenario_deficit ?? 0) > 0 ? 'num-bad' : '';
        return `
          <tr data-block-id="${row.block_id}" class="${selectedClass}">
            <td>${row.block_id}</td>
            <td>${formatNumber(row.population)}</td>
            <td>${formatNumber(row.baseline_capacity)} → ${formatNumber(row.scenario_capacity)}</td>
            <td class="${addedClass}">${signedNumber(row.added_capacity)}</td>
            <td>${formatPercent(row.baseline_provision)} → ${formatPercent(row.scenario_provision)}</td>
            <td class="${changeClass}">${formatChange(row.provision_change)}</td>
            <td class="${deficitClass}">${formatNumber(row.baseline_deficit, 1)} → ${formatNumber(row.scenario_deficit, 1)}</td>
            <td class="${reductionClass}">${signedNumber(row.deficit_reduction, 1)}</td>
          </tr>`;
      })
      .join('');
  }

  const label = state.scenario
    ? `Сценарий: ${state.scenarioLabel || 'текущий'}`
    : 'Исходное состояние';
  const filterText = state.tableFilter.trim() ? ` · поиск «${state.tableFilter.trim()}»` : '';
  const sortHeader = el.blocksTable.querySelector(`th[data-sort="${state.sortKey}"]`);
  const sortLabel = sortHeader
    ? (sortHeader.dataset.label || sortHeader.textContent.replace(/\s+/g, ' ').trim())
    : state.sortKey;
  const sortText = `сортировка: ${sortLabel} ${state.sortDir === 'asc' ? '↑' : '↓'}`;
  el.tableSubtitle.textContent = `${label} · только жилые кварталы${filterText} · ${sortText} · показано ${start + (pageRows.length ? 1 : 0)}–${end} из ${rows.length}`;
  el.blocksPagination.innerHTML = paginationHtml(start, end, rows.length, totalPages);
  updateSortHeaders();
}

function updateSortHeaders() {
  el.blocksTable.querySelectorAll('th[data-sort]').forEach((header) => {
    header.classList.toggle('sort-asc', header.dataset.sort === state.sortKey && state.sortDir === 'asc');
    header.classList.toggle('sort-desc', header.dataset.sort === state.sortKey && state.sortDir === 'desc');
  });
}

function autoBestSet() {
  return new Set((state.auto?.best || []).map(Number));
}

function filteredAutoRows() {
  if (!state.auto || !Array.isArray(state.auto.rows)) return [];
  const bestSet = autoBestSet();
  const filter = state.autoFilter.trim().toLowerCase();
  const rows = state.auto.rows
    .map((row, index) => ({ ...row, rank: index + 1, is_best: bestSet.has(Number(row.block_id)) }))
    .filter((row) => !filter || String(row.block_id).includes(filter));
  rows.sort((left, right) => {
    if (state.autoSortKey === 'rank') {
      return compareValues(left.rank, right.rank, state.autoSortDir);
    }
    if (state.autoSortKey === 'block_id') {
      return compareValues(left.block_id, right.block_id, state.autoSortDir);
    }
    return compareValues(left[state.autoSortKey], right[state.autoSortKey], state.autoSortDir);
  });
  return rows;
}

function autoSubtitle() {
  if (!state.auto) return 'Запустите подбор, чтобы увидеть все жилые кварталы.';
  if (state.auto.status === 'running') {
    return `Подбор выполняется: проверено ${formatNumber(state.auto.checked)} из ${formatNumber(state.auto.total)} жилых кварталов.`;
  }
  if (state.auto.status === 'error') return `Ошибка: ${state.auto.error || 'не удалось выполнить подбор'}`;
  const parts = [
    `Проверено ${formatNumber(state.auto.checked)} из ${formatNumber(state.auto.total)} жилых кварталов`,
  ];
  if (state.auto.best_reduction !== null && state.auto.best_reduction !== undefined) {
    parts.push(`лучшее сокращение — ${formatNumber(state.auto.best_reduction)} мест`);
  }
  if (state.auto.best?.length) {
    parts.push(`равнозначных лучших — ${formatNumber(state.auto.best.length)}`);
  }
  if (state.auto.errors?.length) {
    parts.push(`ошибок — ${formatNumber(state.auto.errors.length)}`);
  }
  if (state.auto.status === 'cancelled') {
    parts.push('подбор остановлен');
  }
  return `${parts.join('; ')}.`;
}

function renderAutoTable() {
  el.autoTableSubtitle.textContent = autoSubtitle();
  const rows = filteredAutoRows();
  if (!rows.length) {
    const message = !state.auto
      ? 'Запустите автоматический подбор, чтобы увидеть все жилые кварталы.'
      : state.auto.status === 'running'
        ? 'Подбор выполняется. Таблица заполнится после завершения.'
        : state.auto.status === 'error'
          ? 'Подбор завершился ошибкой. Проверьте сообщение в боковой панели.'
          : 'Нет вариантов для отображения.';
    el.autoTableBody.innerHTML = `<tr><td colspan="11" class="muted">${escapeHtml(message)}</td></tr>`;
    return;
  }

  const recommendedId = Number(state.auto?.recommended ?? state.auto?.best?.[0]);
  el.autoTableBody.innerHTML = rows
    .map((row) => {
      const isRecommended = row.is_best && Number(row.block_id) === recommendedId;
      const bestClass = isRecommended ? 'best-row' : '';
      const bestBadge = isRecommended
        ? ' <span class="badge">рекомендуемый</span>'
        : row.is_best
          ? ' <span class="badge muted">равнозначный</span>'
          : '';
      return `
        <tr data-block-id="${row.block_id}" class="${bestClass}">
          <td>${row.rank}</td>
          <td>${row.block_id}${bestBadge}</td>
          <td>${formatNumber(row.population)}</td>
          <td>${formatNumber(row.baseline_capacity)}</td>
          <td>${formatNumber(row.scenario_capacity)}</td>
          <td>${formatNumber(row.deficit, 1)}</td>
          <td class="num-good">${signedNumber(row.deficit_reduction, 1)}</td>
          <td>${formatPercent(row.provision)}</td>
          <td>${formatNumber(row.blocks_improved)}</td>
          <td>${formatNumber(row.blocks_with_deficit)}</td>
          <td><button type="button" class="button secondary small" data-apply-auto="${row.block_id}">Применить</button></td>
        </tr>`;
    })
    .join('');
}

function renderAutoResult() {
  const auto = state.auto;
  if (!auto) {
    el.autoBestCount.textContent = '';
    el.autoResult.innerHTML = '<p class="muted small">Автоподбор ещё не запускался.</p>';
    return;
  }
  if (auto.status === 'running') {
    el.autoBestCount.textContent = 'идёт';
    el.autoResult.innerHTML = `<p class="status-text">Проверено ${formatNumber(auto.checked)} из ${formatNumber(auto.total)} жилых кварталов…</p>`;
    return;
  }
  if (auto.status === 'error') {
    el.autoBestCount.textContent = 'ошибка';
    el.autoResult.innerHTML = `<p class="status-text error">${escapeHtml(auto.error || 'Не удалось выполнить автоподбор')}</p>`;
    return;
  }

  const best = auto.best || [];
  const recommended = Number(auto.recommended ?? best[0]);
  const hasRecommended = Number.isFinite(recommended) && best.includes(recommended);
  el.autoBestCount.textContent = best.length ? `равнозначных: ${formatNumber(best.length)}` : '';
  const errorsText = auto.errors?.length
    ? `<br><span class="status-text error">Ошибок: ${formatNumber(auto.errors.length)}. Показан частичный результат.</span>`
    : '';
  const cancelledText = auto.status === 'cancelled'
    ? '<br><span class="status-text error">Подбор остановлен; показаны завершённые варианты.</span>'
    : '';
  const bestChips = best
    .map((blockId) => {
      const recommendedClass = Number(blockId) === recommended ? ' recommended' : '';
      return `<button type="button" class="best-chip${recommendedClass}" data-best-block="${blockId}" title="Применить квартал ${blockId}">${blockId}</button>`;
    })
    .join('');
  const bestButton = hasRecommended
    ? `<button type="button" class="button secondary wide" data-best-block="${recommended}">Применить рекомендуемый квартал ${recommended}</button>`
    : '';
  el.autoResult.innerHTML = `
    <div class="auto-summary">
      <strong>Лучшее сокращение: ${formatNumber(auto.best_reduction)} мест.</strong><br>
      Проверено ${formatNumber(auto.checked)} из ${formatNumber(auto.total)} жилых кварталов.
      Равнозначных лучших: ${formatNumber(best.length)}.${errorsText}${cancelledText}
      <br><span class="muted">Критерий: суммарный дефицит после добавления одной школы. На карту применяется один рекомендуемый участок; остальные равнозначные варианты показаны в таблице.</span>
    </div>
    ${best.length ? `<div class="best-list">${bestChips}</div>` : ''}
    ${best.length ? '<p class="muted small">Нажмите номер квартала, чтобы применить только его.</p>' : ''}
    ${bestButton}
    <button type="button" class="button ghost wide" data-scroll-auto>Показать все варианты в таблице</button>
  `;
}

function renderExperimentButtons() {
  const entries = Object.entries(state.scenarios);
  if (!entries.length) {
    el.experimentButtons.innerHTML = '<p class="muted small">Сценарии не загружены.</p>';
    return;
  }
  el.experimentButtons.innerHTML = entries
    .map(
      ([key, definition]) => `
        <button type="button" class="experiment-button" data-scenario="${key}">
          <strong>${escapeHtml(definition.name)}</strong>
          <span>${escapeHtml(definition.description)}</span>
        </button>`,
    )
    .join('');
}

function formatPlacements(placements) {
  if (!Array.isArray(placements) || !placements.length) return '—';
  return placements
    .slice()
    .sort((left, right) => Number(left.block_id) - Number(right.block_id))
    .map((placement) => `Кв. ${placement.block_id} — ${formatNumber(placement.capacity)}`)
    .join('; ');
}

function comparisonRow(name, placements, summary, actions) {
  return `
    <tr>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(typeof placements === 'string' ? placements : formatPlacements(placements))}</td>
      <td>${formatNumber(summary?.added_capacity ?? 0)}</td>
      <td>${formatNumber(summary?.deficit)}</td>
      <td>${signedNumber(summary?.deficit_reduction)}</td>
      <td>${formatPercent(summary?.provision)}</td>
      <td>${actions}</td>
    </tr>`;
}

function renderComparison() {
  const rows = [
    comparisonRow('Исходное состояние', '—', state.meta.baseline, '<span class="muted">—</span>'),
  ];
  if (state.scenario) {
    rows.push(
      comparisonRow(
        state.scenarioLabel || 'Текущий сценарий',
        state.scenario.placements,
        state.scenario.summary,
        '<button type="button" class="button secondary small" data-action="save-current">Сохранить</button>',
      ),
    );
  }
  for (const saved of state.saved) {
    rows.push(
      comparisonRow(
        saved.name,
        saved.placements,
        saved.summary,
        [
          `<button type="button" class="button secondary small" data-action="load-saved" data-saved-id="${escapeHtml(saved.id)}">Загрузить</button>`,
          `<button type="button" class="button ghost small" data-action="delete-saved" data-saved-id="${escapeHtml(saved.id)}">Удалить</button>`,
        ].join(' '),
      ),
    );
  }
  el.comparisonTableBody.innerHTML = rows.join('');
}

function renderSaved() {
  if (!state.saved.length) {
    el.savedScenarios.innerHTML = '<p class="saved-empty">История пуста. Рассчитайте сценарий и сохраните его.</p>';
    return;
  }
  el.savedScenarios.innerHTML = state.saved
    .map(
      (saved) => `
        <div class="saved-scenario">
          <div class="saved-scenario-head">
            <strong>${escapeHtml(saved.name)}</strong>
            <span class="muted small">${formatPercent(saved.summary?.provision)}</span>
          </div>
          <p>${escapeHtml(formatPlacements(saved.placements))} · сокращение ${formatNumber(saved.summary?.deficit_reduction)} мест</p>
          <div class="saved-actions">
            <button type="button" class="button secondary small" data-action="load-saved" data-saved-id="${escapeHtml(saved.id)}">Загрузить</button>
            <button type="button" class="button ghost small" data-action="delete-saved" data-saved-id="${escapeHtml(saved.id)}">Удалить</button>
          </div>
        </div>`,
    )
    .join('');
}

function legendItem(color, label) {
  return `<span class="legend-item"><i class="legend-swatch" style="background:${color}"></i>${label}</span>`;
}

function renderLegend() {
  const schoolItem = state.scenario
    ? '<span class="legend-item"><i class="legend-school"></i>новая школа</span>'
    : '';
  if (state.mode === 'change') {
    el.legend.innerHTML = [
      '<span class="legend-title">Изменение в кварталах школ</span>',
      legendItem('#cfd8e3', 'без изменений'),
      legendItem('#e9a19a', 'снижение'),
      legendItem('#d9f0e3', '< 5 п.п.'),
      legendItem('#9dd9b5', '5–15 п.п.'),
      legendItem('#4caf7d', '15–30 п.п.'),
      legendItem('#15803d', '≥ 30 п.п.'),
      schoolItem,
      '<span class="legend-note">закрашены только кварталы с новыми школами</span>',
    ].join('');
    return;
  }
  el.legend.innerHTML = [
    '<span class="legend-title">Обеспеченность школами</span>',
    legendItem('#b42318', '0–15%'),
    legendItem('#d97706', '15–35%'),
    legendItem('#eab308', '35–60%'),
    legendItem('#65a30d', '60–85%'),
    legendItem('#15803d', '85–100%'),
    legendItem('#c9d2dc', 'нет спроса'),
    schoolItem,
  ].join('');
}

function colorForProvision(value) {
  if (value === null || value === undefined) return '#c9d2dc';
  if (value <= 0.15) return '#b42318';
  if (value <= 0.35) return '#d97706';
  if (value <= 0.6) return '#eab308';
  if (value <= 0.85) return '#65a30d';
  return '#15803d';
}

function styleForFeature(feature) {
  const blockId = Number(feature.properties.block_id);
  const row = state.rowsById.get(blockId);
  if (!row) {
    return { color: '#ffffff', weight: 0.6, fillColor: '#c9d2dc', fillOpacity: 0.7 };
  }
  if (state.mode === 'change' && !(row.added_capacity > 0)) {
    return {
      color: '#d8e0e8',
      weight: 0.4,
      fillColor: '#eef2f6',
      fillOpacity: 0.08,
    };
  }
  let color;
  if (state.mode === 'change') {
    const change = row.provision_change;
    if (change === null || change === undefined || Math.abs(change) < 0.005) {
      color = '#cfd8e3';
    } else if (change < 0) {
      color = '#e9a19a';
    } else if (change < 0.05) {
      color = '#d9f0e3';
    } else if (change < 0.15) {
      color = '#9dd9b5';
    } else if (change < 0.3) {
      color = '#4caf7d';
    } else {
      color = '#15803d';
    }
  } else {
    const provision = state.mode === 'baseline' ? row.baseline_provision : row.scenario_provision;
    color = row.population > 0 ? colorForProvision(provision) : '#c9d2dc';
  }
  return { color: '#ffffff', weight: 0.6, fillColor: color, fillOpacity: 0.78 };
}

function tooltipHtml(blockId) {
  const row = state.rowsById.get(blockId);
  if (!row) return `Квартал ${blockId}`;
  const lines = [
    `<strong>Квартал ${blockId}</strong>`,
    'Жилой квартал для размещения',
    `Население: ${formatNumber(row.population)} чел.`,
  ];
  if (state.scenario) {
    lines.push(`Исходно: ${formatPercent(row.baseline_provision)} · дефицит ${formatNumber(row.baseline_deficit, 1)}`);
    lines.push(`Сценарий: ${formatPercent(row.scenario_provision)} · дефицит ${formatNumber(row.scenario_deficit, 1)}`);
    if (row.added_capacity > 0) {
      lines.push(`Новая школа: +${formatNumber(row.added_capacity)} мест`);
    } else if ((row.provision_change ?? 0) > 0) {
      lines.push(`Влияние соседней школы: ${formatChange(row.provision_change)}`);
    }
  } else {
    lines.push(`Обеспеченность: ${formatPercent(row.baseline_provision)}`);
    lines.push(`Дефицит: ${formatNumber(row.baseline_deficit, 1)} мест`);
  }
  return lines.join('<br>');
}

function updateModeButtons() {
  el.modeButtons.querySelectorAll('button[data-mode]').forEach((button) => {
    button.classList.toggle('active', button.dataset.mode === state.mode);
  });
}

function updateSelectionLayer() {
  if (!state.selectionLayer) return;
  state.selectionLayer.clearLayers();
  if (state.selectedId === null) return;
  const feature = state.featuresById.get(state.selectedId);
  if (!feature) return;
  L.geoJSON(feature, {
    style: {
      color: '#0b2d44',
      weight: 3,
      fillColor: '#0b2d44',
      fillOpacity: 0.06,
      dashArray: '6 4',
    },
    interactive: false,
  }).addTo(state.selectionLayer);
}

function updateSchoolMarkers() {
  if (!state.schoolLayer) return;
  state.schoolLayer.clearLayers();
  if (!state.scenario) return;
  for (const placement of state.scenario.placements || []) {
    const center = state.centers.get(Number(placement.block_id));
    if (!center) continue;
    L.circleMarker(center, {
      radius: 7,
      color: '#ffffff',
      weight: 2,
      fillColor: '#143f5e',
      fillOpacity: 1,
    })
      .bindTooltip(
        `Новая школа: квартал ${placement.block_id}, ${formatNumber(placement.capacity)} мест`,
        { direction: 'top' },
      )
      .addTo(state.schoolLayer);
  }
}

function refreshMap() {
  if (!state.geoLayer) return;
  state.geoLayer.eachLayer((layer) => {
    layer.setStyle(styleForFeature(layer.feature));
    const blockId = Number(layer.feature.properties.block_id);
    layer.setTooltipContent(tooltipHtml(blockId));
  });
  updateSelectionLayer();
  updateSchoolMarkers();
  renderLegend();
}

function setMode(mode) {
  if (!MODES.includes(mode)) return;
  if (mode === 'change' && !state.scenario) {
    showToast('Сначала рассчитайте сценарий, чтобы увидеть изменение.', 'error');
    return;
  }
  state.mode = mode;
  updateModeButtons();
  renderKpis();
  refreshMap();
}

function pageForBlock(blockId) {
  const rows = filteredBlockRows();
  const index = rows.findIndex((row) => row.block_id === blockId);
  if (index < 0) return null;
  return Math.floor(index / PAGE_SIZE) + 1;
}

function selectBlock(blockId, { fromMap = false, focusTable = false } = {}) {
  const row = state.rowsById.get(blockId);
  if (!row) return;
  state.selectedId = blockId;
  populateBlockSelect(blockId);
  if (focusTable) {
    const page = pageForBlock(blockId);
    if (page !== null) state.page = page;
  }
  renderSelected();
  renderPlacements();
  renderTable();
  refreshMap();
  if (fromMap) {
    const layer = state.layersById.get(blockId);
    if (layer) layer.openTooltip();
  }
}

function initMap() {
  state.mapInstance = L.map('map', {
    preferCanvas: true,
    zoomControl: true,
    minZoom: 10,
  }).setView([60.93, 76.57], 12);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(state.mapInstance);

  state.selectionLayer = L.layerGroup().addTo(state.mapInstance);
  state.schoolLayer = L.layerGroup().addTo(state.mapInstance);

  state.geoLayer = L.geoJSON(state.geojson, {
    style: styleForFeature,
    onEachFeature: (feature, layer) => {
      const blockId = Number(feature.properties.block_id);
      state.layersById.set(blockId, layer);
      state.centers.set(blockId, layer.getBounds().getCenter());
      layer.bindTooltip(tooltipHtml(blockId), {
        sticky: true,
        direction: 'top',
        className: 'map-popup',
      });
      layer.on({
        mouseover: (event) => {
          event.target.setStyle({ weight: 2, color: '#143f5e' });
        },
        mouseout: (event) => {
          event.target.setStyle(styleForFeature(event.target.feature));
        },
        click: () => {
          selectBlock(blockId, { fromMap: true });
        },
      });
    },
  }).addTo(state.mapInstance);

  const bounds = state.geoLayer.getBounds();
  if (bounds.isValid()) {
    state.mapInstance.fitBounds(bounds, { padding: [12, 12] });
  }
  L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(state.mapInstance);
  updateSelectionLayer();
  updateSchoolMarkers();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.error || `Ошибка HTTP ${response.status}`);
  }
  return data;
}

async function postJson(url, body) {
  return fetchJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
}

function parseCapacityInput(value) {
  const normalized = String(value ?? '').trim().replace(',', '.');
  const number = Number(normalized);
  if (!Number.isFinite(number) || number <= 0 || !Number.isInteger(number)) {
    showToast('Вместимость должна быть целым положительным числом.', 'error');
    return null;
  }
  return number;
}

function showToast(message, kind = 'info') {
  el.toast.textContent = message;
  el.toast.className = `toast ${kind}`.trim();
  el.toast.classList.remove('hidden');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.toast.classList.add('hidden'), 5200);
}

async function calculateScenario({ label = '', saveName = '', mode = 'scenario' } = {}) {
  const placements = state.manualPlacements
    .map((placement) => ({
      block_id: Number(placement.block_id),
      capacity: Number(placement.capacity),
    }))
    .sort((left, right) => left.block_id - right.block_id);
  setManualStatus('Расчёт сценария…');
  try {
    const data = await postJson('/api/scenario', { placements });
    state.scenario = data;
    state.scenarioLabel = label || (placements.length ? 'Текущий сценарий' : 'Пустой сценарий');
    applyScenarioRows(data.blocks);
    state.mode = mode;
    updateModeButtons();
    if (saveName) el.saveName.value = saveName;
    renderAll();
    const summary = data.summary;
    if (!placements.length) {
      setManualStatus('Пустой сценарий: показатели совпадают с исходным состоянием.', 'success');
    } else {
      setManualStatus(
        `Добавлено ${formatNumber(summary.added_capacity)} мест; остаточный дефицит ${formatNumber(summary.deficit)}; сокращение ${formatNumber(summary.deficit_reduction)}; обеспеченность ${formatPercent(summary.provision)}.`,
        summary.deficit_reduction > 0 ? 'success' : '',
      );
    }
    return data;
  } catch (error) {
    setManualStatus(error.message, 'error');
    showToast(error.message, 'error');
    throw error;
  }
}

function addSchool() {
  if (state.selectedId === null) {
    showToast('Сначала выберите квартал на карте или в таблице.', 'error');
    return;
  }
  const capacity = parseCapacityInput(el.manualCapacity.value);
  if (capacity === null) return;
  const existing = state.manualPlacements.find((placement) => placement.block_id === state.selectedId);
  if (existing) {
    existing.capacity += capacity;
    showToast(`Вместимость квартала ${state.selectedId} увеличена до ${formatNumber(existing.capacity)} мест.`, 'success');
  } else {
    state.manualPlacements.push({ block_id: state.selectedId, capacity });
    showToast(`Школа на ${formatNumber(capacity)} мест добавлена в квартал ${state.selectedId}.`, 'success');
  }
  renderPlacements();
  markScenarioStale();
}

function removePlacement(blockId) {
  state.manualPlacements = state.manualPlacements.filter((placement) => placement.block_id !== blockId);
  renderPlacements();
  markScenarioStale();
}

function resetScenario() {
  state.manualPlacements = [];
  state.scenario = null;
  state.scenarioLabel = '';
  state.mode = 'baseline';
  state.selectedId = null;
  state.tableFilter = '';
  state.page = 1;
  el.manualCapacity.value = '600';
  el.tableSearch.value = '';
  el.saveName.value = '';
  resetRows();
  populateBlockSelect();
  updateModeButtons();
  renderAll();
  setManualStatus('Сценарий не рассчитан.');
  showToast('Сценарий сброшен к исходному состоянию.', 'success');
}

function updateAutoProgress(job) {
  const total = Number(job.total) || candidateCount();
  const checked = Number(job.checked) || 0;
  const percent = total ? Math.min(100, Math.round((checked / total) * 100)) : 0;
  el.autoProgressBar.style.width = `${percent}%`;
  const suffix = job.last_block_id === null || job.last_block_id === undefined
    ? ''
    : `; последний квартал ${job.last_block_id}`;
  el.autoProgressText.textContent = `Проверено ${formatNumber(checked)} из ${formatNumber(total)} жилых кварталов${suffix}`;
}

function setAutoBusy(running) {
  state.autoRunning = running;
  el.autoStart.disabled = running;
  el.autoStart.textContent = running ? 'Подбор выполняется…' : 'Разместить автоматически';
  el.autoCancel.classList.toggle('hidden', !running);
  el.autoCancel.disabled = false;
}

function finishAutoError(message) {
  clearTimeout(state.autoTimer);
  state.autoTimer = null;
  setAutoBusy(false);
  el.autoProgress.classList.remove('hidden');
  el.autoProgressText.textContent = message;
  el.autoProgressText.className = 'status-text error';
  state.auto = {
    status: 'error',
    error: message,
    checked: state.auto?.checked || 0,
    total: state.auto?.total || candidateCount(),
    best: [],
    errors: [],
  };
  renderAutoResult();
  renderAutoTable();
  showToast(message, 'error');
}

function finishAuto(job) {
  clearTimeout(state.autoTimer);
  state.autoTimer = null;
  state.auto = job;
  setAutoBusy(false);
  el.autoProgress.classList.remove('hidden');
  updateAutoProgress(job);
  el.autoProgressText.className = 'status-text';
  renderAutoResult();
  renderAutoTable();
  const bestCount = job.best?.length ?? 0;
  if (job.status === 'cancelled') {
    showToast(`Подбор остановлен: проверено ${formatNumber(job.checked)} из ${formatNumber(job.total)}.`, 'error');
  } else if (job.errors?.length) {
    showToast(`Подбор завершён частично: ошибок ${formatNumber(job.errors.length)}.`, 'error');
  } else {
    showToast(
      `Подбор завершён: лучшее сокращение — ${formatNumber(job.best_reduction)} мест; равнозначных лучших — ${formatNumber(bestCount)}.`,
      'success',
    );
  }
}

async function pollAuto() {
  if (!state.autoJobId) return;
  try {
    const job = await fetchJson(`/api/auto/status/${state.autoJobId}`);
    state.auto = job;
    if (job.status === 'running') {
      updateAutoProgress(job);
      renderAutoResult();
      renderAutoTable();
      state.autoTimer = setTimeout(pollAuto, 700);
      return;
    }
    finishAuto(job);
  } catch (error) {
    finishAutoError(error.message);
  }
}

async function startAuto() {
  if (state.autoRunning) return;
  const capacity = parseCapacityInput(el.autoCapacity.value);
  if (capacity === null) return;
  clearTimeout(state.autoTimer);
  state.autoTimer = null;
  state.autoJobId = null;
  state.auto = {
    status: 'running',
    capacity,
    checked: 0,
    total: candidateCount(),
    best: [],
    errors: [],
  };
  setAutoBusy(true);
  el.autoProgress.classList.remove('hidden');
  el.autoProgressBar.style.width = '0%';
  el.autoProgressText.className = 'status-text';
  el.autoProgressText.textContent = `Проверено 0 из ${formatNumber(candidateCount())} жилых кварталов…`;
  renderAutoResult();
  renderAutoTable();
  try {
    const response = await postJson('/api/auto/start', { capacity });
    state.autoJobId = response.job_id;
    pollAuto();
  } catch (error) {
    finishAutoError(error.message);
  }
}

async function cancelAuto() {
  if (!state.autoJobId || !state.autoRunning) return;
  el.autoCancel.disabled = true;
  try {
    await postJson(`/api/auto/cancel/${state.autoJobId}`, {});
    showToast('Останавливаем подбор после текущего квартала…', 'info');
  } catch (error) {
    showToast(error.message, 'error');
    el.autoCancel.disabled = false;
  }
}

async function applyBestBlock(blockId) {
  const capacity = Number(state.auto?.capacity);
  if (!Number.isFinite(capacity) || capacity <= 0) return;
  state.manualPlacements = [{ block_id: Number(blockId), capacity }];
  state.scenarioLabel = `Авто-подбор: квартал ${blockId}`;
  el.manualCapacity.value = String(capacity);
  el.saveName.value = state.scenarioLabel;
  renderPlacements();
  selectBlock(Number(blockId), { focusTable: true });
  try {
    await calculateScenario({
      label: state.scenarioLabel,
      saveName: state.scenarioLabel,
      mode: 'change',
    });
    showToast(`Сценарий с кварталом ${blockId} рассчитан.`, 'success');
  } catch {
    // Ошибка уже показана в статусе и toast.
  }
}

async function loadExperiment(key) {
  const definition = state.scenarios[key];
  if (!definition) return;
  state.manualPlacements = (definition.placements || []).map((placement) => ({
    block_id: Number(placement.block_id),
    capacity: Number(placement.capacity),
  }));
  state.scenarioLabel = definition.name;
  el.manualCapacity.value = String(state.manualPlacements[0]?.capacity || 600);
  if (state.manualPlacements[0]) {
    selectBlock(state.manualPlacements[0].block_id, { focusTable: true });
  }
  renderPlacements();
  try {
    await calculateScenario({
      label: definition.name,
      saveName: definition.name,
      mode: 'change',
    });
  } catch {
    // Ошибка уже показана.
  }
}

function loadSavedScenarios() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item) => item && item.id && item.name && Array.isArray(item.placements) && item.summary,
    );
  } catch {
    return [];
  }
}

function persistSavedScenarios() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.saved));
  } catch {
    showToast('Не удалось сохранить историю в localStorage.', 'error');
  }
}

function makeId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function saveCurrentScenario() {
  if (!state.scenario) {
    showToast('Сначала рассчитайте сценарий.', 'error');
    return;
  }
  const name = el.saveName.value.trim() || `Сценарий ${state.saved.length + 1}`;
  const item = {
    id: makeId(),
    name,
    placements: state.manualPlacements.map((placement) => ({
      block_id: Number(placement.block_id),
      capacity: Number(placement.capacity),
    })),
    summary: state.scenario.summary,
    label: state.scenarioLabel,
    createdAt: new Date().toISOString(),
  };
  state.saved.unshift(item);
  persistSavedScenarios();
  el.saveName.value = '';
  renderComparison();
  renderSaved();
  showToast(`Сценарий «${name}» сохранён.`, 'success');
}

async function loadSavedScenario(id) {
  const item = state.saved.find((saved) => saved.id === id);
  if (!item) return;
  state.manualPlacements = (item.placements || []).map((placement) => ({
    block_id: Number(placement.block_id),
    capacity: Number(placement.capacity),
  }));
  state.scenarioLabel = item.name;
  el.saveName.value = item.name;
  if (state.manualPlacements[0]) {
    el.manualCapacity.value = String(state.manualPlacements[0].capacity);
    selectBlock(state.manualPlacements[0].block_id, { focusTable: true });
  }
  renderPlacements();
  try {
    await calculateScenario({
      label: item.name,
      saveName: item.name,
      mode: 'change',
    });
    showToast(`Сценарий «${item.name}» загружен.`, 'success');
  } catch {
    // Ошибка уже показана.
  }
}

function deleteSavedScenario(id) {
  const item = state.saved.find((saved) => saved.id === id);
  state.saved = state.saved.filter((saved) => saved.id !== id);
  persistSavedScenarios();
  renderComparison();
  renderSaved();
  if (item) showToast(`Сценарий «${item.name}» удалён.`, 'success');
}

function handleSavedAction(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  event.stopPropagation();
  const action = button.dataset.action;
  const savedId = button.dataset.savedId;
  if (action === 'save-current') {
    saveCurrentScenario();
  } else if (action === 'load-saved' && savedId) {
    loadSavedScenario(savedId);
  } else if (action === 'delete-saved' && savedId) {
    deleteSavedScenario(savedId);
  }
}

function exportCsv() {
  const rows = state.rows.slice().sort((left, right) => left.block_id - right.block_id);
  if (!rows.length) {
    showToast('Нет данных для экспорта.', 'error');
    return;
  }
  const header = [
    'Квартал',
    'Население, чел.',
    'Вместимость исходная',
    'Вместимость сценария',
    'Δ вместимости',
    'Обеспеченность исходная, %',
    'Обеспеченность сценария, %',
    'Δ обеспеченности, п.п.',
    'Дефицит исходный',
    'Дефицит сценария',
    'Сокращение дефицита',
    'Тип использования',
    'Морфотип',
  ];
  const csvCell = (value) => {
    if (value === null || value === undefined) return '';
    const text = String(value);
    return /[;"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const numberText = (value, digits = 0) => (
    value === null || value === undefined
      ? ''
      : formatNumber(value, digits).replace(/\u00A0/g, ' ')
  );
  const percentText = (value) => (
    value === null || value === undefined
      ? ''
      : formatNumber(value * 100, 2).replace(/\u00A0/g, ' ')
  );
  const changeText = (value) => (value === null || value === undefined ? '' : numberText(value * 100, 1));
  const lines = [header.join(';')];
  for (const row of rows) {
    lines.push([
      row.block_id,
      numberText(row.population),
      numberText(row.baseline_capacity),
      numberText(row.scenario_capacity),
      numberText(row.added_capacity),
      percentText(row.baseline_provision),
      percentText(row.scenario_provision),
      changeText(row.provision_change),
      numberText(row.baseline_deficit, 1),
      numberText(row.scenario_deficit, 1),
      numberText(row.deficit_reduction, 1),
      csvCell(row.land_use),
      csvCell(row.morphotype),
    ].map(csvCell).join(';'));
  }
  const blob = new Blob([`\uFEFF${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const mode = state.scenario ? state.scenarioLabel || 'scenario' : 'baseline';
  const safeMode = mode.replace(/[^\wа-яА-ЯёЁ-]+/g, '_').slice(0, 50);
  anchor.href = url;
  anchor.download = `school-placement_${safeMode}_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function bindEvents() {
  el.addSchool.addEventListener('click', addSchool);
  el.calculateScenario.addEventListener('click', () => {
    calculateScenario({
      label: el.saveName.value.trim() || 'Текущий сценарий',
      saveName: el.saveName.value.trim(),
      mode: 'scenario',
    }).catch(() => {});
  });
  el.resetScenario.addEventListener('click', resetScenario);
  el.autoStart.addEventListener('click', startAuto);
  el.autoCancel.addEventListener('click', cancelAuto);
  el.saveScenario.addEventListener('click', saveCurrentScenario);
  el.exportCsv.addEventListener('click', exportCsv);

  el.placementsList.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-remove-block]');
    if (!button) return;
    removePlacement(Number(button.dataset.removeBlock));
  });

  el.manualBlock.addEventListener('change', (event) => {
    const blockId = Number(event.target.value);
    if (!event.target.value || !Number.isFinite(blockId)) {
      state.selectedId = null;
      renderSelected();
      renderPlacements();
      renderTable();
      updateSelectionLayer();
      return;
    }
    selectBlock(blockId, { focusTable: true });
  });

  el.tableSearch.addEventListener('input', (event) => {
    state.tableFilter = event.target.value;
    state.page = 1;
    renderTable();
  });

  el.autoTableSearch.addEventListener('input', (event) => {
    state.autoFilter = event.target.value;
    renderAutoTable();
  });

  el.modeButtons.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-mode]');
    if (!button) return;
    setMode(button.dataset.mode);
  });

  el.blocksTable.querySelector('thead').addEventListener('click', (event) => {
    const header = event.target.closest('th[data-sort]');
    if (!header) return;
    const key = header.dataset.sort;
    if (state.sortKey === key) {
      state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      state.sortKey = key;
      state.sortDir = 'asc';
    }
    state.page = 1;
    renderTable();
  });

  el.autoTable.querySelector('thead').addEventListener('click', (event) => {
    const header = event.target.closest('th[data-sort]');
    if (!header) return;
    const key = header.dataset.sort;
    if (state.autoSortKey === key) {
      state.autoSortDir = state.autoSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      state.autoSortKey = key;
      state.autoSortDir = 'asc';
    }
    renderAutoTable();
  });

  el.blocksPagination.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-page]');
    if (!button || button.disabled) return;
    const page = Number(button.dataset.page);
    if (!Number.isFinite(page)) return;
    state.page = page;
    renderTable();
  });

  el.blocksTableBody.addEventListener('click', (event) => {
    const row = event.target.closest('tr[data-block-id]');
    if (!row) return;
    selectBlock(Number(row.dataset.blockId));
  });

  el.autoTableBody.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-apply-auto]');
    if (button) {
      event.stopPropagation();
      applyBestBlock(Number(button.dataset.applyAuto));
      return;
    }
    const row = event.target.closest('tr[data-block-id]');
    if (!row) return;
    selectBlock(Number(row.dataset.blockId));
  });

  el.autoResult.addEventListener('click', (event) => {
    const blockButton = event.target.closest('[data-best-block]');
    if (blockButton) {
      applyBestBlock(Number(blockButton.dataset.bestBlock));
      return;
    }
    const scrollButton = event.target.closest('[data-scroll-auto]');
    if (scrollButton) {
      el.autoTableCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  el.experimentButtons.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-scenario]');
    if (!button) return;
    loadExperiment(button.dataset.scenario);
  });

  el.savedScenarios.addEventListener('click', handleSavedAction);
  el.comparisonTableBody.addEventListener('click', handleSavedAction);
}

function renderAll() {
  renderExperimentButtons();
  renderSaved();
  renderComparison();
  renderPlacements();
  renderKpis();
  renderSelected();
  renderTable();
  renderAutoResult();
  renderAutoTable();
  refreshMap();
}

async function init() {
  try {
    const payload = await fetchJson('/api/initial');
    state.meta = payload.meta;
    state.geojson = payload.blocks;
    state.featuresById = new Map(
      payload.blocks.features.map((feature) => [Number(feature.properties.block_id), feature]),
    );
    state.baselineRows = payload.blocks.features
      .map((feature) => ({ ...feature.properties }))
      .sort((left, right) => Number(left.block_id) - Number(right.block_id));
    state.baselineById = new Map(state.baselineRows.map((row) => [Number(row.block_id), row]));
    state.populationTotal = numOrNull(payload.meta.population_total)
      ?? state.baselineRows.reduce((sum, row) => sum + (numOrNull(row.population) ?? 0), 0);
    state.scenarios = payload.scenarios || {};
    state.saved = loadSavedScenarios();
    state.rows = state.baselineRows.map((row) => baselineRow(row));
    reindexRows();
    populateBlockSelect();

    initMap();
    bindEvents();
    updateTopbar();
    updateModeButtons();
    renderAll();
    el.loading.classList.add('hidden');
    setTimeout(() => state.mapInstance.invalidateSize(), 50);

    if (!state.meta.verification?.ok) {
      showToast('Внимание: исходный расчёт не совпал с данными практики 2.', 'error');
    }
  } catch (error) {
    console.error(error);
    el.loading.textContent = `Не удалось загрузить приложение: ${error.message}`;
    el.loading.classList.remove('hidden');
  }
}

init();
