import os, json, datetime, asyncio, requests
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CHAT_ID           = os.environ["CHAT_ID"]
META_TOKEN        = os.environ["META_TOKEN"]
AD_ACCOUNT_ID     = os.environ.get("AD_ACCOUNT_ID", "act_2783197798689936")

client      = Anthropic(api_key=ANTHROPIC_API_KEY)
history     = {}
MAX_HISTORY = 30

def send_telegram(text: str) -> str:
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
        return "✅ נשלח" if r.json().get("ok") else f"❌ {r.text}"
    except Exception as e:
        return f"שגיאה: {e}"

def get_campaign_insights(date_preset: str = "yesterday") -> str:
    try:
        url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"
        params = {
            "access_token": META_TOKEN,
            "date_preset": date_preset,
            "fields": "campaign_name,adset_name,spend,impressions,clicks,ctr,cpc,actions,cost_per_action_type",
            "level": "campaign",
            "limit": 20
        }
        r = requests.get(url, params=params)
        data = r.json()
        if "error" in data:
            return f"❌ שגיאת Meta API: {data['error'].get('message', str(data['error']))}"
        campaigns = data.get("data", [])
        if not campaigns:
            return f"אין נתונים ל-{date_preset}"
        result = []
        for c in campaigns:
            leads = next((a["value"] for a in c.get("actions", []) if a["action_type"] in ["lead", "contact", "onsite_conversion.lead_grouped"]), "0")
            msgs  = next((a["value"] for a in c.get("actions", []) if a["action_type"] == "onsite_conversion.messaging_conversation_started_7d"), "0")
            cpl   = round(float(c.get("spend","0")) / max(int(leads),1), 2)
            result.append({
                "קמפיין": c.get("campaign_name",""),
                "הוצאה": f"₪{c.get('spend','0')}",
                "חשיפות": c.get("impressions","0"),
                "קליקים": c.get("clicks","0"),
                "CTR": f"{c.get('ctr','0')}%",
                "לידים": leads,
                "הודעות_WA": msgs,
                "CPL": f"₪{cpl}"
            })
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"שגיאה: {e}"

def get_ads_insights(date_preset: str = "yesterday") -> str:
    try:
        url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"
        params = {
            "access_token": META_TOKEN,
            "date_preset": date_preset,
            "fields": "ad_name,campaign_name,spend,impressions,clicks,actions",
            "level": "ad",
            "limit": 10,
            "sort": "spend_descending"
        }
        r = requests.get(url, params=params)
        data = r.json()
        if "error" in data:
            return f"❌ {data['error'].get('message', str(data['error']))}"
        ads = data.get("data", [])
        if not ads:
            return "אין נתוני מודעות"
        result = []
        for a in ads[:5]:
            leads = next((x["value"] for x in a.get("actions", []) if x["action_type"] in ["lead","contact"]), "0")
            result.append({
                "מודעה": a.get("ad_name","")[:50],
                "קמפיין": a.get("campaign_name","")[:30],
                "הוצאה": f"₪{a.get('spend','0')}",
                "קליקים": a.get("clicks","0"),
                "לידים": leads
            })
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"שגיאה: {e}"

