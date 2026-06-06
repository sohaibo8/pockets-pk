from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import re
import json
from datetime import datetime, timedelta

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

POCKETS_FILE = "/tmp/pockets.json"
TRANSACTION_FILE = "/tmp/last_transaction.json"
LOG_FILE = "/tmp/transaction_log.json"
MERCHANT_FILE = "/tmp/merchant_memory.json"

DEFAULT_POCKETS = {
    "Groceries":      {"budget": 30000, "spent": 0},
    "Eating Out":     {"budget": 25000, "spent": 0},
    "Petrol":         {"budget": 25000, "spent": 0},
    "Emergency Fund": {"budget": 30000, "spent": 0},
    "Investments":    {"budget": 40000, "spent": 0},
    "Gym":            {"budget": 7000,  "spent": 0},
    "Subscriptions":  {"budget": 6000,  "spent": 0},
    "Flex":           {"budget": 4000,  "spent": 0},
    "Wife":           {"budget": 15000, "spent": 0},
    "Ami":            {"budget": 15000, "spent": 0},
    "Donation":       {"budget": 20000, "spent": 0},
}

def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f)

def load_pockets(): return load_json(POCKETS_FILE, DEFAULT_POCKETS.copy())
def save_pockets(p): save_json(POCKETS_FILE, p)
def load_transaction(): return load_json(TRANSACTION_FILE, {"amount":0,"merchant":"","pending":False})
def save_transaction(t): save_json(TRANSACTION_FILE, t)
def load_log(): return load_json(LOG_FILE, [])
def save_log(l): save_json(LOG_FILE, l)
def load_merchant_memory(): return load_json(MERCHANT_FILE, {})
def save_merchant_memory(m): save_json(MERCHANT_FILE, m)

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
        sent_match = re.search(r'sent to (.+?)(?:\s+from|\s+via)', sms)
        if sent_match:
            merchant = sent_match.group(1).strip()
    return amount, merchant

def log_transaction(amount, merchant, pocket_name):
    log = load_log()
    log.append({
        "date": datetime.now().isoformat(),
        "amount": amount,
        "merchant": merchant,
        "pocket": pocket_name
    })
    save_log(log)

@app.get("/", response_class=HTMLResponse)
async def serve_app():
    with open("static/index.html") as f:
        return HTMLResponse(f.read())

@app.get("/manifest.json")
async def manifest():
    return FileResponse("static/manifest.json")

@app.get("/sw.js")
async def sw():
    return FileResponse("static/sw.js")

@app.post("/sms")
async def receive_sms(request: Request):
    sms = ""
    try:
        # First check query parameters
        params = dict(request.query_params)
        if "sms" in params and params["sms"] and params["sms"] != "{sms_message}":
            sms = params["sms"]
            print(f"SMS from query params: {sms}")
        else:
            raw = await request.body()
            raw_str = raw.decode("utf-8").strip()
            print(f"Raw SMS body: {raw_str}")
            # Try JSON first
            try:
                body = json.loads(raw_str)
                sms = body.get("sms", raw_str)
            except:
                sms = raw_str
    except Exception as e:
        print(f"SMS error: {e}")

    amount, merchant = parse_sms(sms)
    print(f"Amount: {amount} | Merchant: {merchant}")

    if amount > 0:
        memory = load_merchant_memory()
        if merchant in memory:
            pocket_name = memory[merchant]
            pockets = load_pockets()
            if pocket_name in pockets:
                pockets[pocket_name]["spent"] += amount
                save_pockets(pockets)
                log_transaction(amount, merchant, pocket_name)
                save_transaction({"amount": amount, "merchant": merchant, "pending": False, "auto_assigned": pocket_name})
                print(f"Auto-assigned {merchant} → {pocket_name}")
                return JSONResponse({"status": "auto_assigned", "pocket": pocket_name})
        save_transaction({"amount": amount, "merchant": merchant, "pending": True, "auto_assigned": None})

    return JSONResponse({"status": "ok", "amount": amount, "merchant": merchant})

@app.get("/pending")
async def get_pending():
    return JSONResponse(load_transaction())

@app.post("/assign")
async def assign_pocket(request: Request):
    body = await request.json()
    pocket_num = body.get("pocket")
    t = load_transaction()
    if not t.get("pending"):
        return JSONResponse({"status": "no_pending"})
    pockets = load_pockets()
    pocket_names = list(pockets.keys())
    if pocket_num < 1 or pocket_num > len(pocket_names):
        return JSONResponse({"status": "invalid"})
    pocket_name = pocket_names[pocket_num - 1]
    amount = t["amount"]
    merchant = t["merchant"]
    pockets[pocket_name]["spent"] += amount
    save_pockets(pockets)
    log_transaction(amount, merchant, pocket_name)
    memory = load_merchant_memory()
    memory[merchant] = pocket_name
    save_merchant_memory(memory)
    t["pending"] = False
    save_transaction(t)
    return JSONResponse({"status": "ok", "pocket": pocket_name, "amount": amount})

@app.post("/skip")
async def skip_transaction():
    t = load_transaction()
    t["pending"] = False
    save_transaction(t)
    return JSONResponse({"status": "skipped"})

@app.post("/change")
async def change_assignment(request: Request):
    body = await request.json()
    pocket_num = body.get("pocket")
    pockets = load_pockets()
    pocket_names = list(pockets.keys())
    t = load_transaction()
    old_pocket = t.get("auto_assigned")
    amount = t.get("amount", 0)
    merchant = t.get("merchant", "")
    if old_pocket and old_pocket in pockets:
        pockets[old_pocket]["spent"] -= amount
    new_pocket = pocket_names[pocket_num - 1]
    pockets[new_pocket]["spent"] += amount
    save_pockets(pockets)
    log = load_log()
    for entry in reversed(log):
        if entry["merchant"] == merchant and entry["pocket"] == old_pocket:
            entry["pocket"] = new_pocket
            break
    save_log(log)
    memory = load_merchant_memory()
    memory[merchant] = new_pocket
    save_merchant_memory(memory)
    t["auto_assigned"] = new_pocket
    save_transaction(t)
    return JSONResponse({"status": "ok", "new_pocket": new_pocket})

@app.get("/status")
async def get_status():
    return JSONResponse(load_pockets())

@app.get("/transactions")
async def get_transactions():
    return JSONResponse(load_log())

@app.post("/reset")
async def reset_pockets():
    save_pockets(DEFAULT_POCKETS.copy())
    save_transaction({"amount": 0, "merchant": "", "pending": False})
    return JSONResponse({"status": "reset"})

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
