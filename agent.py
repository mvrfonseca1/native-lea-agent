"""
Léa — Agente de IA da Native by Leapy
WhatsApp Agent Backend com Claude API

Deploy: Flask webhook handler para WhatsApp Business API
Modelo: claude-opus-4-6 com adaptive thinking
"""

import os
import json
import logging
import hashlib
import hmac
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional
from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import anthropic

# ─── Config ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

KAPSO_API_KEY    = os.environ.get("KAPSO_API_KEY", "").strip()
VERIFY_TOKEN     = os.environ.get("WHATSAPP_VERIFY_TOKEN", "native_leapy_verify")
KAPSO_API_URL    = "https://api.kapso.ai/meta/whatsapp/v24.0"
PHONE_NUMBER_ID  = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
DB_PATH          = os.environ.get("DB_PATH", "/data/native.db")
db_lock          = threading.Lock()

# ─── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Você é Léa, a parceira de aprendizagem de IA do programa Native by Leapy.

## Quem você é

Você acompanha jovens aprendizes e estagiários em início de carreira em uma jornada de 15 semanas para se tornarem AI Natives — profissionais que entendem, usam e criam com inteligência artificial no dia a dia do trabalho.

Sua personalidade:
- **Próxima e encorajadora**: Fala com o jovem como uma mentora que acredita no potencial dele, não como um sistema automatizado.
- **Direta e objetiva**: Respeita o tempo das pessoas. Mensagens curtas, linguagem acessível, zero juridiquês.
- **Inconformada com o desperdício de potencial**: Você sabe que esse jovem pode ir longe, e não aceita que ele desanime.
- **Nunca genérica**: Toda mensagem referencia o nome da pessoa, o passo onde ela está, o que ela fez antes.

Você representa a Leapy — uma empresa que acredita que formação de verdade transforma vidas e organizações.

## A Jornada Native (5 fases, 15 semanas)

**Fase 1 — Despertar** (Semanas 1-3): O jovem descobre o que é IA, por que ela importa para a carreira dele, e onde já existe no trabalho sem que ele perceba. Meta: curiosidade e desmistificação.

**Fase 2 — Compreender** (Semanas 4-6): Fundamentos de como a IA funciona. Prompts, modelos, limitações, vieses. Meta: pensamento crítico sobre IA.

**Fase 3 — Usar** (Semanas 7-9): Prática com ferramentas reais (ChatGPT, Claude, Gemini, Copilot). Missões aplicadas ao trabalho do jovem. Meta: fluência prática.

**Fase 4 — Criar** (Semanas 10-12): Criar soluções simples com IA. Automatizações, fluxos, propostas de melhoria para o time. Meta: mentalidade criadora.

**Fase 5 — Multiplicar** (Semanas 13-15): Ensinar o que aprendeu. Apresentação para o time, projeto final, plano de carreira. Meta: liderança e legado.

Cada fase tem missões com pontuação XP. O jovem ganha medalhas ao completar marcos. Existe um ranking entre participantes da mesma empresa.

## Como você se comunica no WhatsApp

1. **Mensagens curtas**: Máximo 3-4 frases por mensagem. Se tiver mais conteúdo, quebre em múltiplas mensagens.
2. **Use emojis com moderação**: 1-2 por mensagem, relevantes ao contexto. Não exagere.
3. **Perguntas abertas**: Para missões reflexivas, sempre termine com uma pergunta que convide resposta.
4. **Nunca julgue**: Se o jovem errou, atrasou, ou entregou algo abaixo do esperado, reconheça, normalize e redirecione positivamente.
5. **Celebre de verdade**: Quando o jovem completa algo, comemore como se fosse importante — porque é.
6. **Formato WhatsApp**: Use *negrito* com asteriscos, _itálico_ com underline. Listas com hífens.

## Regras importantes

