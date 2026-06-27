# 🏥 Contexto do Projeto: Clínica WhatsApp Bot

**Ambiente:** Oracle Cloud (Always Free - Ampere A1 ARM64)
**OS:** Oracle Linux 9
**Servidor IP:** 137.131.225.116

Este documento resume o estado atual da infraestrutura de atendimento do WhatsApp da clínica. O projeto foi **migrado** de um ambiente local (Windows/WSL) para um servidor em nuvem (Oracle Cloud), garantindo estabilidade e execução 100% via Docker.

---

## 🏗️ Arquitetura Atual (Docker)

O ecossistema roda inteiramente orquestrado pelo `docker-compose.yml`, otimizado para a arquitetura **ARM64**:

1. **Evolution API (`:8080`)**:
   - Motor de conexão com o WhatsApp.
   - Atualizado para a versão **v2.3.7** (estável).
   - Comunica-se com o PostgreSQL e Redis.
   - Dispara Webhooks para o Bot em Python.

2. **Bot em Python / FastAPI (`:8000/docs`)**:
   - Cérebro do sistema de triagem.
   - Recebe mensagens da Evolution API, avalia horários e intenções, e direciona para o humano (Chatwoot) quando necessário.

3. **Chatwoot (`:3000`)**:
   - Painel de atendimento humano (CRM).
   - **Nota de Arquitetura:** Roda de forma nativa (`chatwoot:latest`) sem emulação. A chave `SECRET_KEY_BASE` foi fixada em 128 caracteres no arquivo `.yml` para evitar travamentos do Rails 7.

4. **Bancos de Dados**:
   - **PostgreSQL (`pgvector/pgvector:pg15`)**: A imagem foi obrigatoriamente alterada de `alpine` para `pgvector` pois as novas versões do Chatwoot exigem a extensão `vector` para recursos de IA, o que causava falha na criação do banco (`db:chatwoot_prepare`).
   - **Redis 7**: Gerenciamento de filas (Sidekiq) e cache da Evolution API.

---

## ⚠️ Lições Aprendidas na Migração (ARM64)
- **Emulação QEMU:** Evitada. O Oracle Linux 9 (via SELinux) bloqueia binários AMD64 por padrão, causando `exec format error`.
- **Tamanho de Senhas:** O Chatwoot falhará na inicialização silenciosamente se o `SECRET_KEY_BASE` tiver menos de 64 caracteres.
- **Banco de Dados Chatwoot:** Em instalações do zero, é estritamente necessário rodar `docker compose run --rm chatwoot-web bundle exec rake db:chatwoot_prepare` com uma imagem Postgres que suporte `pgvector`.
- **Alinhamento de Webhooks**: O Chatwoot exige que a URL do Webhook da API do Canal esteja exatamente alinhada com o nome da instância ativa (ex: `/chatwoot/webhook/bot`), sob pena de retornar erro `404 Not Found` no tráfego de saída.

---

## ✅ O Que Já Foi Feito (Status: Pronto)

- [x] Migração de código do Windows para Linux via Git.
- [x] Deploy da Evolution API + Redis + Banco.
- [x] Resolução de conflitos de compatibilidade ARM64 do Chatwoot.
- [x] Criação de tabelas do banco de dados concluída.
- [x] Chatwoot acessível pelo IP público.
- [x] Criação da conta do SuperAdmin e caixa de entrada do Chatwoot.
- [x] Alinhamento e atualização da Evolution API para a versão **v2.3.7** (estável).
- [x] Correção dos webhooks do Chatwoot no banco de dados local.

---

## 🎯 Próximos Passos (Na Prática)

1. **Leitura do QR Code / Pairing Code**: Autenticar o celular do cliente no Evolution Manager.
2. **Testar Triagem**: Enviar uma mensagem para a clínica, verificar se o Bot em Python responde corretamente ou repassa a conversa para a tela do Chatwoot.
3. **Isolamento de Projetos**: Garantir que o consumo de memória se mantenha baixo para podermos implementar o `appo-bot-love` (segundo cliente) no mesmo servidor sem gerar conflitos de rede ou carga.

