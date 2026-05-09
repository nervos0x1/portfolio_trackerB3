#!/usr/bin/env python3
"""
relatorio.py
Gera PDF com resumo semanal da carteira e envia via Telegram.
Uso: python3 relatorio.py
"""

import os
import sqlite3
import requests
import logging
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from fpdf import FPDF
from dotenv import load_dotenv

# --- CONFIG -------------------------------------------------------------------
BASE_DIR = Path("/mnt/external/portfolio_tracker")
load_dotenv(BASE_DIR / ".env")

DB_PATH        = BASE_DIR / "database" / "carteira.db"
LOG_PATH       = BASE_DIR / "logs" / "relatorio.log"
PDF_PATH       = BASE_DIR / "logs" / "relatorio.pdf"
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
ALLOWED_CHATID = int(os.getenv("ALLOWED_CHATID", "0"))
API_URL        = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Feeds RSS de notícias do mercado brasileiro
RSS_FEEDS = [
    ("InfoMoney",   "https://www.infomoney.com.br/feed/"),
    ("Valor Ec.",   "https://valor.globo.com/rss/financas"),
    ("Investing",   "https://br.investing.com/rss/news.rss"),
]

# --- LOGGING ------------------------------------------------------------------
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# --- DADOS DO BANCO -----------------------------------------------------------
def get_carteira(cur):
    cur.execute("""
        SELECT ticker, nome, tipo, quantidade, preco_medio,
               preco_atual, variacao_dia, valor_atual,
               lucro_prejuizo, rentabilidade_pct
        FROM carteira_resumo
        WHERE preco_atual IS NOT NULL
        ORDER BY valor_atual DESC
    """)
    return cur.fetchall()

def get_totais(cur):
    cur.execute("""
        SELECT
            SUM(custo_total)            AS total_investido,
            SUM(valor_atual)            AS total_atual,
            SUM(valor_atual)-SUM(custo_total) AS lucro_total
        FROM carteira_resumo
        WHERE preco_atual IS NOT NULL
    """)
    return cur.fetchone()

def get_proventos_semana(cur):
    sete_dias = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    cur.execute("""
        SELECT ticker, tipo, SUM(valor_total) as total
        FROM proventos
        WHERE data >= ?
        GROUP BY ticker, tipo
        ORDER BY total DESC
    """, (sete_dias,))
    return cur.fetchall()

def get_proventos_total(cur):
    cur.execute("SELECT SUM(valor_total) FROM proventos")
    return cur.fetchone()[0] or 0

def get_alertas(cur):
    LIMITE = 5.0
    cur.execute("""
        SELECT ticker, preco_medio, preco_atual, rentabilidade_pct
        FROM carteira_resumo
        WHERE preco_atual IS NOT NULL
          AND (rentabilidade_pct <= ? OR rentabilidade_pct >= ?)
        ORDER BY rentabilidade_pct ASC
    """, (-LIMITE, LIMITE))
    return cur.fetchall()

def get_maiores_variacoes(cur):
    cur.execute("""
        SELECT ticker, variacao_dia, preco_atual
        FROM carteira_resumo
        WHERE variacao_dia IS NOT NULL
        ORDER BY variacao_dia DESC
    """)
    return cur.fetchall()

def get_noticias():
    noticias = []
    for fonte, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                titulo = entry.get("title", "")[:100]
                noticias.append((fonte, titulo))
            if noticias:
                break  # pega só do primeiro feed que funcionar
        except Exception:
            continue
    return noticias[:8]

