import time
import requests
import numpy as np
import os
import threading
import psycopg2

from flask import Flask, render_template_string, redirect
from datetime import datetime


# ==============================================================================
# CONFIGURAÇÕES DA API
# ==============================================================================

API_URL = "https://22885.club/api/webapi/GetNoaverageEmerdList"

API_HEADERS = {
    "accept": "application/json, text/plain, */*",

    # ============================================================
    # COLOQUE SEU TOKEN COMPLETO AQUI
    # ============================================================
    "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",

    "content-type": "application/json;charset=UTF-8",
    "origin": "https://popbra66.com",
    "referer": "https://popbra66.com/",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64)"
}


# ==============================================================================
# GESTÃO FINANCEIRA
# ==============================================================================

VALOR_BASE = 1.0

# Vitória normal = +R$ 1,00
LUCRO_BASE = 1.0

# Vitória Violet (0 ou 5) = +R$ 0,50
LUCRO_BASE_VIOLET = 0.5

# Derrota = -R$ 1,00
PREJUIZO_DERROTA = 1.0


# ==============================================================================
# CONFIGURAÇÃO DA V3
# ==============================================================================

# Quantidade mínima de estratégias concordando
MIN_CONFLUENCIA = 1

# Existem 5 estratégias.
TOTAL_ESTRATEGIAS = 1


# ==============================================================================
# VARIÁVEIS GLOBAIS DE MEMÓRIA
# ==============================================================================

history_numbers = []
history_colors = []

processed_issues = set()

history_results = []


# ==============================================================================
# ESTADO DO BOT
# ==============================================================================

bot_state = "PARADO"

signal_color = None

# Controle manual
bot_running = False

# Lock para evitar conflitos entre Flask e thread
bot_lock = threading.Lock()


# ==============================================================================
# CONTADORES DA SESSÃO ATUAL
# ==============================================================================

wins = 0
wins_05 = 0
wins_10 = 0
losses = 0

current_profit = 0.0


# ==============================================================================
# LOGS
# ==============================================================================

log_lines = []


# ==============================================================================
# BANCO DE DADOS POSTGRESQL
# ==============================================================================

def get_db_connection():

    try:

        database_url = os.environ.get("DATABASE_URL")

        if not database_url:
            return None

        return psycopg2.connect(database_url)

    except Exception:

        return None


# ==============================================================================
# INICIALIZAÇÃO DO BANCO
# ==============================================================================

def init_db():

    conn = get_db_connection()

    if not conn:

        add_log("⚠️ Banco de dados não configurado.")

        return

    try:

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS historico (
                    issue TEXT PRIMARY KEY,
                    cor TEXT,
                    numero INTEGER,
                    acao TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS placar (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    wins INTEGER DEFAULT 0,
                    wins_05 INTEGER DEFAULT 0,
                    wins_10 INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    profit REAL DEFAULT 0.0
                );
            """)

            cur.execute("""
                INSERT INTO placar
                (id, wins, wins_05, wins_10, losses, profit)
                VALUES
                (1, 0, 0, 0, 0, 0.0)
                ON CONFLICT (id) DO NOTHING;
            """)

            conn.commit()

        conn.close()

        add_log("🗄️ Banco de dados inicializado.")

    except Exception as e:

        add_log(
            f"⚠️ Erro ao inicializar banco: {e}"
        )


# ==============================================================================
# ATUALIZA PLACAR NO BANCO
# ==============================================================================

def update_placar_in_db():

    conn = get_db_connection()

    if not conn:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""
                UPDATE placar
                SET
                    wins = %s,
                    wins_05 = %s,
                    wins_10 = %s,
                    losses = %s,
                    profit = %s
                WHERE id = 1;
            """, (
                wins,
                wins_05,
                wins_10,
                losses,
                current_profit
            ))

            conn.commit()

        conn.close()

    except Exception as e:

        add_log(
            f"⚠️ Erro ao atualizar placar: {e}"
        )


# ==============================================================================
# SALVA JOGO NO BANCO
# ==============================================================================

