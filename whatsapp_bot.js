const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const path = require('path');
const { Client, LocalAuth } = require('whatsapp-web.js');
const axios = require('axios');

const seenMessageIds = new Set();
setInterval(() => seenMessageIds.clear(), 1000 * 60 * 5);

// Segurança cliente: kill-switch e rate-limit
const ALLOW_SEND = process.env.ALLOW_SEND === 'true';
const ALLOW_RESTART = process.env.ALLOW_RESTART === 'true';
const MAX_REPLIES_PER_MINUTE = parseInt(process.env.MAX_REPLIES_PER_MINUTE) || 120;
let repliesThisMinute = 0;
setInterval(() => { repliesThisMinute = 0; }, 60 * 1000);

// Inicializa o cliente do WhatsApp (salva a sessão localmente para não pedir QR Code toda hora)
const client = new Client({
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
        protocolTimeout: 120000
    },
    authStrategy: new LocalAuth()
});

// Recuperação automática: reinicia o client em caso de exceções não tratadas
async function restartClient(reason) {
    if (!ALLOW_RESTART) {
        console.warn('Restart automático desabilitado (ALLOW_RESTART!=true).');
        return;
    }
    console.error('>>> Reiniciando client por motivo:', reason);
    try {
        await client.destroy();
    } catch (e) {
        console.error('Erro ao destruir client:', e && e.message ? e.message : e);
    }
    // aguarda um pouco antes de reiniciar
    setTimeout(() => {
        try {
            client.initialize();
        } catch (e) {
            console.error('Falha ao reiniciar client:', e && e.message ? e.message : e);
        }
    }, 2000);
}

process.on('unhandledRejection', (reason, p) => {
    console.error('Unhandled Rejection at:', p, 'reason:', reason);
    restartClient('unhandledRejection');
});

process.on('uncaughtException', (err) => {
    console.error('Uncaught Exception:', err && err.stack ? err.stack : err);
    restartClient('uncaughtException');
});

client.on('disconnected', (reason) => {
    console.warn('Client desconectado:', reason);
    restartClient('disconnected');
});

// Quando o WhatsApp pedir autenticaÃ§Ã£o, gera o QR Code no terminal
client.on('qr', async (qr) => {
    console.log('\n======================================================');
    console.log('ðŸ¤– Escaneie o QR Code abaixo com o WhatsApp da ClÃnica');
    console.log('======================================================\n');
    qrcode.generate(qr, { small: true });

    const qrImagePath = path.resolve(__dirname, 'whatsapp_qr.png');
    try {
        await QRCode.toFile(qrImagePath, qr, { width: 240 });
        console.log(`\nQR salvo como imagem em: ${qrImagePath}`);
        console.log('Abra o arquivo se o QR no terminal estiver grande demais.\n');
    } catch (err) {
        console.error('Erro ao gerar QR Code como imagem:', err);
    }
});

// Quando conectar com sucesso
client.on('ready', () => {
    console.log('\n✅ Tudo certo! Bot do WhatsApp conectado com sucesso.');
    console.log('📡 Aguardando mensagens dos pacientes...\n');
});

// Listener: Quando receber uma mensagem
client.on('message', async (msg) => {
    // Ignorar status, mensagens do bot, mensagens de grupos e mensagens de tipo não suportado
    if (msg.isStatus || msg.fromMe || msg.author || msg.from.includes('@g.us')) return;
    if (!['chat', 'text', 'extendedTextMessage'].includes(msg.type)) return;

    const telefone = msg.from.replace('@c.us', ''); // Limpa o ID do WhatsApp
    const texto = msg.body;
    const message_id = msg.id._serialized;

    if (!texto || !texto.trim()) {
        console.log(`[⚠️ Ignorado] mensagem sem texto de: ${telefone} (tipo: ${msg.type})`);
        return;
    }

    if (seenMessageIds.has(message_id)) {
        console.log(`[⚠️ Ignorado] mensagem duplicada de: ${telefone} id: ${message_id}`);
        return;
    }
    seenMessageIds.add(message_id);

    console.log(`[📩 Nova Mensagem] De: ${telefone} | Texto: "${texto}"`);

    try {
        // Envia a mensagem via Webhook (POST) para o nosso backend em Python (FastAPI)
        const response = await axios.post('http://127.0.0.1:8000/webhook', {
            telefone: telefone,
            mensagem: texto,
            api_message_id: message_id
        });
        // O Python processa as regras de negócio e devolve o texto da resposta
        if (response.data) {
            // Se o backend indicar que o envio está desabilitado ou que não há sessão/paciente, respeite
            if (response.data.status) {
                const s = response.data.status;
                if (['sending_disabled', 'no_session_or_patient', 'ignored_outbound'].includes(s)) {
                    console.log(`[ℹ️ Backend sinalizou: ${s}] Não será enviada resposta para ${telefone}`);
                    return;
                }
            }

            if (!response.data.resposta) {
                // Nada para responder
                return;
            }

            if (!ALLOW_SEND) {
                console.warn('Envio de respostas está desabilitado no cliente (ALLOW_SEND!=true).');
                return;
            }

            if (repliesThisMinute >= MAX_REPLIES_PER_MINUTE) {
                console.warn('Rate limit atingido. Pulando envio para evitar flood.');
                return;
            }

            const textoResposta = response.data.resposta;
            console.log(`[🤖 Preparando Resposta] ${textoResposta}`);

            // 1. Pega a conversa e mostra o status "digitando..." no celular do paciente
            const chat = await msg.getChat();
            await chat.sendStateTyping();

            // 2. Calcula um atraso realista: 2 segundos + 50ms por cada letra do texto
            const delayHumanizado = Math.max(2000, textoResposta.length * 50);

            // 3. Espera o tempo, envia a mensagem e limpa o "digitando..."
            setTimeout(async () => {
                try {
                    await msg.reply(textoResposta);
                    repliesThisMinute += 1;
                    await chat.clearState();
                    console.log(`[✅ Enviado] Após ${delayHumanizado}ms`);
                } catch (e) {
                    console.error('Erro ao enviar resposta:', e && e.message ? e.message : e);
                }
            }, delayHumanizado);
        }

    } catch (error) {
        console.error('❌ Erro ao comunicar com a API Python:', error.message || error.toString());
        if (error.response) {
            console.error('--- Resposta da API ---');
            console.error('Status:', error.response.status);
            console.error('Dados:', error.response.data);
        }
        console.error(error.stack || error);
        console.log('Verifique se o servidor FastAPI está rodando em http://127.0.0.1:8000');
    }
});

// Inicializa o robô
client.initialize();
