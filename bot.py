import os
import json
import re
from datetime import date
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

CONFIG_FILE = "config.json"

DEFAULT_CATEGORIES = {
    "Hogar":         ["alquiler", "expensas", "luz", "gas", "agua", "internet", "supermercado"],
    "Personales":    ["ropa", "salud", "gimnasio", "higiene", "ocio", "electronica", "monitor", "notebook", "celular", "tablet"],
    "Hormiga":       ["cafe", "café", "transporte", "kiosco", "delivery", "uber", "taxi"],
    "Mascotas":      ["alimento", "bano", "baño", "veterinaria", "accesorios"],
    "Hijos":         ["colegio", "club", "utiles", "útiles", "actividades"],
    "Deudas/Cuotas": ["tarjeta", "credito personal", "crédito personal"],
}

# ── Config ──────────────────────────────────────────────────────────────────


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"categories": {k: list(v) for k, v in DEFAULT_CATEGORIES.items()}}


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

# ── Google Sheets ────────────────────────────────────────────────────────────


def sheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    return gspread.authorize(creds)


def get_or_create_sheet(month_name: str):
    client = sheets_client()
    ss = client.open_by_key(GOOGLE_SHEET_ID)
    try:
        sh = ss.worksheet(month_name)
    except gspread.exceptions.WorksheetNotFound:
        sh = ss.add_worksheet(title=month_name, rows=1000, cols=6)
        sh.append_row(["Fecha", "Categoría", "Concepto", "Monto", "Cuota", "Tipo"])
    return sh

# ── Helpers ──────────────────────────────────────────────────────────────────


def is_authorized(update: Update) -> bool:
    allowed = [int(x.strip()) for x in os.getenv("TELEGRAM_CHAT_ID", "").split(",")]
    return update.effective_user.id in allowed


def detect_category(concepto: str, config: dict) -> str:
    concepto_lower = concepto.lower()
    for cat, keywords in config["categories"].items():
        if cat == "Deudas/Cuotas":
            continue
        for kw in keywords:
            if kw.lower() in concepto_lower:
                return cat
    return "Hormiga"


def parse_expense(text: str):
    """
    Returns (monto, concepto, cuotas, mes_inicio)
    mes_inicio: 0 = mes actual (default)
    """
    # monto Nc+Xm concepto  → cuotas con mes de inicio X meses adelante
    m = re.match(r'^(\d+(?:[.,]\d+)?)\s+(\d+)[cC]\+(\d+)[mM]\s+(.+)$', text.strip())
    if m:
        return float(m.group(1).replace(',', '.')), m.group(4).strip(), int(m.group(2)), int(m.group(3))

    # monto Nc concepto
    m = re.match(r'^(\d+(?:[.,]\d+)?)\s+(\d+)[cC]\s+(.+)$', text.strip())
    if m:
        return float(m.group(1).replace(',', '.')), m.group(3).strip(), int(m.group(2)), 0

    # monto concepto
    m = re.match(r'^(\d+(?:[.,]\d+)?)\s+(.+)$', text.strip())
    if m:
        return float(m.group(1).replace(',', '.')), m.group(2).strip(), None, 0

    return None, None, None, 0