def save_game_to_db(issue, cor, numero, acao):

    conn = get_db_connection()

    if not conn:
        return

    try:

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO historico
                (issue, cor, numero, acao)
                VALUES (%s, %s, %s, %s)

                ON CONFLICT (issue) DO NOTHING;
            """, (
                issue,
                cor,
                numero,
                acao
            ))

            conn.commit()

        conn.close()

    except Exception as e:

        add_log(
            f"⚠️ Erro ao salvar histórico: {e}"
        )


# ==============================================================================
# SISTEMA DE LOG
# ==============================================================================

def add_log(msg):

    timestamp = datetime.now().strftime("%H:%M:%S")

    log_lines.append(
        f"[{timestamp}] {msg}"
    )

    if len(log_lines) > 50:

        log_lines.pop(0)


# ==============================================================================
# INICIAR NOVA SESSÃO
# ==============================================================================

def start_bot():

    global bot_running
    global wins
    global wins_05
    global wins_10
    global losses
    global current_profit
    global bot_state
    global signal_color
    global history_results

    with bot_lock:

        wins = 0
        wins_05 = 0
        wins_10 = 0
        losses = 0

        current_profit = 0.0

        bot_state = "CACANDO"

        signal_color = None

        history_results = []

        bot_running = True

        add_log("")
        add_log("==========================================")
        add_log("🟢 BOT INICIADO MANUALMENTE")
        add_log("💰 NOVA SESSÃO FINANCEIRA")
        add_log("📊 PLACAR ZERADO")
        add_log("==========================================")

        update_placar_in_db()


# ==============================================================================
# PARAR BOT
# ==============================================================================

def stop_bot():

    global bot_running
    global bot_state
    global signal_color

    with bot_lock:

        bot_running = False

        bot_state = "PARADO"

        signal_color = None

        add_log("")
        add_log("==========================================")
        add_log("🔴 BOT PARADO MANUALMENTE")
        add_log(
            f"💰 SALDO FINAL DA SESSÃO: "
            f"R$ {current_profit:.2f}"
        )
        add_log("📊 RESULTADO CONGELADO")
        add_log("==========================================")


# ==============================================================================
# BUSCA RESULTADOS DA API
# ==============================================================================

def fetch_latest_results():

    payload = {
        "pageSize": 10,
        "pageNo": 1,
        "typeId": 1,
        "language": 3,
        "random": "2535e29e3dc5441cafefdeb3fe4a7c82",
        "signature": "4BB11F00CC6485FA05174CE313B6EE1B",
        "timestamp": int(time.time())
    }

    try:

        response = requests.post(
            API_URL,
            headers=API_HEADERS,
            json=payload,
            timeout=8
        )

        if response.status_code == 200:

            data = response.json()

            if (
                "data" in data
                and
                "list" in data["data"]
            ):

                return data["data"]["list"]

            elif "list" in data:

                return data["list"]

        return []

    except Exception:

        return []


# ==============================================================================
# NORMALIZA COR
# ==============================================================================

def normalize_color(c, num=None):

    if num is not None:

        if num == 0:
            return "V"

        if num == 5:
            return "V"

        if num % 2 == 0:
            return "R"

        return "G"

    c = str(c).lower()

    if "violet" in c:
        return "V"

    if "red" in c:
        return "R"

    if "green" in c:
        return "G"

    return None


# ==============================================================================
# SISTEMA DE ESTRATÉGIA V3
# ==============================================================================

V3_BLOCKED_CONTEXTS = {"GVG", "GRV", "RVG"}

def calcular_estrategias():
    """V3: inverte a última cor R/G e bloqueia os 3 contextos testados."""
    sinais = {"V3_INVERTE": None}
    motivos = {"V3_INVERTE": "Sem sinal"}

    if len(history_colors) < 3:
        motivos["V3_INVERTE"] = "Aguardando 3 resultados anteriores"
        return sinais, motivos

    ultima = history_colors[-1]
    trio = "".join(history_colors[-3:])

    if ultima == "V":
        motivos["V3_INVERTE"] = "Última cor = V; sem inversão"
        return sinais, motivos

    if trio in V3_BLOCKED_CONTEXTS:
        motivos["V3_INVERTE"] = f"Contexto bloqueado: {trio}"
        return sinais, motivos

    sinal = "G" if ultima == "R" else "R"
    sinais["V3_INVERTE"] = sinal
    motivos["V3_INVERTE"] = f"Inverte {ultima} → {sinal} | trio={trio}"
    return sinais, motivos


def calcular_confluencia():
    sinais, motivos = calcular_estrategias()
    votos_r = [k for k, v in sinais.items() if v == "R"]
    votos_g = [k for k, v in sinais.items() if v == "G"]
    qtd_r, qtd_g = len(votos_r), len(votos_g)

    if qtd_r > qtd_g and qtd_r >= MIN_CONFLUENCIA:
        sinal = "R"
        qtd = qtd_r
    elif qtd_g > qtd_r and qtd_g >= MIN_CONFLUENCIA:
        sinal = "G"
        qtd = qtd_g
    else:
        sinal = None
        qtd = max(qtd_r, qtd_g)

    return {
        "sinal": sinal,
        "confluencia": qtd,
        "votos_r": votos_r,
        "votos_g": votos_g,
        "sinais": sinais,
        "motivos": motivos
    }


def formatar_estrategias(resultado):
    partes = []
    for estrategia, sinal in resultado["sinais"].items():
        motivo = resultado["motivos"].get(estrategia, "")
        partes.append(f"V3={sinal or '—'} ({motivo})")
    return " | ".join(partes)


# LOOP PRINCIPAL DO BOT
# ==============================================================================

def bot_loop():

    global bot_state
    global wins
    global wins_05
    global wins_10
    global losses
    global current_profit
    global signal_color
    global history_numbers
    global history_colors
    global processed_issues
    global history_results

    add_log("🤖 SISTEMA INICIADO.")
    add_log("⏹ BOT AGUARDANDO COMANDO INICIAR.")

    while True:

        novos = []

        try:

            # ==================================================================
            # BUSCA RESULTADOS
            # ==================================================================

            raw = fetch_latest_results()

            if not raw:

                time.sleep(5)

                continue


            # ==================================================================
            # ORGANIZA ORDEM
            # ==================================================================

            raw.reverse()


            # ==================================================================
            # PROCESSA NOVOS RESULTADOS
            # ==================================================================

            for item in raw:

                issue = str(
                    item.get("issueNumber")
                )

                try:

                    num = int(
                        item.get(
                            "number",
                            item.get("numero", 0)
                        )
                    )

                except Exception:

                    num = 0


                cor = normalize_color(
                    item.get("colour", ""),
                    num
                )


                if (
                    cor
                    and
                    issue not in processed_issues
                ):

                    novos.append({
                        "issue": issue,
                        "cor": cor,
                        "num": num
                    })

                    processed_issues.add(issue)


            # ==================================================================
            # IMPORTANTE:
            #
            # O histórico NÃO é atualizado aqui.
            #
            # Cada resultado será processado individualmente.
            #
            # Primeiro usamos o histórico anterior para avaliar:
            #
            #     "qual seria o sinal?"
            #
            # Depois adicionamos o resultado ao histórico.
            #
            # Isso evita que o resultado atual influencie seu próprio sinal.
            # ==================================================================


            # ==================================================================
            # SE BOT ESTÁ PARADO
            # ==================================================================

            if not bot_running:

                for jogo in novos:

                    history_numbers.append(
                        jogo["num"]
                    )

                    history_colors.append(
                        jogo["cor"]
                    )

                    save_game_to_db(
                        jogo["issue"],
                        jogo["cor"],
                        jogo["num"],
                        "AGUARDANDO"
                    )


                if len(history_numbers) > 50:

                    history_numbers = history_numbers[-50:]

                    history_colors = history_colors[-50:]


                time.sleep(2)

                continue


            # ==================================================================
            # PROCESSA CADA NOVO RESULTADO
            # ==================================================================

            for jogo in novos:

                issue = jogo["issue"]

                cor = jogo["cor"]

                num = jogo["num"]


                # ==============================================================
                # ESTADO: ACOMPANHANDO
                # ==============================================================

                if bot_state == "ACOMPANHANDO":

                    # ----------------------------------------------------------
                    # VERIFICA SE GANHOU
                    # ----------------------------------------------------------

                    if (
                        cor == signal_color
                        or
                        (
                            signal_color in ["G", "R"]
                            and
                            cor == "V"
                        )
                    ):

                        is_violet_win = (
                            cor == "V"
                        )

                        wins += 1


                        if is_violet_win:

                            wins_05 += 1

                            profit_add = (
                                LUCRO_BASE_VIOLET
                            )

                            resultado_tipo = (
                                "VITÓRIA 0,5"
                            )

                            add_log(
                                f"🟣 VITÓRIA VIOLET! "
                                f"0/5 caiu! "
                                f"+R$ {profit_add:.2f}"
                            )

                            acao_db = "VITORIA_05"


                        else:

                            wins_10 += 1

                            profit_add = (
                                LUCRO_BASE
                            )

                            resultado_tipo = (
                                "VITÓRIA 1,0"
                            )

                            add_log(
                                f"✅ VITÓRIA! "
                                f"O {signal_color} caiu! "
                                f"+R$ {profit_add:.2f}"
                            )

                            acao_db = "VITORIA_10"


                        current_profit += (
                            profit_add
                        )


                        history_results.append({
                            "issue": issue,
                            "result": "WIN",
                            "type": resultado_tipo,
                            "value": profit_add
                        })


                        bot_state = "CACANDO"

                        signal_color = None


                        update_placar_in_db()

                        save_game_to_db(
                            issue,
                            cor,
                            num,
                            acao_db
                        )


                    # ==========================================================
                    # DERROTA
                    # ==========================================================

                    else:

                        losses += 1

                        current_profit -= (
                            PREJUIZO_DERROTA
                        )


                        history_results.append({
                            "issue": issue,
                            "result": "LOSS",
                            "type": "DERROTA",
                            "value": -PREJUIZO_DERROTA
                        })


                        add_log(
                            f"❌❌❌ DERROTA! "
                            f"-R$ {PREJUIZO_DERROTA:.2f}"
                        )


                        bot_state = "CACANDO"

                        signal_color = None


                        update_placar_in_db()

                        save_game_to_db(
                            issue,
                            cor,
                            num,
                            "DERROTA"
                        )


                    if len(history_results) > 15:

                        history_results.pop(0)


                # ==============================================================
                # ESTADO: CAÇANDO
                # ==============================================================

                else:

                    # ----------------------------------------------------------
                    # CALCULA V3 ANTES DE ADICIONAR O NOVO RESULTADO
                    # ----------------------------------------------------------

                    if len(history_numbers) >= 3:

                        resultado = (
                            calcular_confluencia()
                        )

                        sinal_disparado = (
                            resultado["sinal"]
                        )

                        confluencia = (
                            resultado["confluencia"]
                        )


                        # ------------------------------------------------------
                        # MOSTRA VOTOS
                        # ------------------------------------------------------

                        add_log(
                            f"📊 "
                            f"{formatar_estrategias(resultado)}"
                        )


                        # ------------------------------------------------------
                        # DISPARO
                        # ------------------------------------------------------

                        if sinal_disparado:

                            bot_state = "ACOMPANHANDO"

                            signal_color = (
                                sinal_disparado
                            )


                            cor_sinal = (

                                "🟢 GREEN"

                                if sinal_disparado == "G"

                                else

                                "🔴 RED"
                            )


                            votos_r = (
                                len(resultado["votos_r"])
                            )

                            votos_g = (
                                len(resultado["votos_g"])
                            )


                            add_log(
                                f"{cor_sinal} "
                                f"🚨 V3 "
                                f"{confluencia}/"
                                f"{TOTAL_ESTRATEGIAS} 🚨"
                            )


                            add_log(
                                f"📊 Votos: "
                                f"R={votos_r} | "
                                f"G={votos_g}"
                            )


                            # --------------------------------------------------
                            # MOSTRA MOTIVOS
                            # --------------------------------------------------

                            for estrategia in resultado["sinais"]:

                                sinal = (
                                    resultado["sinais"]
                                    [estrategia]
                                )

                                if sinal:

                                    motivo = (
                                        resultado["motivos"]
                                        .get(
                                            estrategia,
                                            ""
                                        )
                                    )

                                    add_log(
                                        f"   ↳ "
                                        f"{estrategia}: "
                                        f"{sinal} "
                                        f"({motivo})"
                                    )


                            add_log(
                                f"🚀 ENTRAR NO "
                                f"{signal_color}! "
                                f"(Aposta Fixa "
                                f"R${VALOR_BASE:.2f})"
                            )


                            save_game_to_db(
                                issue,
                                cor,
                                num,
                                f"SINAL "
                                f"{signal_color} "
                                f"CONFLUENCIA "
                                f"{confluencia}/"
                                f"{TOTAL_ESTRATEGIAS}"
                            )


                        else:

                            # --------------------------------------------------
                            # NÃO HOUVE V3
                            # --------------------------------------------------

                            votos_r = (
                                len(resultado["votos_r"])
                            )

                            votos_g = (
                                len(resultado["votos_g"])
                            )


                            if votos_r or votos_g:

                                add_log(
                                    f"⚪ SEM ENTRADA — "
                                    f"R={votos_r} | "
                                    f"G={votos_g}"
                                )


                            save_game_to_db(
                                issue,
                                cor,
                                num,
                                "AGUARDANDO"
                            )


                    else:

                        save_game_to_db(
                            issue,
                            cor,
                            num,
                            "AGUARDANDO"
                        )


                # ==============================================================
                # AGORA SIM:
                #
                # adiciona o resultado ao histórico.
                # ==============================================================

                history_numbers.append(num)

                history_colors.append(cor)


                # --------------------------------------------------------------
                # LIMITA MEMÓRIA
                # --------------------------------------------------------------

                if len(history_numbers) > 50:

                    history_numbers = (
                        history_numbers[-50:]
                    )

                    history_colors = (
                        history_colors[-50:]
                    )


        except Exception as e:

            add_log(
                f"⚠️ Erro no loop: {e}"
            )


        # ======================================================================
        # SMART POLLING
        # ======================================================================

        if novos:

            time.sleep(50)

        else:

            time.sleep(5)


# ==============================================================================
# SERVIDOR WEB FLASK
# ==============================================================================

app = Flask(__name__)


# ==============================================================================
# CONTROLE MANUAL - INICIAR
# ==============================================================================

@app.route("/start", methods=["POST"])
def start():

    start_bot()

    return redirect("/")


# ==============================================================================
# CONTROLE MANUAL - PARAR
# ==============================================================================

@app.route("/stop", methods=["POST"])
def stop():

    stop_bot()

    return redirect("/")


# ==============================================================================
# HTML
# ==============================================================================

HTML_TEMPLATE = """

