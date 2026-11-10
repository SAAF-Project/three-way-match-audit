// Light/dark toggle. The server renders the saved choice from the `theme`
// cookie, so this file only handles clicks and restored pages.
(() => {
  const COOKIE = "theme";
  const ONE_YEAR = 60 * 60 * 24 * 365;
  const root = document.documentElement;

  function activeTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  document.querySelector(".theme-toggle")?.addEventListener("click", () => {
    const next = activeTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    document.cookie = `${COOKIE}=${next}; max-age=${ONE_YEAR}; path=/; samesite=lax`;
  });

  // The Back button can restore a page rendered before the theme changed.
  window.addEventListener("pageshow", () => {
    const saved = document.cookie.match(/(?:^|; )theme=(light|dark)(?:;|$)/);
    if (saved) root.dataset.theme = saved[1];
  });
})();
