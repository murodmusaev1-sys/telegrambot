"""Dekor Panel: Telegram-bot konsultatsiya, savdo va administrator tizimi (Claude AI asosida)."""
import asyncio
import base64
import hashlib
import html
import json
import logging
import os
import random
import re
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
import httpx
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Konfiguratsiya va loglar
# ---------------------------------------------------------------------------
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("dekor-bot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MANAGER_CHAT_ID_RAW = os.getenv("MANAGER_CHAT_ID", "").strip()
MANAGER_CHAT_ID = int(MANAGER_CHAT_ID_RAW) if MANAGER_CHAT_ID_RAW.isdigit() else None

# Claude model nomini to'g'irlash (xato aliaslarni to'g'ri modelga o'tkazish)
def resolve_model_name(raw_model: str) -> str:
    cleaned = (raw_model or "").strip()
    return cleaned or "claude-haiku-5-5"


MODEL = resolve_model_name(os.getenv("CLAUDE_MODEL", "claude-haiku-5-5"))

BASE_DIR = Path(__file__).parent
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_HISTORY = 30

# Zavod doimiy aloqa ma'lumotlari
MANAGER_PHONE_PRIMARY = "+998 88 130 07 11"
MANAGER_PHONE_WHATSAPP = "+998 99 856 07 11"
MANAGER_USERNAME = "MMB881300711"
CHANNEL_USERNAME = "Dekor_Panel"
INSTAGRAM_PAGE = "dekor_panell"

# ---------------------------------------------------------------------------
# Dinamik konfiguratsiya (Lokatsiya, manzil va h.k.)
# ---------------------------------------------------------------------------
CONFIG_FILE = BASE_DIR / "bot_config.json"

DEFAULT_CONFIG = {
    "location": {
        "lat": 41.2289,
        "lon": 69.3364,
        "address": "Toshkent shahar, Bektemir tumani.",
        "landmark": "Toshkent Coca-Cola zavodi yonida.",
        "work_hours": "Dushanba - Shanba, 09:00 dan 18:00 gacha.",
    }
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("Xatolik bot_config.json o'qishda: %s", e)
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.error("Xatolik bot_config.json saqlashda: %s", e)


def is_admin(user_id: Optional[int]) -> bool:
    """Foydalanuvchi admin yoki menejer ekanligini tekshirish."""
    if not user_id:
        return False
    if MANAGER_CHAT_ID and user_id == MANAGER_CHAT_ID:
        return True
    raw_admins = os.getenv("ADMIN_IDS", "").split(",")
    for a in raw_admins:
        if a.strip().isdigit() and int(a.strip()) == user_id:
            return True
    return False


# Admin sessiyalari va kesh
ADMIN_SESSIONS: dict[int, dict[str, Any]] = defaultdict(dict)
DEL_PHOTO_CACHE: dict[str, Path] = {}

# ---------------------------------------------------------------------------
# Mahsulot toifalari va ularning ma'lumotlari
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, dict[str, Any]] = {
    "alyukobond": {
        "name_uz": "Алюкобонд (Alukabond)",
        "name_ru": "Алюкобонд",
        "aliases": ["alyukobond", "алюкобонд", "alukabond", "alukobond", "alyukabond"],
        "icon": "🏢",
        "desc_uz": "Bir xil rangli, yaltiroq, metallik va yog'och (dub) fakturali panellar. Fasad va interyer uchun.",
        "desc_ru": "Однотонные, глянцевые, металлик и под дерево (дуб) панели. Для фасадов и интерьера.",
    },
    "pvh_paneli": {
        "name_uz": "PVX panellar",
        "name_ru": "ПВХ панели",
        "aliases": ["pvh_paneli", "пвх панели", "пвх", "pvh", "pvx", "pvx panellar"],
        "icon": "🎨",
        "desc_uz": "Marmar tosh, daraxt va zamonaviy abstrakt naqshli, namga chidamli PVX panellar.",
        "desc_ru": "Мраморные, под дерево и с рисунками влагостойкие качественные ПВХ панели.",
    },
    "baget": {
        "name_uz": "Baget",
        "name_ru": "Багет",
        "aliases": ["baget", "багет"],
        "icon": "📐",
        "desc_uz": "Shift va devor tutashgan joylari uchun nafis bezakli bagetlar.",
        "desc_ru": "Элегантные декоративные багеты для стен и потолков.",
    },
    "baget_4x4": {
        "name_uz": "Baget 4x4",
        "name_ru": "Багет 4x4",
        "aliases": ["baget_4x4", "багет 4x4", "baget 4*4"],
        "icon": "📐",
        "desc_uz": "4x4 o'lchamdagi mustahkam va keng dekorativ bagetlar.",
        "desc_ru": "Прочные широкие декоративные багеты формата 4x4.",
    },
    "konechnik": {
        "name_uz": "Profillar (Konechnik, Soedinitel)",
        "name_ru": "Конечники, соединители, углы",
        "aliases": ["konechnik", "конечник", "соединитель", "профили", "углы", "сайдин", "burchak"],
        "icon": "🔩",
        "desc_uz": "Panellarni montaj qilish profillari: конечник, соединитель, burchaklar (oltin, qora, alyuminiy).",
        "desc_ru": "Монтажные профили: конечник, соединитель, внутренние и наружные углы (золото, чёрный, алюминий).",
    },
    "rebro_3d": {
        "name_uz": "Qovurg'a 3D (Ребро 3D)",
        "name_ru": "Ребро 3D (qovurga)",
        "aliases": ["rebro_3d", "ребро 3d", "3d", "qovurga 3d", "3d qovurga"],
        "icon": "🌊",
        "desc_uz": "Zamonaviy 3D relyefli qovurg'a panellar — xonaga hajm va estetika bag'ishlaydi.",
        "desc_ru": "Современные 3D рельефные панели (ребро/qovurga) для акцентных стен.",
    },
    "rebro_4d": {
        "name_uz": "Qovurg'a 4D (Ребро 4D)",
        "name_ru": "Ребро 4D (qovurga)",
        "aliases": ["rebro_4d", "ребро 4d", "4d", "qovurga 4d"],
        "icon": "🌊",
        "desc_uz": "Yuqori sifatli 4D qovurg'ali devor panellari.",
        "desc_ru": "Высококачественные 4D рельефные панели.",
    },
    "rebro_5d": {
        "name_uz": "Qovurg'a 5D (Ребро 5D)",
        "name_ru": "Ребро 5D (qovurga)",
        "aliases": ["rebro_5d", "ребро 5d", "5d", "qovurga 5d"],
        "icon": "🌊",
        "desc_uz": "Eksklyuziv chuqur to'lqinli 5D qovurg'a panellar.",
        "desc_ru": "Эксклюзивные глубокие 5D рельефные панели.",
    },
    "dekor_plastik": {
        "name_uz": "Dekor plastik",
        "name_ru": "Декор пластик",
        "aliases": ["dekor_plastik", "декор пластик"],
        "icon": "✨",
        "desc_uz": "Keng turdagi dekorativ plastik qoplamalar.",
        "desc_ru": "Широкий ассортимент декоративного пластика.",
    },
    "dekor_mdf": {
        "name_uz": "Dekor MDF",
        "name_ru": "Декор МДФ",
        "aliases": ["dekor_mdf", "декор мдф", "мдф", "mdf"],
        "icon": "🪵",
        "desc_uz": "Ichki interyer uchun shinam va sifatli MDF dekor panellar.",
        "desc_ru": "Элегантные интерьерные МДФ панели.",
    },
    "bambuk": {
        "name_uz": "Bambuk panellar (Tez kunda)",
        "name_ru": "Бамбуковые панели (Скоро)",
        "aliases": ["bambuk", "бамбук", "бамбуковые панели"],
        "icon": "🎋",
        "desc_uz": "Tabiiy ekologik bambuk panellar — tez kunda sotuvda!",
        "desc_ru": "Экологичные трендовые бамбуковые панели — скоро в продаже!",
    },
    "potolok_krashenyj": {
        "name_uz": "Shift uchun bo'yalgan plastik",
        "name_ru": "Потолочный крашеный пластик",
        "aliases": ["potolok_krashenyj", "потолочный крашеный пластик", "shift plastik"],
        "icon": "🏠",
        "desc_uz": "Shiftlar uchun yengil, namlikka chidamli bo'yalgan plastik qoplamalar.",
        "desc_ru": "Влагостойкий окрашенный пластик для потолков.",
    },
    "potolok_laminat": {
        "name_uz": "Shift uchun laminat plastik",
        "name_ru": "Потолочный пластик ламинат",
        "aliases": ["potolok_laminat", "потолочный пластик ламинат"],
        "icon": "🏠",
        "desc_uz": "Laminatsiyalangan uzoq xizmat qiluvchi shift materiallari.",
        "desc_ru": "Ламинированные эстетичные потолочные панели.",
    },
    "reyki_plastik": {
        "name_uz": "Plastik reykalar",
        "name_ru": "Рейки пластиковые",
        "aliases": ["reyki_plastik", "рейки пластиковые", "plastik reyka"],
        "icon": "📏",
        "desc_uz": "Interyerni zonalarga ajratish va devor bezash uchun zamonaviy reykalar.",
        "desc_ru": "Пластиковые интерьерные рейки для зонирования и декора.",
    },
    "reyki_alyuminiy": {
        "name_uz": "Alyuminiy reykalar",
        "name_ru": "Рейки алюминиевые",
        "aliases": ["reyki_alyuminiy", "рейки алюминиевые", "alyuminiy reyka"],
        "icon": "📏",
        "desc_uz": "Mustahkam va uzoq yillik premium alyuminiy reykalar.",
        "desc_ru": "Долговечные и премиальные алюминиевые рейки.",
    },
}

# ---------------------------------------------------------------------------
# Rasmlar katalogi va fayl tizimi boshqaruvi
# ---------------------------------------------------------------------------
def get_photo_roots() -> list[Path]:
    """Mavjud foto jildlarini topish (photo va photos)."""
    roots = []
    for name in ("photo", "photos"):
        p = BASE_DIR / name
        if p.is_dir():
            roots.append(p)
    if not roots:
        default_dir = BASE_DIR / "photo"
        default_dir.mkdir(exist_ok=True)
        roots.append(default_dir)
    return roots


def ensure_photo_folders() -> None:
    """Katalog toifalari uchun jildlar mavjudligini ta'minlash."""
    root = get_photo_roots()[0]
    for key in CATEGORIES:
        folder = find_category_folder(key)
        if not folder:
            try:
                (root / key).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass


def find_category_folder(cat_key: str) -> Optional[Path]:
    """Toifa kalitiga yoki nomiga mos keladigan diskdagi jildni topish."""
    needle = cat_key.strip().lower()
    targets = {needle}

    if cat_key in CATEGORIES:
        info = CATEGORIES[cat_key]
        targets.add(info["name_ru"].lower())
        targets.add(info["name_uz"].lower())
        for a in info.get("aliases", []):
            targets.add(a.lower())
    else:
        for k, info in CATEGORIES.items():
            all_names = [k.lower(), info["name_ru"].lower(), info["name_uz"].lower()] + [
                a.lower() for a in info.get("aliases", [])
            ]
            if needle in all_names:
                targets.update(all_names)
                break

    for root in get_photo_roots():
        if not root.is_dir():
            continue
        for sub in root.iterdir():
            if not sub.is_dir():
                continue
            sub_name = sub.name.lower().strip()
            if sub_name in targets:
                return sub
            for t in targets:
                if t in sub_name or sub_name in t:
                    return sub
    return None


def get_category_photos(cat_key: str, query: str = "") -> list[Path]:
    """Toifadagi rasmlarni olish va qidiruv bo'yicha filtrlash."""
    folder = find_category_folder(cat_key)
    if not folder or not folder.is_dir():
        return []

    files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() in IMAGE_EXT]
    if not files:
        return []

    q = (query or "").strip().lower()
    if not q:
        return files

    synonyms = {
        "oq": ["белый", "oq", "white"],
        "qora": ["чёрный", "черный", "qora", "black"],
        "qizil": ["красный", "qizil", "red"],
        "yashil": ["зелёный", "зеленый", "yashil", "green"],
        "oltin": ["золото", "oltin", "tilla", "gold"],
        "kumush": ["серебро", "kumush", "silver"],
        "dub": ["дуб", "dub", "oak"],
        "daraxt": ["дерево", "daraxt", "wood"],
        "marmar": ["мрамор", "marmar", "marble"],
        "oyna": ["зеркало", "зеркальное", "oyna"],
        "salat": ["салатовый", "salat"],
        "krem": ["кремовый", "krem"],
    }
    match_words = {q}
    for k, syn_list in synonyms.items():
        if q == k or q in syn_list:
            match_words.update(syn_list)

    matched = []
    for p in files:
        stem = p.stem.lower()
        if any(w in stem for w in match_words):
            matched.append(p)

    return matched if matched else files