<!DOCTYPE html>

<html lang="pt-br">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<meta http-equiv="refresh" content="10">

<title>Bot Aposta Fixa</title>

<style>

:root {

    --bg-main: #080a0f;

    --bg-card: rgba(22, 27, 34, 0.7);

    --border: rgba(255,255,255,0.08);

    --text: #e6edf3;

    --text-muted: #7d8590;

    --purple: #bc52ff;

    --green: #00e676;

    --red: #ff5252;

    --yellow: #ffca28;
}


* {

    box-sizing: border-box;

    margin: 0;

    padding: 0;
}


body {

    background:
        radial-gradient(
            circle at top center,
            #1a1f2e 0%,
            var(--bg-main) 60%
        );

    color: var(--text);

    font-family: Arial, sans-serif;

    min-height: 100vh;

    padding: 20px;

    display: flex;

    justify-content: center;

    overflow-x: hidden;
}


.container {

    max-width: 1100px;

    width: 100%;
}


.header {

    display: flex;

    justify-content: space-between;

    align-items: center;

    margin-bottom: 20px;

    gap: 15px;

    flex-wrap: wrap;
}


.logo-text {

    font-size: 26px;

    font-weight: 900;

    color: var(--purple);
}


.header-controls {

    display: flex;

    gap: 10px;

    align-items: center;

    flex-wrap: wrap;
}


