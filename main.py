import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# ======================
# Vonage
# ======================
from vonage import Client as VonageClient
from vonage.messages import Messages

# ======================
# Gemini AI
# ======================
from google.genai import Client as GeminiClient
from google.genai import types

# ======================
# Load ENV
# ======================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
PORT = int(os.getenv("PORT", 3000))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ======================
# Initialize App
# ======================
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ======================
# Vonage clients
# ======================
vonage_client = VonageClient(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
messages_client = Messages(client=vonage_client)

# ======================
# Gemini AI client
# ======================
gemini_client = GeminiClient(api_key=GEMINI_API_KEY)

# ======================
# In-memory log
# ======================
whatsapp_log = []
call_log = []

# ======================
# AI RESPONSE
# ======================
def ai_response(prompt: str) -> str:
    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig()
        )
        return response.text
    except Exception as e:
        print(f"[Error] AI response failed: {e}")
        return "Sorry, I couldn't process your request."

# ======================
# SEND WHATSAPP
# ======================
def send_whatsapp(to: str, text: str):
    try:
        messages_client.send_message({
            "from": {"type": "whatsapp", "number": WHATSAPP_SANDBOX_NUMBER},
            "to": {"type": "whatsapp", "number": to},
            "message_type": "text",
            "text": text
        })
        whatsapp_log.append({"to": to, "text": text})
    except Exception as e:
        print(f"[Error] WhatsApp send failed: {e}")

# ======================
# MAKE VOICE CALL
# ======================
async def make_call(to_number: str):
    try:
        ai_text = ai_response("The user requested a call. Give a friendly greeting and short introduction.")
        ncco = [{"action": "talk", "voiceName": "Joanna", "text": ai_text}]
        vonage_client.voice.create_call({
            "to": [{"type": "phone", "number": to_number}],
            "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
            "ncco": ncco
        })
        call_log.append({"to": to_number, "text": ai_text})
    except Exception as e:
        print(f"[Error] Voice call failed: {e}")

# ======================
# INBOUND WHATSAPP
# ======================
@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").strip()

    if text.lower() == "call":
        send_whatsapp(sender, "سنقوم بالاتصال بك الآن على رقم هاتفك...")
        to_number = sender
        if not to_number.startswith("+"):
            to_number = "+" + to_number  # تأكد من صيغة رقم دولي
        await make_call(to_number)
    else:
        reply_text = ai_response(text)
        send_whatsapp(sender, reply_text)

    return JSONResponse({"ok": True})

# ======================
# WEB INTERFACE
# ======================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "whatsapp_log": whatsapp_log,
        "call_log": call_log
    })

@app.post("/web/send_whatsapp")
async def web_send_whatsapp(req: Request):
    data = await req.json()
    to = data.get("to")
    text = data.get("text")
    send_whatsapp(to, text)
    return JSONResponse({"ok": True, "message": f"WhatsApp sent to {to}"})

@app.post("/web/make_call")
async def web_make_call(req: Request):
    data = await req.json()
    to = data.get("to")
    if not to.startswith("+"):
        to = "+" + to
    await make_call(to)
    return JSONResponse({"ok": True, "message": f"Voice call initiated to {to}"})

# ======================
# STATUS
# ======================
@app.get("/status")
async def status():
    return JSONResponse({"ok": True, "whatsapp_count": len(whatsapp_log), "call_count": len(call_log)})

# ======================
# MAIN
# ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
