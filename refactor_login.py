import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\accounts\login.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

new_login_ui = """<div class="min-h-screen flex bg-white font-sans">
  
  <!-- Left Side: Visual/Hero Panel -->
  <div class="hidden lg:flex lg:w-1/2 relative bg-slate-900 overflow-hidden items-end p-16">
    <!-- Animated Gradient Background Elements -->
    <div class="absolute top-[-20%] left-[-10%] w-[120%] h-[120%] bg-gradient-to-br from-indigo-600/30 via-slate-900 to-rose-600/20 blur-[120px] pointer-events-none"></div>
    <div class="absolute bottom-[-10%] right-[-10%] w-[80%] h-[80%] bg-gradient-to-tl from-indigo-500/20 to-transparent blur-[100px] pointer-events-none"></div>
    
    <!-- Pattern Overlay -->
    <div class="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMiIgY3k9IjIiIHI9IjIiIGZpbGw9InJnYmEoMjU1LDI1NSwyNTUsMC4wNSkiLz48L3N2Zz4=')] opacity-50"></div>

    <!-- Hero Content -->
    <div class="relative z-10 w-full max-w-xl">
      <div class="w-16 h-16 bg-white/10 backdrop-blur-md rounded-2xl border border-white/20 flex items-center justify-center mb-8 shadow-2xl">
        <svg class="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"></path></svg>
      </div>
      <h1 class="text-5xl md:text-6xl font-black tracking-tighter text-white leading-[1.1] mb-6">
        Elevate your<br>
        <span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-rose-400">property management.</span>
      </h1>
      <p class="text-slate-300 text-lg md:text-xl font-medium leading-relaxed max-w-md">
        Experience the next generation of seamless real estate administration. Trust the process, stick to the plan.
      </p>
    </div>
  </div>

  <!-- Right Side: Form Panel -->
  <div class="w-full lg:w-1/2 flex items-center justify-center p-8 sm:p-12 lg:p-24 relative bg-white">
    
    <!-- Mobile background decoration -->
    <div class="lg:hidden absolute inset-0 bg-slate-50 opacity-50 pointer-events-none"></div>

    <div class="w-full max-w-md relative z-10">
      
      <!-- Logo Lockup -->
      <div class="flex items-center gap-3 mb-12">
        <img src="{% static 'img/accounts/RealEstate360+ Logo2 jpg.jpg' %}" alt="Logo" class="w-10 h-10 rounded-xl shadow-sm border border-slate-100 object-cover">
        <span class="text-xl font-black text-slate-900 tracking-tight">RealEstate360+</span>
      </div>
      
      <!-- Form Header -->
      <div class="mb-10">
        <h2 class="text-3xl sm:text-4xl font-black text-slate-900 tracking-tight mb-3">Welcome Back</h2>
        <p class="text-base text-slate-500 font-medium leading-relaxed">Enter your credentials to securely access your administrative dashboard.</p>
      </div>

      <!-- Error State -->
      {% if form.errors %}
        <div class="mb-8 p-4 bg-rose-50 border-l-4 border-rose-500 rounded-r-xl flex items-start gap-3">
          <svg class="w-5 h-5 text-rose-600 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"></path>
          </svg>
          <span class="text-sm font-bold text-rose-800">Invalid email or password. Please try again.</span>
        </div>
      {% endif %}

      <!-- The Form -->
      <form method="post" novalidate class="space-y-6">
        {% csrf_token %}
        
        <!-- Email Input -->
        <div class="space-y-2 relative group">
          <label for="id_username" class="block text-xs font-black text-slate-500 uppercase tracking-widest transition-colors group-focus-within:text-indigo-600">Email Address</label>
          <input type="email" id="id_username" name="username" required 
                 class="w-full px-5 py-4 bg-slate-50 border-2 border-slate-100 rounded-2xl text-base font-bold text-slate-900 focus:bg-white focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 transition-all outline-none" 
                 placeholder="name@company.com" value="{{ form.username.value|default_if_none:'' }}">
        </div>

        <!-- Password Input -->
        <div class="space-y-2 relative group">
          <div class="flex justify-between items-center">
            <label for="id_password" class="block text-xs font-black text-slate-500 uppercase tracking-widest transition-colors group-focus-within:text-indigo-600">Password</label>
            <a href="#" class="text-xs font-black text-indigo-600 hover:text-indigo-800 transition-colors">Forgot?</a>
          </div>
          <div class="relative">
             <input type="password" id="id_password" name="password" required 
                    class="w-full pl-5 pr-12 py-4 bg-slate-50 border-2 border-slate-100 rounded-2xl text-base font-bold text-slate-900 focus:bg-white focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 transition-all outline-none" 
                    placeholder="Enter your password">
             
             <!-- Toggle Icon -->
             <button type="button" id="togglePasswordBtn" class="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none transition-colors p-1 rounded-md">
               <svg id="togglePasswordIcon" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                 <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                 <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
               </svg>
             </button>
          </div>
        </div>

        <!-- Submit -->
        <div class="pt-4 space-y-4">
          <button type="submit" class="w-full bg-slate-900 hover:bg-black text-white font-black py-4 rounded-2xl shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all active:translate-y-0 active:shadow-md text-base">
            Sign In to Dashboard
          </button>
          
          <div class="text-center">
            <a href="/" class="inline-block text-sm font-bold text-slate-500 hover:text-slate-900 transition-colors">
              &larr; Return to Landing Page
            </a>
          </div>
        </div>

      </form>
    </div>
  </div>
</div>"""

# Replace the specific block from `<div class="login-page-wrapper">` up to `</div>` just before `{% endif %}`
content = re.sub(
    r'<div class="login-page-wrapper">.*?</div>\s*</div>\s*</div>',
    new_login_ui,
    content,
    flags=re.DOTALL
)

# Fix script - replace toggle id references
content = content.replace("document.getElementById('togglePassword')", "document.getElementById('togglePasswordBtn')")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
