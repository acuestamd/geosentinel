/* GeoSentinel evidence workspace. Pure selectors are shared with Node tests. */
(function (root) {
  'use strict';
  const SOURCES = { who: 'WHO', paho: 'PAHO', news: 'GDELT / news', mastodon: 'Mastodon', reddit: 'Reddit' };
  const DEFAULT_FILTERS = { search: '', source: 'all', time: '30d', triage: 'review', unlocated: false };
  const EVIDENCE = { official: 'Official source', media: 'Media report', community: 'Community report' };
  const REASONS = {
    explicit_event_language: 'The report uses language describing a possible current health event.',
    event_location_match: 'A location was matched near the event description; this match requires review.',
    explicit_end_of_event: 'The report explicitly describes an event as ended or resolved.',
    explicit_negation: 'The report contains a negative statement about the suspected event.',
    historical_research_or_simulation: 'The text concerns historical research, retrospective analysis or a simulation.',
    historical_year_reference: 'The event refers to an earlier year, even though the report may be recent.',
    background_prevention_or_research: 'The text mainly concerns background, prevention or research.',
    official_outbreak_notice_without_event_detail: 'An official outbreak notice was found, but the event details need review.',
    no_explicit_current_event: 'The text does not clearly describe a current event.',
    location_not_resolved: 'No location could be matched with sufficient specificity.',
    only_incidental_locations: 'The named locations appear incidental to the health event.',
    multiple_event_countries: 'More than one event country is mentioned; no single location was selected.',
    country_level_multiple_places: 'Several places are mentioned within one country. The map uses country-level context.',
    multiple_event_places: 'Several event locations are mentioned; no single map pin was selected.',
    no_recognized_disease: 'No disease in the current recognition vocabulary was identified.',
    multiple_distinct_event_assertions: 'The report describes multiple events that cannot safely be reduced to one signal.',
    multiple_diseases_without_unique_event: 'Several diseases are mentioned without a unique event association.',
    ambiguous_congo_name: 'The name Congo is ambiguous, so no specific country was assumed.',
    explicit_zero_current_reporting_window: 'The report explicitly records zero cases in its current reporting window.'
  };
  const reasonText = reason => typeof reason === 'string' ? REASONS[reason] || reason.replace(/_/g, ' ') : JSON.stringify(reason);
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  function safeURL(value) {
    try { const url = new URL(String(value)); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; }
    catch (_) { return ''; }
  }
  function publicationTime(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value)) return null;
    const time = Date.parse(value);
    return Number.isFinite(time) ? time : null;
  }
  function locationOf(signal) {
    const loc = signal && signal.location;
    if (!loc || typeof loc.lat !== 'number' || typeof loc.lng !== 'number' || !Number.isFinite(loc.lat) || !Number.isFinite(loc.lng) || Math.abs(loc.lat) > 90 || Math.abs(loc.lng) > 180) return null;
    return loc;
  }
  function locationLabel(loc) {
    if (!loc) return 'Location unresolved';
    const name = String(loc.name || ''), country = String(loc.country || '');
    return name && country && name.toLowerCase() !== country.toLowerCase() ? `${name}, ${country}` : name || country || 'Reported coordinates';
  }
  function evidenceOf(signal) {
    return Object.hasOwn(EVIDENCE, signal.evidence_level) ? signal.evidence_level : ['who', 'paho'].includes(signal.source) ? 'official' : signal.source === 'news' ? 'media' : 'community';
  }
  function triageOf(signal) {
    if (['review', 'context'].includes(signal.triage)) return signal.triage;
    return ['context', 'resolved', 'negated'].includes(signal.event_status) ? 'context' : 'review';
  }
  function filterSignals(signals, filters = DEFAULT_FILTERS, now = Date.now()) {
    const f = { ...DEFAULT_FILTERS, ...filters };
    const query = f.search.trim().toLocaleLowerCase();
    const duration = { '24h': 86400000, '7d': 604800000, '30d': 2592000000 }[f.time];
    return (Array.isArray(signals) ? signals : []).filter(signal => {
      if (f.source !== 'all' && signal.source !== f.source) return false;
      if (f.triage !== 'all' && triageOf(signal) !== f.triage) return false;
      if (f.unlocated && locationOf(signal)) return false;
      const published = publicationTime(signal.published);
      if (f.time === 'unknown' && published !== null) return false;
      if (duration && (published === null || published > now + 300000 || now - published > duration)) return false;
      if (query) {
        const loc = signal.location || {};
        const haystack = [signal.disease, signal.original_title, signal.summary, loc.name, loc.country, signal.provenance?.publisher, signal.source].filter(Boolean).join(' ').toLocaleLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    }).sort((a, b) => (publicationTime(b.published) ?? -Infinity) - (publicationTime(a.published) ?? -Infinity));
  }
  function groupLocations(signals) {
    const groups = new Map();
    for (const signal of signals) {
      const loc = locationOf(signal);
      if (!loc) continue;
      const key = [String(loc.name || '').toLocaleLowerCase(), String(loc.country || '').toLocaleLowerCase(), loc.lat.toFixed(4), loc.lng.toFixed(4)].join('|');
      if (!groups.has(key)) groups.set(key, { key, location: loc, label: locationLabel(loc), signals: [] });
      groups.get(key).signals.push(signal);
    }
    return [...groups.values()].sort((a, b) => b.signals.length - a.signals.length || a.label.localeCompare(b.label));
  }
  function summarize(signals) {
    const locations = groupLocations(signals);
    const bySource = {}, byDisease = {}, byEvidence = {}, byEventStatus = {};
    for (const signal of signals) {
      for (const [target, key] of [[bySource, signal.source || 'unknown'], [byDisease, signal.disease || 'Unspecified'], [byEvidence, evidenceOf(signal)], [byEventStatus, signal.event_status || 'uncertain']]) target[key] = (target[key] || 0) + 1;
    }
    return { total: signals.length, official: byEvidence.official || 0, unlocated: signals.filter(s => !locationOf(s)).length, locations, bySource, byDisease, byEvidence, byEventStatus };
  }
  function contextValue(value, unit, decimals = 1) {
    return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(decimals)}${unit}` : 'Unavailable';
  }
  function outlookHTML(signal) {
    const context = signal.context || {}, weather = context.weather || {}, mobility = context.mobility || {}, forecast = context.forecast || {}, profile = context.profile || {};
    const recent = weather.periods?.recent || {}, next = weather.periods?.forecast || {};
    const available = ['available', 'partial'].includes(weather.status);
    const needsLocality = weather.status === 'needs_locality';
    const weatherLabels = { available: 'Model data available', partial: 'Partial model data', deferred: 'Awaiting collection', needs_locality: 'Locality needed', unavailable: 'Data unavailable', not_requested: 'Not collected' };
    const periodLabel = period => period.start && period.end ? `${String(period.start).slice(5)} – ${String(period.end).slice(5)}` : '';
    const weatherURL = safeURL(weather.source_url), referenceURL = safeURL(profile.reference_url);
    const required = Array.isArray(forecast.required_inputs) ? forecast.required_inputs : [];
    const weatherNote = available ? weather.relevance_note || 'Weather model data provide environmental context. They do not predict outbreak severity.' : needsLocality ? 'A city or local area is needed to attach weather data. Country-level coordinates are too broad for a local atmospheric assessment.' : weather.error || 'No weather model data are attached to this report. A forecast cannot assume missing observations are zero.';
    const table = available ? `<table class="weather-table"><thead><tr><th scope="col">Atmospheric factor</th><th scope="col">Recent 7 days<small>${escapeHTML(periodLabel(recent))}</small></th><th scope="col">Next 7 days<small>${escapeHTML(periodLabel(next))}</small></th></tr></thead><tbody><tr><td>Mean temperature</td><td>${contextValue(recent.temperature_mean_c, ' °C')}</td><td>${contextValue(next.temperature_mean_c, ' °C')}</td></tr><tr><td>Total rainfall</td><td>${contextValue(recent.precipitation_total_mm, ' mm')}</td><td>${contextValue(next.precipitation_total_mm, ' mm')}</td></tr><tr><td>Mean humidity</td><td>${contextValue(recent.relative_humidity_mean_pct, '%', 0)}</td><td>${contextValue(next.relative_humidity_mean_pct, '%', 0)}</td></tr></tbody></table>` : '';
    const inputs = required.length ? required.map(input => typeof input === 'string' ? input : input.label || input.name || input.description || JSON.stringify(input)) : ['A local case time series with a known reporting baseline', 'A disease-specific model calibrated against observed outcomes', 'Local exposure, population and response data'];
    return `<section class="outlook" aria-labelledby="outlook-title"><div class="outlook-header"><div><h3 id="outlook-title">Outlook &amp; drivers</h3><p>${escapeHTML(profile.label || 'Forecast readiness')}</p></div><a class="outlook-link" href="https://github.com/acuestamd/project-geosentinel/blob/main/docs/METHODOLOGY.md" target="_blank" rel="noopener noreferrer">Method ↗</a></div><div class="outlook-status"><strong>No calibrated outbreak forecast</strong><p>${escapeHTML(forecast.reason || 'Available source reports do not support an estimated outbreak probability, future case count or severity forecast.')}</p></div><section class="driver-block"><div class="driver-heading"><h4>Environmental context</h4><span class="driver-state ${weather.status === 'available' ? 'available' : ''}">${escapeHTML(weatherLabels[weather.status] || 'Not collected')}</span></div><p class="driver-note">${escapeHTML(weatherNote)}</p>${table}${available ? `<p class="driver-source">${escapeHTML(weather.location?.name || 'Reported locality')} · weather model, not a local station measurement.${weatherURL ? ` <a href="${escapeHTML(weatherURL)}" target="_blank" rel="noopener noreferrer">${escapeHTML(weather.source || 'Weather source')} ↗</a>` : ''}${weather.generated_at ? `<br>Retrieved ${escapeHTML(String(weather.generated_at))}` : ''}</p>` : ''}${weather.report_timing_note ? `<p class="driver-source">${escapeHTML(weather.report_timing_note)}</p>` : ''}</section><section class="driver-block"><div class="driver-heading"><h4>Air travel &amp; mobility</h4><span class="driver-state">Not connected</span></div><p class="driver-note">${escapeHTML(mobility.reason || 'Current routes, passenger volumes and travel dates are not connected. Geographic proximity or a static route map cannot establish importation risk.')}</p></section><section class="driver-block"><div class="driver-heading"><h4>Inputs still needed</h4><span class="driver-state">Before estimation</span></div>${profile.description ? `<p class="driver-note">${escapeHTML(profile.description)}</p>` : ''}<ul class="input-list">${inputs.map(input => `<li>${escapeHTML(input)}</li>`).join('')}</ul>${referenceURL ? `<p class="driver-source"><a href="${escapeHTML(referenceURL)}" target="_blank" rel="noopener noreferrer">Disease and forecasting reference ↗</a></p>` : ''}</section></section>`;
  }
  function collectionState(data, { now = Date.now(), offline = false, failed = false } = {}) {
    if (offline) return { label: 'Offline', className: 'error', message: 'Your browser is offline. The ledger shows the last data loaded in this session; it may be out of date.' };
    if (failed) return { label: data ? 'Refresh failed' : 'Data unavailable', className: 'error', message: data ? 'The latest refresh failed. The previous dataset remains visible. Use Refresh to try again.' : 'Collection data could not be loaded. Use Refresh to try again, or check the project run history.' };
    if (!data) return { label: 'Checking feeds', className: 'warn', message: '' };
    if (data.health?.status === 'unavailable') return { label: 'Collection unavailable', className: 'error', message: 'No collection source is currently available. Any retained reports may be old; check source details before reviewing.' };
    const timestamp = publicationTime(data.lastSuccessfulScan || data.lastScan);
    if (timestamp === null || now - timestamp > 7200000 || timestamp > now + 300000) return { label: 'Collection overdue', className: 'warn', message: 'No recent successful collection can be confirmed. Reports may be stale. The scheduled interval is a target, not a freshness guarantee.' };
    if (data.health?.status === 'degraded') return { label: 'Partial coverage', className: 'warn', message: 'One or more feeds returned incomplete data or failed. A missing signal can reflect a collection gap.' };
    if (data.health?.status === 'healthy') return { label: 'Collection current', className: 'ok', message: '' };
    return { label: 'Health unreported', className: 'warn', message: 'This dataset does not include source health. Collection completeness cannot be confirmed.' };
  }
  const api = { DEFAULT_FILTERS, escapeHTML, safeURL, publicationTime, locationOf, locationLabel, evidenceOf, triageOf, filterSignals, groupLocations, summarize, collectionState, contextValue, outlookHTML };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.GeoSentinel = api;
  if (typeof document === 'undefined') return;

  const $ = id => document.getElementById(id);
  const state = { data: null, filters: { ...DEFAULT_FILTERS }, visible: [], summary: summarize([]), failed: false, loading: false, map: null, layer: null, firstFit: true, detailIndex: null, origin: null, view: 'ledger', tileErrors: 0 };
  const fmtNumber = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('en') : '—';
  function dateLabel(value, includeTime = false) {
    const time = publicationTime(value);
    if (time === null) return 'Publication date unknown';
    return new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', ...(includeTime ? { hour: '2-digit', minute: '2-digit', timeZoneName: 'short', timeZone: 'UTC' } : { timeZone: 'UTC' }) }).format(time);
  }
  function ageLabel(value) {
    const timestamp = publicationTime(value);
    if (timestamp === null) return 'unknown';
    const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 1440) return `${Math.floor(minutes / 60)} hr ago`;
    return `${Math.floor(minutes / 1440)} days ago`;
  }
  function titleOf(signal) { return signal.original_title || signal.summary || `${signal.disease || 'Health signal'} — ${locationLabel(signal.location)}`; }
  function indexOf(signal) { return state.data.signals.indexOf(signal); }
  function countChart(title, values, labels = {}) {
    const items = Object.entries(values).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...items.map(([, count]) => count));
    return `<section class="chart-group"><h3>${escapeHTML(title)}</h3>${items.map(([key, count]) => `<div class="chart-row"><div class="chart-label"><span>${escapeHTML(labels[key] || key.replace(/_/g, ' '))}</span><span class="mono">${count}</span></div><div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${count / max * 100}%"></div></div></div>`).join('')}</section>`;
  }
  function renderHealth() {
    const health = collectionState(state.data, { offline: navigator.onLine === false, failed: state.failed });
    $('healthStatus').textContent = health.label;
    $('healthStatus').className = `status ${health.className}`;
    const healthExpanded = $('healthToggle').getAttribute('aria-expanded') === 'true';
    $('healthNotice').hidden = !health.message || (health.label === 'Partial coverage' && !healthExpanded);
    $('healthNotice').textContent = health.message;
    $('healthNotice').className = `notice ${health.className === 'error' ? 'error' : ''}`;
    if (!state.data) {
      if (state.failed) $('scanTime').textContent = 'No dataset loaded';
      return;
    }
    const data = state.data;
    const latest = data.lastScan;
    $('scanTime').textContent = `Latest attempt ${ageLabel(latest)}`;
    $('scanTime').title = publicationTime(latest) === null ? 'Collection time unknown' : dateLabel(latest, true);
    const sourceRecords = Array.isArray(data.health?.sources) ? data.health.sources : [];
    const records = Object.entries(SOURCES).map(([id, name]) => sourceRecords.find(s => s.id === id || (id === 'news' && s.id === 'gdelt')) || { id, name, status: 'unknown' });
    $('sourceMini').innerHTML = records.map(source => {
      const id = source.id === 'gdelt' ? 'news' : source.id;
      const cls = source.status === 'ok' ? health.className === 'ok' ? 'ok' : 'warn' : source.status === 'error' ? 'error' : 'warn';
      const status = source.status === 'ok' ? 'available' : source.status === 'disabled' ? 'disabled' : source.status === 'error' ? 'failed' : source.status || 'unknown';
      return `<span class="source-mini-item" title="${escapeHTML(status)}"><span class="source-dot ${cls}" aria-hidden="true"></span>${escapeHTML(id === 'news' ? 'GDELT' : SOURCES[id] || source.name || id)}${source.status === 'error' ? ' !' : source.status === 'disabled' ? ' –' : ''}<span class="sr-only">: ${escapeHTML(status)}</span></span>`;
    }).join('');
    $('sourceHealth').innerHTML = records.map(source => {
      const id = source.id === 'gdelt' ? 'news' : source.id;
      const labels = { ok: 'Available', partial: 'Partial', error: 'Failed', disabled: 'Disabled', unknown: 'Unknown' };
      // An old successful source status is historical, never a green live indicator.
      const cls = source.status === 'ok' ? health.className === 'ok' ? 'ok' : 'warn' : source.status === 'error' ? 'error' : 'warn';
      const isCounted = ['ok', 'partial'].includes(source.status);
      const caption = isCounted ? `${fmtNumber(source.items ?? source.signals)} items collected` : source.status === 'disabled' ? 'Not configured' : source.status === 'error' ? 'Collection interrupted' : 'No collection report';
      return `<div class="source-cell"><div><div class="source-name"><span class="source-dot ${cls}" aria-hidden="true"></span>${escapeHTML(id === 'news' ? 'GDELT' : SOURCES[id] || source.name || id)}</div><div class="source-caption">${escapeHTML(caption)}</div></div><span class="source-state">${escapeHTML(labels[source.status] || 'Unknown')}</span></div>`;
    }).join('');
    const success = data.lastSuccessfulScan;
    $('healthDetail').innerHTML = `<p>Collection attempts run on a 30-minute schedule. Counts below describe collection across all sources; the evidence workspace below follows your filters. Last successful collection: <strong>${publicationTime(success) === null ? 'not reported' : escapeHTML(dateLabel(success, true))}</strong>.</p><ul>${records.map(source => {
      const errors = Array.isArray(source.errors) ? source.errors : [];
      return `<li><strong>${escapeHTML(source.name || SOURCES[source.id] || source.id)}:</strong> ${escapeHTML(source.status || 'unknown')} · ${fmtNumber(source.items)} items · ${fmtNumber(source.signals)} extracted signals. Last success: ${publicationTime(source.last_success) === null ? 'not reported' : escapeHTML(dateLabel(source.last_success, true))}${errors.length ? `<br>${errors.map(error => escapeHTML(String(error))).join('<br>')}` : ''}</li>`;
    }).join('')}</ul><p style="margin-top:12px">Disabled feeds do not contribute coverage. Official provenance does not establish that automated extraction, classification or geolocation is correct.</p>`;
  }
  function renderLedger() {
    if (!state.data) return;
    const records = state.visible;
    if (!records.length) {
      $('ledger').innerHTML = `<div class="empty"><h3>No reports in this view</h3><p>Try a wider report-date window, include context reports or clear your search. Missing reports do not establish that a location is safe.</p><button class="btn" data-reset>Reset filters</button></div>`;
    } else {
      $('ledger').innerHTML = records.map(signal => {
        const evidence = evidenceOf(signal);
        const published = publicationTime(signal.published) === null ? 'Date unknown' : `${dateLabel(signal.published)}${signal.date_basis === 'gdelt_index' ? ' · indexed' : ''}`;
        return `<button type="button" class="record" data-record="${indexOf(signal)}" aria-label="Review ${escapeHTML(titleOf(signal))}"><span class="record-top"><span class="evidence ${evidence}">${EVIDENCE[evidence]}</span><span class="record-source">${escapeHTML(SOURCES[signal.source] || signal.source || 'Unknown source')}</span><span class="record-date mono">${escapeHTML(published)}</span></span><span class="record-title">${escapeHTML(titleOf(signal))}</span><span class="record-bottom"><span class="disease">${escapeHTML(signal.disease || 'Unspecified')}</span><span aria-hidden="true">·</span><span>${escapeHTML(locationLabel(locationOf(signal)))}</span>${triageOf(signal) === 'context' ? `<span>· ${escapeHTML((signal.event_status || 'context').replace(/_/g, ' '))}</span>` : ''}${['available', 'partial'].includes(signal.context?.weather?.status) ? '<span class="driver-tag">Weather context</span>' : ''}<span class="record-arrow" aria-hidden="true">→</span></span></button>`;
      }).join('');
    }
    const summary = state.summary;
    $('analytics').innerHTML = records.length ? countChart('Source composition', summary.bySource, SOURCES) + countChart('Reported diseases', summary.byDisease) + countChart('Automated event classification', summary.byEventStatus) + '<p class="analysis-note">Counts represent extracted signals in this filtered view. They are not case counts, outbreak estimates or independently corroborated events.</p>' : '<div class="empty"><h3>No reports to analyze</h3><p>Adjust the filters to include more source reports.</p></div>';
  }
  function renderLocations() {
    const groups = state.summary.locations;
    $('locationCount').textContent = fmtNumber(groups.length);
    $('locationList').innerHTML = groups.length ? groups.map((group, index) => `<button class="location-chip" data-location="${index}" aria-label="Show ${escapeHTML(group.label)}, ${group.signals.length} signals on map"><span>${escapeHTML(group.label)}</span><b>${group.signals.length}</b></button>`).join('') : '<span style="font-size:13px;color:var(--muted)">No usable locations in this view.</span>';
    $('unlocatedNote').innerHTML = state.filters.unlocated ? 'Showing reports without usable coordinates. <button data-unlocated="false">Show all locations again</button>.' : state.summary.unlocated ? `${state.summary.unlocated} report${state.summary.unlocated === 1 ? '' : 's'} cannot be placed on the map. <button data-unlocated="true">Review unlocated reports</button>.` : 'Reported coordinates are automated matches, not confirmed outbreak sites.';
    if (!state.map) return;
    state.layer.clearLayers();
    groups.forEach((group, index) => {
      const evidence = group.signals.some(s => evidenceOf(s) === 'official') ? 'official' : group.signals.some(s => evidenceOf(s) === 'media') ? 'media' : 'community';
      const icon = L.divIcon({ className: '', html: `<span class="map-pin ${evidence}">${group.signals.length}</span>`, iconSize: [29, 29], iconAnchor: [14, 14] });
      const marker = L.marker([group.location.lat, group.location.lng], { icon, title: `${group.label}: ${group.signals.length} signals`, keyboard: true }).addTo(state.layer);
      marker.bindPopup(`<div class="popup-title">${escapeHTML(group.label)}</div><p class="popup-caption">${group.signals.length} filtered signal${group.signals.length === 1 ? '' : 's'} · location requires review</p>${group.signals.slice(0, 8).map(signal => `<button class="popup-record" data-record="${indexOf(signal)}">${escapeHTML(signal.disease || 'Health signal')} · ${escapeHTML(SOURCES[signal.source] || signal.source)} →</button>`).join('')}${group.signals.length > 8 ? '<p class="popup-caption">Additional reports are in the evidence ledger.</p>' : ''}`, { maxWidth: 290 });
      group.marker = marker;
    });
    if (state.firstFit && groups.length) { fitMap(); state.firstFit = false; }
  }
  function fitMap() {
    if (!state.map) return;
    const groups = state.summary.locations;
    if (!groups.length) { state.map.setView([20, 10], 2, { animate: false }); return; }
    state.map.fitBounds(groups.map(g => [g.location.lat, g.location.lng]), { padding: state.map.getSize().x < 500 ? [20, 20] : [45, 45], maxZoom: groups.length === 1 ? 5 : 4, animate: false });
  }
  function render() {
    renderHealth();
    if (!state.data) return;
    state.visible = filterSignals(state.data.signals, state.filters);
    state.summary = summarize(state.visible);
    const summary = state.summary;
    $('metricSignals').textContent = fmtNumber(summary.total);
    $('metricOfficial').textContent = fmtNumber(summary.official);
    $('metricLocations').textContent = fmtNumber(summary.locations.length);
    $('metricUnlocated').textContent = fmtNumber(summary.unlocated);
    $('visibleCount').textContent = `${summary.total} records`;
    $('ledgerSubtitle').textContent = state.filters.triage === 'review' ? 'Review queue · automated selection, unverified' : state.filters.triage === 'context' ? 'Context, resolved or excluded source reports' : 'All collected signals · unverified';
    const undated = filterSignals(state.data.signals, { ...state.filters, time: 'unknown' }).length;
    const dateNote = ['30d', '7d', '24h'].includes(state.filters.time) && undated ? ` ${undated} undated report${undated === 1 ? ' is' : 's are'} excluded; <button data-undated>review unknown dates</button>.` : '';
    $('filterContext').innerHTML = `All workspace counts, map locations and analysis follow the filters.${dateNote}${state.filters.unlocated ? ' <strong>Unlocated reports only.</strong>' : ''}`;
    $('exportButton').disabled = false;
    renderLedger(); renderLocations();
    $('liveStatus').textContent = `${summary.total} filtered signals at ${summary.locations.length} usable locations; ${summary.unlocated} unlocated.`;
  }
  function showDetail(index, origin) {
    const signal = state.data?.signals[index];
    if (!signal) return;
    state.detailIndex = index;
    state.origin = origin;
    const evidence = evidenceOf(signal), loc = locationOf(signal), url = safeURL(signal.provenance?.url || signal.url);
    const rationale = Array.isArray(signal.rationale) ? signal.rationale : [];
    const candidates = Array.isArray(signal.location_candidates) ? signal.location_candidates : [];
    const candidateLabels = candidates.map(candidate => typeof candidate === 'string' ? candidate : locationLabel(candidate.location || candidate));
    const provenance = signal.provenance || {};
    const eventLabels = { active: 'Possible active event', resolved: 'Resolved / historical', negated: 'Negated statement', context: 'Context report', uncertain: 'Uncertain' };
    $('detailContent').innerHTML = `<span class="evidence ${evidence}">${EVIDENCE[evidence]}</span><h2 id="detailTitle">${escapeHTML(titleOf(signal))}</h2><p class="detail-deck">${escapeHTML(provenance.publisher || SOURCES[signal.source] || signal.source || 'Unknown publisher')} · ${escapeHTML(signal.disease || 'Unspecified health signal')}</p><div class="detail-actions">${url ? `<a class="btn btn-primary" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Read original source ↗</a>` : '<span class="detail-deck">No usable source URL was supplied.</span>'}${loc ? '<button class="btn" id="detailMapButton">Locate on map</button>' : ''}</div><div class="detail-warning"><strong>Unverified signal.</strong> An official source is a provenance category, not validation of this extraction. Read the original report before interpreting its disease, location or event status.</div><dl class="detail-grid"><div><dt>${signal.date_basis === 'gdelt_index' ? 'GDELT indexed date' : 'Source publication date'}</dt><dd>${escapeHTML(dateLabel(signal.published, Boolean(signal.published?.includes('T'))))}${signal.date_basis === 'gdelt_index' ? '<br><small>Index timestamp; publication date is unconfirmed.</small>' : ''}</dd></div><div><dt>Collected</dt><dd>${publicationTime(signal.retrieved_at) === null ? 'Collection time unknown' : escapeHTML(dateLabel(signal.retrieved_at, true))}</dd></div><div><dt>Reported location</dt><dd>${escapeHTML(locationLabel(loc))}</dd></div><div><dt>Automated classification</dt><dd>${escapeHTML(eventLabels[signal.event_status] || 'Uncertain')}</dd></div><div><dt>Review scope</dt><dd>${triageOf(signal) === 'review' ? 'Review queue' : 'Context / excluded'}</dd></div><div><dt>Source</dt><dd>${escapeHTML(SOURCES[signal.source] || signal.source || 'Unknown')}</dd></div></dl>${outlookHTML(signal)}<section class="detail-section"><h3>Why this report appears here</h3>${rationale.length ? `<ul>${rationale.map(reason => `<li>${escapeHTML(reasonText(reason))}</li>`).join('')}</ul>` : '<p>No classification rationale was supplied in this dataset. The report requires manual source review.</p>'}${!loc ? '<p style="margin-top:12px">No unambiguous, usable coordinates were supplied. This report has no map pin.</p>' : ''}${candidateLabels.length ? `<details class="detail-candidates"><summary>Location candidates (${candidateLabels.length})</summary><p>${candidateLabels.map(escapeHTML).join(' · ')}</p></details>` : ''}</section><section class="detail-section"><h3>Collected source text</h3><p>${escapeHTML(signal.summary || 'No source excerpt was supplied. Open the original report for context.')}</p></section><section class="detail-section"><h3>Source trail</h3><p>${escapeHTML(provenance.publisher || SOURCES[signal.source] || signal.source || 'Unknown publisher')}${provenance.query || signal.query ? `\nCollection query: ${escapeHTML(provenance.query || signal.query)}` : ''}${provenance.feed || provenance.feed_url ? `\nFeed: ${escapeHTML(provenance.feed || provenance.feed_url)}` : ''}</p><p class="detail-id mono" style="margin-top:12px">Document: ${escapeHTML(signal.document_id || signal.id || 'not supplied')}<br>Event candidate: ${escapeHTML(signal.event_id || 'not supplied')}</p></section>`;
    const dialog = $('detailDialog');
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
    $('closeDetail').focus();
    $('detailMapButton')?.addEventListener('click', () => {
      dialog.close();
      if (state.map && loc) state.map.setView([loc.lat, loc.lng], 5, { animate: false });
      $('map').scrollIntoView({ behavior: 'instant', block: 'center' });
      $('map').focus();
    });
  }
  function resetFilters() {
    state.filters = { ...DEFAULT_FILTERS };
    $('filterForm').reset();
    render();
  }
  function setView(view, focus = false) {
    state.view = view;
    for (const tab of document.querySelectorAll('[data-view]')) {
      const selected = tab.dataset.view === view;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    }
    $('ledger').hidden = view !== 'ledger'; $('analytics').hidden = view !== 'analytics';
  }
  let toastTimeout;
  function toast(message) { clearTimeout(toastTimeout); $('toast').textContent = message; $('toast').hidden = false; toastTimeout = setTimeout(() => { $('toast').hidden = true; }, 4000); }
  function exportView() {
    if (!state.data) return;
    const payload = { exported_at: new Date().toISOString(), project: 'GeoSentinel', schema_version: state.data.schema_version || 'unknown', scope: 'Filtered, unverified source signals. No independent validation or analyst adjudication is recorded.', filters: { ...state.filters }, dataset_last_scan: state.data.lastScan || null, dataset_last_successful_scan: state.data.lastSuccessfulScan || null, collection_health: state.data.health || null, signal_count: state.visible.length, signals: state.visible };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = `geosentinel-evidence-${new Date().toISOString().slice(0, 10)}.json`; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`Exported ${state.visible.length} signals with filters and source metadata.`);
  }
  async function loadData() {
    if (state.loading) return;
    state.loading = true; $('refreshButton').disabled = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(`signals.json?t=${Date.now()}`, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || !Array.isArray(data.signals) || data.signals.some(signal => !signal || typeof signal !== 'object')) throw new Error('Invalid dataset');
      state.data = data; state.failed = false; render();
    } catch (_) {
      state.failed = true; renderHealth();
      if (!state.data) {
        $('ledger').innerHTML = '<div class="empty"><h3>Collection data unavailable</h3><p>The dataset could not be loaded. Refresh to try again; source availability cannot currently be confirmed.</p><button class="btn" data-retry>Try again</button></div>';
        $('locationList').textContent = 'No dataset loaded.';
        $('liveStatus').textContent = 'Collection data unavailable. Use Refresh to try again.';
      }
    } finally { clearTimeout(timeout); state.loading = false; $('refreshButton').disabled = false; }
  }
  function initMap() {
    if (typeof L === 'undefined') {
      $('map').innerHTML = '<div class="map-fallback">The map library could not load. All reports and location details remain available in the evidence ledger.</div>';
      $('fitMap').disabled = true;
      return;
    }
    state.map = L.map('map', { center: [20, 10], zoom: 2, minZoom: 1, maxZoom: 13, maxBounds: [[-85, -180], [85, 180]], maxBoundsViscosity: 1, scrollWheelZoom: false, attributionControl: true, keyboard: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, noWrap: true, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors' }).on('tileerror', () => {
      state.tileErrors += 1;
      if (state.tileErrors === 3) toast('Some map tiles could not load. Source reports remain available.');
    }).addTo(state.map);
    state.map.attributionControl.setPrefix(false);
    state.layer = L.layerGroup().addTo(state.map);
    $('map').tabIndex = 0;
  }
  $('filterForm').addEventListener('submit', event => event.preventDefault());
  let searchTimeout;
  $('search').addEventListener('input', event => { clearTimeout(searchTimeout); searchTimeout = setTimeout(() => { state.filters.search = event.target.value; render(); }, 120); });
  for (const field of ['source', 'time', 'triage']) $(field).addEventListener('change', event => { state.filters[field] = event.target.value; render(); });
  $('resetButton').addEventListener('click', resetFilters);
  $('refreshButton').addEventListener('click', loadData);
  $('exportButton').addEventListener('click', exportView);
  $('fitMap').addEventListener('click', fitMap);
  $('healthToggle').addEventListener('click', () => { const show = $('healthDetail').hidden; $('healthDetail').hidden = !show; $('sourceHealth').hidden = !show; $('healthToggle').setAttribute('aria-expanded', String(show)); renderHealth(); });
  $('closeDetail').addEventListener('click', () => $('detailDialog').close());
  $('detailDialog').addEventListener('close', () => { state.origin?.focus(); });
  $('detailDialog').addEventListener('click', event => { if (event.target === $('detailDialog') && event.clientX < $('detailDialog').getBoundingClientRect().left) $('detailDialog').close(); });
  document.addEventListener('click', event => {
    const target = event.target.closest('button');
    if (!target) return;
    if (target.hasAttribute('data-record')) showDetail(Number(target.dataset.record), target);
    else if (target.hasAttribute('data-location')) {
      const group = state.summary.locations[Number(target.dataset.location)];
      if (group && state.map) { state.map.setView([group.location.lat, group.location.lng], 5, { animate: false }); group.marker?.openPopup(); }
    } else if (target.hasAttribute('data-reset')) resetFilters();
    else if (target.hasAttribute('data-retry')) loadData();
    else if (target.hasAttribute('data-unlocated')) { state.filters.unlocated = target.dataset.unlocated === 'true'; render(); }
    else if (target.hasAttribute('data-undated')) { state.filters.time = 'unknown'; $('time').value = 'unknown'; render(); }
    else if (target.dataset.view) setView(target.dataset.view);
  });
  document.querySelector('.view-tabs').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    setView(event.key === 'Home' ? 'ledger' : event.key === 'End' ? 'analytics' : state.view === 'ledger' ? 'analytics' : 'ledger', true);
  });
  window.addEventListener('offline', renderHealth);
  window.addEventListener('online', loadData);
  initMap(); loadData();
  setInterval(loadData, 120000);
  setInterval(renderHealth, 30000);
})(typeof globalThis !== 'undefined' ? globalThis : this);
