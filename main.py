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
# ENV
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
# APP
# ======================

app = FastAPI()

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")


# ======================
# VONAGE
# ======================

vonage_client = vonage.Client(
    application_id=APP_ID,
    private_key=PRIVATE_KEY_PATH,
)

voice = Voice(vonage_client)
messages = vonage.Messages(vonage_client)


# ======================
# LOGS
# ======================

whatsapp_log = []
call_log = []
conversation_log = []


# ======================
# GEMINI
# ======================

def ask_gemini_safe(prompt):

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text":
                        "You are AI assistant in phone call. "
                        "Reply short and clear. "
                        "User: " + prompt
                    }
                ]
            }
        ]
    }

    try:

        r = requests.post(
            url,
            params={"key": GEMINI_API_KEY},
            json=payload,
        )

        data = r.json()

        text = ""

        for c in data.get("candidates", []):
            for p in c.get("content", {}).get("parts", []):
                text += p.get("text", "")

        if not text:
            text = "Sorry, I did not understand."

        return text

    except Exception as e:

        print(e)

        return "Error"


# ======================
# WHATSAPP
# ======================

def send_whatsapp(to, text):

    messages.send_message({
        "channel": "whatsapp",
        "from": WHATSAPP_SANDBOX_NUMBER,
        "to": to,
        "message_type": "text",
        "text": text
    })

    whatsapp_log.append({"to": to})


# ======================
# REPORT
# ======================

def send_report(to):

    msg = f"""
REPORT

WhatsApp: {len(whatsapp_log)}
Calls: {len(call_log)}
"""

    send_whatsapp(to, msg)


# ======================
# CALL
# ======================

async def make_call(to_number):

    url = f"{RENDER_URL}/answer"

    print("ANSWER URL:", url)

    voice.create_call({
        "to": [{"type": "phone", "number": to_number}],
        "from": {"type": "phone", "number": VOICE_FROM_NUMBER},
        "answer_url": [url],
    })

    call_log.append({"to": to_number})


# ======================
# ANSWER
# ======================

@app.get("/answer")
async def answer():

    ncco = [

        {
            "action": "talk",
            "text": "Hello. This is your AI assistant. Please speak.",
            "voiceName": "Amy",
            "bargeIn": True
        },

        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "endOnSilence": 1,
                "maxDuration": 60,
                "language": "en-US"
            },
            "eventUrl": [f"{RENDER_URL}/event"]
        }

    ]

    return JSONResponse(ncco)


# ======================
# EVENT
# ======================

@app.post("/event")
async def event(req: Request):

    try:
        data = await req.json()
    except:
        form = await req.form()
        data = dict(form)

    print("EVENT:", data)

    speech = ""

    try:

        if "speech" in data:

            results = data["speech"].get("results", [])

            if results:
                speech = results[0].get("text", "")

    except:
        pass


    if not speech:

        return JSONResponse([

            {
                "action": "talk",
                "text": "I did not hear you",
                "voiceName": "Amy"
            },

            {
                "action": "input",
                "type": ["speech"],
                "speech": {
                    "endOnSilence": 1,
                    "maxDuration": 60,
                    "language": "en-US"
                },
                "eventUrl": [f"{RENDER_URL}/event"]
            }

        ])


    reply = ask_gemini_safe(speech)


    ncco = [

        {
            "action": "talk",
            "text": reply,
            "voiceName": "Amy"
        },

        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "endOnSilence": 1,
                "maxDuration": 60,
                "language": "en-US"
            },
            "eventUrl": [f"{RENDER_URL}/event"]
        }

    ]

    return JSONResponse(ncco)


# ======================
# INBOUND
# ======================

@app.post("/inbound")
async def inbound(req: Request):

    data = await req.json()

    sender = data.get("from")
    text = data.get("text", "")

    if text == "call":

        await make_call(sender)

    elif text == "report":

        send_report(sender)

    else:

        reply = ask_gemini_safe(text)

        send_whatsapp(sender, reply)

    return JSONResponse({"ok": True})


# ======================
# WEB
# ======================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "whatsapp_log": whatsapp_log,
            "call_log": call_log,
        }
    )


# ======================
# STATUS
# ======================

@app.get("/status")
async def status():

    return {
        "calls": len(call_log),
        "whatsapp": len(whatsapp_log)
    }


# ======================
# MAIN
# ======================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False
    )
