# 🏢 Dekor Panel: Telegram Savdo va Maslahatchi Boti (AI)

Ushbu bot **Dekor Panel** (Toshkent, O'zbekiston) zavodi uchun maxsus ishlab chiqilgan bo'lib, **Claude AI** sun'iy intellekti, to'liq interaktiv katalog, avtomatlashtirilgan zayavka tizimi hamda **Administrator Boshqaruv Paneli (Admin Panel)** bilan jihozlangan.

---

## ⚙️ Administrator Paneli (Faqat Adminlar Uchun)

Admin paneliga kirish uchun `/admin` buyrug'ini yuboring yoki admin akkauntidan `/start` bosilganda pastki menyuda paydo bo'ladigan **«⚙️ Admin Panel»** tugmasini bosing.

> **Xavfsizlik:** Admin panelga faqat `.env` dagi `MANAGER_CHAT_ID` egasi (yoki `ADMIN_IDS` dagi ID egalari) kira oladi. Oddiy foydalanuvchilar kira olmaydi.

### Admin Panel Imkoniyatlari:

1. **📸 Kataloglarga rasm qo'shish:**
   - «📸 Rasm qo'shish» tugmasini bosing.
   - Kerakli katalog toifasini tanlang (masalan: *Алюкобонд*, *PVX panellar*, *Baget* va h.k.).
   - Rasmni Telegram orqali yuboring.
   - **💡 Foydali maslahat:** Rasm tagiga (caption) mahsulot nomi yoki rangini yozib yuborsangiz (masalan: *«1014 Oltin yaltiroq»*), fayl aynan shu nom bilan diskka saqlanadi va mijozlar qidirganda darhol topiladi!
   - Bitta yoki bir nechta rasmni ketma-ket yuborishingiz mumkin.

2. **🗑 Kataloglardan rasm o'chirish:**
   - «🗑 Rasm o'chirish» tugmasini bosing.
   - Kerakli toifani tanlang (har bir toifa yonida mavjud rasmlar soni ko'rsatiladi).
   - O'chirmoqchi bo'lgan rasmingizni tanlang (sahifalash: ⬅️ / ➡️).
   - Bot rasmning o'zini va nomini tasdiqlash uchun ko'rsatadi: **«✅ Ha, o'chirilsin»** tugmasini bosishingiz bilan rasm diskdan to'liq o'chiriladi.

3. **📍 Lokatsiyani sozlash va o'zgartirish:**
   - «📍 Lokatsiyani sozlash» bo'limiga kiring:
     - **📌 Geopozitsiya yuborish:** Telegramdagi qisqich (📎) -> «Geopozitsiya» orqali xaritadan yangi nuqtani yuborsangiz, bot darhol yangi koordinatalarni saqlab oladi.
     - **🏢 Manzil matnini tahrirlash:** Zavodning yangi matnli manzilini kiritish.
     - **🚩 Mo'ljalni tahrirlash:** Yangi mo'ljalni kiritish (masalan: *Coca-Cola zavodi yonida*).
     - **🕒 Ish vaqtini tahrirlash:** Ish tartibini o'zgartirish.
   - Barcha o'zgarishlar `bot_config.json` faylida doimiy saqlanadi va mijozlarga darhol yangilangan ma'lumotlar ko'rinadi.

4. **📊 Statistika va 🔄 Qayta yuklash:**
   - Barcha toifalardagi rasmlar soni, faol chatlar va AI modelini tekshirish.
   - Botni o'chirmasdan turib yangi yuklangan fayllarni qayta indekslash.

---

## 🌟 Foydalanuvchilar Uchun Asosiy Imkoniyatlar

1. **🤖 Aqlli AI Konsultant (Claude 3.5 / 3.7 Sonnet):**
   - O'zbek va rus tillarida xushmuomala savdo konsultatsiyasi.
   - Xaridor yuborgan devor/xona fotosuratlarini ko'rib, mos mahsulotlarni tanlab berish.
2. **📁 Interaktiv Katalog va Galereya:**
   - 15 ta toifa bo'yicha namunalar.
   - Ranglar va kodlar bo'yicha aqlli filtr (`oq`, `qora`, `dub`, `oltin`, `1014`, `1001` va h.k.).
3. **📱 1-Bosishda Telefon Raqam Qoldirish:**
   - Mijoz raqamini ulashishi yoki matn sifatida yozib yuborishi bilan menejerga to'liq buyurtma kartochkasi boradi.
4. **📍 Xarita va Navigatsiya:**
   - Google Maps va Yandex Navigator orqali zavodga to'g'ridan-to'g'ri marshrut.

---

## ⚙️ Ishga Tushirish

```bash
pip install -r requirements.txt
python bot.py
```
