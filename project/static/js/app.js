document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.getElementById('sidebar');
  const menuToggle = document.getElementById('menuToggle');
  const backdrop = document.getElementById('sidebarBackdrop');
  const setMenuOpen = (open) => {
    if (!sidebar || !menuToggle || !backdrop) return;
    sidebar.classList.toggle('open', open);
    backdrop.classList.toggle('open', open);
    menuToggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  };
  menuToggle?.addEventListener('click', () => {
    setMenuOpen(!sidebar.classList.contains('open'));
  });
  backdrop?.addEventListener('click', () => setMenuOpen(false));
  sidebar?.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', () => setMenuOpen(false));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setMenuOpen(false);
  });
  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) setMenuOpen(false);
  });

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
});
