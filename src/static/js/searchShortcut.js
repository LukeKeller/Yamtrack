// Keyboard shortcuts for Yamtrack.
//
// - `/`     focus the global header search input
// - ⌘K/^K   open the command palette (also handled by Alpine in cmdk.html)
// - `?`     toggle the shortcut overlay (Shift+/)
// - j / k   move focus down / up through items marked [data-row-nav]
// - 1-9     rate focused card 1..9 (only on cards with [data-quick-rate-url])
// - 0       rate focused card 10
// - g h     go home
// - g d     go to calendar (date)
// - g l     go to lists
// - g s     focus search input
//
// Two-key sequences time out after 1.2s of inactivity.

(function () {
  const isTyping = () => {
    const el = document.activeElement;
    return el && (
      el.tagName === 'INPUT'
      || el.tagName === 'TEXTAREA'
      || el.isContentEditable
    );
  };

  const focusSearch = () => {
    const input = document.getElementById('global-search');
    if (input) {
      input.focus();
      input.select();
    }
  };

  // URLs are injected by base.html via data-* attrs on a <script> tag so we
  // honor Django's BASE_URL prefix (e.g. /yamtrack on subpath deploys).
  const cfg = document.currentScript || document.querySelector('script[data-shortcut-home]');
  const jumpTargets = {
    h: cfg?.dataset?.shortcutHome || '/',
    d: cfg?.dataset?.shortcutCalendar || '/calendar/',
    l: cfg?.dataset?.shortcutLists || '/lists/',
  };

  let awaitingG = false;
  let timer = null;

  // Read Django's csrftoken cookie for fetch-driven mutations (HTMX picks it
  // up automatically, but the quick-rate hotkey path uses bare fetch).
  const csrfToken = () => {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  };

  // Update or insert the score badge on a card after a successful rate.
  // Keeps the visual in sync without re-rendering the whole card.
  const reflectScore = (card, score) => {
    card.dataset.quickRateScore = String(score);
    let badge = card.querySelector('[data-quick-rate-badge]');
    const text = Number.isInteger(score) ? `${score}.0` : String(score);
    if (badge) {
      const span = badge.querySelector('span');
      if (span) span.textContent = text;
      return;
    }
    // No existing badge — insert a minimal one mirroring the template's classes.
    const poster = card.querySelector('.relative');
    if (!poster) return;
    badge = document.createElement('div');
    badge.setAttribute('data-quick-rate-badge', '');
    badge.className = 'absolute top-10 left-2 flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium text-white bg-black/60 backdrop-blur-sm shadow-md';
    badge.innerHTML = `<svg class="w-3.5 h-3.5 text-amber-400 fill-current" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span>${text}</span>`;
    poster.appendChild(badge);
  };

  const announce = (msg) => {
    const region = document.getElementById('yt-aria-live');
    if (!region) return;
    region.textContent = msg;
    setTimeout(() => { region.textContent = ''; }, 2500);
  };

  // POSTs a quick-rate score for the focused card. Returns true if a request
  // was issued (so the caller can preventDefault), false otherwise.
  const quickRateFocused = (score) => {
    const active = document.activeElement;
    if (!active) return false;
    const card = active.closest('[data-row-nav]');
    if (!card) return false;
    const url = card.dataset.quickRateUrl;
    if (!url) return false;
    const body = new URLSearchParams({ score: String(score) });
    fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      credentials: 'same-origin',
      body,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then(() => {
        reflectScore(card, score);
        announce(`Rated ${score} out of 10`);
      })
      .catch(() => {
        announce('Could not save rating');
      });
    return true;
  };

  // j/k focus traversal: walks elements opting in via [data-row-nav].
  // Each card/list-row that wants the shortcut sets the attribute and a
  // tabindex of 0 (or relies on an anchor child) so focus() lands somewhere.
  const moveRowFocus = (delta) => {
    const items = Array.from(document.querySelectorAll('[data-row-nav]'));
    if (items.length === 0) return false;
    const active = document.activeElement;
    let currentIndex = items.findIndex((el) => el === active || el.contains(active));
    if (currentIndex === -1) {
      currentIndex = delta > 0 ? -1 : items.length;
    }
    const nextIndex = Math.max(0, Math.min(items.length - 1, currentIndex + delta));
    const target = items[nextIndex];
    if (!target) return false;
    target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    const focusable = target.querySelector('a, button, [tabindex]') || target;
    focusable.focus({ preventScroll: true });
    return true;
  };

  document.addEventListener('keydown', (e) => {
    if (isTyping()) return;

    // ⌘K / Ctrl+K → command palette. cmdk.html also binds this; dispatching the
    // custom event lets either path open the dialog.
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent('cmdk-open'));
      return;
    }

    if (e.key === '/') {
      e.preventDefault();
      focusSearch();
      return;
    }

    // `?` (Shift + /) → toggle shortcut overlay
    if (e.key === '?') {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent('shortcuts-toggle'));
      return;
    }

    if (e.key === 'j' || e.key === 'J') {
      if (moveRowFocus(1)) e.preventDefault();
      return;
    }
    if (e.key === 'k' || e.key === 'K') {
      if (moveRowFocus(-1)) e.preventDefault();
      return;
    }

    // Digits rate the focused card. 1-9 → that value, 0 → 10 (the only way
    // to set a 10/10 from the number row). Skip when modifier keys are held
    // so accelerators like Ctrl+1 aren't hijacked.
    if (!e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey && /^[0-9]$/.test(e.key)) {
      const score = e.key === '0' ? 10 : Number(e.key);
      if (quickRateFocused(score)) e.preventDefault();
      return;
    }

    // Two-key `g X` sequences
    if (awaitingG) {
      awaitingG = false;
      clearTimeout(timer);
      const key = e.key.toLowerCase();
      if (key === 's') {
        e.preventDefault();
        focusSearch();
        return;
      }
      const target = jumpTargets[key];
      if (target) {
        e.preventDefault();
        window.location.href = target;
      }
      return;
    }
    if (e.key.toLowerCase() === 'g') {
      awaitingG = true;
      timer = setTimeout(() => { awaitingG = false; }, 1200);
    }
  });

  // Restore focus to a sensible target after HTMX swaps. Without this the
  // browser's focus often lands on <body>, which loses j/k context.
  document.addEventListener('htmx:afterSwap', (e) => {
    if (!e.target || isTyping()) return;
    const focusTarget = e.target.querySelector('[data-focus-after]');
    if (focusTarget) {
      focusTarget.focus({ preventScroll: true });
    }
  });

  // Announce HTMX requests for screen readers via the live region. The server
  // can include <span hx-swap-oob="innerHTML:#yt-aria-live">message</span> in
  // any response, but as a fallback we surface generic success on 2xx.
  document.addEventListener('htmx:afterRequest', (e) => {
    const xhr = e.detail && e.detail.xhr;
    if (!xhr || xhr.status < 200 || xhr.status >= 300) return;
    const trigger = e.detail && e.detail.elt;

    // Quick-rate via the popover: keep the on-poster score badge in sync.
    // The hotkey path calls reflectScore directly, but HTMX clicks need this
    // catch-all so both surfaces feel identical.
    if (trigger && trigger.matches('[hx-post*="update-score"]')) {
      const card = trigger.closest('[data-row-nav]');
      const score = trigger.getAttribute('hx-vals');
      const match = score && score.match(/"score"\s*:\s*([0-9.]+)/);
      if (card && match) reflectScore(card, Number(match[1]));
    }

    const liveRegion = document.getElementById('yt-aria-live');
    if (!liveRegion) return;
    if (liveRegion.textContent.trim()) return; // already set by OOB swap
    const label = trigger && trigger.getAttribute('aria-label');
    if (label) {
      liveRegion.textContent = label;
      setTimeout(() => { liveRegion.textContent = ''; }, 2500);
    }
  });
})();
