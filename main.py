from fastapi import FastAPI, HTTPException, Depends, Header, Body
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from psycopg2 import pool
import psycopg2.extras
import json
import uuid
import logging
import os
import hashlib
import hmac
import time
import base64
import re
import requests
import os
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://evolution-api:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "sua_api_key_super_secreta")
from typing import Optional, List
from datetime import datetime, time as dt_time, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Configuração de Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# =========================================================
# SCHEDULER: LEMBRETES AUTOMÁTICOS
# =========================================================
scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")

def job_lembrete_24h():
    """Roda a cada hora: envia lembrete 24h antes da consulta."""
    conn = db_pool.getconn()
    try:
        agora = datetime.now()
        janela_inicio = agora + timedelta(hours=23)
        janela_fim    = agora + timedelta(hours=25)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT c.id_consulta, p.telefone, p.nome AS paciente_nome,
                       m.nome AS medico_nome, d.inicio_datetime,
                       cfg.msg_lembrete_24h
                FROM consulta c
                JOIN disponibilidade d ON d.id_disponibilidade = c.id_disponibilidade
                JOIN paciente p ON p.id_paciente = c.id_paciente
                JOIN medico m ON m.id_medico = d.id_medico
                LEFT JOIN configuracao_sistema cfg ON TRUE
                WHERE c.status IN ('AGENDADA','CONFIRMADA')
                  AND c.lembrete_24h_enviado = FALSE
                  AND d.inicio_datetime BETWEEN %s AND %s
            """, (janela_inicio, janela_fim))
            consultas = cur.fetchall()

        for c in consultas:
            nome_curto = c['paciente_nome'].split()[0]
            data_fmt = c['inicio_datetime'].strftime('%d/%m às %H:%M')
            msg_template = c.get('msg_lembrete_24h') or (
                f"Olá, {nome_curto}! 👋\n\n"
                f"Lembramos que você tem consulta com *{c['medico_nome']}* "
                f"amanhã, *{data_fmt}*.\n\n"
                f"Para confirmar, responda *1 - Confirmar* ou *2 - Cancelar*. 🏥"
            )
            mensagem = msg_template.replace('{nome}', nome_curto).replace('{medico}', c['medico_nome']).replace('{data}', data_fmt)
            enviar_mensagem_whatsapp(c['telefone'], mensagem)

            # Marca como enviado e atualiza status
            conn2 = db_pool.getconn()
            try:
                with conn2.cursor() as cur2:
                    cur2.execute("""
                        UPDATE consulta SET lembrete_24h_enviado = TRUE, status = 'CONFIRMADA'
                        WHERE id_consulta = %s
                    """, (c['id_consulta'],))
                    conn2.commit()
            finally:
                db_pool.putconn(conn2)
            logger.info(f"Lembrete 24h enviado para {c['telefone']} (consulta {c['id_consulta']})")
    except Exception as e:
        logger.error(f"Erro no job_lembrete_24h: {e}")
    finally:
        db_pool.putconn(conn)


def job_lembrete_dia():
    """Roda às 07:30 todo dia: envia lembrete no dia da consulta."""
    conn = db_pool.getconn()
    try:
        hoje_inicio = datetime.now().replace(hour=0,  minute=0,  second=0, microsecond=0)
        hoje_fim    = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT c.id_consulta, p.telefone, p.nome AS paciente_nome,
                       m.nome AS medico_nome, d.inicio_datetime,
                       cfg.msg_lembrete_dia
                FROM consulta c
                JOIN disponibilidade d ON d.id_disponibilidade = c.id_disponibilidade
                JOIN paciente p ON p.id_paciente = c.id_paciente
                JOIN medico m ON m.id_medico = d.id_medico
                LEFT JOIN configuracao_sistema cfg ON TRUE
                WHERE c.status IN ('AGENDADA','CONFIRMADA')
                  AND c.lembrete_dia_enviado = FALSE
                  AND d.inicio_datetime BETWEEN %s AND %s
            """, (hoje_inicio, hoje_fim))
            consultas = cur.fetchall()

        for c in consultas:
            nome_curto = c['paciente_nome'].split()[0]
            hora_fmt = c['inicio_datetime'].strftime('%H:%M')
            msg_template = c.get('msg_lembrete_dia') or (
                f"Bom dia, {nome_curto}! ☀️\n\n"
                f"Hoje é o dia da sua consulta com *{c['medico_nome']}* às *{hora_fmt}*.\n\n"
                f"Lembre-se de chegar com 10 minutos de antecedência. Te esperamos! 🏥"
            )
            mensagem = msg_template.replace('{nome}', nome_curto).replace('{medico}', c['medico_nome']).replace('{hora}', hora_fmt)
            enviar_mensagem_whatsapp(c['telefone'], mensagem)

            conn2 = db_pool.getconn()
            try:
                with conn2.cursor() as cur2:
                    cur2.execute("""
                        UPDATE consulta SET lembrete_dia_enviado = TRUE
                        WHERE id_consulta = %s
                    """, (c['id_consulta'],))
                    conn2.commit()
            finally:
                db_pool.putconn(conn2)
            logger.info(f"Lembrete do dia enviado para {c['telefone']} (consulta {c['id_consulta']})")
    except Exception as e:
        logger.error(f"Erro no job_lembrete_dia: {e}")
    finally:
        db_pool.putconn(conn)


@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(job_lembrete_24h, 'interval', hours=1, id='lembrete_24h')
    scheduler.add_job(job_lembrete_dia, CronTrigger(hour=7, minute=30), id='lembrete_dia')
    scheduler.start()
    logger.info("✅ Scheduler de lembretes iniciado.")

