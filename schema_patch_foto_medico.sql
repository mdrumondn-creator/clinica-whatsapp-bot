-- PATCH: foto do médico + índice de stats
ALTER TABLE medico ADD COLUMN IF NOT EXISTS foto_base64 TEXT;
CREATE INDEX IF NOT EXISTS idx_disponibilidade_inicio ON disponibilidade(inicio_datetime);
