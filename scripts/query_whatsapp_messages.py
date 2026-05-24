import psycopg2
import csv
import sys

try:
    conn = psycopg2.connect(host='localhost', database='clinica', user='postgres', password='postgres')
    cur = conn.cursor()
    cur.execute("""
        SELECT telefone_remetente, mensagem, direcao, api_message_id, created_at
        FROM whatsapp_mensagem
        ORDER BY created_at DESC
        LIMIT 200
    """)
    rows = cur.fetchall()
    writer = csv.writer(sys.stdout)
    writer.writerow(['telefone_remetente','mensagem','direcao','api_message_id','created_at'])
    for r in rows:
        writer.writerow([r[0], r[1], r[2], r[3], r[4].isoformat() if r[4] else ''])
    cur.close()
    conn.close()
except Exception as e:
    print('ERROR', e)
    sys.exit(1)
