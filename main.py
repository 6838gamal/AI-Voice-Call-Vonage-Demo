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
# LOAD ENV
# ======================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
PORT = int(os.getenv("PORT", 10000))
RENDER_URL = os.getenv("RENDER_URL")  # e.g. https://ai-voice-call-vonage-demo.onrender.com
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ======================
# INITIALIZE APP
# ======================
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ======================
# VONAGE CLIENTS
# ======================
vonage_client = vonage.Client(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
voice = Voice(vonage_client)
messages = vonage.Messages(vonage_client)

# ======================
# LOGS
# ======================
whatsapp_log = []
call_log = []
conversation_log = []

# ======================
# GEMINI AI
# ======================
def ask_gemini_safe(prompt):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    payload = {
        "contents": [{"parts": [{"text": f"You are an AI assistant in a phone call. Reply short and clear. User: {prompt}"}]}]
    }
    try:
        r = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload)
        data = r.json()
        text = ""
        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")
        if not text:
            text = "Sorry, I did not understand."
        conversation_log.append({"user": prompt, "ai": text})
        print("CHAT:", prompt, "->", text)
        return text
    except Exception as e:
        print("GEMINI ERROR:", e)
        return "⚠️ AI error."

# ======================
# WHATSAPP
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
        print("WHATSAPP ERROR:", e)

def send_report(to):
    msg = f"REPORT\n\nWhatsApp: {len(whatsapp_log)}\nCalls: {len(call_log)}"
    send_whatsapp(to, msg)

# ======================
# VOICE CALL
# ======================
async def make_call(to_number):
    try:
        if not to_number.startswith("+"):
            to_number = "+" + to_number
        voice.create_call({
            "to": [{"type": "phone", "number": to_number}],
            "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
            "answer_url": [f"{RENDER_URL}/answer"],
        })
        call_log.append({"to": to_number})
        return True
    except Exception as e:
        print("CALL ERROR:", e)
        return False

# ======================
# ANSWER NCCO
# ======================
@app.get("/answer")
async def answer():
    ncco = [
        {
            "action": "talk",
            "text": "Hello. This is your AI assistant. Please speak after the beep.",
            "voiceName": "Amy",
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {"language": "en-US", "endOnSilence": 1, "maxDuration": 60},
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ]
    return JSONResponse(ncco)

# ======================
# EVENT HANDLER
# ======================
@app.post("/event")
async def event(req: Request):
    try:
        data = await req.json()
    except:
        try:
            form = await req.form()
            data = dict(form)
        except:
            data = {}

    print("EVENT RAW:", data)
    speech = ""

    try:
        if "speech" in data:
            speech_data = data["speech"]
            results = []
            if isinstance(speech_data, list):
                results = speech_data[0].get("results", [])
            elif isinstance(speech_data, dict):
                results = speech_data.get("results", [])
            if results:
                speech = results[0].get("text", "")
    except Exception as e:
        print("SPEECH PARSE ERROR:", e)

    if not speech:
        return JSONResponse([
            {"action": "talk", "text": "I did not hear you. Please speak.", "voiceName": "Amy"},
            {
                "action": "input",
                "type": ["speech"],
                "speech": {"language": "en-US", "endOnSilence": 1, "maxDuration": 60},
                "eventUrl": [f"{RENDER_URL}/event"]
            }
        ])

    reply = ask_gemini_safe(speech)
    print("USER:", speech, "AI:", reply)

    return JSONResponse([
        {"action": "talk", "text": reply, "voiceName": "Amy"},
        {
            "action": "input",
            "type": ["speech"],
            "speech": {"language": "en-US", "endOnSilence": 1, "maxDuration": 60},
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ])

# ======================
# INBOUND WHATSAPP
# ======================
@app.post("/inbound")
async def inbound(req: Request):
    try:
        data = await req.json()
    except:
        try:
            form = await req.form()
            data = dict(form)
        except:
            data = {}

    sender = data.get("from")
    text = data.get("text") or data.get("message", {}).get("content", {}).get("text", "")
    text = (text or "").lower().strip()

    if not sender:
        return JSONResponse({"ok": False})

    if text == "call":
        send_whatsapp(sender, "Calling you now...")
        ok = await make_call(sender)
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
# WEB UI
# ======================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "whatsapp_log": whatsapp_log, "call_log": call_log}
    )

# ======================
# STATUS
# ======================
@app.get("/status")
async def status():
    return {"whatsapp": len(whatsapp_log), "calls": len(call_log)}

# ======================
# MAIN
# ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
