Documentação comentada do Clinica WhatsApp Bot

Veja o arquivo na área de trabalho: C:\Users\MARCEL\Desktop\clinica_whatsapp_bot_comentado.md

Este repositório contém:
- `main.py` — servidor FastAPI com regras de segurança e fluxo de agendamento.
- `whatsapp_bot.js` — cliente Node.js que encaminha mensagens para o servidor.
- `scripts/` — scripts de auditoria e testes.

As alterações recentes adicionam:
- Kill-switch (`ALLOW_SEND`) no servidor e cliente.
- Validação opt-in: só responde automaticamente para consultas `AGENDADA`/`CONFIRMADA`.
- Criação de sessão por intenção de agendamento (detecção por palavras-chave).
- Coleta e validação de CPF antes de permitir agendamento.
- Rate-limit e proteção contra reinício automático não autorizado.

Consulte `clinica_whatsapp_bot_comentado.md` na área de trabalho para uma explicação em linguagem simples com trechos do código.
