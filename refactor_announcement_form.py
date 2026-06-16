import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\announcement_form.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the layout from `<div class="flex-1 w-full max-w-4xl mx-auto">` down to `</header>`
new_header = """<!-- Column: Primary Editor -->
    <div class="flex-1 w-full space-y-6">
      
      <!-- Studio Header -->
      <header class="bg-slate-900 border border-slate-800 rounded-[2rem] p-8 sm:p-10 shadow-2xl relative overflow-hidden group">
        <div class="absolute inset-0 bg-gradient-to-br from-indigo-500/10 via-transparent to-rose-500/10 opacity-50 group-hover:opacity-100 transition-opacity duration-700"></div>
        <div class="absolute -top-24 -right-24 w-64 h-64 bg-indigo-500/20 rounded-full blur-3xl pointer-events-none"></div>
        <div class="relative z-10">
          <div class="flex items-center gap-2 mb-3">
            <span class="inline-block w-3 h-3 rounded-full bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.8)]"></span>
            <span class="text-xs font-black text-indigo-400 uppercase tracking-widest">Broadcast Tool</span>
          </div>
          <h1 class="text-3xl md:text-4xl font-black tracking-tight text-white leading-tight">
            {{ title }}
          </h1>
          <p class="text-slate-400 mt-3 text-lg font-medium leading-relaxed max-w-2xl">Write a message or update for all your tenants to see.</p>
        </div>
      </header>

      <!-- Main Form Block -->
      <div class="bg-white border border-slate-200 rounded-[2rem] shadow-sm hover:shadow-md transition-shadow p-6 sm:p-10">"""

content = re.sub(
    r'<!-- Column: Primary Editor -->.*?</header>',
    new_header,
    content,
    flags=re.DOTALL
)

# Fix bottom closing tags. We replaced a single `<div class="bg-white ...">` with `<!-- Main Form Block --><div class="...">`. So `</div>` tags at the bottom don't need changes.

# Style the inputs
content = re.sub(
    r'<label class="block text-sm font-black text-slate-800 uppercase tracking-widest">',
    r'<label class="block text-xs font-black text-slate-500 mb-2 uppercase tracking-widest">',
    content
)

content = re.sub(
    r'class="w-full px-4 py-4 bg-slate-50 border-2 border-slate-100 rounded-xl text-lg font-bold text-slate-900 focus:bg-white focus:border-slate-900 transition-all outline-none"',
    r'class="w-full px-4 py-3.5 bg-slate-50 border-2 border-slate-100 rounded-xl text-base font-bold text-slate-900 focus:bg-white focus:border-indigo-500 transition-all outline-none"',
    content
)

content = re.sub(
    r'class="w-full px-4 py-4 bg-slate-50 border-2 border-slate-100 rounded-xl text-lg font-medium text-slate-800 leading-relaxed focus:bg-white focus:border-slate-900 transition-all outline-none"',
    r'class="w-full px-4 py-3.5 bg-slate-50 border-2 border-slate-100 rounded-xl text-base font-bold text-slate-900 leading-relaxed focus:bg-white focus:border-indigo-500 transition-all outline-none"',
    content
)

# Form section wrappers - remove `space-y-6` from `<form method="post" class="space-y-6">` to `space-y-8`
content = content.replace(
    '<form method="post" class="space-y-6">',
    '<form method="post" class="space-y-8">'
)

# Toggle styles
content = content.replace(
    'class="w-6 h-6 rounded-lg border-2 border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer transition-all"',
    'class="w-5 h-5 rounded text-indigo-600 border-slate-300 focus:ring-indigo-500 cursor-pointer transition-all"'
)
content = content.replace(
    '<div class="p-6 bg-slate-50 border-2 border-slate-100 rounded-2xl flex items-center gap-4 group cursor-pointer">',
    '<div class="flex items-center pt-2"><label class="inline-flex items-center gap-3 cursor-pointer group">'
)
content = content.replace(
    '</label>\n          </div>',
    '</label></div>'
)
# Change the label classes inside the toggle
content = re.sub(
    r'<label for="id_is_active" class="text-base font-black text-slate-800 cursor-pointer select-none group-hover:text-slate-900">',
    r'<span class="text-sm font-extrabold text-slate-800 select-none uppercase tracking-wider group-hover:text-slate-900">',
    content
)
# Actually we changed label to span for the text since we wrapped it all in `<label>`
content = content.replace(
    'Post this announcement immediately\n            </label>',
    'Post this announcement immediately\n            </span>'
)

# Move the submit controls
# Before:
#           <!-- Actions -->
#           <div class="pt-6 flex flex-col sm:flex-row items-center gap-4">
#             <button ... > ... </button>
#             <a ...> Back </a>
#           </div>

# Replace the actions div
actions_regex = r'<!-- Actions -->\s*<div class="pt-6 flex flex-col sm:flex-row items-center gap-4">.*?</div>\s*</form>'
new_actions = """<!-- Actions -->
          <div class="pt-8 border-t border-slate-100 flex flex-col sm:flex-row items-center gap-3 justify-end">
            <a href="{% url 'admin_announcements' %}" onclick="if (document.referrer) { window.history.back(); return false; }" class="inline-flex items-center gap-2 px-6 py-3.5 bg-white border-2 border-slate-200 rounded-xl text-sm font-extrabold text-slate-700 hover:bg-slate-50 transition-all shadow-sm group">
              <svg class="w-5 h-5 text-slate-400 group-hover:text-slate-600 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 19l-7-7 7-7"></path>
              </svg>
              <span>Cancel</span>
            </a>
            <button type="submit" class="w-full sm:w-auto px-8 py-3.5 bg-slate-900 hover:bg-black text-white rounded-xl font-extrabold text-sm transition-all shadow-xl hover:-translate-y-0.5 active:translate-y-0 active:shadow-md text-center">
              {% if ann %}Update Announcement{% else %}Post Announcement{% endif %}
            </button>
          </div>
        </form>"""

content = re.sub(actions_regex, new_actions, content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
