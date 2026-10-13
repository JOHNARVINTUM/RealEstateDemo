import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\rentals\tenant_dashboard.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

new_css = """<style>
  .tenant-dashboard-shell {
    max-width: 1440px;
    margin: 0 auto;
    padding-bottom: 4rem;
  }

  /* Premium Card Foundations */
  .tenant-hero,
  .tenant-status-panel,
  .tenant-next-panel,
  .tenant-movein-card,
  .tenant-mini-card,
  .tenant-feed-card {
    background: #ffffff;
    border: 1px solid rgba(226, 232, 240, 0.4);
    border-radius: 2.25rem; /* Massive premium rounded corners */
    box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.04), 0 0 0 1px rgba(15, 23, 42, 0.015);
    transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
  }

  .tenant-hero:hover,
  .tenant-status-panel:hover,
  .tenant-next-panel:hover,
  .tenant-mini-card:hover {
    box-shadow: 0 35px 60px -15px rgba(15, 23, 42, 0.08), 0 0 0 1px rgba(15, 23, 42, 0.02);
    transform: translateY(-2px);
  }

  /* Hero Section Styling */
  .tenant-hero {
    background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
    padding: clamp(2rem, 4vw, 3.5rem);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 2rem;
  }

  .tenant-date-card {
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(241, 245, 249, 0.9);
    border-radius: 1.5rem;
    padding: 1.25rem 1.75rem;
    min-width: 200px;
    box-shadow: 0 10px 30px -10px rgba(15, 23, 42, 0.04);
    text-align: right;
  }

  /* Status Panel Split Layout */
  .tenant-status-content {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(280px, 320px);
    align-items: stretch;
    gap: clamp(1.5rem, 3vw, 2.5rem);
  }

  .tenant-status-action {
    display: flex;
    min-width: 0;
    flex-direction: column;
    justify-content: center;
    padding: 2rem;
    border-radius: 1.75rem;
    border: 1px solid rgba(226, 232, 240, 0.6);
  }

  .tenant-status-action.is-clear {
    background: linear-gradient(160deg, #ecfdf5 0%, #f8fafc 100%);
    border-color: #d1fae5;
  }

  .tenant-status-action.is-due {
    background: linear-gradient(160deg, #fff1f2 0%, #f8fafc 100%);
    border-color: #ffe4e6;
  }

  /* Dynamic Left Borders with Gradients */
  .tenant-status-panel, .tenant-next-panel {
    border-left: none;
  }
  
  .tenant-status-panel.is-clear::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0; width: 6px;
    background: linear-gradient(to bottom, #10b981, #34d399);
  }
  
  .tenant-status-panel.is-due::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0; width: 6px;
    background: linear-gradient(to bottom, #f43f5e, #fb7185);
  }
  
  .tenant-next-panel::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0; width: 6px;
    background: linear-gradient(to bottom, #6366f1, #818cf8);
  }

  /* Inner elements & Typography */
  h1, h2, h3 {
    font-family: 'Outfit', sans-serif !important;
  }

  .tenant-action-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.45fr);
    gap: 1.5rem;
  }

  .tenant-status-panel,
  .tenant-next-panel,
  .tenant-feed-card {
    padding: clamp(1.5rem, 3vw, 2.5rem);
  }

  .tenant-next-panel {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .tenant-movein-card {
    padding: 1.75rem 2.5rem;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(180px, auto);
    align-items: center;
    gap: 1.5rem;
  }

  .tenant-mini-card {
    padding: 1.75rem;
    min-height: 130px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }

  .tenant-mini-card span,
  .tenant-mini-card small {
    display: block;
    font-size: 0.72rem;
    font-weight: 900;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #94a3b8;
  }

  .tenant-mini-card strong {
    display: block;
    margin-top: 0.75rem;
    font-size: 1.5rem;
    font-weight: 900;
    color: #0f172a;
  }

  .tenant-mini-card small {
    margin-top: 0.5rem;
    font-size: 0.7rem;
    letter-spacing: 0;
    text-transform: none;
    color: #64748b;
  }

  /* List & Feed Headers */
  .tenant-section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding-bottom: 1.5rem;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid rgba(226, 232, 240, 0.6);
  }

  .tenant-section-head h2 {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 900;
    color: #0f172a;
    letter-spacing: -0.02em;
  }

  .tenant-section-head p {
    margin-top: 0.35rem;
    font-size: 0.9rem;
    font-weight: 700;
    color: #64748b;
  }

  /* Pills & Actions */
  .tenant-pill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    padding: 0.4rem 0.85rem;
    font-size: 0.68rem;
    font-weight: 900;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    white-space: nowrap;
    box-shadow: 0 2px 10px -2px rgba(0,0,0,0.05);
  }

  .tenant-small-action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 1rem;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #1d4ed8;
    padding: 0.75rem 1.25rem;
    font-size: 0.75rem;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    transition: all 0.2s ease;
  }

  .tenant-small-action:hover {
    background: #3b82f6;
    color: white;
    border-color: #3b82f6;
    box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.3);
    transform: translateY(-1px);
  }

  /* Rows */
  .tenant-payment-row,
  .tenant-update-row {
    border: 1px solid rgba(226, 232, 240, 0.6);
    background: #f8fafc;
    border-radius: 1.5rem;
    padding: 1.25rem;
    transition: all 0.3s ease;
  }

  .tenant-payment-row:hover,
  .tenant-update-row:hover {
    background: #ffffff;
    border-color: rgba(203, 213, 225, 0.8);
    box-shadow: 0 10px 30px -10px rgba(15, 23, 42, 0.05);
    transform: scale(1.01);
  }

  .tenant-payment-icon {
    width: 3rem;
    height: 3rem;
    border-radius: 1rem;
    background: linear-gradient(135deg, #0f172a 0%, #334155 100%);
    color: white;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.1rem;
    font-weight: 900;
    flex: 0 0 auto;
    box-shadow: 0 8px 20px -6px rgba(15, 23, 42, 0.4);
  }

  .tenant-update-row h3 {
    margin: 0;
    font-size: 1.1rem;
    font-weight: 900;
    line-height: 1.4;
    color: #0f172a;
  }

  .tenant-update-row time {
    flex: 0 0 auto;
    border-radius: 999px;
    background: #ffffff;
    border: 1px solid rgba(226, 232, 240, 0.8);
    padding: 0.4rem 0.8rem;
    font-size: 0.65rem;
    font-weight: 900;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748b;
    box-shadow: 0 2px 8px -2px rgba(0,0,0,0.03);
  }

  .tenant-update-row p {
    margin-top: 1rem;
    color: #475569;
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1.7;
    white-space: pre-line;
  }

  .tenant-empty-state {
    border: 2px dashed rgba(203, 213, 225, 0.6);
    background: #f8fafc;
    border-radius: 1.5rem;
    padding: 3rem 2rem;
    text-align: center;
    color: #64748b;
  }

  .tenant-empty-state strong,
  .tenant-empty-state span {
    display: block;
  }

  .tenant-empty-state strong {
    color: #0f172a;
    font-weight: 900;
    font-size: 1.1rem;
  }

  .tenant-empty-state span {
    margin-top: 0.5rem;
    font-weight: 600;
    font-size: 0.9rem;
  }

  @media (max-width: 1100px) {
    .tenant-action-grid,
    .tenant-movein-card {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 799px) {
    .tenant-hero {
      flex-direction: column;
    }

    .tenant-date-card,
    .tenant-status-action {
      width: 100%;
      text-align: left;
    }

    .tenant-status-content {
      grid-template-columns: 1fr;
    }
  }
</style>"""

updated_content = re.sub(r"<style>.*?</style>", new_css, content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(updated_content)
