from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg2 import pool
import psycopg2.extras
import json
import uuid
import logging
import os
from typing import Optional

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
    direcao: Optional[str] = None


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

        # Só crie sessão se o telefone estiver cadastrado como paciente
        cur.execute("""
            SELECT id_paciente FROM paciente WHERE telefone = %s LIMIT 1
        """, (telefone,))
        paciente = cur.fetchone()

        if not paciente:
            return None, None

        id_paciente = paciente[0]

        # Requer pelo menos uma consulta ativa (AGENDADA ou CONFIRMADA)
        cur.execute("""
            SELECT 1 FROM consulta
            WHERE id_paciente = %s AND status IN ('AGENDADA','CONFIRMADA')
            LIMIT 1
        """, (id_paciente,))
        if not cur.fetchone():
            # Sem consulta ativa — não criar sessão para conversas não relacionadas
            return None, None

        # Cria sessão apenas para pacientes com consulta
        contexto_inicial = json.dumps({"etapa": "inicio"})
        cur.execute("""
            INSERT INTO sessao_chatbot (telefone, id_paciente, estado_atual, contexto_json)
            VALUES (%s, %s, 'ABERTA', %s)
            RETURNING id_sessao
        """, (telefone, id_paciente, contexto_inicial))
        
        id_sessao = cur.fetchone()[0]
        conn.commit()

    return id_sessao, "inicio"


def create_session_for_intent(conn, telefone):
    def write_audit(conn, id_registro, tabela, acao, dados_novos):
        with conn.cursor() as acur:
            acur.execute("""
                INSERT INTO auditoria (id_registro, tabela, acao, dados_novos)
                VALUES (%s, %s, %s, %s::jsonb)
            """, (id_registro, tabela, acao, json.dumps(dados_novos)))
        conn.commit()

    with conn.cursor() as cur:
        contexto_inicial = json.dumps({"etapa": "pedir_cpf"})
        cur.execute("""
            INSERT INTO sessao_chatbot (telefone, estado_atual, contexto_json)
            VALUES (%s, 'ABERTA', %s)
            RETURNING id_sessao
        """, (telefone, contexto_inicial))
        id_sessao = cur.fetchone()[0]
        conn.commit()

    # Registrar auditoria para investigação — sessão criada por intenção de agendamento
    write_audit(conn, id_sessao, 'sessao_chatbot', 'CREATE_INTENT_SESSION', {
        'telefone': telefone,
        'contexto': {'etapa': 'pedir_cpf'}
    })

    return id_sessao, "pedir_cpf"


def is_scheduling_intent(texto: str) -> bool:
    if not texto:
        return False
    t = texto.lower()
    keywords = [
        'agend', 'agendar', 'agendado', 'agendada', 'quero agendar', 'marcar', '1',
        'confirm', 'confirmar', 'confirmado'
    ]
    for k in keywords:
        if k in t:
            return True
    return False


