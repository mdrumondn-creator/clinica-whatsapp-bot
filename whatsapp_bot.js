const qrcode = require('qrcode-terminal');
const { Client, LocalAuth } = require('whatsapp-web.js');
const axios = require('axios');

// Inicializa o cliente do WhatsApp (salva a sessão localmente para não pedir QR Code toda hora)
const client = new Client({
    authStrategy: new LocalAuth()
});

// Quando o WhatsApp pedir autenticação, gera o QR Code no terminal
client.on('qr', (qr) => {
    console.log('\n======================================================');
    console.log('🤖 Escaneie o QR Code abaixo com o WhatsApp da Clínica');
    console.log('======================================================\n');
    qrcode.generate(qr, { small: true });
});

// Quando conectar com sucesso
client.on('ready', () => {
    console.log('\n✅ Tudo certo! Bot do WhatsApp conectado com sucesso.');
    console.log('📡 Aguardando mensagens dos pacientes...\n');
});

// Listener: Quando receber uma mensagem
client.on('message', async (msg) => {
    // Ignorar status e mensagens de grupos
    if (msg.isStatus || msg.author || msg.from.includes('@g.us')) return;

    const telefone = msg.from.replace('@c.us', ''); // Limpa o ID do WhatsApp
    const texto = msg.body;
    const message_id = msg.id._serialized;

    console.log(`[📩 Nova Mensagem] De: ${telefone} | Texto: "${texto}"`);

    try {
        // Envia a mensagem via Webhook (POST) para o nosso backend em Python (FastAPI)
        const response = await axios.post('http://localhost:8000/webhook', {
            telefone: telefone,
            mensagem: texto,
            api_message_id: message_id
        });

        // O Python processa as regras de negócio e devolve o texto da resposta
        if (response.data && response.data.resposta) {
            console.log(`[🤖 Resposta Bot] ${response.data.resposta}`);
            msg.reply(response.data.resposta);
        }

    } catch (error) {
        console.error(`❌ Erro ao comunicar com a API Python:`, error.message);
        console.log(`Verifique se o servidor FastAPI está rodando em http://localhost:8000`);
    }
});

// Inicializa o robô
client.initialize();
