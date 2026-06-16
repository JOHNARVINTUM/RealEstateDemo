import os

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\rentals\tenant_dashboard.html"

new_content = """{% extends "tenant_base.html" %}
{% load humanize %}
{% block title %}Home | RealEstate360+{% endblock %}
{% block meta_description %}See your bills, rent status, payments, and news.{% endblock %}

{% block tenant_content %}

<!-- SKELETON LOADER -->
<div id="tenantDashboardSkeleton" class="space-y-6 animate-pulse">
  <div class="h-40 bg-slate-200 rounded-3xl w-full"></div>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="h-64 bg-slate-200 rounded-3xl col-span-2"></div>
    <div class="h-64 bg-slate-200 rounded-3xl col-span-1"></div>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
    <div class="h-32 bg-slate-200 rounded-3xl"></div>
    <div class="h-32 bg-slate-200 rounded-3xl"></div>
    <div class="h-32 bg-slate-200 rounded-3xl"></div>
    <div class="h-32 bg-slate-200 rounded-3xl"></div>
  </div>
</div>

<!-- MAIN CONTENT -->
<div data-page-content class="hidden opacity-0 transition-opacity duration-700 ease-in-out">
  <div class="max-w-7xl mx-auto space-y-8 pb-12">
    
    <!-- 1. HEADER HERO (Bento Item 1) -->
    <div class="relative overflow-hidden rounded-[2.5rem] bg-slate-950 p-8 sm:p-12 text-white shadow-2xl">
      <!-- Decorative Background Elements -->
      <div class="absolute -top-24 -right-24 w-96 h-96 bg-blue-600 rounded-full mix-blend-multiply filter blur-3xl opacity-50"></div>
      <div class="absolute -bottom-24 -left-24 w-72 h-72 bg-emerald-500 rounded-full mix-blend-multiply filter blur-3xl opacity-30"></div>
      
      <div class="relative z-10 flex flex-col md:flex-row md:items-end md:justify-between gap-8">
        <div>
          <div class="flex items-center gap-3 mb-6">
            <span class="flex h-3 w-3 relative">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full {% if lease %}bg-emerald-400{% else %}bg-amber-400{% endif %} opacity-75"></span>
              <span class="relative inline-flex rounded-full h-3 w-3 {% if lease %}bg-emerald-500{% else %}bg-amber-500{% endif %}"></span>
            </span>
            {% if all_active_leases.count > 1 and lease %}
              <div class="relative inline-block">
                <select onchange="if(this.value) window.location.href='?lease_id='+this.value"
                        class="appearance-none rounded-full bg-white/10 border border-white/20 text-white py-1.5 pl-4 pr-10 text-xs font-black uppercase tracking-widest outline-none backdrop-blur-md focus:bg-white/20 transition-colors cursor-pointer">
                  {% for l in all_active_leases %}
                    <option class="text-slate-900" value="{{ l.id }}" {% if l.id == lease.id %}selected{% endif %}>
                      Room {{ l.unit.number }} - {{ l.start_date|date:"M d, Y" }}
                    </option>
                  {% endfor %}
                </select>
                <svg class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 9l-7 7-7-7"/>
                </svg>
              </div>
              <span class="rounded-full bg-blue-500/20 border border-blue-400/30 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-blue-200 backdrop-blur-sm">
                {{ all_active_leases.count }} Units
              </span>
            {% else %}
              <span class="rounded-full bg-white/10 border border-white/20 px-4 py-1.5 text-[10px] font-black uppercase tracking-widest text-white backdrop-blur-sm">
                {% if lease %}Room {{ lease.unit.number }}{% else %}Waiting for room assignment{% endif %}
              </span>
            {% endif %}
          </div>
          
          <h1 class="text-4xl sm:text-6xl font-black tracking-tight mb-2">
            Hello, {% if profile and profile.first_name %}{{ profile.first_name }}{% else %}{{ request.user.username }}{% endif %}
          </h1>
          <p class="text-slate-400 font-medium text-lg">{{ request.user.email }}</p>
        </div>

        <div class="bg-white/10 backdrop-blur-lg border border-white/20 rounded-3xl p-5 text-right min-w-[180px]">
          <span class="text-[10px] font-black uppercase tracking-widest text-slate-300">Today</span>
          <strong class="block text-xl font-black text-white mt-1">{% now "F d, Y" %}</strong>
        </div>
      </div>
    </div>

    <!-- 2. MAIN BENTO GRID -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
      
      <!-- Current Billing Card -->
      <div class="lg:col-span-2 rounded-[2.5rem] bg-white border border-slate-200 shadow-xl shadow-slate-200/50 overflow-hidden flex flex-col group">
        <div class="p-8 sm:p-10 flex-1 flex flex-col justify-center {% if current_balance and current_balance.total_balance > 0 %}bg-gradient-to-br from-rose-50/50 to-white{% else %}bg-gradient-to-br from-emerald-50/50 to-white{% endif %}">
          <div class="flex items-center justify-between mb-8">
            <span class="text-xs font-black uppercase tracking-widest {% if current_balance and current_balance.total_balance > 0 %}text-rose-600{% else %}text-emerald-600{% endif %}">Current Billing</span>
            {% if current_balance and current_balance.status == "PARTIALLY_PAID" %}
              <span class="bg-amber-100 text-amber-800 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest">Partial</span>
            {% elif current_balance and current_balance.total_balance > 0 %}
              <span class="bg-rose-100 text-rose-800 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest">Unpaid</span>
            {% else %}
              <span class="bg-emerald-100 text-emerald-800 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest">Cleared</span>
            {% endif %}
          </div>
          
          <h2 class="text-5xl sm:text-7xl font-black text-slate-900 tracking-tighter mb-6">
            {% if current_balance and current_balance.total_balance > 0 %}
              &#8369;{{ current_balance.total_balance|floatformat:2|intcomma }}
            {% elif show_paid_hero and paid_hero_month %}
              {{ paid_hero_month|date:"F Y" }} Paid
            {% else %}
              You're all set
            {% endif %}
          </h2>

          {% if current_balance %}
            <div class="flex flex-wrap gap-6 text-sm font-bold text-slate-500">
              <div class="bg-white/80 backdrop-blur-sm border border-slate-200 rounded-2xl px-5 py-3">Rent <strong class="text-slate-900 ml-2">&#8369;{{ current_balance.rent_balance|floatformat:2|intcomma }}</strong></div>
              <div class="bg-white/80 backdrop-blur-sm border border-slate-200 rounded-2xl px-5 py-3">Water <strong class="text-slate-900 ml-2">&#8369;{{ current_balance.water_balance|floatformat:2|intcomma }}</strong></div>
              <div class="bg-white/80 backdrop-blur-sm border border-slate-200 rounded-2xl px-5 py-3">Parking <strong class="text-slate-900 ml-2">&#8369;{{ current_balance.parking_balance|floatformat:2|intcomma }}</strong></div>
              {% if current_balance.interest > 0 %}
                <div class="bg-rose-50 border border-rose-200 rounded-2xl px-5 py-3 text-rose-700">Late Fee <strong class="ml-2">&#8369;{{ current_balance.interest|floatformat:2|intcomma }}</strong></div>
              {% endif %}
            </div>
          {% elif show_paid_hero %}
            <p class="text-lg font-bold text-emerald-700">Your current billing cycle has been fully settled.</p>
          {% endif %}
        </div>
        
        <!-- Call to Action Footer -->
        <div class="bg-slate-50 border-t border-slate-100 p-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            <span class="text-[10px] font-black uppercase tracking-widest text-slate-400">{% if current_balance and current_balance.total_balance > 0 %}Pay By{% else %}Status{% endif %}</span>
            <strong class="block text-lg font-black text-slate-900">
              {% if current_balance and current_balance.total_balance > 0 %}
                {{ current_balance.due_date|date:"M d, Y" }}
              {% else %}
                Paid
              {% endif %}
            </strong>
          </div>
          <div class="w-full sm:w-auto">
            {% if has_pending_payment %}
              <span class="inline-block w-full text-center bg-orange-100 text-orange-800 border border-orange-200 px-8 py-4 rounded-2xl font-black text-sm uppercase tracking-wider">
                Waiting for approval
              </span>
            {% elif current_balance and current_balance.total_balance > 0 %}
              <a href="{% url 'tenant_pay_advance' %}" class="inline-block w-full text-center bg-blue-600 hover:bg-blue-700 text-white px-8 py-4 rounded-2xl font-black text-sm uppercase tracking-wider transition-colors shadow-lg shadow-blue-600/30">
                Pay Now
              </a>
            {% else %}
              <a href="{% url 'tenant_billing' %}" class="inline-block w-full text-center bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 px-8 py-4 rounded-2xl font-black text-sm uppercase tracking-wider transition-colors">
                View Billing
              </a>
            {% endif %}
          </div>
        </div>
      </div>

      <!-- Next Bill Sidebar Card -->
      <div class="rounded-[2.5rem] bg-indigo-950 text-white p-8 sm:p-10 flex flex-col justify-between shadow-xl relative overflow-hidden">
        <div class="absolute top-0 right-0 w-64 h-64 bg-indigo-600 rounded-full mix-blend-screen filter blur-3xl opacity-30 transform translate-x-1/2 -translate-y-1/2"></div>
        
        <div class="relative z-10">
          <span class="text-xs font-black uppercase tracking-widest text-indigo-300">Next Bill</span>
          <h2 class="text-4xl sm:text-5xl font-black tracking-tight mt-4">
            {% if next_bill_preview %}&#8369;{{ next_bill_preview.total_due|floatformat:2|intcomma }}{% else %}-{% endif %}
          </h2>
          <p class="mt-2 text-base font-medium text-indigo-200">
            {% if next_bill_preview %}{{ next_bill_preview.billing_month|date:"F Y" }}{% else %}No upcoming bill available{% endif %}
          </p>
        </div>
        
        {% if next_bill_preview %}
          <div class="relative z-10 bg-white/10 backdrop-blur-md border border-white/20 rounded-3xl p-6 mt-8">
            <span class="text-[10px] font-black uppercase tracking-widest text-indigo-300">{{ next_due_label|default:"Due Date" }}</span>
            <strong class="block text-2xl font-black mt-2">{{ next_bill_preview.due_date|date:"M d, Y" }}</strong>
          </div>
        {% endif %}
      </div>
    </div>

    <!-- 3. MINI STATS GRID -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-6">
      <div class="bg-white border border-slate-200 rounded-[2rem] p-6 sm:p-8 shadow-sm hover:shadow-lg transition-shadow">
        <span class="text-[10px] font-black uppercase tracking-widest text-slate-400 block mb-3">Move-In Date</span>
        <strong class="text-xl sm:text-2xl font-black text-slate-900 block">{% if lease %}{{ lease.start_date|date:"M d, Y" }}{% else %}-{% endif %}</strong>
      </div>
      <div class="bg-white border border-slate-200 rounded-[2rem] p-6 sm:p-8 shadow-sm hover:shadow-lg transition-shadow">
        <span class="text-[10px] font-black uppercase tracking-widest text-slate-400 block mb-3">Monthly Rent</span>
        <strong class="text-xl sm:text-2xl font-black text-emerald-600 block">{% if total_monthly_rent %}&#8369;{{ total_monthly_rent|floatformat:2|intcomma }}{% else %}-{% endif %}</strong>
        {% if lease and lease.parking_fee > 0 %}
          <span class="text-xs font-semibold text-slate-500 mt-2 block">Includes &#8369;{{ lease.parking_fee|floatformat:2|intcomma }} parking</span>
        {% endif %}
      </div>
      <div class="bg-white border border-slate-200 rounded-[2rem] p-6 sm:p-8 shadow-sm hover:shadow-lg transition-shadow">
        <span class="text-[10px] font-black uppercase tracking-widest text-slate-400 block mb-3">Next Bill</span>
        <strong class="text-xl sm:text-2xl font-black text-indigo-600 block">{% if next_billing_month %}{{ next_billing_month|date:"F Y" }}{% else %}-{% endif %}</strong>
      </div>
      <div class="bg-white border border-slate-200 rounded-[2rem] p-6 sm:p-8 shadow-sm hover:shadow-lg transition-shadow">
        <span class="text-[10px] font-black uppercase tracking-widest text-slate-400 block mb-3">Next Pay Date</span>
        <strong class="text-xl sm:text-2xl font-black text-amber-600 block">{% if next_due_date %}{{ next_due_date|date:"M d, Y" }}{% else %}-{% endif %}</strong>
      </div>
    </div>

    <!-- Move In Card if applicable -->
    {% if move_in_payment %}
      <div class="bg-white border border-slate-200 rounded-[2.5rem] p-8 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <span class="text-[10px] font-black uppercase tracking-widest text-slate-400">Initial Fee</span>
          <h2 class="text-3xl font-black text-slate-900 mt-2">Security Deposit</h2>
          <p class="text-sm font-semibold text-slate-500 mt-1">Your initial payment to secure your room.</p>
        </div>
        <div class="flex flex-col md:items-end gap-3">
          <div class="flex items-center gap-4">
            <strong class="text-3xl font-black text-slate-900">&#8369;{{ move_in_payment.amount|floatformat:2|intcomma }}</strong>
            <span class="px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest {% if move_in_payment.status == 'APPROVED' %}bg-emerald-100 text-emerald-800{% else %}bg-amber-100 text-amber-800{% endif %}">
              {{ move_in_payment.status }}
            </span>
          </div>
          <div class="flex items-center gap-3 text-xs font-black uppercase tracking-widest text-slate-400">
            <span class="bg-slate-100 px-3 py-1 rounded-lg text-slate-600">{{ move_in_payment.payment_method }}</span>
            <span>Ref: {{ move_in_payment.reference_code }}</span>
          </div>
        </div>
      </div>
    {% endif %}

    <!-- 4. FEED SECTION (Payments & Updates) -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
      
      <!-- Recent Payments -->
      <div class="bg-white border border-slate-200 rounded-[2.5rem] p-8 sm:p-10 shadow-lg">
        <div class="flex items-center justify-between mb-8 border-b border-slate-100 pb-6">
          <div>
            <h2 class="text-2xl font-black text-slate-900">Recent Payments</h2>
            <p class="text-sm font-semibold text-slate-500 mt-1">Your latest transaction records</p>
          </div>
          {% if has_pending_payment %}
            <span class="bg-emerald-100 text-emerald-800 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest">Pending Review</span>
          {% else %}
            <a href="{% url 'tenant_pay_advance' %}" class="bg-blue-50 text-blue-700 hover:bg-blue-100 hover:text-blue-800 px-5 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-colors">Pay Now</a>
          {% endif %}
        </div>
        
        <div class="space-y-4">
          {% for payment in recent_payments %}
            <div class="group flex flex-col sm:flex-row sm:items-center gap-5 p-5 rounded-3xl border border-slate-100 bg-slate-50 hover:bg-white hover:border-slate-200 hover:shadow-md transition-all">
              <div class="w-14 h-14 rounded-2xl bg-slate-900 text-white flex items-center justify-center text-xl font-black shadow-inner flex-shrink-0 group-hover:scale-105 transition-transform">
                {{ payment.payment_method|slice:":1" }}
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-3">
                  <strong class="text-xl font-black text-slate-900">&#8369;{{ payment.amount|floatformat:2|intcomma }}</strong>
                  <span class="px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest {% if payment.status == 'APPROVED' %}bg-emerald-100 text-emerald-800{% elif payment.status == 'PENDING' %}bg-amber-100 text-amber-800{% else %}bg-rose-100 text-rose-800{% endif %}">
                    {{ payment.status }}
                  </span>
                </div>
                <p class="text-[10px] font-black uppercase tracking-widest text-slate-400 mt-1 truncate">
                  {{ payment.payment_method }} &bull; {{ payment.reference_code }}
                </p>
                <p class="text-sm font-semibold text-slate-500 mt-1">{{ payment.created_at|date:"M d, Y" }}</p>
                
                {% if payment.payment_method == "CASH" and payment.preferred_date %}
                  <div class="mt-3 bg-white border border-slate-200 rounded-xl px-4 py-3 text-xs font-bold text-slate-600">
                    Scheduled: {{ payment.preferred_date|date:"M d, Y" }}{% if payment.preferred_time %} at {{ payment.preferred_time|time:"g:i A" }}{% endif %}
                    <span class="ml-2 px-2 py-0.5 rounded-lg text-[9px] uppercase tracking-wider font-black {% if payment.schedule_confirmed %}bg-emerald-50 text-emerald-700{% else %}bg-amber-50 text-amber-700{% endif %}">
                      {% if payment.schedule_confirmed %}Confirmed{% else %}Under Review{% endif %}
                    </span>
                  </div>
                {% endif %}
              </div>
            </div>
          {% empty %}
            <div class="border-2 border-dashed border-slate-200 rounded-3xl p-10 text-center bg-slate-50/50">
              <strong class="text-lg font-black text-slate-900 block">No payments yet</strong>
              <span class="text-sm font-semibold text-slate-500 mt-2 block">Your completed and pending payments will appear here.</span>
            </div>
          {% endfor %}
        </div>
      </div>

      <!-- Updates -->
      <div class="bg-white border border-slate-200 rounded-[2.5rem] p-8 sm:p-10 shadow-lg">
        <div class="mb-8 border-b border-slate-100 pb-6">
          <h2 class="text-2xl font-black text-slate-900">Updates</h2>
          <p class="text-sm font-semibold text-slate-500 mt-1">Announcements and building notices</p>
        </div>
        
        <div class="space-y-4">
          {% for a in announcements %}
            <div class="p-6 rounded-3xl border border-slate-100 bg-slate-50 hover:bg-white hover:border-slate-200 hover:shadow-md transition-all">
              <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                <h3 class="text-lg font-black text-slate-900 leading-tight">{{ a.title }}</h3>
                <span class="inline-block bg-white border border-slate-200 rounded-xl px-3 py-1 text-[10px] font-black uppercase tracking-widest text-slate-500 whitespace-nowrap">
                  {{ a.created_at|date:"M d, Y" }}
                </span>
              </div>
              <p class="text-sm font-semibold text-slate-600 leading-relaxed whitespace-pre-line">{{ a.body }}</p>
            </div>
          {% empty %}
            <div class="border-2 border-dashed border-slate-200 rounded-3xl p-10 text-center bg-slate-50/50">
              <strong class="text-lg font-black text-slate-900 block">No updates for now</strong>
              <span class="text-sm font-semibold text-slate-500 mt-2 block">Announcements will appear when posted by the admin.</span>
            </div>
          {% endfor %}
        </div>
      </div>

    </div>
  </div>
</div>

{% endblock %}

{% block tenant_modals %}
  {% if not lease %}
  <div id="noUnitModal" class="fixed inset-0 bg-slate-900/80 backdrop-blur-md flex items-center justify-center z-[1050] p-4">
    <div class="bg-white rounded-3xl border border-slate-200 max-w-lg w-full shadow-2xl overflow-hidden">
      <div class="p-10 text-center">
        <div class="w-20 h-20 bg-blue-50 text-blue-700 rounded-2xl flex items-center justify-center text-3xl mb-6 mx-auto border-2 border-blue-100">
          R
        </div>
        <h3 class="text-3xl font-black text-slate-900 mb-4">Waiting for your room</h3>
        <p class="text-xl text-slate-600 leading-relaxed mb-8">
          Welcome. Your account is active, but we have not assigned you a room yet. Once everything is ready, your rent details will appear here.
        </p>
        <div class="bg-slate-50 rounded-2xl p-6 border-2 border-slate-100 mb-8 text-left">
          <p class="font-black text-slate-800 text-lg mb-3">Next Steps:</p>
          <ul class="space-y-3 text-base text-slate-600 font-bold">
            <li class="flex items-center gap-3">
              <span class="w-2 h-2 rounded-full bg-blue-500"></span>
              Watch your email for updates.
            </li>
            <li class="flex items-center gap-3">
              <span class="w-2 h-2 rounded-full bg-blue-500"></span>
              Check for news in the feed below.
            </li>
          </ul>
        </div>
        <button onclick="closeNoUnitModal()" class="w-full py-5 bg-slate-900 hover:bg-slate-800 text-white rounded-2xl font-black text-xl transition-all shadow-lg active:scale-95">
          Understood
        </button>
      </div>
    </div>
  </div>

  <script>
    function closeNoUnitModal() {
      const modal = document.getElementById('noUnitModal');
      if (modal) modal.style.display = 'none';
    }
    setTimeout(closeNoUnitModal, 15000);
    document.getElementById('noUnitModal').addEventListener('click', function(e) {
      if (e.target === this) closeNoUnitModal();
    });
  </script>
  {% endif %}

  {% if lease and profile and not profile.has_seen_unit_welcome %}
  <div id="unitWelcomeModal" class="fixed inset-0 bg-slate-900/80 backdrop-blur-md flex items-center justify-center z-[1050] p-4">
    <div class="bg-white rounded-3xl border border-slate-200 max-w-lg w-full shadow-2xl overflow-hidden">
      <div class="p-10">
        <div class="w-20 h-20 bg-emerald-50 text-emerald-700 rounded-2xl flex items-center justify-center text-3xl mb-6 border-2 border-emerald-100">
          OK
        </div>
        <h3 class="text-3xl font-black text-slate-900 mb-2">You have a room</h3>
        <p class="text-xl text-slate-600 mb-8 font-medium">You are now in Room <span class="font-black text-slate-900">{{ lease.unit.number }}</span>.</p>
        
        <div class="bg-slate-50 border-2 border-slate-100 rounded-2xl p-6 mb-8 space-y-4">
          <div class="flex justify-between items-center py-2 border-b-2 border-slate-200/50">
            <span class="text-slate-500 font-black uppercase text-xs tracking-widest">Unit Type</span>
            <span class="text-lg font-black text-slate-900">{{ lease.unit.get_unit_type_display }}</span>
          </div>
          <div class="flex justify-between items-center py-2 border-b-2 border-slate-200/50">
            <span class="text-slate-500 font-black uppercase text-xs tracking-widest">Floor / Size</span>
            <span class="text-lg font-black text-slate-900">Floor {{ lease.unit.floor_level }} / {{ lease.unit.size_sqm }} sqm</span>
          </div>
          <div class="flex justify-between items-center py-2 border-b-2 border-slate-200/50">
            <span class="text-slate-500 font-black uppercase text-xs tracking-widest">Monthly Rate</span>
            <span class="text-xl font-black text-emerald-700">&#8369;{{ lease.monthly_rent|floatformat:2|intcomma }}</span>
          </div>
          <div class="flex justify-between items-center py-2">
            <span class="text-slate-500 font-black uppercase text-xs tracking-widest">Pay By</span>
            <span class="text-lg font-black text-slate-900">Day {{ lease.due_day }} of each month</span>
          </div>
        </div>

        <button onclick="closeUnitWelcomeModal()" class="w-full py-5 bg-slate-900 hover:bg-slate-800 text-white rounded-2xl font-black text-xl transition-all shadow-lg active:scale-95">
          Close
        </button>
      </div>
    </div>
  </div>

  <script>
    function closeUnitWelcomeModal() {
      const modal = document.getElementById('unitWelcomeModal');
      if (modal) {
        modal.style.display = 'none';
        fetch('{% url "mark_unit_welcome_seen" %}', {
          method: 'POST',
          headers: {
            'X-CSRFToken': '{{ csrf_token }}',
            'Content-Type': 'application/json',
          },
        }).catch(error => console.log('Error marking welcome as seen:', error));
      }
    }
    setTimeout(closeUnitWelcomeModal, 20000);
    document.getElementById('unitWelcomeModal').addEventListener('click', function(e) {
      if (e.target === this) closeUnitWelcomeModal();
    });
  </script>
  {% endif %}

  <script>
    document.addEventListener('DOMContentLoaded', function () {
      const skeleton = document.getElementById('tenantDashboardSkeleton');
      const content = document.querySelector('[data-page-content]');
      if (!skeleton || !content) return;

      window.addEventListener('load', function () {
        skeleton.classList.add('hidden');
        content.classList.remove('hidden', 'opacity-0');
        content.classList.add('opacity-100');
      }, { once: true });
    });
  </script>
{% endblock %}"""

with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)