# ---------------------------------------------------------------------------
# Telegram UI: Tugmalar va menyular
# ---------------------------------------------------------------------------
def get_main_reply_keyboard(is_admin_user: bool = False) -> ReplyKeyboardMarkup:
    """Pastki doimiy menyu tugmalari."""
    buttons = [
        [KeyboardButton("📁 Katalog / Каталог"), KeyboardButton("👨‍💼 Menejer / Менеджер")],
        [KeyboardButton("📍 Manzil / Локация"), KeyboardButton("📱 Raqam qoldirish")],
        [KeyboardButton("🔄 Yangilash / Сброс"), KeyboardButton("ℹ️ Ma'lumot / Инфо")],
    ]
    if is_admin_user:
        buttons.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, is_persistent=True)


def get_catalog_inline_keyboard() -> InlineKeyboardMarkup:
    """Katalog toifalari uchun interaktiv inline menyu."""
    keyboard = []
    keys = list(CATEGORIES.keys())
    for i in range(0, len(keys), 2):
        row = []
        k1 = keys[i]
        info1 = CATEGORIES[k1]
        row.append(
            InlineKeyboardButton(
                f"{info1['icon']} {info1['name_ru']}", callback_data=f"cat_{k1}"
            )
        )
        if i + 1 < len(keys):
            k2 = keys[i + 1]
            info2 = CATEGORIES[k2]
            row.append(
                InlineKeyboardButton(
                    f"{info2['icon']} {info2['name_ru']}", callback_data=f"cat_{k2}"
                )
            )
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton("👨‍💼 Menejer bilan bog'lanish", url=f"https://t.me/{MANAGER_USERNAME}"),
            InlineKeyboardButton("📢 Rasmiy Kanal", url=f"https://t.me/{CHANNEL_USERNAME}"),
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def get_category_action_keyboard(cat_key: str) -> InlineKeyboardMarkup:
    """Toifa ko'rsatilgandan keyingi inline amallar."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛍 Buyurtma berish / Заказать", callback_data=f"order_{cat_key}"
                ),
                InlineKeyboardButton(
                    "📸 Yana fotosuratlar", callback_data=f"more_{cat_key}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "👨‍💼 Menejerga yozish", url=f"https://t.me/{MANAGER_USERNAME}"
                ),
                InlineKeyboardButton("📁 Barcha katalog", callback_data="catalog_menu"),
            ],
        ]
    )


def get_manager_direct_keyboard() -> InlineKeyboardMarkup:
    """Menejer bilan to'g'ridan-to'g'ri bog'lanish tugmalari."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💬 Telegramda yozish", url=f"https://t.me/{MANAGER_USERNAME}"
                ),
                InlineKeyboardButton(
                    "🟢 WhatsApp", url=f"https://wa.me/998998560711"
                ),
            ],
            [
                InlineKeyboardButton("📢 Telegram Kanalimiz", url=f"https://t.me/{CHANNEL_USERNAME}"),
                InlineKeyboardButton("📸 Instagram", url=f"https://instagram.com/{INSTAGRAM_PAGE}"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Admin Panel Tugmalari va Yordamchilari
# ---------------------------------------------------------------------------
def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📸 Rasm qo'shish", callback_data="adm_photo_add"),
                InlineKeyboardButton("🗑 Rasm o'chirish", callback_data="adm_photo_del"),
            ],
            [
                InlineKeyboardButton("📍 Lokatsiyani sozlash", callback_data="adm_loc_menu"),
                InlineKeyboardButton("📊 Statistika", callback_data="adm_stats"),
            ],
            [
                InlineKeyboardButton("🔄 Prompt/Jildlarni yangilash", callback_data="adm_reload"),
                InlineKeyboardButton("❌ Menyudan chiqish", callback_data="adm_close"),
            ],
        ]
    )


def get_admin_add_photo_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    keys = list(CATEGORIES.keys())
    for i in range(0, len(keys), 2):
        row = []
        k1 = keys[i]
        info1 = CATEGORIES[k1]
        c1 = len(get_category_photos(k1))
        row.append(
            InlineKeyboardButton(
                f"{info1['icon']} {info1['name_ru']} ({c1})",
                callback_data=f"adm_upcat_{k1}",
            )
        )
        if i + 1 < len(keys):
            k2 = keys[i + 1]
            info2 = CATEGORIES[k2]
            c2 = len(get_category_photos(k2))
            row.append(
                InlineKeyboardButton(
                    f"{info2['icon']} {info2['name_ru']} ({c2})",
                    callback_data=f"adm_upcat_{k2}",
                )
            )
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Admin panel", callback_data="adm_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_del_photo_category_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    keys = list(CATEGORIES.keys())
    for i in range(0, len(keys), 2):
        row = []
        k1 = keys[i]
        info1 = CATEGORIES[k1]
        c1 = len(get_category_photos(k1))
        row.append(
            InlineKeyboardButton(
                f"{info1['icon']} {info1['name_ru']} ({c1})",
                callback_data=f"adm_delcat_{k1}_0",
            )
        )
        if i + 1 < len(keys):
            k2 = keys[i + 1]
            info2 = CATEGORIES[k2]
            c2 = len(get_category_photos(k2))
            row.append(
                InlineKeyboardButton(
                    f"{info2['icon']} {info2['name_ru']} ({c2})",
                    callback_data=f"adm_delcat_{k2}_0",
                )
            )
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Admin panel", callback_data="adm_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_category_photos_del_keyboard(
    cat_key: str, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    photos = get_category_photos(cat_key)
    info = CATEGORIES.get(cat_key, {})
    cat_title = info.get("name_uz", cat_key)

    if not photos:
        text = f"📂 <b>«{cat_title}»</b> toifasida hozircha fotosuratlar mavjud emas."
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Toifalar ro'yxati", callback_data="adm_photo_del")]]
        )
        return text, kb

    per_page = 6
    total_pages = (len(photos) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))

    page_photos = photos[page * per_page : (page + 1) * per_page]
    keyboard = []

    for p in page_photos:
        short_id = hashlib.md5(f"{cat_key}_{p.name}".encode()).hexdigest()[:8]
        DEL_PHOTO_CACHE[short_id] = p
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🗑 {p.stem[:24]}",
                    callback_data=f"adm_askdel_{short_id}_{cat_key}_{page}",
                )
            ]
        )

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                "⬅️ Oldingi", callback_data=f"adm_delcat_{cat_key}_{page-1}"
            )
        )
    nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton(
                "➡️ Keyingi", callback_data=f"adm_delcat_{cat_key}_{page+1}"
            )
        )

    keyboard.append(nav_row)
    keyboard.append(
        [
            InlineKeyboardButton("🔙 Toifalar ro'yxati", callback_data="adm_photo_del"),
            InlineKeyboardButton("⚙️ Admin panel", callback_data="adm_menu"),
        ]
    )

    text = (
        f"🗑 <b>«{cat_title}» toifasidagi fotosuratlar ({len(photos)} ta):</b>\n\n"
        "O'chirmoqchi bo'lgan rasmingiz ustiga bosing:"
    )
    return text, InlineKeyboardMarkup(keyboard)


