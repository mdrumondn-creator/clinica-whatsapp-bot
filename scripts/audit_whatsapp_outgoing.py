import psycopg2
import csv
import sys

OUTPUT_CSV = 'outgoing_whatsapp_messages.csv'

try:
    conn = psycopg2.connect(host='localhost', database='clinica', user='postgres', password='postgres')
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM whatsapp_mensagem
        WHERE direcao = 'SAIDA'
    """)
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT telefone_remetente, mensagem, api_message_id, created_at
        FROM whatsapp_mensagem
        WHERE direcao = 'SAIDA'
        ORDER BY created_at DESC
        LIMIT 500
    """)
    rows = cur.fetchall()

    print(f'Total de mensagens de saída registradas: {total}')
    if total > 0:
        with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['telefone_remetente', 'mensagem', 'api_message_id', 'created_at'])
            for r in rows:
                writer.writerow([r[0], r[1], r[2], r[3].isoformat() if r[3] else ''])
        print(f'Até 500 registros recentes gravados em: {OUTPUT_CSV}')
    else:
        print('Nenhuma mensagem de saída encontrada na tabela whatsapp_mensagem.')

    if total > 0:
        cur.execute("""
            SELECT COUNT(DISTINCT telefone_remetente)
            FROM whatsapp_mensagem
            WHERE direcao = 'SAIDA'
        """)
        distinct_numbers = cur.fetchone()[0]
        print(f'Número distinto de destinatários de saída: {distinct_numbers}')

    cur.close()
    conn.close()
except Exception as e:
    print('ERROR', e)
    sys.exit(1)
