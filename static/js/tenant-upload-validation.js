(function () {
  "use strict";

  var allowedExtensions = new Set([".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg"]);
  var maxFileSize = 10 * 1024 * 1024;
  var invalidTypeMessage = "Please upload a PDF, Word document (.doc/.docx), PNG, or JPG/JPEG file.";

  function showFeedback(input, feedback, kind, message) {
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.setAttribute("role", kind === "success" ? "status" : "alert");
    feedback.className = "mt-2 whitespace-pre-line text-sm font-semibold " +
      (kind === "success" ? "text-emerald-700" : "text-rose-700");
    input.setAttribute("aria-invalid", kind === "error" ? "true" : "false");
  }

  function clearFeedback(input, feedback) {
    feedback.textContent = "";
    feedback.hidden = true;
    input.removeAttribute("aria-invalid");
  }

  document.querySelectorAll("input[data-tenant-document-upload]").forEach(function (input) {
    var feedback = document.getElementById(input.getAttribute("data-feedback-id"));
    if (!feedback) return;

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) {
        clearFeedback(input, feedback);
        return;
      }

      var dot = file.name.lastIndexOf(".");
      var extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
      if (!allowedExtensions.has(extension)) {
        input.value = "";
        showFeedback(
          input,
          feedback,
          "error",
          "\u2715 Invalid file type\n" + invalidTypeMessage
        );
        return;
      }

      if (file.size > maxFileSize) {
        input.value = "";
        showFeedback(
          input,
          feedback,
          "error",
          "\u2715 File too large\nMaximum allowed size is 10 MB."
        );
        return;
      }

      showFeedback(
        input,
        feedback,
        "success",
        "\u2713 Valid file"
      );
    });
  });
})();
