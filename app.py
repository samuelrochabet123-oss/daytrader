import time
import requests
import numpy as np
import os
import threading
import psycopg2
from flask import Flask, render_template_string
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÕES DA API E GESTÃO FINANCEIRA
# ==============================================================================
API_URL = "https://22885.club/api/webapi/GetNoaverageEmerdList"
API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    # ⚠️ COLOQUE SEU TOKEN COMPLETO AQUI (apague as reticências)
    "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://popbra66.com",
    "referer": "https://popbra66.com/",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64)"
}

# Gestão de Banca (Aposta Fixa R$1)
VALOR_BASE = 1.0
LUCRO_BASE = 1.0
LUCRO_BASE_VIOLET = 0.5  # Se cair 0 ou 5, paga 1.5x
PREJUIZO_DERROTA = 1.0

# Variáveis globais de memória (RAM)
history_numbers = []
history_colors = []
processed_issues = set()
history_results = [] # Lista para o painel de histórico

# Estado do Bot
bot_state = "CACANDO" 
signal_color = None   
wins = 0
losses = 0
current_profit = 0.0
log_lines = []

# ==============================================================================
# BANCO DE DADOS (PostgreSQL do Railway) - MODO RESET TOTAL
# ==============================================================================
def get_db_connection():
    try:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url: return None
        return psycopg2.connect(database_url)
    except: return None

