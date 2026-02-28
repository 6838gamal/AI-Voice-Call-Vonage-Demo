import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import asyncio

# ======================
# Vonage
# ======================
from vonage import Client as VonageClient
from vonage.messages import Messages

# ======================
# Gemini AI
# ======================
from google_genai import Client as GeminiClient

# ======================
# Load ENV
# ======================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
VONAGE_API_KEY = os.getenv("VONAGE_API_KEY")
VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET")
WHATSAPP_SANDBOX_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
PORT = int(os.getenv("PORT", 3000))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ======================
# Initialize App
# ======================
app = FastAPI()

# Vonage clients
vonage_client = VonageClient(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
messages_client = Messages(key=VONAGE_API_KEY, secret=VONAGE_API_SECRET)

# Gemini AI client
gemini_client = GeminiClient(api_key=GEMINI_API_KEY)

# Last WhatsApp user
last_whatsapp_user = None

# ======================
# AI RESPONSE
# ======================
def ai_response(prompt: str) -> str:
    """Generate AI response using Gemini"""
    try:
        response = gemini_client.chat(
            model="gemini-3.5-flash",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].content
    except Exception as e:
        print(f"[Error] AI response failed: {e}")
        return "Sorry, I couldn't process your request."

# ======================
# SEND WHATSAPP
# ======================
def send_whatsapp(to: str, text: str):
    """Send WhatsApp message via Vonage"""
    try:
        messages_client.send_message({
            "from": WHATSAPP_SANDBOX_NUMBER,
            "to": to,
            "message_type": "text",
            "text": text
        })
    except Exception as e:
        print(f"[Error] WhatsApp send failed: {e}")

# ======================
# MAKE VOICE CALL
# ======================
async def make_call(to_number: str):
    """Make AI-powered voice call via Vonage"""
    try:
        ai_text = ai_response("The user requested a call. Give a friendly greeting and short introduction.")
        ncco = [
            {
                "action": "talk",
                "voiceName": "Joanna",
                "text": ai_text
            }
        ]
        vonage_client.voice.create_call({
            "to": [{"type": "phone", "number": to_number}],
            "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
            "ncco": ncco
        })
    except Exception as e:
        print(f"[Error] Voice call failed: {e}")

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
        reply_text = ai_response(text)
        send_whatsapp(sender, reply_text)

    return JSONResponse({"ok": True})

# ======================
# STATUS
# ======================
@app.get("/status")
async def status():
    return JSONResponse({"ok": True})

# ======================
# MAIN
# ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
