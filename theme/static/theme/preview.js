// Show a large card image beside a hovered thumbnail ([data-preview]), kept inside the viewport.
(function () {
  const WIDTH = 244, HEIGHT = 340, GAP = 16, MARGIN = 8;
  const preview = document.createElement('img');
  preview.className = 'card-preview';
  preview.alt = '';
  preview.hidden = true;
  document.body.appendChild(preview);

  // Delegated, so thumbnails swapped in by htmx get the preview too.
  document.addEventListener('mouseover', (event) => {
    const thumb = event.target.closest('[data-preview]');
    if (!thumb) return;
    const r = thumb.getBoundingClientRect();
    let left = r.right + GAP;
    if (left + WIDTH > window.innerWidth - MARGIN) left = r.left - GAP - WIDTH;
    const top = Math.max(MARGIN, Math.min(r.top + r.height / 2 - HEIGHT / 2, window.innerHeight - HEIGHT - MARGIN));
    preview.src = thumb.dataset.preview;
    preview.style.left = Math.max(MARGIN, left) + 'px';
    preview.style.top = top + 'px';
    preview.hidden = false;
  });
  document.addEventListener('mouseout', (event) => {
    if (event.target.closest('[data-preview]')) preview.hidden = true;
  });
  window.addEventListener('scroll', () => { preview.hidden = true; }, {passive: true});
})();
