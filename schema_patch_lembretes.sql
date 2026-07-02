-- =========================================================
-- PATCH: Lembretes automáticos por WhatsApp
-- Executar no banco PostgreSQL do servidor Oracle
-- =========================================================

-- 1. Colunas de controle na tabela consulta
ALTER TABLE consulta
    ADD COLUMN IF NOT EXISTS lembrete_24h_enviado BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS lembrete_dia_enviado  BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Templates de mensagem na configuracao_sistema
ALTER TABLE configuracao_sistema
    ADD COLUMN IF NOT EXISTS msg_lembrete_24h TEXT,
    ADD COLUMN IF NOT EXISTS msg_lembrete_dia TEXT;

-- Valores padrão (editáveis pelo painel admin depois)
UPDATE configuracao_sistema SET
    msg_lembrete_24h = E'Olá, {nome}! 👋\n\nLembramos que você tem consulta com *{medico}* amanhã, *{data}*.\n\nPara confirmar, responda *1 - Confirmar* ou *2 - Cancelar*. 🏥',
    msg_lembrete_dia = E'Bom dia, {nome}! ☀️\n\nHoje é o dia da sua consulta com *{medico}* às *{hora}*.\n\nLembre-se de chegar com 10 minutos de antecedência. Te esperamos! 🏥'
WHERE msg_lembrete_24h IS NULL;
