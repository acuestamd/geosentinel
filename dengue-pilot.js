'use strict';
(function (root) {
  const DAY = 86400000;
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const number = (value, digits = 0) => finite(value) ? value.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : 'Unavailable';
  function dateTime(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value)) return null;
    const timestamp = Date.parse(value);
    return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value.slice(0, 10) ? timestamp : null;
  }
  function dateLabel(value, year = true) {
    const timestamp = dateTime(value);
    return timestamp === null ? 'Date unavailable' : new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', ...(year ? { year: 'numeric' } : {}), timeZone: 'UTC' }).format(timestamp);
  }
  function safeURL(value) {
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''; } catch { return ''; }
  }
  function modelLabel(value) {
    const labels = { persistence: 'Last reported week', seasonal: 'Same week, previous year', seasonal_naive: 'Seasonal baseline', baseline: 'Simple baseline', cases: 'Cases + seasonality', ridge_cases: 'Cases + seasonality', case_model: 'Cases + seasonality', cases_only: 'Cases + seasonality', weather: 'Cases + seasonality + weather', ridge_weather: 'Cases + seasonality + weather', weather_model: 'Cases + seasonality + weather', cases_weather: 'Cases + seasonality + weather' };
    return labels[value] || String(value || 'Model unavailable').replace(/_/g, ' ');
  }
  function pilotState(data, now = Date.now()) {
    if (!data || data.schema_version !== 1 || !['ready', 'stale', 'unavailable'].includes(data.status)) return { status: 'unavailable', label: 'Pilot unavailable', forecast: false, message: 'The pilot dataset could not be read. Refresh this panel or check the source and project run history.' };
    if (data.status === 'unavailable') return { status: 'unavailable', label: 'Source unavailable', forecast: false, message: 'A valid model run is unavailable. The source may be delayed or the data may not meet the pilot’s quality checks. No new outlook is shown.' };
    const generated = dateTime(data.generated_at);
    const date = new Date(now), today = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
    const expectedOrigin = today - date.getUTCDay() * DAY;
    const origin = dateTime(data.origin_week);
    if (data.status === 'stale' || generated === null || now - generated > 2 * DAY || generated > now + 300000 || (origin !== null && origin !== expectedOrigin) || data.data_quality?.valid_for_forecast !== true) return { status: 'stale', label: 'Outlook paused', forecast: false, message: 'The source data or model run is out of date or incomplete. The available history is shown for context; a new outlook will appear after a valid update.' };
    return { status: 'ready', label: 'Experimental', forecast: true, message: '' };
  }
  function historyRows(data) {
    if (!Array.isArray(data?.history)) return [];
    const latest = dateTime(data.data_quality?.latest_week);
    const rows = data.history.filter(row => dateTime(row?.week) !== null && (latest === null || dateTime(row.week) <= latest) && finite(row.cases) && row.cases >= 0);
    return [...new Map(rows.map(row => [row.week, row])).values()].sort((a, b) => a.week.localeCompare(b.week));
  }
  function forecastRows(data, now = Date.now()) {
    if (!pilotState(data, now).forecast || !Array.isArray(data.forecasts)) return [];
    const origin = dateTime(data.origin_week);
    const rows = data.forecasts.filter(row => Number.isInteger(row?.horizon_weeks) && row.horizon_weeks >= 1 && row.horizon_weeks <= 4 && dateTime(row.week) !== null && (origin === null || dateTime(row.week) === origin + row.horizon_weeks * 7 * DAY) && ['point', 'lower', 'upper'].every(key => finite(row[key]) && row[key] >= 0) && row.lower <= row.point && row.point <= row.upper).sort((a, b) => a.horizon_weeks - b.horizon_weeks);
    return rows.length === 4 && new Set(rows.map(row => row.horizon_weeks)).size === 4 && new Set(rows.map(row => row.week)).size === 4 ? rows : [];
  }
  function chartHTML(data, now = Date.now(), compact = false) {
    const rows = historyRows(data).slice(-52), forecast = forecastRows(data, now);
    if (!rows.length) return '<div class="pilot-empty"><h2>No usable weekly history</h2><p>The source has not supplied enough valid weekly observations for this chart.</p></div>';
    const width = compact ? 420 : 940, height = compact ? 270 : 305, left = compact ? 45 : 65, right = 24, top = 28, bottom = 44;
    const dates = [...rows, ...forecast].map(row => dateTime(row.week));
    const start = Math.min(...dates), end = Math.max(...dates, start + 7 * DAY);
    const maximum = Math.max(1, ...rows.map(row => row.cases), ...forecast.map(row => row.upper));
    const power = 10 ** Math.floor(Math.log10(maximum)), upper = Math.ceil(maximum / power * 2) / 2 * power;
    const x = value => left + (dateTime(value) - start) / (end - start) * (width - left - right);
    const y = value => height - bottom - value / upper * (height - top - bottom);
    const point = (row, field) => `${x(row.week).toFixed(2)},${y(row[field]).toFixed(2)}`;
    const ticks = Array.from({ length: 5 }, (_, i) => upper * i / 4).map(value => `<line x1="${left}" x2="${width - right}" y1="${y(value).toFixed(2)}" y2="${y(value).toFixed(2)}" stroke="#e1eaee"/><text x="${left - 10}" y="${(y(value) + 4).toFixed(2)}" text-anchor="end">${number(value)}</text>`).join('');
    const labels = [rows[0], rows[Math.floor(rows.length / 3)], rows[Math.floor(2 * rows.length / 3)], rows[rows.length - 1]];
    const datesHTML = [...new Map(labels.map(row => [row.week, row])).values()].map(row => `<text x="${x(row.week).toFixed(2)}" y="${height - 15}" text-anchor="middle">${dateLabel(row.week, false)}</text>`).join('');
    const last = rows[rows.length - 1];
    // Split history at missing weeks so an interrupted series is never drawn as observed continuity.
    const paths = rows.reduce((parts, row, index) => { if (!index || dateTime(row.week) - dateTime(rows[index - 1].week) > 8 * DAY) parts.push([]); parts[parts.length - 1].push(row); return parts; }, []).map(part => `<polyline points="${part.map(row => point(row, 'cases')).join(' ')}" fill="none" stroke="#123f50" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>`).join('');
    let outlook = '';
    if (forecast.length) {
      const origin = { week: last.week, point: last.cases, lower: last.cases, upper: last.cases };
      const series = [origin, ...forecast];
      outlook = `<rect x="${x(last.week).toFixed(2)}" y="${top}" width="${(width - right - x(last.week)).toFixed(2)}" height="${height - top - bottom}" fill="#f0f7f9"/><polygon points="${series.map(row => point(row, 'upper')).join(' ')} ${[...series].reverse().map(row => point(row, 'lower')).join(' ')}" fill="#d5e9ee"/><line x1="${x(last.week).toFixed(2)}" x2="${x(last.week).toFixed(2)}" y1="${top}" y2="${height - bottom}" stroke="#8eb7c5" stroke-dasharray="4 4"/><polyline points="${series.map(row => point(row, 'point')).join(' ')}" fill="none" stroke="#17677d" stroke-width="2.4" stroke-dasharray="5 4"/>${forecast.map(row => `<circle cx="${x(row.week).toFixed(2)}" cy="${y(row.point).toFixed(2)}" r="3.5" fill="#17677d"><title>Week of ${dateLabel(row.week)}: ${number(row.point)} reported cases; range ${number(row.lower)} to ${number(row.upper)}</title></circle>`).join('')}`;
    }
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="dengueChartTitle dengueChartDesc"><title id="dengueChartTitle">Rio de Janeiro weekly reported dengue cases</title><desc id="dengueChartDesc">${rows.length} available weeks, from ${dateLabel(rows[0].week)} to ${dateLabel(last.week)}.${forecast.length ? ' Dashed line: experimental outlook. Shaded band: empirical uncertainty range. Exact forecast values and an accessible history table follow.' : ' The forecast is currently withheld.'}</desc>${ticks}${outlook}${paths}${datesHTML}<text x="${left}" y="15">Reported cases / week</text><circle cx="${x(last.week).toFixed(2)}" cy="${y(last.cases).toFixed(2)}" r="3.4" fill="#123f50"/></svg>`;
  }
  function periodLabel(value) {
    if (Array.isArray(value)) return value.map(item => dateLabel(item)).join(' – ');
    if (value && typeof value === 'object') return `${dateLabel(value.start || value.from)} – ${dateLabel(value.end || value.to)}`;
    return typeof value === 'string' ? escapeHTML(value) : 'Unavailable';
  }
  function skillLabel(value) {
    if (!finite(value)) return 'Unavailable';
    if (Math.abs(value) < 0.0005) return 'No improvement';
    return `${number(Math.abs(value) * 100, 1)}% ${value > 0 ? 'lower error' : 'higher error'}`;
  }
  function evaluationHTML(data) {
    const evaluation = data.evaluation || {}, rows = Array.isArray(evaluation.horizons) ? evaluation.horizons.filter(row => Number.isInteger(row?.horizon_weeks) && row.horizon_weeks >= 1 && row.horizon_weeks <= 4) : [];
    const candidates = Array.isArray(evaluation.candidates) ? evaluation.candidates : [];
    const candidateTable = candidates.length ? `<p class="pilot-muted">The model is selected using development weeks only; held-out results never choose the model. ${escapeHTML(evaluation.selection_rule || '')}</p><div class="pilot-table-wrap" tabindex="0" role="region" aria-label="Model selection and held-out comparison"><table class="pilot-table"><thead><tr><th scope="col">Candidate model</th><th scope="col">Development MAE</th><th scope="col">Held-out MAE</th></tr></thead><tbody>${candidates.map(row => `<tr><th scope="row">${escapeHTML(row.label || modelLabel(row.model))}${row.model === evaluation.selected_model ? '<span class="chosen">Selected</span>' : ''}</th><td>${number(row.development_mae, 1)}</td><td>${number(row.heldout_mae, 1)}</td></tr>`).join('')}</tbody></table></div>` : '';
    if (!rows.length) return '<section class="pilot-card pilot-section"><div class="pilot-card-head"><div><h2>Does the model improve on the baseline?</h2><p>Evaluation results are unavailable for this run.</p></div></div><p class="pilot-evaluation-intro">A forecast cannot establish its own quality. Held-out errors and interval coverage are required before interpreting model skill.</p></section>';
    return `<section class="pilot-card pilot-section" aria-labelledby="dengueEvaluationTitle"><div class="pilot-card-head"><div><h2 id="dengueEvaluationTitle">Does the model improve on the baseline?</h2><p>Held-out historical weeks · mean absolute error (MAE) · lower is better</p></div></div><p class="pilot-evaluation-intro">${escapeHTML(evaluation.design || 'Time-ordered evaluation using the latest revised source series.')} The development-selected model is <strong>${escapeHTML(modelLabel(evaluation.selected_model || data.model?.name))}</strong>. The baseline is ${escapeHTML(modelLabel(evaluation.baseline))}. The comparison reports both improvement and worse performance.</p><div class="pilot-table-wrap" tabindex="0" role="region" aria-label="Forecast errors by horizon"><table class="pilot-table"><thead><tr><th scope="col">Target horizon</th><th scope="col">Baseline MAE</th><th scope="col">Cases + seasonality</th><th scope="col">+ Weather</th><th scope="col">Selected vs baseline</th><th scope="col">Test weeks</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${row.horizon_weeks} ${row.horizon_weeks === 1 ? 'week' : 'weeks'} ahead</th><td>${number(row.baseline_mae, 1)}</td><td>${number(row.case_model_mae, 1)}</td><td>${number(row.weather_model_mae, 1)}</td><td>${skillLabel(row.skill_vs_baseline)}</td><td>${number(row.n)}</td></tr>`).join('')}</tbody></table></div><div class="pilot-evaluation-foot">MAE is the average absolute error in reported cases per week. Historical tests use today’s revised data; they cannot reproduce what was actually available on each past forecast date. Results are a development benchmark, not prospective validation.</div><details class="pilot-details"><summary>Evaluation periods and uncertainty coverage</summary>${candidateTable}<p class="pilot-muted">Initial training: ${periodLabel(evaluation.train_period)}. Development: ${periodLabel(evaluation.development_period)}. Calibration: ${periodLabel(evaluation.calibration_period)}. Held-out test: ${periodLabel(evaluation.test_period)}.</p><div class="pilot-table-wrap" tabindex="0" role="region" aria-label="Empirical range coverage"><table class="pilot-table"><thead><tr><th scope="col">Target horizon</th><th scope="col">Observed interval coverage</th><th scope="col">Test weeks</th></tr></thead><tbody>${rows.map(row => `<tr><th scope="row">${row.horizon_weeks} ${row.horizon_weeks === 1 ? 'week' : 'weeks'} ahead</th><td>${finite(row.interval_coverage) ? `${number(row.interval_coverage * 100, 1)}%` : 'Unavailable'}</td><td>${number(row.n)}</td></tr>`).join('')}</tbody></table></div><p class="pilot-evaluation-foot">${escapeHTML(evaluation.interval_method || data.interval?.method || 'Intervals are based on historical calibration errors.')} Coverage is the share of held-out observations inside the range, not a guarantee for future weeks.</p></details></section>`;
  }
  function renderPilot(data, now = Date.now(), compact = false) {
    const state = pilotState(data, now), sourceURL = safeURL(data?.source?.url), sourceName = escapeHTML(data?.source?.name || 'InfoDengue');
    const source = sourceURL ? `<a href="${escapeHTML(sourceURL)}" target="_blank" rel="noopener noreferrer">${sourceName} ↗</a>` : sourceName;
    if (state.status === 'unavailable') return `<div class="pilot-empty" role="status"><h2>${state.label}</h2><p>${state.message}</p><p style="margin-top:12px">${escapeHTML((data?.data_quality?.notes || []).filter(value => typeof value === 'string').slice(0, 3).join(' '))}</p><p style="margin-top:12px">Source: ${source}. <a href="https://github.com/acuestamd/project-geosentinel/actions" target="_blank" rel="noopener noreferrer">Check collection runs ↗</a></p><button type="button" class="btn" data-dengue-retry>Try again</button></div>`;
    const history = historyRows(data), forecasts = forecastRows(data, now), quality = data.data_quality || {}, last = history[history.length - 1];
    const level = finite(data.interval?.level) ? `${number(data.interval.level * 100)}%` : '';
    const note = state.message ? `<div class="pilot-notice" role="status"><strong>${state.label}</strong>${state.message}</div>` : '';
    const notes = Array.isArray(quality.notes) ? quality.notes.filter(value => typeof value === 'string') : [];
    const limitations = Array.isArray(data.limitations) ? data.limitations.filter(value => typeof value === 'string') : [];
    const model = escapeHTML(data.model?.label || modelLabel(data.model?.name || data.evaluation?.selected_model));
    const gapCount = Array.isArray(quality.gaps) ? quality.gaps.length : quality.gaps;
    const revisionNote = finite(quality.latest_reported_cases) && finite(quality.latest_nowcast_cases)
      ? `<div class="pilot-notice"><strong>Recent counts are provisional</strong>For the latest reported week, InfoDengue lists ${number(quality.latest_reported_cases)} notifications and an upstream nowcast of ${number(quality.latest_nowcast_cases)}. The nowcast estimates delayed reporting; it is not an observed count or an input to this pilot.</div>` : '';
    return `${note}${revisionNote}<div class="pilot-layout"><section class="pilot-card" aria-labelledby="dengueChartHeading"><div class="pilot-card-head"><div><h2 id="dengueChartHeading">Reported cases &amp; four-week outlook</h2><p>Municipality of Rio de Janeiro · last 52 available weeks</p></div><span class="status ${state.status === 'ready' ? 'warn' : 'error'}">${state.label}</span></div><div class="pilot-chart">${chartHTML(data, now, compact)}</div><div class="pilot-chart-legend"><span><i class="pilot-key" aria-hidden="true"></i>Reported cases</span>${forecasts.length ? `<span><i class="pilot-key forecast" aria-hidden="true"></i>Model outlook</span><span><i class="pilot-key interval" aria-hidden="true"></i>${level} empirical range</span>` : ''}</div><p class="pilot-chart-note">Case counts are subject to reporting delays and later revision.${forecasts.length ? ` The band reflects historical model errors; it does not describe clinical severity or epidemic-alert probability.` : ' An outlook is not displayed until the pilot passes freshness and data checks.'}</p>${forecasts.length ? `<div class="pilot-week-grid" aria-label="Forecast values">${forecasts.map(row => `<div class="pilot-week"><p class="pilot-week-label">${row.horizon_weeks} ${row.horizon_weeks === 1 ? 'week' : 'weeks'} ahead</p><time datetime="${escapeHTML(row.week)}">Week of ${dateLabel(row.week, false)}</time><p class="pilot-week-value">${number(row.point)}</p><p class="pilot-week-range">${number(row.lower)}–${number(row.upper)} <span class="sr-only">reported cases, empirical range</span></p></div>`).join('')}</div>` : ''}</section><aside class="pilot-card pilot-sidebar" aria-label="Model and data provenance"><p class="eyebrow">Run record</p><h2>What feeds this outlook</h2><dl><div><dt>Model used for this outlook</dt><dd>${model}<small>${data.model?.uses_weather === true ? 'Uses lagged temperature and humidity' : 'Weather tested as a separate candidate'}</small></dd></div><div><dt>Latest reported week</dt><dd>${dateLabel(quality.latest_week || last?.week)}<small>${last ? `${number(last.cases)} reported cases` : 'Case count unavailable'}</small></dd></div><div><dt>Forecast origin / current week</dt><dd>${dateLabel(data.origin_week || quality.latest_complete_week)}<small>Source lag: ${finite(quality.lag_days) ? `${number(quality.lag_days)} days` : 'unavailable'}</small></dd></div><div><dt>History available</dt><dd>${number(quality.observations ?? history.length)} weeks<small>${finite(gapCount) ? `${number(gapCount)} gaps in weekly coverage` : 'Check source coverage notes'}</small></dd></div><div><dt>Run generated</dt><dd>${dateLabel(data.generated_at)}</dd></div><div><dt>Source</dt><dd>${source}<small>Retrieved ${dateLabel(data.source?.retrieved_at)}</small></dd></div></dl><p class="pilot-provenance">Forecast dates follow the model’s explicit weekly targets. The four target weeks start after the current calendar week. The model bridges incomplete weeks and any reporting delay.</p></aside></div>${evaluationHTML(data)}<div class="pilot-limitations"><section class="pilot-card"><h2>Read the limits with the result</h2><p>This is an experimental forecast of reported case counts for one municipality. It does not estimate hospital demand, deaths, individual risk or whether an event will become severe.</p><ul>${[...notes, ...limitations].slice(0, 12).map(value => `<li>${escapeHTML(value)}</li>`).join('')}</ul><p style="margin-top:12px"><a href="https://github.com/acuestamd/project-geosentinel/blob/main/docs/DENGUE_PILOT.md" target="_blank" rel="noopener noreferrer">Pilot method &amp; evaluation ↗</a></p></section><section class="pilot-card"><h2>Additional signals</h2><p>New sources earn their place by improving held-out forecasts. They are not included until access and evaluation are available.</p><div class="pilot-integration"><strong>Cases &amp; weather</strong><span>InfoDengue historical series</span></div><div class="pilot-integration"><strong>Google Trends</strong><span>Access required · not connected</span></div><div class="pilot-integration"><strong>X / Twitter</strong><span>Not connected</span></div><div class="pilot-integration"><strong>Passenger flows</strong><span>Provider required</span></div><p style="margin-top:12px">Search interest and social activity can reflect news coverage as well as illness. Each addition needs a separate comparison against the same baseline.</p></section></div><details class="pilot-data-details"><summary>Read the chart as a table (${Math.min(history.length, 52)} observed weeks)</summary><div class="pilot-table-wrap" tabindex="0" role="region" aria-label="Observed weekly case counts"><table class="pilot-table"><thead><tr><th scope="col">Week starting</th><th scope="col">Reported cases</th><th scope="col">Minimum temperature, °C</th><th scope="col">Maximum relative humidity, %</th></tr></thead><tbody>${history.slice(-52).reverse().map(row => `<tr><th scope="row">${dateLabel(row.week)}</th><td>${number(row.cases)}</td><td>${number(row.temperature_min, 1)}</td><td>${number(row.humidity_max, 1)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  async function readJSON(response, limit = 1024 * 1024) {
    if (!response.ok) throw new Error(`Pilot HTTP ${response.status}`);
    const length = Number(response.headers?.get('content-length'));
    if (Number.isFinite(length) && length > limit) throw new Error('Pilot response is too large');
    if (!response.body?.getReader) { const body = await response.text(); if (new TextEncoder().encode(body).length > limit) throw new Error('Pilot response is too large'); return JSON.parse(body); }
    const reader = response.body.getReader(), chunks = []; let total = 0;
    try { while (true) { const { value, done } = await reader.read(); if (done) break; total += value.byteLength; if (total > limit) { await reader.cancel(); throw new Error('Pilot response is too large'); } chunks.push(value); } }
    finally { reader.releaseLock(); }
    const bytes = new Uint8Array(total); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder().decode(bytes));
  }
  const api = { escapeHTML, number, dateTime, dateLabel, safeURL, pilotState, historyRows, forecastRows, chartHTML, evaluationHTML, renderPilot, skillLabel, readJSON };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.GeoSentinelDengue = api;
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  if (!$('dengue-pilot')) return;
  const tabs = [$('signalsWorkspaceTab'), $('dengueWorkspaceTab')];
  let loaded = false, pending = false, currentData = null, resizeTimer;
  async function loadPilot() {
    if (pending) return;
    pending = true; $('dengueRefresh').disabled = true; $('dengueContent').setAttribute('aria-busy', 'true');
    $('dengueContent').innerHTML = '<div class="pilot-loading" role="status">Loading the latest pilot run and evaluation…</div>';
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try { const response = await fetch(`dengue_forecast.json?t=${Date.now()}`, { cache: 'no-store', signal: controller.signal }); const data = await readJSON(response); currentData = data; $('dengueContent').innerHTML = renderPilot(data, Date.now(), root.innerWidth <= 600); loaded = pilotState(data).status !== 'unavailable'; }
    catch { $('dengueContent').innerHTML = renderPilot(null); loaded = false; }
    finally { clearTimeout(timer); pending = false; $('dengueRefresh').disabled = false; $('dengueContent').setAttribute('aria-busy', 'false'); }
  }
  function selectWorkspace(pilot, focus = false, changeHash = true) {
    $('signalsWorkspace').hidden = pilot; $('dengue-pilot').hidden = !pilot;
    tabs.forEach((tab, index) => { const selected = pilot === (index === 1); tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1; });
    document.querySelector('.skip').href = pilot ? '#dengue-pilot' : '#evidence';
    document.querySelector('.skip').textContent = pilot ? 'Skip to dengue pilot' : 'Skip to signal review';
    if (changeHash) history.replaceState(null, '', pilot ? '#dengue-pilot' : '#signals');
    if (focus) tabs[pilot ? 1 : 0].focus();
    if (pilot && !loaded) loadPilot();
    if (!pilot) root.dispatchEvent(new Event('resize'));
  }
  tabs.forEach((tab, index) => tab.addEventListener('click', () => selectWorkspace(index === 1)));
  document.querySelector('.workspace-nav').addEventListener('keydown', event => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); selectWorkspace(event.key === 'Home' ? false : event.key === 'End' ? true : tabs[0].getAttribute('aria-selected') === 'true', true); });
  $('dengueRefresh').addEventListener('click', loadPilot);
  $('dengueContent').addEventListener('click', event => { if (event.target.closest('[data-dengue-retry]')) loadPilot(); });
  root.addEventListener('hashchange', () => selectWorkspace(location.hash === '#dengue-pilot', false, false));
  root.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { const chart = document.querySelector('.pilot-chart'); if (currentData && chart) chart.innerHTML = chartHTML(currentData, Date.now(), root.innerWidth <= 600); }, 120); });
  selectWorkspace(location.hash === '#dengue-pilot', false, false);
})(typeof globalThis !== 'undefined' ? globalThis : this);
