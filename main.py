import os
import re
import json
import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest, Talk

# =========================
# Load environment variables
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")  # رقم Vonage أو Sandbox
WHATSAPP_FROM = os.getenv("VONAGE_SANDBOX_NUMBER")  # نفس الرقم للواتساب
VONAGE_API_KEY = os.getenv("VONAGE_API_KEY")
VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET")
BASE_URL = os.getenv("BASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

with open(PRIVATE_KEY_PATH, "r") as f:
    PRIVATE_KEY = f.read()

# =========================
# Initialize app and clients
# =========================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Vonage Voice client
voice_auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
vonage_voice = Vonage(voice_auth)

# Vonage Messages client for WhatsApp
msg_auth = Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)
vonage_msg = Vonage(msg_auth)

chat_sessions = {}
call_log = {}

# =========================
# Helpers
# =========================
def clean_number(number: str):
    return re.sub(r"\D", "", str(number))

def ask_gemini(text: str, session_id: str):
    history = chat_sessions.get(session_id, [])[-6:]  # آخر 6 رسائل
    full_prompt = "\n".join(history + [f"User: {text}"])
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    try:
        r = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
        reply = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        reply = f"AI Error: {e}"
    history.append(f"User: {text}")
    history.append(f"AI: {reply}")
    chat_sessions[session_id] = history
    return reply

def generate_ncco(text: str):
    return [
        {"action": "talk", "text": text, "language": "en-US", "bargeIn": True},
        {"action": "input", "type": ["speech"], "speech": {"language": "en-US", "endOnSilence": 1.2}, "eventUrl": [f"{BASE_URL}/event"]}
    ]

def send_whatsapp_report(message: str, to_number: str):
    try:
        vonage_msg.messages.send_message({
            "channel": "whatsapp",
            "from": WHATSAPP_FROM,
            "to": to_number,
            "message_type": "text",
            "text": message
        })
        print("📲 WhatsApp report sent")
    except Exception as e:
        print("WhatsApp Error:", e)

# =========================
# Web Routes
# =========================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

@app.post("/call")
async def make_call(request: Request, phone: str = Form(...)):
    to_num = clean_number(phone)
    try:
        call_request = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],  # ✅ dict بالشكل الصحيح
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},  # ✅ dict وليس string
            ncco=generate_ncco("Hello! This is your AI assistant.")
        )
        response = vonage_voice.voice.create_call(call_request)
        call_uuid = getattr(response, "uuid", to_num)
        call_log[call_uuid] = {"to": to_num, "status": "initiated"}
        print("Call initiated:", call_uuid)
    except Exception as e:
        call_log[to_num] = {"to": to_num, "status": f"Error: {e}"}
        print("Call Error:", e)
    return templates.TemplateResponse("index.html", {"request": request, "calls": call_log})

@app.post("/event")
async def voice_event(request: Request):
    data = await request.json()
    call_uuid = data.get("uuid")
    status = data.get("status")
    to_number = data.get("to") or WHATSAPP_FROM
    duration = data.get("duration", 0)

    # ===== Successful call =====
    if status in ["completed", "disconnected"]:
        conversation = "\n".join(chat_sessions.get(call_uuid, []))
        summary = ask_gemini(f"Summarize this call professionally:\n{conversation}", call_uuid)
        report = f"""
📞 Call Report
Status: {status}
Duration: {duration} sec
Call ID: {call_uuid}

🧠 Conversation Summary:
{summary}
"""
        send_whatsapp_report(report, to_number)
        chat_sessions.pop(call_uuid, None)
        return JSONResponse({"status": "ok"})

    # ===== No answer / timeout =====
    if status in ["no-answer", "timeout"]:
        report = f"⚠️ Call Not Answered\nStatus: {status}\nCall ID: {call_uuid}"
        send_whatsapp_report(report, to_number)
        return JSONResponse({"status": "ok"})

    # ===== Failed call =====
    if status in ["failed", "busy", "rejected", "network-error"]:
        reason = data.get("reason", "Unknown")
        report = f"❌ Call Failed\nStatus: {status}\nReason: {reason}\nCall ID: {call_uuid}"
        send_whatsapp_report(report, to_number)
        return JSONResponse({"status": "ok"})

    # ===== Speech Handling =====
    speech_results = data.get("speech", {}).get("results", [])
    user_text = speech_results[0]["text"] if speech_results else "Are you there?"
    ai_reply = ask_gemini(user_text, call_uuid)
    return JSONResponse(generate_ncco(ai_reply))

# =========================
# Run Server
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