.live-badge {

    background: rgba(0,230,118,0.1);

    border: 1px solid var(--green);

    color: var(--green);

    padding: 6px 16px;

    border-radius: 50px;

    font-size: 14px;

    font-weight: 700;
}


.live-badge.stopped {

    background: rgba(255,82,82,0.1);

    border-color: var(--red);

    color: var(--red);
}


.btn {

    border: none;

    padding: 11px 18px;

    border-radius: 10px;

    font-weight: 800;

    font-size: 13px;

    cursor: pointer;

    transition: 0.2s;
}


.btn:hover {

    transform: scale(1.03);
}


.btn-start {

    background: var(--green);

    color: #000;
}


.btn-stop {

    background: var(--red);

    color: #fff;
}


.trend-strip {

    display: flex;

    gap: 6px;

    margin-bottom: 20px;

    overflow-x: auto;

    padding: 10px;

    background: var(--bg-card);

    border: 1px solid var(--border);

    border-radius: 12px;
}


.trend-pill {

    min-width: 36px;

    height: 36px;

    border-radius: 8px;

    display: flex;

    align-items: center;

    justify-content: center;

    font-weight: 700;

    font-size: 14px;

    color: #fff;

    flex-shrink: 0;
}


.pill-r {

    background: var(--red);
}