# --- PDF ----------------------------------------------------------------------
class PDF(FPDF):
    def header(self):
        self.set_fill_color(26, 26, 46)
        self.rect(0, 0, 210, 30, 'F')
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(255, 255, 255)
        self.set_y(8)
        self.cell(0, 10, "Relatorio Semanal de Investimentos", align="C")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(200, 200, 200)
        self.set_y(19)
        self.cell(0, 6, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", align="C")
        self.ln(18)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, "Relatorio informativo. Nao constitui recomendacao de investimento.", align="C")

    def section_title(self, title):
        self.ln(4)
        self.set_fill_color(26, 26, 46)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, f"  {title}", fill=True, ln=True)
        self.ln(2)
        self.set_text_color(0, 0, 0)

    def kpi_row(self, items):
        """Linha de KPIs lado a lado."""
        w = 190 / len(items)
        for label, valor, cor in items:
            self.set_fill_color(*cor)
            self.set_text_color(255, 255, 255)
            self.set_font("Helvetica", "B", 10)
            x = self.get_x()
            y = self.get_y()
            self.rect(x, y, w - 2, 16, 'F')
            self.set_xy(x + 2, y + 1)
            self.cell(w - 4, 5, label, ln=True)
            self.set_xy(x + 2, y + 7)
            self.set_font("Helvetica", "B", 12)
            self.cell(w - 4, 6, valor)
            self.set_xy(x + w, y)
        self.ln(20)
        self.set_text_color(0, 0, 0)


def gerar_pdf(dados: dict) -> Path:
    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(10, 10, 10)

    carteira        = dados["carteira"]
    totais          = dados["totais"]
    proventos_sem   = dados["proventos_semana"]
    proventos_total = dados["proventos_total"]
    alertas         = dados["alertas"]
    variacoes       = dados["variacoes"]
    noticias        = dados["noticias"]

    total_inv, total_atual, lucro = totais
    total_inv   = total_inv   or 0
    total_atual = total_atual or 0
    lucro       = lucro       or 0
    rent_total  = ((total_atual / total_inv) - 1) * 100 if total_inv > 0 else 0

    # -- KPIs principais -------------------------------------------------------
    pdf.section_title("RESUMO DO PATRIMONIO")
    cor_lucro = (39, 174, 96) if lucro >= 0 else (192, 57, 43)
    pdf.kpi_row([
        ("Total Investido",  f"R${total_inv:,.2f}",   (41, 128, 185)),
        ("Valor Atual",      f"R${total_atual:,.2f}",  (142, 68, 173)),
        ("Resultado",        f"R${lucro:+,.2f}",       cor_lucro),
        ("Rentabilidade",    f"{rent_total:+.2f}%",    cor_lucro),
    ])

    # -- Tabela de ativos ------------------------------------------------------
    pdf.section_title("POSICAO ATUAL")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(240, 240, 240)
    cols = [("Ticker", 22), ("Tipo", 16), ("Qtd", 14), ("P.Médio", 24),
            ("Atual", 24), ("Hoje%", 18), ("Total%", 18), ("Valor", 28), ("P&L", 26)]
    for col, w in cols:
        pdf.cell(w, 6, col, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 7.5)
    for i, row in enumerate(carteira):
        ticker, nome, tipo, qtd, pm, preco, var_dia, valor, lp, rent = row
        fill = i % 2 == 0
        pdf.set_fill_color(248, 248, 248) if fill else pdf.set_fill_color(255, 255, 255)

        cor_lp = (39, 174, 96) if (lp or 0) >= 0 else (192, 57, 43)
        var_str  = f"{var_dia:+.1f}%" if var_dia  is not None else ""
        rent_str = f"{rent:+.1f}%"   if rent      is not None else ""
        lp_str   = f"R${lp:+.2f}"   if lp        is not None else ""

        cells = [
            (ticker,           22, "L"),
            (tipo or "",      16, "C"),
            (f"{qtd:.0f}",     14, "C"),
            (f"R${pm:.2f}",    24, "C"),
            (f"R${preco:.2f}", 24, "C"),
            (var_str,          18, "C"),
            (rent_str,         18, "C"),
            (f"R${valor:.2f}", 28, "C"),
            (lp_str,           26, "C"),
        ]
        for j, (txt, w, align) in enumerate(cells):
            if j == 8:
                pdf.set_text_color(*cor_lp)
            pdf.cell(w, 5.5, txt, border=1, fill=fill, align=align)
            pdf.set_text_color(0, 0, 0)
        pdf.ln()

    # -- Maiores variações do dia -----------------------------------------------
    pdf.ln(3)
    pdf.section_title("MAIORES VARIACOES DO DIA")
    altas  = [r for r in variacoes if (r[1] or 0) > 0][:3]
    baixas = [r for r in reversed(variacoes) if (r[1] or 0) < 0][:3]

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(39, 174, 96)
    pdf.cell(95, 6, "  MAIORES ALTAS", ln=False)
    pdf.set_text_color(192, 57, 43)
    pdf.cell(95, 6, "  MAIORES BAIXAS", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)

    max_rows = max(len(altas), len(baixas))
    for i in range(max_rows):
        if i < len(altas):
            t, v, p = altas[i]
            pdf.set_text_color(39, 174, 96)
            pdf.cell(95, 5.5, f"  {t}: R${p:.2f}  ({v:+.2f}%)", ln=False)
        else:
            pdf.cell(95, 5.5, "", ln=False)
        if i < len(baixas):
            t, v, p = baixas[i]
            pdf.set_text_color(192, 57, 43)
            pdf.cell(95, 5.5, f"  {t}: R${p:.2f}  ({v:+.2f}%)", ln=True)
        else:
            pdf.cell(95, 5.5, "", ln=True)
        pdf.set_text_color(0, 0, 0)

    # -- Alertas ---------------------------------------------------------------
    if alertas:
        pdf.ln(3)
        pdf.section_title("ALERTAS DE COMPRA/VENDA (+-5% do PM)")
        pdf.set_font("Helvetica", "", 9)
        for ticker, pm, preco, rent in alertas:
            sinal = ">> COMPRA" if rent <= -5 else ">> VENDA"
            cor   = (39, 174, 96) if rent <= -5 else (192, 57, 43)
            pdf.set_text_color(*cor)
            pdf.cell(0, 5.5,
                f"  {sinal}  {ticker}  |  PM: R${pm:.2f}  ->  Atual: R${preco:.2f}  |  {rent:+.2f}%",
                ln=True)
        pdf.set_text_color(0, 0, 0)

    # -- Proventos -------------------------------------------------------------
    pdf.ln(3)
    pdf.section_title("PROVENTOS")
    pdf.set_font("Helvetica", "", 9)
    if proventos_sem:
        pdf.cell(0, 5, "  Últimos 7 dias:", ln=True)
        for ticker, tipo, total in proventos_sem:
            pdf.cell(0, 5, f"    - {ticker} ({tipo}): R${total:.2f}", ln=True)
    else:
        pdf.cell(0, 5, "  Nenhum provento nos últimos 7 dias.", ln=True)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, f"  Total histórico recebido: R${proventos_total:.2f}", ln=True)

    # -- Notícias --------------------------------------------------------------
    if noticias:
        pdf.ln(3)
        pdf.section_title("NOTICIAS DO MERCADO")
        pdf.set_font("Helvetica", "", 8.5)
        for fonte, titulo in noticias:
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(20, 5, f"  [{fonte}]", ln=False)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 5, titulo)

    pdf.output(str(PDF_PATH))
    return PDF_PATH