@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown(wait=False)

@app.get("/")
def serve_dashboard():
    return FileResponse("admin_dashboard.html")

# =========================================================
# CORS (permite o painel admin acessar a API)
# =========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# CONFIGURAÇÃO JWT SIMPLES (sem dependência externa)
# =========================================================
JWT_SECRET = os.getenv("JWT_SECRET", "clinica-bot-secret-change-me")
JWT_EXPIRATION_SECONDS = 28800  # 8 horas

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)

def criar_token_jwt(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload["exp"] = int(time.time()) + JWT_EXPIRATION_SECONDS
    h = _b64url_encode(json.dumps(header).encode())
    p = _b64url_encode(json.dumps(payload).encode())
    signature = hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    s = _b64url_encode(signature)
    return f"{h}.{p}.{s}"

def verificar_token_jwt(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Token inválido")
        h, p, s = parts
        expected_sig = hmac.new(JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        actual_sig = _b64url_decode(s)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("Assinatura inválida")
        payload = json.loads(_b64url_decode(p))
        if payload.get("exp", 0) < time.time():
            raise ValueError("Token expirado")
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {e}")


# =========================================================
# DEPENDÊNCIA: AUTENTICAÇÃO DO ADMIN
# =========================================================
def admin_auth(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Header Authorization inválido")
    token = authorization[7:]
    payload = verificar_token_jwt(token)
    return payload


# =========================================================
# POOL DE CONEXÃO DB (Evita Race Conditions no FastAPI)
# =========================================================
try:
    db_pool = pool.ThreadedConnectionPool(
        1, 20,
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "clinica"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "postgres")
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
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
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
# MODELOS ADMIN
# =========================================================
class LoginRequest(BaseModel):
    login: str
    senha: str

class ConfigUpdate(BaseModel):
    bot_ativo: Optional[bool] = None
    bot_inicio_funcionamento: Optional[str] = None  # "HH:MM"
    bot_fim_funcionamento: Optional[str] = None      # "HH:MM"
    tempo_padrao_consulta_minutos: Optional[int] = None
    msg_saudacao: Optional[str] = None
    msg_solicitar_cpf: Optional[str] = None
    msg_despedida_lgpd: Optional[str] = None
    msg_solicitar_nome: Optional[str] = None
    msg_fora_horario: Optional[str] = None
    msg_lembrete_24h: Optional[str] = None
    msg_lembrete_dia: Optional[str] = None

class LiberarAgenda(BaseModel):
    id_medico: int
    slots: List[dict]  # [{"inicio": "2026-06-16T08:00:00", "fim": "2026-06-16T08:30:00"}, ...]

class NovoMedico(BaseModel):
    nome: str
    especialidade: Optional[str] = None
    crm: str
    uf_crm: str
    telefone: Optional[str] = None
    email: Optional[str] = None
    tempo_padrao_minutos: Optional[int] = 30


# =========================================================
# UTIL: VERIFICAR HORÁRIO DE FUNCIONAMENTO
# =========================================================
def bot_esta_operacional(conn) -> tuple:
    """Retorna (operacional: bool, config: dict)"""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT *
            FROM configuracao_sistema
            ORDER BY id_config LIMIT 1
        """)
        config = cur.fetchone()

    if not config:
        # Sem configuração — assume operacional
        return True, {}

    if not config["bot_ativo"]:
        return False, dict(config)

    agora = datetime.now().time()
    inicio = config["bot_inicio_funcionamento"]
    fim = config["bot_fim_funcionamento"]

    # Converte para objetos time se forem strings
    if isinstance(inicio, str):
        inicio = dt_time.fromisoformat(inicio)
    if isinstance(fim, str):
        fim = dt_time.fromisoformat(fim)

    dentro_horario = inicio <= agora <= fim
    return dentro_horario, dict(config)


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
        cur.execute("""
            SELECT id_sessao, contexto_json, updated_at FROM sessao_chatbot
            WHERE telefone = %s AND estado_atual = 'ABERTA'
        """, (telefone,))
        
        sessao = cur.fetchone()

        if sessao:
            id_sessao = sessao[0]
            contexto = sessao[1] if sessao[1] else {}
            etapa = contexto.get("etapa", "inicio")
            
            # Timeout logic: if inactive for 15+ mins and in the main flow, reset to 'inicio'
            updated_at = sessao[2]
            if updated_at:
                now_utc = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
                diff = now_utc - updated_at
                if diff.total_seconds() > 900:  # 15 minutes
                    if etapa in ["menu", "escolher_especialidade", "agendar", "fim", "inicio"]:
                        etapa = "inicio"
                        contexto["etapa"] = "inicio"
            
            return id_sessao, etapa, contexto

        # Só crie sessão se o telefone estiver cadastrado como paciente
        cur.execute("""
            SELECT id_paciente FROM paciente WHERE telefone = %s LIMIT 1
        """, (telefone,))
        paciente = cur.fetchone()

        if not paciente:
            return None, None, {}

        id_paciente = paciente[0]

        # Requer pelo menos uma consulta ativa (AGENDADA ou CONFIRMADA)
        cur.execute("""
            SELECT 1 FROM consulta
            WHERE id_paciente = %s AND status IN ('AGENDADA','CONFIRMADA')
            LIMIT 1
        """, (id_paciente,))
        if not cur.fetchone():
            return None, None, {}

        # Cria sessão apenas para pacientes com consulta
        contexto_obj = {"etapa": "inicio"}
        contexto_inicial = json.dumps(contexto_obj)
        cur.execute("""
            INSERT INTO sessao_chatbot (telefone, id_paciente, estado_atual, contexto_json)
            VALUES (%s, %s, 'ABERTA', %s)
            RETURNING id_sessao
        """, (telefone, id_paciente, contexto_inicial))
        
        id_sessao = cur.fetchone()[0]
        conn.commit()

    return id_sessao, "inicio", contexto_obj


def create_session_for_intent(conn, telefone):
    def write_audit(conn, id_registro, tabela, acao, dados_novos):
        with conn.cursor() as acur:
            acur.execute("""
                INSERT INTO auditoria (id_registro, tabela, acao, dados_novos)
                VALUES (%s, %s, %s, %s::jsonb)
            """, (id_registro, tabela, acao, json.dumps(dados_novos)))
        conn.commit()

    with conn.cursor() as cur:
        contexto_obj = {"etapa": "inicio_agendamento"}
        contexto_inicial = json.dumps(contexto_obj)
        cur.execute("""
            INSERT INTO sessao_chatbot (telefone, estado_atual, contexto_json)
            VALUES (%s, 'ABERTA', %s)
            RETURNING id_sessao
        """, (telefone, contexto_inicial))
        id_sessao = cur.fetchone()[0]
        conn.commit()

    # Registrar auditoria para investigação
    write_audit(conn, id_sessao, 'sessao_chatbot', 'CREATE_INTENT_SESSION', {
        'telefone': telefone,
        'contexto': contexto_obj
    })

    return id_sessao, "inicio_agendamento", contexto_obj


def is_scheduling_intent(texto: str) -> bool:
    if not texto:
        return False
    t = texto.lower()
    keywords = [
        'agend', 'marcar', 'consulta', 'horario', 'horário',
        'ola', 'olá', 'oi', 'bom dia', 'boa tarde', 'boa noite', 'preciso', 'quero'
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
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        logger.warning(f"Mensagem duplicada ignorada: {dados.api_message_id}")
        return False
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro ao salvar mensagem: {e}")
        return False


# =========================================================
# AGENDAMENTO COM LOCK (CRÍTICO)
# =========================================================
def agendar(conn, telefone, id_disponibilidade):
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_disponibilidade
                FROM disponibilidade
                WHERE id_disponibilidade = %s
                FOR UPDATE
            """, (id_disponibilidade,))

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
def processar_fluxo(conn, telefone, mensagem, etapa_atual, contexto, config):
    if etapa_atual == "inicio_agendamento":
        return config.get('msg_saudacao', "Olá! Seja bem-vindo(a) ao atendimento virtual da nossa clínica! 🏥\n\nPara seguirmos com o seu agendamento, precisamos de alguns dados. Você concorda com os termos de tratamento dos seus dados (LGPD)?"), "validar_lgpd", ["Concordo", "Não Concordo"]

    if etapa_atual == "validar_lgpd":
        resp = str(mensagem).strip().lower()
        if resp in ["1", "concordo"]:
            return config.get('msg_solicitar_cpf', "Excelente! 👍\nPor favor, digite apenas os números do seu *CPF* ou *carteirinha* do convênio:"), "pedir_cpf"
        elif resp in ["2", "não concordo", "nao concordo"]:
            return config.get('msg_despedida_lgpd', "Compreendemos a sua escolha. Como precisamos dos dados para o agendamento, o atendimento foi encerrado.\n\nSempre que precisar, estaremos à disposição! 👋"), "fim"
        else:
            return "Por favor, responda com Concordo ou Não Concordo.", "validar_lgpd"

    if etapa_atual == "pedir_cpf":
        texto = (mensagem or '').strip()
        digits = re.sub(r"\D", "", texto)
        if len(digits) < 11:
            return "Por favor, envie seu CPF (somente números, 11 dígitos) ou número da carteirinha.", "pedir_cpf"

        with conn.cursor() as cur:
            cur.execute("""
                SELECT id_paciente FROM paciente WHERE regexp_replace(coalesce(cpf, ''), '\\D', '', 'g') = %s LIMIT 1
            """, (digits,))
            p = cur.fetchone()

        if not p:
            contexto["cpf_temp"] = digits
            return config.get('msg_solicitar_nome', "Vi que é seu primeiro acesso por aqui! 🎉\nPara completarmos o seu cadastro, digite o seu *Nome Completo*, por favor:"), "pedir_nome"

        id_paciente = p[0]
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sessao_chatbot SET id_paciente = %s
                WHERE telefone = %s
            """, (id_paciente, telefone))
            conn.commit()

        resultado_inicio = processar_fluxo(conn, telefone, mensagem, "inicio", contexto, config)
        resposta_inicio = resultado_inicio[0]
        botoes_inicio = resultado_inicio[2] if len(resultado_inicio) == 3 else []
        
        with conn.cursor() as cur:
            cur.execute("SELECT nome FROM paciente WHERE id_paciente = %s", (id_paciente,))
            nome_paciente = cur.fetchone()[0].split()[0]
            
        return f"É muito bom ter você de volta, {nome_paciente}! ✨\n\n" + resposta_inicio, "inicio", botoes_inicio

    if etapa_atual == "pedir_nome":
        nome = (mensagem or '').strip()
        if len(nome.split()) < 2:
            return "Por favor, digite seu *nome e sobrenome* para o cadastro:", "pedir_nome"
            
        cpf = contexto.get("cpf_temp", "")
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO paciente (nome, cpf, telefone, aceite_lgpd, data_aceite_lgpd)
                VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                RETURNING id_paciente
            """, (nome, cpf, telefone))
            id_paciente = cur.fetchone()[0]
            
            cur.execute("""
                UPDATE sessao_chatbot SET id_paciente = %s
                WHERE telefone = %s
            """, (id_paciente, telefone))
            conn.commit()
            
        resultado_inicio = processar_fluxo(conn, telefone, mensagem, "inicio", contexto, config)
        resposta_inicio = resultado_inicio[0]
        botoes_inicio = resultado_inicio[2] if len(resultado_inicio) == 3 else []
        return f"Cadastro concluído com sucesso, {nome.split()[0]}! " + resposta_inicio, "inicio", botoes_inicio

    if etapa_atual == "inicio":
        return (
            "Como podemos ajudar você hoje? Escolha uma das opções:"
        ), "menu", ["Agendar consulta", "Falar com recepção"]

    if etapa_atual == "menu":
        resp = str(mensagem).strip().lower()
        if resp in ["1", "agendar consulta", "agendar"]:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT especialidade FROM medico WHERE especialidade IS NOT NULL LIMIT 3")
                especialidades = [r[0] for r in cur.fetchall()]
                
            if especialidades:
                return "Para qual especialidade você deseja agendar?", "escolher_especialidade", especialidades
            return "Perfeito! Por favor, digite o ID do horário desejado:", "agendar"
        elif resp in ["2", "falar com recepção", "recepção", "falar com a recepção"]:
            return "Certo, aguarde só um instante. Já vou chamar uma de nossas atendentes para falar com você! 👩‍⚕️", "fim"
        else:
            return "Ops, não entendi essa opção. Por favor, escolha 'Agendar consulta' ou 'Falar com recepção'.", "menu"

    if etapa_atual == "escolher_especialidade":
        especialidade = (mensagem or '').strip()
        return f"Ótima escolha ({especialidade}). Por favor, digite o ID do horário desejado:", "agendar"

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
MSG_FORA_HORARIO = (
    "🕐 Olá! Nosso atendimento automático funciona de {inicio} às {fim}.\n\n"
    "Sua mensagem foi registrada e nossa equipe entrará em contato "
    "assim que possível no próximo horário de atendimento.\n\n"
    "Obrigado pela compreensão! 🏥"
)

MSG_BOT_DESATIVADO = (
    "Olá! Nosso atendimento automático está temporariamente desativado.\n\n"
    "Sua mensagem foi registrada e nossa equipe entrará em contato em breve.\n\n"
    "Obrigado pela compreensão! 🏥"
)

def enviar_mensagem_whatsapp(telefone: str, texto: str, botoes: list = None):
    api_url = os.getenv("EVOLUTION_API_URL", "http://evolution-api:8080")
    api_key = os.getenv("EVOLUTION_API_KEY", "apikey_secreta_evolution")
    instance = "bot"
    
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }
    
    if botoes:
        texto += "\n\n" + "\n".join(f"*{i+1}* - {btn}" for i, btn in enumerate(botoes))
        
    payload = {
        "number": telefone,
        "text": texto
    }
    
    try:
        url = f"{api_url}/message/sendText/{instance}"
        logger.info(f"Enviando mensagem para {telefone} via Evolution API...")
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code not in (200, 201):
            logger.error(f"Erro ao enviar mensagem via Evolution API: {res.status_code} - {res.text}")
        else:
            logger.info(f"Mensagem enviada com sucesso para {telefone}")
    except Exception as e:
        logger.error(f"Exceção ao enviar mensagem via Evolution API: {e}")

@app.post("/webhook")
@app.post("/webhook/{path:path}")
def webhook(payload: dict = Body(...)):
    # Detect if it is an Evolution API payload
    is_evolution = "event" in payload and "instance" in payload
    
    if is_evolution:
        event = payload.get("event")
        if event != "messages.upsert":
            logger.info(f"Ignorando evento da Evolution API: {event}")
            return {"status": "event_ignored", "event": event}
            
        data = payload.get("data", {})
        key = data.get("key", {})
        from_me = key.get("fromMe", False)
        
        # Ignora se for do próprio bot
        if from_me:
            return {"status": "ignored_outbound"}
            
        remote_jid = key.get("remoteJid", "")
        
        # Ignora mensagens de grupos ou de status
        if "@g.us" in remote_jid or "status@broadcast" in remote_jid:
            return {"status": "ignored_group_or_status"}
            
        telefone = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
        telefone = re.sub(r"\D", "", telefone)
        
        message_data = data.get("message", {})
        if not message_data:
            return {"status": "empty_message"}
            
        mensagem = (
            message_data.get("conversation") or 
            message_data.get("extendedTextMessage", {}).get("text") or 
            message_data.get("imageMessage", {}).get("caption") or 
            message_data.get("videoMessage", {}).get("caption") or 
            ""
        )
        api_message_id = key.get("id", f"evo-{uuid.uuid4().hex}")
        direcao = 'SAIDA' if from_me else 'ENTRADA'
        
        msg = Mensagem(
            telefone=telefone,
            mensagem=mensagem,
            api_message_id=api_message_id,
            direcao=direcao
        )
    else:
        try:
            msg = Mensagem(**payload)
        except Exception as e:
            logger.error(f"Erro ao parsear payload do webhook: {e}")
            raise HTTPException(status_code=422, detail=str(e))

    conn = db_pool.getconn()
    try:
        # Salva a mensagem recebida
        if not salvar_mensagem(conn, msg):
            return {"status": "already_processed_or_error"}

        # Filtro de segurança: ignorar mensagens de saída
        if msg.direcao and msg.direcao.upper() in ('SAIDA', 'OUTBOUND', 'OUTGOING', 'SENT'):
            logger.info(f"Ignorando mensagem de saída: {msg.api_message_id} ({msg.direcao})")
            return {"status": "ignored_outbound"}

        # Kill-switch de segurança
        if os.getenv('ALLOW_SEND', 'false').lower() != 'true':
            logger.warning("Envio de mensagens está desabilitado por kill-switch (ALLOW_SEND!=true)")
            return {"status": "sending_disabled"}

        # =============================================
        # VERIFICAÇÃO DE HORÁRIO DE FUNCIONAMENTO
        # =============================================
        operacional, config = bot_esta_operacional(conn)
        if not operacional:
            if not config.get("bot_ativo", True):
                resposta_fora = MSG_BOT_DESATIVADO
            else:
                inicio_str = str(config.get("bot_inicio_funcionamento", "08:00"))[:5]
                fim_str = str(config.get("bot_fim_funcionamento", "18:00"))[:5]
                msg_fora = config.get("msg_fora_horario")
                if msg_fora:
                    resposta_fora = msg_fora.replace("{inicio}", inicio_str).replace("{fim}", fim_str)
                else:
                    resposta_fora = MSG_FORA_HORARIO.format(inicio=inicio_str, fim=fim_str)

            logger.info(f"Mensagem recebida fora do horário de {msg.telefone}. Registrada para acompanhamento.")
            
            # Envia a resposta fora do horário
            enviar_mensagem_whatsapp(msg.telefone, resposta_fora)
            
            return {"resposta": resposta_fora, "botoes": [], "status": "fora_horario"}

        # =============================================
        # FLUXO NORMAL DO BOT
        # =============================================
        sessao_id, etapa_atual, contexto = get_or_create_session(conn, msg.telefone)

        if not sessao_id:
            if is_scheduling_intent(msg.mensagem):
                sessao_id, etapa_atual, contexto = create_session_for_intent(conn, msg.telefone)
                logger.info(f"Criada sessão por intenção de agendamento para {msg.telefone}: {sessao_id}")
            else:
                logger.info(f"Nenhuma sessão ativa e nenhum cadastro para {msg.telefone}; ignorando.")
                return {"status": "no_session_or_patient"}

        result = processar_fluxo(
            conn, msg.telefone, msg.mensagem, etapa_atual, contexto, config
        )
        if len(result) == 3:
            resposta, nova_etapa, botoes = result
        else:
            resposta, nova_etapa = result
            botoes = []

        # Registra tentativa de envio no log de mensagens (saída)
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

        except Exception as e:
            conn.rollback()
            logger.error(f"Falha ao registrar mensagem de saída/auditoria: {e}")

        # Atualiza a etapa
        contexto["etapa"] = nova_etapa
        with conn.cursor() as cur:
            novo_contexto = json.dumps(contexto)
            cur.execute("""
                UPDATE sessao_chatbot
                SET contexto_json = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id_sessao = %s
            """, (novo_contexto, sessao_id))
            conn.commit()

        # Envia a resposta via Evolution API
        enviar_mensagem_whatsapp(msg.telefone, resposta, botoes)

        return {"resposta": resposta, "botoes": botoes}

    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: LOGIN ADMIN
# =========================================================
@app.post("/api/admin/login")
def admin_login(req: LoginRequest):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id_usuario, nome, login, senha_hash, perfil
                FROM usuario
                WHERE login = %s AND ativo = TRUE
                LIMIT 1
            """, (req.login,))
            user = cur.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Credenciais inválidas")

        # Verificação de senha usando SHA-256 simples
        # Em produção, usar bcrypt (passlib)
        senha_hash = hashlib.sha256(req.senha.encode()).hexdigest()
        if not hmac.compare_digest(user["senha_hash"], senha_hash):
            raise HTTPException(status_code=401, detail="Credenciais inválidas")

        token = criar_token_jwt({
            "sub": user["id_usuario"],
            "nome": user["nome"],
            "perfil": user["perfil"]
        })

        return {
            "token": token,
            "usuario": {
                "id": user["id_usuario"],
                "nome": user["nome"],
                "perfil": user["perfil"]
            }
        }
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: OBTER CONFIGURAÇÕES
# =========================================================
@app.get("/api/admin/config")
def get_config(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM configuracao_sistema ORDER BY id_config LIMIT 1")
            config = cur.fetchone()
        if not config:
            raise HTTPException(status_code=404, detail="Configuração não encontrada")

        # Converte objetos time para strings serializáveis
        result = dict(config)
        for key in ["bot_inicio_funcionamento", "bot_fim_funcionamento"]:
            if result.get(key) and hasattr(result[key], "isoformat"):
                result[key] = result[key].isoformat()[:5]
        if result.get("updated_at"):
            result["updated_at"] = result["updated_at"].isoformat()

        return result
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: ATUALIZAR CONFIGURAÇÕES
# =========================================================
@app.put("/api/admin/config")
def update_config(req: ConfigUpdate, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        updates = []
        params = []

        if req.bot_ativo is not None:
            updates.append("bot_ativo = %s")
            params.append(req.bot_ativo)
        if req.bot_inicio_funcionamento is not None:
            updates.append("bot_inicio_funcionamento = %s")
            params.append(req.bot_inicio_funcionamento)
        if req.bot_fim_funcionamento is not None:
            updates.append("bot_fim_funcionamento = %s")
            params.append(req.bot_fim_funcionamento)
        if req.tempo_padrao_consulta_minutos is not None:
            updates.append("tempo_padrao_consulta_minutos = %s")
            params.append(req.tempo_padrao_consulta_minutos)
        
        if req.msg_saudacao is not None:
            updates.append("msg_saudacao = %s")
            params.append(req.msg_saudacao)
        if req.msg_solicitar_cpf is not None:
            updates.append("msg_solicitar_cpf = %s")
            params.append(req.msg_solicitar_cpf)
        if req.msg_despedida_lgpd is not None:
            updates.append("msg_despedida_lgpd = %s")
            params.append(req.msg_despedida_lgpd)
        if req.msg_solicitar_nome is not None:
            updates.append("msg_solicitar_nome = %s")
            params.append(req.msg_solicitar_nome)
        if req.msg_fora_horario is not None:
            updates.append("msg_fora_horario = %s")
            params.append(req.msg_fora_horario)
        if req.msg_lembrete_24h is not None:
            updates.append("msg_lembrete_24h = %s")
            params.append(req.msg_lembrete_24h)
        if req.msg_lembrete_dia is not None:
            updates.append("msg_lembrete_dia = %s")
            params.append(req.msg_lembrete_dia)

        if not updates:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = f"UPDATE configuracao_sistema SET {', '.join(updates)} WHERE id_config = 1"

        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()

        # Auditoria
        with conn.cursor() as acur:
            acur.execute("""
                INSERT INTO auditoria (id_registro, tabela, acao, id_usuario, dados_novos)
                VALUES (%s, %s, %s, %s, %s::jsonb)
            """, (1, 'configuracao_sistema', 'UPDATE_CONFIG', user.get("sub"),
                  json.dumps(req.dict(exclude_none=True))))
            conn.commit()

        return {"status": "ok", "mensagem": "Configurações atualizadas com sucesso"}
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: LISTAR MÉDICOS
# =========================================================
@app.get("/api/admin/medicos")
def listar_medicos(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id_medico, nome, especialidade, crm, uf_crm,
                       telefone, email, tempo_padrao_minutos, ativo,
                       foto_base64
                FROM medico
                ORDER BY nome
            """)
            medicos = cur.fetchall()
        return {"medicos": medicos}
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: CADASTRAR MÉDICO
# =========================================================
@app.post("/api/admin/medicos")
def cadastrar_medico(req: NovoMedico, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO medico (nome, especialidade, crm, uf_crm, telefone, email, tempo_padrao_minutos)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id_medico
            """, (req.nome, req.especialidade, req.crm, req.uf_crm,
                  req.telefone, req.email, req.tempo_padrao_minutos))
            id_medico = cur.fetchone()[0]
            conn.commit()
        return {"status": "ok", "id_medico": id_medico}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Médico com este CRM já cadastrado")
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: UPLOAD DE FOTO DO MÉDICO
# =========================================================
class FotoMedico(BaseModel):
    foto_base64: str  # "data:image/jpeg;base64,..."

@app.put("/api/admin/medicos/{id_medico}/foto")
def upload_foto_medico(id_medico: int, req: FotoMedico, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        # Valida tamanho (~500KB max em base64 ≈ 360KB de imagem)
        if len(req.foto_base64) > 700_000:
            raise HTTPException(status_code=413, detail="Imagem muito grande. Máximo: 500KB")
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE medico SET foto_base64 = %s WHERE id_medico = %s
            """, (req.foto_base64, id_medico))
            conn.commit()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: STATS — AGENDAMENTOS POR DIA (últimos 7 + próx 7)
