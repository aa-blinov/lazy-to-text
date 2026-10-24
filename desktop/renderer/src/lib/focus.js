// Keyboard focus after the screen changes. Switching screens with Cmd/Ctrl+N
// replaces the content but leaves the focus on the sidebar, so the next Tab
// walks the sidebar again; the new screen's heading takes it instead. A
// heading is not focusable by itself, so it gets tabindex -1 (focusable by
// script, not a Tab stop). A screen that draws its heading only after its
// data arrived is waited for briefly, then the main area itself is used.

export function focusScreen({ tries = 12, delay = 50 } = {}) {
  const attempt = (left) => {
    const main = document.querySelector('main');
    if (!main) return;
    const heading = main.querySelector('h1, h2');
    const target = heading || (left <= 0 ? main : null);
    if (!target) {
      setTimeout(() => attempt(left - 1), delay);
      return;
    }
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  };
  // After the new screen has been drawn.
  setTimeout(() => attempt(tries), 0);
}
