(function () {
  function applyLoadingState(form) {
    if (!form || form.dataset.loadingStateApplied === "true") {
      return;
    }
    form.dataset.loadingStateApplied = "true";

    var button = form.querySelector("[data-loading-button]");
    if (!button || button.dataset.loading === "true") {
      return;
    }

    button.dataset.loading = "true";
    button.disabled = true;
    button.classList.add("opacity-70", "cursor-not-allowed");

    var loadingText = button.dataset.loadingText || "Loading...";
    var label = button.querySelector(".button-label");
    if (label) {
      label.textContent = loadingText;
      label.classList.add("justify-center");
    } else {
      button.textContent = loadingText;
    }

    var secondarySpans = button.querySelectorAll("span");
    if (secondarySpans.length > 1) {
      secondarySpans[1].classList.add("hidden");
    }
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    if (!form.matches("form[data-loading-form], form.confirm-action")) {
      return;
    }
    applyLoadingState(form);
  }, true);
})();
