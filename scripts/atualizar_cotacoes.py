#!/usr/bin/env python3
"""
atualizar_cotacoes.py
Consulta cotações da brapi.dev e salva no banco SQLite.
Roda a cada 15 minutos via cron.
Uso: python3 atualizar_cotacoes.py
"""

import os
import sqlite3
import requests
import logging
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path("/mnt/external/portfolio_tracker")
load_dotenv(BASE_DIR / ".env")

DB_PATH     = BASE_DIR / "database" / "carteira.db"
LOG_PATH    = BASE_DIR / "logs" / "cotacoes.log"
BRAPI_TOKEN = os.getenv("BRAPI_TOKEN", "")
BRAPI_URL   = "https://brapi.dev/api/quote/{ticker}?token=" + BRAPI_TOKEN
DELAY_SEG   = 2  # pausa entre requests para não sobrecarregar a API

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Busca todos os tickers cadastrados
    cur.execute("SELECT ticker FROM acoes ORDER BY ticker")
    tickers = [row[0] for row in cur.fetchall()]

    if not tickers:
        log.warning("Nenhum ativo encontrado no banco.")
        conn.close()
        return

    atualizados = 0
    erros       = 0
    agora       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for ticker in tickers:
        url = BRAPI_URL.format(ticker=ticker)

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"{ticker}: erro na requisição — {e}")
            erros += 1
            time.sleep(DELAY_SEG)
            continue

        resultados = data.get("results", [])
        if not resultados:
            log.warning(f"{ticker}: sem resultado na resposta")
            erros += 1
            time.sleep(DELAY_SEG)
            continue

        item = resultados[0]
        preco          = item.get("regularMarketPrice")
        variacao_pct   = item.get("regularMarketChangePercent")
        variacao_valor = item.get("regularMarketChange")
        volume         = item.get("regularMarketVolume")
        abertura       = item.get("regularMarketOpen")
        minimo         = item.get("regularMarketDayLow")
        maximo         = item.get("regularMarketDayHigh")

        if preco is None:
            log.warning(f"{ticker}: preço ausente na resposta")
            erros += 1
            time.sleep(DELAY_SEG)
            continue

        cur.execute("""
            INSERT INTO cotacoes
                (ticker, preco, variacao_dia, variacao_valor, volume,
                 preco_abertura, preco_minimo, preco_maximo, data_atualizacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, preco, variacao_pct, variacao_valor, volume,
              abertura, minimo, maximo, agora))

        atualizados += 1
        log.debug(f"{ticker}: R${preco} ({variacao_pct:+.2f}%)" if variacao_pct else f"{ticker}: R${preco}")
        time.sleep(DELAY_SEG)

    conn.commit()
    conn.close()

    log.info(f"Atualizados: {atualizados} | Erros: {erros} | Total: {len(tickers)}")
    print(f"[{agora}] ✅ {atualizados}/{len(tickers)} cotações atualizadas | {erros} erros")

if __name__ == "__main__":
    main()
