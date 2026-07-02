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
import bcrypt
from typing import Optional, List
from datetime import datetime, time as dt_time, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Configuração de Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://evolution-api:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")

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
# CORS
# SEGURANÇA: allow_credentials=False — JWT vai em header Authorization,
# não em cookie. Manter allow_origins=["*"] durante fase de testes.
# Em produção, restringir para o domínio real.
# =========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# CONFIGURAÇÃO JWT
# SEGURANÇA: JWT_SECRET obrigatório — sem fallback fraco.
# Se não definido, o app falha no startup (fail-fast).
# =========================================================
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "❌ JWT_SECRET não definido! Configure a variável de ambiente antes de iniciar. "
        "Exemplo: export JWT_SECRET=$(openssl rand -hex 32)"
    )
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

class NovoUsuario(BaseModel):
    nome: str
    login: str
    senha: str
    perfil: str = 'recepcao'

class AlterarSenha(BaseModel):
    id_usuario: int
    nova_senha: str

class FotoMedico(BaseModel):
    foto_base64: str

class ResolveAtendimento(BaseModel):
    telefone: str

class AgendamentoManual(BaseModel):
    id_disponibilidade: int
    cpf: Optional[str] = None
    telefone: Optional[str] = None
    nome_paciente: Optional[str] = None


# =========================================================
# UTIL: VALIDAR FORÇA DE SENHA
# Política: mínimo 6 caracteres e pelo menos 1 número.
# =========================================================
def validar_forca_senha(senha: str):
    if len(senha) < 6:
        raise HTTPException(
            status_code=400,
            detail="Senha deve ter pelo menos 6 caracteres."
        )
    if not any(c.isdigit() for c in senha):
        raise HTTPException(
            status_code=400,
            detail="Senha deve conter pelo menos um número."
        )


# =========================================================
# UTIL: VERIFICAR / GERAR HASH DE SENHA (bcrypt)
# Suporte a migração lazy: hashes SHA-256 legados são aceitos
# e migrados para bcrypt automaticamente no login.
# =========================================================
def _verificar_e_migrar_senha(senha_digitada: str, hash_armazenado: str, id_usuario: int, conn) -> bool:
    """
    Verifica a senha. Se o hash for SHA-256 legado (64 hex chars),
    verifica e migra para bcrypt silenciosamente.
    """
    # Detecta formato: bcrypt começa com $2b$ ou $2a$
    if hash_armazenado.startswith("$2"):
        # Hash bcrypt — verificação direta
        return bcrypt.checkpw(senha_digitada.encode(), hash_armazenado.encode())
    else:
        # Hash SHA-256 legado — verificação e migração
        sha_hash = hashlib.sha256(senha_digitada.encode()).hexdigest()
        if not hmac.compare_digest(hash_armazenado, sha_hash):
            return False
        # Migra para bcrypt
        novo_hash = bcrypt.hashpw(senha_digitada.encode(), bcrypt.gensalt()).decode()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE usuario SET senha_hash = %s WHERE id_usuario = %s",
                    (novo_hash, id_usuario)
                )
                conn.commit()
            logger.info(f"Senha do usuário id={id_usuario} migrada de SHA-256 para bcrypt.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Falha ao migrar hash de senha: {e}")
        return True


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

    from zoneinfo import ZoneInfo
    sp_tz = ZoneInfo("America/Sao_Paulo")
    agora = datetime.now(sp_tz).time()
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
            
            # Timeout: se inativo por 15+ min, reseta para 'inicio'
            updated_at = sessao[2]
            if updated_at:
                now_utc = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
                diff = now_utc - updated_at
                if diff.total_seconds() > 900:  # 15 minutos
                    if etapa in ["menu", "escolher_especialidade", "agendar", "fim", "inicio"]:
                        etapa = "inicio"
                        contexto["etapa"] = "inicio"
            
            return id_sessao, etapa, contexto

        # Só cria sessão se o telefone estiver cadastrado como paciente
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
            return config.get('msg_solicitar_cpf', "Excelente! 🙌\nPor favor, digite apenas os números do seu *CPF* ou *carteirinha* do convênio:"), "pedir_cpf"
        elif resp in ["2", "não concordo", "nao concordo"]:
            return config.get('msg_despedida_lgpd', "Compreendemos a sua escolha. Como precisamos dos dados para o agendamento, o atendimento foi encerrado.\n\nSempre que precisar, estaremos à disposição! 🙏"), "fim"
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
            return config.get('msg_solicitar_nome', "Vi que é seu primeiro acesso por aqui! 🙏\nPara completarmos o seu cadastro, digite o seu *Nome Completo*, por favor:"), "pedir_nome"

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
            return "Certo, aguarde só um instante. Já vou chamar uma de nossas atendentes para falar com você! 🙋‍♀️", "em_atendimento_humano"
        else:
            return "Ops, não entendi essa opção. Por favor, escolha 'Agendar consulta' ou 'Falar com recepção'.", "menu"

    if etapa_atual == "em_atendimento_humano":
        return "Você já está na fila de atendimento! ⏳\n\nPor favor, aguarde mais um instante, um de nossos assistentes humanos já vai falar com você.", "em_atendimento_humano"


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

    return "Seu atendimento foi finalizado. Qualquer coisa é só chamar! 🙏", "fim"


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
    api_key = os.getenv("EVOLUTION_API_KEY")
    if not api_key:
        logger.error("EVOLUTION_API_KEY não definida — mensagem não enviada.")
        return
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

        # Filtro de segurança: ignora mensagens de saída
        if msg.direcao and msg.direcao.upper() in ('SAIDA', 'OUTBOUND', 'OUTGOING', 'SENT'):
            logger.info(f"Ignorando mensagem de saída: {msg.api_message_id} ({msg.direcao})")
            return {"status": "ignored_outbound"}

        # Kill-switch de segurança
        if os.getenv('ALLOW_SEND', 'false').lower() != 'true':
            logger.warning("Envio de mensagens está desabilitado por kill-switch (ALLOW_SEND!=true)")
            return {"status": "sending_disabled"}

        # =========================================================
        # VERIFICAÇÃO DE HORÁRIO DE FUNCIONAMENTO
        # =========================================================
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

        # =========================================================
        # FLUXO NORMAL DO BOT
        # =========================================================
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

        # Verificação com suporte a migração lazy SHA-256 → bcrypt
        if not _verificar_e_migrar_senha(req.senha, user["senha_hash"], user["id_usuario"], conn):
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
        db_pool.putconn(conn)


