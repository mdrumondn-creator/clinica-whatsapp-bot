import sys

with open("main.py", "r", encoding="utf-8") as f:
    text_main = f.read()

# Add endpoints for Users
user_endpoints = """
# =========================================================
# ENDPOINTS: USUÁRIOS
# =========================================================
@app.get("/api/admin/usuarios")
def listar_usuarios(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id_usuario, nome, login, perfil, ativo, created_at FROM usuario ORDER BY id_usuario")
            usuarios = cur.fetchall()
            for u in usuarios:
                if u.get("created_at"): u["created_at"] = u["created_at"].isoformat()
        return {"usuarios": usuarios}
    finally:
        db_pool.putconn(conn)

class NovoUsuario(BaseModel):
    nome: str
    login: str
    senha: str
    perfil: str = 'recepcao'

@app.post("/api/admin/usuarios")
def cadastrar_usuario(req: NovoUsuario, user=Depends(admin_auth)):
    if user.get("perfil") != "admin":
        raise HTTPException(status_code=403, detail="Apenas admins podem criar usuários")
        
    conn = db_pool.getconn()
    try:
        senha_hash = hashlib.sha256(req.senha.encode()).hexdigest()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usuario WHERE login = %s", (req.login,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Login já existe")
                
            cur.execute(\"""
                INSERT INTO usuario (nome, login, senha_hash, perfil, ativo)
                VALUES (%s, %s, %s, %s, TRUE)
            \""", (req.nome, req.login, senha_hash, req.perfil))
            conn.commit()
        return {"status": "success", "message": "Usuário criado"}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Login já existe")
    finally:
        db_pool.putconn(conn)

class AlterarSenha(BaseModel):
    id_usuario: int
    nova_senha: str

@app.post("/api/admin/usuarios/senha")
def alterar_senha_usuario(req: AlterarSenha, user=Depends(admin_auth)):
    if user.get("perfil") != "admin":
        raise HTTPException(status_code=403, detail="Apenas admins podem alterar senhas")
        
    conn = db_pool.getconn()
    try:
        senha_hash = hashlib.sha256(req.nova_senha.encode()).hexdigest()
        with conn.cursor() as cur:
            cur.execute("UPDATE usuario SET senha_hash = %s WHERE id_usuario = %s", (senha_hash, req.id_usuario))
            conn.commit()
        return {"status": "success"}
    finally:
        db_pool.putconn(conn)
"""
if "@app.get(\"/api/admin/usuarios\")" not in text_main:
    text_main = text_main.replace("# ENDPOINT: LISTAR CONSULTAS", user_endpoints + "\n# ENDPOINT: LISTAR CONSULTAS")
    with open("main.py", "w", encoding="utf-8") as f:
        f.write(text_main)

# Update HTML
with open("admin_dashboard.html", "r", encoding="utf-8") as f:
    text_html = f.read()

# Add sidebar item
sidebar_item = """
          <a href="#" class="nav-item" onclick="showPage('usuarios')">
            <span class="icon"><span class="material-symbols-rounded">group</span></span> Usuários
          </a>
          <a href="#" class="nav-item" onclick="showPage('conexao')">"""
text_html = text_html.replace("""<a href="#" class="nav-item" onclick="showPage('conexao')">""", sidebar_item)

# Add page HTML
page_html = """
    <!-- PAGE: USUARIOS -->
    <div class="page animate-in" id="page-usuarios">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title"><span class="material-symbols-rounded">group</span> Gestão de Usuários</h3>
          <button class="btn btn-primary" onclick="document.getElementById('modal-usuario').style.display='flex'">Novo Usuário</button>
        </div>
        <div class="table-responsive">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Nome</th>
                <th>Login</th>
                <th>Perfil</th>
                <th>Status</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody id="users-container">
              <tr><td colspan="6" style="text-align:center;">Carregando...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
"""
text_html = text_html.replace('<!-- PAGE: CONEXAO -->', page_html + '\n    <!-- PAGE: CONEXAO -->')

