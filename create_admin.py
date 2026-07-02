"""
create_admin.py
-------------------------------------------------
Script para criar o primeiro usuário administrador
no banco de dados da clínica.

Uso:
    python create_admin.py

Dependências: psycopg2-binary, bcrypt, python-dotenv
    pip install psycopg2-binary bcrypt python-dotenv
"""

import os
import bcrypt
import getpass
import psycopg2

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Sem dotenv, usa variáveis de ambiente normais


def hash_senha(senha: str) -> str:
    """Hash bcrypt seguro com salt automático."""
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def validar_forca_senha(senha: str) -> bool:
    """Valida requisitos mínimos de senha: 6+ chars e pelo menos 1 número."""
    if len(senha) < 6:
        print("❌ Senha deve ter pelo menos 6 caracteres.")
        return False
    if not any(c.isdigit() for c in senha):
        print("❌ Senha deve conter pelo menos um número.")
        return False
    return True


def criar_usuario(nome: str, login: str, senha: str, perfil: str = "admin") -> bool:
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "clinica"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASS", "postgres"),
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO usuario (nome, login, senha_hash, perfil, ativo)
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING id_usuario
                """,
                (nome, login, hash_senha(senha), perfil),
            )
            id_usuario = cur.fetchone()[0]
        conn.commit()
        print(f"✅ Usuário '{login}' criado com sucesso (id={id_usuario}, perfil={perfil}).")
        return True
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        print(f"❌ Login '{login}' já existe.")
        return False
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"❌ Erro ao criar usuário: {e}")
        return False
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    print("=== Criação de Usuário Admin ===\n")
    nome  = input("Nome completo: ").strip()
    login = input("Login (usuário): ").strip()

    while True:
        senha = getpass.getpass("Senha (mín. 6 chars, 1 número): ")
        if validar_forca_senha(senha):
            confirma = getpass.getpass("Confirme a senha: ")
            if senha == confirma:
                break
            print("❌ As senhas não coincidem. Tente novamente.\n")

    perfil = input("Perfil [admin/recepcao] (padrão: admin): ").strip() or "admin"

    criar_usuario(nome, login, senha, perfil)
