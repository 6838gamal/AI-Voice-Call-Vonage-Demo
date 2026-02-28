import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import requests
import vonage

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # <-- مفتاح Gemini من البيئة

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
voice = vonage.Voice(vonage_client)
messages = vonage.Messages(vonage_client)

# ======================
# Logs
# ======================
whatsapp_log = []
call_log = []
conversation_log = []

# ======================
# Gemini AI
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

    except requests.RequestException as e:
        print("REQUEST ERROR:", e)
        return "⚠️ حدث خطأ أثناء الاتصال بالذكاء الاصطناعي."
    except Exception as e:
        print("GENERAL ERROR:", e)
        return "⚠️ حدث خطأ غير متوقع."

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

def send_report(to):
    msg = f"""
REPORT

WhatsApp sent: {len(whatsapp_log)}
Calls made: {len(call_log)}
"""
    send_whatsapp(to, msg)

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
        return True
    except Exception as e:
        print("CALL ERROR:", e)
        return False

# ======================
# IVR Answer
# ======================
@app.get("/answer")
async def answer():
    ncco = [
        {
            "action": "talk",
            "text": "Welcome! Press 1 for Service A, 2 for Service B, 3 to receive a report."
        },
        {
            "action": "input",
            "maxDigits": 1,
            "timeOut": 10,
            "eventUrl": [f"{RENDER_URL}/event"]
        }
    ]
    return JSONResponse(ncco)

# ======================
# IVR Event
# ======================
@app.post("/event")
async def event(req: Request):
    data = await req.json()
    print("RAW EVENT:", data)
    dtmf = data.get("dtmf")

    if dtmf == "1":
        ncco = [
            {"action": "talk", "text": "You selected Service A. Please say your details after the beep."},
            {"action": "input",
             "type": ["speech"],
             "speech": {"language": "en-US", "endOnSilence": 2, "maxDuration": 60},
             "eventUrl": [f"{RENDER_URL}/service_a"]}
        ]
    elif dtmf == "2":
        ncco = [
            {"action": "talk", "text": "You selected Service B. Please say your details after the beep."},
            {"action": "input",
             "type": ["speech"],
             "speech": {"language": "en-US", "endOnSilence": 2, "maxDuration": 60},
             "eventUrl": [f"{RENDER_URL}/service_b"]}
        ]
    elif dtmf == "3":
        ncco = [{"action": "talk", "text": "Report will be sent to your WhatsApp. Thank you!"}]
    else:
        ncco = [{"action": "talk", "text": "Sorry, invalid choice. Goodbye!"}]
    return JSONResponse(ncco)

# ======================
# Example Service Endpoints
# ======================
@app.post("/service_a")
async def service_a(req: Request):
    data = await req.json()
    speech = ""
    if "speech" in data:
        speech = data["speech"][0]["results"][0]["text"]
    send_whatsapp("+967774440982", f"Service A request: {speech}")
    return JSONResponse([{"action": "talk", "text": "Thank you, your Service A request has been received."}])

@app.post("/service_b")
async def service_b(req: Request):
    data = await req.json()
    speech = ""
    if "speech" in data:
        speech = data["speech"][0]["results"][0]["text"]
    send_whatsapp("+967774440982", f"Service B request: {speech}")
    return JSONResponse([{"action": "talk", "text": "Thank you, your Service B request has been received."}])

# ======================
# Inbound WhatsApp
# ======================
@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    print("INBOUND:", data)
    sender = data.get("from")
    text = data.get("text", "")

    if not text and "message" in data:
        text = data["message"].get("content", {}).get("text", "")

    text = (text or "").lower().strip()
    if not sender:
        return JSONResponse({"ok": False})

    if text == "call":
        send_whatsapp(sender, "Calling you now...")
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
