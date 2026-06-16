import os

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\billing\tenant_billing.html"

new_content = """{% extends "tenant_base.html" %}
{% load humanize %}
{% block title %}Bills | RealEstate360+{% endblock %}

{% block tenant_content %}
<div class="max-w-7xl mx-auto pb-16 space-y-8">

  <!-- 1. Premium Glassmorphic Hero -->
  <div class="relative overflow-hidden rounded-[2.5rem] bg-slate-900 p-8 sm:p-12 text-white shadow-2xl">
    <div class="absolute -top-24 -right-24 w-96 h-96 bg-blue-600 rounded-full mix-blend-multiply filter blur-3xl opacity-40"></div>
    <div class="absolute -bottom-24 -left-24 w-72 h-72 bg-emerald-500 rounded-full mix-blend-multiply filter blur-3xl opacity-30"></div>
    
    <div class="relative z-10 flex flex-col min-[800px]:flex-row min-[800px]:items-center min-[800px]:justify-between gap-8">
      <div>
        <div class="flex items-center gap-3 mb-4">
          <span class="inline-block p-3 rounded-2xl bg-white/10 backdrop-blur-md border border-white/20 shadow-inner">
            <svg class="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
          </span>
          <h1 class="text-4xl sm:text-6xl font-black tracking-tight">Billing</h1>
        </div>
        <p class="text-lg text-slate-300 font-medium max-w-2xl">
          Review your monthly charges, monitor your payment status, and browse your approved payment history.
        </p>
      </div>
      
      <div class="bg-white/10 backdrop-blur-lg border border-white/20 px-8 py-5 rounded-3xl text-center min-w-[200px]">
        <span class="text-[10px] font-black text-slate-300 block uppercase tracking-widest mb-1">Current Month</span>
        <strong class="text-3xl font-black text-white block">{% now "F Y" %}</strong>
      </div>
    </div>
  </div>

  <!-- 2. Filter Bar -->
  <div class="bg-white border border-slate-200 rounded-3xl p-6 shadow-sm flex flex-col md:flex-row md:items-end gap-4">
    <form method="get" class="w-full flex flex-col md:flex-row md:items-end gap-4">
      <div class="flex-1">
        <label class="block text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2 ml-2">Contract Month Filter</label>
        <select name="billing_month" class="w-full rounded-2xl border-2 border-slate-100 bg-slate-50 px-5 py-4 text-sm font-black text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-100/50 cursor-pointer">
          <option value="">All contract months</option>
          {% for month_value, month_label in contract_month_choices %}
            <option value="{{ month_value }}" {% if billing_month_filter == month_value %}selected{% endif %}>{{ month_label }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="flex flex-col sm:flex-row gap-3">
        <button type="submit" class="inline-flex items-center justify-center rounded-2xl bg-slate-900 px-8 py-4 text-sm font-black text-white shadow-lg shadow-slate-200 transition hover:bg-slate-700 active:scale-95">
          Apply Filter
        </button>
        {% if billing_month_filter %}
          <a href="{% url 'tenant_billing' %}" class="inline-flex items-center justify-center rounded-2xl border-2 border-slate-200 bg-white px-8 py-4 text-sm font-black text-slate-600 transition hover:bg-slate-50">
            Reset
          </a>
        {% endif %}
      </div>
    </form>
  </div>

  <!-- 3. Current Bill Mega-Card -->
  <div class="relative rounded-[3rem] p-1 overflow-hidden shadow-2xl {% if current_bill and current_bill.total_balance > 0 %}bg-gradient-to-br from-rose-400 via-rose-500 to-red-600{% else %}bg-gradient-to-br from-emerald-400 via-emerald-500 to-teal-600{% endif %}">
    <div class="bg-white rounded-[2.9rem] overflow-hidden flex flex-col lg:flex-row">
      <!-- Left Side (Details) -->
      <div class="flex-1 p-8 sm:p-12 {% if current_bill and current_bill.total_balance > 0 %}bg-rose-50/30{% else %}bg-emerald-50/30{% endif %}">
        <div class="flex flex-wrap items-center gap-3 mb-6">
          <span class="text-xs font-black uppercase tracking-widest {% if current_bill and current_bill.total_balance > 0 %}text-rose-600{% else %}text-emerald-600{% endif %}">
            Current Statement
          </span>
          {% if current_bill and current_bill.status == "PAID" %}
            <span class="bg-emerald-100 text-emerald-800 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border border-emerald-200">Paid</span>
          {% elif current_bill and current_bill.status == "PARTIALLY_PAID" %}
            <span class="bg-amber-100 text-amber-800 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border border-amber-200">Partial</span>
          {% elif current_bill %}
            <span class="bg-rose-100 text-rose-800 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border border-rose-200">Open</span>
          {% else %}
            <span class="bg-slate-100 text-slate-600 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest border border-slate-200">No Bill</span>
          {% endif %}
        </div>

        <h2 class="text-5xl sm:text-6xl font-black tracking-tight text-slate-900 mb-2">
          {% if current_bill %}{{ current_bill.billing_month|date:"F Y" }}{% else %}No active bill{% endif %}
        </h2>
        <p class="text-sm font-bold text-slate-500">
          Due by {% if current_bill and current_bill.due_date %}{{ current_bill.due_date|date:"F j, Y" }}{% else %}-{% endif %}
        </p>

        {% if current_bill %}
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-8">
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
              <span class="block text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2">Rent</span>
              <strong class="block text-xl font-black text-slate-900">&#8369;{{ current_bill.base_rent|default:"0.00"|floatformat:2|intcomma }}</strong>
            </div>
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
              <span class="block text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2">Water</span>
              <strong class="block text-xl font-black text-slate-900">&#8369;{{ current_bill.water_amount|default:"0.00"|floatformat:2|intcomma }}</strong>
            </div>
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
              <span class="block text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2">Parking</span>
              <strong class="block text-xl font-black text-slate-900">&#8369;{{ current_bill.parking_fee|default:"0.00"|floatformat:2|intcomma }}</strong>
            </div>
            <div class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
              <span class="block text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2">Late Fee</span>
              <strong class="block text-xl font-black {% if current_bill.interest > 0 %}text-rose-600{% else %}text-slate-900{% endif %}">&#8369;{{ current_bill.interest|default:"0.00"|floatformat:2|intcomma }}</strong>
            </div>
          </div>
        {% endif %}
      </div>

      <!-- Right Side (Action) -->
      <div class="lg:w-96 flex flex-col justify-center p-8 sm:p-12 {% if current_bill and current_bill.total_balance > 0 %}bg-rose-50 border-t lg:border-t-0 lg:border-l border-rose-100{% else %}bg-emerald-50 border-t lg:border-t-0 lg:border-l border-emerald-100{% endif %}">
        <span class="text-[10px] font-black uppercase tracking-widest {% if current_bill and current_bill.total_balance > 0 %}text-rose-400{% else %}text-emerald-500{% endif %} block mb-2">
          {% if current_bill and current_bill.total_balance > 0 %}Still Owed{% else %}Total Balance{% endif %}
        </span>
        <strong class="text-5xl font-black text-slate-900 tracking-tight block">
          &#8369;{% if current_bill %}{{ current_bill.total_balance|default:"0.00"|floatformat:2|intcomma }}{% else %}0.00{% endif %}
        </strong>
        <p class="mt-4 text-sm font-bold leading-relaxed {% if current_bill and current_bill.total_balance > 0 %}text-rose-700/80{% else %}text-emerald-700/80{% endif %}">
          {% if current_bill and current_bill.total_balance > 0 %}
            This balance is ready for payment. Settle it to avoid late fees.
          {% else %}
            No outstanding balance for this statement. You are all cleared.
          {% endif %}
        </p>

        {% if has_pending_payment %}
          <span class="mt-8 inline-block w-full text-center bg-amber-200 text-amber-900 px-6 py-4 rounded-2xl font-black text-sm uppercase tracking-widest shadow-md">
            Payment under review
          </span>
        {% elif current_bill and current_bill.total_balance > 0 %}
          <a href="{% url 'tenant_pay_advance' %}" class="mt-8 inline-block w-full text-center bg-slate-900 hover:bg-slate-800 text-white px-6 py-4 rounded-2xl font-black text-sm uppercase tracking-widest transition-all shadow-xl hover:-translate-y-1">
            Pay Now
          </a>
        {% else %}
          <a href="{% url 'tenant_dashboard' %}" class="mt-8 inline-block w-full text-center bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 px-6 py-4 rounded-2xl font-black text-sm uppercase tracking-widest transition-colors">
            Back to Dashboard
          </a>
        {% endif %}
      </div>
    </div>
  </div>

  <!-- 4. Data Tables Section -->
  <div class="grid lg:grid-cols-2 gap-8">
    
    <!-- Status Table -->
    <div class="bg-white border border-slate-200 rounded-[2.5rem] p-8 shadow-sm">
      <div class="flex items-center justify-between mb-8 border-b border-slate-100 pb-6">
        <div>
          <h2 class="text-2xl font-black text-slate-900">Monthly Status</h2>
          <p class="text-sm font-semibold text-slate-500 mt-1">All your contract months</p>
        </div>
        <span class="bg-slate-100 text-slate-600 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest">{{ monthly_status_rows|length }} Months</span>
      </div>

      <div class="overflow-x-auto -mx-8 px-8">
        <table class="w-full text-left border-separate border-spacing-y-2">
          <thead>
            <tr>
              <th class="pb-3 text-[10px] font-black uppercase tracking-widest text-slate-400">Month</th>
              <th class="pb-3 text-[10px] font-black uppercase tracking-widest text-slate-400 text-right">Balance</th>
              <th class="pb-3 text-[10px] font-black uppercase tracking-widest text-slate-400 text-right pr-4">Status</th>
            </tr>
          </thead>
          <tbody>
            {% for row in monthly_status_rows %}
              <tr class="group hover:-translate-y-0.5 transition-transform">
                <td class="bg-slate-50 p-4 rounded-l-2xl border-y border-l border-slate-100 group-hover:bg-white group-hover:border-slate-200 group-hover:shadow-sm transition-all">
                  <strong class="block text-sm font-black text-slate-900">{{ row.month_label }}</strong>
                  <span class="text-xs font-bold text-slate-500">Due: {% if row.due_date %}{{ row.due_date|date:"M d" }}{% else %}-{% endif %}</span>
                </td>
                <td class="bg-slate-50 p-4 border-y border-slate-100 text-right group-hover:bg-white group-hover:border-slate-200 group-hover:shadow-sm transition-all">
                  <strong class="text-sm font-black text-slate-900">&#8369;{{ row.balance|floatformat:2|intcomma }}</strong>
                </td>
                <td class="bg-slate-50 p-4 rounded-r-2xl border-y border-r border-slate-100 text-right pr-4 group-hover:bg-white group-hover:border-slate-200 group-hover:shadow-sm transition-all">
                  <span class="inline-block px-3 py-1.5 rounded-full text-[9px] font-black uppercase tracking-widest
                    {% if row.status == 'PAID' %}bg-emerald-100 text-emerald-800
                    {% elif row.status == 'PARTIALLY_PAID' %}bg-amber-100 text-amber-800
                    {% elif row.status == 'OPEN' %}bg-rose-100 text-rose-800
                    {% else %}bg-slate-200 text-slate-600{% endif %}">
                    {{ row.status_label }}
                  </span>
                </td>
              </tr>
            {% empty %}
              <tr>
                <td colspan="3">
                  <div class="border-2 border-dashed border-slate-200 rounded-3xl p-10 text-center bg-slate-50/50 mt-4">
                    <strong class="text-sm font-black text-slate-900 block">No records</strong>
                  </div>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- History Table -->
    <div class="bg-white border border-slate-200 rounded-[2.5rem] p-8 shadow-sm flex flex-col">
      <div class="flex items-center justify-between mb-8 border-b border-slate-100 pb-6">
        <div>
          <h2 class="text-2xl font-black text-slate-900">Payment History</h2>
          <p class="text-sm font-semibold text-slate-500 mt-1">Approved transactions</p>
        </div>
        <span class="bg-slate-100 text-slate-600 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest">{{ transactions|length }} Records</span>
      </div>

      <div class="overflow-x-auto -mx-8 px-8 flex-1">
        <table class="w-full text-left border-separate border-spacing-y-2">
          <thead>
            <tr>
              <th class="pb-3 text-[10px] font-black uppercase tracking-widest text-slate-400">Date & Ref</th>
              <th class="pb-3 text-[10px] font-black uppercase tracking-widest text-slate-400">Covered</th>
              <th class="pb-3 text-[10px] font-black uppercase tracking-widest text-slate-400 text-right pr-4">Total Paid</th>
            </tr>
          </thead>
          <tbody id="historyTableBody">
            {% for t in transactions %}
              <tr class="history-row group hover:-translate-y-0.5 transition-transform">
                <td class="bg-slate-50 p-4 rounded-l-2xl border-y border-l border-slate-100 group-hover:bg-white group-hover:border-slate-200 group-hover:shadow-sm transition-all">
                  <strong class="block text-sm font-black text-slate-900">{% if t.paid_at %}{{ t.paid_at|date:"M d, Y" }}{% else %}<span class="text-amber-500">Pending</span>{% endif %}</strong>
                  <span class="text-[10px] font-black uppercase tracking-widest text-slate-400">{{ t.reference }}</span>
                </td>
                <td class="bg-slate-50 p-4 border-y border-slate-100 group-hover:bg-white group-hover:border-slate-200 group-hover:shadow-sm transition-all">
                  <span class="text-xs font-bold text-slate-600">
                    {% if t.bill_months_label %}{{ t.bill_months_label }}{% else %}{{ t.months_paid }} Month{{ t.months_paid|pluralize }}{% endif %}
                  </span>
                </td>
                <td class="bg-slate-50 p-4 rounded-r-2xl border-y border-r border-slate-100 text-right pr-4 group-hover:bg-white group-hover:border-slate-200 group-hover:shadow-sm transition-all">
                  <strong class="text-base font-black text-slate-900">&#8369;{{ t.total_amount|floatformat:2|intcomma }}</strong>
                </td>
              </tr>
            {% empty %}
              <tr>
                <td colspan="3">
                  <div class="border-2 border-dashed border-slate-200 rounded-3xl p-10 text-center bg-slate-50/50 mt-4">
                    <strong class="text-sm font-black text-slate-900 block">No payments yet</strong>
                  </div>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="mt-6 pt-6 border-t border-slate-100 flex items-center justify-between" id="historyPagination">
        <div class="text-[10px] font-black uppercase tracking-widest text-slate-400">
          Showing <span id="historyStart" class="text-slate-900">0</span> - <span id="historyEnd" class="text-slate-900">0</span> of <span id="historyTotal" class="text-slate-900">{{ transactions|length }}</span>
        </div>
        <div class="flex items-center gap-2" id="historyPageButtons"></div>
      </div>

    </div>
  </div>

</div>

<!-- Logic Script for Pagination and Loader removal -->
<script>
  document.addEventListener('DOMContentLoaded', function () {
    const skeleton = document.getElementById('tenantBillingSkeleton');
    const content = document.querySelector('[data-page-content]');

    if (skeleton && content) {
      window.addEventListener('load', function () {
        if(skeleton) skeleton.classList.add('hidden');
        if(content) {
          content.classList.remove('tenant-page-content-hidden', 'opacity-0');
          content.classList.add('opacity-100');
        }
      }, { once: true });
    }

    // Pagination Logic
    function setupPagination(rowClass, startId, endId, totalId, containerId, pageSize) {
      const rows = document.querySelectorAll('.' + rowClass);
      const total = rows.length;
      const totalPages = Math.ceil(total / pageSize);
      const container = document.getElementById(containerId);
      const startSpan = document.getElementById(startId);
      const endSpan = document.getElementById(endId);

      if (total <= pageSize) {
        const wrapper = document.getElementById(containerId)?.closest('#historyPagination');
        if (wrapper) wrapper.style.display = 'none';
        rows.forEach(row => row.style.display = '');
        if (startSpan) startSpan.textContent = total > 0 ? 1 : 0;
        if (endSpan) endSpan.textContent = total;
        return;
      }

      function addButton(label, disabled, active, onClick) {
        if (!container) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.disabled = disabled;
        button.className = `w-8 h-8 rounded-xl font-black text-xs flex items-center justify-center transition-all ${active ? 'bg-slate-900 text-white shadow-md' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`;
        if (disabled) button.className += ' opacity-50 cursor-not-allowed';
        button.addEventListener('click', onClick);
        container.appendChild(button);
      }

      function showPage(page) {
        const start = (page - 1) * pageSize;
        const end = Math.min(start + pageSize, total);

        rows.forEach((row, index) => {
          row.style.display = (index >= start && index < end) ? '' : 'none';
        });

        if (startSpan) startSpan.textContent = total > 0 ? start + 1 : 0;
        if (endSpan) endSpan.textContent = end;
        if (!container) return;

        container.innerHTML = '';
        addButton('<', page === 1, false, () => showPage(page - 1));
        for (let i = 1; i <= totalPages; i += 1) {
          addButton(String(i), false, i === page, () => showPage(i));
        }
        addButton('>', page === totalPages, false, () => showPage(page + 1));
      }

      showPage(1);
    }

    setupPagination('history-row', 'historyStart', 'historyEnd', 'historyTotal', 'historyPageButtons', 5);
  });
</script>
{% endblock %}"""

with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)
