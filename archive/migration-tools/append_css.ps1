$css = @'

/* ----- Modal Animation ----- */
#confirmModal.open .modal {
  animation: scaleIn 0.22s ease both;
}
#confirmModal.open .modal-overlay {
  animation: fadeIn 0.22s ease both;
}

/* ----- Empty State Enhanced ----- */
.empty-state {
  padding: 3.5rem 1.5rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.9rem;
}
.empty-icon {
  width: 3rem;
  height: 3rem;
  margin: 0 auto 1rem;
  color: #cbd5e1;
}

/* ----- Alert / Info Bars ----- */
.alert {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.9rem 1.1rem;
  border-radius: 1rem;
  font-size: 0.88rem;
  font-weight: 500;
  margin-bottom: 1rem;
}
.alert-danger {
  background: var(--danger-soft);
  border-left: 4px solid #ef4444;
  color: #b91c1c;
}
.alert-warning {
  background: var(--warning-soft);
  border-left: 4px solid #f59e0b;
  color: #b45309;
}
.alert-info {
  background: #eff6ff;
  border-left: 4px solid #3b82f6;
  color: #1d4ed8;
}

/* ----- Detail Card Hover ----- */
.detail-card {
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.detail-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

/* ----- Select consistent arrow ----- */
select.input {
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' viewBox='0 0 24 24' stroke='%2364748b' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M19 9l-7 7-7-7'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.85rem center;
  background-size: 1rem;
  padding-right: 2.5rem;
}

/* ----- Thin scrollbar for main content ----- */
main { scrollbar-width: thin; scrollbar-color: #cbd5e1 transparent; }
main::-webkit-scrollbar { width: 6px; }
main::-webkit-scrollbar-track { background: transparent; }
main::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 999px; }

/* ----- Nav icon gap ----- */
.nav-item { gap: 0.7rem; }
.nav-icon { width: 1.1rem; height: 1.1rem; flex-shrink: 0; opacity: 0.85; }
.nav-item.active .nav-icon,
.nav-item:hover .nav-icon { opacity: 1; }

/* ----- Breadcrumb ----- */
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.75rem;
  font-size: 0.82rem;
  color: var(--muted);
}
.breadcrumb a {
  color: var(--muted);
  text-decoration: none;
  transition: color 0.15s;
}
.breadcrumb a:hover { color: var(--primary); }
.breadcrumb-sep { color: #cbd5e1; font-size: 0.7rem; }
.breadcrumb .breadcrumb-current { color: var(--primary); font-weight: 600; }

/* ----- Result count tag ----- */
.result-count {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.7rem;
  background: #f1f5f9;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--muted);
}

/* ----- Stats bar above tables ----- */
.stats-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.stat-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.85rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 700;
  border: 1px solid var(--border);
  background: #fff;
  box-shadow: var(--shadow-sm);
}
.stat-pill-value {
  font-size: 1rem;
  font-weight: 800;
  color: var(--primary);
}
'@

Add-Content -Path "static\admin_portal\css\admin.css" -Value $css -Encoding UTF8
Write-Host "Done"
