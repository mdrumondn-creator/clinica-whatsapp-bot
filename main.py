from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg2 import pool
import psycopg2.extras
import json
import logging

# Configuração de Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# =========================================================
# POOL DE CONEXÃO DB (Evita Race Conditions no FastAPI)
# =========================================================
try:
    db_pool = pool.ThreadedConnectionPool(
        1, 20,
        host="localhost",
        database="clinica",
        user="postgres",
        password="postgres"
    )
except Exception as e:
    logger.error(f"Erro ao inicializar pool de conexões: {e}")
    raise e

# =========================================================
# DEPENDÊNCIA DE CONEXÃO
# =========================================================
def get_db_connection():
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)


# =========================================================
# MODELO DE ENTRADA (Webhook WhatsApp)
# =========================================================
class Mensagem(BaseModel):
    telefone: str
    mensagem: str
    api_message_id: str


# =========================================================
# UTIL: IDENTIFICAR PACIENTE
# =========================================================
def get_paciente(conn, telefone):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id_paciente FROM paciente
            WHERE telefone = %s
            LIMIT 1
        """, (telefone,))
        res = cur.fetchone()
    return res[0] if res else None


# =========================================================
# UTIL: CRIAR / OBTER SESSÃO
# =========================================================
def get_or_create_session(conn, telefone):
    with conn.cursor() as cur:
        # Correção 1: Coluna estado_atual ao invés de status
        cur.execute("""
            SELECT id_sessao, contexto_json FROM sessao_chatbot
            WHERE telefone = %s AND estado_atual = 'ABERTA'
        """, (telefone,))
        
        sessao = cur.fetchone()

        if sessao:
            id_sessao = sessao[0]
            contexto = sessao[1] if sessao[1] else {}
            etapa = contexto.get("etapa", "inicio")
            return id_sessao, etapa

        # Correção 2: estado_atual segue a Enum ('ABERTA'), e a 'etapa' vai pro JSONB
        contexto_inicial = json.dumps({"etapa": "inicio"})
        cur.execute("""
            INSERT INTO sessao_chatbot (telefone, estado_atual, contexto_json)
            VALUES (%s, 'ABERTA', %s)
            RETURNING id_sessao
        """, (telefone, contexto_inicial))
        
        id_sessao = cur.fetchone()[0]
        conn.commit()

    return id_sessao, "inicio"


# =========================================================
# SALVAR MENSAGEM
# =========================================================
def salvar_mensagem(conn, dados):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO whatsapp_mensagem (
                    telefone_remetente,
                    mensagem,
                    direcao,
                    api_message_id
                )
                VALUES (%s, %s, 'ENTRADA', %s)
            """, (dados.telefone, dados.mensagem, dados.api_message_id))
        conn.commit()
    except psycopg2.IntegrityError:
        # Correção 3: Captura específica para idempotência (evita erro silencioso)
        conn.rollback()
        logger.warning(f"Mensagem duplicada ignorada: {dados.api_message_id}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao salvar mensagem: {e}")


# =========================================================
# AGENDAMENTO COM LOCK (CRÍTICO)
# =========================================================
def agendar(conn, telefone, id_disponibilidade):
    try:
        with conn.cursor() as cur:
            # psycopg2 inicia transação implicitamente, não precisa de BEGIN
            cur.execute("""
                SELECT id_disponibilidade
                FROM disponibilidade
                WHERE id_disponibilidade = %s
                FOR UPDATE
            """, (id_disponibilidade,))

            # Verifica conflito ativo (ignorando canceladas/faltas)
            cur.execute("""
                SELECT 1
                FROM consulta
                WHERE id_disponibilidade = %s
                AND status NOT IN ('CANCELADA','FALTOU')
            """, (id_disponibilidade,))

            if cur.fetchone():
                conn.rollback()
                return False

            paciente_id = get_paciente(conn, telefone)
            if not paciente_id:
                conn.rollback()
                return False

            cur.execute("""
                INSERT INTO consulta (id_paciente, id_disponibilidade)
                VALUES (%s, %s)
            """, (paciente_id, id_disponibilidade))

            conn.commit()
            return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Erro na transação de agendamento: {e}")
        return False


# =========================================================
# FLUXO SIMPLES CHATBOT
# =========================================================
def processar_fluxo(conn, telefone, mensagem, etapa_atual):
    if etapa_atual == "inicio":
        return "Olá! Digite:\n1 - Agendar consulta\n2 - Falar com atendente", "menu"

    if etapa_atual == "menu":
        if mensagem == "1":
            return "Qual ID da disponibilidade deseja?", "agendar"
        elif mensagem == "2":
            return "Encaminhando para atendente.", "fim"
        else:
            return "Opção inválida.", "menu"

    if etapa_atual == "agendar":
        try:
            disp_id = int(mensagem)
            sucesso = agendar(conn, telefone, disp_id)

            if sucesso:
                return "Consulta agendada com sucesso!", "fim"
            else:
                return "Horário indisponível ou paciente não cadastrado.", "menu"
        except ValueError:
            return "Informe um número válido.", "agendar"

    return "Fluxo encerrado.", "fim"


# =========================================================
# ENDPOINT PRINCIPAL (Webhook)
# =========================================================
@app.post("/webhook")
def webhook(msg: Mensagem):
    # Gerenciamento de conexão por request
    conn = db_pool.getconn()
    try:
        salvar_mensagem(conn, msg)

        sessao_id, etapa_atual = get_or_create_session(conn, msg.telefone)

        resposta, nova_etapa = processar_fluxo(
            conn, msg.telefone, msg.mensagem, etapa_atual
        )

        # Atualiza a etapa no JSONB
        with conn.cursor() as cur:
            novo_contexto = json.dumps({"etapa": nova_etapa})
            cur.execute("""
                UPDATE sessao_chatbot
                SET contexto_json = %s
                WHERE id_sessao = %s
            """, (novo_contexto, sessao_id))
            conn.commit()

        return {"resposta": resposta}

    finally:
        # Libera a conexão de volta para o pool
        db_pool.putconn(conn)
