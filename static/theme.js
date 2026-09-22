// Appliqué avant le rendu pour éviter le flash de thème clair au chargement.
// (Chargé sans `defer` dans <head> : c'est volontaire.)
(function () {
  try {
    var saved = localStorage.getItem("srv-theme");
    if (saved === "dark" || saved === "light") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) {
    /* mode privé / stockage bloqué : on garde la préférence système */
  }
})();
