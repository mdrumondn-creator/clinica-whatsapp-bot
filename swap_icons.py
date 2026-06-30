import sys

with open("admin_dashboard.html", "r", encoding="utf-8") as f:
    text = f.read()

# Remove lucide script
text = text.replace('<script src="https://unpkg.com/lucide@latest"></script>\n', '')
text = text.replace('<script src="https://unpkg.com/lucide@latest"></script>', '')
text = text.replace('<script>lucide.createIcons();</script>\n', '')
text = text.replace('  lucide.createIcons();\n', '')

# Add Material Symbols CSS
material_css = '<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />'
if material_css not in text:
    text = text.replace('</head>', f'  {material_css}\n</head>')

# Define mapping from lucide to material
mapping = {
    '<i data-lucide="hospital"></i>': '<span class="material-symbols-rounded">local_hospital</span>',
    '<i data-lucide="layout-dashboard"></i>': '<span class="material-symbols-rounded">space_dashboard</span>',
    '<i data-lucide="clipboard-list"></i>': '<span class="material-symbols-rounded">content_paste</span>',
    '<i data-lucide="message-circle"></i>': '<span class="material-symbols-rounded">chat</span>',
    '<i data-lucide="calendar"></i>': '<span class="material-symbols-rounded">calendar_month</span>',
    '<i data-lucide="stethoscope"></i>': '<span class="material-symbols-rounded">stethoscope</span>',
    '<i data-lucide="smartphone"></i>': '<span class="material-symbols-rounded">smartphone</span>',
    '<i data-lucide="settings"></i>': '<span class="material-symbols-rounded">settings</span>',
    '<i data-lucide="check-circle-2"></i>': '<span class="material-symbols-rounded">check_circle</span>',
    '<i data-lucide="unplug"></i>': '<span class="material-symbols-rounded">power_off</span>',
    '<i data-lucide="user"></i>': '<span class="material-symbols-rounded">person</span>',
    '<i data-lucide="calendar-days"></i>': '<span class="material-symbols-rounded">calendar_today</span>',
    '<i data-lucide="refresh-cw"></i>': '<span class="material-symbols-rounded">refresh</span>',
    '<i data-lucide="x-circle"></i>': '<span class="material-symbols-rounded">cancel</span>',
}

# The big checkmark had specific style added to the i tag, let's fix that too
text = text.replace('<i data-lucide="check-circle-2" style="width:64px; height:64px;"></i>', '<span class="material-symbols-rounded" style="font-size: 64px;">check_circle</span>')

for k, v in mapping.items():
    text = text.replace(k, v)

# Fix remaining emojis
text = text.replace('📈', '<span class="material-symbols-rounded">trending_up</span>')
text = text.replace('🚪', '<span class="material-symbols-rounded">logout</span>')
text = text.replace('🌓', '<span class="material-symbols-rounded">dark_mode</span>')

# Fix `.icon` class in CSS to support font scaling correctly
css_old = ".sidebar-nav .icon {\n      display: inline-flex;\n      align-items: center;\n      width: 18px; height: 18px;\n      opacity: .8;\n      transition: all var(--transition);\n      margin-right: 4px;\n    }"
css_new = ".sidebar-nav .icon {\n      display: inline-flex;\n      align-items: center;\n      justify-content: center;\n      font-size: 1.25rem;\n      width: 24px; height: 24px;\n      opacity: .8;\n      transition: all var(--transition);\n      margin-right: 6px;\n    }"
text = text.replace(css_old, css_new)

# Make sure material symbols inherit color and align nicely
material_style = """
    .material-symbols-rounded {
      font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      vertical-align: middle;
      font-size: 1.2em; /* scale slightly with text */
    }
"""
if ".material-symbols-rounded {" not in text:
    text = text.replace("/* ===================== BUTTONS ===================== */", material_style + "\n    /* ===================== BUTTONS ===================== */")

# Fix stat watermark size since it's a font now
stat_watermark_old = ".stat-icon-watermark svg {\n      width: 2.5rem; height: 2.5rem;\n    }"
stat_watermark_new = ".stat-icon-watermark .material-symbols-rounded {\n      font-size: 3rem;\n    }"
text = text.replace(stat_watermark_old, stat_watermark_new)

with open("admin_dashboard.html", "w", encoding="utf-8") as f:
    f.write(text)