def get_account_summary(date_preset: str = "yesterday") -> str:
    try:
        url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"
        params = {
            "access_token": META_TOKEN,
            "date_preset": date_preset,
            "fields": "spend,impressions,clicks,ctr,cpc,actions",
            "level": "account"
        }
        r = requests.get(url, params=params)
        data = r.json()
        if "error" in data:
            return f"❌ {data['error'].get('message', str(data['error']))}"
        rows = data.get("data", [])
        if not rows:
            return "אין נתונים לתאריך זה"
        d = rows[0]
        leads = next((a["value"] for a in d.get("actions", []) if a["action_type"] in ["lead","contact","onsite_conversion.lead_grouped"]), "0")
        msgs  = next((a["value"] for a in d.get("actions", []) if a["action_type"] == "onsite_conversion.messaging_conversation_started_7d"), "0")
        spend = float(d.get("spend","0"))
        cpl   = round(spend / max(int(leads),1), 2)
        return json.dumps({
            "תקופה": date_preset,
            "הוצאה_כוללת": f"₪{spend}",
            "חשיפות": d.get("impressions","0"),
            "קליקים": d.get("clicks","0"),
            "CTR": f"{d.get('ctr','0')}%",
            "CPC": f"₪{d.get('cpc','0')}",
            "לידים": leads,
            "הודעות_WA": msgs,
            "עלות_ליד": f"₪{cpl}"
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"שגיאה: {e}"

TOOLS = [
    {"name": "get_account_summary", "description": "סיכום כולל של החשבון — הוצאה, קליקים, לידים, CPL", 
     "input_schema": {"type": "object", "properties": {"date_preset": {"type": "string", "description": "yesterday / today / last_7d / last_30d / this_month"}}}},
    {"name": "get_campaign_insights", "description": "נתוני קמפיינים — ביצועים לפי קמפיין",
     "input_schema": {"type": "object", "properties": {"date_preset": {"type": "string"}}}},
    {"name": "get_ads_insights", "description": "Top 5 מודעות לפי הוצאה",
     "input_schema": {"type": "object", "properties": {"date_preset": {"type": "string"}}}},
    {"name": "send_telegram", "description": "שולח הודעה לטלגרם",
     "input_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}}
]

SYSTEM = """אתה סוכן Meta Ads מקצועי בשם META.NEWSITE עובד עבור newsite.co.il — חברה לבניית אתרים לעסקים קטנים ובינוניים בישראל.
חשבון פרסום: act_2783197798689936 (newsite)
תפקידך: לנתח נתוני קמפיינים, לזהות בעיות ולהמליץ על שיפורים.
דוח יומי: הוצאה, לידים, CPL, הקמפיין הכי טוב, ☢️ אם CPL עלה מ-50₪ — התרה.
ענה תמיד בעברית."""

def trim_history(hist):
    if len(hist) > MAX_HISTORY:
        hist = hist[-MAX_HISTORY:]
        while hist and hist[0]["role"] != "user":
            hist.pop(0)
    return hist

def run_tool(name, inp):
    if name == "get_account_summary":   return get_account_summary(inp.get("date_preset","yesterday"))
    if name == "get_campaign_insights": return get_campaign_insights(inp.get("date_preset","yesterday"))
    if name == "get_ads_insights":      return get_ads_insights(inp.get("date_preset","yesterday"))
    if name == "send_telegram":         return send_telegram(inp["text"])
    return "פעולה לא מוכרת"

def run_agent(uid: str, msg: str) -> str:
    if uid not in history: history[uid] = []
    history[uid] = trim_history(history[uid])
    history[uid].append({"role": "user", "content": msg})
    while True:
        resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=2048, system=SYSTEM, tools=TOOLS, messages=history[uid])
        if resp.stop_reason == "end_turn":
            text = next((b.text for b in resp.content if hasattr(b, "text") and b.type == "text"), "✅ בוצע")
            history[uid].append({"role": "assistant", "content": text})
            return text
        if resp.stop_reason == "tool_use":
            history[uid].append({"role": "assistant", "content": resp.content})
            results = [{"type": "tool_result", "tool_use_id": b.id, "content": run_tool(b.name, b.input)} for b in resp.content if b.type == "tool_use"]
            history[uid].append({"role": "user", "content": results})

def run_daily_report():
    print(f"[{datetime.datetime.now()}] 📊 מריץ דוח יומי Meta...")
    run_agent("daily_auto", """הרץ דוח Meta Ads יומי:
1. שלב נתוני חשבון של אתמול
2. שלב נתוני קמפיינים של אתמול
3. שלב Top 5 מודעות
4. שלח דוח לטלגרם בפורמט:

📣 <b>דוח Meta Ads יומי | newsite</b>
📅 [תאריך אתמול]
━━━━━━━━━━━━━━━━━━━━
💰 <b>הוצאה:</b> ₪XX
👥 <b>לידים:</b> XX
💬 <b>הודעות WA:</b> XX
📉 <b>עלות ליד:</b> ₪XX
🖱️ <b>קליקים:</b> XX | CTR: X%
━━━━━━━━━━━━━━━━━━━━
🏆 <b>קמפיין מוביל:</b> [שם] — ₪X לליד
⚠️ <b>שים לב:</b> [תובנה חשובה אחת]
📌 <b>המלצה:</b> [פעולה אחת לשיפור]""")

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = str(update.effective_user.id)
    msg  = update.message.text
    await update.message.reply_text("⏳ META.NEWSITE בודק נתונים...")
    try:
        result = await asyncio.get_event_loop().run_in_executor(None, run_agent, uid, msg)
        for i in range(0, len(result), 4000):
            await update.message.reply_text(result[i:i+4000], parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ שגיאה: {e}")

async def post_init(application: Application):
    scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")
    scheduler.add_job(
        lambda: asyncio.get_event_loop().run_in_executor(None, run_daily_report),
        "cron", hour=8, minute=0
    )
    scheduler.start()
    print("✅ META.NEWSITE פעיל!")

if __name__ == "__main__":
    print("🚀 META.NEWSITE מתחיל...")
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()