# --- TELEGRAM -----------------------------------------------------------------
def send_pdf(pdf_path: Path):
    with open(pdf_path, "rb") as f:
        requests.post(f"{API_URL}/sendDocument", data={
            "chat_id": ALLOWED_CHATID,
            "caption": " Seu relatório semanal está pronto!"
        }, files={"document": f})

def send_msg(text: str):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": ALLOWED_CHATID,
        "text": text,
        "parse_mode": "HTML"
    })

# --- MAIN ---------------------------------------------------------------------
def gerar_e_enviar():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()

        dados = {
            "carteira":        get_carteira(cur),
            "totais":          get_totais(cur),
            "proventos_semana": get_proventos_semana(cur),
            "proventos_total": get_proventos_total(cur),
            "alertas":         get_alertas(cur),
            "variacoes":       get_maiores_variacoes(cur),
            "noticias":        get_noticias(),
        }
        conn.close()

        send_msg(" Gerando seu relatório semanal, aguarde...")
        pdf_path = gerar_pdf(dados)
        send_pdf(pdf_path)
        log.info("Relatório gerado e enviado com sucesso")
        print(" Relatório enviado!")

    except Exception as e:
        log.error(f"Erro ao gerar relatório: {e}")
        send_msg(f" Erro ao gerar relatório: {e}")
        raise

if __name__ == "__main__":
    gerar_e_enviar()
