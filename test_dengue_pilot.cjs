'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { number, dateTime, safeURL, pilotState, historyRows, forecastRows, chartHTML, evaluationHTML, renderPilot, skillLabel, readJSON } = require('./dengue-pilot.js');
const NOW = Date.parse('2026-09-06T12:00:00Z');
const fixture = (overrides = {}) => ({
  schema_version: 1, status: 'ready', generated_at: '2026-09-06T11:00:00Z', origin_week: '2026-09-06',
  location: { name: 'Rio de Janeiro', country: 'Brazil', geocode: 3304557 },
  source: { name: 'InfoDengue', url: 'https://info.dengue.mat.br/', retrieved_at: '2026-09-06T10:00:00Z' },
  data_quality: { valid_for_forecast: true, latest_week: '2026-08-23', latest_complete_week: '2026-08-30', lag_days: 8, observations: 600, gaps: [], latest_reported_cases: 95, latest_nowcast_cases: 227, notes: [] },
  model: { name: 'ridge_cases', label: 'Cases + seasonality', uses_weather: false },
  interval: { level: 0.8, method: 'Empirical calibration' },
  history: [{ week: '2026-08-09', cases: 108, temperature_min: 19, humidity_max: 90 }, { week: '2026-08-16', cases: 100, temperature_min: null, humidity_max: 0 }, { week: '2026-08-23', cases: 95, temperature_min: 20, humidity_max: 94 }],
  forecasts: ['2026-09-13', '2026-09-20', '2026-09-27', '2026-10-04'].map((week, index) => ({ week, horizon_weeks: index + 1, data_horizon_weeks: index + 3, point: 90 + index, lower: 40, upper: 160, model: 'ridge_cases' })),
  evaluation: { selected_model: 'ridge_cases', baseline: 'persistence', horizons: [1, 2, 3, 4].map(horizon_weeks => ({ horizon_weeks, n: 100, baseline_mae: 10, case_model_mae: 12, weather_model_mae: 15, selected_model: 'ridge_cases', skill_vs_baseline: -0.2, interval_coverage: 0.72 })) },
  limitations: ['Uses revised historical data.'], ...overrides
});

test('unavailable, stale and malformed runs never issue a forecast', () => {
  for (const data of [null, {}, fixture({ status: 'unavailable' }), fixture({ status: 'stale' }), fixture({ generated_at: '2026-09-03T00:00:00Z' }), fixture({ generated_at: '2026-09-07T00:00:00Z' }), fixture({ data_quality: { valid_for_forecast: false } })]) {
    assert.equal(pilotState(data, NOW).forecast, false);
    assert.deepEqual(forecastRows(data, NOW), []);
  }
  assert.equal(pilotState(fixture(), NOW).forecast, true);
  assert.match(renderPilot(fixture({ status: 'stale' }), NOW), /Outlook paused/);
  assert.doesNotMatch(renderPilot(fixture({ status: 'stale' }), NOW), /class="pilot-week"/);
});

test('a run crossing the epidemiological week boundary cannot relabel past targets as next week', () => {
  const oldOrigin = fixture({ generated_at: '2026-09-05T23:00:00Z', origin_week: '2026-08-30' });
  assert.equal(pilotState(oldOrigin, NOW).status, 'stale');
  assert.deepEqual(forecastRows(oldOrigin, NOW), []);
});

test('forecast output requires all four unique targets, finite ordered bounds and matching calendar weeks', () => {
  assert.equal(forecastRows(fixture(), NOW).length, 4);
  for (const change of [{ lower: 1000 }, { point: NaN }, { upper: null }, { lower: -1 }, { week: '2026-09-07' }, { horizon_weeks: 2 }]) {
    const data = fixture(); data.forecasts[0] = { ...data.forecasts[0], ...change };
    assert.deepEqual(forecastRows(data, NOW), []);
  }
  const data = fixture(); data.forecasts.pop();
  assert.deepEqual(forecastRows(data, NOW), []);
});

