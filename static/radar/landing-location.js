// "Recommended for you" puts closer events higher once the user shares their location.
// Radar's banner explains why first; the browser's own prompt appears only after a tap on
// "Share location", because a "Block" there is usually permanent.
// The row (and its banner) arrives after the page loads, so this starts on radar:recommendations
// (recommendations-row.js), or right away on a page that renders the row itself.
const startLocationBanner = () => {
  const DISMISS_KEY = 'radar.locationBannerDismissedAt';
  const DISMISS_DAYS = 30;
  const container = document.querySelector('[data-recommendations]');
  const banner = container && container.querySelector('[data-location-banner]');
  // No banner means the browser already sent a recent location (a six-hour cookie).
  if (!banner || !navigator.geolocation) return;

  const status = banner.querySelector('[data-location-status]');
  const shareButton = banner.querySelector('button[type="submit"]');
  // "Use my location" in the row's heading: the way back after "Not now" or a block in the browser.
  const useButton = container.querySelector('[data-location-share]');
  const showUseButton = () => { if (useButton) { useButton.hidden = false; useButton.disabled = false; } };

  // Remembering "Not now" is a per-browser convenience; if storage is blocked the banner just shows again.
  const recentlyDismissed = () => {
    try {
      return Date.now() - (Number(localStorage.getItem(DISMISS_KEY)) || 0) < DISMISS_DAYS * 86400000;
    } catch (error) {
      return false;
    }
  };
  const rememberDismissed = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (error) { /* storage blocked */ }
  };

  const getPosition = () => new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => resolve([position.coords.latitude, position.coords.longitude]),
      reject,
      { maximumAge: 300000, timeout: 10000 },
    );
  });

  // Sends the location, snapped to the ~500 m grid first (map-location.js) so the exact position never
  // leaves the device, then swaps in the re-ranked row and moves the map preview there.
  // A quiet refresh replaces the row the page just showed, so its impressions replace that row's too.
  const send = async (coords, { quiet }) => {
    const [lat, lng] = window.radarSnapLocation(coords);
    banner.elements.lat.value = lat;
    banner.elements.lng.value = lng;
    const body = new FormData(banner);
    if (quiet) body.append('replace', '1');
    const response = await fetch(banner.action, {
      method: 'POST', body, headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`Saving the location failed (${response.status})`);
    const data = await response.json();
    container.outerHTML = data.html;
    window.lucide?.createIcons();
    document.dispatchEvent(new CustomEvent('radar:location', { detail: [data.location.lat, data.location.lng] }));
  };

  // Problems are shown in the banner, even when sharing started from "Use my location".
  const showProblem = (text) => {
    banner.hidden = false;
    if (useButton) useButton.hidden = true;
    status.hidden = false;
    status.classList.remove('is-note');
    status.textContent = text;
    shareButton.disabled = false;
  };

  const share = async ({ quiet }) => {
    try {
      await send(await getPosition(), { quiet });
    } catch (error) {
      if (quiet) { showUseButton(); return; } // A background refresh failed: offer a retry, quietly.
      if (error && error.code === 1) { // PERMISSION_DENIED: blocked in the browser, now or earlier.
        showProblem('Location is blocked for this site in your browser. To share it, allow location for this site '
          + 'in your browser’s settings, then tap Share location again.');
        return;
      }
      showProblem('Couldn’t get your location. Recommendations still work without it.');
    }
  };

  banner.addEventListener('submit', (event) => {
    event.preventDefault();
    shareButton.disabled = true;
    share({ quiet: false });
  });
  banner.querySelector('[data-location-dismiss]').addEventListener('click', () => {
    rememberDismissed();
    banner.hidden = true;
    showUseButton();
  });
  useButton?.addEventListener('click', () => {
    useButton.disabled = true;
    share({ quiet: false });
  });
  // "Don't ask again" switches Account & privacy to "Don't use my location", so the two can't disagree.
  const neverButton = banner.querySelector('[data-location-never]');
  neverButton.addEventListener('click', async () => {
    neverButton.disabled = true;
    try {
      const response = await fetch(banner.dataset.offUrl, {
        method: 'POST', body: new FormData(banner), headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`Turning location off failed (${response.status})`);
      banner.querySelector('.location-actions').hidden = true;
      status.hidden = false;
      status.classList.add('is-note');
      status.textContent = 'Got it. Radar won’t use your location. You can turn it back on in Account & privacy.';
      window.setTimeout(() => { banner.hidden = true; }, 4000);
    } catch (error) {
      neverButton.disabled = false;
      status.hidden = false;
      status.textContent = 'Couldn’t save that. Please try again.';
    }
  });

  const decide = (state) => {
    if (state === 'granted') { share({ quiet: true }); return; } // Shared before: refresh without asking.
    if (state === 'denied') { showUseButton(); return; } // Blocked in the browser: don't keep asking.
    if (recentlyDismissed()) showUseButton(); else banner.hidden = false;
  };
  if (navigator.permissions?.query) {
    navigator.permissions.query({ name: 'geolocation' }).then((result) => decide(result.state), () => decide('prompt'));
  } else {
    decide('prompt');
  }
};
if (document.querySelector('[data-recommendations-src]')) {
  document.addEventListener('radar:recommendations', startLocationBanner, { once: true });
} else {
  startLocationBanner();
}
