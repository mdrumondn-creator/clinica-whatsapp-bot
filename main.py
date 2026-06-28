from fastapi import FastAPI, HTTPException, Depends, Header, Body
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
from typing import Optional, List
from datetime import datetime, time as dt_time

# Configuração de Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

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
            SELECT bot_ativo, bot_inicio_funcionamento, bot_fim_funcionamento,
                   tempo_padrao_consulta_minutos
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
            SELECT id_sessao, contexto_json FROM sessao_chatbot
            WHERE telefone = %s AND estado_atual = 'ABERTA'
        """, (telefone,))
        
        sessao = cur.fetchone()

        if sessao:
            id_sessao = sessao[0]
            contexto = sessao[1] if sessao[1] else {}
            etapa = contexto.get("etapa", "inicio")
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
    except psycopg2.IntegrityError:
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
def processar_fluxo(conn, telefone, mensagem, etapa_atual, contexto):
    if etapa_atual == "inicio_agendamento":
        return (
            "Para prosseguir com seu atendimento, precisamos de alguns dados.\n\n"
            "🔒 *Em conformidade com a Lei nº 13.709 – Lei Geral de Proteção de Dados Pessoais (LGPD)*, será necessário o tratamento de seus dados pessoais para finalidade exclusiva de identificação, visando fornecer o atendimento adequado e aprimorar nossos serviços e sua experiência.\n\n"
            "🔗 Leia a lei na íntegra: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm\n\n"
            "Você aceita os termos descritos no link e concorda com o tratamento dos seus dados?"
        ), "validar_lgpd", ["Concordo", "Não Concordo"]

    if etapa_atual == "validar_lgpd":
        resp = str(mensagem).strip().lower()
        if resp in ["1", "concordo"]:
            return "Obrigado por confirmar! Por favor, digite seu *CPF* (somente números) ou número da carteirinha:", "pedir_cpf"
        elif resp in ["2", "não concordo", "nao concordo"]:
            return "Entendemos perfeitamente. Como precisamos dos dados para agendamento, seu atendimento foi encerrado. A clínica agradece o contato e estamos de portas abertas! 👋", "fim"
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
            return "Vi que é seu primeiro acesso conosco! Para finalizar o seu cadastro, por favor, digite o seu *Nome Completo*:", "pedir_nome"

        id_paciente = p[0]
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sessao_chatbot SET id_paciente = %s
                WHERE telefone = %s
            """, (id_paciente, telefone))
            conn.commit()

        resultado_inicio = processar_fluxo(conn, telefone, mensagem, "inicio", contexto)
        resposta_inicio = resultado_inicio[0]
        botoes_inicio = resultado_inicio[2] if len(resultado_inicio) == 3 else []
        
        with conn.cursor() as cur:
            cur.execute("SELECT nome FROM paciente WHERE id_paciente = %s", (id_paciente,))
            nome_paciente = cur.fetchone()[0].split()[0]
            
        return f"Bem-vindo(a) de volta, {nome_paciente}! " + resposta_inicio, "inicio", botoes_inicio

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
            
        resultado_inicio = processar_fluxo(conn, telefone, mensagem, "inicio", contexto)
        resposta_inicio = resultado_inicio[0]
        botoes_inicio = resultado_inicio[2] if len(resultado_inicio) == 3 else []
        return f"Cadastro concluído com sucesso, {nome.split()[0]}! " + resposta_inicio, "inicio", botoes_inicio

    if etapa_atual == "inicio":
        return (
            "Como posso te ajudar hoje?"
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
        salvar_mensagem(conn, msg)

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
            conn, msg.telefone, msg.mensagem, etapa_atual, contexto
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

        # Atualiza a etapa
        contexto["etapa"] = nova_etapa
        with conn.cursor() as cur:
            novo_contexto = json.dumps(contexto)
            cur.execute("""
                UPDATE sessao_chatbot
                SET contexto_json = %s
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
                       telefone, email, tempo_padrao_minutos, ativo
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
                       p.nome AS paciente_nome, p.telefone AS paciente_telefone
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
