from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import re
import requests
import json

app = FastAPI()

ULTRAMSG_TOKEN = "mas9ab8b30m7ardd"
ULTRAMSG_INSTANCE = "instance176624"
WHATSAPP_NUMBER = "+923335148886"

pockets = {
    "Groceries":      {"budget": 30000, "spent": 0},
    "Eating out":     {"budget": 20000, "spent": 0},
    "Petrol":         {"budget": 25000, "spent": 0},
    "Emergency Fund": {"budget": 30000, "spent": 0},
    "Investments":    {"budget": 40000, "spent": 0},
    "Gym":            {"budget": 7000,  "spent": 0},
    "Flex":           {"budget": 15863, "spent": 0},
    "Wife":           {"budget": 15000, "spent": 0},
    "Ami":            {"budget": 15000, "spent": 0},
}

last_transaction = {"amount": 0, "merchant": "", "pending": False}


def parse_sms(sms: str):
    amount = 0
    merchant = "Unknown"
    amount_match = re.search(r'PKR\s?([\d,]+\.?\d*)', sms)
    if amount_match:
        amount = float(amount_match.group(1).replace(',', ''))
    merchant_match = re.search(r'charged at (.+?) via', sms)
    if merchant_match:
        merchant = merchant_match.group(1).strip()
    if not merchant_match:
        sent_match = re.search(r'sent to (.+?) from', sms)
        if sent_match:
            merchant = sent_match.group(1).strip()
    return amount, merchant


def send_whatsapp(message: str):
    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat"
    payload = {
        "token": ULTRAMSG_TOKEN,
        "to": WHATSAPP_NUMBER,
        "body": message
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"WhatsApp error: {e}")


def pocket_menu(amount: float, merchant: str) -> str:
    lines = [
        f"💳 *PKR {amount:,.0f}* at {merchant}",
        "",
        "Which pocket? Reply with number:",
        "",
    ]
    for i, (name, data) in enumerate(pockets.items(), 1):
        remaining = data['budget'] - data['spent']
        emoji = "🔴" if remaining < amount else "🟡" if remaining < data['budget'] * 0.3 else "🟢"
        lines.append(f"{i}. {name} {emoji} — PKR {remaining:,.0f} left")
    lines.append("")
    lines.append("0. Skip / Not a spend")
    return "\n".join(lines)


def pocket_status() -> str:
    lines = ["📊 *Pockets PK — Balance*", ""]
    total_budget = 0
    total_spent = 0
    for name, data in pockets.items():
        remaining = data['budget'] - data['spent']
        percent = int((data['spent'] / data['budget']) * 100) if data['budget'] > 0 else 0
        emoji = "🔴" if remaining < 0 else "🟡" if percent > 70 else "🟢"
        total_budget += data['budget']
        total_spent += data['spent']
        lines.append(f"{emoji} *{name}*: PKR {remaining:,.0f} left ({percent}% used)")
    lines.append("")
    lines.append(f"💰 Total: PKR {total_budget - total_spent:,.0f} of PKR {total_budget:,.0f} remaining")
    return "\n".join(lines)


@app.post("/sms")
async def receive_sms(request: Request):
    sms = ""
    try:
        raw = await request.body()
        raw_str = raw.decode("utf-8")
        print(f"Raw SMS body: {raw_str}")
        
        # Try JSON first
        try:
            body = json.loads(raw_str)
            sms = body.get("sms", "")
        except:
            # Try extracting sms field from malformed JSON or form data
            sms_match = re.search(r'"sms"\s*:\s*"(.+?)"(?:,|})', raw_str)
            if sms_match:
                sms = sms_match.group(1)
            else:
                sms = raw_str
    except Exception as e:
        print(f"Error: {e}")

    print(f"SMS: {sms}")
    amount, merchant = parse_sms(sms)
    print(f"Amount: {amount}, Merchant: {merchant}")

    if amount > 0:
        last_transaction["amount"] = amount
        last_transaction["merchant"] = merchant
        last_transaction["pending"] = True
        send_whatsapp(pocket_menu(amount, merchant))

    return JSONResponse({"status": "ok", "amount": amount, "merchant": merchant})


@app.post("/reply")
async def receive_reply(request: Request):
    message = ""
    try:
        raw = await request.body()
        raw_str = raw.decode("utf-8")
        print(f"Raw reply body: {raw_str}")

        # Try JSON
        try:
            body = json.loads(raw_str)
            # UltraMsg sends message in 'body' field inside 'data' or directly
            if "data" in body:
                message = body["data"].get("body", "")
            else:
                message = body.get("body", "")
        except:
            # Try form data
            from urllib.parse import parse_qs
            params = parse_qs(raw_str)
            if "body" in params:
                message = params["body"][0]
            else:
                message = raw_str

        message = message.strip()
        print(f"Reply message: {message}")

    except Exception as e:
        print(f"Reply error: {e}")

    if message.lower() == "status":
        send_whatsapp(pocket_status())
        return JSONResponse({"status": "ok"})

    if message.lower() == "reset":
        for name in pockets:
            pockets[name]["spent"] = 0
        send_whatsapp("🔄 All pockets reset! New month started.")
        return JSONResponse({"status": "reset"})

    if not last_transaction["pending"]:
        send_whatsapp("No pending transaction. Send *status* to see balances.")
        return JSONResponse({"status": "no_pending"})

    pocket_names = list(pockets.keys())

    if message == "0":
        last_transaction["pending"] = False
        send_whatsapp("✅ Transaction skipped.")
        return JSONResponse({"status": "skipped"})

    if message in [str(i) for i in range(1, len(pocket_names) + 1)]:
        pocket_name = pocket_names[int(message) - 1]
        amount = last_transaction["amount"]
        pockets[pocket_name]["spent"] += amount
        last_transaction["pending"] = False
        remaining = pockets[pocket_name]["budget"] - pockets[pocket_name]["spent"]
        warning = " ⚠️ Running low!" if remaining < pockets[pocket_name]["budget"] * 0.2 else ""
        send_whatsapp(
            f"✅ PKR {amount:,.0f} → *{pocket_name}*\n"
            f"PKR {remaining:,.0f} remaining{warning}"
        )
        return JSONResponse({"status": "ok", "pocket": pocket_name})

    send_whatsapp("Please reply with a number 1-9 or 0 to skip.")
    return JSONResponse({"status": "invalid"})


@app.get("/status")
async def get_status():
    return JSONResponse(pockets)


@app.get("/")
async def root():
    return {"message": "Pockets PK is running ✅"}

