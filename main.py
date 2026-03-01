import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

import vonage
from vonage import Voice
from google.genai import Client as GeminiClient
from google.genai import types
import asyncio

# ======================
# ENV
# ======================

load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
PORT = int(os.getenv("PORT", 10000))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RENDER_URL = os.getenv("RENDER_URL")

# ======================
# App
# ======================

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ======================
# Vonage
# ======================

vonage_client = vonage.Client(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
voice = Voice(vonage_client)
messages = vonage.Messages(vonage_client)

# ======================
# Gemini
# ======================

gemini = GeminiClient(api_key=GEMINI_API_KEY)

# ======================
# Logs
# ======================

whatsapp_log = []
call_log = []

# ======================
# AI
# ======================

def ai_response(prompt: str) -> str:
    try:
        r = gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig()
        )
        return r.text
    except Exception as e:
        print("AI ERROR:", e)
        return "I did not understand"

# ======================
# WhatsApp
# ======================

def send_whatsapp(to, text):
    try:
        messages.send_message({
            "channel": "whatsapp",
            "from": WHATSAPP_SANDBOX_NUMBER,
            "to": to,
            "message_type": "text",
            "text": text
        })
        whatsapp_log.append({"to": to, "text": text})
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
# Call
# ======================

async def make_call(to_number):
    try:
        voice.create_call({
            "to": [{"type": "phone", "number": to_number}],
            "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
            "answer_url": [f"{RENDER_URL}/answer"]
        })
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
            "text": "Hello! This is your AI assistant. I am ready to help you. Please speak after the beep.",
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 3,
                "maxDuration": 60
            },
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ]
    return JSONResponse(ncco)

# ======================
# Event
# ======================

@app.post("/event")
async def event(req: Request):
    try:
        data = await req.json()
        print("EVENT RAW:", data)
    except Exception as e:
        print("EVENT PARSE ERROR:", e)
        return JSONResponse([{
            "action": "talk",
            "text": "I did not hear anything. Please try again.",
        }, {
            "action": "input",
            "type": ["speech"],
            "speech": {"language": "en-US", "endOnSilence": 3, "maxDuration": 60},
            "eventUrl": [f"{RENDER_URL}/event"]
        }])

    speech_text = ""
    try:
        speech_text = data.get("speech", {}).get("results", [])[0].get("text", "")
    except:
        speech_text = ""

    if not speech_text:
        reply_text = "I did not hear you. Please say that again."
    else:
        reply_text = ai_response(speech_text)

    ncco = [
        {"action": "talk", "text": reply_text},
        {
            "action": "input",
            "type": ["speech"],
            "speech": {"language": "en-US", "endOnSilence": 3, "maxDuration": 60},
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ]

    return JSONResponse(ncco)

# ======================
# Inbound WhatsApp
# ======================

@app.post("/inbound")
async def inbound(req: Request):
    try:
        data = await req.json()
        print("INBOUND:", data)
    except Exception as e:
        print("INBOUND ERROR:", e)
        return JSONResponse({"ok": False})

    sender = data.get("from")
    text = data.get("text", "")
    if not text and "message" in data:
        text = data["message"].get("content", {}).get("text", "")

    text = (text or "").lower().strip()
    if not sender:
        return JSONResponse({"ok": False})

    # CALL
    if text == "call":
        send_whatsapp(sender, "Calling...")
        to = sender
        if not to.startswith("+"):
            to = "+" + to
        ok = await make_call(to)
        if ok:
            send_whatsapp(sender, "Call started")
        else:
            send_whatsapp(sender, "Call failed")

    # REPORT
    elif text in ["report", "status"]:
        send_report(sender)

    # AI
    else:
        reply = ai_response(text)
        send_whatsapp(sender, reply)

    return JSONResponse({"ok": True})

# ======================
# Web UI
# ======================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "whatsapp_log": whatsapp_log, "call_log": call_log}
    )

# ======================
# Status
# ======================

@app.get("/status")
async def status():
    return {"whatsapp": len(whatsapp_log), "calls": len(call_log)}

# ======================
# Main
# ======================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
