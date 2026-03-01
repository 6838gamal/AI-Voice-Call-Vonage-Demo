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
vonage_client = vonage.Client(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
voice = Voice(vonage_client)
messages = vonage.Messages(vonage_client)

# ======================
# Logs
# ======================
whatsapp_log = []
call_log = []
conversation_log = []

# ======================
# AI - Gemini Safe
# ======================
def ask_gemini_safe(prompt):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = requests.post(url, headers=headers, params=params, json=payload)
        response.raise_for_status()
        result = response.json()
        candidates = result.get("candidates")
        if not candidates:
            return "⚠️ لم يتم الحصول على أي رد من الذكاء الاصطناعي."

        text_output = ""
        for cand in candidates:
            if "content" in cand:
                content = cand["content"]
                if "textSegments" in content:
                    for seg in content["textSegments"]:
                        text_output += seg.get("text", "")
                elif "text" in content:
                    text_output += content["text"]

        if not text_output.strip():
            return "⚠️ الذكاء الاصطناعي لم يرجع نصاً قابلاً للعرض."

        conversation_log.append({"user": prompt, "ai": text_output})
        print("CHAT:", prompt, "->", text_output)
        return text_output

    except Exception as e:
        print("AI ERROR:", e)
        return "⚠️ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي."

# ======================
# WhatsApp
# ======================
def send_whatsapp(to, text):
    try:
        # اصلاح الصيغة
        if not to.startswith("whatsapp:"):
            to = "whatsapp:" + to.lstrip("+")
        messages.send_message({
            "channel": "whatsapp",
            "from": WHATSAPP_SANDBOX_NUMBER,
            "to": to,
            "message_type": "text",
            "text": text
        })
        whatsapp_log.append({"to": to, "text": text})
        print(f"WHATSAPP SENT -> {to}: {text}")
    except Exception as e:
        print("WHATSAPP ERROR:", e)

# ======================
# Voice Call
# ======================
async def make_call(to_number):
    try:
        voice.create_call({
            "to": [{"type": "phone", "number": to_number}],
            "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
            "answer_url": [f"{RENDER_URL}/answer"]
        })
        call_log.append({"to": to_number})
        print(f"CALL INITIATED -> {to_number}")
        return True
    except Exception as e:
        print("CALL ERROR:", e)
        return False

# ======================
# Vonage Voice Answer
# ======================
@app.get("/answer")
async def answer():
    ncco = [
        {
            "action": "talk",
            "text": "Hello! This is your AI assistant. I am ready to help you. Please speak after the beep.",
            "bargeIn": False
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 2,
                "maxDuration": 60
            },
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ]
    return JSONResponse(ncco)

# ======================
# Voice Event
# ======================
@app.post("/event")
async def event(req: Request):
    data = await req.json()
    print("EVENT RAW:", data)

    speech_text = ""
    try:
        if "speech" in data:
            speech_data = data["speech"]
            if isinstance(speech_data, list) and len(speech_data) > 0:
                speech_text = speech_data[0].get("results", [{}])[0].get("text", "")
            elif isinstance(speech_data, dict):
                speech_text = speech_data.get("results", [{}])[0].get("text", "")
    except Exception as e:
        print("SPEECH PARSE ERROR:", e)
        speech_text = ""

    if not speech_text:
        ncco = [{"action": "talk", "text": "Thanks for contacting us. Goodbye"}]
        return JSONResponse(ncco)

    reply = ask_gemini_safe(speech_text)
    ncco = [
        {"action": "talk", "text": reply},
        {
            "action": "input",
            "type": ["speech"],
            "speech": {"language": "en-US", "endOnSilence": 2, "maxDuration": 60},
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
    except Exception as e:
        print("INBOUND PARSE ERROR:", e)
        return JSONResponse({"ok": False})

    sender = data.get("from")
    text = data.get("text") or data.get("message", {}).get("content", {}).get("text", "")
    text = (text or "").lower().strip()

    if not sender:
        return JSONResponse({"ok": False})

    if text == "call":
        send_whatsapp(sender, "Calling you now...")
        to = sender
        if not to.startswith("+"):
            to = "+" + to
        ok = await make_call(to)
        send_whatsapp(sender, "Call started" if ok else "Call failed")
    elif text in ["report", "status"]:
        msg = f"WhatsApp messages sent: {len(whatsapp_log)}\nCalls made: {len(call_log)}"
        send_whatsapp(sender, msg)
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