.pill-g {

    background: var(--green);
}


.pill-v {

    background: var(--purple);
}


.stats-grid {

    display: grid;

    grid-template-columns:
        1.4fr
        1fr
        1fr
        1fr
        1fr
        1.4fr;

    gap: 12px;

    margin-bottom: 20px;
}


.card {

    background: var(--bg-card);

    border: 1px solid var(--border);

    border-radius: 16px;

    padding: 15px;

    text-align: center;

    position: relative;

    overflow: hidden;
}


.card-title {

    font-size: 10px;

    color: var(--text-muted);

    text-transform: uppercase;

    margin-bottom: 8px;

    font-weight: 600;
}


.card-value {

    font-size: 26px;

    font-weight: 900;
}


.win-text {

    color: var(--green);
}


.loss-text {

    color: var(--red);
}


.violet-text {

    color: var(--purple);
}


.profit-text {

    font-size: 28px;

    font-weight: 900;
}


.rate-text {

    color: var(--purple);

    font-size: 28px;

    font-weight: 900;
}


.status-hunting {

    color: var(--yellow);

    font-size: 18px;

    font-weight: 700;
}


.status-accompanying {

    font-size: 18px;

    font-weight: 700;
}


.signal-green {

    color: var(--green);
}


.signal-red {

    color: var(--red);
}


