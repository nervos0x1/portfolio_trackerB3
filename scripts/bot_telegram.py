#!/usr/bin/env python3
"""
bot_telegram.py
Bot do Telegram para consultar e atualizar carteira de investimentos.
Uso: python3 bot_telegram.py
"""

import os
import sqlite3
import logging
import requests
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from relatorio import gerar_e_enviar

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path("/mnt/external/portfolio_tracker")
load_dotenv(BASE_DIR / ".env")

DB_PATH        = BASE_DIR / "database" / "carteira.db"
LOG_PATH       = BASE_DIR / "logs" / "bot.log"
XLSX_PATH      = BASE_DIR / "movimentacao.xlsx"
IMPORT_SCRIPT  = BASE_DIR / "scripts" / "importar_carteira.py"
BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
ALLOWED_CHATID = int(os.getenv("ALLOWED_CHATID", "0"))
API_URL        = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send(chat_id: int, text: str):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    })

def get_updates(offset: int = 0):
    try:
        resp = requests.get(f"{API_URL}/getUpdates", params={
            "offset": offset,
            "timeout": 30
        }, timeout=35)
        return resp.json().get("result", [])
    except Exception as e:
        log.error(f"Erro getUpdates: {e}")
        return []

def download_file(file_id: str, dest_path: Path) -> bool:
    """Baixa um arquivo do Telegram e salva localmente."""
    try:
        # Pega o caminho do arquivo no servidor do Telegram
        resp = requests.get(f"{API_URL}/getFile", params={"file_id": file_id})
        file_path = resp.json()["result"]["file_path"]

        # Faz o download
        url  = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        data = requests.get(url, timeout=30)

        with open(dest_path, "wb") as f:
            f.write(data.content)
        return True
    except Exception as e:
        log.error(f"Erro ao baixar arquivo: {e}")
        return False

# ─── BANCO ────────────────────────────────────────────────────────────────────
def get_db():
    return sqlite3.connect(DB_PATH)

# ─── COMANDOS ─────────────────────────────────────────────────────────────────
def cmd_start(chat_id):
    send(chat_id, (
        "👋 Olá! Sou o <b>ZezinhoRico</b> 🤑\n\n"
        "Comandos disponíveis:\n\n"
        "/carteira — resumo completo da carteira\n"
        "/cotacao TICKER — cotação de um ativo\n"
        "/proventos — total de proventos recebidos\n"
        "/resumo — patrimônio total e rentabilidade\n"
        "/alerta — análise de compra/venda vs preço médio\n"
        "/relatorio — gera PDF com resumo semanal da carteira\n"
        "/resultado — lucro/prejuizo realizado e proventos por ativo\n"
        "/ajuda — lista de comandos\n\n"
        "📎 Para atualizar a carteira, envie o arquivo <b>.xlsx</b> da B3 direto aqui no chat!"
    ))

