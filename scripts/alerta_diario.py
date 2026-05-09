#!/usr/bin/env python3
"""
alerta_diario.py
Roda todo dia de manhã e envia alertas automáticos via Telegram.
Uso: python3 alerta_diario.py
Cron: 0 9 * * 1-5 python3 /mnt/external/portfolio_tracker/scripts/alerta_diario.py
"""

import os
import sqlite3
import requests
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path("/mnt/external/portfolio_tracker")
load_dotenv(BASE_DIR / ".env")

DB_PATH        = BASE_DIR / "database" / "carteira.db"
LOG_PATH       = BASE_DIR / "logs" / "alertas.log"
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
ALLOWED_CHATID = int(os.getenv("ALLOWED_CHATID", "0"))
API_URL        = f"https://api.telegram.org/bot{BOT_TOKEN}"
LIMITE_PCT     = 5.0  # % de variação para gerar sinal

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

def send(text: str):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": ALLOWED_CHATID,
        "text": text,
        "parse_mode": "HTML"
    })

def gerar_alertas(cur) -> str:
    cur.execute("""
        SELECT ticker, tipo, quantidade, preco_medio, preco_atual,
               rentabilidade_pct, valor_atual, lucro_prejuizo
        FROM carteira_resumo
        WHERE preco_atual IS NOT NULL
        ORDER BY rentabilidade_pct ASC
    """)
    rows = cur.fetchall()

    if not rows:
        return "⚠️ Nenhum ativo com cotação disponível."

    compras  = []
    vendas   = []
    neutros  = []

    for ticker, tipo, qtd, pm, preco_atual, rent, valor_atual, lp in rows:
        if rent is None:
            continue

        variacao = rent  # % vs preço médio

        if variacao <= -LIMITE_PCT:
            compras.append((ticker, tipo, qtd, pm, preco_atual, variacao, lp))
        elif variacao >= LIMITE_PCT:
            vendas.append((ticker, tipo, qtd, pm, preco_atual, variacao, lp))
        else:
            neutros.append((ticker, tipo, qtd, pm, preco_atual, variacao, lp))

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg   = f"📊 <b>Análise da Carteira</b> — {agora}\n"
    msg  += f"Limite: variação {'>'} {LIMITE_PCT}% do preço médio\n"
    msg  += "─" * 25 + "\n\n"

    if compras:
        msg += "🟢 <b>OPORTUNIDADE DE COMPRA</b>\n"
        msg += "<i>Abaixo do preço médio — pode ser boa hora de aportar</i>\n\n"
        for ticker, tipo, qtd, pm, preco, var, lp in compras:
            msg += (
                f"  <b>{ticker}</b> ({tipo})\n"
                f"  PM: R${pm:.2f} → Atual: R${preco:.2f}\n"
                f"  Variação: {var:+.2f}% | R${lp:+.2f}\n\n"
            )

    if vendas:
        msg += "🔴 <b>CONSIDERAR REALIZAÇÃO</b>\n"
        msg += "<i>Acima do preço médio — avalie realizar lucro</i>\n\n"
        for ticker, tipo, qtd, pm, preco, var, lp in vendas:
            msg += (
                f"  <b>{ticker}</b> ({tipo})\n"
                f"  PM: R${pm:.2f} → Atual: R${preco:.2f}\n"
                f"  Variação: {var:+.2f}% | R${lp:+.2f}\n\n"
            )

    if neutros:
        msg += "🟡 <b>NEUTRO</b>\n"
        msg += "<i>Dentro da faixa de ±5% do preço médio</i>\n\n"
        for ticker, tipo, qtd, pm, preco, var, lp in neutros:
            msg += (
                f"  <b>{ticker}</b>: R${preco:.2f} ({var:+.2f}%)\n"
            )

    msg += f"\n⚠️ <i>Análise informativa. Não é recomendação de investimento.</i>"
    return msg

def main():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    msg  = gerar_alertas(cur)
    conn.close()

    send(msg)
    log.info("Alerta diário enviado")
    print("✅ Alerta diário enviado!")

if __name__ == "__main__":
    main()

