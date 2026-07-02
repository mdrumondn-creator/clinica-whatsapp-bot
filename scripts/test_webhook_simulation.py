import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ['ALLOW_SEND'] = 'true'

from main import Mensagem, webhook

cases = [
    # 1. Número sem cadastro, com intenção de agendar
    Mensagem(telefone='5511999990001', mensagem='Quero agendar consulta', api_message_id='test-intent-1'),
    # 2. Número sem cadastro, sem intenção
    Mensagem(telefone='5511999990002', mensagem='Olá, só queria dizer oi', api_message_id='test-nointent-1'),
    # 3. Número sem cadastro, intent via single digit
    Mensagem(telefone='5511999990003', mensagem='1', api_message_id='test-intent-2')
]

for c in cases:
    print('---')
    print('Enviando:', c.telefone, c.mensagem)
    res = webhook(c)
    print('Resposta:', res)
