# Clínica WhatsApp Bot

Bot de WhatsApp para gerenciamento de agendamentos em clínicas médicas, com painel administrativo web e controle de horário de funcionamento.

## Arquitetura

```
WhatsApp (paciente)
        ↓
whatsapp_bot.js  ←→  main.py (FastAPI)  ←→  PostgreSQL
                           ↑
                   admin_dashboard.html
                   (Painel Web Admin)
```

## Funcionalidades

### Bot Automático (WhatsApp)
- Atendimento automatizado em horário configurável
- Fluxo de consentimento LGPD
- Identificação de paciente por CPF
- Cadastro de novos pacientes
- Agendamento com controle de concorrência (lock `FOR UPDATE`)
- Kill-switch e controle de horário via banco de dados

### Painel Administrativo Web
- Login seguro com token JWT
- Dashboard com estatísticas do dia
- Controle do bot: ligar/desligar, configurar horário de atendimento
- Cadastro de médicos
- Liberação de agenda (slots de disponibilidade)
- Visualização de mensagens recebidas

## Pré-requisitos

- Node.js 18+
- Python 3.10+
- PostgreSQL 14+

## Instalação

### 1. Banco de Dados

```sql
-- Aplicar o schema principal
\i modelo.sql

-- Aplicar o patch de configurações do bot
\i schema_patch.sql
```

### 2. Variáveis de Ambiente

```bash
cp .env.example .env
# Editar .env com suas credenciais reais
```

### 3. Back-end Python (FastAPI)

```bash
pip install fastapi uvicorn psycopg2-binary python-dotenv
uvicorn main:app --reload --port 8000
```

### 4. Criar Primeiro Administrador

```bash
python create_admin.py
```

### 5. Bot Node.js

```bash
npm install
node whatsapp_bot.js
```

### 6. Painel Administrativo

Abra `admin_dashboard.html` no navegador. Certifique-se de que `API_BASE` aponta para o endereço correto do servidor FastAPI.

## Variáveis de Ambiente

| Variável | Descrição | Padrão |
|---|---|---|
| `DB_HOST` | Host do PostgreSQL | `localhost` |
| `DB_NAME` | Nome do banco | `clinica` |
| `DB_USER` | Usuário do banco | `postgres` |
| `DB_PASS` | Senha do banco | — |
| `JWT_SECRET` | Segredo para assinatura JWT | — |
| `ALLOW_SEND` | Habilita envio de mensagens pelo bot | `false` |

## Controle de Horário do Bot

O bot responde automaticamente apenas dentro do horário configurado no painel admin ou diretamente na tabela `configuracao_sistema`:

| Situação | Comportamento |
|---|---|
| Bot ativo + dentro do horário | Atendimento automático completo |
| Bot ativo + fora do horário | Informa o paciente e registra a mensagem |
| Bot desativado (kill-switch) | Silêncio total — equipe humana assume |

## Segurança

- Senhas de administradores armazenadas com hash (SHA-256; migrar para bcrypt em produção)
- Tokens JWT com expiração de 8 horas
- Credenciais do banco via variáveis de ambiente (nunca hardcoded)
- Tabela de auditoria para todas as ações administrativas
- Controle de LGPD embutido no fluxo do bot

## Licença

Uso privado — clínica médica.
