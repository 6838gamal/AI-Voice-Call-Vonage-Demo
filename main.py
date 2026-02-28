import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import uvicorn

from vonage import Client as VonageClient
from google import genai

# ======================
# ENV
# ======================

load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")

VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")

BASE_URL = os.getenv("BASE_URL")

PORT = int(os.getenv("PORT", 3000))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ======================
# APP
# ======================

app = FastAPI()

client = VonageClient(
    application_id=APP_ID,
    private_key=PRIVATE_KEY_PATH,
)

gemini = genai.Client(api_key=GEMINI_API_KEY)


# ======================
# AI
# ======================

def ai_response(text):

    r = gemini.models.generate_content(
        model="gemini-3.5-flash",
        contents=text,
    )

    return r.text


# ======================
# INBOUND
# ======================

@app.post("/inbound")
async def inbound(req: Request):

    data = await req.json()

    text = (data.get("text") or "").strip()

    sender = data.get("from")

    if text.lower() == "call":

        make_call(sender)

    return JSONResponse({"ok": True})


# ======================
# MAKE CALL
# ======================

def make_call(number):

    client.voice.create_call({

        "to": [
            {
                "type": "phone",
                "number": number
            }
        ],

        "from": {
            "type": "phone",
            "number": VOICE_FROM_NUMBER
        },

        "answer_url": [
            f"{BASE_URL}/answer"
        ]

    })


# ======================
# ANSWER
# ======================

@app.get("/answer")
async def answer():

    ncco = [

        {
            "action": "talk",
            "text": "Hello, you are talking with AI assistant"
        },

        {
            "action": "input",
            "type": ["speech"],
            "eventUrl": [f"{BASE_URL}/speech"],
            "speech": {
                "endOnSilence": 1,
                "language": "en-US"
            }
        }

    ]

    return JSONResponse(ncco)


# ======================
# SPEECH
# ======================

@app.post("/speech")
async def speech(req: Request):

    data = await req.json()

    speech_text = ""

    if "speech" in data:

        speech_text = data["speech"]["results"][0]["text"]

    if not speech_text:

        speech_text = "hello"

    ai = ai_response(speech_text)

    ncco = [

        {
            "action": "talk",
            "text": ai
        },

        {
            "action": "input",
            "type": ["speech"],
            "eventUrl": [f"{BASE_URL}/speech"],
            "speech": {
                "endOnSilence": 1,
                "language": "en-US"
            }
        }

    ]

    return JSONResponse(ncco)


# ======================
# STATUS
# ======================

@app.post("/status")
async def status():
    return JSONResponse({"ok": True})


# ======================
# MAIN
# ======================

def main():
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
    )


if __name__ == "__main__":
    main()
