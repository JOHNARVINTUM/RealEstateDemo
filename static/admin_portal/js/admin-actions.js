document.addEventListener('DOMContentLoaded', function () {
  const modal = document.getElementById('confirmModal');
  if (!modal) return;
  const modalMessage = modal.querySelector('.confirm-message');
  const confirmBtn = modal.querySelector('.confirm-yes');
  const cancelBtn = modal.querySelector('.confirm-no');

  let pendingAction = null; // {type: 'form'|'link', target: Element}

  function showModal(message, action) {
    modalMessage.textContent = message || 'Are you sure?';
    pendingAction = action;
    modal.classList.add('open');
    confirmBtn.focus();
  }

  function hideModal() {
    modal.classList.remove('open');
    pendingAction = null;
  }

  // attach to forms
  document.querySelectorAll('form.confirm-action').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      const msg = form.dataset.confirm || 'Are you sure?';
      showModal(msg, { type: 'form', target: form });
    });
  });

  // attach to links
  document.querySelectorAll('a.confirm-action').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      const msg = a.dataset.confirm || 'Are you sure?';
      showModal(msg, { type: 'link', target: a });
    });
  });

  confirmBtn.addEventListener('click', function () {
    if (!pendingAction) {
      hideModal();
      return;
    }
    if (pendingAction.type === 'form') {
      // submit the form
      pendingAction.target.submit();
    } else if (pendingAction.type === 'link') {
      // navigate to link href
      window.location.href = pendingAction.target.href;
    }
  });

  cancelBtn.addEventListener('click', function () {
    hideModal();
  });

  // close on ESC
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.classList.contains('open')) {
      hideModal();
    }
  });
});
