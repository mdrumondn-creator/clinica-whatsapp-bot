-- =========================================================
-- PATCH: CONTROLE DE FUNCIONAMENTO DO BOT
-- =========================================================

-- Tabela para gerenciar parâmetros operacionais globais do bot e clínica
CREATE TABLE IF NOT EXISTS configuracao_sistema (
    id_config SERIAL PRIMARY KEY,
    bot_ativo BOOLEAN DEFAULT TRUE,
    bot_inicio_funcionamento TIME NOT NULL DEFAULT '08:00:00',
    bot_fim_funcionamento TIME NOT NULL DEFAULT '18:00:00',
    tempo_padrao_consulta_minutos INT NOT NULL DEFAULT 30,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Insere uma linha inicial de configuração caso não exista
INSERT INTO configuracao_sistema (id_config, bot_ativo, bot_inicio_funcionamento, bot_fim_funcionamento, tempo_padrao_consulta_minutos)
VALUES (1, TRUE, '08:00:00', '18:00:00', 30)
ON CONFLICT (id_config) DO NOTHING;
