-- =========================================================
-- SISTEMA CLÍNICO + CHATBOT
-- VERSÃO FINAL CONSOLIDADA (REFINADA PARA PRODUÇÃO)
-- =========================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- =========================================================
-- ENUMS
-- =========================================================

CREATE TYPE status_consulta_enum AS ENUM (
    'AGENDADA','CONFIRMADA','CANCELADA','REALIZADA','FALTOU'
);

CREATE TYPE status_pagamento_enum AS ENUM (
    'PENDENTE','PARCIAL','PAGO','CANCELADO','ESTORNADO'
);

CREATE TYPE tipo_movimento_enum AS ENUM ('ENTRADA','SAIDA');

CREATE TYPE status_disponibilidade_enum AS ENUM ('LIVRE','BLOQUEADO');

CREATE TYPE status_sessao_enum AS ENUM ('ABERTA','ENCERRADA','TRANSFERIDA','ABANDONADA');

CREATE TYPE direcao_mensagem_enum AS ENUM ('ENTRADA','SAIDA');

CREATE TYPE status_lembrete_enum AS ENUM ('PENDENTE','ENVIADO','ERRO');

CREATE TYPE status_envio_enum AS ENUM ('PENDENTE','ENVIADO','ERRO');

-- =========================================================
-- PACIENTE
-- =========================================================

