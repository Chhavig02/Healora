import datetime
import random

from gemini_client import generate_text, is_available

STATIC_TIPS = [
    "Stay hydrated — aim for about 8 glasses of water a day.",
    "Aim for 7–9 hours of sleep a night; it's when your immune system does most of its repair work.",
    "Take a 5-minute break to stretch for every hour you spend sitting.",
    "Wash your hands for at least 20 seconds to cut your risk of common infections.",
    "A brisk 30-minute walk most days can lower blood pressure and improve mood.",
    "Add one extra serving of vegetables to a meal today.",
    "Chronic stress affects your heart too — try a few minutes of slow breathing when things get hectic.",
    "Don't skip breakfast — it helps stabilize blood sugar through the morning.",
    "Sunscreen isn't just for summer — daily SPF protects against long-term skin damage.",
    "Limit added sugar where you can; it adds up fast in drinks and snacks.",
    "Regular eye breaks (20-20-20 rule) reduce digital eye strain.",
    "Keep up with recommended vaccinations and screenings for your age group.",
    "Good posture while working reduces the risk of chronic back and neck pain.",
    "Alcohol in moderation matters — track how much you're actually drinking in a week.",
    "A short walk after meals can help with digestion and blood sugar control.",
]

_cache = {}


def get_daily_tip():
    today = datetime.date.today().isoformat()
    if today in _cache:
        return _cache[today]

    tip = None
    if is_available():
        tip = generate_text(
            "Give exactly one short (under 200 characters), friendly, general "
            "wellness tip for a health app's daily tip widget. Evidence-based, "
            "not specific to any single medical condition, plain text, no "
            "markdown, no quotation marks.",
            fallback=None,
        )
        if tip:
            tip = tip.strip().strip('"')

    if not tip:
        tip = random.choice(STATIC_TIPS)

    _cache.clear()
    _cache[today] = tip
    return tip
