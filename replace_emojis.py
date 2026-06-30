import sys

with open("admin_dashboard.html", "r", encoding="utf-8") as f:
    text = f.read()

# Fix textContent to innerHTML for alerts
text = text.replace("alert.textContent = '❌ ' + e.message;", "alert.innerHTML = '<i data-lucide=\"x-circle\"></i> ' + e.message;\n    lucide.createIcons();")
text = text.replace("configAlert.textContent = '✅ Configurações salvas!';", "configAlert.innerHTML = '<i data-lucide=\"check-circle-2\"></i> Configurações salvas!';\n    lucide.createIcons();")
text = text.replace("configAlert.textContent = '❌ ' + e.message;", "configAlert.innerHTML = '<i data-lucide=\"x-circle\"></i> ' + e.message;\n    lucide.createIcons();")
text = text.replace("toast('✅ '", "toast('<i data-lucide=\"check-circle-2\"></i> '")
text = text.replace("toast('❌ '", "toast('<i data-lucide=\"x-circle\"></i> '")

toast_old = "el.innerHTML = (type === 'success' ? '✅ ' : '❌ ') + msg;"
toast_new = "el.innerHTML = (type === 'success' ? '<i data-lucide=\"check-circle-2\"></i> ' : '<i data-lucide=\"x-circle\"></i> ') + msg;\n  lucide.createIcons();"
text = text.replace(toast_old, toast_new)

# General emoji replacements
replacements = {
    '🏥': '<i data-lucide="hospital"></i>',
    '📊': '<i data-lucide="layout-dashboard"></i>',
    '📋': '<i data-lucide="clipboard-list"></i>',
    '💬': '<i data-lucide="message-circle"></i>',
    '📅': '<i data-lucide="calendar"></i>',
    '👨‍⚕️': '<i data-lucide="stethoscope"></i>',
    '📱': '<i data-lucide="smartphone"></i>',
    '⚙️': '<i data-lucide="settings"></i>',
    '✅': '<i data-lucide="check-circle-2"></i>',
    '🔌': '<i data-lucide="unplug"></i>',
    '👤': '<i data-lucide="user"></i>',
    '🗓️': '<i data-lucide="calendar-days"></i>',
    '🔄': '<i data-lucide="refresh-cw"></i>',
    '❌': '<i data-lucide="x-circle"></i>',
}

for k, v in replacements.items():
    text = text.replace(k, v)

head_script = '<script src="https://unpkg.com/lucide@latest"></script>'
if head_script not in text:
    text = text.replace('</head>', f'  {head_script}\n</head>')

# Ensure lucide.createIcons() runs after initial display or anytime a page is shown.
# We can add it to refreshCurrentPage() or just after load
if 'lucide.createIcons();' not in text:
    text = text.replace('</body>', '  <script>lucide.createIcons();</script>\n</body>')

# Let's also add it to loadConexao because it unhides things that might not render right away if they were created dynamically, 
# though Lucide processes all elements in the DOM. But just to be safe, add it to showPage.
showpage_old = "refreshCurrentPage();\n}"
showpage_new = "refreshCurrentPage();\n  lucide.createIcons();\n}"
text = text.replace(showpage_old, showpage_new)

# Fix CSS for Lucide icons inside `.icon`
css_old = ".sidebar-nav .icon {"
css_new = ".sidebar-nav .icon {\n      display: inline-flex;\n      align-items: center;"
text = text.replace(css_old, css_new)
text = text.replace("font-size: 1.15rem;", "width: 18px; height: 18px;")

# Fix main icons in buttons
btn_old = ".btn {"
btn_new = ".btn {\n      display: inline-flex; align-items: center; justify-content: center; gap: .5rem;"
text = text.replace(btn_old, btn_new)

# Fix the big ✅ font size. It was 4rem for emoji, for lucide we need width/height
big_check_old = "font-size:4rem; margin-bottom:1rem;"
big_check_new = "margin-bottom:1rem; color: #34d399;"
text = text.replace(big_check_old, big_check_new)
text = text.replace('<i data-lucide="check-circle-2"></i>', '<i data-lucide="check-circle-2" style="width:64px; height:64px;"></i>', 1) # Only for the first one if it matches, wait no, let's just use CSS for the big one.

with open("admin_dashboard.html", "w", encoding="utf-8") as f:
    f.write(text)
