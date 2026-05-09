#!/usr/bin/env python3
"""
importar_carteira.py
Lê o Excel de movimentações da B3 e popula o banco SQLite.
Sempre faz replace completo — sem duplicatas.
Uso: python3 importar_carteira.py movimentacao.xlsx
"""

import sys
import re
import sqlite3
import pandas as pd
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path("/mnt/external/portfolio_tracker")
DB_PATH  = BASE_DIR / "database" / "carteira.db"

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def classificar_tipo(ticker: str) -> str:
    etfs_conhecidos = {
        "IVVB11", "ACWI11", "NASD11", "BOVA11", "SMAL11",
        "HASH11", "GOLD11", "SPXI11", "QBTC11", "DIVO11"
    }
    t = ticker.upper()
    if t in etfs_conhecidos:
        return "ETF"
    if t.endswith("11"):
        return "FII"
    if re.search(r'\d{2}$', t):
        return "BDR"
    return "ACAO"

def classificar_mov(descricao: str, entrada_saida: str, preco: float) -> str:
    """
    Classifica a movimentação com base na descrição, direção e presença de preço.

    Regra chave: Transferência - Liquidação ou Compra com preço > 0
      - Credito  → COMPRA
      - Debito   → VENDA

    Movimentações sem preço (empréstimo, transferência simples) são ignoradas.
    """
    d   = descricao.strip().upper()
    tem_preco = preco > 0

    # Compra / venda com liquidação financeira (tem preço)
    if ("TRANSFERÊNCIA - LIQUIDAÇÃO" in d or
        "TRANSFERENCIA - LIQUIDACAO" in d or
        "COMPRA" in d or
        "COMPRA / VENDA" in d):
        if not tem_preco:
            return "IGNORAR"   # empréstimo, transferência sem valor financeiro
        return "COMPRA" if entrada_saida == "Credito" else "VENDA"

    if "VENDA" in d and tem_preco:
        return "VENDA"

    # Resgate = liquidação de FII encerrado (zera posição)
    if "RESGATE" in d:
        return "RESGATE"

    # Proventos
    if "JUROS SOBRE CAPITAL" in d or "JCP" in d:
        return "JCP"
    if "DIVIDENDO" in d:
        return "DIVIDENDO"
    if "RENDIMENTO" in d:
        return "RENDIMENTO"

    # Eventos corporativos
    if "BONIFICAÇÃO" in d or "BONIFICACAO" in d or "BONIFICAÇÃO EM ATIVOS" in d:
        return "BONIFICACAO"
    if "SUBSCRIÇÃO" in d or "SUBSCRICAO" in d or "DIREITO DE SUBSCRI" in d:
        return "SUBSCRICAO"
    if "LEILÃO DE FRAÇÃO" in d or "LEILAO DE FRACAO" in d or "FRAÇÃO EM ATIVOS" in d or "FRACAO EM ATIVOS" in d:
        return "FRACAO"

    # Ignorados (não afetam posição)
    return "IGNORAR"

def extrair_ticker(produto: str) -> str | None:
    match = re.match(r'^([A-Z]{4}\d{1,2}[A-Z]?)', str(produto).strip())
    return match.group(1) if match else None

def extrair_nome(produto: str) -> str:
    parts = str(produto).strip().split(" - ", 1)
    return parts[1].strip() if len(parts) > 1 else produto.strip()

