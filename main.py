import os
from datetime import datetime, date
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv

# التغيير هنا: استيراد Vonage بدلاً من Client في الإصدارات الحديثة
from vonage import Auth, Vonage
from vonage_voice import CreateCallRequest, Talk, Input, Dtmf

# تحميل متغيرات البيئة
load_dotenv()

APP_ID = os.getenv("VONAGE_APPLICATION_ID")
PRIVATE_KEY_PATH = os.getenv("VONAGE_PRIVATE_KEY_PATH")
VOICE_FROM_NUMBER = os.getenv("VONAGE_FROM_NUMBER")
TO_NUMBER = os.getenv("TO_NUMBER")
BASE_URL = os.getenv("BASE_URL")

app = FastAPI()

# إعداد المصادقة باستخدام الكلاس المحدث
auth = Auth(application_id=APP_ID, private_key=PRIVATE_KEY_PATH)
# في إصدار 4.x الكلاس يسمى Vonage
vonage_client = Vonage(auth)

@app.get("/dial")
async def dial():
    talk_action = Talk(
        text='Hello! Please enter your birthday as two-digit month, two-digit day, and four-digit year, then press pound.',
        loop=1,
        language='en-US'
    )
    
    dtmf_input = Input(
        type=['dtmf'],
        dtmf=Dtmf(timeOut=10, maxDigits=8, submitOnHash=True),
        eventUrl=[f"{BASE_URL}/birthday"],
        eventMethod='POST'
    )
    
    ncco = [talk_action.model_dump(), dtmf_input.model_dump()]

    call = CreateCallRequest(
        to=[{'type': 'phone', 'number': TO_NUMBER}],
        from_={'type': 'phone', 'number': VOICE_FROM_NUMBER} if VOICE_FROM_NUMBER else None,
        random_from_number=True if not VOICE_FROM_NUMBER else False,
        ncco=ncco,
        machine_detection='hangup'
    )

    # استدعاء خدمة الصوت
    response = vonage_client.voice.create_call(call)
    return response.model_dump()

@app.post("/birthday")
async def birthday(request: Request):
    data = await request.json()
    dtmf_digits = data.get("dtmf", {}).get("digits", "")
    
    days_until, next_age = get_birthday_data(dtmf_digits)

    if days_until is None:
        text = 'Invalid birthday format. Please try again later.'
    else:
        text = f"Your birthday is in {days_until} days and you will be {next_age} years old! Thank you for calling."

    talk_response = Talk(text=text, loop=1, language='en-US')
    return [talk_response.model_dump()]

@app.post("/events")
async def events(request: Request):
    return Response(status_code=204)

def get_birthday_data(dtmf_digits: str):
    if len(dtmf_digits) != 8:
        return None, None
    try:
        bday = datetime.strptime(dtmf_digits, "%m%d%Y").date()
        today = date.today()
        
        next_bday = bday.replace(year=today.year)
        if next_bday < today:
            next_bday = next_bday.replace(year=today.year + 1)

        days_until = (next_bday - today).days
        next_age = next_bday.year - bday.year
        return days_until, next_age
    except ValueError:
        return None, None

if __name__ == "__main__":
    import uvicorn
    # التأكد من استخدام منفذ Render الصحيح
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
