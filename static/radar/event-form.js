// Create/Edit Event: event-type panels, the 3-category limit, the map pin, the live preview card and checklist.
(() => {
  const form = document.querySelector('.event-form');
  if (!form) return;
  const $ = (name) => form.elements[name];
  const readJson = (id) => JSON.parse(document.getElementById(id)?.textContent || 'null');
  const verified = new Set(readJson('verified-slugs') || []);
  const venuePoints = readJson('venue-points') || {};
  const center = readJson('map-center') || { lat: 40.102, lng: -88.2272 };

  // Event type: show only the matching panel.
  const kind = () => form.querySelector('input[name="kind"]:checked')?.value || 'rsvp';
  const showKind = () => form.querySelectorAll('.kind-panel').forEach((panel) => { panel.hidden = panel.dataset.kind !== kind(); });

  // Categories: at most three.
  const chips = [...form.querySelectorAll('.chips input[type="checkbox"]')];
  const limitChips = () => {
    const full = chips.filter((c) => c.checked).length >= 3;
    chips.forEach((c) => { c.disabled = full && !c.checked; });
  };

  // Host note: verified badge or a nudge to request verification.
  const hostNote = document.getElementById('host-note');
  const showHost = () => {
    const select = $('host');
    if (!select || !hostNote) return;
    if (select.value === 'me') hostNote.textContent = 'Posted under your name as a campus member.';
    else if (verified.has(select.value)) hostNote.textContent = '✓ Verified organization. The event shows the verified badge.';
    else hostNote.textContent = 'Not verified yet. The event still publishes, without the badge. Owners can request verification on the organization page.';
  };

  // Map pin (Leaflet loads with defer, so wait for it).
  let map, marker;
  const lat = $('latitude'), lng = $('longitude');
  const clearButton = document.getElementById('clear-pin');
  const placePin = (point, pan) => {
    lat.value = point.lat.toFixed(6);
    lng.value = point.lng.toFixed(6);
    if (map) {
      if (marker) marker.setLatLng(point); else marker = L.marker(point).addTo(map);
      if (pan) map.setView(point, 17);
    }
    clearButton.hidden = false;
    update();
  };
  const clearPin = () => {
    lat.value = ''; lng.value = '';
    if (marker) { marker.remove(); marker = null; }
    clearButton.hidden = true;
    update();
  };
  const startMap = () => {
    if (!window.L) return;
    const start = lat.value && lng.value ? { lat: +lat.value, lng: +lng.value } : center;
    map = L.map('pin-map', { scrollWheelZoom: false }).setView(start, lat.value ? 17 : 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    if (lat.value && lng.value) placePin(start, false);
    map.on('click', (e) => placePin(e.latlng, false));
  };
  clearButton?.addEventListener('click', clearPin);
  $('venue')?.addEventListener('change', (e) => {
    const point = venuePoints[e.target.value];
    if (point && !lat.value) placePin(point, true);
  });

  // Cover preview.
  const coverInput = $('cover');
  let coverUrl = null;
  coverInput?.addEventListener('change', () => {
    const file = coverInput.files[0];
    if (coverUrl) URL.revokeObjectURL(coverUrl);
    coverUrl = file ? URL.createObjectURL(file) : null;
    for (const box of [document.getElementById('cover-preview'), document.getElementById('preview-cover')]) {
      box.querySelector('img')?.remove();
      if (coverUrl) { const img = document.createElement('img'); img.src = coverUrl; img.alt = ''; box.prepend(img); }
    }
    document.querySelector('#cover-preview span')?.toggleAttribute('hidden', !!coverUrl);
  });

  // Live preview and checklist.
  const text = (name) => ($(name)?.value || '').trim();
  const fmtTime = (value) => {
    if (!value) return '';
    const [h, m] = value.split(':').map(Number);
    return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
  };
  const update = () => {
    const title = text('title');
    document.getElementById('preview-title').textContent = title || 'Your event title';
    const day = text('date');
    document.getElementById('preview-date').textContent = day
      ? new Date(`${day}T12:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).toUpperCase()
      : 'DATE';
    const venue = $('venue');
    const venueName = venue && venue.value ? venue.options[venue.selectedIndex].text : '';
    const place = [venueName, text('location_text')].filter(Boolean).join(', ') || 'Location needed';
    const times = [fmtTime(text('start_time')), fmtTime(text('end_time'))].filter(Boolean).join(' – ') || 'Time needed';
    document.getElementById('preview-when').textContent = `${times} · ${place}`;
    const host = $('host');
    document.getElementById('preview-host').textContent = host && host.value !== 'me' ? `by ${host.options[host.selectedIndex].text}` : '';
    const tags = document.getElementById('preview-tags');
    tags.replaceChildren(...chips.filter((c) => c.checked).slice(0, 2).map((c) => {
      const span = document.createElement('span'); span.textContent = c.parentElement.textContent.trim(); return span;
    }), Object.assign(document.createElement('span'), { textContent: kind() === 'paid' ? (text('price_text') || 'Paid') : 'Free' }));

    const list = document.getElementById('checklist');
    if (!list) return;
    const checks = {
      title: !!title,
      description: !!text('description'),
      when: !!(day && text('start_time') && text('end_time')),
      where: !!(venueName || text('location_text')),
      categories: chips.some((c) => c.checked),
      price: kind() !== 'paid' || !!(text('price_text') && (text('external_url') || text('contact_info'))),
    };
    list.querySelector('[data-check="price"]').hidden = kind() !== 'paid';
    list.querySelectorAll('li').forEach((item) => item.classList.toggle('done', checks[item.dataset.check]));
  };

  form.addEventListener('input', update);
  form.addEventListener('change', (e) => {
    if (e.target.name === 'kind') showKind();
    if (e.target.name === 'interests') limitChips();
    if (e.target.name === 'host') showHost();
    update();
  });
  // Catch an end time before the start time here, so nothing is sent and nothing is lost.
  const endInput = $('end_time');
  const endError = document.createElement('p');
  endError.className = 'field-error';
  endError.id = 'end-time-check';
  endError.hidden = true;
  endError.textContent = 'The end time must be after the start time.';
  endInput?.closest('.field')?.append(endError);
  const checkTimes = () => {
    const start = text('start_time'), end = text('end_time');
    const bad = !!(start && end && end <= start);
    endError.hidden = !bad;
    endInput?.closest('.field')?.classList.toggle('has-error', bad);
    endInput?.setAttribute('aria-invalid', bad ? 'true' : 'false');
    if (bad) endInput?.setAttribute('aria-describedby', 'end-time-check'); else endInput?.removeAttribute('aria-describedby');
    return !bad;
  };
  endInput?.addEventListener('change', checkTimes);
  $('start_time')?.addEventListener('change', checkTimes);

  // Warn before leaving with unsaved changes.
  let dirty = false, submitting = false;
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });
  window.addEventListener('beforeunload', (e) => {
    if (dirty && !submitting) { e.preventDefault(); e.returnValue = ''; }
  });
  form.addEventListener('submit', (e) => {
    if (!checkTimes()) {
      e.preventDefault();
      endInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
      endInput.focus({ preventScroll: true });
      return;
    }
    submitting = true;
  });

  // After a save with mistakes, go straight to the first one.
  const firstError = form.querySelector('.has-error');
  if (firstError) {
    firstError.scrollIntoView({ block: 'center' });
    firstError.querySelector('input:not([type=hidden]),select,textarea')?.focus({ preventScroll: true });
  }

  showKind(); limitChips(); showHost(); update();
  if (window.L) startMap(); else window.addEventListener('load', startMap);
})();