# =========================================================
@app.get("/api/admin/stats/agenda-semana")
def stats_agenda_semana(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    DATE(d.inicio_datetime) AS dia,
                    COUNT(c.id_consulta)    AS total
                FROM disponibilidade d
                LEFT JOIN consulta c
                    ON c.id_disponibilidade = d.id_disponibilidade
                    AND c.status NOT IN ('CANCELADA','CANCELADA_CLINICA','FALTOU')
                WHERE d.inicio_datetime BETWEEN CURRENT_DATE - INTERVAL '7 days'
                                            AND CURRENT_DATE + INTERVAL '14 days'
                GROUP BY DATE(d.inicio_datetime)
                ORDER BY dia
            """)
            rows = cur.fetchall()
        result = [{"dia": str(r["dia"]), "total": r["total"]} for r in rows]
        return {"dados": result}
    finally:
        db_pool.putconn(conn)



# =========================================================
# ENDPOINT: LIBERAR AGENDA (criar disponibilidades)
# =========================================================
@app.post("/api/admin/agenda/liberar")
def liberar_agenda(req: LiberarAgenda, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        criados = 0
        erros = []
        for i, slot in enumerate(req.slots):
            inicio = slot.get("inicio")
            fim = slot.get("fim")
            if not inicio or not fim:
                erros.append(f"Slot {i+1}: campos 'inicio' e 'fim' obrigatórios")
                continue
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO disponibilidade (id_medico, inicio_datetime, fim_datetime, status, origem)
                        VALUES (%s, %s, %s, 'LIVRE', 'PAINEL_ADMIN')
                        RETURNING id_disponibilidade
                    """, (req.id_medico, inicio, fim))
                    conn.commit()
                    criados += 1
            except psycopg2.IntegrityError as e:
                conn.rollback()
                erros.append(f"Slot {i+1}: conflito de horário — {str(e).split('DETAIL:')[0].strip()}")
            except Exception as e:
                conn.rollback()
                erros.append(f"Slot {i+1}: {str(e)}")

        # Auditoria
        with conn.cursor() as acur:
            acur.execute("""
                INSERT INTO auditoria (id_registro, tabela, acao, id_usuario, dados_novos)
                VALUES (%s, %s, %s, %s, %s::jsonb)
            """, (req.id_medico, 'disponibilidade', 'LIBERAR_AGENDA', user.get("sub"),
                  json.dumps({"slots_criados": criados, "erros": erros})))
            conn.commit()

        return {"status": "ok", "criados": criados, "erros": erros}
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: LISTAR AGENDA (disponibilidades futuras)
# =========================================================
@app.get("/api/admin/agenda")
def listar_agenda(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id_disponibilidade, d.id_medico, m.nome AS medico_nome,
                       m.especialidade, d.inicio_datetime, d.fim_datetime,
                       d.status, d.origem,
                       c.id_consulta, c.status AS status_consulta,
                       p.id_paciente, p.nome AS paciente_nome, p.telefone AS paciente_telefone, p.cpf AS paciente_cpf
                FROM disponibilidade d
                JOIN medico m ON m.id_medico = d.id_medico
                LEFT JOIN consulta c ON c.id_disponibilidade = d.id_disponibilidade
                    AND c.status NOT IN ('CANCELADA', 'FALTOU')
                LEFT JOIN paciente p ON p.id_paciente = c.id_paciente
                WHERE d.inicio_datetime >= CURRENT_DATE
                ORDER BY d.inicio_datetime
            """)
            agenda = cur.fetchall()

        # Serializa datas
        for item in agenda:
            for key in ["inicio_datetime", "fim_datetime"]:
                if item.get(key):
                    item[key] = item[key].isoformat()

        return {"agenda": agenda}
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: MENSAGENS FORA DE HORÁRIO (fila humana)
# =========================================================
@app.get("/api/admin/mensagens-pendentes")
def mensagens_pendentes(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT wm.id_log, wm.telefone_remetente, wm.mensagem,
                       wm.created_at, p.nome AS paciente_nome
                FROM whatsapp_mensagem wm
                LEFT JOIN paciente p ON p.telefone = wm.telefone_remetente
                WHERE wm.direcao = 'ENTRADA'
                AND wm.created_at >= CURRENT_DATE
                ORDER BY wm.created_at DESC
                LIMIT 100
            """)
            mensagens = cur.fetchall()

        for m in mensagens:
            if m.get("created_at"):
                m["created_at"] = m["created_at"].isoformat()

        return {"mensagens": mensagens}
    finally:
        try:
            conn.rollback()
        except:
            pass
        try:
            conn.rollback()
        except:
            pass
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: LISTAR CONSULTAS (com filtro de data)
# =========================================================
@app.get("/api/admin/consultas")
def get_consultas(data_inicio: Optional[str] = None, data_fim: Optional[str] = None, req_user=Depends(verificar_token_jwt)):
    conn = db_pool.getconn()
    try:
        # Define janela de datas
        if data_inicio:
            dt_inicio = datetime.fromisoformat(data_inicio)
        else:
            dt_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if data_fim:
            dt_fim = datetime.fromisoformat(data_fim).replace(hour=23, minute=59, second=59)
        else:
            dt_fim = dt_inicio.replace(hour=23, minute=59, second=59) + __import__('datetime').timedelta(days=90)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    c.id_consulta,
                    c.status,
                    p.id_paciente,
                    p.nome  AS paciente_nome,
                    p.telefone AS paciente_telefone,
                    p.cpf   AS paciente_cpf,
                    d.inicio_datetime AS inicio,
                    d.fim_datetime    AS fim,
                    m.nome  AS medico_nome,
                    m.especialidade
                FROM consulta c
                JOIN paciente p      ON c.id_paciente       = p.id_paciente
                JOIN disponibilidade d ON c.id_disponibilidade = d.id_disponibilidade
                JOIN medico m         ON d.id_medico          = m.id_medico
                WHERE c.status NOT IN ('CANCELADA','CANCELADA_CLINICA','FALTOU')
                  AND d.inicio_datetime BETWEEN %s AND %s
                ORDER BY d.inicio_datetime ASC
            """, (dt_inicio, dt_fim))
            consultas = cur.fetchall()

        for c in consultas:
            if c["inicio"]: c["inicio"] = c["inicio"].isoformat()
            if c["fim"]:    c["fim"]    = c["fim"].isoformat()

        return {"consultas": consultas}
    except Exception as e:
        logger.error(f"Erro ao buscar consultas: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: AGENDAMENTO MANUAL PELO PAINEL
# =========================================================
class AgendamentoManual(BaseModel):
    id_disponibilidade: int
    cpf: Optional[str] = None
    telefone: Optional[str] = None
    nome_paciente: Optional[str] = None

@app.post("/api/admin/consultas/manual")
def agendar_manual(req: AgendamentoManual, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        # 1. Verificar disponibilidade
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id_disponibilidade, d.status, d.inicio_datetime
                FROM disponibilidade d
                WHERE d.id_disponibilidade = %s
                FOR UPDATE
            """, (req.id_disponibilidade,))
            slot = cur.fetchone()

        if not slot:
            raise HTTPException(status_code=404, detail="Horário não encontrado")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM consulta
                WHERE id_disponibilidade = %s AND status NOT IN ('CANCELADA','CANCELADA_CLINICA','FALTOU')
            """, (req.id_disponibilidade,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Horário já ocupado")

        # 2. Localizar ou criar paciente
        id_paciente = None
        if req.cpf:
            digits = re.sub(r"\D", "", req.cpf)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id_paciente FROM paciente
                    WHERE regexp_replace(coalesce(cpf,''),'\\D','','g') = %s LIMIT 1
                """, (digits,))
                res = cur.fetchone()
                if res:
                    id_paciente = res[0]

        if not id_paciente and req.telefone:
            telefone = re.sub(r"\D", "", req.telefone)
            with conn.cursor() as cur:
                cur.execute("SELECT id_paciente FROM paciente WHERE telefone = %s LIMIT 1", (telefone,))
                res = cur.fetchone()
                if res:
                    id_paciente = res[0]

        if not id_paciente:
            # Cria paciente novo
            if not req.nome_paciente:
                raise HTTPException(status_code=422, detail="Paciente não encontrado. Informe o nome para cadastrar.")
            cpf_val   = re.sub(r"\D", "", req.cpf or "")
            tel_val   = re.sub(r"\D", "", req.telefone or "")
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO paciente (nome, cpf, telefone, aceite_lgpd, data_aceite_lgpd)
                    VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    RETURNING id_paciente
                """, (req.nome_paciente, cpf_val or None, tel_val or None))
                id_paciente = cur.fetchone()[0]
                conn.commit()

        # 3. Criar consulta
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO consulta (id_paciente, id_disponibilidade, status)
                VALUES (%s, %s, 'CONFIRMADA')
                RETURNING id_consulta
            """, (id_paciente, req.id_disponibilidade))
            id_consulta = cur.fetchone()[0]
            conn.commit()

        logger.info(f"Agendamento manual: consulta {id_consulta} criada pelo admin {user.get('sub')}")
        return {"sucesso": True, "id_consulta": id_consulta}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro no agendamento manual: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: CANCELAR CONSULTA
