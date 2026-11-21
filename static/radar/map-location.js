// Helpers for the location a user shares with Radar, used by the home page and the Explore Map.
// A shared location is snapped to a ~500 m grid (LOCATION_GRID_DEGREES in apps/discovery/recommendations.py),
// so maps draw it as a shaded "approximate location" circle rather than a precise dot.
(() => {
  const GRID_DEGREES = 0.005;
  const RADIUS_METERS = 350; // The farthest a snapped point can be from where the user really was.
  const SOURCE = 'approx-location';
  const LAYERS = ['approx-location-fill', 'approx-location-line'];

  // Snap [lat, lng] to the grid before it leaves the device, so the exact position is never sent.
  window.radarSnapLocation = ([lat, lng]) => [lat, lng].map(
    (value) => Number((Math.round(value / GRID_DEGREES) * GRID_DEGREES).toFixed(3)),
  );

  const circle = ([lat, lng]) => {
    const metersPerDegreeLat = 111320;
    const metersPerDegreeLng = 111320 * Math.cos((lat * Math.PI) / 180);
    const ring = Array.from({ length: 65 }, (_, i) => {
      const angle = (i / 64) * 2 * Math.PI;
      return [lng + (RADIUS_METERS * Math.cos(angle)) / metersPerDegreeLng,
        lat + (RADIUS_METERS * Math.sin(angle)) / metersPerDegreeLat];
    });
    return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring] }, properties: {} };
  };

  // Draws (or moves) the circle on a MapLibre map. Returns { remove } to take it off again.
  window.radarApproximateLocation = (map, location) => {
    const data = circle(location);
    const add = () => {
      const source = map.getSource(SOURCE);
      if (source) { source.setData(data); return; }
      map.addSource(SOURCE, { type: 'geojson', data });
      map.addLayer({ id: LAYERS[0], type: 'fill', source: SOURCE, paint: { 'fill-color': '#2f6fb0', 'fill-opacity': 0.14 } });
      map.addLayer({
        id: LAYERS[1], type: 'line', source: SOURCE,
        paint: { 'line-color': '#2f6fb0', 'line-width': 1.5, 'line-opacity': 0.7, 'line-dasharray': [2, 2] },
      });
    };
    if (map.isStyleLoaded()) add(); else map.once('load', add);
    map.on('style.load', add); // Switching map style drops custom layers, so draw it again.
    return {
      remove() {
        map.off('style.load', add);
        LAYERS.forEach((id) => { if (map.getLayer(id)) map.removeLayer(id); });
        if (map.getSource(SOURCE)) map.removeSource(SOURCE);
      },
    };
  };
})();