# =========================================================
# SALVAR MENSAGEM
# =========================================================
def salvar_mensagem(conn, dados):
    try:
        with conn.cursor() as cur:
            direcao = (dados.direcao or 'ENTRADA').upper()
            cur.execute("""
                INSERT INTO whatsapp_mensagem (
                    telefone_remetente,
                    mensagem,
                    direcao,
                    api_message_id
                )
                VALUES (%s, %s, %s, %s)
            """, (dados.telefone, dados.mensagem, direcao, dados.api_message_id))
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
    # Etapa para coleta de CPF antes de permitir agendamento
    if etapa_atual == "pedir_cpf":
        texto = (mensagem or '').strip()
        # Normaliza: extrai apenas dígitos
        import re
        digits = re.sub(r"\D", "", texto)
        if len(digits) < 11:
            return "Por favor, envie seu CPF (somente números, 11 dígitos) ou número da carteirinha.", "pedir_cpf"

        # Busca paciente por CPF
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_paciente FROM paciente WHERE regexp_replace(coalesce(cpf, ''), '\\D', '', 'g') = %s LIMIT 1
            """, (digits,))
            p = cur.fetchone()

        if not p:
            return "CPF não encontrado. Se você não tem cadastro, responda 'cadastro' para registrar ou envie outro CPF.", "pedir_cpf"

        id_paciente = p[0]
        # Atualiza sessão com id_paciente e direciona para início do fluxo
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sessao_chatbot SET id_paciente = %s, contexto_json = %s
                WHERE telefone = %s
            """, (id_paciente, json.dumps({"etapa": "inicio"}), telefone))
            conn.commit()

        return "Identificação confirmada. " + processar_fluxo(conn, telefone, mensagem, "inicio")[0], "inicio"
    if etapa_atual == "inicio":
        return "Oiê! Tudo bem? 💙 Sou a assistente virtual da Clínica.\nComo posso te ajudar hoje?\n\n1️⃣ Gostaria de agendar uma consulta\n2️⃣ Preciso falar com a recepção", "menu"

    if etapa_atual == "menu":
        if mensagem == "1":
            return "Perfeito! Por favor, digite o número da sua carteirinha ou o ID do horário desejado:", "agendar"
        elif mensagem == "2":
            return "Certo, aguarde só um instante. Já vou chamar uma de nossas atendentes para falar com você! 👩‍⚕️", "fim"
        else:
            return "Ops, não entendi essa opção. Digite 1 para Agendar ou 2 para Falar com a recepção.", "menu"

    if etapa_atual == "agendar":
        try:
            disp_id = int(mensagem)
            sucesso = agendar(conn, telefone, disp_id)

            if sucesso:
                return "✅ Tudo certo! Sua consulta foi agendada com sucesso. Te esperamos lá!", "fim"
            else:
                return "❌ Poxa, parece que esse horário já foi ocupado ou não achei seu cadastro. Vamos tentar outro horário?", "menu"
        except ValueError:
            return "Por favor, digite apenas números válidos do horário.", "agendar"

    return "Seu atendimento foi finalizado. Qualquer coisa é só chamar! 👋", "fim"


# =========================================================
# ENDPOINT PRINCIPAL (Webhook)
# =========================================================
@app.post("/webhook")
def webhook(msg: Mensagem):
    # Gerenciamento de conexão por request
    conn = db_pool.getconn()
    try:
        # Salva a mensagem recebida (inclui campo direcao quando presente)
        salvar_mensagem(conn, msg)

        # Filtro de segurança: ignorar mensagens que têm direção de saída
        if msg.direcao and msg.direcao.upper() in ('SAIDA', 'OUTBOUND', 'OUTGOING', 'SENT'):
            logger.info(f"Ignorando mensagem de saída: {msg.api_message_id} ({msg.direcao})")
            return {"status": "ignored_outbound"}

        # Kill-switch de segurança: impede o bot de responder se não estiver autorizado
        if os.getenv('ALLOW_SEND', 'false').lower() != 'true':
            logger.warning("Envio de mensagens está desabilitado por kill-switch (ALLOW_SEND!=true)")
            return {"status": "sending_disabled"}

        sessao_id, etapa_atual = get_or_create_session(conn, msg.telefone)

        # Se não existe sessão e o número não é de um paciente cadastrado,
        # permita criar sessão somente quando houver intenção explícita de agendamento
        if not sessao_id:
            if is_scheduling_intent(msg.mensagem):
                sessao_id, etapa_atual = create_session_for_intent(conn, msg.telefone)
                logger.info(f"Criada sessão por intenção de agendamento para {msg.telefone}: {sessao_id}")
            else:
                logger.info(f"Nenhuma sessão ativa e nenhum cadastro para {msg.telefone}; ignorando.")
                return {"status": "no_session_or_patient"}

        resposta, nova_etapa = processar_fluxo(
            conn, msg.telefone, msg.mensagem, etapa_atual
        )

        # Registra tentativa de envio no log de mensagens (saída) e na auditoria
        try:
            out_api_id = f"srv-{uuid.uuid4().hex}"
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO whatsapp_mensagem (
                        telefone_remetente,
                        mensagem,
                        direcao,
                        api_message_id,
                        status_envio
                    )
                    VALUES (%s, %s, 'SAIDA', %s, 'ENVIADO')
                """, (msg.telefone, resposta, out_api_id))
                conn.commit()

            # Auditoria do envio
            with conn.cursor() as acur:
                acur.execute("""
                    INSERT INTO auditoria (id_registro, tabela, acao, dados_novos)
                    VALUES (%s, %s, %s, %s::jsonb)
                """, (out_api_id, 'whatsapp_mensagem', 'OUTGOING_SEND', json.dumps({
                    'telefone': msg.telefone,
                    'api_message_id': out_api_id,
                    'mensagem': resposta
                })))
                conn.commit()
        except Exception as e:
            logger.error(f"Falha ao registrar mensagem de saída/auditoria: {e}")

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
