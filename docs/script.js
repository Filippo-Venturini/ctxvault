// Reveal on scroll
const revealables = document.querySelectorAll(".reveal");

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15, rootMargin: "0px 0px -5% 0px" }
  );
  revealables.forEach((el) => observer.observe(el));
} else {
  revealables.forEach((el) => el.classList.add("is-visible"));
}

// Code tabs
document.querySelectorAll(".code-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const parent = tab.closest(".code-card");
    parent.querySelectorAll(".code-tab").forEach((t) => t.classList.remove("active"));
    parent.querySelectorAll(".code-block").forEach((b) => b.classList.add("hidden"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.remove("hidden");
  });
});

// Fetch GitHub star count
(async () => {
  try {
    const res = await fetch("https://api.github.com/repos/Filippo-Venturini/ctxvault");
    if (res.ok) {
      const data = await res.json();
      const count = data.stargazers_count;
      const el = document.getElementById("star-count");
      if (el && count != null) {
        el.textContent = "⭐ " + count;
      }
    }
  } catch (e) {
    // silently fail, keep the default ⭐
  }
})();

// Fetch PyPI monthly downloads
(async () => {
  const el = document.getElementById("download-count");
  if (!el) return;

  const url = "https://img.shields.io/pepy/dt/ctxvault.json";

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("Errore nel recupero dati");

    const data = await res.json();
    
    if (data && data.value) {
      const total = data.value.replace('total', '').trim();
      
      el.textContent = total; 
      el.title = `Total downloads according to PePy.tech`;
    }
  } catch (e) {
    console.error("Fetch error:", e);
    el.textContent = "n/a";
  }
})();