# ── Confirmation flow ────────────────────────────────────────────────────────


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    p = context.user_data['pending']
    monto = p['monto']
    concepto = p['concepto']
    cuotas = p['cuotas']
    categoria = p['categoria']
    mes_inicio = p.get('mes_inicio', 0)

    cuota_str = f" ({cuotas} cuotas)" if cuotas else ""
    mes_str = f" — inicio en {mes_inicio} mes(es)" if mes_inicio else ""
    text = (
        f"💰 *${monto:,.0f}* — {concepto}{cuota_str}{mes_str}\n"
        f"📂 Categoría: *{categoria}*\n\n¿Confirmar?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancelar",  callback_data="cancel"),
        ],
        [InlineKeyboardButton("📂 Cambiar categoría", callback_data="change_cat")],
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def show_categories_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    cats = list(config["categories"].keys())
    keyboard = []
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(cats[i], callback_data=f"cat:{cats[i]}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(cats[i + 1], callback_data=f"cat:{cats[i+1]}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("← Volver", callback_data="back")])
    await update.callback_query.edit_message_text(
        "📂 Elegí una categoría:", reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ── Save expense ─────────────────────────────────────────────────────────────


async def save_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = context.user_data.pop('pending')
    monto = p['monto']
    concepto = p['concepto']
    cuotas = p['cuotas']
    categoria = p['categoria']
    mes_inicio = p.get('mes_inicio', 0)

    base_month = date.today().replace(day=1) + relativedelta(months=mes_inicio)

    if cuotas:
        for i in range(cuotas):
            target_month = base_month + relativedelta(months=i)
            sheet_name = target_month.strftime("%Y-%m")
            fecha_str = target_month.strftime("%Y-%m-%d")
            tipo = "real" if i == 0 else "informativo"
            sh = get_or_create_sheet(sheet_name)
            sh.append_row([fecha_str, categoria, concepto, monto, f"{i+1}/{cuotas}", tipo])
        msg = f"✅ *${monto:,.0f}* — {concepto} ({cuotas} cuotas)\n📂 {categoria}"
    else:
        fecha_str = date.today().strftime("%Y-%m-%d")
        sheet_name = date.today().strftime("%Y-%m")
        sh = get_or_create_sheet(sheet_name)
        sh.append_row([fecha_str, categoria, concepto, monto, "", "real"])
        msg = f"✅ *${monto:,.0f}* — {concepto}\n📂 {categoria}"

    await update.callback_query.edit_message_text(msg, parse_mode="Markdown")

# ── Handlers ─────────────────────────────────────────────────────────────────


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    text = update.message.text.strip()
    monto, concepto, cuotas, mes_inicio = parse_expense(text)

    if monto is None:
        await update.message.reply_text(
            "No entendí. Formatos válidos:\n"
            "`1500 café`\n"
            "`60000 6c zapatillas`\n"
            "`60000 6c+1m zapatillas` (empieza el mes que viene)",
            parse_mode="Markdown"
        )
        return

    config = load_config()
    categoria = "Deudas/Cuotas" if cuotas else detect_category(concepto, config)

    context.user_data['pending'] = {
        'monto': monto, 'concepto': concepto,
        'cuotas': cuotas, 'categoria': categoria,
        'mes_inicio': mes_inicio,
    }
    await show_confirmation(update, context)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        await save_expense(update, context)
    elif query.data == "cancel":
        context.user_data.pop('pending', None)
        await query.edit_message_text("❌ Gasto cancelado.")
    elif query.data == "change_cat":
        await show_categories_keyboard(update, context)
    elif query.data == "back":
        await show_confirmation(update, context, edit=True)
    elif query.data.startswith("cat:"):
        context.user_data['pending']['categoria'] = query.data[4:]
        await show_confirmation(update, context, edit=True)

# ── Commands ─────────────────────────────────────────────────────────────────


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    today = date.today()
    fecha_str = today.strftime("%Y-%m-%d")
    sheet_name = today.strftime("%Y-%m")

    try:
        sh = get_or_create_sheet(sheet_name)
        records = sh.get_all_records()
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return

    gastos = [r for r in records if r.get("Fecha") == fecha_str and r.get("Tipo") != "informativo"]
    if not gastos:
        await update.message.reply_text(f"Sin gastos hoy ({fecha_str}).")
        return

    total = sum(float(r["Monto"]) for r in gastos)
    lines = [f"📅 *{fecha_str}*\n"]
    for r in gastos:
        cuota = f" [{r['Cuota']}]" if r.get("Cuota") else ""
        lines.append(f"• {r['Concepto']}{cuota} — *${float(r['Monto']):,.0f}* ({r['Categoría']})")
    lines.append(f"\n💰 *Total: ${total:,.0f}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    sheet_name = date.today().strftime("%Y-%m")

    try:
        sh = get_or_create_sheet(sheet_name)
        records = sh.get_all_records()
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return

    gastos = [r for r in records if r.get("Tipo") != "informativo"]
    if not gastos:
        await update.message.reply_text(f"Sin gastos en {sheet_name}.")
        return

    by_cat = {}
    for r in gastos:
        cat = r.get("Categoría", "Sin categoría")
        by_cat[cat] = by_cat.get(cat, 0) + float(r.get("Monto", 0))

    total = sum(by_cat.values())
    sorted_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)

    lines = [f"📊 *Resumen {sheet_name}*\n"]
    for cat, monto in sorted_cats:
        lines.append(f"• {cat}: *${monto:,.0f}*")
    lines.append(f"\n💰 *Total: ${total:,.0f}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_cuotas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    # Show informativo cuotas for next 6 months
    lines = ["📋 *Cuotas próximos 6 meses*\n"]
    today = date.today().replace(day=1)
    found = False

    for i in range(6):
        target = today + relativedelta(months=i)
        sheet_name = target.strftime("%Y-%m")
        try:
            sh = get_or_create_sheet(sheet_name)
            records = sh.get_all_records()
            info = [r for r in records if r.get("Tipo") == "informativo"]
            if info:
                found = True
                lines.append(f"*{sheet_name}*")
                for r in info:
                    lines.append(f"  • {r['Concepto']} [{r['Cuota']}] — ${float(r['Monto']):,.0f}")
        except Exception:
            pass

    if not found:
        await update.message.reply_text("No hay cuotas pendientes registradas.")
        return
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    config = load_config()
    lines = ["📂 *Categorías:*\n"]
    for cat, kws in config["categories"].items():
        examples = ", ".join(kws[:4]) if kws else "—"
        lines.append(f"• *{cat}*: {examples}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "🤖 *Bot de Gastos*\n\n"
        "*Registrar:*\n"
        "`1500 café`\n"
        "`60000 6c zapatillas` — 6 cuotas desde este mes\n"
        "`60000 6c+1m zapatillas` — 6 cuotas desde el mes que viene\n\n"
        "*Consultas:*\n"
        "/hoy — gastos del día\n"
        "/mes — resumen del mes\n"
        "/cuotas — cuotas próximos meses\n"
        "/categorias — categorías configuradas\n\n"
        "*Categorías:*\n"
        "`/addcategoria Hogar netflix`\n"
        "`/delcategoria Hogar netflix`\n"
        "`/addcat Suscripciones`\n"
        "`/delcat Suscripciones`",
        parse_mode="Markdown"
    )


async def cmd_addcategoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: `/addcategoria Categoria keyword`", parse_mode="Markdown")
        return
    cat, keyword = args[0], " ".join(args[1:]).lower()
    config = load_config()
    if cat not in config["categories"]:
        await update.message.reply_text(f"'{cat}' no existe. Creala con /addcat")
        return
    if keyword not in config["categories"][cat]:
        config["categories"][cat].append(keyword)
        save_config(config)
        await update.message.reply_text(f"✅ '{keyword}' agregado a {cat}")
    else:
        await update.message.reply_text(f"'{keyword}' ya existe en {cat}")


async def cmd_delcategoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Uso: `/delcategoria Categoria keyword`", parse_mode="Markdown")
        return
    cat, keyword = args[0], " ".join(args[1:]).lower()
    config = load_config()
    if cat not in config["categories"]:
        await update.message.reply_text(f"'{cat}' no existe.")
        return
    if keyword in config["categories"][cat]:
        config["categories"][cat].remove(keyword)
        save_config(config)
        await update.message.reply_text(f"✅ '{keyword}' eliminado de {cat}")
    else:
        await update.message.reply_text(f"'{keyword}' no existe en {cat}")


async def cmd_addcat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: `/addcat NombreCategoria`", parse_mode="Markdown")
        return
    cat = " ".join(context.args)
    config = load_config()
    if cat in config["categories"]:
        await update.message.reply_text(f"'{cat}' ya existe.")
        return
    config["categories"][cat] = []
    save_config(config)
    await update.message.reply_text(f"✅ Categoría '{cat}' creada.")


async def cmd_delcat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: `/delcat NombreCategoria`", parse_mode="Markdown")
        return
    cat = " ".join(context.args)
    config = load_config()
    if cat not in config["categories"]:
        await update.message.reply_text(f"'{cat}' no existe.")
        return
    del config["categories"][cat]
    save_config(config)
    await update.message.reply_text(f"✅ Categoría '{cat}' eliminada.")

# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("hoy",           cmd_hoy))
    app.add_handler(CommandHandler("mes",           cmd_mes))
    app.add_handler(CommandHandler("cuotas",        cmd_cuotas))
    app.add_handler(CommandHandler("categorias",    cmd_categorias))
    app.add_handler(CommandHandler("ayuda",         cmd_ayuda))
    app.add_handler(CommandHandler("addcategoria",  cmd_addcategoria))
    app.add_handler(CommandHandler("delcategoria",  cmd_delcategoria))
    app.add_handler(CommandHandler("addcat",        cmd_addcat))
    app.add_handler(CommandHandler("delcat",        cmd_delcat))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot iniciado...")
    app.run_polling()


if __name__ == "__main__":
    main()
