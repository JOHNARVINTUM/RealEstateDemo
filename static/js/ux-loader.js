(function () {
  function getLoader() {
    return document.querySelector("[data-ux-loader]");
  }

  function showLoader() {
    var loader = getLoader();
    if (!loader) {
      return;
    }
    loader.classList.add("is-visible");
    loader.setAttribute("aria-hidden", "false");
  }

  function hideLoader() {
    var loader = getLoader();
    if (!loader) {
      return;
    }
    loader.classList.remove("is-visible");
    loader.setAttribute("aria-hidden", "true");
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link) {
      return;
    }

    var href = link.getAttribute("href");
    var target = link.getAttribute("target");
    var isModifiedClick = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0;
    var skipLoader = link.hasAttribute("data-skip-loader") || link.hasAttribute("download");

    if (!href || href.startsWith("#") || href.startsWith("javascript:") || target === "_blank" || isModifiedClick || skipLoader) {
      return;
    }

    try {
      var linkUrl = new URL(link.href, window.location.origin);
      var currentUrl = new URL(window.location.href);
      var isSamePage = linkUrl.pathname === currentUrl.pathname && linkUrl.search === currentUrl.search && linkUrl.hash !== "";

      if (linkUrl.origin !== currentUrl.origin || isSamePage) {
        return;
      }
    } catch (error) {
      return;
    }

    showLoader();
  }, true);

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (form.matches("form[data-loading-form]")) {
      showLoader();
    }
  }, true);

  window.addEventListener("pageshow", hideLoader);
  window.addEventListener("load", hideLoader, { once: true });
})();
