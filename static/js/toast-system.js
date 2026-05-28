(function () {
  function dismissToast(toast) {
    if (!toast) {
      return;
    }
    toast.style.transition = "opacity 0.18s ease, transform 0.18s ease";
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-6px)";
    window.setTimeout(function () {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 180);
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-toast-close]");
    if (!button) {
      return;
    }
    dismissToast(button.closest(".ux-toast"));
  });

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".ux-toast[data-autodismiss]").forEach(function (toast) {
      var delay = parseInt(toast.getAttribute("data-autodismiss"), 10);
      window.setTimeout(function () {
        dismissToast(toast);
      }, Number.isNaN(delay) ? 4500 : delay);
    });
  });
})();
