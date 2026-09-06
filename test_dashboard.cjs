'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { filterSignals, groupLocations, summarize, locationOf, collectionState, safeURL, escapeHTML, publicationTime, outlookHTML, contextValue } = require('./dashboard.js');
const NOW = Date.parse('2026-09-06T12:00:00Z');
const sample = overrides => ({ document_id: 'doc', original_title: 'Cholera report', disease: 'cholera', source: 'who', evidence_level: 'official', triage: 'review', event_status: 'active', published: '2026-09-06T08:00:00Z', location: { name: 'New York', country: 'United States', iso: 'US', lat: 40.71, lng: -74 }, ...overrides });
const all = { source: 'all', time: 'all', triage: 'all' };

test('source, publication, scope, text and unresolved location filters compose', () => {
  const records = [sample({ document_id: 'wanted', location: null, original_title: 'Cholera in a returning traveler' }), sample({ source: 'news' }), sample({ triage: 'context' }), sample({ published: '2025-01-01' }), sample({ document_id: 'mapped' })];
  const filtered = filterSignals(records, { source: 'who', time: '24h', triage: 'review', search: 'returning traveler', unlocated: true }, NOW);
  assert.deepEqual(filtered.map(s => s.document_id), ['wanted']);
});

test('unknown or invalid publication dates do not enter a recency window through retrieval time', () => {
  const records = [sample({ published: '', retrieved_at: '2026-09-06T12:00:00Z' }), sample({ published: 'yesterday' }), sample({ published: '2026-09-05T00:00:00Z' }), sample({ published: '2026-09-07T12:00:00Z' })];
  assert.equal(filterSignals(records, { ...all, time: '24h' }, NOW).length, 0);
  assert.equal(filterSignals(records, { ...all, time: 'unknown' }, NOW).length, 2);
  assert.equal(filterSignals(records, all, NOW).length, 4);
  assert.equal(publicationTime('2026-99-99'), null);
});

test('the 24-hour boundary uses source publication and dates sort newest first', () => {
  const records = [sample({ document_id: 'boundary', published: '2026-09-05T12:00:00Z' }), sample({ document_id: 'old', published: '2026-09-05T11:59:59Z' }), sample({ document_id: 'new', published: '2026-09-06T11:00:00Z' })];
  assert.deepEqual(filterSignals(records, { ...all, time: '24h' }, NOW).map(s => s.document_id), ['new', 'boundary']);
});

test('cities in the same country produce separate map locations', () => {
  const records = [sample(), sample({ location: { name: 'Los Angeles', country: 'United States', iso: 'US', lat: 34.05, lng: -118.24 } }), sample({ disease: 'influenza' })];
  const groups = groupLocations(records);
  assert.equal(groups.length, 2);
  assert.equal(groups.find(g => g.location.name === 'New York').signals.length, 2);
  assert.equal(groups.find(g => g.location.name === 'Los Angeles').signals.length, 1);
});

test('missing, non-finite and invalid coordinates remain in the ledger without invented pins', () => {
  const locations = [null, {}, { lat: null, lng: null }, { lat: '40', lng: '-74' }, { lat: Infinity, lng: 0 }, { lat: 91, lng: 0 }];
  const records = locations.map(location => sample({ location }));
  records.forEach(record => assert.equal(locationOf(record), null));
  const result = summarize(records);
  assert.equal(result.total, 6); assert.equal(result.unlocated, 6); assert.equal(result.locations.length, 0);
  assert.ok(locationOf(sample({ location: { lat: 0, lng: 0 } })));
});

test('all analysis and map totals derive from the exact same filtered signal array', () => {
  const records = [sample(), sample({ source: 'news', evidence_level: 'media' }), sample({ triage: 'context', location: null })];
  const filtered = filterSignals(records, { source: 'who', time: '24h', triage: 'review' }, NOW);
  const result = summarize(filtered);
  assert.equal(result.total, 1); assert.equal(result.official, 1); assert.equal(result.locations.length, 1);
  assert.deepEqual(result.bySource, { who: 1 });
  assert.equal(Object.values(result.byDisease).reduce((sum, n) => sum + n, 0), result.total);
  const empty = summarize(filterSignals(records, { source: 'reddit' }, NOW));
  assert.equal(empty.total, 0); assert.equal(empty.locations.length, 0); assert.deepEqual(empty.bySource, {});
});

test('old successful collection, offline and failed refresh never show a green current state', () => {
  const recent = { lastScan: '2026-09-06T11:59:00Z', lastSuccessfulScan: '2026-09-06T11:59:00Z', health: { status: 'healthy' } };
  assert.equal(collectionState(recent, { now: NOW }).className, 'ok');
  const old = { ...recent, lastSuccessfulScan: '2026-09-06T08:00:00Z' };
  assert.equal(collectionState(old, { now: NOW }).className, 'warn');
  assert.equal(collectionState(recent, { now: NOW, offline: true }).className, 'error');
  assert.equal(collectionState(recent, { now: NOW, failed: true }).className, 'error');
  assert.equal(collectionState({ ...recent, health: { status: 'degraded' } }, { now: NOW }).className, 'warn');
  assert.equal(collectionState({ ...recent, health: { status: 'unavailable' } }, { now: NOW }).className, 'error');
  assert.equal(collectionState({ lastScan: recent.lastScan }, { now: NOW }).className, 'warn');
});

test('source URLs and source text cannot become executable dashboard markup', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', '//example.com', '/local/path', '']) assert.equal(safeURL(value), '');
  assert.equal(safeURL('https://example.com/a?q=test'), 'https://example.com/a?q=test');
  assert.equal(escapeHTML('<img src=x onerror="bad()">'), '&lt;img src=x onerror=&quot;bad()&quot;&gt;');
});


test('environmental context renders actual units and never turns missing data into zero', () => {
  const html = outlookHTML(sample({ context: { weather: { status: 'partial', source: 'Open-Meteo', source_url: 'https://open-meteo.com/', periods: { recent: { temperature_mean_c: 27.2, precipitation_total_mm: null, relative_humidity_mean_pct: 81 }, forecast: { temperature_mean_c: 28.1, precipitation_total_mm: 0, relative_humidity_mean_pct: null } } }, forecast: { status: 'not_estimated', required_inputs: ['Local case incidence'] } } }));
  assert.match(html, /Partial model data/);
  assert.match(html, /27.2 °C/); assert.match(html, /81%/); assert.match(html, /0.0 mm/);
  assert.match(html, /Unavailable/); assert.match(html, /No calibrated outbreak forecast/);
  assert.match(html, /Local case incidence/);
  assert.equal(contextValue(null, ' mm'), 'Unavailable');
  assert.equal(contextValue(undefined, '%'), 'Unavailable');
  assert.equal(contextValue(NaN, ' °C'), 'Unavailable');
});

test('country-level reports explain missing locality and mobility without fabricating a forecast', () => {
  const html = outlookHTML(sample({ context: { weather: { status: 'needs_locality' }, mobility: { status: 'not_connected' }, forecast: { status: 'not_estimated' } } }));
  assert.match(html, /Locality needed/); assert.match(html, /Country-level coordinates are too broad/);
  assert.match(html, /Current routes, passenger volumes and travel dates are not connected/);
  assert.doesNotMatch(html, /weather-table/);
  assert.match(html, /No calibrated outbreak forecast/);
});
