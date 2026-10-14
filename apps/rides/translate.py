"""Language Bridge: chat between a rider and a driver who don't share a language.

Each user has an app language (English, Tamil or Hindi). When a message is sent it's translated
into the other person's language:

* Quick replies and common trip phrases come from a built-in phrasebook in all three languages,
  so the common case works offline and instantly.
* Anything else is sent to Google Cloud Translation when ``GOOGLE_TRANSLATE_API_KEY`` is set;
  without a key the original is shown (the app says so).
"""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)
LANGUAGES = ("en", "ta", "hi")
TIMEOUT_SECONDS = 4

# English, Tamil, Hindi
PHRASES: list[tuple[str, str, str]] = [
    ("I'm at the pickup point", "நான் பிக்அப் இடத்தில் இருக்கிறேன்", "मैं पिकअप पॉइंट पर हूँ"),
    ("Please come to the main gate", "தயவுசெய்து பிரதான வாயிலுக்கு வாருங்கள்", "कृपया मेन गेट पर आइए"),
    ("I'll be there in 2 min", "2 நிமிடத்தில் வருகிறேன்", "मैं 2 मिनट में पहुँचता हूँ"),
    ("Okay 👍", "சரி 👍", "ठीक है 👍"),
    ("I'm on my way", "வந்துகொண்டிருக்கிறேன்", "मैं आ रहा हूँ"),
    ("I've reached the pickup", "பிக்அப் இடத்திற்கு வந்துவிட்டேன்", "मैं पिकअप पर पहुँच गया हूँ"),
    (
        "Stuck in traffic, 5 more minutes",
        "டிராஃபிக்கில் சிக்கியுள்ளேன், இன்னும் 5 நிமிடம்",
        "ट्रैफ़िक में फँसा हूँ, 5 मिनट और",
    ),
    ("Where are you?", "நீங்கள் எங்கே இருக்கிறீர்கள்?", "आप कहाँ हैं?"),
    ("Please call me", "தயவுசெய்து என்னை அழையுங்கள்", "कृपया मुझे कॉल करें"),
    ("I'm waiting", "நான் காத்திருக்கிறேன்", "मैं इंतज़ार कर रहा हूँ"),
    ("Thank you", "நன்றி", "धन्यवाद"),
    ("Please wait 5 minutes", "தயவுசெய்து 5 நிமிடம் காத்திருங்கள்", "कृपया 5 मिनट रुकिए"),
    ("I'm wearing a blue shirt", "நான் நீல சட்டை அணிந்திருக்கிறேன்", "मैंने नीली शर्ट पहनी है"),
    ("Please drive slowly", "தயவுசெய்து மெதுவாக ஓட்டுங்கள்", "कृपया धीरे चलाइए"),
    ("Please turn on the AC", "தயவுசெய்து AC போடுங்கள்", "कृपया AC चालू कीजिए"),
    ("Stop here, please", "இங்கே நிறுத்துங்கள்", "यहीं रोक दीजिए"),
    ("Yes", "ஆம்", "हाँ"),
    ("No", "இல்லை", "नहीं"),
]

_INDEX: dict[str, tuple[str, str, str]] = {}
for _row in PHRASES:
    for _text in _row:
        _INDEX[re.sub(r"[\s.!?,]+", " ", _text).strip().casefold()] = _row


def _key(text: str) -> str:
    return re.sub(r"[\s.!?,]+", " ", text).strip().casefold()


def phrase(text: str) -> tuple[str | None, dict[str, str]]:
    """(language, {lang: text}) if ``text`` is a phrasebook entry, else (None, {})."""
    row = _INDEX.get(_key(text))
    if row is None:
        return None, {}
    source = next(lang for lang, t in zip(LANGUAGES, row, strict=True) if _key(t) == _key(text))
    return source, dict(zip(LANGUAGES, row, strict=True))


def _google(text: str, target: str) -> str | None:
    key = getattr(settings, "GOOGLE_TRANSLATE_API_KEY", "")
    if not key:
        return None
    body = urllib.parse.urlencode({"q": text, "target": target, "format": "text"}).encode()
    request = urllib.request.Request(
        f"https://translation.googleapis.com/language/translate/v2?key={key}", data=body
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
        return data["data"]["translations"][0]["translatedText"]
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        logger.warning("Translation failed: %s", exc)
        return None


def translate(text: str, *, sender_language: str, target: str) -> tuple[str, dict[str, str]]:
    """The message's language and its translations (only ``target`` beyond the phrasebook)."""
    source, known = phrase(text)
    if source:
        return source, {lang: t for lang, t in known.items() if lang != source}
    source = sender_language if sender_language in LANGUAGES else "en"
    if target == source:
        return source, {}
    translated = _google(text, target)
    return source, ({target: translated} if translated else {})
