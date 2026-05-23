// Keyboard shortcuts for Yamtrack.
//
// - `/`     focus the global header search input
// - ⌘K/^K   open the command palette (also handled by Alpine in cmdk.html)
// - `?`     toggle the shortcut overlay (Shift+/)
// - j / k   move focus down / up through items marked [data-row-nav]
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
    const liveRegion = document.getElementById('yt-aria-live');
    if (!liveRegion) return;
    if (liveRegion.textContent.trim()) return; // already set by OOB swap
    const xhr = e.detail && e.detail.xhr;
    if (!xhr || xhr.status < 200 || xhr.status >= 300) return;
    const trigger = e.detail && e.detail.elt;
    const label = trigger && trigger.getAttribute('aria-label');
    if (label) {
      liveRegion.textContent = label;
      setTimeout(() => { liveRegion.textContent = ''; }, 2500);
    }
  });
})();
