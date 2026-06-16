import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\rentals\tenant_dashboard.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace Move In Card
new_move_in = """    <!-- Move In Card if applicable -->
    {% if move_in_payment %}
      <div class="relative overflow-hidden rounded-[2.5rem] p-[2px] bg-gradient-to-r from-amber-400 via-yellow-500 to-orange-500 shadow-2xl">
        <div class="absolute inset-0 bg-white/20 backdrop-blur-3xl animate-pulse"></div>
        <div class="relative bg-slate-950 rounded-[2.4rem] p-8 sm:p-10 flex flex-col md:flex-row md:items-center justify-between gap-6 z-10">
          <div class="absolute -left-12 top-1/2 -translate-y-1/2 w-32 h-32 bg-amber-500/20 rounded-full blur-2xl"></div>
          
          <div class="relative">
            <div class="flex items-center gap-3 mb-2">
              <svg class="w-6 h-6 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.963 11.963 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
              <span class="text-xs font-black uppercase tracking-widest text-amber-500">Initial Fee</span>
            </div>
            <h2 class="text-3xl font-black text-white mt-1">Security Deposit</h2>
            <p class="text-sm font-semibold text-slate-400 mt-2">Your initial payment to secure your room.</p>
          </div>
          <div class="relative flex flex-col md:items-end gap-3 border-t md:border-t-0 md:border-l border-white/10 pt-6 md:pt-0 md:pl-8">
            <div class="flex items-center gap-4">
              <strong class="text-4xl font-black text-white tracking-tight">&#8369;{{ move_in_payment.amount|floatformat:2|intcomma }}</strong>
              <span class="px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest {% if move_in_payment.status == 'APPROVED' %}bg-emerald-500/20 text-emerald-400 border border-emerald-500/30{% else %}bg-amber-500/20 text-amber-400 border border-amber-500/30{% endif %}">
                {{ move_in_payment.status }}
              </span>
            </div>
            <div class="flex items-center gap-3 text-xs font-black uppercase tracking-widest text-slate-400 mt-2">
              <span class="bg-white/10 px-3 py-1.5 rounded-xl text-white">{{ move_in_payment.payment_method }}</span>
              <span class="opacity-60">Ref: {{ move_in_payment.reference_code }}</span>
            </div>
          </div>
        </div>
      </div>
    {% endif %}"""

content = re.sub(r"<!-- Move In Card if applicable -->.*?{% endif %}", new_move_in, content, flags=re.DOTALL)