test('history excludes incomplete weeks and invalid counts without changing missing values to zero', () => {
  const data = fixture();
  data.history.push({ week: '2026-09-06', cases: 1 }, { week: '2026-08-02', cases: null }, { week: '2026-07-26', cases: Infinity }, { week: '2026-02-30', cases: 100 });
  assert.equal(historyRows(data).length, 3);
  assert.equal(number(null), 'Unavailable'); assert.equal(number(undefined), 'Unavailable');
  assert.equal(number(0), '0');
  assert.equal(dateTime('2026-02-30'), null);
  assert.match(renderPilot(data, NOW), /<td>Unavailable<\/td>/);
});

test('the chart has accessible descriptions and splits missing observation weeks', () => {
  const data = fixture(); data.history.splice(1, 1);
  const html = chartHTML(data, NOW);
  assert.match(html, /aria-labelledby="dengueChartTitle dengueChartDesc"/);
  assert.match(html, /Exact forecast values and an accessible history table follow/);
  assert.equal((html.match(/stroke="#123f50" stroke-width="2.4"/g) || []).length, 2);
  assert.doesNotMatch(html, /NaN|Infinity/);
  assert.match(renderPilot(data, NOW), /Read the chart as a table/);
});

test('evaluation shows poor model skill and coverage, never recasts errors as accuracy', () => {
  const html = evaluationHTML(fixture());
  assert.match(html, /20.0% higher error/);
  assert.match(html, /72.0%/);
  assert.match(html, /development benchmark, not prospective validation/);
  assert.match(html, /Last reported week/);
  assert.equal(skillLabel(0), 'No improvement');
  assert.equal(skillLabel(0.1), '10.0% lower error');
  assert.equal(skillLabel(null), 'Unavailable');
});

test('reporting revision context distinguishes notifications and upstream nowcast', () => {
  const html = renderPilot(fixture(), NOW);
  assert.match(html, /95 notifications and an upstream nowcast of 227/);
  assert.match(html, /not an observed count or an input to this pilot/);
  assert.match(html, /0 gaps in weekly coverage/);
  assert.match(html, /80% empirical range/);
  assert.match(html, /Google Trends/);
  assert.match(html, /Access required · not connected/);
});

test('source strings and model metadata cannot inject HTML, scripts or unsafe navigation', () => {
  const data = fixture({ source: { name: '<img src=x onerror=alert(1)>', url: 'javascript:alert(1)' }, model: { label: '<script>alert(1)</script>' }, limitations: ['<iframe src=x>'] });
  data.evaluation.design = '<svg onload=bad()>';
  const html = renderPilot(data, NOW);
  assert.doesNotMatch(html, /<script|<img|<iframe|href="javascript:/);
  assert.match(html, /&lt;script&gt;/); assert.match(html, /&lt;svg onload=bad\(\)&gt;/);
  for (const url of ['javascript:alert(1)', 'data:text/html,x', '//example.com', 'https://user:pass@example.com']) assert.equal(safeURL(url), '');
  assert.equal(safeURL('https://example.com/path'), 'https://example.com/path');
});

test('unavailable payload keeps source failure notes and retry visible', () => {
  const html = renderPilot(fixture({ status: 'unavailable', data_quality: { notes: ['Source timeout.'] } }), NOW);
  assert.match(html, /Source timeout/); assert.match(html, /data-dengue-retry/);
  assert.doesNotMatch(html, /class="pilot-week"/);
});

test('bounded JSON loader rejects non-JSON errors and oversized responses', async () => {
  const { Response } = globalThis;
  await assert.rejects(readJSON(new Response('bad', { status: 503 })), /HTTP 503/);
  await assert.rejects(readJSON(new Response('<html>')), /Unexpected token/);
  await assert.rejects(readJSON(new Response('{}', { headers: { 'content-length': '9999' } }), 10), /too large/);
  await assert.rejects(readJSON(new Response('abcdefghijklmnop'), 10), /too large/);
  assert.deepEqual(await readJSON(new Response('{"value":1}')), { value: 1 });
});
