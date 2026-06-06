(function () {
  var progressTimer = null;
  var progressValue = 0;

  function getLoader() {
    return document.querySelector("[data-ux-loader]");
  }

  function getProgressBar(loader) {
    return loader ? loader.querySelector(".ux-page-loader-progress span") : null;
  }

  function setProgress(loader, value) {
    var bar = getProgressBar(loader);
    if (!bar) {
      return;
    }
    progressValue = Math.max(0, Math.min(100, value));
    bar.style.width = progressValue + "%";
  }

  function stopProgress() {
    if (progressTimer) {
      window.clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function startProgress(loader) {
    stopProgress();
    setProgress(loader, 8);

    window.setTimeout(function () {
      setProgress(loader, 28);
    }, 40);

    progressTimer = window.setInterval(function () {
      var remaining = 92 - progressValue;
      var increment = Math.max(1, remaining * 0.18);
      setProgress(loader, Math.min(92, progressValue + increment));
    }, 420);
  }

  function completeProgress() {
    var loader = getLoader();
    if (!loader) {
      return;
    }
    stopProgress();
    setProgress(loader, 100);
  }

  function showLoader() {
    var loader = getLoader();
    if (!loader) {
      return;
    }
    loader.classList.add("is-visible");
    loader.setAttribute("aria-hidden", "false");
    startProgress(loader);
  }

  function hideLoader() {
    var loader = getLoader();
    if (!loader) {
      return;
    }
    stopProgress();
    setProgress(loader, 100);
    loader.classList.remove("is-visible");
    loader.setAttribute("aria-hidden", "true");
    window.setTimeout(function () {
      setProgress(loader, 8);
    }, 220);
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
  window.addEventListener("beforeunload", completeProgress);
})();
