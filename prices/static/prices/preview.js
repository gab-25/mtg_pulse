// Show a large card image beside a hovered thumbnail ([data-preview]), kept inside the viewport.
(function () {
  const WIDTH = 244, HEIGHT = 340, GAP = 16, MARGIN = 8;
  const preview = document.createElement('img');
  preview.className = 'card-preview';
  preview.alt = '';
  preview.hidden = true;
  document.body.appendChild(preview);

  document.querySelectorAll('[data-preview]').forEach((thumb) => {
    thumb.addEventListener('mouseenter', () => {
      const r = thumb.getBoundingClientRect();
      let left = r.right + GAP;
      if (left + WIDTH > window.innerWidth - MARGIN) left = r.left - GAP - WIDTH;
      const top = Math.max(MARGIN, Math.min(r.top + r.height / 2 - HEIGHT / 2, window.innerHeight - HEIGHT - MARGIN));
      preview.src = thumb.dataset.preview;
      preview.style.left = Math.max(MARGIN, left) + 'px';
      preview.style.top = top + 'px';
      preview.hidden = false;
    });
    thumb.addEventListener('mouseleave', () => { preview.hidden = true; });
  });
  window.addEventListener('scroll', () => { preview.hidden = true; }, {passive: true});
})();
