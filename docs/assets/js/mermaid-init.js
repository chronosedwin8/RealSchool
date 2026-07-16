// Renderiza los diagramas Mermaid usando la copia local (offline) y los vuelve a
// dibujar con el tema correcto al alternar claro/oscuro en Material.
(function () {
  function currentTheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate"
      ? "dark"
      : "default";
  }

  function renderAll() {
    if (!window.mermaid) return;
    document.querySelectorAll("pre.mermaid").forEach(function (el) {
      if (el.dataset.src === undefined) {
        el.dataset.src = el.textContent;
      }
      el.removeAttribute("data-processed");
      el.innerHTML = el.dataset.src;
    });
    window.mermaid.initialize({
      startOnLoad: false,
      theme: currentTheme(),
      securityLevel: "loose",
    });
    try {
      window.mermaid.run({ querySelector: "pre.mermaid" });
    } catch (e) {
      /* sin diagramas en esta página */
    }
  }

  document.addEventListener("DOMContentLoaded", renderAll);

  // Re-render al cambiar el esquema de color (toggle claro/oscuro).
  new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      if (m.attributeName === "data-md-color-scheme") renderAll();
    });
  }).observe(document.body, { attributes: true });
})();
