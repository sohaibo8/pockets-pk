from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import re
import requests
import json

app = FastAPI()

ULTRAMSG_TOKEN = "mas9ab8b30m7ardd"
ULTRAMSG_INSTANCE = "instance176624"
WHATSAPP_NUMBER = "+923335148886"

# Default pocket budgets
DEFAULT_POCKETS = {
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

POCKETS_FILE = "/tmp/pockets.json"
TRANSACTION_FILE = "/tmp/last_transaction.json"


def load_pockets():
    try:
        with open(POCKETS_FILE, "r") as f:
            return json.load(f)
    except:
        save_pockets(DEFAULT_POCKETS)
        return DEFAULT_POCKETS


def save_pockets(p):
    with open(POCKETS_FILE, "w") as f:
        json.dump(p, f)


def load_transaction():
    try:
        with open(TRANSACTION_FILE, "r") as f:
            return json.load(f)
    except:
        return {"amount": 0, "merchant": "", "pending": False}


def save_transaction(t):
    with open(TRANSACTION_FILE, "w") as f:
        json.dump(t, f)


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
        r = requests.post(url, data=payload, timeout=10)
        print(f"WhatsApp response: {r.status_code} {r.text}")
    except Exception as e:
        print(f"WhatsApp error: {e}")


def build_pocket_menu(amount: float, merchant: str, pockets: dict) -> str:
    lines = [
        f"💳 *PKR {amount:,.0f}* charged at *{merchant}*",
        "",
        "Which pocket? Reply with a number:",
        "",
    ]
    for i, (name, data) in enumerate(pockets.items(), 1):
        remaining = data['budget'] - data['spent']
        if remaining <= 0:
            emoji = "🔴"
        elif remaining < data['budget'] * 0.2:
            emoji = "🟡"
        else:
            emoji = "🟢"
        lines.append(f"{i}. {name} {emoji}  PKR {remaining:,.0f} left")
    lines.append("")
    lines.append("0. Skip")
    return "\n".join(lines)


def build_status(pockets: dict) -> str:
    lines = ["📊 *Pockets PK — Balance*", ""]
    for name, data in pockets.items():
        remaining = data['budget'] - data['spent']
        percent = int((data['spent'] / data['budget']) * 100) if data['budget'] > 0 else 0
        if remaining < 0:
            emoji = "🔴"
            status = f"PKR {abs(remaining):,.0f} over budget"
        elif percent > 70:
            emoji = "🟡"
            status = f"PKR {remaining:,.0f} left"
        else:
            emoji = "🟢"
            status = f"PKR {remaining:,.0f} left"
        lines.append(f"{emoji} *{name}*: {status} ({percent}% used)")
    total_budget = sum(d['budget'] for d in pockets.values())
    total_spent = sum(d['spent'] for d in pockets.values())
    lines.append("")
    lines.append(f"💰 *Total spent:* PKR {total_spent:,.0f} of PKR {total_budget:,.0f}")
    return "\n".join(lines)


@app.post("/sms")
async def receive_sms(request: Request):
    sms = ""
    try:
        raw = await request.body()
        raw_str = raw.decode("utf-8")
        print(f"Raw SMS: {raw_str}")
        try:
            body = json.loads(raw_str)
            sms = body.get("sms", "")
        except:
            match = re.search(r'"sms"\s*:\s*"(.+?)"(?:,|})', raw_str)
            if match:
                sms = match.group(1)
            else:
                sms = raw_str
    except Exception as e:
        print(f"SMS parse error: {e}")

    print(f"SMS text: {sms}")
    amount, merchant = parse_sms(sms)
    print(f"Amount: {amount} | Merchant: {merchant}")

    if amount > 0:
        pockets = load_pockets()
        t = {"amount": amount, "merchant": merchant, "pending": True}
        save_transaction(t)
        send_whatsapp(build_pocket_menu(amount, merchant, pockets))
    
    return JSONResponse({"status": "ok", "amount": amount, "merchant": merchant})


@app.post("/reply")
async def receive_reply(request: Request):
    message = ""
    try:
        raw = await request.body()
        raw_str = raw.decode("utf-8")
        print(f"Raw reply: {raw_str}")

        body = json.loads(raw_str)
        data = body.get("data", {})
        msg_type = data.get("type", "")
        message = data.get("body", "").strip()
        from_me = data.get("fromMe", False)
        sender = data.get("from", "")

        print(f"Type:{msg_type} | FromMe:{from_me} | Sender:{sender} | Message:{message}")

        self_msg = data.get("self", False)
        
        # Ignore messages sent BY the bot (self:true means bot's own outgoing message)
        if self_msg:
            print("Ignored — bot's own outgoing message")
            return JSONResponse({"status": "ignored"})

        # Only process chat messages from your number
        is_yours = "923335148886" in sender
        if msg_type != "chat" or not is_yours:
            print("Ignored — not your text message")
            return JSONResponse({"status": "ignored"})

    except Exception as e:
        print(f"Reply parse error: {e}")
        return JSONResponse({"status": "error"})

    # Clean message
    message = message.strip().rstrip(".").strip()
    print(f"Processing: '{message}'")

    # STATUS command
    if message.lower() == "status":
        pockets = load_pockets()
        send_whatsapp(build_status(pockets))
        return JSONResponse({"status": "ok"})

    # RESET command
    if message.lower() == "reset":
        save_pockets(DEFAULT_POCKETS)
        save_transaction({"amount": 0, "merchant": "", "pending": False})
        send_whatsapp("🔄 All pockets reset to full budget. New month started!")
        return JSONResponse({"status": "reset"})

    # Check pending transaction
    t = load_transaction()
    if not t.get("pending"):
        send_whatsapp("No pending transaction.\n\nSend *status* to see your balances.")
        return JSONResponse({"status": "no_pending"})

    pockets = load_pockets()
    pocket_names = list(pockets.keys())

    # SKIP
    if message == "0":
        t["pending"] = False
        save_transaction(t)
        send_whatsapp("✅ Transaction skipped.")
        return JSONResponse({"status": "skipped"})

    # ASSIGN TO POCKET
    if message in [str(i) for i in range(1, len(pocket_names) + 1)]:
        pocket_name = pocket_names[int(message) - 1]
        amount = t["amount"]
        merchant = t.get("merchant", "")

        pockets[pocket_name]["spent"] += amount
        save_pockets(pockets)

        t["pending"] = False
        save_transaction(t)

        remaining = pockets[pocket_name]["budget"] - pockets[pocket_name]["spent"]
        
        if remaining < 0:
            balance_msg = f"⚠️ Over budget by PKR {abs(remaining):,.0f}"
        elif remaining < pockets[pocket_name]["budget"] * 0.2:
            balance_msg = f"🟡 PKR {remaining:,.0f} remaining — running low"
        else:
            balance_msg = f"✅ PKR {remaining:,.0f} remaining"

        send_whatsapp(
            f"✅ *PKR {amount:,.0f}* → *{pocket_name}*\n"
            f"{balance_msg}\n\n"
            f"Send *status* to see all pockets."
        )
        return JSONResponse({"status": "ok", "pocket": pocket_name, "remaining": remaining})

    # Invalid input
    send_whatsapp("Please reply with a number 1–9 or 0 to skip.")
    return JSONResponse({"status": "invalid"})


@app.get("/")
async def root():
    return {"message": "Pockets PK is running ✅"}


@app.get("/status")
async def get_status():
    return JSONResponse(load_pockets())
