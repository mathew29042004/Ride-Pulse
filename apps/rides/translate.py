"""Language Bridge: chat between a rider and a driver who don't share a language.

Each user has an app language (English, Tamil, Hindi, Malayalam, Kannada or Telugu). When a
message is sent it's translated
into the other person's language:

* Quick replies and common trip phrases come from a built-in phrasebook in all six languages,
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
LANGUAGES = ("en", "ta", "hi", "ml", "kn", "te")
TIMEOUT_SECONDS = 4

# English, Tamil, Hindi, Malayalam, Kannada, Telugu
PHRASES: list[tuple[str, str, str, str, str, str]] = [
    (
        "I'm at the pickup point",
        "நான் பிக்அப் இடத்தில் இருக்கிறேன்",
        "मैं पिकअप पॉइंट पर हूँ",
        "ഞാൻ പിക്കപ്പ് പോയിന്റിലുണ്ട്",
        "ನಾನು ಪಿಕಪ್ ಸ್ಥಳದಲ್ಲಿದ್ದೇನೆ",
        "నేను పికప్ పాయింట్ వద్ద ఉన్నాను",
    ),
    (
        "Please come to the main gate",
        "தயவுசெய்து பிரதான வாயிலுக்கு வாருங்கள்",
        "कृपया मेन गेट पर आइए",
        "ദയവായി പ്രധാന ഗേറ്റിലേക്ക് വരൂ",
        "ದಯವಿಟ್ಟು ಮುಖ್ಯ ದ್ವಾರಕ್ಕೆ ಬನ್ನಿ",
        "దయచేసి మెయిన్ గేట్ వద్దకు రండి",
    ),
    (
        "I'll be there in 2 min",
        "2 நிமிடத்தில் வருகிறேன்",
        "मैं 2 मिनट में पहुँचता हूँ",
        "2 മിനിറ്റിൽ എത്തും",
        "2 ನಿಮಿಷದಲ್ಲಿ ಬರುತ್ತೇನೆ",
        "2 నిమిషాల్లో వస్తాను",
    ),
    ("Okay 👍", "சரி 👍", "ठीक है 👍", "ശരി 👍", "ಸರಿ 👍", "సరే 👍"),
    (
        "I'm on my way",
        "வந்துகொண்டிருக்கிறேன்",
        "मैं आ रहा हूँ",
        "ഞാൻ വരുന്നു",
        "ನಾನು ಬರುತ್ತಿದ್ದೇನೆ",
        "నేను వస్తున్నాను",
    ),
    (
        "I've reached the pickup",
        "பிக்அப் இடத்திற்கு வந்துவிட்டேன்",
        "मैं पिकअप पर पहुँच गया हूँ",
        "ഞാൻ പിക്കപ്പിൽ എത്തി",
        "ನಾನು ಪಿಕಪ್ ತಲುಪಿದ್ದೇನೆ",
        "నేను పికప్‌కు చేరుకున్నాను",
    ),
    (
        "Stuck in traffic, 5 more minutes",
        "டிராஃபிக்கில் சிக்கியுள்ளேன், இன்னும் 5 நிமிடம்",
        "ट्रैफ़िक में फँसा हूँ, 5 मिनट और",
        "ട്രാഫിക്കിൽ കുടുങ്ങി, 5 മിനിറ്റ് കൂടി",
        "ಟ್ರಾಫಿಕ್‌ನಲ್ಲಿ ಸಿಲುಕಿದ್ದೇನೆ, ಇನ್ನೂ 5 ನಿಮಿಷ",
        "ట్రాఫిక్‌లో ఇరుక్కున్నాను, మరో 5 నిమిషాలు",
    ),
    (
        "Where are you?",
        "நீங்கள் எங்கே இருக்கிறீர்கள்?",
        "आप कहाँ हैं?",
        "നിങ്ങൾ എവിടെയാണ്?",
        "ನೀವು ಎಲ್ಲಿದ್ದೀರಿ?",
        "మీరు ఎక్కడ ఉన్నారు?",
    ),
    (
        "Please call me",
        "தயவுசெய்து என்னை அழையுங்கள்",
        "कृपया मुझे कॉल करें",
        "ദയവായി എന്നെ വിളിക്കൂ",
        "ದಯವಿಟ್ಟು ನನಗೆ ಕರೆ ಮಾಡಿ",
        "దయచేసి నాకు కాల్ చేయండి",
    ),
    (
        "I'm waiting",
        "நான் காத்திருக்கிறேன்",
        "मैं इंतज़ार कर रहा हूँ",
        "ഞാൻ കാത്തിരിക്കുന്നു",
        "ನಾನು ಕಾಯುತ್ತಿದ್ದೇನೆ",
        "నేను వేచి ఉన్నాను",
    ),
    ("Thank you", "நன்றி", "धन्यवाद", "നന്ദി", "ಧನ್ಯವಾದ", "ధన్యవాదాలు"),
    (
        "Please wait 5 minutes",
        "தயவுசெய்து 5 நிமிடம் காத்திருங்கள்",
        "कृपया 5 मिनट रुकिए",
        "ദയവായി 5 മിനിറ്റ് കാത്തിരിക്കൂ",
        "ದಯವಿಟ್ಟು 5 ನಿಮಿಷ ಕಾಯಿರಿ",
        "దయచేసి 5 నిమిషాలు ఆగండి",
    ),
    (
        "I'm wearing a blue shirt",
        "நான் நீல சட்டை அணிந்திருக்கிறேன்",
        "मैंने नीली शर्ट पहनी है",
        "ഞാൻ നീല ഷർട്ട് ധരിച്ചിട്ടുണ്ട്",
        "ನಾನು ನೀಲಿ ಶರ್ಟ್ ಧರಿಸಿದ್ದೇನೆ",
        "నేను నీలం చొక్కా వేసుకున్నాను",
    ),
    (
        "Please drive slowly",
        "தயவுசெய்து மெதுவாக ஓட்டுங்கள்",
        "कृपया धीरे चलाइए",
        "ദയവായി പതുക്കെ ഓടിക്കൂ",
        "ದಯವಿಟ್ಟು ನಿಧಾನವಾಗಿ ಓಡಿಸಿ",
        "దయచేసి నెమ్మదిగా నడపండి",
    ),
    (
        "Please turn on the AC",
        "தயவுசெய்து AC போடுங்கள்",
        "कृपया AC चालू कीजिए",
        "ദയവായി AC ഓണാക്കൂ",
        "ದಯವಿಟ್ಟು AC ಆನ್ ಮಾಡಿ",
        "దయచేసి AC ఆన్ చేయండి",
    ),
    (
        "Stop here, please",
        "இங்கே நிறுத்துங்கள்",
        "यहीं रोक दीजिए",
        "ഇവിടെ നിർത്തൂ",
        "ಇಲ್ಲಿ ನಿಲ್ಲಿಸಿ",
        "ఇక్కడ ఆపండి",
    ),
    ("Yes", "ஆம்", "हाँ", "അതെ", "ಹೌದು", "అవును"),
    ("No", "இல்லை", "नहीं", "ഇല്ല", "ಇಲ್ಲ", "కాదు"),
]

_INDEX: dict[str, tuple[str, ...]] = {}
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
