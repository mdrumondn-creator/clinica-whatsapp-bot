import sys

with open("admin_dashboard.html", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Add global variable for tracking pending human counts
if "let pendingHumanCount = 0;" not in text:
    text = text.replace("let currentPage = 'dashboard';", "let currentPage = 'dashboard';\nlet pendingHumanCount = 0;")

# 2. Modify loadMensagens to check and alert
load_mensagens_old = """async function loadMensagens() {
  try {
    const data = await api('GET', '/api/admin/mensagens-pendentes');
    const container = document.getElementById('msgs-container');
    if (data.mensagens.length === 0) {"""

load_mensagens_new = """async function loadMensagens() {
  try {
    const data = await api('GET', '/api/admin/mensagens-pendentes');
    const container = document.getElementById('msgs-container');
    
    // Check for human handoff state
    const humanAwaiting = data.mensagens.filter(m => m.etapa_sessao === 'em_atendimento_humano');
    if (humanAwaiting.length > pendingHumanCount) {
      toast('⚠️ Paciente aguardando atendimento manual!', 'error');
      // Tenta tocar um som suave de notificação (o navegador pode bloquear se o usuário não tiver interagido com a página)
      try {
        const audio = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YU'+'A'.repeat(50));
        // audio.play(); // Descomente para ativar som (precisa de um base64 válido de beep)
      } catch(e) {}
    }
    pendingHumanCount = humanAwaiting.length;
    // Atualiza o contador no dashboard se ele estiver visível
    const statMsgs = document.getElementById('stat-msgs');
    if(statMsgs) {
       statMsgs.innerHTML = humanAwaiting.length > 0 ? `<span style="color:var(--danger)">${data.mensagens.length} (${humanAwaiting.length} pendentes)</span>` : data.mensagens.length;
    }

    if (data.mensagens.length === 0) {"""
text = text.replace(load_mensagens_old, load_mensagens_new)

# 3. Modify rendering of message card to show a red badge and resolver button
render_msg_old = """      container.innerHTML = data.mensagens.map(m => `
        <div class="msg-card">
          <div class="msg-header">
            <span class="msg-phone"><span class="material-symbols-rounded">smartphone</span> ${m.telefone_remetente}</span>
            <span class="msg-time">${fmtDatetime(m.created_at)}</span>
          </div>
          <div class="msg-name"><span class="material-symbols-rounded">person</span> ${m.paciente_nome || 'Paciente não identificado'}</div>
          <div class="msg-text">${m.mensagem || '<em style="color:var(--text-3)">mensagem vazia</em>'}</div>
        </div>
      `).join('');"""

render_msg_new = """      container.innerHTML = data.mensagens.map(m => `
        <div class="msg-card ${m.etapa_sessao === 'em_atendimento_humano' ? 'border-danger' : ''}" style="${m.etapa_sessao === 'em_atendimento_humano' ? 'border-left: 4px solid var(--danger);' : ''}">
          <div class="msg-header">
            <span class="msg-phone"><span class="material-symbols-rounded">smartphone</span> ${m.telefone_remetente}</span>
            <span class="msg-time">
              ${m.etapa_sessao === 'em_atendimento_humano' ? '<span class="badge red">AGUARDANDO HUMANO</span>' : ''}
              ${fmtDatetime(m.created_at)}
            </span>
          </div>
          <div class="msg-name"><span class="material-symbols-rounded">person</span> ${m.paciente_nome || 'Paciente não identificado'}</div>
          <div class="msg-text" style="margin-bottom: 0.5rem;">${m.mensagem || '<em style="color:var(--text-3)">mensagem vazia</em>'}</div>
          ${m.etapa_sessao === 'em_atendimento_humano' ? `<button class="btn btn-primary" style="font-size: 0.75rem; padding: 0.3rem 0.6rem;" onclick="resolverAtendimento('${m.telefone_remetente}')">✅ Resolver Atendimento</button>` : ''}
        </div>
      `).join('');"""
text = text.replace(render_msg_old, render_msg_new)

# 4. Add JS function resolverAtendimento
resolve_js = """
async function resolverAtendimento(telefone) {
  try {
    const al = document.getElementById('config-alert');
    await api('POST', '/api/admin/resolver-atendimento', { telefone });
    toast('Atendimento resolvido! Bot reiniciado.', 'success');
    loadMensagens();
  } catch(e) {
    toast('Erro: ' + e.message, 'error');
  }
}
"""
if "async function resolverAtendimento" not in text:
    text = text.replace("async function loadMensagens() {", resolve_js + "\nasync function loadMensagens() {")

with open("admin_dashboard.html", "w", encoding="utf-8") as f:
    f.write(text)
