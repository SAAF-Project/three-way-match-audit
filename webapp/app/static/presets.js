// Tolerance presets on the upload page. Kept out of the HTML so the
// Content-Security-Policy can forbid inline scripts.
(() => {
  const PRESETS = {
    strict:   { price_tolerance: 0,    qty_tolerance: 0, line_total_tolerance: 0,    total_tolerance: 0    },
    standard: { price_tolerance: 0.01, qty_tolerance: 0, line_total_tolerance: 0.01, total_tolerance: 0.05 },
    relaxed:  { price_tolerance: 0.10, qty_tolerance: 1, line_total_tolerance: 1.00, total_tolerance: 5.00 },
  };
  document.querySelectorAll(".preset").forEach(btn => {
    btn.addEventListener("click", () => {
      const vals = PRESETS[btn.dataset.preset];
      for (const [k, v] of Object.entries(vals)) {
        const input = document.querySelector(`[name="${k}"]`);
        if (input) input.value = v;
      }
      document.querySelectorAll(".preset").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });
})();