def get_admin_location_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📌 Geopozitsiya yuborish (Xarita)", callback_data="adm_loc_geo"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏢 Manzil matnini tahrirlash", callback_data="adm_loc_addr"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🚩 Mo'ljalni tahrirlash", callback_data="adm_loc_landmark"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🕒 Ish vaqtini tahrirlash", callback_data="adm_loc_hours"
                ),
            ],
            [
                InlineKeyboardButton("🔙 Admin Panelga qaytish", callback_data="adm_menu"),
            ],
        ]
    )


def render_admin_location_text() -> str:
    cfg = load_config()
    loc = cfg.get("location", DEFAULT_CONFIG["location"])
    lat = loc.get("lat", 41.2289)
    lon = loc.get("lon", 69.3364)
    addr = loc.get("address", "")
    landmark = loc.get("landmark", "")
    hours = loc.get("work_hours", "")

    return (
        "📍 <b>ZAVOD LOKATSIYASI VA MANZIL SOZLAMALARI:</b>\n\n"
        f"🏢 <b>Manzil:</b> {html.escape(str(addr))}\n"
        f"🚩 <b>Mo'ljal:</b> {html.escape(str(landmark))}\n"
        f"🕒 <b>Ish vaqti:</b> {html.escape(str(hours))}\n"
        f"🌐 <b>Koordinatalar:</b> Lat: <code>{lat}</code>, Lon: <code>{lon}</code>\n\n"
        "<i>Quyidagi tugmalar orqali istalgan ma'lumotni o'zgartirishingiz mumkin:</i>"
    )


# ---------------------------------------------------------------------------
# Claude Prompt va Asboblar (Tools)
# ---------------------------------------------------------------------------
EXTRA_RULES = """

## ТЕХНИЧЕСКИЕ ПРАВИЛА (Telegram)
- Ты общаешься с клиентом в личном чате Telegram Dekor Panel.
- Пиши вежливо, уверенно и профессионально на языке клиента (узбекский или русский).
- Инструмент `show_photos`: используй его всегда, когда клиент просит показать товар, дизайн, цвет или ты предлагаешь варианты.
- Инструмент `notify_manager`: отправляет заявку менеджеру. Вызывай его, когда клиент готов заказать, спрашивает цены, оптовые условия или оставляет контакты.
- Цены: НИКОГДА не называй точные цифры сам. Скажи клиенту, что цены уточняются индивидуально от объема менеджером, и передай заявку.
- Если клиент прислал фото своей комнаты/стены или желаемого товара, определи дизайн и предложи подходящий вариант из нашего каталога.
"""

def load_system_prompt() -> str:
    prompt_file = BASE_DIR / "master_prompt.md"
    if prompt_file.exists():
        base = prompt_file.read_text(encoding="utf-8")
    else:
        base = "Ты — консультант завода Dekor Panel в Ташкенте."
    return base + EXTRA_RULES


SYSTEM_PROMPT = load_system_prompt()

TOOLS = [
    {
        "name": "show_photos",
        "description": (
            "Отправить клиенту фото товаров из каталога выбранной категории. "
            "Можно указать часть названия фото (номер дизайна, цвет, код '1014', 'dub', 'oq'), чтобы найти конкретный товар."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Категория: " + ", ".join(f"{k} ({v['name_ru']})" for k, v in CATEGORIES.items())
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "Часть названия, например '1014', 'золото', 'дуб', 'oq', 'qora'. Необязательно.",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Сколько фото отправить (по умолчанию 3).",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "notify_manager",
        "description": (
            "Передать заявку или вопрос клиента менеджеру завода Dekor Panel. "
            "В тексте summary обязательно укажи: товар, цвет, размер, количество, город, опт/розница и контакты."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Подробное описание заявки клиента",
                },
                "product": {"type": "string", "description": "Название товара"},
                "quantity": {"type": "string", "description": "Количество/объём"},
                "client_phone": {"type": "string", "description": "Телефон клиента, если указан"},
            },
            "required": ["summary"],
        },
    },
]

# Xotira va holat
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
HISTORY: dict[int, list] = defaultdict(list)
LOCKS: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
USER_DATA: dict[int, dict[str, Any]] = defaultdict(dict)
SESSION_PHOTO_INDEX: dict[str, int] = defaultdict(int)

GREETING_TEXT = (
    "👋 <b>Assalomu alaykum! Dekor Panel zavodining rasmiy virtual yordamchisiman.</b>\n\n"
    "Biz Toshkentda sifatli panellar, alukabond, profillar va pardozlash materiallarini ishlab chiqaramiz va yetkazib beramiz.\n\n"
    "✨ <i>Sizni qanday mahsulot qiziqtiryapti? Katalogni ko'rish uchun quyidagi tugmalardan foydalanishingiz mumkin:</i>\n\n"
    "➖➖➖➖➖➖➖➖➖➖\n"
    "Здравствуйте! Я виртуальный консультант завода <b>Dekor Panel</b>. "
    "Помогу выбрать панели, алюкобонд, рейки и профили по лучшим ценам завода!"
)

ERROR_TEXT = (
    "⚠️ Texnik xatolik yuz berdi. Iltimos, to'g'ridan-to'g'ri menejerimizga murojaat qiling:\n"
    f"📱 Telefon: {MANAGER_PHONE_PRIMARY}\n"
    f"💬 Telegram: https://t.me/{MANAGER_USERNAME}"
)


# ---------------------------------------------------------------------------
# Typing Action kontekst boshqaruvchisi
# ---------------------------------------------------------------------------
@asynccontextmanager
async def keep_typing(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Claude javob berguncha foydalanuvchiga 'Typing...' holatini uzluksiz ko'rsatish."""
    stop_event = asyncio.Event()

    async def _loop():
        while not stop_event.is_set():
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=3.5)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Asboblar (Tool implementations)
# ---------------------------------------------------------------------------
async def tool_show_photos(
    inp: dict, chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> str:
    category = inp.get("category", "")
    query = inp.get("query", "")
    count = max(1, min(int(inp.get("count") or 3), 5))

    files = get_category_photos(category, query)
    if not files:
        return (
            f"Для категории '{category}' фото пока не загружены или не найдены по запросу '{query}'. "
            "Предложи клиенту связаться с менеджером для получения свежих фото."
        )

    if not query and len(files) > count:
        random.shuffle(files)
    selected = files[:count]

    try:
        if len(selected) == 1:
            p = selected[0]
            with open(p, "rb") as f:
                caption = f"📸 <b>{p.stem}</b>\n\n🏢 <i>Dekor Panel zavodi mahsuloti</i>"
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_category_action_keyboard(category),
                )
        else:
            media_list = []
            opened = []
            try:
                for i, p in enumerate(selected):
                    f = open(p, "rb")
                    opened.append(f)
                    cap = f"📸 <b>{p.stem}</b>" if i == 0 else ""
                    media_list.append(
                        InputMediaPhoto(
                            media=f,
                            caption=cap,
                            parse_mode=ParseMode.HTML if cap else None,
                        )
                    )
                await context.bot.send_media_group(chat_id=chat_id, media=media_list)
            finally:
                for f in opened:
                    f.close()

            await context.bot.send_message(
                chat_id=chat_id,
                text="👆 <i>Yuqoridagi fotosuratlardan birini tanladingizmi yoki boshqa ranglarni ko'rsataylikmi?</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_category_action_keyboard(category),
            )
        return "Фото успешно отправлены клиенту: " + ", ".join(p.stem for p in selected)
    except Exception as e:
        log.exception("Xatolik rasm yuborishda: %s", e)
        return f"Не удалось отправить фото: {e}"