.bottom-grid {

    display: grid;

    grid-template-columns: 2fr 1fr;

    gap: 15px;
}


.console {

    background: var(--bg-card);

    border: 1px solid var(--border);

    border-radius: 16px;

    padding: 20px;

    height: 350px;

    overflow-y: auto;

    font-family: monospace;
}


.log-line {

    padding: 8px 0;

    border-bottom:
        1px solid rgba(255,255,255,0.03);

    font-size: 14px;
}


.log-vitoria {

    color: var(--green);

    font-weight: 700;
}


.log-derrota {

    color: var(--red);

    font-weight: 700;
}


.log-sinal {

    color: var(--purple);

    font-weight: 700;
}


.history-card {

    background: var(--bg-card);

    border: 1px solid var(--border);

    border-radius: 16px;

    padding: 20px;

    height: 350px;

    overflow-y: auto;
}


.history-title {

    font-size: 14px;

    color: var(--text-muted);

    text-transform: uppercase;

    font-weight: 700;

    margin-bottom: 15px;

    border-bottom:
        1px solid var(--border);

    padding-bottom: 10px;
}


.history-row {

    display: flex;

    justify-content: space-between;

    align-items: center;

    padding: 10px 0;

    border-bottom:
        1px solid rgba(255,255,255,0.03);

    font-family: monospace;

    font-size: 13px;
}


