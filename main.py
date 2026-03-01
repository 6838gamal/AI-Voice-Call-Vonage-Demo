import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dotenv import load_dotenv

from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest

from google.genai import Client as GeminiClient
from google.genai import types


# =========================
# ENV
# =========================

load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")

VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
WHATSAPP_NUMBER = os.getenv("VONAGE_SANDBOX_NUMBER")

RENDER_URL = os.getenv("RENDER_URL")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PORT = int(os.getenv("PORT", 10000))


# =========================
# APP
# =========================

app = FastAPI()

templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================
# VONAGE
# =========================

auth = Auth(
    application_id=APP_ID,
    private_key=PRIVATE_KEY_PATH
)

vonage_client = Vonage(auth)


# =========================
# GEMINI
# =========================

gemini = GeminiClient(
    api_key=GEMINI_API_KEY
)


# =========================
# LOGS
# =========================

call_log = []
wa_log = []


# =========================
# AI
# =========================

def ai_response(text: str):

    try:

        r = gemini.models.generate_content(

            model="gemini-2.5-flash",

            contents=text,

            config=types.GenerateContentConfig()

        )

        return r.text

    except Exception as e:

        print("AI ERROR:", e)

        return "I did not understand, please say again."


# =========================
# CALL
# =========================

async def make_call(to_number):

    try:

        ncco = [

            {
                "action": "talk",
                "text": "Hello. This is your AI assistant. Please speak.",
                "language": "en-US"
            },

            {
                "action": "input",
                "type": ["speech"],
                "speech": {
                    "language": "en-US",
                    "endOnSilence": 3,
                    "maxDuration": 60
                },
                "eventUrl": [
                    f"{RENDER_URL}/event"
                ],
                "eventMethod": "POST"
            }

        ]

        call = CreateCallRequest(

            to=[
                {
                    "type": "phone",
                    "number": to_number
                }
            ],

            from_={
                "type": "phone",
                "number": VOICE_FROM_NUMBER
            },

            ncco=ncco

        )

        response = vonage_client.voice.create_call(call)

        print("CALL:", response)

        call_log.append(
            {"to": to_number}
        )

        return True

    except Exception as e:

        print("CALL ERROR:", e)

        return False


# =========================
# EVENT (speech)
# =========================

@app.post("/event")
async def event(req: Request):

    data = await req.json()

    print("EVENT:", data)

    speech = ""

    try:

        speech = data["speech"]["results"][0]["text"]

    except:
        speech = ""


    if not speech:

        text = "I did not hear you. Please speak again."

    else:

        text = ai_response(speech)


    ncco = [

        {
            "action": "talk",
            "text": text,
            "bargeIn": True
        },

        {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": "en-US",
                "endOnSilence": 3,
                "maxDuration": 60
            },
            "eventUrl": [
                f"{RENDER_URL}/event"
            ],
            "eventMethod": "POST"
        }

    ]

    return JSONResponse(ncco)


# =========================
# INBOUND WHATSAPP
# =========================

@app.post("/inbound")
async def inbound(req: Request):

    data = await req.json()

    print("INBOUND:", data)

    sender = data.get("from")

    text = data.get("text", "")

    if not text and "message" in data:

        text = data["message"].get(
            "content", {}
        ).get("text", "")

    text = (text or "").lower().strip()

    if not sender:
        return {"ok": False}


    # CALL

    if text == "call":

        to = sender

        if not to.startswith("+"):
            to = "+" + to

        await make_call(to)


    # AI

    else:

        reply = ai_response(text)

        print(reply)


    return {"ok": True}


# =========================
# UI
# =========================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):

    return templates.TemplateResponse(

        "index.html",

        {
            "request": request,
            "calls": call_log
        }

    )


# =========================
# STATUS
# =========================

@app.get("/status")
async def status():

    return {
        "calls": len(call_log)
    }


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False
    )
