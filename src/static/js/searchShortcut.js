// Keyboard shortcuts for Yamtrack.
//
// - `/`     focus the global header search input
// - ⌘K/^K   open the command palette (also handled by Alpine in cmdk.html)
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

  const jumpTargets = {
    h: '/',
    d: '/calendar/',
    l: '/lists/',
  };

  let awaitingG = false;
  let timer = null;

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
})();