.h-issue {

    color: var(--text-muted);
}


.h-badge {

    padding: 4px 8px;

    border-radius: 6px;

    font-size: 11px;

    font-weight: 700;
}


.h-win {

    background:
        rgba(0,230,118,0.1);

    color: var(--green);
}


.h-loss {

    background:
        rgba(255,82,82,0.1);

    color: var(--red);
}


.h-violet {

    background:
        rgba(188,82,255,0.1);

    color: var(--purple);
}


.h-value {

    font-weight: 700;
}


.session-label {

    margin-bottom: 15px;

    padding: 12px;

    border-radius: 12px;

    background: rgba(188,82,255,0.08);

    border: 1px solid rgba(188,82,255,0.2);

    color: var(--purple);

    text-align: center;

    font-weight: 700;

    font-size: 13px;
}


@media (max-width: 900px) {

    .stats-grid {

        grid-template-columns:
            repeat(3, 1fr);
    }

}


@media (max-width: 600px) {

    .stats-grid {

        grid-template-columns:
            repeat(2, 1fr);
    }

    .bottom-grid {

        grid-template-columns: 1fr;
    }

    .console,
    .history-card {

        height: 250px;
    }

    .header {

        flex-direction: column;

        align-items: stretch;
    }

    .header-controls {

        justify-content: center;
    }

}

</style>

</head>


<body>


