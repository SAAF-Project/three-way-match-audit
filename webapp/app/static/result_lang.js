// Language switch on the result page. Findings are written in the chosen
// language while matching, so the same files and tolerances are posted again.
(() => {
  const ONE_YEAR = 60 * 60 * 24 * 365;
  const form = document.getElementById("rerun-form");

  function restoreFile(input) {
    const bytes = Uint8Array.from(atob(input.dataset.content), c => c.charCodeAt(0));
    const files = new DataTransfer();
    files.items.add(new File([bytes], input.dataset.filename));
    input.files = files.files;
  }

  document.querySelectorAll(".lang-link").forEach(link => {
    link.addEventListener("click", event => {
      event.preventDefault();
      if (link.classList.contains("active")) return;
      form.querySelectorAll('input[type="file"]').forEach(restoreFile);
      document.cookie = `lang=${link.dataset.lang}; max-age=${ONE_YEAR}; path=/; samesite=lax`;
      form.submit();
    });
  });
})();
