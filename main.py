import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import requests

import vonage
from vonage import Voice


# ======================
# Load ENV
# ======================

load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
PORT = int(os.getenv("PORT", 10000))
RENDER_URL = os.getenv("RENDER_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ======================
# Initialize App
# ======================

app = FastAPI()

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")


# ======================
# Vonage Clients
# ======================

vonage_client = vonage.Client(
    application_id=APP_ID,
    private_key=PRIVATE_KEY_PATH,
)

voice = Voice(vonage_client)
messages = vonage.Messages(vonage_client)


# ======================
# Logs
# ======================

whatsapp_log = []
call_log = []
conversation_log = []


# ======================
# Gemini AI (UPDATED)
# ======================

def ask_gemini_safe(prompt):

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    headers = {
        "Content-Type": "application/json"
    }

    params = {
        "key": GEMINI_API_KEY
    }

    system_prompt = """
You are a smart AI assistant talking to users on phone calls and WhatsApp.

Rules:
- reply short
- reply clear
- no long paragraphs
- no markdown
- speak like human assistant
- understand speech errors
- support Arabic and English
"""

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": system_prompt + "\nUser: " + prompt
                    }
                ]
            }
        ]
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            params=params,
            json=payload,
        )

        response.raise_for_status()

        result = response.json()

        candidates = result.get("candidates")

        if not candidates:
            return "Sorry, I did not understand."

        text_output = ""

        for cand in candidates:

            content = cand.get("content", {})

            if "parts" in content:

                for p in content["parts"]:

                    if "text" in p:
                        text_output += p["text"]

        if not text_output.strip():
            return "Sorry, can you repeat?"

        conversation_log.append(
            {
                "user": prompt,
                "ai": text_output,
            }
        )

        print("CHAT:", prompt, "->", text_output)

        return text_output

    except Exception as e:
        print("AI ERROR:", e)
        return "Error talking to AI"


# ======================
# WhatsApp
# ======================

def send_whatsapp(to, text):

    try:

        messages.send_message(
            {
                "channel": "whatsapp",
                "from": WHATSAPP_SANDBOX_NUMBER,
                "to": to,
                "message_type": "text",
                "text": text,
            }
        )

        whatsapp_log.append(
            {
                "to": to,
                "text": text,
            }
        )

    except Exception as e:
        print("WA ERROR:", e)


# ======================
# Report
# ======================

def send_report(to):

    msg = f"""
REPORT

WhatsApp: {len(whatsapp_log)}
Calls: {len(call_log)}
"""

    send_whatsapp(to, msg)


# ======================
# Voice Call
# ======================

async def make_call(to_number):

    try:

        voice.create_call(
            {
                "to": [{"type": "phone", "number": to_number}],
                "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
                "answer_url": [f"{RENDER_URL}/answer"],
            }
        )

        call_log.append({"to": to_number})

        return True

    except Exception as e:

        print("CALL ERROR:", e)

        return False


# ======================
# Answer
# ======================

@app.get("/answer")
async def answer():

    ncco = [
        {
            "action": "talk",
            "text": "Hello, you are speaking with AI assistant. How can I help you?",
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 3,
                "maxDuration": 60,
            },
            "eventUrl": [f"{RENDER_URL}/event"],
        },
    ]

    return JSONResponse(ncco)


# ======================
# Event
# ======================

@app.post("/event")
async def event(req: Request):

    data = await req.json()

    print("EVENT:", data)

    speech = ""

    try:

        if "speech" in data:

            results = data["speech"].get("results", [])

            if results:
                speech = results[0].get("text", "")

    except Exception as e:

        print("PARSE ERROR:", e)

    if not speech:

        return JSONResponse(
            [
                {
                    "action": "talk",
                    "text": "I did not hear you. Goodbye",
                }
            ]
        )

    text = ask_gemini_safe(speech)

    ncco = [
        {
            "action": "talk",
            "text": text,
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 3,
                "maxDuration": 60,
            },
            "eventUrl": [f"{RENDER_URL}/event"],
        },
    ]

    return JSONResponse(ncco)


# ======================
# WhatsApp inbound
# ======================

@app.post("/inbound")
async def inbound(req: Request):

    data = await req.json()

    print("INBOUND:", data)

    sender = data.get("from")

    text = data.get("text", "")

    if not sender:
        return JSONResponse({"ok": False})

    text = (text or "").strip().lower()

    if text == "call":

        send_whatsapp(sender, "Calling you now")

        to = sender

        if not to.startswith("+"):
            to = "+" + to

        ok = await make_call(to)

        if ok:
            send_whatsapp(sender, "Call started")
        else:
            send_whatsapp(sender, "Call failed")

    elif text in ["report", "status"]:

        send_report(sender)

    else:

        reply = ask_gemini_safe(text)

        send_whatsapp(sender, reply)

    return JSONResponse({"ok": True})


# ======================
# Web UI
# ======================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "whatsapp_log": whatsapp_log,
            "call_log": call_log,
        },
    )


# ======================
# Status
# ======================

@app.get("/status")
async def status():

    return {
        "whatsapp": len(whatsapp_log),
        "calls": len(call_log),
    }


# ======================
# Main
# ======================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )
