# 🏥 Contexto do Projeto: Clínica WhatsApp Bot (Evolution API)

**Diretório Principal:** `D:\clinica-bot`

Este documento resume o estado da infraestrutura de atendimento do WhatsApp da clínica, baseada na **Evolution API** rodando nativamente no Windows, com banco de dados e painel **Chatwoot** via Docker.

---

## 🏗️ Arquitetura Configuradada

O projeto foi estruturado para resolver os problemas de bloqueio do WSL2 no Windows, separando a infraestrutura da seguinte forma:

1. **Containers Docker (`docker-compose.yml`)**
   - `db`: PostgreSQL 15 (porta `15432:5432`) - Armazena dados da Evolution API e do Chatwoot.
   - `redis`: Redis 7 (porta `6379:6379`) - Cache e mensageria.
   - `chatwoot`: Painel de atendimento humano (porta `3000:3000`).
   - `sidekiq`: Processamento de background do Chatwoot.

2. **Evolution API Nativa (`evolution-api-native/`)**
   - Devido a limitações do Docker no Windows (WSL2 signature blocking), a Evolution API foi clonada para rodar **nativamente no Node.js** (porta `8080`).
   - Foi criado o script `override.js` para burlar a detecção do OS.
   - O `.env` nativo está configurado para acessar o PostgreSQL e Redis que rodam no Docker (via `127.0.0.1:15432` e `6379`).

3. **Scripts de Automação Criados**
   - `iniciar_evolution.bat`: Inicia o banco/redis no Docker, configura o `.env` nativo, instala os pacotes npm, aplica o Prisma (banco de dados) e sobe a Evolution API.
   - `gerar_instancia.bat`: Faz a requisição POST para a Evolution API para criar a instância `clinica-bot` do WhatsApp.
   - `qrcode.html`: Uma página HTML simples para você abrir no navegador, que consome a API da Evolution e renderiza o QR Code do WhatsApp.

---

## ✅ O Que Já Foi Feito (Status: Pronto)

- [x] Estrutura do `docker-compose.yml` para os serviços base.
- [x] Repositório da Evolution API baixado na pasta `evolution-api-native`.
- [x] Script de patch `override.js` aplicado com sucesso.
- [x] Scripts `.bat` prontos para rodar a aplicação sem complicação.
- [x] Evolution API pré-compilada na pasta `dist/`.

---

## 🔴 O Que Falta Fazer (Bloqueadores Atuais)

Neste exato momento, **todo o sistema está desligado**. Para colocá-lo em 100% de funcionamento, faltam os seguintes passos na ordem:

1. **Ligar o Docker Desktop**
   - Detectei que o Docker API não está respondendo. O Docker Desktop precisa estar aberto no Windows antes de qualquer coisa, senão o Banco de Dados e o Redis não sobem.

2. **Executar a Infraestrutura**
   - Rodar o script `D:\clinica-bot\iniciar_evolution.bat` (que vai subir os containers do banco e iniciar a Evolution API no terminal).

3. **Conectar o WhatsApp**
   - Com a Evolution API rodando, executar o script `D:\clinica-bot\gerar_instancia.bat`.
   - Abrir o arquivo `D:\clinica-bot\qrcode.html` no navegador e ler o QR Code com o WhatsApp do aparelho da clínica.

4. **Testar Integração com Chatwoot / Bot**
   - Acessar o Chatwoot (`http://localhost:3000`), configurar a caixa de entrada da Evolution API.
   - Ligar o servidor Python (FastAPI) para assumir a triagem automática inicial antes de passar para o Chatwoot.

---

## 🎯 Próximo Passo

O sistema está montado e roteirizado, só precisa ser ligado. Abra o **Docker Desktop** no seu Windows, aguarde ele ficar "verde" (Running) e me avise para rodarmos os scripts de inicialização juntos!