# Add Modal HTML
modal_html = """
  <!-- MODAL USUÁRIO -->
  <div class="modal-overlay" id="modal-usuario" style="display:none;" onclick="if(event.target===this) this.style.display='none'">
    <div class="modal-content" style="max-width:400px;">
      <h3>Novo Usuário</h3>
      <div class="form-group" style="margin-top:1rem;">
        <label>Nome</label>
        <input type="text" id="inp-u-nome" placeholder="Ex: Maria" />
      </div>
      <div class="form-group">
        <label>Login</label>
        <input type="text" id="inp-u-login" placeholder="Ex: maria.recepcao" />
      </div>
      <div class="form-group">
        <label>Senha</label>
        <input type="password" id="inp-u-senha" placeholder="***" />
      </div>
      <div class="form-group">
        <label>Perfil</label>
        <select id="inp-u-perfil">
          <option value="recepcao">Recepção</option>
          <option value="admin">Administrador</option>
        </select>
      </div>
      <div style="display:flex; justify-content:flex-end; gap:.5rem; margin-top:1.5rem;">
        <button class="btn btn-ghost" onclick="document.getElementById('modal-usuario').style.display='none'">Cancelar</button>
        <button class="btn btn-primary" onclick="cadastrarUsuario()">Salvar</button>
      </div>
    </div>
  </div>
"""
text_html = text_html.replace('<!-- MODAL PACIENTE -->', modal_html + '\n  <!-- MODAL PACIENTE -->')

# Add JS logic
js_logic = """
async function loadUsuarios() {
  try {
    const data = await api('GET', '/api/admin/usuarios');
    const tbody = document.getElementById('users-container');
    if (data.usuarios.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">Sem usuários</div></td></tr>`;
    } else {
      tbody.innerHTML = data.usuarios.map(u => `
        <tr>
          <td>#${u.id_usuario}</td>
          <td>${u.nome}</td>
          <td>${u.login}</td>
          <td>${u.perfil === 'admin' ? '<span class="badge blue">Admin</span>' : '<span class="badge yellow">Recepção</span>'}</td>
          <td>${u.ativo ? '<span class="badge green">Ativo</span>' : '<span class="badge red">Inativo</span>'}</td>
          <td>
            <button class="btn btn-ghost" style="padding:.2rem .4rem;font-size:.75rem;" onclick="mudarSenha(${u.id_usuario})">Mudar Senha</button>
          </td>
        </tr>
      `).join('');
    }
  } catch (e) {
    console.error(e);
  }
}

async function cadastrarUsuario() {
  try {
    const nome = document.getElementById('inp-u-nome').value.trim();
    const login = document.getElementById('inp-u-login').value.trim();
    const senha = document.getElementById('inp-u-senha').value.trim();
    const perfil = document.getElementById('inp-u-perfil').value;
    if(!nome || !login || !senha) return toast('Preencha todos os campos', 'error');
    
    await api('POST', '/api/admin/usuarios', { nome, login, senha, perfil });
    toast('Usuário criado com sucesso!', 'success');
    document.getElementById('modal-usuario').style.display='none';
    ['inp-u-nome', 'inp-u-login', 'inp-u-senha'].forEach(id => document.getElementById(id).value = '');
    loadUsuarios();
  } catch (e) {
    toast('Erro: ' + e.message, 'error');
  }
}

async function mudarSenha(id_usuario) {
  const nova_senha = prompt('Digite a nova senha para este usuário:');
  if(!nova_senha) return;
  try {
    await api('POST', '/api/admin/usuarios/senha', { id_usuario, nova_senha });
    toast('Senha atualizada com sucesso!', 'success');
  } catch(e) {
    toast('Erro: ' + e.message, 'error');
  }
}
"""
text_html = text_html.replace("async function loadConfig() {", js_logic + "\nasync function loadConfig() {")
text_html = text_html.replace("if (page === 'conexao') loadConexao();", "if (page === 'conexao') loadConexao();\n  if (page === 'usuarios') loadUsuarios();")

with open("admin_dashboard.html", "w", encoding="utf-8") as f:
    f.write(text_html)
