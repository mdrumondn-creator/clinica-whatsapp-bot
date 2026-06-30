import sys
import re

with open("admin_dashboard.html", "r", encoding="utf-8") as f:
    text = f.read()

# First, remove ALL occurrences of modal-usuario completely
text = re.sub(r'<!-- MODAL USUÁRIO -->.*?</div>\s*</div>', '', text, flags=re.DOTALL)

# Now, inject the correct modal right before </body>
correct_modal = """
  <!-- MODAL USUÁRIO -->
  <div id="modal-usuario" style="display:none; position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;z-index:9999;backdrop-filter:blur(2px);" onclick="if(event.target===this) this.style.display='none'">
    <div class="card" style="width: 100%; max-width: 400px; margin: 1rem; position: relative; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
      <button onclick="document.getElementById('modal-usuario').style.display='none'" style="position:absolute;top:1rem;right:1rem;background:none;border:none;color:var(--text-1);font-size:1.5rem;cursor:pointer;">&times;</button>
      <div class="card-header" style="border-bottom: 1px solid var(--border); padding-bottom: .5rem; margin-bottom: 1rem;">
        <div class="card-title"><span class="material-symbols-rounded">person_add</span> Novo Usuário</div>
      </div>
      <div class="form-group" style="margin-top:1rem;">
        <label>Nome</label>
        <input type="text" id="inp-u-nome" placeholder="Ex: Maria" style="width:100%; padding:.6rem; border:1px solid var(--border); border-radius:.5rem;" />
      </div>
      <div class="form-group" style="margin-top:1rem;">
        <label>Login</label>
        <input type="text" id="inp-u-login" placeholder="Ex: maria.recepcao" style="width:100%; padding:.6rem; border:1px solid var(--border); border-radius:.5rem;" />
      </div>
      <div class="form-group" style="margin-top:1rem;">
        <label>Senha</label>
        <input type="password" id="inp-u-senha" placeholder="***" style="width:100%; padding:.6rem; border:1px solid var(--border); border-radius:.5rem;" />
      </div>
      <div class="form-group" style="margin-top:1rem;">
        <label>Perfil</label>
        <select id="inp-u-perfil" style="width:100%; padding:.6rem; border:1px solid var(--border); border-radius:.5rem;">
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

text = text.replace("</body>", correct_modal + "\n</body>")

with open("admin_dashboard.html", "w", encoding="utf-8") as f:
    f.write(text)
