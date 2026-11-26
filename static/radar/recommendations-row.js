// "Recommended for you" arrives after the rest of the home page: ranking takes about ten database queries,
// so the page shows a placeholder (_recommendations_loading.html) and this swaps in the real row.
// The cards' buttons use document-wide listeners, so they work in the new row as they are;
// landing-location.js starts on the radar:recommendations event, once the row and its banner exist.
(() => {
  const holder = document.querySelector('[data-recommendations-src]');
  if (!holder) return;
  const status = holder.querySelector('[data-recommendations-status]');

  const showProblem = () => {
    holder.querySelector('[data-recommendations-skeleton]')?.remove();
    status.classList.add('empty', 'is-problem');
    status.textContent = 'Couldn’t load recommendations. ';
    const retry = document.createElement('a');
    retry.href = window.location.href;
    retry.textContent = 'Reload the page';
    status.append(retry);
    holder.querySelector('[aria-busy]')?.removeAttribute('aria-busy');
  };

  fetch(holder.dataset.recommendationsSrc, { headers: { Accept: 'text/html' }, credentials: 'same-origin' })
    .then((response) => {
      // A signed-out session is redirected to the login page, which isn't the row.
      if (!response.ok || response.redirected) throw new Error(`Loading recommendations failed (${response.status})`);
      return response.text();
    })
    .then((html) => {
      holder.outerHTML = html;
      window.lucide?.createIcons();
      document.dispatchEvent(new CustomEvent('radar:recommendations'));
    })
    .catch(showProblem);
})();