CREATE TABLE paciente (
    id_paciente SERIAL PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    telefone VARCHAR(20) NOT NULL,
    cpf VARCHAR(14) UNIQUE,
    nascimento DATE,
    email VARCHAR(150),
    endereco TEXT,
    aceite_lgpd BOOLEAN DEFAULT FALSE,
    data_aceite_lgpd TIMESTAMPTZ,
    observacoes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_paciente_telefone ON paciente(telefone);

-- =========================================================
-- MEDICO
-- =========================================================

CREATE TABLE medico (
    id_medico SERIAL PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    especialidade VARCHAR(100),
    crm VARCHAR(20) NOT NULL,
    uf_crm VARCHAR(2) NOT NULL,
    telefone VARCHAR(20),
    email VARCHAR(150),
    tempo_padrao_minutos INT DEFAULT 30,
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_medico_crm UNIQUE (crm, uf_crm)
);

-- =========================================================
-- DISPONIBILIDADE
-- =========================================================

CREATE TABLE disponibilidade (
    id_disponibilidade SERIAL PRIMARY KEY,
    id_medico INT NOT NULL,
    inicio_datetime TIMESTAMPTZ NOT NULL,
    fim_datetime TIMESTAMPTZ NOT NULL,
    status status_disponibilidade_enum DEFAULT 'LIVRE',
    permite_sobreposicao BOOLEAN DEFAULT FALSE,
    origem VARCHAR(50),
    google_event_id VARCHAR(100),
    google_sync_status VARCHAR(30),
    observacoes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_disp_medico FOREIGN KEY (id_medico)
        REFERENCES medico(id_medico),

    CONSTRAINT chk_disp_horario
        CHECK (fim_datetime > inicio_datetime)
);

-- 🔥 CONTROLE DE SOBREPOSIÇÃO REAL
ALTER TABLE disponibilidade ADD CONSTRAINT no_overlap_medico
EXCLUDE USING GIST (
    id_medico WITH =,
    tstzrange(inicio_datetime, fim_datetime) WITH &&
)
WHERE (permite_sobreposicao = FALSE);

-- =========================================================
-- TIPO CONSULTA (NORMALIZADO)
-- =========================================================

CREATE TABLE tipo_consulta (
    id_tipo SERIAL PRIMARY KEY,
    nome VARCHAR(50) UNIQUE NOT NULL
);

-- =========================================================
-- CONSULTA
-- =========================================================

CREATE TABLE consulta (
    id_consulta SERIAL PRIMARY KEY,
    id_paciente INT NOT NULL,
    id_disponibilidade INT NOT NULL,
    id_tipo INT,
    status status_consulta_enum DEFAULT 'AGENDADA',
    observacoes TEXT,
    origem VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_consulta_paciente FOREIGN KEY (id_paciente)
        REFERENCES paciente(id_paciente),

    CONSTRAINT fk_consulta_disp FOREIGN KEY (id_disponibilidade)
        REFERENCES disponibilidade(id_disponibilidade),
        
    CONSTRAINT fk_consulta_tipo FOREIGN KEY (id_tipo)
        REFERENCES tipo_consulta(id_tipo)
);

-- Impede múltiplos agendamentos ATIVOS para a mesma disponibilidade
CREATE UNIQUE INDEX idx_disp_ativa ON consulta(id_disponibilidade) 
WHERE status NOT IN ('CANCELADA', 'FALTOU');

-- =========================================================
-- FINANCEIRO
-- =========================================================

CREATE TABLE financeiro (
    id_financeiro SERIAL PRIMARY KEY,
    id_paciente INT NOT NULL,
    id_consulta INT, -- Nullable para cobranças avulsas
    categoria VARCHAR(50),
    valor_total NUMERIC(10,2) NOT NULL,
    desconto NUMERIC(10,2) DEFAULT 0.00,
    valor_liquido NUMERIC(10,2) NOT NULL,
    forma_pagamento VARCHAR(50),
    status_pagamento status_pagamento_enum DEFAULT 'PENDENTE',
    data_pagamento TIMESTAMPTZ,
    observacoes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ,

    CONSTRAINT fk_fin_paciente FOREIGN KEY (id_paciente)
        REFERENCES paciente(id_paciente),

    CONSTRAINT fk_fin_consulta FOREIGN KEY (id_consulta)
        REFERENCES consulta(id_consulta)
);

-- =========================================================
-- USUARIO
-- =========================================================

CREATE TABLE usuario (
    id_usuario SERIAL PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    login VARCHAR(100) UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    perfil VARCHAR(50) NOT NULL,
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================
-- MOVIMENTO DE CAIXA
-- =========================================================

CREATE TABLE movimento_caixa (
    id_movimento SERIAL PRIMARY KEY,
    id_financeiro INT,
    id_usuario INT,
    tipo tipo_movimento_enum NOT NULL,
    valor NUMERIC(10,2) NOT NULL,
    descricao TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_mov_fin FOREIGN KEY (id_financeiro)
        REFERENCES financeiro(id_financeiro),

    CONSTRAINT fk_mov_usuario FOREIGN KEY (id_usuario)
        REFERENCES usuario(id_usuario)
);

-- =========================================================
-- LEMBRETES
-- =========================================================

CREATE TABLE lembrete (
    id_lembrete SERIAL PRIMARY KEY,
    id_consulta INT NOT NULL,
    agendado_para TIMESTAMPTZ NOT NULL,
    enviado_em TIMESTAMPTZ,
    status status_lembrete_enum DEFAULT 'PENDENTE',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_lembrete_consulta FOREIGN KEY (id_consulta)
        REFERENCES consulta(id_consulta)
);

-- =========================================================
-- SESSAO CHATBOT
-- =========================================================

CREATE TABLE sessao_chatbot (
    id_sessao SERIAL PRIMARY KEY,
    telefone VARCHAR(20) UNIQUE NOT NULL,
    id_paciente INT,
    estado_atual status_sessao_enum DEFAULT 'ABERTA',
    contexto_json JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_sessao_paciente FOREIGN KEY (id_paciente)
        REFERENCES paciente(id_paciente)
);

-- =========================================================
-- WHATSAPP MENSAGEM
-- =========================================================

CREATE TABLE whatsapp_mensagem (
    id_log SERIAL PRIMARY KEY,
    telefone_remetente VARCHAR(20) NOT NULL,
    id_paciente INT,
    api_message_id VARCHAR(100) UNIQUE,
    mensagem TEXT,
    direcao direcao_mensagem_enum NOT NULL,
    tipo VARCHAR(50),
    status_envio status_envio_enum DEFAULT 'PENDENTE',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_msg_paciente FOREIGN KEY (id_paciente)
        REFERENCES paciente(id_paciente)
);

-- =========================================================
-- AUDITORIA
-- =========================================================

CREATE TABLE auditoria (
    id_auditoria SERIAL PRIMARY KEY,
    id_registro INT NOT NULL,
    tabela VARCHAR(100) NOT NULL,
    acao VARCHAR(20) NOT NULL,
    id_usuario INT,
    dados_anteriores JSONB,
    dados_novos JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_aud_usuario FOREIGN KEY (id_usuario)
        REFERENCES usuario(id_usuario)
);

-- =========================================================
-- INDICES ADICIONAIS DE PERFORMANCE
-- =========================================================

CREATE INDEX idx_disp_medico ON disponibilidade(id_medico);
CREATE INDEX idx_consulta_paciente ON consulta(id_paciente);
CREATE INDEX idx_financeiro_paciente ON financeiro(id_paciente);
CREATE INDEX idx_lembrete_agendado ON lembrete(agendado_para);
CREATE INDEX idx_msg_telefone ON whatsapp_mensagem(telefone_remetente);
CREATE INDEX idx_auditoria_registro ON auditoria(tabela, id_registro);
