-- =========================================================
-- PATCH V1.2: MENSAGENS DINÂMICAS DO BOT
-- =========================================================

ALTER TABLE configuracao_sistema
ADD COLUMN IF NOT EXISTS msg_saudacao TEXT DEFAULT 'Para prosseguir com seu atendimento, precisamos de alguns dados.

🔒 *Em conformidade com a Lei nº 13.709 – Lei Geral de Proteção de Dados Pessoais (LGPD)*, será necessário o tratamento de seus dados pessoais para finalidade exclusiva de identificação, visando fornecer o atendimento adequado e aprimorar nossos serviços e sua experiência.

🔗 Leia a lei na íntegra: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm

Você aceita os termos descritos no link e concorda com o tratamento dos seus dados?',
ADD COLUMN IF NOT EXISTS msg_solicitar_cpf TEXT DEFAULT 'Obrigado por confirmar! Por favor, digite seu *CPF* (somente números) ou número da carteirinha:',
ADD COLUMN IF NOT EXISTS msg_despedida_lgpd TEXT DEFAULT 'Entendemos perfeitamente. Como precisamos dos dados para agendamento, seu atendimento foi encerrado. A clínica agradece o contato e estamos de portas abertas! 👋',
ADD COLUMN IF NOT EXISTS msg_solicitar_nome TEXT DEFAULT 'Vi que é seu primeiro acesso conosco! Para finalizar o seu cadastro, por favor, digite o seu *Nome Completo*:',
ADD COLUMN IF NOT EXISTS msg_fora_horario TEXT DEFAULT '🕐 Olá! Nosso atendimento automático funciona das {inicio} às {fim}. Sua mensagem foi registrada e nossa equipe entrará em contato assim que possível no próximo horário de atendimento. Obrigado pela compreensão! 🏥';
