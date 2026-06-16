import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\unit_detail.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Make the wrapper match
content = content.replace('bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm relative group', 
                          'bg-white border border-slate-200 rounded-[2rem] overflow-hidden shadow-sm relative group')

# Make the status badges sleek and blurred
content = re.sub(
    r'<div class="absolute top-4 left-4 flex flex-wrap items-center gap-2">.*?<span class="inline-block px-4 py-2 bg-white/90 backdrop-blur-md',
    r'''<div class="absolute top-6 left-6 flex flex-wrap items-center gap-2">
            <span class="inline-block px-4 py-2 backdrop-blur-md rounded-full text-[10px] font-black uppercase tracking-widest shadow-xl border
              {% if display_status_label == 'Pending Payment' %}bg-sky-500/90 text-white border-sky-400/30
              {% elif display_status_label == 'Available' %}bg-emerald-500/90 text-white border-emerald-400/30 flex items-center gap-1.5
              {% elif display_status_label == 'Occupied' %}bg-indigo-600/90 text-white border-indigo-400/30
              {% elif display_status_label == 'Under Maintenance' %}bg-amber-500/90 text-white border-amber-400/30
              {% else %}bg-slate-800/90 text-white border-slate-700/30{% endif %}">
              {% if display_status_label == 'Available' %}<span class="w-1.5 h-1.5 rounded-full bg-white animate-pulse"></span>{% endif %}{{ display_status_label }}
            </span>
            
            <span class="inline-block px-4 py-2 bg-white/90 backdrop-blur-md text-slate-900 border border-white/50 rounded-full text-[10px] font-black uppercase tracking-widest shadow-xl''',
    content,
    flags=re.DOTALL
)

# Soften the boxes
content = content.replace('rounded-2xl', 'rounded-[2rem]')

# Make the Room Info block premium
content = content.replace('bg-white border border-slate-200 rounded-[2rem] p-8 shadow-sm', 
                          'bg-white border border-slate-200 rounded-[2rem] p-8 sm:p-10 shadow-sm hover:shadow-lg transition-shadow')

# Occupancy Status Tenant Avatar
content = content.replace('w-16 h-16 rounded-[2rem] bg-slate-900', 'w-16 h-16 rounded-full bg-indigo-100 border-4 border-white text-indigo-700 shadow-lg')
content = content.replace('w-16 h-16 rounded-[2rem] bg-sky-700', 'w-16 h-16 rounded-full bg-sky-100 border-4 border-white text-sky-700 shadow-lg')

# Financial Card
content = content.replace('bg-white border border-slate-200 rounded-[2rem] p-8 shadow-sm space-y-8', 
                          'bg-slate-900 border border-slate-800 rounded-[2rem] p-8 sm:p-10 shadow-2xl shadow-indigo-900/20 space-y-8 relative overflow-hidden text-white')

# Make the Monthly Rent text in Financial Card white and styled
content = re.sub(
    r'<h3 class="text-xs font-black uppercase tracking-widest text-slate-400 mb-2">Monthly Rent</h3>\s*<div class="flex items-baseline gap-2">\s*<strong class="text-4xl font-black text-slate-900 tracking-tight">',
    r'''<!-- Subtle glow -->
        <div class="absolute top-0 right-0 -mr-20 -mt-20 w-64 h-64 rounded-full bg-indigo-500/20 blur-3xl pointer-events-none"></div>
        <div class="relative z-10">
          <h3 class="text-xs font-black uppercase tracking-widest text-slate-400 mb-2">Monthly Rent</h3>
          <div class="flex items-baseline gap-2">
            <strong class="text-4xl font-black text-white tracking-tight">''',
    content
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
