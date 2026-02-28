import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

from vonage import Vonage, Auth, HttpClientOptions
from vonage_messages import WhatsappText
from vonage_voice import CreateCallRequest, Talk

# Gemini client
from google.ai import gemini

# Uvicorn لتشغيل السيرفر
import uvicorn

# ======================
# ENV
# ======================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")

WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")

BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 3000))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ======================
# APP
# ======================
app = FastAPI()

auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
options = HttpClientOptions(api_host="messages-sandbox.nexmo.com")
vonage_client = Vonage(auth, options)

# Gemini client
gemini_client = gemini.Client(api_key=GEMINI_API_KEY)

# آخر رقم واتساب لاستعماله في المكالمات
last_whatsapp_user = None

# ======================
# AI RESPONSE
# ======================
def ai_response(prompt: str) -> str:
    """يرسل نص إلى Gemini 3.5-Flash ويرجع الرد"""
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
# INBOUND WHATSAPP
# ======================
@app.post("/inbound")
async def inbound(req: Request):
    global last_whatsapp_user

    data = await req.json()
    sender = data.get("from")
    text = (data.get("text") or "").strip()

    last_whatsapp_user = sender

    if text.lower() == "call":
        send_whatsapp(sender, "Calling you now...")
        await make_call(sender)
    else:
        # الرد الذكي باستخدام Gemini
        reply_text = ai_response(text)
        send_whatsapp(sender, reply_text)

    return JSONResponse({"ok": True})

# ======================
# MAKE VOICE CALL
# ======================
async def make_call(to_number: str):
    # الرد الصوتي الذكي باستخدام Gemini
    ai_text = ai_response(
        "The user requested a call. Give a friendly greeting and short introduction."
    )

    talk = Talk(
        text=ai_text,
        loop=1,
        language="en-US"
    )

    ncco = [talk.model_dump()]

    call = CreateCallRequest(
        to=[{"type": "phone", "number": to_number}],
        from_={"type": "phone", "number": VOICE_FROM_NUMBER},
        ncco=ncco,
        machine_detection="hangup"
    )

    client_voice = Vonage(auth)
    client_voice.voice.create_call(call)

# ======================
# STATUS
# ======================
@app.post("/status")
async def status():
    return JSONResponse({"ok": True})

# ======================
# MAIN FUNCTION
# ======================
def main():
    """تشغيل FastAPI على البورت المحدد في .env"""
    port = int(os.getenv("PORT", 3000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

# ======================
# ENTRY POINT
# ======================
if __name__ == "__main__":
    main()
