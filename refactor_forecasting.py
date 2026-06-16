import re

file_path = r"c:\Users\Domeld\Documents\FEU\3rd Year\3rd Sem\Thesis\RealEstateDemo\templates\admin_portal\forecasting.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace metrics panel
metrics_old = """    <div id="metricsPanel" class="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
      <div class="px-8 py-6 border-b border-slate-100 flex items-center gap-3 flex-wrap">
        <span class="inline-block w-3 h-3 rounded-full bg-indigo-500"></span>
        <h2 class="text-2xl font-black text-slate-900">Model Comparison</h2>
        <span class="text-sm font-bold text-slate-400 bg-slate-100 px-3 py-1 rounded-lg ml-2">Backtested on last 3 months</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-base">
          <thead class="bg-slate-50 border-b border-slate-200">
            <tr>
              <th class="text-left px-8 py-5 text-xs font-black text-slate-500 uppercase tracking-widest w-48">Metric</th>
              <th class="text-center px-8 py-5 text-xs font-black text-indigo-700 uppercase tracking-widest">SARIMA</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr class="hover:bg-slate-50">
              <td class="px-8 py-6 font-black text-slate-900">Revenue RMSE</td>
              <td id="metricRmse" class="px-8 py-6 text-center font-black text-indigo-700">-</td>
            </tr>
            <tr class="hover:bg-slate-50">
              <td class="px-8 py-6 font-black text-slate-900">Revenue MAE</td>
              <td id="metricMae" class="px-8 py-6 text-center font-black text-indigo-700">-</td>
            </tr>
            <tr class="hover:bg-slate-50">
              <td class="px-8 py-6 font-black text-slate-900">Revenue MAPE</td>
              <td id="metricMape" class="px-8 py-6 text-center font-black text-indigo-700">-</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>"""

metrics_new = """    <div id="metricsPanel" class="bg-white border border-slate-200 rounded-[2rem] shadow-sm hover:shadow-lg transition-shadow overflow-hidden">
      <div class="px-8 sm:px-10 py-8 border-b border-slate-100 flex items-center justify-between flex-wrap gap-4">
        <div class="flex items-center gap-3">
           <div class="w-10 h-10 rounded-full bg-indigo-50 flex items-center justify-center border border-indigo-100">
             <span class="inline-block w-3 h-3 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.8)]"></span>
           </div>
           <h2 class="text-2xl font-black text-slate-900 tracking-tight">Model Accuracy Metrics</h2>
        </div>
        <span class="text-xs font-black text-indigo-600 bg-indigo-50 border border-indigo-100 px-4 py-2 rounded-full uppercase tracking-widest shadow-sm">Backtested (Last 3 Months)</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-base">
          <thead class="bg-slate-50 border-b border-slate-200">
            <tr>
              <th class="text-left px-8 sm:px-10 py-5 text-xs font-black text-slate-400 uppercase tracking-widest">Performance Metric</th>
              <th class="text-right px-8 sm:px-10 py-5 text-xs font-black text-indigo-700 uppercase tracking-widest">SARIMA Score</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr class="hover:bg-slate-50 transition-colors">
              <td class="px-8 sm:px-10 py-6 font-bold text-slate-700">Root Mean Square Error <span class="text-xs text-slate-400 block mt-1 font-medium">(RMSE)</span></td>
              <td id="metricRmse" class="px-8 sm:px-10 py-6 text-right font-black text-indigo-700 text-lg">-</td>
            </tr>
            <tr class="hover:bg-slate-50 transition-colors">
              <td class="px-8 sm:px-10 py-6 font-bold text-slate-700">Mean Absolute Error <span class="text-xs text-slate-400 block mt-1 font-medium">(MAE)</span></td>
              <td id="metricMae" class="px-8 sm:px-10 py-6 text-right font-black text-indigo-700 text-lg">-</td>
            </tr>
            <tr class="hover:bg-slate-50 transition-colors">
              <td class="px-8 sm:px-10 py-6 font-bold text-slate-700">Mean Abs. Percentage Error <span class="text-xs text-slate-400 block mt-1 font-medium">(MAPE)</span></td>
              <td id="metricMape" class="px-8 sm:px-10 py-6 text-right font-black text-indigo-700 text-lg">-</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>"""

# Replace visualiztions
viz_old = """    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mt-8 mb-6">
      <h2 class="text-2xl font-black text-slate-900">Forecast Visualizations</h2>
      <div class="flex items-center gap-3">
        <label for="forecastTimeFilter" class="text-sm font-bold text-slate-600 uppercase tracking-widest">Timeframe:</label>
        <select id="forecastTimeFilter" class="px-4 py-2 bg-white border border-slate-300 rounded-lg text-sm font-bold text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-500 shadow-sm cursor-pointer">
          <option value="24" selected>Last 24 Months</option>
          <option value="12">Last 12 Months</option>
          <option value="6">Last 6 Months</option>
          <option value="3">Last 3 Months</option>
        </select>
      </div>
    </div>

    <div class="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
      <div class="mb-4 pb-3 border-b border-slate-100">
        <h2 class="text-2xl font-black text-slate-900 tracking-tight">Revenue Forecast</h2>
        <p class="chart-subtitle text-base text-slate-500 mt-1 font-medium">Last 24 months + 3-month forecast (dashed)</p>
      </div>
      <div class="h-[400px] w-full">
        <canvas id="revenueForecastChart"></canvas>
      </div>
    </div>"""

viz_new = """    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mt-12 mb-8">
      <h2 class="text-3xl font-black text-slate-900 tracking-tight">Forecast Visualizations</h2>
      <div class="flex items-center gap-3 bg-white p-2 border border-slate-200 rounded-[1.25rem] shadow-sm">
        <label for="forecastTimeFilter" class="text-xs font-black text-slate-500 uppercase tracking-widest pl-3">Timeframe</label>
        <select id="forecastTimeFilter" class="px-5 py-2.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-xl text-sm font-bold text-slate-800 focus:outline-none focus:ring-4 focus:ring-slate-500/20 shadow-sm cursor-pointer transition-all outline-none appearance-none">
          <option value="24" selected>Last 24 Months</option>
          <option value="12">Last 12 Months</option>
          <option value="6">Last 6 Months</option>
          <option value="3">Last 3 Months</option>
        </select>
      </div>
    </div>

    <div class="bg-white border border-slate-200 rounded-[2rem] p-8 sm:p-10 shadow-sm hover:shadow-lg transition-shadow">
      <div class="mb-6 pb-4 border-b border-slate-100 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 class="text-2xl font-black text-slate-900 tracking-tight">Revenue Trajectory</h2>
          <p class="chart-subtitle text-sm text-slate-500 mt-1 font-bold">Historical collected revenue vs. 3-month predictive SARIMA model</p>
        </div>
      </div>
      <div class="h-[450px] w-full relative">
        <canvas id="revenueForecastChart"></canvas>
      </div>
    </div>"""

content = content.replace(metrics_old, metrics_new)
content = content.replace(viz_old, viz_new)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