# =========================================================
@app.put("/api/admin/consultas/{id_consulta}/cancelar")
def cancelar_consulta_admin(id_consulta: int, req_user=Depends(verificar_token_jwt)):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id_disponibilidade FROM consulta WHERE id_consulta = %s", (id_consulta,))
            res = cur.fetchone()
            if not res:
                raise HTTPException(status_code=404, detail="Consulta não encontrada")
                
            id_disp = res[0]
            
            cur.execute("UPDATE consulta SET status = 'CANCELADA_CLINICA' WHERE id_consulta = %s", (id_consulta,))
            cur.execute("UPDATE disponibilidade SET status = 'LIVRE' WHERE id_disponibilidade = %s", (id_disp,))
            conn.commit()
            
        return {"sucesso": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINT: HISTÓRICO DO PACIENTE
# =========================================================
@app.get("/api/admin/pacientes/{id_paciente}/historico")
def get_historico_paciente(id_paciente: int, req_user=Depends(verificar_token_jwt)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    c.id_consulta, c.status,
                    d.data_hora_inicio as inicio,
                    m.nome as medico_nome
                FROM consulta c
                JOIN disponibilidade d ON c.id_disponibilidade = d.id_disponibilidade
                JOIN medico m ON d.id_medico = m.id_medico
                WHERE c.id_paciente = %s
                ORDER BY d.data_hora_inicio DESC
            """, (id_paciente,))
            hist = cur.fetchall()
            for h in hist:
                if h["inicio"]: h["inicio"] = h["inicio"].isoformat()
        return {"historico": hist}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)

# =========================================================
# ENDPOINTS: EVOLUTION API (WHATSAPP CONNECTION)
# =========================================================
@app.get("/api/admin/whatsapp/status")
def whatsapp_status():
    try:
        headers = {"apikey": EVOLUTION_API_KEY}
        r = requests.get(f"{EVOLUTION_API_URL}/instance/fetchInstances", headers=headers, timeout=5)
        if r.status_code != 200:
            return {"status": "erro", "message": "Falha na API Evolution"}
        instances = r.json()
        if not instances:
            payload = {"instanceName": "clinica", "qrcode": True, "integration": "WHATSAPP-BAILEYS"}
            requests.post(f"{EVOLUTION_API_URL}/instance/create", json=payload, headers=headers)
            return {"status": "desconectado", "instance": "clinica"}
            
        inst = instances[0]
        instance_name = inst.get("instance/instanceName", inst.get("instanceName", "clinica"))
        state = inst.get("connectionStatus", "DISCONNECTED")
        if state == "open" or state == "ONLINE":
            return {"status": "conectado", "instance": instance_name}
        return {"status": "desconectado", "instance": instance_name}
    except Exception as e:
        return {"status": "erro", "message": str(e)}

@app.get("/api/admin/whatsapp/qrcode")
def whatsapp_qrcode(instance: str = "clinica"):
    try:
        headers = {"apikey": EVOLUTION_API_KEY}
        r = requests.get(f"{EVOLUTION_API_URL}/instance/connect/{instance}", headers=headers, timeout=5)
        if r.status_code == 200:
            return r.json()
        return {"error": "Falha ao gerar QR Code"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/admin/whatsapp/logout")
def whatsapp_logout(instance: str = "clinica"):
    try:
        headers = {"apikey": EVOLUTION_API_KEY}
        r = requests.delete(f"{EVOLUTION_API_URL}/instance/logout/{instance}", headers=headers, timeout=5)
        return {"sucesso": r.status_code == 200}
    except Exception as e:
        return {"sucesso": False, "error": str(e)}
