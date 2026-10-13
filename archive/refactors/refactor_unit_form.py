import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\unit_form_with_images.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Update header and form rounding
content = content.replace(
    'class="bg-white border border-slate-200 rounded-xl p-8 shadow-xs"',
    'class="bg-white border border-slate-200 rounded-[2rem] p-8 sm:p-10 shadow-sm"'
)
content = content.replace(
    'class="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden divide-y divide-slate-100"',
    'class="bg-white border border-slate-200 rounded-[2rem] shadow-sm overflow-hidden divide-y divide-slate-100"'
)

# Enhance section headers and numbering
content = content.replace(
    'w-6 h-6 rounded-md bg-slate-100 text-slate-800 font-extrabold text-sm',
    'w-8 h-8 rounded-full bg-indigo-600 text-white font-black text-sm shadow-md'
)

# Inputs, selects, and textareas styling
content = content.replace(
    'bg-white border border-slate-300 rounded-lg text-base font-medium text-slate-900 focus:ring-2 focus:ring-slate-500 focus:border-slate-500 transition-all outline-none',
    'bg-slate-50 border border-slate-200 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:ring-4 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all outline-none'
)

# Photo Box
content = content.replace(
    'bg-white border-2 border-dashed border-slate-300 rounded-xl p-8',
    'bg-white border-2 border-dashed border-slate-300 rounded-[2rem] p-10 hover:shadow-lg hover:-translate-y-1'
)
content = content.replace(
    'w-16 h-16 bg-slate-50 border border-slate-200 rounded-xl',
    'w-20 h-20 bg-indigo-50 border border-indigo-100 rounded-[2rem] text-indigo-600'
)

# Button styling
content = content.replace(
    'bg-slate-800 hover:bg-slate-900 text-white rounded-lg',
    'bg-slate-900 hover:bg-black text-white rounded-xl shadow-xl hover:-translate-y-0.5 active:translate-y-0 active:shadow-md'
)

# Existing Images grid cards
content = content.replace(
    'bg-white border border-slate-200 rounded-xl overflow-hidden shadow-xs relative flex flex-col h-72',
    'bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm hover:shadow-lg transition-shadow relative flex flex-col h-72'
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
