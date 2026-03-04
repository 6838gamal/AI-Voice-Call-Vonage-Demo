import os
import re
import json
import requests
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest

# =========================
# Load Environment
# =========================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")

VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
WHATSAPP_FROM = os.getenv("VONAGE_SANDBOX_NUMBER")

VONAGE_API_KEY = os.getenv("VONAGE_API_KEY")
VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET")

BASE_URL = os.getenv("BASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# =========================
# Load Private Key
# =========================
with open(PRIVATE_KEY_PATH, "r") as f:
    PRIVATE_KEY = f.read()

# =========================
# Init App & Clients
# =========================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

voice_auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
vonage_voice = Vonage(voice_auth)

msg_auth = Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)
vonage_msg = Vonage(msg_auth)

chat_sessions = {}

# =========================
# Helpers
# =========================
def clean_number(number: str):
    return re.sub(r"\D", "", str(number))

def ask_gemini(text: str, session_id: str):
    history = chat_sessions.get(session_id, [])[-6:]
    full_prompt = "\n".join(history + [f"User: {text}"])

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}]
    }

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
        {
            "action": "talk",
            "text": text,
            "language": "en-US",
            "bargeIn": True
        },
        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 1.2
            },
            "eventUrl": [f"{BASE_URL}/event"]
        }
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
# Routes
# =========================

@app.post("/call")
async def make_call(phone: str = Form(...)):
    to_num = clean_number(phone)
    from_num = clean_number(VOICE_FROM_NUMBER)

    try:
        call = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": from_num},
            answer_url=[f"{BASE_URL}/answer"],
            answer_method="GET"
        )

        response = vonage_voice.voice.create_call(call)
        print("Call initiated:", response)

    except Exception as e:
        print("Call Error:", e)

    return {"status": "calling"}

@app.get("/answer")
async def answer():
    return JSONResponse(generate_ncco("Hello! This is your AI assistant."))

@app.post("/event")
async def voice_event(request: Request):
    try:
        data = await request.json()
    except:
        form = await request.form()
        data = dict(form)

    call_uuid = data.get("uuid")
    status = data.get("status")
    duration = data.get("duration", 0)
    to_number = data.get("to")

    # ===== Call Completed =====
    if status in ["completed", "disconnected"]:
        conversation = "\n".join(chat_sessions.get(call_uuid, []))

        summary = ask_gemini(
            f"Summarize this call professionally:\n{conversation}",
            call_uuid
        )

        report = f"""
📞 Call Report
Status: {status}
Duration: {duration} sec
Call ID: {call_uuid}

🧠 Summary:
{summary}
"""

        send_whatsapp_report(report, to_number)
        chat_sessions.pop(call_uuid, None)
        return JSONResponse({"status": "ok"})

    # ===== Call Failed =====
    if status in ["failed", "rejected", "busy", "timeout"]:
        reason = data.get("reason", "Unknown")

        report = f"""
❌ Call Failed
Status: {status}
Reason: {reason}
Call ID: {call_uuid}
"""

        send_whatsapp_report(report, to_number)
        return JSONResponse({"status": "ok"})

    # ===== Speech Handling =====
    speech_results = data.get("speech", {}).get("results", [])
    if speech_results:
        user_text = speech_results[0].get("text")
    else:
        user_text = "Are you there?"

    ai_reply = ask_gemini(user_text, call_uuid)
    return JSONResponse(generate_ncco(ai_reply))

# =========================
# Run
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