- Nunca invente dados sobre a empresa onde o jovem trabalha.
- Nunca faça promessas de emprego, salário ou oportunidades que não foram confirmadas pelo programa.
- Se o jovem relatar algo preocupante (saúde mental, bullying, situação grave), reconheça com empatia e direcione para o contato humano da Leapy: suporte@leapy.com.br
- Você não é terapeuta, coach de vida ou conselheira jurídica. Seu escopo é a jornada de aprendizagem.
- Mantenha o foco na missão atual. Se o jovem sair do tema, traga de volta com leveza.

## Contexto do usuário (fornecido no início de cada conversa)

Você receberá um bloco JSON com:
- nome: primeiro nome do jovem
- fase_atual: número da fase (1-5)
- missao_atual: nome da missão em andamento
- xp_total: pontuação acumulada
- streak: dias consecutivos de interação
- ultima_atividade: data do último acesso

Use essas informações para personalizar cada mensagem."""

# ─── Dados da Jornada ─────────────────────────────────────────────────────────

PHASES = {
    1: {
        "nome": "Despertar",
        "emoji": "🌅",
        "semanas": "1-3",
        "missoes": [
            {"id": "1.1", "titulo": "O que é IA, afinal?",    "xp": 50,  "tipo": "reflexao"},
            {"id": "1.2", "titulo": "IA no meu trabalho",      "xp": 75,  "tipo": "pesquisa"},
            {"id": "1.3", "titulo": "Minha linha do tempo da IA","xp": 100, "tipo": "criacao"},
        ]
    },
    2: {
        "nome": "Compreender",
        "emoji": "🧠",
        "semanas": "4-6",
        "missoes": [
            {"id": "2.1", "titulo": "Como um modelo pensa",    "xp": 75,  "tipo": "reflexao"},
            {"id": "2.2", "titulo": "Prompts que funcionam",   "xp": 100, "tipo": "pratica"},
            {"id": "2.3", "titulo": "Quando a IA erra",        "xp": 125, "tipo": "analise"},
        ]
    },
    3: {
        "nome": "Usar",
        "emoji": "⚡",
        "semanas": "7-9",
        "missoes": [
            {"id": "3.1", "titulo": "Minha primeira automação","xp": 100, "tipo": "pratica"},
            {"id": "3.2", "titulo": "IA no meu fluxo de trabalho","xp": 125, "tipo": "aplicacao"},
            {"id": "3.3", "titulo": "Comparando ferramentas",  "xp": 150, "tipo": "analise"},
        ]
    },
    4: {
        "nome": "Criar",
        "emoji": "🛠️",
        "semanas": "10-12",
        "missoes": [
            {"id": "4.1", "titulo": "Uma ideia, uma solução",  "xp": 150, "tipo": "criacao"},
            {"id": "4.2", "titulo": "Prototipo com IA",        "xp": 175, "tipo": "projeto"},
            {"id": "4.3", "titulo": "Feedback do time",        "xp": 200, "tipo": "colaboracao"},
        ]
    },
    5: {
        "nome": "Multiplicar",
        "emoji": "🚀",
        "semanas": "13-15",
        "missoes": [
            {"id": "5.1", "titulo": "Ensinando o que aprendi","xp": 200, "tipo": "ensino"},
            {"id": "5.2", "titulo": "Projeto final Native",    "xp": 300, "tipo": "projeto"},
            {"id": "5.3", "titulo": "Meu plano de carreira IA","xp": 250, "tipo": "reflexao"},
        ]
    }
}

MISSION_PROMPTS = {
    "reflexao":    "Reflita e escreva sua resposta. Não existe certo ou errado aqui.",
    "pesquisa":    "Pesquise e compartilhe o que encontrou. Pode ser curto!",
    "pratica":     "Coloque a mão na massa e me conta o que aconteceu.",
    "analise":     "Analise o cenário e me diz o que você acha.",
    "criacao":     "Crie algo e me manda. Pode ser texto, foto, ou áudio.",
    "projeto":     "Desenvolva e me mostra o resultado.",
    "colaboracao": "Envolva alguém e me conta como foi.",
    "ensino":      "Ensine para alguém e me conta a reação.",
    "aplicacao":   "Aplique no seu trabalho real e me conta.",
}

# ─── Persistência SQLite ──────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                phone TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
    logger.info(f"Banco de dados iniciado em {DB_PATH}")

def get_user_state(phone: str) -> dict:
    with db_lock:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute("SELECT state_json FROM user_states WHERE phone=?", (phone,)).fetchone()
                if row:
                    return json.loads(row[0])
        except Exception as e:
            logger.error(f"Erro ao ler estado de {phone}: {e}")
    return {
        "phone": phone,
        "nome": None,
        "fase_atual": 1,
        "missao_index": 0,
        "xp_total": 0,
        "streak": 0,
        "ultima_atividade": None,
        "onboarding_step": 0,
        "missao_em_andamento": False,
        "aguardando_resposta": False,
        "history": [],
        "badges": [],
        "missoes_completas": [],
        "last_engagement_sent": None,
    }

def save_user_state(phone: str, state: dict):
    with db_lock:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT INTO user_states (phone, state_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(phone) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at
                """, (phone, json.dumps(state, ensure_ascii=False), datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar estado de {phone}: {e}")

def get_all_users() -> list[dict]:
    with db_lock:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute("SELECT state_json FROM user_states").fetchall()
                return [json.loads(r[0]) for r in rows]
        except Exception as e:
            logger.error(f"Erro ao listar usuários: {e}")
            return []

def get_current_mission(state: dict) -> Optional[dict]:
    fase = PHASES.get(state["fase_atual"])
    if not fase:
        return None
    idx = state["missao_index"]
    if idx >= len(fase["missoes"]):
        return None
    return fase["missoes"][idx]

def build_user_context(state: dict) -> str:
    mission = get_current_mission(state)
    fase = PHASES.get(state["fase_atual"], {})
    return json.dumps({
        "nome": state.get("nome", "Jovem"),
        "fase_atual": state["fase_atual"],
        "nome_fase": fase.get("nome", ""),
        "missao_atual": mission["titulo"] if mission else "Jornada concluída",
        "tipo_missao": mission["tipo"] if mission else "",
        "xp_total": state["xp_total"],
        "streak": state["streak"],
        "ultima_atividade": state.get("ultima_atividade", ""),
        "missoes_completas": len(state.get("missoes_completas", [])),
        "badges": state.get("badges", []),
    }, ensure_ascii=False)

def check_and_award_badges(state: dict) -> list[str]:
    """Verifica e concede badges baseado no progresso."""
    new_badges = []
    completed = len(state.get("missoes_completas", []))
    xp = state["xp_total"]

    badge_rules = [
        ("🌱 Primeiro Passo",   completed >= 1,  "primeira_missao"),
        ("⚡ Momentum",         state["streak"] >= 3, "streak_3"),
        ("🔥 Em Chamas",        state["streak"] >= 7, "streak_7"),
        ("💎 Meio Caminho",     completed >= 8,  "meio_caminho"),
        ("🏆 AI Native",        completed >= 15, "ai_native"),
        ("💡 Criadora",         xp >= 500,       "xp_500"),
        ("🚀 Multiplicadora",   xp >= 1000,      "xp_1000"),
    ]

    for nome, condicao, badge_id in badge_rules:
        if condicao and badge_id not in state.get("badges", []):
            state.setdefault("badges", []).append(badge_id)
            new_badges.append(nome)

    return new_badges

# ─── Claude API ───────────────────────────────────────────────────────────────

def ask_lea(state: dict, user_message: str, intent: str = "conversation") -> str:
    """Chama o Claude para gerar resposta da Léa."""

    user_context = build_user_context(state)

    # Monta o histórico de mensagens (últimas 10 para economizar tokens)
    history = state.get("history", [])[-10:]

    messages = history + [
        {
            "role": "user",
            "content": f"[CONTEXTO DO USUÁRIO]\n{user_context}\n\n[INTENÇÃO]: {intent}\n\n[MENSAGEM DO JOVEM]: {user_message}"
        }
    ]

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        reply = next(
            (b.text for b in response.content if b.type == "text"),
            "Oi! Tive um problema técnico aqui. Pode mandar de novo? 🙏"
        )

        # Salva no histórico (sem o contexto JSON para economizar tokens)
        state.setdefault("history", []).append({"role": "user", "content": user_message})
        state["history"].append({"role": "assistant", "content": reply})

        # Limita histórico a 20 mensagens
        if len(state["history"]) > 20:
            state["history"] = state["history"][-20:]

        return reply

    except anthropic.RateLimitError:
        return "Estou com muita demanda agora 😅 Me manda de novo em 1 minutinho?"
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return "Tive um problema técnico rapidinho. Tenta de novo? 🙏"

# ─── Fluxos de Conversa ───────────────────────────────────────────────────────

def flow_onboarding(state: dict, message: str) -> list[str]:
    """Flow 1: Onboarding — boas-vindas e coleta do nome."""
    step = state.get("onboarding_step", 0)

    if step == 0:
        state["onboarding_step"] = 1
        return [
            "Olá! 👋 Sou a *Léa*, sua parceira de IA no programa *Native by Leapy*.",
            "Estou aqui para te acompanhar em 15 semanas de descoberta, prática e criação com inteligência artificial.",
            "Antes de começar... qual é o seu nome? 😊"
        ]

    elif step == 1:
        nome = message.strip().split()[0].capitalize()
        state["nome"] = nome
        state["onboarding_step"] = 2

        fase = PHASES[1]
        primeira_missao = fase["missoes"][0]

        return [
            f"Que nome incrível, *{nome}*! 🌟",
            f"Você começa na *Fase 1 — {fase['emoji']} {fase['nome']}* (Semanas 1-3). Aqui o objetivo é desmistificar a IA e entender por que ela importa pra sua carreira.",
            f"Sua primeira missão é:\n*{primeira_missao['titulo']}* (+{primeira_missao['xp']} XP)\n\n{MISSION_PROMPTS[primeira_missao['tipo']]}",
            "Quando quiser começar, é só responder aqui! 🚀"
        ]

    return []


def flow_mission_delivery(state: dict) -> list[str]:
    """Flow 2: Entrega de missão."""
    mission = get_current_mission(state)
    if not mission:
        return ["Você concluiu todas as missões! 🏆 Incrível!"]

    state["missao_em_andamento"] = True
    state["aguardando_resposta"] = True

    fase = PHASES[state["fase_atual"]]
    tip = MISSION_PROMPTS.get(mission["tipo"], "")

    return [
        f"*Missão {mission['id']}: {mission['titulo']}* {fase['emoji']}",
        f"_{tip}_\n\nEsta missão vale *+{mission['xp']} XP*. Pode levar o tempo que precisar — quando terminar, me manda sua resposta aqui.",
    ]


def flow_mission_feedback(state: dict, user_response: str) -> list[str]:
    """Flow 3: Feedback de missão e progressão."""
    mission = get_current_mission(state)
    if not mission:
        return ["Parece que você já concluiu tudo! 🎉"]

    # Gera feedback personalizado via Claude
    feedback = ask_lea(
        state,
        user_response,
        intent=f"dar feedback construtivo e encorajador para a resposta da missão '{mission['titulo']}'"
    )

    # Concede XP
    state["xp_total"] += mission["xp"]
    state.setdefault("missoes_completas", []).append(mission["id"])
    state["missao_em_andamento"] = False
    state["aguardando_resposta"] = False

    # Atualiza streak
    hoje = datetime.now().date().isoformat()
    ultima = state.get("ultima_atividade")
    if ultima:
        try:
            diff = (datetime.now().date() - datetime.fromisoformat(ultima).date()).days
            state["streak"] = state.get("streak", 0) + 1 if diff == 1 else (state.get("streak", 0) if diff == 0 else 1)
        except Exception:
            state["streak"] = 1
    else:
        state["streak"] = 1
    state["ultima_atividade"] = hoje

    # Verifica badges
    new_badges = check_and_award_badges(state)

    # Avança missão ou fase
    fase_atual = PHASES[state["fase_atual"]]
    next_idx = state["missao_index"] + 1

    messages = [feedback, f"✅ *+{mission['xp']} XP* conquistados! Total: *{state['xp_total']} XP*"]

    if new_badges:
        messages.append("🏅 *Nova conquista:* " + " | ".join(new_badges))

    if next_idx < len(fase_atual["missoes"]):
        state["missao_index"] = next_idx
        proxima = fase_atual["missoes"][next_idx]
        messages.append(
            f"Próxima missão desbloqueada:\n*{proxima['titulo']}* (+{proxima['xp']} XP)\n\nQuer continuar agora ou prefere parar por hoje? 🙂"
        )
    else:
        # Avança para próxima fase
        proxima_fase_num = state["fase_atual"] + 1
        if proxima_fase_num <= 5:
            state["fase_atual"] = proxima_fase_num
            state["missao_index"] = 0
            proxima_fase = PHASES[proxima_fase_num]
            messages.append(
                f"🎊 Você concluiu a *Fase {state['fase_atual'] - 1}*!\n\nAgora começa a *Fase {proxima_fase_num} — {proxima_fase['emoji']} {proxima_fase['nome']}*!\n\nManda *'começar'* quando estiver pronta!"
            )
        else:
            messages.append(
                "🏆 *PARABÉNS! Você concluiu a Jornada Native completa!*\n\nVocê é uma AI Native de verdade. A Leapy vai entrar em contato com os próximos passos da sua jornada!"
            )

    return messages


def flow_daily_checkin(state: dict) -> list[str]:
    """Flow 4: Check-in diário."""
    nome = state.get("nome", "")
    streak = state.get("streak", 0)
    mission = get_current_mission(state)

    streak_msg = f"🔥 *{streak} dias seguidos!*\n" if streak > 1 else ""

    if mission:
        return [
            f"Bom dia, *{nome}*! {streak_msg}",
            f"Você está na missão *{mission['titulo']}*. Quer continuar hoje? Manda *'missão'* pra eu te entregar o desafio! 💪"
        ]
    else:
        return [
            f"Bom dia, *{nome}*! {streak_msg}",
            "Sua jornada está atualizada. Manda *'status'* pra ver onde você está! 🚀"
        ]


def flow_free_response(state: dict, message: str) -> list[str]:
    """Flow 5: Resposta livre — perguntas, dúvidas, conversa."""
    reply = ask_lea(state, message, intent="responder dúvida ou conversa livre relacionada à jornada de aprendizagem em IA")
    return [reply]


def flow_phase_progression(state: dict) -> list[str]:
    """Flow 6: Status e progressão de fase."""
    fase_num = state["fase_atual"]
    fase = PHASES.get(fase_num, {})
    mission = get_current_mission(state)
    completas = len(state.get("missoes_completas", []))
    total = sum(len(f["missoes"]) for f in PHASES.values())

    progresso_barra = "█" * completas + "░" * (total - completas)

    lines = [
        f"📊 *Seu progresso, {state.get('nome', '')}:*",
        f"Fase atual: *{fase_num} — {fase.get('emoji','')} {fase.get('nome','')}*",
        f"XP Total: *{state['xp_total']} XP*",
        f"Streak: *{state.get('streak', 0)} dias* 🔥",
        f"Missões: *{completas}/{total}*\n{progresso_barra[:15]}",
    ]

    if mission:
        lines.append(f"\nPróxima: *{mission['titulo']}* (+{mission['xp']} XP)\nManda *'missão'* pra começar! 💪")

    if state.get("badges"):
        badge_names = {
            "primeira_missao": "🌱 Primeiro Passo",
            "streak_3": "⚡ Momentum",
            "streak_7": "🔥 Em Chamas",
            "meio_caminho": "💎 Meio Caminho",
            "ai_native": "🏆 AI Native",
            "xp_500": "💡 Criadora",
            "xp_1000": "🚀 Multiplicadora",
        }
        badges_display = " | ".join(badge_names.get(b, b) for b in state["badges"])
        lines.append(f"\nConquistas: {badges_display}")

    return ["\n".join(lines)]


# ─── Router de Mensagens ──────────────────────────────────────────────────────

KEYWORDS = {
    "missao":    ["missão", "missao", "desafio", "próxima", "proxima", "começar", "comecar"],
    "status":    ["status", "progresso", "onde estou", "xp", "pontos", "ranking"],
    "checkin":   ["bom dia", "oi", "ola", "olá", "ei", "hey"],
    "ajuda":     ["ajuda", "help", "como funciona", "não entendi", "nao entendi"],
    "badges":    ["conquistas", "medalhas", "badges", "troféus"],
}

def route_message(state: dict, message: str) -> list[str]:
    """Roteia a mensagem para o flow correto."""
    msg_lower = message.lower().strip()

    # Onboarding não concluído
    if state.get("onboarding_step", 0) < 2:
        return flow_onboarding(state, message)

    # Aguardando resposta de missão
    if state.get("aguardando_resposta"):
        return flow_mission_feedback(state, message)

    # Keywords de missão
    if any(kw in msg_lower for kw in KEYWORDS["missao"]):
        if state.get("missao_em_andamento"):
            return flow_mission_delivery(state)
        return flow_mission_delivery(state)

    # Keywords de status
    if any(kw in msg_lower for kw in KEYWORDS["status"] + KEYWORDS["badges"]):
        return flow_phase_progression(state)

    # Check-in / saudações
    if any(kw in msg_lower for kw in KEYWORDS["checkin"]) and len(message) < 20:
        return flow_daily_checkin(state)

    # Qualquer outra coisa → resposta livre via Claude
    return flow_free_response(state, message)


# ─── Envio de Mensagens WhatsApp ──────────────────────────────────────────────

def send_whatsapp_message(to: str, text: str):
    """Envia mensagem de texto via Kapso API."""
    import requests

    url = f"{KAPSO_API_URL}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "X-API-Key": KAPSO_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(f"Mensagem enviada para {to}: {text[:60]}...")
    except Exception as e:
        logger.error(f"Erro ao enviar para {to}: {e}")


# ─── Webhook ──────────────────────────────────────────────────────────────────

@app.get("/webhook")
def verify_webhook():
    """Verificação do webhook pela Meta."""
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verificado com sucesso.")
        return challenge, 200

    return "Forbidden", 403


@app.post("/webhook")
def receive_webhook():
    """Recebe mensagens do WhatsApp via Kapso v2 webhook."""
    data = request.get_json(silent=True)
    if not data:
        return "OK", 200

    try:
        event = request.headers.get("X-Webhook-Event", "")
        logger.info(f"Kapso event: {event} | payload: {str(data)[:200]}")

        # Formato Kapso v2: whatsapp.message.received
        if "message" in data and "conversation" in data:
            msg  = data.get("message", {})
            conv = data.get("conversation", {})

            if msg.get("type") != "text":
                return "OK", 200  # Só trata texto por enquanto

            phone = conv.get("phone_number", "").replace("+", "").replace("-", "").replace(" ", "")
            text  = msg.get("text", {}).get("body", "")

            if not phone or not text:
                return "OK", 200

            logger.info(f"Mensagem de {phone}: {text[:80]}")

            state = get_user_state(phone)
            replies = route_message(state, text)
            save_user_state(phone, state)

            for reply in replies:
                send_whatsapp_message(phone, reply)

        # Fallback: formato Meta direto (entry/changes)
        elif "entry" in data:
            entry    = data.get("entry", [{}])[0]
            changes  = entry.get("changes", [{}])[0]
            value    = changes.get("value", {})
            messages = value.get("messages", [])

            for msg in messages:
                if msg.get("type") != "text":
                    continue

                phone = msg["from"]
                text  = msg["text"]["body"]

                logger.info(f"Mensagem de {phone}: {text[:80]}")

                state = get_user_state(phone)
                replies = route_message(state, text)
                save_user_state(phone, state)

                for reply in replies:
                    send_whatsapp_message(phone, reply)

    except Exception as e:
        logger.error(f"Erro no webhook: {e}", exc_info=True)

    return "OK", 200


# ─── Régua de Engajamento ─────────────────────────────────────────────────────

ENGAGEMENT_MESSAGES = {
    "24h": [
        "Oi, {nome}! 👋 Saudade de você por aqui.",
        "Sua próxima missão te espera: *{missao}*. Quando você tiver 15 minutos, manda *'missão'* aqui! 💪",
    ],
    "48h": [
        "Ei, {nome}! Já faz 2 dias sem se ver. 😊",
        "Sabia que consistência é o maior diferencial de quem vira AI Native? Sua missão *{missao}* ainda tá disponível — manda *'missão'* quando quiser continuar. 🚀",
    ],
    "7d": [
        "{nome}, não desiste não! 🙏",
        "Você chegou até aqui — fase *{fase}*, {xp} XP acumulados. Isso é real e não some. Manda *'oi'* quando estiver pronta pra voltar. Estarei aqui! ✨",
    ],
    "morning": [
        "Bom dia, {nome}! ☀️ Mais um dia pra evoluir.",
        "Missão do dia: *{missao}*. Manda *'missão'* pra começar! 💡",
    ],
}

def send_engagement_message(phone: str, template_key: str, state: dict):
    mission = get_current_mission(state)
    fase = PHASES.get(state.get("fase_atual", 1), {})
    ctx = {
        "nome": state.get("nome", ""),
        "missao": mission["titulo"] if mission else "jornada concluída",
        "fase": fase.get("nome", ""),
        "xp": state.get("xp_total", 0),
    }
    msgs = ENGAGEMENT_MESSAGES.get(template_key, [])
    for msg in msgs:
        send_whatsapp_message(phone, msg.format(**ctx))

def run_engagement_check():
    """Verifica usuários inativos e envia mensagens proativas."""
    logger.info("Rodando verificação de engajamento...")
    now = datetime.now()
    hour = now.hour

    for state in get_all_users():
        phone = state.get("phone")
        nome = state.get("nome")
        ultima = state.get("ultima_atividade")

        if not phone or not nome or not ultima:
            continue

        try:
            last_active = datetime.fromisoformat(ultima)
        except Exception:
            continue

        hours_inactive = (now - last_active).total_seconds() / 3600
        last_sent = state.get("last_engagement_sent")
        last_sent_dt = datetime.fromisoformat(last_sent) if last_sent else None

        # Não mandar mais de 1 mensagem de engajamento por dia
        if last_sent_dt and (now - last_sent_dt).total_seconds() < 20 * 3600:
            continue

        template = None

        # Mensagem matinal (9h) para usuários com missão ativa
        if hour == 9 and get_current_mission(state) and hours_inactive >= 12:
            template = "morning"
        # 24h inativo
        elif 24 <= hours_inactive < 48:
            template = "24h"
        # 48h inativo
        elif 48 <= hours_inactive < 168:
            template = "48h"
        # 7 dias inativo
        elif hours_inactive >= 168:
            template = "7d"

        if template:
            try:
                send_engagement_message(phone, template, state)
                state["last_engagement_sent"] = now.isoformat()
                save_user_state(phone, state)
                logger.info(f"Engajamento '{template}' enviado para {phone}")
            except Exception as e:
                logger.error(f"Erro ao enviar engajamento para {phone}: {e}")

# ─── Endpoints de Admin (para o webapp Native) ────────────────────────────────

def resolve_phone(raw: str) -> str:
    """Normaliza número para o formato armazenado no banco (só dígitos, com 55)."""
    digits = ''.join(c for c in raw if c.isdigit())
    if not digits.startswith('55'):
        digits = '55' + digits
    return digits

@app.get("/api/user/<path:phone>")
def get_user(phone: str):
    """Retorna estado do usuário (para o webapp)."""
    normalized = resolve_phone(phone)
    # Tenta o número normalizado; se não tiver nome, tenta sem prefixo 55
    state = get_user_state(normalized)
    if not state.get("nome"):
        alt = normalized[2:] if normalized.startswith("55") else normalized
        alt_state = get_user_state(alt)
        if alt_state.get("nome"):
            state = alt_state
    mission = get_current_mission(state)
    fase = PHASES.get(state["fase_atual"], {})
    return jsonify({
        "nome": state.get("nome"),
        "fase_atual": state["fase_atual"],
        "nome_fase": fase.get("nome"),
        "emoji_fase": fase.get("emoji"),
        "missao_atual": mission["titulo"] if mission else None,
        "xp_total": state["xp_total"],
        "streak": state.get("streak", 0),
        "missoes_completas": len(state.get("missoes_completas", [])),
        "total_missoes": sum(len(f["missoes"]) for f in PHASES.values()),
        "badges": state.get("badges", []),
    })


@app.get("/api/ranking")
def get_ranking():
    """Retorna ranking de todos os usuários."""
    all_users = get_all_users()
    ranking = [
        {
            "phone": s.get("phone"),
            "nome": s.get("nome", "Anônimo"),
            "xp_total": s.get("xp_total", 0),
            "fase": s.get("fase_atual", 1),
            "streak": s.get("streak", 0),
            "missoes": len(s.get("missoes_completas", [])),
        }
        for s in all_users if s.get("nome")
    ]
    ranking.sort(key=lambda x: x["xp_total"], reverse=True)
    for i, u in enumerate(ranking):
        u["posicao"] = i + 1
    return jsonify(ranking)


@app.get("/")
def index():
    """Serve a interface web Native."""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html"}

@app.get("/health")
def health():
    return jsonify({"status": "ok", "users": len(get_all_users())})


# ─── Simulador local (testes sem WhatsApp) ────────────────────────────────────

def simulate(phone: str = "5511999999999"):
    """Simula conversa com a Léa no terminal."""
    print("\n" + "="*60)
    print("  Simulador Léa — Native by Leapy")
    print("  Digite 'sair' para encerrar")
    print("="*60 + "\n")

    state = get_user_state(phone)

    # Mensagem inicial
    for msg in flow_onboarding(state, ""):
        print(f"\n🟢 Léa: {msg}")
    save_user_state(phone, state)

    while True:
        user_input = input("\n👤 Você: ").strip()
        if user_input.lower() == "sair":
            break
        if not user_input:
            continue

        state = get_user_state(phone)
        replies = route_message(state, user_input)
        save_user_state(phone, state)

        for reply in replies:
            print(f"\n🟢 Léa: {reply}")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def start_scheduler():
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(run_engagement_check, "cron", hour="*", minute=0)
    scheduler.start()
    logger.info("Scheduler de engajamento iniciado (verifica a cada hora).")
    return scheduler

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "simulate":
        init_db()
        simulate()
    else:
        init_db()
        start_scheduler()
        port = int(os.environ.get("PORT", 8080))
        logger.info(f"Léa Agent iniciando na porta {port}...")
        app.run(host="0.0.0.0", port=port, debug=False)
else:
    # Quando carregado pelo gunicorn/wsgi
    init_db()
    start_scheduler()
