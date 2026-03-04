import os
import re
import json
import logging
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from vonage import Vonage, Auth
from vonage_voice import CreateCallRequest

# ==================================================
# Logging Configuration
# ==================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================================================
# Load Environment Variables
# ==================================================
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
WHATSAPP_FROM = os.getenv("VONAGE_SANDBOX_NUMBER")
WHATSAPP_TO = os.getenv("REPORT_TO_NUMBER")
BASE_URL = os.getenv("BASE_URL")
PORT = int(os.getenv("PORT", 10000))

# ==================================================
# Validate Environment
# ==================================================
def validate_env():
    required = {
        "VONAGE_APPLICATION_ID": APP_ID,
        "VONAGE_PRIVATE_KEY_PATH": PRIVATE_KEY_PATH,
        "VONAGE_FROM_NUMBER": VOICE_FROM_NUMBER,
        "VONAGE_SANDBOX_NUMBER": WHATSAPP_FROM,
        "REPORT_TO_NUMBER": WHATSAPP_TO,
        "BASE_URL": BASE_URL
    }

    for key, value in required.items():
        if not value:
            logger.error(f"❌ Missing ENV variable: {key}")
        else:
            logger.info(f"✅ {key} loaded")

validate_env()

# ==================================================
# Load Private Key
# ==================================================
try:
    with open(PRIVATE_KEY_PATH, "r") as f:
        PRIVATE_KEY = f.read()
    logger.info("✅ Private key loaded")
except Exception:
    logger.exception("❌ Failed to load private key")

# ==================================================
# Init FastAPI
# ==================================================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ==================================================
# Init Vonage Clients
# ==================================================
try:
    voice_auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
    vonage_voice = Vonage(voice_auth)

    message_auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY)
    vonage_messages = Vonage(message_auth)

    logger.info("✅ Vonage clients initialized")
except Exception:
    logger.exception("❌ Failed to initialize Vonage clients")

call_log = {}

# ==================================================
# Helpers
# ==================================================
def clean_number(number: str):
    return re.sub(r"\D", "", str(number))

def send_whatsapp_report(message: str):
    try:
        logger.info("📤 Sending WhatsApp message...")
        response = vonage_messages.messages.create(
            channel="whatsapp",
            from_=WHATSAPP_FROM,
            to=WHATSAPP_TO,
            message_type="text",
            text={"body": message}
        )
        logger.info(f"✅ WhatsApp sent successfully: {response}")
    except Exception:
        logger.exception("❌ WhatsApp sending failed")

def generate_ncco(text: str):
    return [
        {
            "action": "talk",
            "text": text,
            "language": "en-US"
        }
    ]

# ==================================================
# Routes
# ==================================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "calls": call_log
    })

# ==================================================
# Create Call
# ==================================================
@app.post("/call")
async def make_call(request: Request, phone: str = Form(...)):
    to_num = clean_number(phone)
    logger.info(f"📞 Call requested to: {to_num}")

    try:
        send_whatsapp_report(f"📞 Call requested to {to_num}")

        call_request = CreateCallRequest(
            to=[{"type": "phone", "number": to_num}],
            from_={"type": "phone", "number": VOICE_FROM_NUMBER},
            ncco=generate_ncco("Hello! This is your AI assistant.")
        )

        logger.info("🔹 Sending request to Vonage Voice API...")
        response = vonage_voice.voice.create_call(call_request)

        call_uuid = getattr(response, "uuid", None)

        if call_uuid:
            logger.info(f"✅ Call created: {call_uuid}")
            call_log[call_uuid] = {
                "to": to_num,
                "status": "initiated"
            }
        else:
            logger.warning("⚠️ No UUID returned from Vonage")

    except Exception:
        logger.exception("❌ Call creation failed")
        send_whatsapp_report("❌ Call creation failed. Check logs.")

    return templates.TemplateResponse("index.html", {
        "request": request,
        "calls": call_log
    })

# ==================================================
# Webhook Event Handler
# ==================================================
@app.post("/event")
async def voice_event(request: Request):
    try:
        data = await request.json()
        logger.info(f"📩 Event received: {json.dumps(data)}")

        call_uuid = data.get("uuid")
        status = data.get("status")
        duration = data.get("duration", 0)

        if not call_uuid:
            logger.warning("⚠️ Event without UUID")
            return JSONResponse({"status": "ignored"})

        call_log[call_uuid] = {
            "to": data.get("to"),
            "status": status
        }

        logger.info(f"📊 Call {call_uuid} status: {status}")

        # ==== Handle statuses ====
        if status in ["completed", "disconnected"]:
            send_whatsapp_report(
                f"✅ Call Completed\nID: {call_uuid}\nDuration: {duration}s"
            )

        elif status in ["no-answer", "timeout"]:
            send_whatsapp_report(
                f"⚠️ Call Not Answered\nID: {call_uuid}"
            )

        elif status in ["busy", "rejected"]:
            send_whatsapp_report(
                f"❌ Call Rejected / Busy\nID: {call_uuid}"
            )

        elif status in ["failed"]:
            reason = data.get("reason", "Unknown")
            send_whatsapp_report(
                f"❌ Call Failed\nID: {call_uuid}\nReason: {reason}"
            )

        else:
            send_whatsapp_report(
                f"ℹ️ Call Ended\nStatus: {status}\nID: {call_uuid}"
            )

        return JSONResponse({"status": "ok"})

    except Exception:
        logger.exception("❌ Error processing webhook event")
        return JSONResponse({"status": "error"})

# ==================================================
# Health Check Endpoint
# ==================================================
@app.get("/health")
def health():
    return {
        "status": "running",
        "app_id_loaded": bool(APP_ID),
        "private_key_loaded": bool(PRIVATE_KEY_PATH),
        "voice_number_loaded": bool(VOICE_FROM_NUMBER),
        "whatsapp_loaded": bool(WHATSAPP_FROM)
    }

# ==================================================
# Run
# ==================================================
if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting AI Voice System...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
