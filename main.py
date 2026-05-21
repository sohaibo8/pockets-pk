from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import re
import requests

app = FastAPI()

# UltraMsg config
ULTRAMSG_TOKEN = "mas9ab8b30m7ardd"
ULTRAMSG_INSTANCE = "instance176624"
WHATSAPP_NUMBER = "+923335148886"

# 9 Pockets
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

# Last transaction waiting for pocket assignment
last_transaction = {"amount": 0, "merchant": "", "pending": False}


def parse_sms(sms: str):
    amount = 0
    merchant = "Unknown"

    # Extract PKR amount — handles PKR1,161.00 or PKR 1,161.00
    amount_match = re.search(r'PKR\s?([\d,]+\.?\d*)', sms)
    if amount_match:
        amount = float(amount_match.group(1).replace(',', ''))

    # 6222 format: charged at MERCHANT via
    merchant_match = re.search(r'charged at (.+?) via', sms)
    if merchant_match:
        merchant = merchant_match.group(1).strip()

    # 8222 format: sent to MERCHANT from
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
    body = await request.json()
    sms = body.get("sms", "")
    print(f"Received SMS: {sms}")

    amount, merchant = parse_sms(sms)

    if amount > 0:
        last_transaction["amount"] = amount
        last_transaction["merchant"] = merchant
        last_transaction["pending"] = True
        send_whatsapp(pocket_menu(amount, merchant))

    return JSONResponse({"status": "ok", "amount": amount, "merchant": merchant})


@app.post("/reply")
async def receive_reply(request: Request):
    body = await request.json()
    message = body.get("body", "").strip()

    # Show status anytime
    if message.lower() == "status":
        send_whatsapp(pocket_status())
        return JSONResponse({"status": "ok"})

    # Reset pockets
    if message.lower() == "reset":
        for name in pockets:
            pockets[name]["spent"] = 0
        send_whatsapp("🔄 All pockets reset! New month started.")
        return JSONResponse({"status": "reset"})

    if not last_transaction["pending"]:
        send_whatsapp("No pending transaction. Send *status* to see balances.")
        return JSONResponse({"status": "no_pending"})

    pocket_names = list(pockets.keys())

    # Skip
    if message == "0":
        last_transaction["pending"] = False
        send_whatsapp("✅ Transaction skipped.")
        return JSONResponse({"status": "skipped"})

    # Assign to pocket
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


@app.post("/reset")
async def reset_pockets():
    for name in pockets:
        pockets[name]["spent"] = 0
    send_whatsapp("🔄 All pockets reset! Salary day activated.")
    return JSONResponse({"status": "reset"})


@app.get("/")
async def root():
    return {"message": "Pockets PK is running ✅"}