async def tool_notify_manager(
    inp: dict, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> str:
    user = update.effective_user
    chat_id = update.effective_chat.id
    phone = USER_DATA[chat_id].get("phone") or inp.get("client_phone") or "Ko'rsatilmadi"
    product = inp.get("product") or "Ko'rsatilmadi"
    quantity = inp.get("quantity") or "Ko'rsatilmadi"
    summary = inp.get("summary", "")

    who = user.full_name + (f" (@{user.username})" if user.username else "")
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    manager_text = (
        f"🔔 <b>YANGI BUYURTMA / НОВАЯ ЗАЯВКА</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👤 <b>Mijoz:</b> {html.escape(who)}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"📱 <b>Telefon:</b> <code>{html.escape(str(phone))}</code>\n"
        f"📦 <b>Mahsulot:</b> {html.escape(str(product))}\n"
        f"🔢 <b>Hajmi:</b> {html.escape(str(quantity))}\n"
        f"🕒 <b>Vaqt:</b> {now_str}\n\n"
        f"📝 <b>Batafsil / Детали:</b>\n{html.escape(summary)}"
    )

    manager_keyboard = [
        [InlineKeyboardButton("💬 Mijozga yozish", url=f"tg://user?id={user.id}")],
    ]
    if user.username:
        manager_keyboard[0].append(
            InlineKeyboardButton("🌐 Profil", url=f"https://t.me/{user.username}")
        )

    if MANAGER_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=MANAGER_CHAT_ID,
                text=manager_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(manager_keyboard),
            )
        except Exception as e:
            log.error("Menejerga xabar yetib bormadi: %s", e)

    client_notice = (
        "✅ <b>Zayavkangiz qabul qilindi!</b>\n"
        "Menejerimizga barcha tafsilotlar yetkazildi. Tez orada siz bilan bog'lanishadi.\n\n"
        f"📞 <i>Shoshilinch bo'lsa, to'g'ridan-to'g'ri bog'lanishingiz mumkin:</i>\n"
        f"• Tel: {MANAGER_PHONE_PRIMARY}\n"
        f"• Telegram: @{MANAGER_USERNAME}"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=client_notice,
        parse_mode=ParseMode.HTML,
        reply_markup=get_manager_direct_keyboard(),
    )
    return "Заявка успешно передана менеджеру, клиенту отправлены контакты."


async def run_tool(block, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        if block.name == "show_photos":
            return await tool_show_photos(block.input, update.effective_chat.id, context)
        if block.name == "notify_manager":
            return await tool_notify_manager(block.input, update, context)
        return "Неизвестный инструмент."
    except Exception as e:
        log.exception("Asbob bajarilishida xatolik %s: %s", block.name, e)
        return f"Ошибка при выполнении действия: {e}"


# ---------------------------------------------------------------------------
# Claude AI Muloqot yadrosi
# ---------------------------------------------------------------------------
def _is_plain_user(msg: dict) -> bool:
    if msg["role"] != "user":
        return False
    content = msg["content"]
    if isinstance(content, str):
        return True
    return all(
        not (isinstance(b, dict) and b.get("type") == "tool_result") for b in content
    )


def trim_history(history: list) -> None:
    while len(history) > MAX_HISTORY:
        history.pop(0)
    while history and not _is_plain_user(history[0]):
        history.pop(0)


async def ask_claude(
    chat_id: int,
    content: list,
    plain_text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    if not client:
        return (
            "Kechirasiz, sun'iy intellekt xizmati kaliti kiritilmagan. "
            f"Iltimos, menejerimizga murojaat qiling: @{MANAGER_USERNAME}"
        )

    history = HISTORY[chat_id]
    start_idx = len(history)
    history.append({"role": "user", "content": content})
    answer = ""

    for _ in range(6):
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=history,
        )
        history.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            answer = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            break

        results = []
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                out = await run_tool(block, update, context)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": out}
                )
        history.append({"role": "user", "content": results})

    if any(isinstance(b, dict) and b.get("type") == "image" for b in content):
        history[start_idx] = {
            "role": "user",
            "content": [{"type": "text", "text": plain_text + " [клиент прислал фото]"}],
        }

    trim_history(history)
    return answer


async def send_smart_long(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    """Xabarni xavfsiz va chiroyli tarzda bo'lib yuborish."""
    if len(text) <= 4000:
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    paragraphs = text.split("\n\n")
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) + 2 < 4000:
            current_chunk += (p + "\n\n")
        else:
            if current_chunk:
                await context.bot.send_message(chat_id=chat_id, text=current_chunk.strip())
            current_chunk = p + "\n\n"
    if current_chunk:
        await context.bot.send_message(chat_id=chat_id, text=current_chunk.strip())


# ---------------------------------------------------------------------------
# Xabarlarni qabul qilish va boshqarish
# ---------------------------------------------------------------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = (msg.text or msg.caption or "").strip()

    admin_session = ADMIN_SESSIONS.get(user_id, {})

    # 1. ADMIN HOLATI: Rasm yuklash
    if is_admin(user_id) and admin_session.get("state") == "waiting_photo":
        cat_key = admin_session.get("category")
        info = CATEGORIES.get(cat_key, {})
        cat_name = info.get("name_uz", cat_key)

        if msg.photo or (msg.document and msg.document.mime_type and "image" in msg.document.mime_type):
            if msg.photo:
                photo_obj = msg.photo[-1]
                file_obj = await photo_obj.get_file()
            else:
                file_obj = await msg.document.get_file()

            folder = find_category_folder(cat_key)
            if not folder:
                root = get_photo_roots()[0]
                folder = root / cat_key
                folder.mkdir(parents=True, exist_ok=True)

            caption = (msg.caption or "").strip()
            if caption:
                clean_name = re.sub(r'[\\/*?:"<>|]', "", caption).strip()
                target_filename = f"{clean_name}.jpg"
            else:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_filename = f"{cat_key}_{ts}.jpg"

            dest = folder / target_filename
            counter = 1
            while dest.exists():
                stem = dest.stem
                dest = folder / f"{stem}_{counter}.jpg"
                counter += 1

            data = await file_obj.download_as_bytearray()
            dest.write_bytes(bytes(data))

            await update.effective_message.reply_text(
                f"✅ <b>Rasm muvaffaqiyatli saqlandi!</b>\n\n"
                f"📁 Toifa: <b>{cat_name}</b>\n"
                f"📄 Fayl nomi: <code>{dest.name}</code>\n\n"
                f"<i>Yana rasm yuborishingiz mumkin. Yakunlash uchun /cancel yoki /admin buyrug'ini bosing.</i>",
                parse_mode=ParseMode.HTML,
            )
            return
        elif text == "/cancel":
            await cmd_cancel(update, context)
            return
        elif text == "/admin":
            await cmd_admin(update, context)
            return
        else:
            await update.effective_message.reply_text(
                "📸 Iltimos, fotosurat yuboring. Bekor qilish uchun: /cancel"
            )
            return

    # 2. ADMIN HOLATI: Manzil, mo'ljal yoki ish vaqti matnini o'zgartirish
    if is_admin(user_id) and admin_session.get("state") in (
        "waiting_address_text",
        "waiting_landmark",
        "waiting_hours",
    ):
        state = admin_session.get("state")
        cfg = load_config()
        if "location" not in cfg:
            cfg["location"] = DEFAULT_CONFIG["location"].copy()

        if state == "waiting_address_text":
            cfg["location"]["address"] = text
            field_name = "Manzil"
        elif state == "waiting_landmark":
            cfg["location"]["landmark"] = text
            field_name = "Mo'ljal"
        elif state == "waiting_hours":
            cfg["location"]["work_hours"] = text
            field_name = "Ish vaqti"
        else:
            field_name = "Ma'lumot"

        save_config(cfg)
        ADMIN_SESSIONS[user_id] = {}

        await update.effective_message.reply_text(
            f"✅ <b>{field_name} muvaffaqiyatli yangilandi:</b>\n\n"
            f"<i>{html.escape(text)}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_location_keyboard(),
        )
        return

    clean_text = text.lower().replace("\ufe0f", "").strip()

    # Reply menyudagi tugmalar bosilganda tezkor javoblar
    if any(k in clean_text for k in ("katalog", "каталог", "catalog")):
        await cmd_catalog(update, context)
        return
    elif any(k in clean_text for k in ("menejer", "менеджер", "manager")):
        await cmd_manager(update, context)
        return
    elif any(k in clean_text for k in ("manzil", "локация", "адрес", "xarita", "location")):
        await cmd_location(update, context)
        return
    elif any(k in clean_text for k in ("raqam", "telefon", "номер", "kontakt", "contact", "bog'lanish")):
        await prompt_contact_request(update, context)
        return
    elif any(k in clean_text for k in ("yangilash", "сброс", "reset", "qayta boshlash")):
        await cmd_reset(update, context)
        return
    elif any(k in clean_text for k in ("ma'lumot", "malumot", "инфо", "info", "haqida")):
        await cmd_info(update, context)
        return
    elif is_admin(user_id) and any(k in clean_text for k in ("admin", "админ")):
        await cmd_admin(update, context)
        return
    elif any(k in clean_text for k in ("orqaga", "asosiy menyu", "назад", "меню")):
        await update.effective_message.reply_text(
            "🏢 <b>Asosiy menyu:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_reply_keyboard(is_admin_user=is_admin(user_id)),
        )
        return

    # Foydalanuvchi matn ko'rinishida telefon raqamini yozgan bo'lsa (avtomatik saqlash)
    phone_match = re.search(r"(\+?998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}|\b\d{9}\b)", text)
    if phone_match and len(text.strip()) < 30:
        detected_phone = phone_match.group(0).replace(" ", "").replace("-", "")
        if not detected_phone.startswith("+"):
            if detected_phone.startswith("998"):
                detected_phone = "+" + detected_phone
            else:
                detected_phone = "+998" + detected_phone

        USER_DATA[chat_id]["phone"] = detected_phone
        await update.effective_message.reply_text(
            f"✅ <b>Rahmat! Telefon raqamingiz saqlandi:</b> <code>{detected_phone}</code>\n\n"
            "Menejerimiz siz bilan tez orada bog'lanadi. Mahsulot bo'yicha savollaringiz bo'lsa, bemalol yozishingiz mumkin!",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_reply_keyboard(is_admin_user=is_admin(user_id)),
        )
        if MANAGER_CHAT_ID:
            user = update.effective_user
            who = user.full_name + (f" (@{user.username})" if user.username else "")
            notice = (
                f"📱 <b>MIJOZ TELEFON RAQAMINI QOLDIRDI!</b>\n"
                f"👤 Mijoz: {html.escape(who)}\n"
                f"📞 Telefon: <code>{detected_phone}</code>\n"
                f"🆔 ID: <code>{user.id}</code>"
            )
            try:
                await context.bot.send_message(
                    chat_id=MANAGER_CHAT_ID,
                    text=notice,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("💬 Yozish", url=f"tg://user?id={user.id}")]]
                    ),
                )
            except Exception as e:
                log.error("Menejerga kontakt yetkazilmadi: %s", e)
        return

    # Claude uchun kontent tayyorlash
    content: list = []
    if msg.photo:
        photo_obj = msg.photo[-1]
        if photo_obj.file_size and photo_obj.file_size > 3_500_000 and len(msg.photo) > 1:
            photo_obj = msg.photo[-2]

        tg_file = await photo_obj.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(data).decode(),
                },
            }
        )
        text = text or "Mijoz fotosurat yubordi va fikr/maslahat so'ramoqda."

    content.append({"type": "text", "text": text})

    async with LOCKS[chat_id]:
        async with keep_typing(chat_id, context):
            try:
                answer = await ask_claude(chat_id, content, text, update, context)
            except Exception as e:
                log.exception("Klientga javob berishda xatolik: %s", e)
                HISTORY.pop(chat_id, None)
                answer = ERROR_TEXT

        if answer:
            await send_smart_long(context, chat_id, answer)