<div class="container">


    <div class="header">

        <div class="logo-text">

            🤖 Bot V3

        </div>


        <div class="header-controls">

            {% if running %}

                <div class="live-badge">

                    ● OPERANDO

                </div>

                <form method="POST" action="/stop">

                    <button
                        type="submit"
                        class="btn btn-stop">

                        ⏹ PARAR BOT

                    </button>

                </form>

            {% else %}

                <div class="live-badge stopped">

                    ● PARADO

                </div>

                <form method="POST" action="/start">

                    <button
                        type="submit"
                        class="btn btn-start">

                        ▶ INICIAR BOT

                    </button>

                </form>

            {% endif %}

        </div>

    </div>


    <div class="session-label">

        {% if running %}

            🟢 SESSÃO ATIVA — CONTABILIZANDO RESULTADOS

        {% else %}

            🔴 SESSÃO PARADA — RESULTADO CONGELADO

        {% endif %}

    </div>


    <div class="trend-strip">

        {% for i in range(history_numbers|length) %}

            {% if i >= history_numbers|length - 15 %}

                <div class="trend-pill pill-{{ history_colors[i].lower() }}">

                    {{ history_numbers[i] }}

                </div>

            {% endif %}

        {% endfor %}

    </div>


    <div class="stats-grid">


        <div class="card">

            <div class="card-title">

                Saldo da Sessão (R$)

            </div>

            <div class="card-value profit-text
                {{ 'win-text' if profit >= 0 else 'loss-text' }}">

                {{ '%.2f' % profit }}

            </div>

        </div>


        <div class="card">

            <div class="card-title">

                Vitórias

            </div>

            <div class="card-value win-text">

                {{ wins }}

            </div>

        </div>


        <div class="card">

            <div class="card-title">

                Vitórias 1,0

            </div>

            <div class="card-value win-text">

                {{ wins_10 }}

            </div>

        </div>


        <div class="card">

            <div class="card-title">

                Vitórias 0,5

            </div>

            <div class="card-value violet-text">

                {{ wins_05 }}

            </div>

        </div>


        <div class="card">

            <div class="card-title">

                Derrotas

            </div>

            <div class="card-value loss-text">

                {{ losses }}

            </div>

        </div>


        <div class="card">

            <div class="card-title">

                Aproveit.

            </div>

            <div class="card-value rate-text">

                {{ win_rate }}%

            </div>

        </div>


        <div class="card">

            <div class="card-title">

                Status do Bot

            </div>


            {% if not running %}

                <div
                    class="status-hunting"
                    style="color: var(--red);">

                    ⏹ BOT PARADO

                </div>


            {% elif state == 'ACOMPANHANDO' %}

                <div class="status-accompanying
                    {{ 'signal-green'
                       if signal == 'G'
                       else 'signal-red' }}">

                    {{ 'ENTRAR GREEN'
                       if signal == 'G'
                       else 'ENTRAR RED' }}

                </div>


            {% else %}

                <div class="status-hunting">

                    CAÇANDO V3

                </div>

            {% endif %}

        </div>


    </div>


    <div class="bottom-grid">


        <div class="console" id="consoleBox">

            {% for line in logs %}

                {% if 'VITÓRIA VIOLET' in line %}

                    <div class="log-line log-vitoria">

                        {{ line }}

                    </div>


                {% elif 'VITÓRIA' in line %}

                    <div class="log-line log-vitoria">

                        {{ line }}

                    </div>


                {% elif 'DERROTA' in line %}

                    <div class="log-line log-derrota">

                        {{ line }}

                    </div>


                {% elif 'V3' in line
                      or '🟣' in line
                      or '🟢' in line
                      or '🔴' in line %}

                    <div class="log-line log-sinal">

                        {{ line }}

                    </div>


                {% else %}

                    <div class="log-line">

                        {{ line }}

                    </div>

                {% endif %}

            {% endfor %}

        </div>


        <div class="history-card">

            <div class="history-title">

                📜 Histórico da Sessão

            </div>


            {% if not history_results %}

                <div
                    style="
                        color: var(--text-muted);
                        text-align: center;
                        padding: 30px 5px;
                        font-size: 13px;
                    ">

                    Nenhuma operação realizada nesta sessão.

                </div>

            {% endif %}


            {% for item in history_results|reverse %}

                <div class="history-row">


                    <span class="h-issue">

                        {{ item.issue }}

                    </span>


                    {% if item.result == 'WIN' %}

                        {% if item.type == 'VITÓRIA 0,5' %}

                            <span class="h-badge h-violet">

                                VITÓRIA 0,5

                            </span>

                        {% else %}

                            <span class="h-badge h-win">

                                VITÓRIA 1,0

                            </span>

                        {% endif %}

                    {% else %}

                        <span class="h-badge h-loss">

                            DERROTA

                        </span>

                    {% endif %}


                    <span class="h-value
                        {{ 'win-text'
                           if item.result == 'WIN'
                           else 'loss-text' }}">

                        R$
                        {{ '%.2f'|format(item.value) }}

                    </span>


                </div>

            {% endfor %}


        </div>


    </div>


</div>


<script>

const consoleDiv =
    document.getElementById("consoleBox");

if (consoleDiv) {

    consoleDiv.scrollTop =
        consoleDiv.scrollHeight;

}

</script>


</body>

</html>

"""


# ==============================================================================
# ROTA PRINCIPAL
# ==============================================================================

@app.route("/")
def home():

    total_jogos = wins + losses


    if total_jogos > 0:

        win_rate = round(
            (wins / total_jogos) * 100,
            1
        )

    else:

        win_rate = 0.0


    return render_template_string(

        HTML_TEMPLATE,

        logs=log_lines,

        wins=wins,

        wins_05=wins_05,

        wins_10=wins_10,

        losses=losses,

        win_rate=win_rate,

        profit=current_profit,

        history_numbers=history_numbers,

        history_colors=history_colors,

        state=bot_state,

        signal=signal_color,

        history_results=history_results,

        running=bot_running
    )


# ==============================================================================
# INICIALIZAÇÃO
# ==============================================================================

if __name__ == "__main__":

    init_db()


    bot_running = False

    bot_state = "PARADO"


    t = threading.Thread(
        target=bot_loop,
        daemon=True
    )

    t.start()


    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )


    app.run(
        host="0.0.0.0",
        port=port
    )
