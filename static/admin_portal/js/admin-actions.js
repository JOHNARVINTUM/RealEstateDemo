document.addEventListener('DOMContentLoaded', function () {
  const modal = document.getElementById('confirmModal');
  if (!modal) return;

  const modalMessage = modal.querySelector('.confirm-message');
  const confirmBtn   = modal.querySelector('.confirm-yes');
  const cancelBtn    = modal.querySelector('.confirm-no');
  const overlay      = modal.querySelector('.modal-overlay');

  let pendingAction = null;

  function showModal(message, action) {
    modalMessage.textContent = message || 'Are you sure?';
    pendingAction = action;
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    confirmBtn.focus();
  }

  function hideModal() {
    modal.classList.remove('open');
    document.body.style.overflow = '';
    pendingAction = null;
  }

  // Attach to forms with confirm-action class
  document.querySelectorAll('form.confirm-action').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      showModal(form.dataset.confirm || 'Are you sure?', { type: 'form', target: form });
    });
  });

  // Attach to links with confirm-action class
  document.querySelectorAll('a.confirm-action').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      showModal(a.dataset.confirm || 'Are you sure?', { type: 'link', target: a });
    });
  });

  confirmBtn.addEventListener('click', function () {
    if (!pendingAction) { hideModal(); return; }
    if (pendingAction.type === 'form') {
      pendingAction.target.submit();
    } else if (pendingAction.type === 'link') {
      window.location.href = pendingAction.target.href;
    }
  });

  cancelBtn.addEventListener('click', hideModal);

  // Click overlay to close
  if (overlay) overlay.addEventListener('click', hideModal);

  // ESC to close
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.classList.contains('open')) hideModal();
  });

  // Sidebar Toggle logic
  const sidebarToggle = document.getElementById('sidebarToggle');
  if (sidebarToggle) {
    // Check local storage for preference
    if (localStorage.getItem('sidebarCollapsed') === 'true') {
      document.body.classList.add('sidebar-collapsed');
    }

    sidebarToggle.addEventListener('click', function() {
      document.body.classList.toggle('sidebar-collapsed');
      const isCollapsed = document.body.classList.contains('sidebar-collapsed');
      localStorage.setItem('sidebarCollapsed', isCollapsed);
    });
  }

  // Mobile Sidebar Toggle
  const mobileToggle = document.getElementById('mobileSidebarToggle');
  const mobileOverlay = document.getElementById('mobileOverlay');

  if (mobileToggle) {
    mobileToggle.addEventListener('click', function() {
      document.body.classList.toggle('mobile-sidebar-open');
    });
  }

  if (mobileOverlay) {
    mobileOverlay.addEventListener('click', function() {
      document.body.classList.remove('mobile-sidebar-open');
    });
  }
});