def to_float(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 importar_carteira.py <arquivo.xlsx>")
        sys.exit(1)

    xlsx_path = Path(sys.argv[1])
    if not xlsx_path.exists():
        print(f"❌ Arquivo não encontrado: {xlsx_path}")
        sys.exit(1)

    print(f"📂 Lendo {xlsx_path.name}...")
    df = pd.read_excel(xlsx_path)
    df.columns = [
        "entrada_saida", "data", "movimentacao", "produto",
        "instituicao", "quantidade", "preco_unitario", "valor_operacao"
    ]

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    # ── REPLACE SEGURO: preserva cotacoes e alertas ───────────────────────────
    print("Limpando movimentacoes e posicoes anteriores...")
    cur.execute("PRAGMA foreign_keys = OFF")
    cur.execute("DELETE FROM movimentacoes")
    cur.execute("DELETE FROM proventos")
    cur.execute("DELETE FROM acoes")
    cur.execute("PRAGMA foreign_keys = ON")
    conn.commit()

    # ── PROCESSAR LINHAS ──────────────────────────────────────────────────────
    movs      = []
    proventos = []
    tickers   = {}  # ticker -> (nome, tipo)
    ignoradas = 0

    for _, row in df.iterrows():
        ticker = extrair_ticker(str(row["produto"]))
        if not ticker:
            continue  # Tesouro, CDB, etc — ignora

        nome          = extrair_nome(str(row["produto"]))
        entrada_saida = str(row["entrada_saida"]).strip()
        descricao     = str(row["movimentacao"]).strip()
        qtd           = to_float(row["quantidade"])
        preco         = to_float(row["preco_unitario"])
        valor         = to_float(row["valor_operacao"])
        instituicao   = str(row["instituicao"]).strip()
        tipo_mov      = classificar_mov(descricao, entrada_saida, preco)

        if tipo_mov == "IGNORAR":
            ignoradas += 1
            continue

        try:
            data_str = pd.to_datetime(row["data"], dayfirst=True).strftime("%Y-%m-%d")
        except Exception:
            data_str = str(row["data"])

        tickers[ticker] = (nome, classificar_tipo(ticker))

        movs.append((
            ticker, data_str, tipo_mov, entrada_saida,
            qtd, preco, valor, instituicao, descricao
        ))

    # ── INSERIR ATIVOS ────────────────────────────────────────────────────────
    for ticker, (nome, tipo) in tickers.items():
        cur.execute("""
            INSERT OR IGNORE INTO acoes (ticker, nome, tipo) VALUES (?, ?, ?)
        """, (ticker, nome, tipo))

    # ── INSERIR MOVIMENTACOES ─────────────────────────────────────────────────
    cur.executemany("""
        INSERT INTO movimentacoes
            (ticker, data, tipo, entrada_saida, quantidade, preco_unitario,
             valor_total, instituicao, descricao_original)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, movs)

    conn.commit()
    print(f"✅ {len(movs)} movimentações importadas | {ignoradas} ignoradas (sem valor financeiro)")
    print(f"   {len(tickers)} ativos encontrados")

    # ── CALCULAR POSIÇÃO ATUAL ────────────────────────────────────────────────
    print("\n📊 Calculando posição atual (preço médio ponderado)...")

    for ticker in sorted(tickers):
        cur.execute("""
            SELECT tipo, entrada_saida, quantidade, preco_unitario, valor_total, data, instituicao
            FROM movimentacoes
            WHERE ticker = ?
            ORDER BY data ASC
        """, (ticker,))
        rows = cur.fetchall()

        qtd_atual       = 0.0
        custo_total     = 0.0
        primeira_compra = None
        ultima_atualiz  = None

        for tipo_mov, entrada_saida, qtd, preco, valor, data, inst in rows:

            if tipo_mov == "COMPRA":
                custo_total     += qtd * preco
                qtd_atual       += qtd
                primeira_compra  = primeira_compra or data
                ultima_atualiz   = data

            elif tipo_mov == "VENDA":
                if qtd_atual > 0:
                    pm           = custo_total / qtd_atual
                    custo_total -= qtd * pm
                    qtd_atual   -= qtd
                    if qtd_atual < 0.001:
                        qtd_atual   = 0.0
                        custo_total = 0.0
                ultima_atualiz = data

            elif tipo_mov == "RESGATE":
                # Encerramento total do ativo (FII liquidado, etc)
                qtd_atual   = 0.0
                custo_total = 0.0
                ultima_atualiz = data

            elif tipo_mov == "BONIFICACAO":
                # Aumenta quantidade sem alterar custo (preco medio cai)
                qtd_atual      += qtd
                ultima_atualiz  = data

            elif tipo_mov == "FRACAO":
                # Debito = saida da fracao do saldo
                # Credito = leilao da fracao (entrada financeira, nao muda posicao)
                if entrada_saida == "Debito":
                    qtd_atual -= qtd
                    if qtd_atual < 0.001:
                        qtd_atual   = 0.0
                        custo_total = 0.0
                ultima_atualiz = data

            elif tipo_mov in ("JCP", "DIVIDENDO", "RENDIMENTO"):
                proventos.append((ticker, data, tipo_mov, qtd_atual, preco, valor, inst))

        preco_medio = (custo_total / qtd_atual) if qtd_atual > 0.001 else 0.0
        ativo       = 1 if qtd_atual > 0.001 else 0

        cur.execute("""
            UPDATE acoes SET
                quantidade         = ?,
                preco_medio        = ?,
                custo_total        = ?,
                primeira_compra    = ?,
                ultima_atualizacao = ?,
                ativo              = ?
            WHERE ticker = ?
        """, (
            round(qtd_atual,   4),
            round(preco_medio, 4),
            round(custo_total, 2),
            primeira_compra,
            ultima_atualiz,
            ativo,
            ticker
        ))

    # ── INSERIR PROVENTOS ─────────────────────────────────────────────────────
    cur.executemany("""
        INSERT INTO proventos
            (ticker, data, tipo, quantidade, valor_por_cota, valor_total, instituicao)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, proventos)

    conn.commit()

    # ── RELATÓRIO FINAL ───────────────────────────────────────────────────────
    cur.execute("""
        SELECT ticker, nome, tipo, quantidade, preco_medio, custo_total
        FROM acoes
        WHERE ativo = 1 AND quantidade > 0
        ORDER BY custo_total DESC
    """)
    posicao = cur.fetchall()

    print(f"\n{'Ticker':<10} {'Tipo':<6} {'Qtd':>8} {'P.Médio':>10} {'Custo Total':>12}")
    print("─" * 52)
    total = 0.0
    for ticker, nome, tipo, qtd, pm, custo in posicao:
        print(f"{ticker:<10} {tipo:<6} {qtd:>8.0f} {pm:>10.2f} {custo:>12.2f}")
        total += custo
    print("─" * 52)
    print(f"{'TOTAL INVESTIDO':>36} {total:>12.2f}")

    # Ativos zerados (vendidos/resgatados)
    cur.execute("""
        SELECT ticker FROM acoes WHERE ativo = 0 OR quantidade = 0
    """)
    zerados = [r[0] for r in cur.fetchall()]
    if zerados:
        print(f"\n⬜ Zerados/vendidos: {', '.join(zerados)}")

    cur.execute("SELECT COUNT(*) FROM proventos")
    print(f"\n💰 {cur.fetchone()[0]} registros de proventos salvos")

    conn.close()
    print("\n✅ Importação concluída! Para atualizar: substitua o .xlsx e rode novamente.")

if __name__ == "__main__":
    main()
