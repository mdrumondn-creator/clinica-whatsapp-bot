"""
create_admin.py
-------------------------------------------------
Script para criar o primeiro usuário administrador
no banco de dados da clínica.

Uso:
    python create_admin.py

Dependências: psycopg2-binary, python-dotenv
    pip install psycopg2-binary python-dotenv
"""

import os
import hashlib
import getpass
import psycopg2

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Sem dotenv, usa variáveis de ambiente normais


def hash_senha(senha: str) -> str:
    """Hash SHA-256 simples (substitua por bcrypt em produção)."""
    return hashlib.sha256(senha.encode()).hexdigest()


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
        print(f"\n✅ Usuário criado com sucesso! ID: {id_usuario}")
        return True
    except psycopg2.IntegrityError:
        print(f"\n❌ Erro: login '{login}' já existe no banco.")
        return False
    except Exception as e:
        print(f"\n❌ Erro ao conectar ou inserir: {e}")
        return False
    finally:
        if conn:
            conn.close()


def main():
    print("=" * 50)
    print("  Clínica Bot — Criar Usuário Administrador")
    print("=" * 50)
    print()

    nome = input("Nome completo: ").strip()
    if not nome:
        print("❌ Nome não pode ser vazio.")
        return

    login = input("Login (usuário): ").strip()
    if not login:
        print("❌ Login não pode ser vazio.")
        return

    senha = getpass.getpass("Senha (não será exibida): ")
    if len(senha) < 8:
        print("❌ Senha deve ter ao menos 8 caracteres.")
        return

    confirmar = getpass.getpass("Confirme a senha: ")
    if senha != confirmar:
        print("❌ As senhas não coincidem.")
        return

    perfil = input("Perfil [admin/recepcionista] (padrão: admin): ").strip() or "admin"

    print(f"\nCriando usuário '{login}' com perfil '{perfil}'...")
    criar_usuario(nome, login, senha, perfil)


if __name__ == "__main__":
    main()
