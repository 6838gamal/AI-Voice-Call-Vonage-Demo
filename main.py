import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from vonage import Client as VonageClient
from vonage_messages import WhatsappText
from vonage_voice import VoiceClient, Talk  # استخدم VoiceClient الجديد
from google.ai import gemini

load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
PORT = int(os.getenv("PORT", 3000))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# Clients
vonage_client = VonageClient(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
voice_client = VoiceClient(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
gemini_client = gemini.Client(api_key=GEMINI_API_KEY)

# ======================
# AI RESPONSE
# ======================
def ai_response(prompt: str) -> str:
    response = gemini_client.chat(
        model="gemini-3.5-flash",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].content

# ======================
# SEND WHATSAPP
# ======================
def send_whatsapp(to: str, text: str):
    msg = WhatsappText(
        from_=WHATSAPP_SANDBOX_NUMBER,
        to=to,
        text=text
    )
    vonage_client.messages.send(msg)

# ======================
# MAKE VOICE CALL
# ======================
def make_call(to_number: str):
    ai_text = ai_response("The user requested a call. Give a friendly greeting and short introduction.")

    talk = Talk(
        text=ai_text,
        loop=1,
        language="en-US"
    )

    voice_client.create_call(
        to=[{"type": "phone", "number": to_number}],
        from_={"type": "phone", "number": VOICE_FROM_NUMBER},
        ncco=[talk.model_dump()]
    )

# ======================
# FRONTEND
# ======================
@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.post("/send_whatsapp")
async def send_whatsapp_api(req: Request):
    data = await req.json()
    to = data.get("to")
    text = data.get("text")
    if not to or not text:
        return JSONResponse({"ok": False, "error": "Missing 'to' or 'text'"})
    
    # AI can optionally reply automatically
    ai_text = ai_response(text)
    send_whatsapp(to, ai_text)
    return JSONResponse({"ok": True, "ai_reply": ai_text})

# ======================
# INBOUND WHATSAPP
# ======================
@app.post("/inbound")
async def inbound(req: Request):
    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").strip().lower()

    if text == "call":
        send_whatsapp(sender, "Starting a voice call now...")
        make_call(sender)
    else:
        reply_text = ai_response(text)
        send_whatsapp(sender, reply_text)

    return JSONResponse({"ok": True})

# ======================
# RUN APP
# ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