def cmd_carteira(chat_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT ticker, tipo, quantidade, preco_medio, preco_atual,
               variacao_dia, variacao_valor, valor_atual, lucro_prejuizo, rentabilidade_pct, cotacao_em
        FROM carteira_resumo
        ORDER BY valor_atual DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        send(chat_id, "⚠️ Nenhum ativo encontrado na carteira.")
        return

    total_custo = 0.0
    total_atual = 0.0
    linhas      = []
    sem_cotacao = []

    for ticker, tipo, qtd, pm, preco_atual, var_dia, var_val, valor_atual, lp, rent, cotacao_em in rows:
        if preco_atual is None:
            sem_cotacao.append(ticker)
            continue

        sinal    = "🟢" if (lp or 0) >= 0 else "🔴"
        var_str  = f"{var_dia:+.2f}%" if var_dia is not None else "—"
        rent_str = f"{rent:+.2f}%" if rent is not None else "—"
        lp_str   = f"R${lp:+.2f}" if lp is not None else "—"

        linhas.append(
            f"{sinal} <b>{ticker}</b> ({tipo})\n"
            f"   Qtd: {qtd:.0f} | PM: R${pm:.2f} | Atual: R${preco_atual:.2f}\n"
            f"   Hoje: {var_str} | Total: {rent_str} ({lp_str})\n"
            f"   Valor: R${valor_atual:.2f}"
        )
        total_custo += pm * qtd
        total_atual += valor_atual or 0

    total_lp   = total_atual - total_custo
    total_rent = ((total_atual / total_custo) - 1) * 100 if total_custo > 0 else 0
    sinal_tot  = "🟢" if total_lp >= 0 else "🔴"

    msg  = "📊 <b>Carteira</b>\n\n"
    msg += "\n\n".join(linhas)
    msg += f"\n\n{'─'*25}\n"
    msg += f"{sinal_tot} <b>Total investido:</b> R${total_custo:.2f}\n"
    msg += f"{sinal_tot} <b>Valor atual:</b> R${total_atual:.2f}\n"
    msg += f"{sinal_tot} <b>Resultado:</b> R${total_lp:+.2f} ({total_rent:+.2f}%)"

    if sem_cotacao:
        msg += f"\n\n⚠️ Sem cotação: {', '.join(sem_cotacao)}"

    send(chat_id, msg)

def cmd_cotacao(chat_id, ticker: str):
    ticker = ticker.upper().strip()
    conn   = get_db()
    cur    = conn.cursor()

    cur.execute("""
        SELECT ticker, nome, tipo, quantidade, preco_medio, preco_atual,
               variacao_dia, variacao_valor, valor_atual, lucro_prejuizo,
               rentabilidade_pct, cotacao_em
        FROM carteira_resumo
        WHERE ticker = ?
    """, (ticker,))
    row = cur.fetchone()

    if not row:
        cur.execute("SELECT ticker, nome, tipo FROM acoes WHERE ticker = ?", (ticker,))
        ativo = cur.fetchone()
        conn.close()
        if ativo:
            send(chat_id, f"⚠️ <b>{ticker}</b> está na carteira mas sem posição ativa ou sem cotação.")
        else:
            send(chat_id, f"❌ Ticker <b>{ticker}</b> não encontrado na carteira.")
        return

    conn.close()
    ticker, nome, tipo, qtd, pm, preco_atual, var_dia, var_val, valor_atual, lp, rent, cotacao_em = row

    sinal   = "🟢" if (lp or 0) >= 0 else "🔴"
    var_str = f"{var_dia:+.2f}%" if var_dia is not None else "—"

    msg = (
        f"{sinal} <b>{ticker}</b> — {nome}\n"
        f"Tipo: {tipo}\n\n"
        f"💰 Preço atual: <b>R${preco_atual:.2f}</b>\n"
        f"📈 Variação hoje: {var_str} (R${var_val:+.2f})\n\n"
        f"📦 Quantidade: {qtd:.0f}\n"
        f"📉 Preço médio: R${pm:.2f}\n"
        f"💼 Valor na carteira: R${valor_atual:.2f}\n"
        f"{'📈' if (lp or 0) >= 0 else '📉'} Resultado: R${lp:+.2f} ({rent:+.2f}%)\n\n"
        f"🕐 Cotação em: {cotacao_em}"
    )
    send(chat_id, msg)

def cmd_proventos(chat_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT ticker, tipo, SUM(valor_total) as total, COUNT(*) as n
        FROM proventos
        GROUP BY ticker, tipo
        ORDER BY total DESC
    """)
    rows = cur.fetchall()

    cur.execute("SELECT SUM(valor_total) FROM proventos")
    total_geral = cur.fetchone()[0] or 0
    conn.close()

    if not rows:
        send(chat_id, "⚠️ Nenhum provento registrado.")
        return

    linhas = []
    for ticker, tipo, total, n in rows:
        linhas.append(f"  <b>{ticker}</b> ({tipo}): R${total:.2f} ({n}x)")

    msg  = "💰 <b>Proventos recebidos</b>\n\n"
    msg += "\n".join(linhas)
    msg += f"\n\n{'─'*25}\n"
    msg += f"<b>Total geral: R${total_geral:.2f}</b>"
    send(chat_id, msg)

def cmd_resumo(chat_id):
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT tipo, COUNT(*) as qtd, SUM(custo_total) as custo, SUM(valor_atual) as atual
        FROM carteira_resumo
        GROUP BY tipo
        ORDER BY atual DESC
    """)
    rows = cur.fetchall()

    cur.execute("SELECT SUM(valor_total) FROM proventos")
    total_proventos = cur.fetchone()[0] or 0
    conn.close()

    if not rows:
        send(chat_id, "⚠️ Nenhum dado disponível.")
        return

    total_custo = 0.0
    total_atual = 0.0
    linhas      = []

    for tipo, qtd, custo, atual in rows:
        if atual is None:
            continue
        lp    = atual - custo
        rent  = ((atual / custo) - 1) * 100 if custo > 0 else 0
        sinal = "🟢" if lp >= 0 else "🔴"
        linhas.append(
            f"{sinal} <b>{tipo}</b> ({qtd} ativo{'s' if qtd > 1 else ''})\n"
            f"   Investido: R${custo:.2f} | Atual: R${atual:.2f}\n"
            f"   Resultado: R${lp:+.2f} ({rent:+.2f}%)"
        )
        total_custo += custo
        total_atual += atual

    total_lp   = total_atual - total_custo
    total_rent = ((total_atual / total_custo) - 1) * 100 if total_custo > 0 else 0
    sinal_tot  = "🟢" if total_lp >= 0 else "🔴"

    msg  = "📊 <b>Resumo da Carteira</b>\n\n"
    msg += "\n\n".join(linhas)
    msg += f"\n\n{'─'*25}\n"
    msg += f"{sinal_tot} <b>Total investido:</b> R${total_custo:.2f}\n"
    msg += f"{sinal_tot} <b>Patrimônio atual:</b> R${total_atual:.2f}\n"
    msg += f"{sinal_tot} <b>Resultado:</b> R${total_lp:+.2f} ({total_rent:+.2f}%)\n"
    msg += f"💰 <b>Proventos recebidos:</b> R${total_proventos:.2f}\n"
    msg += f"🏆 <b>Retorno total (c/ proventos):</b> R${(total_lp + total_proventos):+.2f}"
    send(chat_id, msg)

def cmd_alerta(chat_id):
    LIMITE_PCT = 5.0
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT ticker, tipo, quantidade, preco_medio, preco_atual,
               rentabilidade_pct, valor_atual, lucro_prejuizo
        FROM carteira_resumo
        WHERE preco_atual IS NOT NULL
        ORDER BY rentabilidade_pct ASC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        send(chat_id, "⚠️ Nenhum ativo com cotação disponível.")
        return

    compras = []
    vendas  = []
    neutros = []

    for ticker, tipo, qtd, pm, preco_atual, rent, valor_atual, lp in rows:
        if rent is None:
            continue
        if rent <= -LIMITE_PCT:
            compras.append((ticker, tipo, qtd, pm, preco_atual, rent, lp))
        elif rent >= LIMITE_PCT:
            vendas.append((ticker, tipo, qtd, pm, preco_atual, rent, lp))
        else:
            neutros.append((ticker, tipo, qtd, pm, preco_atual, rent, lp))

    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg   = f"📊 <b>Análise da Carteira</b> — {agora}\n"
    msg  += f"Limite: variação &gt; {LIMITE_PCT}% do preço médio\n"
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
            msg += f"  <b>{ticker}</b>: R${preco:.2f} ({var:+.2f}%)\n"

    msg += f"\n⚠️ <i>Análise informativa. Não é recomendação de investimento.</i>"
    send(chat_id, msg)


def cmd_resultado(chat_id):
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
            a.ticker,
            a.nome,
            a.tipo,
            a.custo_total,
            a.quantidade,
            (SELECT SUM(m.quantidade * m.preco_unitario)
             FROM movimentacoes m
             WHERE m.ticker = a.ticker AND m.tipo = 'COMPRA') AS total_comprado,
            (SELECT SUM(m.quantidade * m.preco_unitario)
             FROM movimentacoes m
             WHERE m.ticker = a.ticker AND m.tipo IN ('VENDA','RESGATE')) AS total_vendido,
            (SELECT COALESCE(SUM(p.valor_total), 0)
             FROM proventos p
             WHERE p.ticker = a.ticker) AS total_proventos
        FROM acoes a
        ORDER BY a.ativo DESC, a.ticker ASC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        send(chat_id, "Nenhum ativo encontrado.")
        return

    ativos_ativos   = []
    ativos_vendidos = []

    for ticker, nome, tipo, custo_atual, qtd_atual, total_comprado, total_vendido, proventos in rows:
        total_comprado = total_comprado or 0
        total_vendido  = total_vendido  or 0
        proventos      = proventos      or 0
        custo_atual    = custo_atual    or 0
        qtd_atual      = qtd_atual      or 0

        if qtd_atual > 0:
            ativos_ativos.append((ticker, tipo, qtd_atual, custo_atual, proventos))
        else:
            lp_realizado = total_vendido - total_comprado
            ativos_vendidos.append((ticker, tipo, total_comprado, total_vendido, lp_realizado, proventos))

    msg = "\U0001f4ca <b>Resultado por Ativo</b>\n\n"

    if ativos_vendidos:
        msg += "\U0001f3c1 <b>Ativos Encerrados</b>\n\n"
        total_lp_realizado  = 0
        total_prov_vendidos = 0
        for ticker, tipo, comprado, vendido, lp, proventos in ativos_vendidos:
            sinal = "\U0001f7e2" if lp >= 0 else "\U0001f534"
            msg += (
                f"{sinal} <b>{ticker}</b> ({tipo})\n"
                f"   Investido: R${comprado:.2f}\n"
                f"   Recebido na venda: R${vendido:.2f}\n"
                f"   Resultado venda: R${lp:+.2f}\n"
                f"   Proventos recebidos: R${proventos:.2f}\n"
                f"   Resultado total: R${(lp + proventos):+.2f}\n\n"
            )
            total_lp_realizado  += lp
            total_prov_vendidos += proventos

        msg += (
            f"{'─'*25}\n"
            f"Total realizado (vendas): R${total_lp_realizado:+.2f}\n"
            f"Total proventos (encerrados): R${total_prov_vendidos:.2f}\n"
            f"Subtotal encerrados: R${(total_lp_realizado + total_prov_vendidos):+.2f}\n\n"
        )

    if ativos_ativos:
        msg += "\U0001f4b0 <b>Proventos -- Ativos em Carteira</b>\n\n"
        total_prov_ativos = 0
        for ticker, tipo, qtd, custo, proventos in ativos_ativos:
            if proventos > 0:
                msg += f"  <b>{ticker}</b>: R${proventos:.2f}\n"
                total_prov_ativos += proventos
        if total_prov_ativos == 0:
            msg += "  Nenhum provento registrado ainda.\n"
        else:
            msg += f"\n  Total proventos (carteira ativa): R${total_prov_ativos:.2f}\n"

    total_lp_r = sum(r[4] for r in ativos_vendidos) if ativos_vendidos else 0
    total_prov = (sum(r[5] for r in ativos_vendidos) if ativos_vendidos else 0) + (sum(r[4] for r in ativos_ativos) if ativos_ativos else 0)
    resultado_total = total_lp_r + total_prov
    sinal = "\U0001f7e2" if resultado_total >= 0 else "\U0001f534"

    msg += (
        f"\n{'─'*25}\n"
        f"{sinal} <b>Resultado realizado (vendas):</b> R${total_lp_r:+.2f}\n"
        f"\U0001f4b0 <b>Total proventos (historico):</b> R${total_prov:.2f}\n"
        f"{sinal} <b>Resultado total consolidado:</b> R${resultado_total:+.2f}\n\n"
        f"<i>Nao inclui resultado nao realizado dos ativos em carteira.</i>"
    )

    send(chat_id, msg)


def cmd_ajuda(chat_id):
    send(chat_id, (
        "📋 <b>Comandos disponíveis</b>\n\n"
        "/carteira — lista todos os ativos com cotação atual\n"
        "/cotacao TICKER — cotação detalhada de um ativo\n"
        "   ex: /cotacao ITUB4\n"
        "/proventos — dividendos e rendimentos recebidos\n"
        "/resumo — patrimônio total por tipo de ativo\n"
        "/alerta — análise de compra/venda vs preço médio\n"
        "/relatorio — gera PDF com resumo semanal\n"
        "/resultado — lucro/prejuizo realizado e proventos por ativo\n"
        "/ajuda — esta mensagem\n\n"
        "📎 <b>Atualizar carteira:</b> envie o arquivo .xlsx da B3 direto aqui no chat!"
    ))

def handle_documento(chat_id, document: dict):
    """Recebe .xlsx enviado no chat e reimporta a carteira."""
    nome_arquivo = document.get("file_name", "")

    if not nome_arquivo.endswith(".xlsx"):
        send(chat_id, "❌ Envie um arquivo <b>.xlsx</b> exportado da B3.")
        return

    send(chat_id, "📥 Arquivo recebido! Atualizando carteira, aguarde...")

    # Baixa o arquivo
    ok = download_file(document["file_id"], XLSX_PATH)
    if not ok:
        send(chat_id, "❌ Erro ao baixar o arquivo. Tente novamente.")
        return

    # Roda o script de importação
    try:
        resultado = subprocess.run(
            ["python3", str(IMPORT_SCRIPT), str(XLSX_PATH)],
            capture_output=True,
            text=True,
            timeout=120
        )
        saida = resultado.stdout.strip()
        erro  = resultado.stderr.strip()

        if resultado.returncode != 0:
            log.error(f"Erro na importação: {erro}")
            send(chat_id, f"❌ Erro na importação:\n<code>{erro[-500:]}</code>")
            return

        # Pega o resumo do banco após importação
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(custo_total) FROM acoes WHERE ativo=1 AND quantidade > 0")
        qtd_ativos, total_investido = cur.fetchone()
        conn.close()

        msg = (
            f"✅ <b>Carteira atualizada!</b>\n\n"
            f"📦 {qtd_ativos} ativos na carteira\n"
            f"💰 Total investido: R${total_investido:.2f}\n\n"
            f"Use /carteira para ver o resumo completo."
        )
        send(chat_id, msg)
        log.info(f"Carteira atualizada via Telegram — {qtd_ativos} ativos, R${total_investido:.2f}")

    except subprocess.TimeoutExpired:
        send(chat_id, "❌ A importação demorou demais. Tente novamente.")
    except Exception as e:
        log.error(f"Erro inesperado na importação: {e}")
        send(chat_id, f"❌ Erro inesperado: {e}")

# ─── LOOP PRINCIPAL ───────────────────────────────────────────────────────────
def main():
    log.info("Bot iniciado")
    print("🤖 ZezinhoRico bot iniciado! Aguardando mensagens...")

    offset = 0
    while True:
        updates = get_updates(offset)

        for update in updates:
            offset  = update["update_id"] + 1
            msg     = update.get("message", {})
            chat    = msg.get("chat", {})
            chat_id = chat.get("id")
            text    = msg.get("text", "").strip()
            document = msg.get("document")

            if not chat_id:
                continue

            # Segurança: só você pode usar
            if chat_id != ALLOWED_CHATID:
                log.warning(f"Acesso negado para chat_id {chat_id}")
                send(chat_id, "⛔ Acesso não autorizado.")
                continue

            # Recebeu um arquivo
            if document:
                handle_documento(chat_id, document)
                continue

            if not text:
                continue

            log.info(f"Comando recebido: {text}")

            partes  = text.split()
            comando = partes[0].lower()

            if comando in ("/start", "/inicio"):
                cmd_start(chat_id)
            elif comando == "/carteira":
                cmd_carteira(chat_id)
            elif comando == "/cotacao":
                if len(partes) < 2:
                    send(chat_id, "❌ Informe o ticker. Ex: /cotacao ITUB4")
                else:
                    cmd_cotacao(chat_id, partes[1])
            elif comando == "/proventos":
                cmd_proventos(chat_id)
            elif comando == "/resumo":
                cmd_resumo(chat_id)
            elif comando == "/alerta":
                cmd_alerta(chat_id)
            elif comando == "/relatorio":
                gerar_e_enviar()
            elif comando == "/resultado":
                cmd_resultado(chat_id)
            elif comando in ("/ajuda", "/help"):
                cmd_ajuda(chat_id)
            else:
                send(chat_id, "❓ Comando não reconhecido. Use /ajuda para ver os comandos disponíveis.")

if __name__ == "__main__":
    main()