async def handle_location_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Geolokatsiya xabarlarini qabul qilish."""
    user_id = update.effective_user.id
    loc = update.effective_message.location
    if not loc:
        return

    admin_session = ADMIN_SESSIONS.get(user_id, {})
    if is_admin(user_id) and admin_session.get("state") == "waiting_location":
        lat = loc.latitude
        lon = loc.longitude

        cfg = load_config()
        if "location" not in cfg:
            cfg["location"] = DEFAULT_CONFIG["location"].copy()
        cfg["location"]["lat"] = lat
        cfg["location"]["lon"] = lon
        save_config(cfg)

        ADMIN_SESSIONS[user_id] = {}

        await update.effective_message.reply_text(
            "✅ <b>Yangi geolokatsiya muvaffaqiyatli saqlandi!</b>\n\n"
            f"🌐 Kenglik (Lat): <code>{lat}</code>\n"
            f"🌐 Uzunlik (Lon): <code>{lon}</code>\n\n"
            "<i>Endi mijozlar «📍 Manzil / Локация» tugmasini bosganda xaritada aynan shu nuqta ko'rsatiladi.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_location_keyboard(),
        )
        return

    await update.effective_message.reply_text(
        "📍 Geolokatsiyangiz qabul qilindi. Tez orada siz bilan bog'lanamiz!",
        reply_markup=get_main_reply_keyboard(is_admin_user=is_admin(user_id)),
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_text = (
        "🎙 <b>Ovozli xabaringiz qabul qilindi!</b>\n\n"
        "Hozirda ovozni avtomatik matnga aylantirish xizmati ulanmoqda. "
        "Sizga tezkor va aniq ma'lumot berishimiz uchun, iltimos:\n\n"
        "✍️ Savolingizni <b>matn shaklida</b> yozib yuboring yoki quyidagi tugma orqali to'g'ridan-to'g'ri <b>menejerimiz</b> bilan bog'laning:"
    )
    await update.effective_message.reply_text(
        reply_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_manager_direct_keyboard(),
    )


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contact = update.effective_message.contact
    chat_id = update.effective_chat.id
    user = update.effective_user

    phone = contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    USER_DATA[chat_id]["phone"] = phone

    await update.effective_message.reply_text(
        f"✅ <b>Rahmat, telefon raqamingiz qabul qilindi:</b> <code>{phone}</code>\n\n"
        "Mutaxassisimiz siz bilan tez orada bog'lanadi. Agar mahsulot bo'yicha savollaringiz bo'lsa, bemalol yozishingiz mumkin!",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_reply_keyboard(is_admin_user=is_admin(user.id)),
    )

    if MANAGER_CHAT_ID:
        who = user.full_name + (f" (@{user.username})" if user.username else "")
        notice = (
            f"📱 <b>YANGI TELEFON RAQAM QABUL QILINDI!</b>\n"
            f"👤 Mijoz: {html.escape(who)}\n"
            f"📞 Telefon: <code>{phone}</code>\n"
            f"🆔 ID: <code>{user.id}</code>"
        )
        try:
            await context.bot.send_message(
                chat_id=MANAGER_CHAT_ID,
                text=notice,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("💬 Yozish", url=f"tg://user?id={user.id}"),
                        ]
                    ]
                ),
            )
        except Exception as e:
            log.error("Menejerga kontakt yetkazilmadi: %s", e)


async def prompt_contact_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contact_keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📲 Telefon raqamimni ulashish", request_contact=True)],
            [KeyboardButton("🔙 Asosiy menyu")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    text = (
        "📱 <b>Menejerimiz siz bilan bog'lanishi uchun telefon raqamingizni qoldiring:</b>\n\n"
        "1️⃣ Pastdagi <b>«📲 Telefon raqamimni ulashish»</b> tugmasini bosing\n"
        "2️⃣ Yoki raqamingizni shu yerga yozib yuboring (masalan: <code>+998901234567</code>)"
    )
    try:
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=contact_keyboard,
        )
    except Exception as e:
        log.exception("prompt_contact_request xatolik: %s", e)


# ---------------------------------------------------------------------------
# Buyruqlar (Commands)
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    HISTORY.pop(chat_id, None)
    admin_mode = is_admin(user_id)

    await update.effective_message.reply_text(
        GREETING_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_reply_keyboard(is_admin_user=admin_mode),
    )
    await update.effective_message.reply_text(
        "📋 <b>Asosiy mahsulotlar toifalari:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_catalog_inline_keyboard(),
    )


async def cmd_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🏢 <b>Dekor Panel Mahsulotlar Katalogi:</b>\n\n"
        "Kerakli bo'limni tanlang va fotosuratlar hamda ma'lumotlar bilan tanishing:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_catalog_inline_keyboard(),
    )


async def cmd_manager(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👨‍💼 <b>Dekor Panel sotuv bo'limi menejeri:</b>\n\n"
        f"• 📞 <b>Telefon:</b> {MANAGER_PHONE_PRIMARY}\n"
        f"• 🟢 <b>WhatsApp:</b> {MANAGER_PHONE_WHATSAPP}\n"
        f"• 💬 <b>Telegram:</b> @{MANAGER_USERNAME}\n"
        f"• 📢 <b>Telegram Kanal:</b> @{CHANNEL_USERNAME}\n\n"
        "Optom va chakana savdo bo'yicha barcha savollaringizga javob beramiz!"
    )
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_manager_direct_keyboard(),
    )


async def cmd_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    cfg = load_config()
    loc = cfg.get("location", DEFAULT_CONFIG["location"])
    lat = float(loc.get("lat", 41.2289))
    lon = float(loc.get("lon", 69.3364))
    addr = loc.get("address", "Toshkent shahar, Bektemir tumani.")
    landmark = loc.get("landmark", "Toshkent Coca-Cola zavodi yonida.")
    hours = loc.get("work_hours", "Dushanba - Shanba, 09:00 dan 18:00 gacha.")

    try:
        await context.bot.send_location(
            chat_id=chat_id,
            latitude=lat,
            longitude=lon,
        )
    except Exception as e:
        log.warning("send_location xatolik: %s", e)

    text = (
        "📍 <b>Dekor Panel Ishlab Chiqarish Zavodi Manzili:</b>\n\n"
        f"🏢 <b>Manzil:</b> {html.escape(str(addr))}\n"
        f"🚩 <b>Mo'ljal:</b> {html.escape(str(landmark))}\n"
        f"🕒 <b>Ish vaqti:</b> {html.escape(str(hours))}\n\n"
        f"📞 <b>Aloqa telefoni:</b> {MANAGER_PHONE_PRIMARY}\n\n"
        f"🚗 <i>Zavodimizga tashrif buyurib, barcha mahsulotlarni jonli ko'rishingiz mumkin!</i>"
    )
    maps_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗺 Google Maps",
                    url=f"https://maps.google.com/?q={lat},{lon}",
                ),
                InlineKeyboardButton(
                    "🚕 Yandex Navigator",
                    url=f"https://yandex.com/maps/?pt={lon},{lat}&z=16&l=map",
                ),
            ],
            [
                InlineKeyboardButton("💬 Menejerga yozish", url=f"https://t.me/{MANAGER_USERNAME}"),
                InlineKeyboardButton("🟢 WhatsApp", url="https://wa.me/998998560711"),
            ],
        ]
    )
    try:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=maps_keyboard
        )
    except Exception as e:
        log.exception("cmd_location reply_text xatolik: %s", e)
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🏢 <b>Dekor Panel Haqida:</b>\n\n"
        "• Toshkentdagi zamonaviy dekoratsiya va devor panellari ishlab chiqaruvchi zavod.\n"
        "• Asosiy mijozlarimiz: do'kon egalari, ulgurji xaridorlar, ustalar va qurilish tashkilotlari.\n"
        "• Mahsulotlar: Alukabond, PVX marmar panellar, 3D/4D/5D qovurg'a panellar, bagetlar, montaj profillari va boshqalar.\n"
        "• Sifat kafolati va qulay to'lov shartlari mavjud.\n\n"
        f"📱 Batafsil ma'lumot: {MANAGER_PHONE_PRIMARY}"
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=get_manager_direct_keyboard()
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    HISTORY.pop(chat_id, None)
    await update.effective_message.reply_text(
        "🔄 <b>Muloqot yangilandi!</b>\nSizga qanday yordam bera olaman?",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_reply_keyboard(is_admin_user=is_admin(user_id)),
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.effective_message.reply_text(
        f"🆔 <b>Sizning Telegram ID:</b> <code>{chat_id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Administrator boshqaruv paneli."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.effective_message.reply_text(
            "⛔️ <b>Kechirasiz, ushbu bo'lim faqat bot ma'murlari (adminlar) uchun!</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    ADMIN_SESSIONS[user.id] = {}
    await update.effective_message.reply_text(
        "⚙️ <b>DEKOR PANEL — BOSHQUVR PANELI (ADMIN)</b>\n\n"
        "Xush kelibsiz! Quyidagi boshqaruv amallaridan birini tanlang:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_dashboard_keyboard(),
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Faol admin amalini bekor qilish."""
    user_id = update.effective_user.id
    if user_id in ADMIN_SESSIONS and ADMIN_SESSIONS[user_id]:
        ADMIN_SESSIONS[user_id] = {}
        await update.effective_message.reply_text(
            "❌ <b>Amal bekor qilindi.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_dashboard_keyboard(),
        )
    else:
        await update.effective_message.reply_text("Bekor qilinadigan faol amal yo'q.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menejer uchun statistika."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    photo_counts = []
    total_photos = 0
    for key, info in CATEGORIES.items():
        photos = get_category_photos(key)
        count = len(photos)
        total_photos += count
        if count > 0:
            photo_counts.append(f"• {info['name_ru']}: <b>{count} ta</b> rasm")

    report = (
        "📊 <b>Bot Statistikasi va Holati:</b>\n\n"
        f"🤖 <b>AI Model:</b> <code>{MODEL}</code>\n"
        f"💬 <b>Faol chatlar soni:</b> {len(HISTORY)}\n"
        f"📸 <b>Jami yuklangan rasmlar:</b> {total_photos} ta\n\n"
        f"<b>Mavjud rasmlar toifasi:</b>\n"
        + ("\n".join(photo_counts) if photo_counts else "<i>Rasmlar hali yuklanmagan</i>")
    )
    await update.effective_message.reply_text(report, parse_mode=ParseMode.HTML)


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt va jildlarni qayta yuklash."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    global SYSTEM_PROMPT
    SYSTEM_PROMPT = load_system_prompt()
    ensure_photo_folders()
    await update.effective_message.reply_text(
        "✅ <b>Master-prompt va foto jildlar qayta yuklandi!</b>",
        parse_mode=ParseMode.HTML,
    )


# ---------------------------------------------------------------------------
# Callback Query Handlers (Tugmalar bosilganda)
# ---------------------------------------------------------------------------
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if data == "noop":
        return

    # ------------------ ADMIN AMALLARI ------------------
    if data.startswith("adm_"):
        if not is_admin(user_id):
            await query.answer("⛔️ Faqat adminlar uchun!", show_alert=True)
            return

        if data == "adm_menu":
            ADMIN_SESSIONS[user_id] = {}
            await query.edit_message_text(
                "⚙️ <b>DEKOR PANEL — BOSHQUVR PANELI (ADMIN)</b>\n\n"
                "Quyidagi boshqaruv amallaridan birini tanlang:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_dashboard_keyboard(),
            )
            return

        elif data == "adm_close":
            ADMIN_SESSIONS[user_id] = {}
            await query.edit_message_text("🚪 Admin paneldan chiqildi.")
            return

        elif data == "adm_stats":
            await cmd_stats(update, context)
            return

        elif data == "adm_reload":
            await cmd_reload(update, context)
            return

        elif data == "adm_photo_add":
            ADMIN_SESSIONS[user_id] = {}
            await query.edit_message_text(
                "📸 <b>Qaysi toifaga rasm yuklamoqchisiz?</b>\n\n"
                "Kerakli toifani tanlang:",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_add_photo_keyboard(),
            )
            return

        elif data.startswith("adm_upcat_"):
            cat_key = data.replace("adm_upcat_", "")
            info = CATEGORIES.get(cat_key, {})
            cat_title = info.get("name_uz", cat_key)
            ADMIN_SESSIONS[user_id] = {"state": "waiting_photo", "category": cat_key}
            await query.edit_message_text(
                f"📸 <b>«{cat_title}» toifasiga rasm yuklash holati:</b>\n\n"
                "Iltimos, rasm(lar)ni shu yerga yuboring.\n\n"
                "💡 <i>Maslahat: Rasm tagiga (caption) nom yoki rangini yozib yuborsangiz (masalan: «Oltin 1014»), fayl shu nom bilan saqlanadi.</i>\n\n"
                "Bekor qilish uchun: /cancel",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_photo_add")]]
                ),
            )
            return

        elif data == "adm_photo_del":
            ADMIN_SESSIONS[user_id] = {}
            await query.edit_message_text(
                "🗑 <b>Qaysi toifadan rasm o'chirmoqchisiz?</b>\n\n"
                "Toifani tanlang (qavs ichida mavjud rasmlar soni):",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_del_photo_category_keyboard(),
            )
            return

        elif data.startswith("adm_delcat_"):
            parts = data.split("_")
            cat_key = parts[2]
            page = int(parts[3]) if len(parts) > 3 else 0
            text, kb = get_admin_category_photos_del_keyboard(cat_key, page)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return

        elif data.startswith("adm_askdel_"):
            parts = data.split("_")
            short_id = parts[2]
            cat_key = parts[3]
            page = int(parts[4]) if len(parts) > 4 else 0
            p = DEL_PHOTO_CACHE.get(short_id)
            if not p or not p.is_file():
                await query.answer("Fayl topilmadi yoki allaqachon o'chirilgan!", show_alert=True)
                return

            confirm_kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🗑 Ha, o'chirilsin",
                            callback_data=f"adm_dodel_{short_id}_{cat_key}_{page}",
                        ),
                        InlineKeyboardButton(
                            "❌ Bekor qilish",
                            callback_data=f"adm_delcat_{cat_key}_{page}",
                        ),
                    ]
                ]
            )
            try:
                with open(p, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=(
                            f"⚠️ <b>Rostdan ham ushbu rasmni o'chirmoqchimisiz?</b>\n\n"
                            f"📁 Toifa: <b>{CATEGORIES.get(cat_key, {}).get('name_uz', cat_key)}</b>\n"
                            f"📄 Fayl nomi: <code>{p.name}</code>"
                        ),
                        parse_mode=ParseMode.HTML,
                        reply_markup=confirm_kb,
                    )
            except Exception as e:
                log.exception("send_photo askdel xatolik: %s", e)
                await query.message.reply_text(
                    f"⚠️ <b>Rostdan ham «{p.name}» faylini o'chirmoqchimisiz?</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=confirm_kb,
                )
            return

        elif data.startswith("adm_dodel_"):
            parts = data.split("_")
            short_id = parts[2]
            cat_key = parts[3]
            page = int(parts[4]) if len(parts) > 4 else 0
            p = DEL_PHOTO_CACHE.get(short_id)
            if p and p.is_file():
                fname = p.name
                p.unlink(missing_ok=True)
                DEL_PHOTO_CACHE.pop(short_id, None)
                await query.answer(f"✅ {fname} o'chirildi!", show_alert=True)
                await query.message.reply_text(
                    f"🗑 <b>{fname}</b> muvaffaqiyatli o'chirildi!", parse_mode=ParseMode.HTML
                )
            else:
                await query.answer("Fayl allaqachon o'chirilgan.", show_alert=True)

            text, kb = get_admin_category_photos_del_keyboard(cat_key, page)
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return

        elif data == "adm_loc_menu":
            ADMIN_SESSIONS[user_id] = {}
            await query.edit_message_text(
                render_admin_location_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_location_keyboard(),
            )
            return

        elif data == "adm_loc_geo":
            ADMIN_SESSIONS[user_id] = {"state": "waiting_location"}
            await query.edit_message_text(
                "📌 <b>Zavodning yangi geolokatsiyasini yuborish:</b>\n\n"
                "Pastdagi «Qisqich» (📎) tugmasini bosib, «Geopozitsiya» bo'limidan zavod joylashgan nuqtani yuboring.\n\n"
                "Bekor qilish uchun: /cancel",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_loc_menu")]]
                ),
            )
            return

        elif data == "adm_loc_addr":
            ADMIN_SESSIONS[user_id] = {"state": "waiting_address_text"}
            await query.edit_message_text(
                "🏢 <b>Yangi manzil matnini yozib yuboring:</b>\n\n"
                "(Masalan: <i>Toshkent shahar, Bektemir tumani</i>)\n\n"
                "Bekor qilish uchun: /cancel",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_loc_menu")]]
                ),
            )
            return

        elif data == "adm_loc_landmark":
            ADMIN_SESSIONS[user_id] = {"state": "waiting_landmark"}
            await query.edit_message_text(
                "🚩 <b>Yangi mo'ljal matnini yozib yuboring:</b>\n\n"
                "(Masalan: <i>Toshkent Coca-Cola zavodi yonida</i>)\n\n"
                "Bekor qilish uchun: /cancel",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_loc_menu")]]
                ),
            )
            return

        elif data == "adm_loc_hours":
            ADMIN_SESSIONS[user_id] = {"state": "waiting_hours"}
            await query.edit_message_text(
                "🕒 <b>Yangi ish vaqti matnini yozib yuboring:</b>\n\n"
                "(Masalan: <i>Dushanba - Shanba, 09:00 dan 18:00 gacha</i>)\n\n"
                "Bekor qilish uchun: /cancel",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Orqaga", callback_data="adm_loc_menu")]]
                ),
            )
            return

    # ------------------ FOYDALANUVCHI AMALLARI ------------------
    if data == "catalog_menu":
        await query.edit_message_text(
            "🏢 <b>Dekor Panel Mahsulotlar Katalogi:</b>\n\n"
            "Kerakli toifani tanlang:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_catalog_inline_keyboard(),
        )
        return

    if data.startswith("cat_"):
        cat_key = data.replace("cat_", "")
        info = CATEGORIES.get(cat_key)
        if not info:
            await query.message.reply_text("Kategoriya topilmadi.")
            return

        photos = get_category_photos(cat_key)
        SESSION_PHOTO_INDEX[f"{chat_id}_{cat_key}"] = 0

        text = (
            f"{info['icon']} <b>{info['name_uz']} / {info['name_ru']}</b>\n\n"
            f"📝 <b>Tavsif:</b> {info['desc_uz']}\n\n"
            f"📸 <i>Mavjud fotosuratlar soni: {len(photos)} ta</i>"
        )
        await query.message.reply_text(text, parse_mode=ParseMode.HTML)

        if photos:
            selected = photos[:3]
            try:
                if len(selected) == 1:
                    with open(selected[0], "rb") as f:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=f,
                            caption=f"📸 <b>{selected[0].stem}</b>",
                            parse_mode=ParseMode.HTML,
                            reply_markup=get_category_action_keyboard(cat_key),
                        )
                else:
                    media_list = []
                    opened = []
                    try:
                        for i, p in enumerate(selected):
                            f = open(p, "rb")
                            opened.append(f)
                            cap = f"📸 <b>{p.stem}</b>" if i == 0 else ""
                            media_list.append(
                                InputMediaPhoto(
                                    media=f,
                                    caption=cap,
                                    parse_mode=ParseMode.HTML if cap else None,
                                )
                            )
                        await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                    finally:
                        for f in opened:
                            f.close()

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Tanlangan toifa namunalari 👆",
                        reply_markup=get_category_action_keyboard(cat_key),
                    )
            except Exception as e:
                log.exception("Kategoriya rasmlarini yuborishda xatolik: %s", e)
        else:
            await query.message.reply_text(
                "📸 <i>Ushbu toifa uchun rasmlar tez orada yuklanadi. "
                "Menejerdan so'nggi fotosuratlar va narxlarni olishingiz mumkin:</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_category_action_keyboard(cat_key),
            )
        return

    if data.startswith("more_"):
        cat_key = data.replace("more_", "")
        photos = get_category_photos(cat_key)
        if not photos:
            await query.message.reply_text(
                "📸 <i>Ushbu toifa rasmlari tez kunda yuklanadi. Hozirda namunalar uchun menejerimizga yozishingiz mumkin:</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_manager_direct_keyboard(),
            )
            return

        session_key = f"{chat_id}_{cat_key}"
        curr_idx = SESSION_PHOTO_INDEX[session_key] + 3
        if curr_idx >= len(photos):
            curr_idx = 0
        SESSION_PHOTO_INDEX[session_key] = curr_idx

        selected = photos[curr_idx : curr_idx + 3]
        if not selected:
            selected = photos[:3]

        try:
            if len(selected) == 1:
                with open(selected[0], "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=f"📸 <b>{selected[0].stem}</b>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_category_action_keyboard(cat_key),
                    )
            else:
                media_list = []
                opened = []
                try:
                    for i, p in enumerate(selected):
                        f = open(p, "rb")
                        opened.append(f)
                        cap = f"📸 <b>{p.stem}</b>" if i == 0 else ""
                        media_list.append(
                            InputMediaPhoto(
                                media=f,
                                caption=cap,
                                parse_mode=ParseMode.HTML if cap else None,
                            )
                        )
                    await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                finally:
                    for f in opened:
                        f.close()

                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Qo'shimcha namunalar 👆",
                    reply_markup=get_category_action_keyboard(cat_key),
                )
        except Exception as e:
            log.exception("Yana rasmlar yuborishda xatolik: %s", e)
        return

    if data.startswith("order_"):
        cat_key = data.replace("order_", "")
        info = CATEGORIES.get(cat_key, {})
        cat_name = info.get("name_uz", cat_key)

        prompt_msg = (
            f"🛍 <b>{cat_name} bo'yicha buyurtma:</b>\n\n"
            "Iltimos, sizga kerakli rang, dizayn kodi, o'lcham va taxminiy miqdorni (list yoki dona) yozib yuboring. "
            "Biz darhol buyurtmani menejerimizga yetkazamiz!"
        )
        await query.message.reply_text(
            prompt_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👨‍💼 Menejerga to'g'ridan-to'g'ri yozish",
                            url=f"https://t.me/{MANAGER_USERNAME}",
                        )
                    ]
                ]
            ),
        )
        return


