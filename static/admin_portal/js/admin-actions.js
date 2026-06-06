document.addEventListener('DOMContentLoaded', function () {
  const modal = document.getElementById('confirmModal');
  if (!modal) return;

  const modalMessage = modal.querySelector('.confirm-message');
  const confirmBtn   = modal.querySelector('.confirm-yes');
  const cancelBtn    = modal.querySelector('.confirm-no');
  const overlay      = modal.querySelector('.modal-overlay');
  const progressBar  = modal.querySelector('.confirm-loading-progress span');

  let pendingAction = null;
  let progressTimer = null;
  let progressValue = 0;

  function setProgress(value) {
    if (!progressBar) return;
    progressValue = Math.max(0, Math.min(100, value));
    progressBar.style.width = progressValue + '%';
  }

  function stopProgress() {
    if (progressTimer) {
      window.clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function startProgress() {
    stopProgress();
    setProgress(8);
    window.setTimeout(function () {
      setProgress(28);
    }, 40);
    progressTimer = window.setInterval(function () {
      const remaining = 92 - progressValue;
      const increment = Math.max(1, remaining * 0.18);
      setProgress(Math.min(92, progressValue + increment));
    }, 360);
  }

  function setLoadingState() {
    modal.classList.add('is-loading');
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;
    if (overlay) overlay.style.pointerEvents = 'none';
    startProgress();
  }

  function showModal(message, action) {
    modalMessage.textContent = message || 'Are you sure?';
    pendingAction = action;
    modal.classList.remove('is-loading');
    confirmBtn.disabled = false;
    cancelBtn.disabled = false;
    if (overlay) overlay.style.pointerEvents = '';
    stopProgress();
    setProgress(8);
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    confirmBtn.focus();
  }

  function hideModal() {
    if (modal.classList.contains('is-loading')) return;
    modal.classList.remove('open');
    modal.classList.remove('is-loading');
    document.body.style.overflow = '';
    pendingAction = null;
    stopProgress();
    setProgress(8);
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
    setLoadingState();
    if (pendingAction.type === 'form') {
      window.setTimeout(function () {
        setProgress(100);
        pendingAction.target.submit();
      }, 180);
    } else if (pendingAction.type === 'link') {
      window.setTimeout(function () {
        setProgress(100);
        window.location.href = pendingAction.target.href;
      }, 180);
    }
  });

  cancelBtn.addEventListener('click', hideModal);

  // Click overlay to close
  if (overlay) overlay.addEventListener('click', hideModal);

  // ESC to close
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.classList.contains('open') && !modal.classList.contains('is-loading')) hideModal();
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
