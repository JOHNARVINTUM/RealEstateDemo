(function () {
  function getOrCreateErrorElement(input) {
    var errorEl = input.nextElementSibling;
    if (!errorEl || !errorEl.classList.contains("global-validation-error")) {
      errorEl = document.createElement("div");
      errorEl.className = "global-validation-error";
      errorEl.style.color = "red";
      errorEl.style.fontSize = "12px";
      errorEl.style.marginTop = "4px";
      input.parentNode.insertBefore(errorEl, input.nextSibling);
    }
    return errorEl;
  }

  function clearError(input, errorEl) {
    errorEl.textContent = "";
    input.style.borderColor = "green";
  }

  function setError(input, errorEl, message) {
    errorEl.textContent = message;
    input.style.borderColor = "red";
  }

  function validateEmail(input) {
    var val = input.value;
    if (!val) return true;
    if (val.includes(" ")) return "Email cannot contain spaces.";
    var pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!pattern.test(val)) return "Must follow proper email format (name@domain.com).";
    return true;
  }

  function validatePhone(input) {
    var val = input.value;
    if (!val) return true;
    if (!/^\d{11}$/.test(val)) return "Must be exactly 11 digits (e.g., 09123456789).";
    return true;
  }

  function validateAmount(input) {
    var val = input.value;
    if (!val) return true;
    var numStr = val.replace(/,/g, "");
    var num = parseFloat(numStr);
    if (Number.isNaN(num)) return "Must be a valid number.";
    if (num > 1000000) return "Amount cannot exceed 1,000,000.";
    return true;
  }

  function validateSlots(input) {
    var val = input.value;
    if (!val) return true;
    var num = parseInt(val, 10);
    if (Number.isNaN(num)) return "Must be a valid number.";
    if (num < 0 || num > 10) return "Cannot exceed 10 slots.";
    return true;
  }

  function validatePersonName(input) {
    var val = input.value;
    if (!val) return true;
    if (/[^a-zA-Z\s\-\.]/.test(val)) return "Must contain letters only. No numbers or special characters.";
    return true;
  }

  function validateReference(input) {
    var val = input.value;
    if (!val) return true;
    if (!/^\d{13}$/.test(val)) return "Must be exactly 13 digits. Numbers only.";
    return true;
  }

  function resolveValidationType(input) {
    var type = (input.type || "").toLowerCase();
    var name = (input.name || "").toLowerCase();
    var id = (input.id || "").toLowerCase();

    if (type === "email" || name.includes("email")) {
      return "email";
    }
    if (name.includes("phone") || id.includes("phone") || name === "contact_no" || id === "contact_no") {
      return "phone";
    }
    if (name.includes("amount") || id.includes("amount") || name.includes("rent") || name.includes("deposit")) {
      return "amount";
    }
    if (name.includes("slots") || id.includes("slots")) {
      return "slots";
    }
    if (name === "first_name" || name === "last_name" || name === "name") {
      return "personName";
    }
    if (name.includes("reference") || id.includes("reference")) {
      if (!name.includes("cash") && !id.includes("cash")) {
        return "reference";
      }
    }
    return null;
  }

  function validateInputByType(input, type) {
    if (type === "email") return validateEmail(input);
    if (type === "phone") return validatePhone(input);
    if (type === "amount") return validateAmount(input);
    if (type === "slots") return validateSlots(input);
    if (type === "personName") return validatePersonName(input);
    if (type === "reference") return validateReference(input);
    return true;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var forms = document.querySelectorAll("form");

    document.querySelectorAll("input").forEach(function (input) {
      var validationType = resolveValidationType(input);
      if (!validationType) {
        return;
      }

      input.dataset.validationType = validationType;
      input.addEventListener("input", function () {
        var errorEl = getOrCreateErrorElement(input);
        var result = validateInputByType(input, validationType);

        if (result === true) {
          if (input.value) {
            clearError(input, errorEl);
          } else {
            errorEl.textContent = "";
            input.style.borderColor = "";
          }
        } else {
          setError(input, errorEl, result);
        }
      });
    });

    forms.forEach(function (form) {
      form.addEventListener("submit", function (event) {
        var isValid = true;
        var inputsToValidate = form.querySelectorAll("input[data-validation-type]");

        inputsToValidate.forEach(function (input) {
          var type = input.dataset.validationType;
          var errorEl = getOrCreateErrorElement(input);
          var result = validateInputByType(input, type);

          if (result !== true && input.value) {
            setError(input, errorEl, result);
            isValid = false;
          }
        });

        if (!isValid) {
          event.preventDefault();
        }
      });
    });
  });
})();
