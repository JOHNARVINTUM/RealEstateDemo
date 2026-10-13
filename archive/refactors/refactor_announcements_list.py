import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\announcements.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

new_grid = """<!-- Announcement Cards Stream Grid -->
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
    {% for a in items %}
    
    <!-- Broadcast Card -->
    <div class="bg-white border border-slate-200 rounded-[2rem] flex flex-col justify-between shadow-sm overflow-hidden hover:shadow-xl hover:-translate-y-1 transition-all duration-300 relative group">
      
      <!-- Top Accent Bar -->
      <div class="h-2 w-full {% if a.is_active %}bg-gradient-to-r from-blue-500 to-indigo-500{% else %}bg-slate-200{% endif %}"></div>

      <div class="p-8 sm:p-10 flex flex-col flex-grow">
        <!-- Status Badges -->
        <div class="flex justify-between items-center mb-6">
          <span class="inline-block px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest select-none {% if a.is_active %}bg-blue-50 text-blue-700 border border-blue-100{% else %}bg-slate-100 text-slate-500 border border-slate-200{% endif %}">
            {% if a.is_active %}<span class="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 mr-1 animate-pulse"></span>Live{% else %}Draft{% endif %}
          </span>
          <div class="flex items-center gap-2 text-slate-400">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
            <span class="text-xs font-black uppercase tracking-widest">
              {{ a.created_at|date:"M d, Y" }}
            </span>
          </div>
        </div>

        <!-- Title -->
        <h3 class="text-2xl font-black text-slate-900 leading-tight mb-4 group-hover:text-indigo-600 transition-colors line-clamp-2" title="{{ a.title }}">
          {{ a.title }}
        </h3>

        <!-- Body -->
        <p class="text-sm text-slate-600 leading-relaxed line-clamp-4 font-bold flex-grow" title="{{ a.body }}">
          {{ a.body }}
        </p>
      </div>

      <!-- Footer Actions -->
      <div class="p-6 sm:px-10 bg-slate-50/50 border-t border-slate-100 flex items-center justify-between gap-4 mt-auto">
        
        <!-- Author Profile -->
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-full bg-slate-900 text-white flex items-center justify-center text-sm font-black shadow-lg border-2 border-white">
            {{ a.created_by.email|first|upper|default:"A" }}
          </div>
          <span class="text-[10px] font-black text-slate-500 uppercase tracking-widest">
            By Admin
          </span>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-2">
          <a href="{% url 'admin_edit_announcement' a.id %}" 
             class="w-10 h-10 flex items-center justify-center bg-white border-2 border-slate-200 hover:border-indigo-200 hover:bg-indigo-50 text-slate-400 hover:text-indigo-600 rounded-xl transition-all shadow-sm" title="Edit">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
          </a>

          <a href="{% url 'admin_delete_announcement' a.id %}"
             class="w-10 h-10 flex items-center justify-center bg-white border-2 border-slate-200 hover:border-rose-200 hover:bg-rose-50 text-slate-400 hover:text-rose-600 rounded-xl transition-all shadow-sm" title="Delete">
             <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
          </a>
        </div>

      </div>

    </div>

    {% empty %}
    
    <!-- Empty Response Block -->
    <div class="col-span-full py-24 text-center bg-white border border-slate-200 rounded-[2rem] p-8 shadow-sm">
      <div class="w-24 h-24 bg-slate-50 border-2 border-slate-100 rounded-full flex items-center justify-center mx-auto mb-6">
        <svg class="w-10 h-10 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9.5a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"></path>
        </svg>
      </div>
      <h3 class="text-2xl font-black text-slate-900">No announcements yet.</h3>
      <p class="text-slate-500 mt-2 font-bold max-w-md mx-auto text-sm">Start by posting your first news update for your tenants to keep them informed.</p>
      
      <a href="{% url 'admin_create_announcement' %}" class="inline-block mt-8 px-8 py-3.5 bg-slate-900 hover:bg-slate-800 text-white rounded-xl font-black tracking-wide transition-all shadow-lg active:scale-95">
        + Create First Post
      </a>
    </div>

    {% endfor %}
  </div>"""

content = re.sub(r'<!-- Announcement Cards Stream Grid -->.*?{% endfor %}\s*</div>', new_grid, content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