# Replace Feed Section (Payments & Updates)
new_feed = """    <!-- 4. FEED SECTION (Payments & Updates) -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
      
      <!-- Recent Payments: Wallet Card Style -->
      <div class="bg-slate-50 border border-slate-200 rounded-[2.5rem] p-8 sm:p-10 shadow-inner">
        <div class="flex items-center justify-between mb-8">
          <div>
            <h2 class="text-2xl font-black text-slate-900">Wallet History</h2>
            <p class="text-sm font-semibold text-slate-500 mt-1">Latest transaction records</p>
          </div>
          {% if has_pending_payment %}
            <span class="bg-emerald-100 text-emerald-800 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest">Pending Review</span>
          {% else %}
            <a href="{% url 'tenant_pay_advance' %}" class="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-colors shadow-md">Pay Now</a>
          {% endif %}
        </div>
        
        <div class="space-y-4">
          {% for payment in recent_payments %}
            <!-- Wallet Card Item -->
            <div class="relative overflow-hidden bg-white border border-slate-200 rounded-3xl p-5 shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all group">
              <!-- Side Color Strip -->
              <div class="absolute left-0 top-0 bottom-0 w-2 {% if payment.status == 'APPROVED' %}bg-emerald-500{% elif payment.status == 'PENDING' %}bg-amber-500{% else %}bg-rose-500{% endif %} group-hover:w-3 transition-all duration-300"></div>
              
              <div class="ml-3 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div class="flex items-center gap-4">
                  <div class="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-slate-600 border border-slate-200">
                    <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                  <div>
                    <strong class="text-xl font-black text-slate-900">&#8369;{{ payment.amount|floatformat:2|intcomma }}</strong>
                    <p class="text-[10px] font-black uppercase tracking-widest text-slate-400 mt-1">
                      {{ payment.payment_method }} &bull; {{ payment.reference_code }}
                    </p>
                  </div>
                </div>
                
                <div class="text-right">
                  <span class="inline-block px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest mb-1 {% if payment.status == 'APPROVED' %}bg-emerald-100 text-emerald-800{% elif payment.status == 'PENDING' %}bg-amber-100 text-amber-800{% else %}bg-rose-100 text-rose-800{% endif %}">
                    {{ payment.status }}
                  </span>
                  <p class="text-xs font-bold text-slate-500">{{ payment.created_at|date:"M d, Y" }}</p>
                </div>
              </div>
              
              {% if payment.payment_method == "CASH" and payment.preferred_date %}
                <div class="ml-3 mt-4 pt-4 border-t border-slate-100 flex items-center justify-between">
                  <span class="text-xs font-bold text-slate-600">
                    <svg class="w-4 h-4 inline-block mr-1 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                    Scheduled: {{ payment.preferred_date|date:"M d, Y" }}{% if payment.preferred_time %} at {{ payment.preferred_time|time:"g:i A" }}{% endif %}
                  </span>
                  <span class="px-2 py-1 rounded-lg text-[9px] uppercase tracking-wider font-black {% if payment.schedule_confirmed %}bg-emerald-50 text-emerald-700{% else %}bg-amber-50 text-amber-700{% endif %}">
                    {% if payment.schedule_confirmed %}Confirmed{% else %}Reviewing{% endif %}
                  </span>
                </div>
              {% endif %}
            </div>
          {% empty %}
            <div class="border-2 border-dashed border-slate-300 rounded-3xl p-10 text-center bg-white">
              <div class="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg class="w-8 h-8 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z"></path></svg>
              </div>
              <strong class="text-lg font-black text-slate-900 block">No payments yet</strong>
              <span class="text-sm font-semibold text-slate-500 mt-2 block">Your completed and pending payments will appear here.</span>
            </div>
          {% endfor %}
        </div>
      </div>

      <!-- Updates: Timeline Layout -->
      <div class="bg-white border border-slate-200 rounded-[2.5rem] p-8 sm:p-10 shadow-lg">
        <div class="mb-10">
          <h2 class="text-2xl font-black text-slate-900">Notice Board</h2>
          <p class="text-sm font-semibold text-slate-500 mt-1">Announcements & Building Updates</p>
        </div>
        
        <div class="relative pl-6 space-y-8 border-l-2 border-slate-100">
          {% for a in announcements %}
            <div class="relative">
              <!-- Timeline Dot -->
              <div class="absolute -left-[31px] top-1.5 w-4 h-4 bg-white border-4 border-blue-500 rounded-full shadow-sm"></div>
              
              <div class="bg-slate-50 hover:bg-blue-50/50 border border-slate-100 hover:border-blue-100 rounded-2xl p-5 transition-colors">
                <div class="flex items-center gap-3 mb-2">
                  <span class="text-[10px] font-black uppercase tracking-widest text-blue-600 bg-blue-100 px-2 py-1 rounded-md">{{ a.created_at|date:"M d, Y" }}</span>
                </div>
                <h3 class="text-lg font-black text-slate-900 leading-tight mb-2">{{ a.title }}</h3>
                <p class="text-sm font-medium text-slate-600 leading-relaxed whitespace-pre-line">{{ a.body }}</p>
              </div>
            </div>
          {% empty %}
            <div class="border-2 border-dashed border-slate-200 rounded-3xl p-10 text-center bg-slate-50 relative ml-4">
              <div class="absolute -left-[31px] top-1/2 -translate-y-1/2 w-4 h-4 bg-white border-4 border-slate-300 rounded-full shadow-sm"></div>
              <strong class="text-lg font-black text-slate-900 block">No updates for now</strong>
              <span class="text-sm font-semibold text-slate-500 mt-2 block">Announcements will appear when posted by the admin.</span>
            </div>
          {% endfor %}
        </div>
      </div>

    </div>"""

content = re.sub(r"<!-- 4\. FEED SECTION \(Payments & Updates\).*?</div>\s*</div>\s*</div>\s*</div>", new_feed + "\n  </div>\n</div>", content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
