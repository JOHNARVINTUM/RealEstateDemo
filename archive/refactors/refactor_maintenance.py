import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\maintenance_update.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the wrapper class
content = content.replace('maintenance-resolve-studio max-w-6xl', 'tenant-form-wrapper max-w-7xl')

# Add the Premium Studio Header
header_html = """
      <!-- Premium Studio Header -->
      <header class="bg-slate-900 border border-slate-800 rounded-2xl p-6 lg:p-8 shadow-xl shadow-slate-900/10 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6 relative overflow-hidden mb-6">
        <!-- Subtle glow effect -->
        <div class="absolute top-0 right-0 -mr-20 -mt-20 w-64 h-64 rounded-full bg-indigo-500/10 blur-3xl pointer-events-none"></div>

        <div class="relative z-10">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white shadow-inner border border-white/10">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
              </svg>
            </div>
            <h1 class="text-2xl sm:text-3xl font-black tracking-tight text-white leading-tight">Resolve Issue #{{ req.id }}</h1>
          </div>
          <p class="text-sm text-slate-400 mt-1 leading-relaxed pl-13 ml-1">
            Update the status or assign a worker to fix this maintenance request.
          </p>
        </div>
      </header>
"""
content = re.sub(
    r'(<div class="flex-1 space-y-6">\s*)<!-- Main Info Card -->',
    r'\g<1>' + header_html + r'\n      <!-- Main Info Card -->',
    content
)

# Fix primary submit button
content = content.replace('bg-slate-900 hover:bg-black', 'bg-slate-800 hover:bg-slate-900 text-white rounded-lg font-extrabold text-base transition-colors')
content = content.replace('rounded-xl font-black', 'rounded-lg font-extrabold')

# Fix inputs
content = re.sub(
    r'px-4 py-3 bg-white border-2 border-slate-200 rounded-xl text-sm font-bold text-slate-900 focus:border-slate-800 focus:ring-0',
    r'px-4 py-3 bg-white border border-slate-300 rounded-lg text-base font-medium text-slate-900 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 hover:border-slate-400 shadow-sm',
    content
)

content = re.sub(
    r'px-4 py-3 bg-white border-2 border-slate-200 rounded-xl text-sm font-black text-slate-900 focus:border-slate-800 focus:ring-0',
    r'px-4 py-3 bg-white border border-slate-300 rounded-lg text-base font-medium text-slate-900 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 hover:border-slate-400 shadow-sm',
    content
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
