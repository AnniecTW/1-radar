// Explore Map: filters, the MapLibre map (category pins, popularity heatmap, map/satellite styles),
// and the result list beside it. Result cards come from the server (discovery/_map_results.html).
(() => {
  const config = window.RADAR_MAP;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- Filters -------------------------------------------------------------------------------
  const filterForm = document.querySelector('.map-filter-form');
  if (filterForm) {
    document.addEventListener('keydown', (event) => { if (event.key === 'Tab') document.body.classList.add('keyboard-focus-mode'); });
    document.addEventListener('pointerdown', () => document.body.classList.remove('keyboard-focus-mode'));
    // Indoors / Quiet events switch their own URL parameter, so they combine with the search text.
    filterForm.querySelectorAll('[data-toggle-param]').forEach((button) => button.addEventListener('click', () => {
      const url = new URL(location.href);
      const { toggleParam: param, toggleValue: value } = button.dataset;
      if (url.searchParams.get(param) === value) url.searchParams.delete(param); else url.searchParams.set(param, value);
      location.assign(url);
    }));
    const dateSelect = filterForm.querySelector('select[name="date"]');
    const dateCaption = dateSelect?.closest('.date-filter-content')?.querySelector('small');
    const syncDateCaption = () => { if (dateCaption && dateSelect?.selectedOptions[0]) dateCaption.textContent = dateSelect.selectedOptions[0].dataset.caption || ''; };
    syncDateCaption();
    dateSelect?.addEventListener('change', () => { syncDateCaption(); filterForm.requestSubmit(); });
    filterForm.querySelector('select[name="category"]')?.addEventListener('change', () => filterForm.requestSubmit());
    filterForm.querySelectorAll('input[type="checkbox"][name="free"],input[type="checkbox"][name="walk"]')
      .forEach((input) => input.addEventListener('change', () => filterForm.requestSubmit()));
  }

  document.getElementById('results-sort')?.addEventListener('change', (event) => {
    const url = new URL(location.href);
    if (event.target.value === 'popular') url.searchParams.set('sort', 'popular'); else url.searchParams.delete('sort');
    location.assign(url);
  });

  // ---- Map -----------------------------------------------------------------------------------
  const mapElement = document.getElementById('explore-map');
  if (!mapElement || !window.maplibregl) return;
  const status = document.getElementById('map-status');
  const list = document.getElementById('event-list');
  const searchAreaButton = document.getElementById('search-area');
  const heatmapToggle = document.getElementById('heatmap-toggle');
  const initialPoints = JSON.parse(document.getElementById('map-points').textContent);
  const center = JSON.parse(document.getElementById('map-center').textContent);
  if (!config.key) { status.textContent = 'Map unavailable: configure MAPTILER_API_KEY.'; return; }

  const styleUrl = (name) => `https://api.maptiler.com/maps/${name}/style.json?key=${encodeURIComponent(config.key)}`;
  const STYLES = { streets: styleUrl('streets-v2'), satellite: styleUrl('hybrid') };
  const map = new maplibregl.Map({ container: mapElement, style: STYLES.streets, center: [center[1], center[0]], zoom: 12.2 });
  new ResizeObserver(() => map.resize()).observe(mapElement);

  let currentPoints = initialPoints;
  const markers = new Map();
  const seenMarkerIds = new Set();
  let draggedSinceSearch = false;

  // Popularity heatmap. Re-added whenever the style changes, because a new style drops custom layers.
  const toGeoJson = (points) => {
    const maxPopularity = Math.max(1, ...points.map((point) => point.popularity || 0));
    return {
      type: 'FeatureCollection',
      features: points.map((point) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [point.lng, point.lat] },
        properties: { weight: 0.4 + 0.6 * ((point.popularity || 0) / maxPopularity) },
      })),
    };
  };
  const addHeatmap = () => {
    if (map.getSource('event-heat')) return;
    map.addSource('event-heat', { type: 'geojson', data: toGeoJson(currentPoints) });
    map.addLayer({
      id: 'event-heat',
      type: 'heatmap',
      source: 'event-heat',
      layout: { visibility: heatmapToggle.checked ? 'visible' : 'none' },
      paint: {
        'heatmap-weight': ['get', 'weight'],
        // Strong enough to read with only a handful of events; colours start early on the density scale.
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 10, 1.6, 16, 3],
        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 10, 30, 13, 55, 16, 90],
        'heatmap-opacity': 0.75,
        'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
          0, 'rgba(255,253,249,0)', 0.08, 'rgba(150,190,230,0.5)', 0.3, 'rgba(244,210,110,0.72)',
          0.55, 'rgba(240,140,75,0.82)', 0.85, 'rgba(198,80,36,0.9)'],
      },
    });
  };
  const updateHeatmap = () => map.getSource('event-heat')?.setData(toGeoJson(currentPoints));
  heatmapToggle.addEventListener('change', () => {
    if (map.getLayer('event-heat')) map.setLayoutProperty('event-heat', 'visibility', heatmapToggle.checked ? 'visible' : 'none');
  });
  map.on('style.load', addHeatmap);

  document.querySelectorAll('[data-map-style]').forEach((button) => button.addEventListener('click', () => {
    if (button.getAttribute('aria-pressed') === 'true') return;
    document.querySelectorAll('[data-map-style]').forEach((other) => other.setAttribute('aria-pressed', String(other === button)));
    map.setStyle(STYLES[button.dataset.mapStyle]);
  }));

  document.querySelectorAll('[data-map-zoom]').forEach((button) => button.addEventListener('click', () => {
    map.zoomTo(map.getZoom() + (button.dataset.mapZoom === 'in' ? 1 : -1), { duration: 250 });
  }));

  const getLocation = () => new Promise((resolve) => {
    if (!navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
      (position) => resolve([position.coords.latitude, position.coords.longitude]),
      () => resolve(null),
      { maximumAge: 300000, timeout: 5000 },
    );
  });
  let youAreHere = null;
  document.querySelector('[data-map-locate]')?.addEventListener('click', async () => {
    const coords = await getLocation();
    if (!coords) { status.hidden = false; status.textContent = 'Could not get your location.'; return; }
    const lngLat = [coords[1], coords[0]];
    if (!youAreHere) {
      const dot = document.createElement('div');
      dot.className = 'you-are-here';
      dot.setAttribute('aria-label', 'Your location');
      youAreHere = new maplibregl.Marker({ element: dot });
    }
    youAreHere.setLngLat(lngLat).addTo(map);
    map.flyTo({ center: lngLat, zoom: Math.max(map.getZoom(), 14.5), duration: reducedMotion ? 0 : 900 });
  });

  // Pins: a round badge in the category colour with its icon, larger for more popular events.
  const cardFor = (id) => list.querySelector(`[data-event-id="${CSS.escape(id)}"]`);
  const popupContent = (point) => {
    const popup = document.createElement('a');
    popup.className = 'map-popup';
    popup.href = `/events/${encodeURIComponent(point.slug)}/`;
    const title = document.createElement('b');
    title.textContent = point.title;
    const when = document.createElement('small');
    when.textContent = new Date(point.start).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    const where = document.createElement('small');
    where.textContent = point.venue || '';
    popup.append(title, when, where);
    return popup;
  };
  const renderPins = (points) => {
    markers.forEach((marker) => marker.remove());
    markers.clear();
    const maxPopularity = Math.max(1, ...points.map((point) => point.popularity || 0));
    points.forEach((point, index) => {
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = `map-pin tone-${point.tone}`;
      pin.style.setProperty('--pin-size', `${Math.round(30 + 14 * ((point.popularity || 0) / maxPopularity))}px`);
      pin.style.setProperty('--marker-delay', `${Math.min(index, 8) * 18}ms`);
      pin.setAttribute('aria-label', `${point.title}${point.category ? `, ${point.category}` : ''}`);
      // MapLibre positions the marker element with a transform, so hover effects go on the inner face.
      pin.innerHTML = `<span class="pin-face"><i data-lucide="${point.icon}" aria-hidden="true"></i></span>`;
      if (!seenMarkerIds.has(point.id)) { pin.classList.add('marker-enter'); seenMarkerIds.add(point.id); }

      const marker = new maplibregl.Marker({ element: pin })
        .setLngLat([point.lng, point.lat])
        .setPopup(new maplibregl.Popup({ offset: 20, closeButton: false }).setDOMContent(popupContent(point)))
        .addTo(map);

      const highlightCard = (on) => cardFor(point.id)?.classList.toggle('active', on);
      pin.addEventListener('mouseenter', () => highlightCard(true));
      pin.addEventListener('mouseleave', () => highlightCard(false));
      pin.addEventListener('click', () => {
        const card = cardFor(point.id);
        if (!card) return;
        card.scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth', block: 'nearest' });
        card.classList.add('active');
        window.setTimeout(() => card.classList.remove('active'), 1100);
      });
      markers.set(point.id, marker);
    });
    window.lucide?.createIcons();
  };

  // Hovering or focusing a card lifts its pin.
  const pinFor = (card) => markers.get(card?.dataset.eventId)?.getElement();
  list.addEventListener('mouseover', (event) => pinFor(event.target.closest('[data-event-id]'))?.classList.add('marker-active'));
  list.addEventListener('mouseout', (event) => pinFor(event.target.closest('[data-event-id]'))?.classList.remove('marker-active'));
  list.addEventListener('focusin', (event) => pinFor(event.target.closest('[data-event-id]'))?.classList.add('marker-active'));
  list.addEventListener('focusout', (event) => pinFor(event.target.closest('[data-event-id]'))?.classList.remove('marker-active'));

  const resultCount = document.getElementById('result-count');
  const resultLabel = document.getElementById('result-label');
  const showResults = (points, cardsHtml) => {
    currentPoints = points;
    if (cardsHtml !== undefined) {
      list.innerHTML = cardsHtml;
      window.lucide?.createIcons();
    }
    resultCount.textContent = points.length;
    const noun = points.length === 1 ? 'event' : 'events';
    resultLabel.textContent = resultLabel.dataset.searching ? `${noun} match your search` : `${noun} on the map`;
    renderPins(points);
    updateHeatmap();
    status.hidden = true;
  };

  async function fetchArea(bounds, centerCoords) {
    const url = new URL('/api/map-events/', location.origin);
    url.searchParams.set('bbox', [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(','));
    for (const key of ['date', 'category', 'q', 'sort']) url.searchParams.set(key, config[key]);
    for (const key of ['free', 'indoors', 'quiet']) if (config[key]) url.searchParams.set(key, '1');
    if (config.walk) {
      url.searchParams.set('walk', '1');
      if (centerCoords) { url.searchParams.set('lat', centerCoords[0]); url.searchParams.set('lng', centerCoords[1]); }
    }
    list.setAttribute('aria-busy', 'true');
    list.innerHTML = '<div class="event-skeletons" aria-label="Loading events">'
      + Array.from({ length: 3 }, () => '<div class="event-skeleton"><i></i><span><b></b><b></b><b></b></span></div>').join('') + '</div>';
    status.hidden = false;
    status.textContent = 'Updating events…';
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      showResults(data.events, data.cards_html);
    } finally {
      list.removeAttribute('aria-busy');
    }
  }

  map.on('load', async () => {
    status.hidden = true;
    addHeatmap(); // no-op if 'style.load' already added it
    showResults(initialPoints);
    if (initialPoints.length > 1) {
      const bounds = new maplibregl.LngLatBounds();
      initialPoints.forEach((point) => bounds.extend([point.lng, point.lat]));
      map.fitBounds(bounds, { padding: 64, maxZoom: 14, duration: 0 });
    } else if (initialPoints.length === 1) {
      map.setCenter([initialPoints[0].lng, initialPoints[0].lat]);
    }
    if (config.walk) {
      try { await fetchArea(map.getBounds(), await getLocation()); } catch {
        status.hidden = false;
        status.textContent = 'Could not load walking-distance results.';
      }
    }
  });
  map.on('error', () => {
    status.hidden = false;
    status.textContent = 'Map tiles failed to load. Check your MapTiler key and allowed referrers.';
  });

  // After the person drags the map, offer to search the new area.
  map.on('dragstart', () => { draggedSinceSearch = true; });
  map.on('moveend', () => { if (draggedSinceSearch) { searchAreaButton.hidden = false; draggedSinceSearch = false; } });
  searchAreaButton.addEventListener('click', async () => {
    searchAreaButton.disabled = true;
    searchAreaButton.classList.add('is-loading');
    searchAreaButton.querySelector('.search-label').textContent = 'Searching…';
    try {
      await fetchArea(map.getBounds(), config.walk ? await getLocation() : null);
      searchAreaButton.hidden = true;
    } catch {
      status.hidden = false;
      status.textContent = 'Could not load events. Please try again.';
    } finally {
      searchAreaButton.disabled = false;
      searchAreaButton.classList.remove('is-loading');
      searchAreaButton.querySelector('.search-label').textContent = 'Search this area';
    }
  });
})();