# =========================================================
# ENDPOINTS: CONFIGURAÇÃO
# =========================================================
@app.get("/api/admin/config")
def obter_config(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM configuracao_sistema ORDER BY id_config LIMIT 1")
            config = cur.fetchone()
        if not config:
            return {}
        config_dict = dict(config)
        for key in ['bot_inicio_funcionamento', 'bot_fim_funcionamento']:
            if config_dict.get(key) is not None:
                config_dict[key] = str(config_dict[key])[:5]
        return config_dict
    finally:
        db_pool.putconn(conn)

@app.put("/api/admin/config")
def atualizar_config(req: ConfigUpdate, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        campos = {k: v for k, v in req.model_dump().items() if v is not None}
        if not campos:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id_config FROM configuracao_sistema LIMIT 1")
            config_existente = cur.fetchone()

            if config_existente:
                set_clause = ", ".join(f"{k} = %s" for k in campos)
                cur.execute(
                    f"UPDATE configuracao_sistema SET {set_clause} WHERE id_config = %s",
                    list(campos.values()) + [config_existente["id_config"]]
                )
            else:
                cols = ", ".join(campos.keys())
                placeholders = ", ".join(["%s"] * len(campos))
                cur.execute(
                    f"INSERT INTO configuracao_sistema ({cols}) VALUES ({placeholders})",
                    list(campos.values())
                )
        conn.commit()
        return {"status": "success", "updated": list(campos.keys())}
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINTS: MÉDICOS
# =========================================================
@app.get("/api/admin/medicos")
def listar_medicos(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM medico WHERE deleted_at IS NULL ORDER BY nome")
            medicos = cur.fetchall()
        return {"medicos": [dict(m) for m in medicos]}
    finally:
        db_pool.putconn(conn)

@app.post("/api/admin/medicos")
def cadastrar_medico(req: NovoMedico, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO medico (nome, especialidade, crm, uf_crm, telefone, email, tempo_padrao_minutos)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id_medico
            """, (req.nome, req.especialidade, req.crm, req.uf_crm, req.telefone, req.email, req.tempo_padrao_minutos))
            id_medico = cur.fetchone()["id_medico"]
        conn.commit()
        return {"status": "success", "id_medico": id_medico}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="CRM já cadastrado")
    finally:
        db_pool.putconn(conn)

@app.put("/api/admin/medicos/{id_medico}/foto")
def upload_foto_medico(id_medico: int, req: FotoMedico, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
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
# ENDPOINTS: AGENDA
# =========================================================
@app.get("/api/admin/agenda")
def listar_agenda(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT d.id_disponibilidade, d.inicio_datetime, d.fim_datetime,
                       d.status, m.nome AS medico_nome, m.especialidade,
                       c.id_consulta, c.status AS consulta_status,
                       p.nome AS paciente_nome, p.telefone AS paciente_telefone
                FROM disponibilidade d
                JOIN medico m ON m.id_medico = d.id_medico
                LEFT JOIN consulta c ON c.id_disponibilidade = d.id_disponibilidade
                    AND c.status NOT IN ('CANCELADA','FALTOU')
                LEFT JOIN paciente p ON p.id_paciente = c.id_paciente
                WHERE d.inicio_datetime >= NOW() - INTERVAL '1 day'
                ORDER BY d.inicio_datetime
                LIMIT 200
            """)
            agenda = cur.fetchall()
        result = []
        for row in agenda:
            r = dict(row)
            for key in ['inicio_datetime', 'fim_datetime']:
                if r.get(key):
                    r[key] = r[key].isoformat()
            result.append(r)
        return {"agenda": result}
    finally:
        db_pool.putconn(conn)

@app.post("/api/admin/agenda/liberar")
def liberar_agenda(req: LiberarAgenda, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        criados = 0
        with conn.cursor() as cur:
            for slot in req.slots:
                try:
                    cur.execute("""
                        INSERT INTO disponibilidade (id_medico, inicio_datetime, fim_datetime, status)
                        VALUES (%s, %s, %s, 'LIVRE')
                    """, (req.id_medico, slot["inicio"], slot["fim"]))
                    criados += 1
                except psycopg2.IntegrityError:
                    conn.rollback()
        conn.commit()
        return {"status": "success", "slots_criados": criados}
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINTS: CONSULTAS
# =========================================================
@app.get("/api/admin/consultas")
def listar_consultas(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT c.id_consulta, c.status, c.lembrete_24h_enviado, c.lembrete_dia_enviado,
                       p.nome AS paciente_nome, p.telefone,
                       m.nome AS medico_nome, m.especialidade,
                       d.inicio_datetime, d.fim_datetime
                FROM consulta c
                JOIN disponibilidade d ON d.id_disponibilidade = c.id_disponibilidade
                JOIN paciente p ON p.id_paciente = c.id_paciente
                JOIN medico m ON m.id_medico = d.id_medico
                WHERE d.inicio_datetime >= NOW() - INTERVAL '7 days'
                ORDER BY d.inicio_datetime DESC
                LIMIT 100
            """)
            consultas = cur.fetchall()
        result = []
        for row in consultas:
            r = dict(row)
            for key in ['inicio_datetime', 'fim_datetime']:
                if r.get(key):
                    r[key] = r[key].isoformat()
            result.append(r)
        return {"consultas": result}
    finally:
        db_pool.putconn(conn)

@app.patch("/api/admin/consultas/{id_consulta}/status")
def atualizar_status_consulta(id_consulta: int, body: dict = Body(...), user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        novo_status = body.get("status")
        status_validos = ['AGENDADA', 'CONFIRMADA', 'CANCELADA', 'REALIZADA', 'FALTOU']
        if novo_status not in status_validos:
            raise HTTPException(status_code=400, detail=f"Status inválido. Use: {status_validos}")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE consulta SET status = %s WHERE id_consulta = %s",
                (novo_status, id_consulta)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Consulta não encontrada")
        conn.commit()
        return {"status": "success", "novo_status": novo_status}
    finally:
        db_pool.putconn(conn)

@app.post("/api/admin/consultas/manual")
def agendar_manual(req: AgendamentoManual, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
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
                WHERE id_disponibilidade = %s AND status NOT IN ('CANCELADA', 'FALTOU')
            """, (req.id_disponibilidade,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Horário já ocupado")

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
            if not req.nome_paciente:
                raise HTTPException(status_code=422, detail="Paciente não encontrado. Informe o nome para cadastrar.")
            cpf_val = re.sub(r"\D", "", req.cpf or "")
            tel_val = re.sub(r"\D", "", req.telefone or "")
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO paciente (nome, cpf, telefone, aceite_lgpd, data_aceite_lgpd)
                    VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    RETURNING id_paciente
                """, (req.nome_paciente, cpf_val or None, tel_val or None))
                id_paciente = cur.fetchone()[0]
                conn.commit()

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

@app.put("/api/admin/consultas/{id_consulta}/cancelar")
def cancelar_consulta_admin(id_consulta: int, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id_disponibilidade FROM consulta WHERE id_consulta = %s", (id_consulta,))
            res = cur.fetchone()
            if not res:
                raise HTTPException(status_code=404, detail="Consulta não encontrada")
            id_disp = res[0]
            cur.execute("UPDATE consulta SET status = 'CANCELADA' WHERE id_consulta = %s", (id_consulta,))
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
# ENDPOINTS: PACIENTES
# =========================================================
@app.get("/api/admin/pacientes")
def listar_pacientes(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id_paciente, nome, telefone, cpf, email, nascimento,
                       aceite_lgpd, created_at
                FROM paciente
                WHERE deleted_at IS NULL
                ORDER BY nome
                LIMIT 500
            """)
            pacientes = cur.fetchall()
        result = []
        for row in pacientes:
            r = dict(row)
            for key in ['nascimento', 'created_at']:
                if r.get(key):
                    r[key] = r[key].isoformat()
            result.append(r)
        return {"pacientes": result}
    finally:
        db_pool.putconn(conn)

@app.get("/api/admin/pacientes/{id_paciente}/historico")
def get_historico_paciente(id_paciente: int, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    c.id_consulta, c.status,
                    d.inicio_datetime as inicio,
                    m.nome as medico_nome
                FROM consulta c
                JOIN disponibilidade d ON c.id_disponibilidade = d.id_disponibilidade
                JOIN medico m ON d.id_medico = m.id_medico
                WHERE c.id_paciente = %s
                ORDER BY d.inicio_datetime DESC
            """, (id_paciente,))
            hist = cur.fetchall()
            for h in hist:
                if h["inicio"]:
                    h["inicio"] = h["inicio"].isoformat()
        return {"historico": hist}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db_pool.putconn(conn)


# =========================================================
# ENDPOINTS: MENSAGENS WHATSAPP
# =========================================================
@app.get("/api/admin/mensagens")
def listar_mensagens(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id_mensagem, telefone_remetente, mensagem, direcao,
                       status_envio, created_at
                FROM whatsapp_mensagem
                ORDER BY created_at DESC
                LIMIT 200
            """)
            msgs = cur.fetchall()
        result = []
        for row in msgs:
            r = dict(row)
            if r.get('created_at'):
                r['created_at'] = r['created_at'].isoformat()
            result.append(r)
        return {"mensagens": result}
    finally:
        db_pool.putconn(conn)


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
                if u.get("created_at"):
                    u["created_at"] = u["created_at"].isoformat()
        return {"usuarios": usuarios}
    finally:
        db_pool.putconn(conn)

@app.post("/api/admin/usuarios")
def cadastrar_usuario(req: NovoUsuario, user=Depends(admin_auth)):
    if user.get("perfil") != "admin":
        raise HTTPException(status_code=403, detail="Apenas admins podem criar usuários")

    # Validação de força de senha
    validar_forca_senha(req.senha)

    conn = db_pool.getconn()
    try:
        senha_hash = bcrypt.hashpw(req.senha.encode(), bcrypt.gensalt()).decode()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usuario WHERE login = %s", (req.login,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="Login já existe")
                
            cur.execute("""
                INSERT INTO usuario (nome, login, senha_hash, perfil, ativo)
                VALUES (%s, %s, %s, %s, TRUE)
            """, (req.nome, req.login, senha_hash, req.perfil))
            conn.commit()
        return {"status": "success", "message": "Usuário criado"}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Login já existe")
    finally:
        db_pool.putconn(conn)

@app.post("/api/admin/usuarios/senha")
def alterar_senha_usuario(req: AlterarSenha, user=Depends(admin_auth)):
    if user.get("perfil") != "admin":
        raise HTTPException(status_code=403, detail="Apenas admins podem alterar senhas")

    # Validação de força de senha
    validar_forca_senha(req.nova_senha)

    conn = db_pool.getconn()
    try:
        senha_hash = bcrypt.hashpw(req.nova_senha.encode(), bcrypt.gensalt()).decode()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuario SET senha_hash = %s WHERE id_usuario = %s",
                (senha_hash, req.id_usuario)
            )
            conn.commit()
        return {"status": "success", "message": "Senha alterada"}
    finally:
        db_pool.putconn(conn)

@app.get("/api/admin/mensagens-pendentes")
def mensagens_pendentes(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT wm.id_log, wm.telefone_remetente, wm.mensagem,
                       wm.created_at, p.nome AS paciente_nome,
                       COALESCE(s.contexto_json->>'etapa', '') AS etapa_sessao
                FROM whatsapp_mensagem wm
                LEFT JOIN paciente p ON p.telefone = wm.telefone_remetente
                LEFT JOIN sessao_chatbot s ON s.telefone = wm.telefone_remetente
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
        db_pool.putconn(conn)

@app.post("/api/admin/resolver-atendimento")
def resolver_atendimento(req: ResolveAtendimento, user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sessao_chatbot 
                SET contexto_json = jsonb_set(COALESCE(contexto_json, '{}'::jsonb), '{etapa}', '"inicio"'), 
                    updated_at = CURRENT_TIMESTAMP
                WHERE telefone = %s
            """, (req.telefone,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Sessão não encontrada para o telefone")
            conn.commit()
        return {"status": "success", "message": "Atendimento resolvido, bot reiniciado."}
    finally:
        db_pool.putconn(conn)

@app.get("/api/admin/stats/agenda-semana")
def get_stats_agenda_semana(user=Depends(admin_auth)):
    conn = db_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                WITH recursive dates AS (
                    SELECT CURRENT_DATE - INTERVAL '7 days' as dia
                    UNION ALL
                    SELECT dia + INTERVAL '1 day' FROM dates WHERE dia < CURRENT_DATE + INTERVAL '14 days'
                )
                SELECT 
                    to_char(dates.dia, 'YYYY-MM-DD') as dia,
                    count(c.id_consulta) as total
                FROM dates
                LEFT JOIN disponibilidade d ON to_char(d.inicio_datetime, 'YYYY-MM-DD') = to_char(dates.dia, 'YYYY-MM-DD')
                LEFT JOIN consulta c ON c.id_disponibilidade = d.id_disponibilidade AND c.status NOT IN ('CANCELADA', 'FALTOU')
                GROUP BY dates.dia
                ORDER BY dates.dia ASC
            """)
            dados = cur.fetchall()
        return {"dados": dados}
    except Exception as e:
        logger.error(f"Erro ao buscar estatísticas da semana: {e}")
        return {"dados": []}
    finally:
        db_pool.putconn(conn)

@app.get("/api/admin/whatsapp/status")
def whatsapp_status(user=Depends(admin_auth)):
    try:
        headers = {"apikey": EVOLUTION_API_KEY}
        r = requests.get(f"{EVOLUTION_API_URL}/instance/fetchInstances", headers=headers, timeout=5)
        if r.status_code != 200:
            return {"status": "erro", "message": "Falha na API Evolution"}
        instances = r.json()
        if type(instances) is dict and "error" in instances:
            return {"status": "erro", "message": str(instances)}

        if not instances:
            payload = {"instanceName": "bot", "qrcode": True, "integration": "WHATSAPP-BAILEYS"}
            res = requests.post(f"{EVOLUTION_API_URL}/instance/create", json=payload, headers=headers, timeout=10)
            if res.status_code not in (200, 201):
                return {"status": "erro", "message": f"Erro ao criar instância: {res.text}"}
            return {"status": "desconectado", "instance": "bot"}
            
        inst = instances[0]
        instance_name = inst.get("name", inst.get("instanceName", "bot"))
        state = inst.get("connectionStatus", "DISCONNECTED")
        if state == "open" or state == "ONLINE":
            return {"status": "conectado", "instance": instance_name}
        return {"status": "desconectado", "instance": instance_name}
    except Exception as e:
        return {"status": "erro", "message": str(e)}

@app.get("/api/admin/whatsapp/qrcode")
def whatsapp_qrcode(instance: str = "bot", user=Depends(admin_auth)):
    try:
        headers = {"apikey": EVOLUTION_API_KEY}
        r = requests.get(f"{EVOLUTION_API_URL}/instance/connect/{instance}", headers=headers, timeout=5)
        if r.status_code == 200:
            return r.json()
        return {"error": f"Falha ao gerar QR Code: {r.status_code} - {r.text}"}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/admin/whatsapp/logout")
def whatsapp_logout(instance: str = "bot", user=Depends(admin_auth)):
    try:
        headers = {"apikey": EVOLUTION_API_KEY}
        r = requests.delete(f"{EVOLUTION_API_URL}/instance/logout/{instance}", headers=headers, timeout=5)
        return {"sucesso": r.status_code == 200}
    except Exception as e:
        return {"sucesso": False, "error": str(e)}
