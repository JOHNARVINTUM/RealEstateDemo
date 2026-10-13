import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\unit_form_with_images.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

new_header = """<!-- Studio Header -->
      <header class="bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-indigo-500/10 via-transparent to-rose-500/10 opacity-50 group-hover:opacity-100 transition-opacity duration-700"></div>
        <div class="absolute -top-24 -right-24 w-64 h-64 bg-indigo-500/20 rounded-full blur-3xl pointer-events-none"></div>
        <div class="relative z-10">
          <div class="flex items-center gap-2 mb-3">
            <span class="inline-block w-3 h-3 rounded-full bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.8)]"></span>
            <span class="text-xs font-black text-indigo-400 uppercase tracking-widest">{% if action == "Add" %}New Room{% else %}Room Profile{% endif %}</span>
          </div>
          <h1 class="text-3xl md:text-4xl font-black tracking-tight text-white leading-tight">
            {% if action == "Add" %}Add a New Room{% else %}Edit Room Details{% endif %}
          </h1>
          <p class="text-slate-400 mt-3 text-lg font-medium leading-relaxed max-w-2xl">
            {% if action == "Add" %}
              Add a new room to your property list and set its details.
            {% else %}
              Update the room's details, price, and photos.
            {% endif %}
          </p>
        </div>
      </header>"""

# Replace the header
content = re.sub(r'<!-- Studio Header -->.*?</header>', new_header, content, flags=re.DOTALL)

# Update form tag
content = re.sub(
    r'<form method="post" enctype="multipart/form-data" class="[^"]*">',
    r'<form method="post" enctype="multipart/form-data" class="space-y-6">',
    content
)

# Update Sections to be cards
# Replace `<div class="p-6 sm:p-8 space-y-5">` with card div
content = re.sub(
    r'<div class="p-6 sm:p-8 space-y-5(?: bg-slate-50/30)?">',
    r'<div class="bg-white border border-slate-200 rounded-2xl shadow-sm hover:shadow-md transition-shadow p-6 sm:p-8 space-y-6">',
    content
)

# Update photo section wrapper `<div class="p-6 sm:p-8 space-y-6 bg-slate-50/30">`
content = content.replace(
    '<div class="p-6 sm:p-8 space-y-6 bg-slate-50/30">',
    '<div class="bg-white border border-slate-200 rounded-2xl shadow-sm hover:shadow-md transition-shadow p-6 sm:p-8 space-y-6">'
)

# Update section headers (e.g. `border-b border-slate-100`)
content = content.replace(
    'border-b border-slate-100',
    'border-b border-slate-100 pb-4'
)

# Update numbering styling
content = re.sub(
    r'<span class="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-600 text-white font-black text-sm shadow-md">(\d+)</span>',
    r'<span class="flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-50 text-indigo-700 font-black text-sm border border-indigo-100">\1</span>',
    content
)

# Update labels to match `text-xs font-black text-slate-500 mb-2 uppercase tracking-widest`
content = re.sub(
    r'<label class="block text-sm font-bold text-slate-800 mb-2 uppercase tracking-wider">',
    r'<label class="block text-xs font-black text-slate-500 mb-2 uppercase tracking-widest">',
    content
)

# Update inputs
# `bg-slate-50 border border-slate-200 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:ring-4 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all outline-none`
# -> `w-full px-4 py-3.5 bg-slate-50 border-2 border-slate-100 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:border-indigo-500 transition-all outline-none`
content = re.sub(
    r'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:ring-4 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all outline-none',
    r'w-full px-4 py-3.5 bg-slate-50 border-2 border-slate-100 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:border-indigo-500 transition-all outline-none',
    content
)

# Select inputs
content = re.sub(
    r'w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-base font-medium text-slate-900 focus:ring-2 focus:ring-slate-500 focus:border-slate-500 transition-all outline-none cursor-pointer',
    r'w-full px-4 py-3.5 bg-slate-50 border-2 border-slate-100 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:border-indigo-500 transition-all outline-none cursor-pointer appearance-none',
    content
)

# Textareas
content = re.sub(
    r'w-full px-4 py-3 bg-white border border-slate-300 rounded-lg text-base font-medium text-slate-900 leading-relaxed focus:ring-2 focus:ring-slate-500 focus:border-slate-500 transition-all outline-none',
    r'w-full px-4 py-3.5 bg-slate-50 border-2 border-slate-100 rounded-xl text-base font-bold text-slate-900 leading-relaxed focus:bg-white focus:border-indigo-500 transition-all outline-none',
    content
)

# Button styling - the submit form block at the end
# `<div class="p-6 bg-slate-50 flex flex-col sm:flex-row items-center gap-3 justify-end">`
content = content.replace(
    '<div class="p-6 bg-slate-50 flex flex-col sm:flex-row items-center gap-3 justify-end">',
    '<div class="bg-white border border-slate-200 rounded-2xl shadow-sm p-6 flex flex-col sm:flex-row items-center gap-3 justify-end mt-8">'
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