# ---------------------------------------------------------------------------
# Botni ishga tushirish va buyruqlar menyusi
# ---------------------------------------------------------------------------
async def post_init(application: Application) -> None:
    """Telegram menyusida buyruqlarni ro'yxatdan o'tkazish."""
    ensure_photo_folders()
    commands = [
        BotCommand("start", "Botni ishga tushirish / Запустить бота"),
        BotCommand("katalog", "Mahsulotlar katalogi / Каталог товаров"),
        BotCommand("menejer", "Menejer bilan bog'lanish / Связаться с менеджером"),
        BotCommand("manzil", "Zavod manzili va xarita / Адрес и локация"),
        BotCommand("telefon", "Telefon raqam qoldirish / Оставить номер"),
        BotCommand("admin", "Admin boshqaruv paneli / Панель управления"),
        BotCommand("reset", "Muloqotni qayta boshlash / Начать заново"),
        BotCommand("myid", "Telegram ID ni bilish / Узнать свой ID"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        log.info("Telegram buyruqlari muvaffaqiyatli o'rnatildi")
    except Exception as e:
        log.warning("Buyruqlarni o'rnatishda xatolik: %s", e)



# ---------------------------------------------------------------------------
# Instagram'ga post / reels / karusel chiqarish (faqat admin / menejer uchun)
# ---------------------------------------------------------------------------
IG_TOKEN = os.getenv("INSTAGRAM_TOKEN", "").strip()
IG_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
IG_API_VERSION = os.getenv("IG_API_VERSION", "v23.0").strip()
IG_GRAPH = f"https://graph.instagram.com/{IG_API_VERSION}"
IG_MEDIA_DIR = Path(os.getenv("IG_MEDIA_DIR", "/tmp/ig_media"))
IG_MAX_ITEMS = 10


def ig_public_base() -> str:
    base = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
    return base.strip().rstrip("/")


def ig_cleanup_old_files(max_age_sec: int = 3600) -> None:
    try:
        IG_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for f in IG_MEDIA_DIR.iterdir():
            if f.is_file() and now - f.stat().st_mtime > max_age_sec:
                f.unlink(missing_ok=True)
    except Exception as e:
        log.warning("IG fayllarni tozalashda xatolik: %s", e)


def ig_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("ig", {"active": False, "items": [], "caption": ""})


def ig_reset(context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.user_data.get("ig")
    if st:
        for it in st.get("items", []):
            (IG_MEDIA_DIR / it["name"]).unlink(missing_ok=True)
    context.user_data["ig"] = {"active": False, "items": [], "caption": ""}


IG_KEYBOARD = InlineKeyboardMarkup(
    [[
        InlineKeyboardButton("📤 Опубликовать", callback_data="ig_publish"),
        InlineKeyboardButton("❌ Отмена", callback_data="ig_cancel"),
    ]]
)


async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not is_admin(user.id if user else None):
        return
    if not (IG_TOKEN and IG_ACCOUNT_ID):
        await update.message.reply_text(
            "Instagram не подключён: в Render (Environment) нет INSTAGRAM_TOKEN или INSTAGRAM_ACCOUNT_ID."
        )
        return
    if not ig_public_base():
        await update.message.reply_text(
            "Не задан публичный адрес сервиса. Добавьте в Render (Environment) переменную PUBLIC_URL, "
            "например https://telegrambot-1oo0.onrender.com"
        )
        return
    ig_reset(context)
    st = ig_state(context)
    st["active"] = True
    await update.message.reply_text(
        "Режим публикации в Instagram включён.\n\n"
        "1) Пришлите фото (до 10 штук = карусель) или одно видео (будет Reels).\n"
        "2) Подпись можно написать в подписи к фото или отдельным сообщением.\n"
        "3) Нажмите «Опубликовать».\n\n"
        "Отмена: /cancel_post"
    )


async def cmd_cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not is_admin(user.id if user else None):
        return
    ig_reset(context)
    await update.message.reply_text("Публикация отменена.")


async def cmd_ig_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not is_admin(user.id if user else None):
        return
    if not (IG_TOKEN and IG_ACCOUNT_ID):
        await update.message.reply_text("INSTAGRAM_TOKEN или INSTAGRAM_ACCOUNT_ID не заданы в Render.")
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{IG_GRAPH}/{IG_ACCOUNT_ID}",
                params={"fields": "username", "access_token": IG_TOKEN},
            )
        data = r.json()
        if r.status_code == 200 and data.get("username"):
            await update.message.reply_text(f"✅ Instagram подключён: @{data['username']}")
        else:
            msg = (data.get("error") or {}).get("message", str(data))[:300]
            await update.message.reply_text(f"❌ Instagram ответил ошибкой: {msg}")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось связаться с Instagram: {e}")


async def ig_handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin 'post' rejimida yuborilgan foto/videoni yig'ish."""
    user = update.effective_user
    msg = update.message
    if not msg or not is_admin(user.id if user else None):
        return
    st = ig_state(context)
    if not st["active"]:
        return  # oddiy handle_message ishlaydi

    kind = "video" if msg.video else "photo"
    if kind == "video" and st["items"]:
        await msg.reply_text("Видео (Reels) публикуется отдельно. Отмените /cancel_post и начните заново.")
        raise ApplicationHandlerStop
    if st["items"] and st["items"][0]["kind"] == "video":
        await msg.reply_text("Уже добавлено видео. Для фото начните заново: /cancel_post, затем /post.")
        raise ApplicationHandlerStop
    if len(st["items"]) >= IG_MAX_ITEMS:
        await msg.reply_text("Максимум 10 фото в одном посте.")
        raise ApplicationHandlerStop

    try:
        IG_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        ig_cleanup_old_files()
        tg_file = await (msg.video.get_file() if kind == "video" else msg.photo[-1].get_file())
        name = f"{uuid.uuid4().hex}.{'mp4' if kind == 'video' else 'jpg'}"
        await tg_file.download_to_drive(custom_path=IG_MEDIA_DIR / name)
    except Exception as e:
        log.warning("IG media yuklab olishda xatolik: %s", e)
        await msg.reply_text(
            "Не удалось получить файл от Telegram (видео больше 20 МБ бот скачать не может). Попробуйте файл меньше."
        )
        raise ApplicationHandlerStop

    first = not st["items"]
    st["items"].append({"kind": kind, "name": name})
    if msg.caption and not st["caption"]:
        st["caption"] = msg.caption.strip()

    group_id = msg.media_group_id
    already = st.get("last_group") == group_id and group_id is not None
    st["last_group"] = group_id
    if first or not already:
        await msg.reply_text(
            "Файл добавлен. Можно прислать ещё фото или написать подпись.\nКогда всё готово — нажмите «Опубликовать».",
            reply_markup=IG_KEYBOARD,
        )
    raise ApplicationHandlerStop


async def ig_handle_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.message
    if not msg or not is_admin(user.id if user else None):
        return
    st = ig_state(context)
    if not st["active"]:
        return
    st["caption"] = (msg.text or "").strip()[:2200]
    await msg.reply_text("Подпись сохранена ✅", reply_markup=IG_KEYBOARD)
    raise ApplicationHandlerStop


async def ig_graph_post(client: httpx.AsyncClient, path: str, data: dict) -> dict:
    payload = dict(data)
    payload["access_token"] = IG_TOKEN
    r = await client.post(f"{IG_GRAPH}/{path}", data=payload)
    js = r.json()
    if r.status_code >= 400 or "error" in js:
        err = (js.get("error") or {})
        raise RuntimeError(err.get("error_user_msg") or err.get("message") or str(js))
    return js


async def ig_wait_ready(client: httpx.AsyncClient, container_id: str, max_wait: int) -> None:
    waited = 0
    while waited <= max_wait:
        r = await client.get(
            f"{IG_GRAPH}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN},
        )
        js = r.json()
        status = js.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram не принял файл: {js.get('status') or status}")
        await asyncio.sleep(5)
        waited += 5
    raise RuntimeError("Instagram слишком долго обрабатывает файл. Попробуйте ещё раз позже.")


async def ig_publish_items(items: list, caption: str) -> str:
    base = ig_public_base()
    urls = [f"{base}/media/{it['name']}" for it in items]
    async with httpx.AsyncClient(timeout=90) as client:
        if len(items) == 1 and items[0]["kind"] == "video":
            c = await ig_graph_post(client, f"{IG_ACCOUNT_ID}/media", {
                "media_type": "REELS", "video_url": urls[0], "caption": caption,
            })
            await ig_wait_ready(client, c["id"], 300)
        elif len(items) == 1:
            c = await ig_graph_post(client, f"{IG_ACCOUNT_ID}/media", {
                "image_url": urls[0], "caption": caption,
            })
            await ig_wait_ready(client, c["id"], 60)
        else:
            child_ids = []
            for u in urls:
                ch = await ig_graph_post(client, f"{IG_ACCOUNT_ID}/media", {
                    "image_url": u, "is_carousel_item": "true",
                })
                await ig_wait_ready(client, ch["id"], 60)
                child_ids.append(ch["id"])
            c = await ig_graph_post(client, f"{IG_ACCOUNT_ID}/media", {
                "media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption,
            })
            await ig_wait_ready(client, c["id"], 60)
        pub = await ig_graph_post(client, f"{IG_ACCOUNT_ID}/media_publish", {"creation_id": c["id"]})
        media_id = pub["id"]
        link = ""
        try:
            r = await client.get(
                f"{IG_GRAPH}/{media_id}",
                params={"fields": "permalink", "access_token": IG_TOKEN},
            )
            link = r.json().get("permalink", "")
        except Exception:
            pass
        return link or "(ссылка недоступна, пост опубликован)"


async def ig_handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user = update.effective_user
    if not q or not is_admin(user.id if user else None):
        return
    await q.answer()
    st = ig_state(context)
    if q.data == "ig_cancel":
        ig_reset(context)
        await q.message.reply_text("Публикация отменена.")
        raise ApplicationHandlerStop
    if q.data == "ig_publish":
        if not st["items"]:
            await q.message.reply_text("Сначала пришлите фото или видео.")
            raise ApplicationHandlerStop
        if st.get("busy"):
            raise ApplicationHandlerStop
        st["busy"] = True
        await q.message.reply_text("Публикую в Instagram, подождите (видео может занять до нескольких минут)...")
        try:
            link = await ig_publish_items(st["items"], st["caption"])
            await q.message.reply_text(f"✅ Опубликовано: {link}")
            ig_reset(context)
        except Exception as e:
            log.warning("Instagram publish xatolik: %s", e)
            st["busy"] = False
            await q.message.reply_text(f"❌ Не получилось опубликовать: {str(e)[:500]}\nМожно нажать «Опубликовать» ещё раз.", reply_markup=IG_KEYBOARD)
        raise ApplicationHandlerStop


# ---------------------------------------------------------------------------
# 24/7 Bulutli Serverlar uchun Yengil Health-check Web Serveri
# ---------------------------------------------------------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/media/"):
            name = os.path.basename(self.path.split("?", 1)[0])
            fpath = IG_MEDIA_DIR / name
            if re.fullmatch(r"[0-9a-f]{32}\.(jpg|mp4)", name) and fpath.is_file():
                data = fpath.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4" if name.endswith(".mp4") else "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Dekor Panel Telegram Bot 24/7 ishlamoqda! Status: OK")

    def log_message(self, format, *args):
        pass  # Terminal loglarini ortiqcha to'ldirmaslik


def start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))

    def _run():
        try:
            server = HTTPServer(("0.0.0.0", port), HealthHandler)
            log.info("Foniy 24/7 Web server %s-portda ishga tushdi", port)
            server.serve_forever()
        except Exception as e:
            log.warning("Health server ishga tushmadi (lokal rejimda normal): %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN muhit o'zgaruvchisi topilmadi (.env faylini tekshiring)!")

    # 24/7 bepul serverlar uchun foniy serverni yurgizish
    start_health_server()

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(30)
        .build()
    )

    # Buyruqlar
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("katalog", cmd_catalog))
    app.add_handler(CommandHandler("catalog", cmd_catalog))
    app.add_handler(CommandHandler("menejer", cmd_manager))
    app.add_handler(CommandHandler("manager", cmd_manager))
    app.add_handler(CommandHandler("manzil", cmd_location))
    app.add_handler(CommandHandler("location", cmd_location))
    app.add_handler(CommandHandler("telefon", prompt_contact_request))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reload", cmd_reload))

    # Instagram'ga post chiqarish (faqat admin) - oddiy handlerlardan oldin
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(CommandHandler("cancel_post", cmd_cancel_post))
    app.add_handler(CommandHandler("ig_check", cmd_ig_check))
    app.add_handler(CallbackQueryHandler(ig_handle_callback, pattern=r"^ig_"), group=-1)
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.VIDEO), ig_handle_media),
        group=-1,
    )
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ig_handle_caption),
        group=-1,
    )

    # Tugmalar (Callback query)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Xabarlar
    private = filters.ChatType.PRIVATE
    app.add_handler(MessageHandler(private & filters.LOCATION, handle_location_message))
    app.add_handler(MessageHandler(private & filters.CONTACT, handle_contact))
    app.add_handler(
        MessageHandler(
            private & (
                filters.PHOTO
                | filters.Document.IMAGE
                | (filters.TEXT & ~filters.COMMAND)
            ),
            handle_message,
        )
    )
    app.add_handler(MessageHandler(private & (filters.VOICE | filters.AUDIO), handle_voice))

    log.info("Dekor Panel Telegram boti muvaffaqiyatli ishga tushmoqda...")
    app.run_polling(drop_pending_updates=True, bootstrap_retries=-1)


if __name__ == "__main__":
    main()