def init_db():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            # 🧹 LIMPEZA TOTAL: Apaga tudo para recomeçar do zero a cada reinicialização
            cur.execute("DROP TABLE IF EXISTS historico;")
            cur.execute("DROP TABLE IF EXISTS placar;")
            
            # Cria as tabelas limpinhas
            cur.execute("CREATE TABLE historico (issue TEXT PRIMARY KEY, cor TEXT, numero INTEGER, acao TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
            cur.execute("CREATE TABLE placar (id INTEGER PRIMARY KEY DEFAULT 1, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, profit REAL DEFAULT 0.0);")
            cur.execute("INSERT INTO placar (id, wins, losses, profit) VALUES (1, 0, 0, 0.0);")
            conn.commit()
        conn.close()

def update_placar_in_db():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE placar SET wins = %s, losses = %s, profit = %s WHERE id = 1;", (wins, losses, current_profit))
            conn.commit()
        conn.close()

def save_game_to_db(issue, cor, numero, acao):
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO historico (issue, cor, numero, acao) VALUES (%s, %s, %s, %s) ON CONFLICT (issue) DO NOTHING;", (issue, cor, numero, acao))
            conn.commit()
        conn.close()

# ==============================================================================
# LÓGICA DO BOT (APOSTA FIXA - SEM GALE)
# ==============================================================================
def add_log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_lines.append(f"[{timestamp}] {msg}")
    if len(log_lines) > 50: log_lines.pop(0)

def fetch_latest_results():
    payload = {"pageSize": 10, "pageNo": 1, "typeId": 1, "language": 3, "random": "2535e29e3dc5441cafefdeb3fe4a7c82", "signature": "4BB11F00CC6485FA05174CE313B6EE1B", "timestamp": int(time.time())}
    try:
        response = requests.post(API_URL, headers=API_HEADERS, json=payload, timeout=8)
        if response.status_code == 200:
            data = response.json()
            if "data" in data and "list" in data["data"]: return data["data"]["list"]
            elif "list" in data: return data["list"]
        return []
    except: return []

def normalize_color(c, num=None):
    if num is not None:
        if num == 0: return "V"
        if num == 5: return "V"
        if num % 2 == 0: return "R"
        return "G"
    c = str(c).lower()
    if "violet" in c: return "V"
    if "red" in c: return "R"
    if "green" in c: return "G"
    return None

def bot_loop():
    global bot_state, wins, losses, current_profit, signal_color, history_numbers, history_colors, processed_issues, history_results
    add_log("🤖 BOT APOSTA FIXA INICIADO...")
    
    while True:
        try:
            raw = fetch_latest_results()
            if not raw:
                time.sleep(10)
                continue
            
            raw.reverse()
            novos = []
            for item in raw:
                issue = str(item.get("issueNumber"))
                try:
                    num = int(item.get("number", item.get("numero", 0)))
                except:
                    num = 0
                cor = normalize_color(item.get("colour", ""), num)
                
                if cor and issue not in processed_issues:
                    history_colors.append(cor)
                    history_numbers.append(num)
                    processed_issues.add(issue)
                    novos.append({"issue": issue, "cor": cor, "num": num})
            
            if len(history_numbers) > 50: 
                history_numbers = history_numbers[-50:]
                history_colors = history_colors[-50:]
                
            for jogo in novos:
                issue, cor, num = jogo["issue"], jogo["cor"], jogo["num"]
                cor_formatada = "🟣 VIOLET" if cor == "V" else "🔴 RED" if cor == "R" else "🟢 GREEN"
                
                add_log("="*60)
                add_log(f"🎲 NOVO JOGO: {issue} | COR: {cor_formatada} | Nº: {num}")
                add_log("-"*60)

                if bot_state == "ACOMPANHANDO":
                    # Lógica Sem Gale: Avalia imediatamente se ganhou ou perdeu
                    if cor == signal_color or (signal_color in ["G", "R"] and cor == "V"):
                        is_violet_win = (cor == "V")
                        wins += 1
                        profit_add = LUCRO_BASE_VIOLET if is_violet_win else LUCRO_BASE
                        current_profit += profit_add
                        
                        # Adiciona ao histórico visual
                        history_results.append({"issue": issue, "result": "WIN", "value": profit_add})
                        
                        add_log(f"✅✅✅ VITÓRIA! O {signal_color} caiu! +R$ {profit_add:.2f}")
                        bot_state = "CACANDO"; signal_color = None
                        update_placar_in_db()
                        save_game_to_db(issue, cor, num, "VITORIA")
                    else:
                        losses += 1
                        current_profit -= PREJUIZO_DERROTA
                        
                        # Adiciona ao histórico visual
                        history_results.append({"issue": issue, "result": "LOSS", "value": -PREJUIZO_DERROTA})
                        
                        add_log(f"❌❌❌ DERROTA! -R$ {PREJUIZO_DERROTA:.2f}")
                        bot_state = "CACANDO"; signal_color = None
                        update_placar_in_db()
                        save_game_to_db(issue, cor, num, "DERROTA")
                        
                    # Mantém apenas os últimos 15 resultados no painel
                    if len(history_results) > 15:
                        history_results.pop(0)
                        
                else:
                    # LÓGICA DE CAÇADA (4 REGRAS SNIPER)
                    if len(history_numbers) >= 3:
                        soma_3 = sum(history_numbers[-3:])
                        last_num = history_numbers[-1]
                        prev_num = history_numbers[-2]
                        prev2_num = history_numbers[-3]
                        
                        sinal_disparado = None
                        motivo = ""
                        
                        # Regra 1: Soma(3) <= 4 -> Green
                        if soma_3 <= 4:
                            sinal_disparado = "G"; motivo = f"Soma(3) = {soma_3} (<=4)"
                        
                        # Regra 2: Duplo 8 ou 9 -> Red
                        elif last_num >= 8 and prev_num >= 8:
                            sinal_disparado = "R"; motivo = f"Duplo Teto ({prev_num},{last_num})"
                        
                        # Regra 3: Teto Isolado (4,7,7) -> Red
                        elif last_num >= 7 and prev_num >= 7 and prev2_num <= 4:
                            sinal_disparado = "R"; motivo = f"Teto Isolado ({prev2_num},{prev_num},{last_num})"
                        
                        # Regra 4: Teto Relax (7,6) -> Red
                        elif last_num >= 7 and prev_num >= 6:
                            sinal_disparado = "R"; motivo = f"Teto Relax ({prev_num},{last_num})"
                        
                        if sinal_disparado:
                            bot_state = "ACOMPANHANDO"
                            signal_color = sinal_disparado
                            cor_sinal = "🟢 GREEN" if sinal_disparado == "G" else "🔴 RED"
                            add_log(f"{cor_sinal} 🚨 SINAL SNIPER ({sinal_disparado}) 🚨")
                            add_log(f"Regra: {motivo}")
                            add_log(f"🚀 ENTRAR NO {signal_color}! (Aposta Fixa R${VALOR_BASE:.2f})")
                            save_game_to_db(issue, cor, num, f"SINAL {signal_color}")
                        else:
                            add_log("⚪ AGUARDANDO... Nenhum padrão ativo.")
                            save_game_to_db(issue, cor, num, "AGUARDANDO")
        except Exception as e:
            add_log(f"Erro no loop: {e}")
            
        # SMART POLLING
        if novos:
            time.sleep(50)
        else:
            time.sleep(5)

# ==============================================================================
# SERVIDOR WEB (FLASK) - LAYOUT COM HISTÓRICO
# ==============================================================================
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="10">
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect x='4' y='10' width='24' height='18' rx='4' fill='%23bc52ff'/%3E%3Ccircle cx='12' cy='18' r='2.5' fill='%23080a0f'/%3E%3Ccircle cx='20' cy='18' r='2.5' fill='%23080a0f'/%3E%3Cline x1='12' y1='24' x2='20' y2='24' stroke='%23080a0f' stroke-width='2' stroke-linecap='round'/%3E%3Cline x1='16' y1='10' x2='16' y2='4' stroke='%23bc52ff' stroke-width='2'/%3E%3Ccircle cx='16' cy='3' r='2.5' fill='%23bc52ff'/%3E%3C/svg%3E">
    <title>Bot Day Trade</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;700;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root { --bg-main: #080a0f; --bg-card: rgba(22, 27, 34, 0.7); --border: rgba(255, 255, 255, 0.08); --text: #e6edf3; --text-muted: #7d8590; --purple: #bc52ff; --green: #00e676; --red: #ff5252; --yellow: #ffca28; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: radial-gradient(circle at top center, #1a1f2e 0%, var(--bg-main) 60%); color: var(--text); font-family: 'Outfit', sans-serif; min-height: 100vh; padding: 20px; display: flex; justify-content: center; overflow-x: hidden; }
        .container { max-width: 1000px; width: 100%; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .logo-wrapper { display: flex; align-items: center; gap: 12px; }
        .bot-icon { color: var(--purple); filter: drop-shadow(0 0 8px var(--purple)); display: flex; align-items: center; }
        .logo-text { font-size: 26px; font-weight: 900; background: linear-gradient(135deg, var(--purple) 0%, #ffffff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; letter-spacing: -1px; }
        .live-badge { background: rgba(0, 230, 118, 0.1); border: 1px solid var(--green); color: var(--green); padding: 6px 16px; border-radius: 50px; font-size: 14px; font-weight: 700; display: flex; align-items: center; gap: 8px; text-transform: uppercase; }
        .live-dot { width: 8px; height: 8px; background: var(--green); border-radius: 50%; box-shadow: 0 0 10px var(--green); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
        
        .trend-strip { display: flex; gap: 6px; margin-bottom: 20px; overflow-x: auto; padding: 10px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; backdrop-filter: blur(12px); }
        .trend-pill { min-width: 36px; height: 36px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; color: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.3); flex-shrink: 0; }
        .pill-r { background: var(--red); } .pill-g { background: var(--green); } .pill-v { background: var(--purple); box-shadow: 0 0 10px var(--purple); }
        
        .stats-grid { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1.5fr; gap: 12px; margin-bottom: 20px; }
        .card { background: var(--bg-card); border: 1px solid var(--border); backdrop-filter: blur(12px); border-radius: 16px; padding: 15px; text-align: center; transition: all 0.4s ease; position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; }
        .card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: transparent; transition: 0.4s; }
        .card-title { font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 5px; font-weight: 600; }
        .card-value { font-size: 26px; font-weight: 900; line-height: 1; }
        .win-text { color: var(--green); text-shadow: 0 0 15px rgba(0, 230, 118, 0.4); }
        .loss-text { color: var(--red); text-shadow: 0 0 15px rgba(255, 82, 82, 0.4); }
        .profit-text { font-size: 28px; font-weight: 900; }
        .rate-text { color: var(--purple); text-shadow: 0 0 20px rgba(188, 82, 255, 0.5); font-size: 28px; }
        .status-hunting { color: var(--yellow); font-size: 18px; font-weight: 700; }
        .status-accompanying { font-size: 18px; font-weight: 700; }
        .signal-green { color: var(--green); text-shadow: 0 0 15px var(--green); }
        .signal-red { color: var(--red); text-shadow: 0 0 15px var(--red); }
        .card-hunting::before { background: var(--yellow); } .card-active { border-color: var(--purple); } .card-active::before { background: var(--purple); }

        .bottom-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 15px; }
        .console { background: var(--bg-card); border: 1px solid var(--border); backdrop-filter: blur(12px); border-radius: 16px; padding: 20px; height: 350px; overflow-y: auto; font-family: 'JetBrains Mono', monospace; }
        .console::-webkit-scrollbar { width: 6px; } .console::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
        .log-line { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 14px; display: flex; }
        .log-time { color: var(--text-muted); margin-right: 15px; font-size: 12px; min-width: 70px; }
        .log-msg { flex: 1; }
        .log-vitoria .log-msg { color: var(--green); font-weight: 700; } .log-derrota .log-msg { color: var(--red); font-weight: 700; }
        .log-sinal .log-msg { color: var(--purple); font-weight: 700; } .log-aguardando .log-msg { color: var(--text-muted); }
        .log-jogo .log-msg { color: var(--text); font-weight: 700; }

        .history-card { background: var(--bg-card); border: 1px solid var(--border); backdrop-filter: blur(12px); border-radius: 16px; padding: 20px; height: 350px; overflow-y: auto; }
        .history-title { font-size: 14px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; margin-bottom: 15px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .history-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.03); font-family: 'JetBrains Mono'; font-size: 13px; }
        .h-issue { color: var(--text-muted); }
        .h-badge { padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; }
        .h-win { background: rgba(0, 230, 118, 0.1); color: var(--green); }
        .h-loss { background: rgba(255, 82, 82, 0.1); color: var(--red); }
        .h-value { font-weight: 700; }
        
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .stats-grid .card:nth-child(1) { grid-column: span 2; }
            .stats-grid .card:nth-child(5) { grid-column: span 2; }
            .card-value { font-size: 22px; }
            .profit-text, .rate-text { font-size: 24px; }
            .status-hunting, .status-accompanying { font-size: 16px; }
            .bottom-grid { grid-template-columns: 1fr; }
            .console, .history-card { height: 250px; padding: 15px; }
            .log-time { display: none; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo-wrapper">
                <div class="bot-icon"><svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path></svg></div>
                <div class="logo-text">Bot Aposta Fixa</div>
            </div>
            <div class="live-badge"><div class="live-dot"></div> LIVE</div>
        </div>
        
        <div class="trend-strip">
            {% for i in range(history_numbers|length) %}
                {% if i >= history_numbers|length - 15 %}
                    <div class="trend-pill pill-{{ history_colors[i].lower() }}">{{ history_numbers[i] }}</div>
                {% endif %}
            {% endfor %}
        </div>
        
        <div class="stats-grid">
            <div class="card"><div class="card-title">Saldo (R$)</div><div class="card-value profit-text {{ 'win-text' if profit >= 0 else 'loss-text' }}">{{ '%.2f' % profit }}</div></div>
            <div class="card"><div class="card-title">Vitórias</div><div class="card-value win-text">{{ wins }}</div></div>
            <div class="card"><div class="card-title">Derrotas</div><div class="card-value loss-text">{{ losses }}</div></div>
            <div class="card"><div class="card-title">Aproveit.</div><div class="card-value rate-text">{{ win_rate }}%</div></div>
            <div class="card {% if state == 'ACOMPANHANDO' %}card-active{% else %}card-hunting{% endif %}">
                <div class="card-title">Status do Bot</div>
                {% if state == 'ACOMPANHANDO' %}
                    <div class="status-accompanying {{ 'signal-green' if signal == 'G' else 'signal-red' }}">{{ 'ENTRAR GREEN' if signal == 'G' else 'ENTRAR RED' }}</div>
                {% else %}
                    <div class="status-hunting">CAÇANDO NÚMEROS</div>
                {% endif %}
            </div>
        </div>

        <div class="bottom-grid">
            <div class="console" id="consoleBox">
                {% for line in logs %}
                    {% if 'VITÓRIA' in line %}
                        <div class="log-line log-vitoria"><span class="log-time">{{ line.split(']')[0].replace('[','') }}</span><span class="log-msg">✅ {{ line.split(']')[1] }}</span></div>
                    {% elif 'DERROTA' in line %}
                        <div class="log-line log-derrota"><span class="log-time">{{ line.split(']')[0].replace('[','') }}</span><span class="log-msg">❌ {{ line.split(']')[1] }}</span></div>
                    {% elif 'SINAL' in line or '🟣' in line or '🟢' in line or '🔴' in line %}
                        <div class="log-line log-sinal"><span class="log-time">{{ line.split(']')[0].replace('[','') }}</span><span class="log-msg">{{ line.split(']')[1] }}</span></div>
                    {% elif 'NOVO JOGO' in line %}
                        <div class="log-line log-jogo"><span class="log-time">{{ line.split(']')[0].replace('[','') }}</span><span class="log-msg">🎲 {{ line.split(']')[1] }}</span></div>
                    {% elif '==' in line or '--' in line %}<div class="log-line"></div>
                    {% else %}<div class="log-line"><span class="log-time">{{ line.split(']')[0].replace('[','') }}</span><span class="log-msg">{{ line.split(']')[1] }}</span></div>{% endif %}
                {% endfor %}
            </div>
            
            <div class="history-card">
                <div class="history-title">📜 Histórico de Sinais</div>
                {% for item in history_results|reverse %}
                    <div class="history-row">
                        <span class="h-issue">{{ item.issue }}</span>
                        <span class="h-badge {{ 'h-win' if item.result == 'WIN' else 'h-loss' }}">{{ 'VITÓRIA' if item.result == 'WIN' else 'DERROTA' }}</span>
                        <span class="h-value {{ 'win-text' if item.result == 'WIN' else 'loss-text' }}">R$ {{ '%.2f'|format(item.value) }}</span>
                    </div>
                {% endfor %}
            </div>
        </div>
    </div>
    
    <script>
        const consoleDiv = document.getElementById('consoleBox');
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    total_jogos = wins + losses
    win_rate = round((wins / total_jogos) * 100, 1) if total_jogos > 0 else 0.0
    
    return render_template_string(HTML_TEMPLATE, logs=log_lines, wins=wins, losses=losses, win_rate=win_rate, profit=current_profit, history_numbers=history_numbers, history_colors=history_colors, state=bot_state, signal=signal_color, history_results=history_results)

if __name__ == "__main__":
    init_db() # Zera o banco ao reiniciar
    t = threading.Thread(target=bot_loop)
    t.daemon = True
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
