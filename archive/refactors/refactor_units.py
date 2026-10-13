import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\units.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

new_grid = """<!-- Master Grid Display Workspace -->
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
    {% for unit in page_obj %}
    <div class="bg-white border border-slate-200 rounded-[2rem] shadow-sm hover:shadow-2xl hover:shadow-indigo-900/5 hover:-translate-y-1 transition-all duration-500 group flex flex-col h-full overflow-hidden relative">
      
      <!-- Top Image with Gradient Overlay -->
      <div class="relative h-64 bg-slate-100 shrink-0 w-full overflow-hidden rounded-t-[2rem]">
        <img src="{{ unit.cover_image_url }}" alt="Unit {{ unit.number }}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-1000 ease-out">
        <div class="absolute inset-0 bg-gradient-to-t from-slate-900/80 via-slate-900/20 to-transparent"></div>
        
        <!-- Status Badge Top Right -->
        <div class="absolute top-5 right-5">
          {% if unit.display_status_label == "Pending Payment" %}
            <span class="px-3.5 py-1.5 bg-sky-500/90 backdrop-blur-md border border-sky-400/30 text-white text-[10px] font-black uppercase tracking-widest rounded-full shadow-lg">Pending Payment</span>
          {% elif unit.display_status_label == "Under Maintenance" %}
            <span class="px-3.5 py-1.5 bg-amber-500/90 backdrop-blur-md border border-amber-400/30 text-white text-[10px] font-black uppercase tracking-widest rounded-full shadow-lg">Under Repair</span>
          {% elif unit.display_status_label == "Available" %}
            <span class="px-3.5 py-1.5 bg-emerald-500/90 backdrop-blur-md border border-emerald-400/30 text-white text-[10px] font-black uppercase tracking-widest rounded-full shadow-lg flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-white animate-pulse"></span> Available</span>
          {% else %}
            <span class="px-3.5 py-1.5 bg-indigo-600/90 backdrop-blur-md border border-indigo-400/30 text-white text-[10px] font-black uppercase tracking-widest rounded-full shadow-lg">Occupied</span>
          {% endif %}
        </div>
        
        <!-- Price Tag Bottom Left -->
        <div class="absolute bottom-5 left-5">
          <div class="text-[10px] text-slate-300 font-extrabold uppercase tracking-widest mb-0.5">Monthly Rent</div>
          <div class="text-3xl font-black text-white tracking-tight flex items-baseline gap-1">
            <span class="text-xl text-emerald-400 font-bold">₱</span>{{ unit.monthly_rent|floatformat:0|intcomma }}
          </div>
        </div>
      </div>

      <!-- Core Details Padding -->
      <div class="p-6 sm:p-8 flex flex-col flex-1 bg-white relative">
        
        <!-- Main Title & Type -->
        <div class="flex justify-between items-start mb-6">
          <div>
            <h3 class="text-2xl font-black text-slate-900 tracking-tight leading-none mb-2">Room #{{ unit.number }}</h3>
            <p class="text-xs font-bold text-slate-500 uppercase tracking-widest flex items-center gap-2">
              <svg class="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path></svg>
              {{ unit.get_unit_type_display }}
            </p>
          </div>
          <div class="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-lg flex items-center gap-1.5">
            <svg class="w-4 h-4 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"></path></svg>
            <span class="text-sm font-black text-slate-800">{{ unit.size_sqm|floatformat:0 }} <span class="text-[10px] text-slate-400 uppercase">sqm</span></span>
          </div>
        </div>

        <!-- Occupancy Monitor -->
        <div class="mb-8 p-4 rounded-2xl border border-slate-100 bg-slate-50/50">
          <span class="text-[10px] font-black text-slate-400 uppercase tracking-widest block mb-3 pl-1">Current Occupant</span>
          
          {% if unit.pending_lease and not unit.current_tenant %}
            {% with tenant=unit.pending_tenant %}
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full bg-sky-100 border-2 border-white shadow-sm flex items-center justify-center text-sm font-black text-sky-700 shrink-0 relative">
                  {{ tenant.email|first|upper|default:"?" }}
                  <span class="absolute bottom-0 right-0 w-2.5 h-2.5 bg-sky-500 rounded-full border-2 border-white"></span>
                </div>
                <div class="min-w-0 flex-1">
                  <strong class="text-sm font-black text-slate-900 block truncate">
                    {{ tenant.tenantprofile.full_name|default:tenant.email }}
                  </strong>
                  <span class="text-[10px] text-sky-600 font-black uppercase tracking-widest">Awaiting Move-in</span>
                </div>
              </div>
            {% endwith %}
          {% elif not unit.is_active or unit.status == 'MAINTENANCE' %}
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-full bg-amber-100 border-2 border-white shadow-sm flex items-center justify-center text-amber-700 shrink-0">
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
              </div>
              <div class="min-w-0 flex-1">
                <strong class="text-sm font-black text-slate-900 block">Maintenance</strong>
                <span class="text-[10px] text-amber-600 font-black uppercase tracking-widest">Fixes in progress</span>
              </div>
            </div>
          {% elif unit.current_tenant %}
            {% with tenant=unit.current_tenant %}
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full bg-indigo-100 border-2 border-white shadow-sm flex items-center justify-center text-sm font-black text-indigo-700 shrink-0 relative">
                  {{ tenant.email|first|upper|default:"?" }}
                  <span class="absolute bottom-0 right-0 w-2.5 h-2.5 bg-emerald-500 rounded-full border-2 border-white"></span>
                </div>
                <div class="min-w-0 flex-1">
                  <strong class="text-sm font-black text-slate-900 block truncate">
                    {{ tenant.tenantprofile.full_name|default:tenant.email }}
                  </strong>
                  <span class="text-[10px] text-indigo-500 font-black uppercase tracking-widest">Active Tenant</span>
                </div>
              </div>
            {% endwith %}
          {% else %}
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-full bg-slate-100 border-2 border-white shadow-sm border border-dashed border-slate-300 flex items-center justify-center text-slate-400 shrink-0">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
              </div>
              <div class="min-w-0 flex-1">
                <strong class="text-sm font-black text-slate-500 block">No Occupant</strong>
                <span class="text-[10px] text-slate-400 font-black uppercase tracking-widest">Ready for lease</span>
              </div>
            </div>
          {% endif %}
        </div>

        <!-- Action Bar Spacer -->
        <div class="mt-auto grid grid-cols-[auto_1fr] gap-3">
          <a href="{% url 'admin_unit_detail' unit.id %}" class="flex items-center justify-center w-12 h-12 bg-white border-2 border-slate-200 hover:border-slate-800 hover:bg-slate-50 text-slate-700 hover:text-slate-900 rounded-xl transition-all group/btn" title="View Details">
            <svg class="w-5 h-5 group-hover/btn:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
          </a>
          <a href="{% url 'admin_edit_unit' unit.id %}" class="flex items-center justify-center h-12 bg-slate-900 hover:bg-black text-white rounded-xl font-extrabold text-sm transition-all shadow-md hover:shadow-xl hover:-translate-y-0.5 active:translate-y-0 active:shadow-sm">
            Edit Room
          </a>
        </div>

      </div>
    </div>
    {% empty %}"""

content = re.sub(r'<!-- Master Grid Display Workspace -->.*?{% empty %}', new_grid, content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
