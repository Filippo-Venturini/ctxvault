// The live demo is a full-screen app: it opens in its own tab, and the docs
// stay where they were. Material re-renders pages without a reload, so the
// links are marked on every page change.
document$.subscribe(() => {
  document.querySelectorAll('a[href$="demo.html"]').forEach((a) => {
    a.target = "_blank";
    a.rel = "noopener";
  });
});
