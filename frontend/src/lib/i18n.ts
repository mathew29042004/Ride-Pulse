/**
 * Tamil and Hindi for the rider and driver apps.
 *
 * Strings are keyed by their English text, so `t("Where to?")` reads naturally in the code and
 * anything not translated yet simply shows in English. `{name}` placeholders are filled from the
 * second argument: `t("Meet at {place}", { place })`.
 */

import { useSyncExternalStore } from "react";

export type Language = "en" | "ta" | "hi";

export const LANGUAGES: { code: Language; label: string }[] = [
  { code: "en", label: "English" },
  { code: "ta", label: "தமிழ்" },
  { code: "hi", label: "हिन्दी" },
];

// English: [Tamil, Hindi]
const STRINGS: Record<string, [string, string]> = {
  // Tabs
  Ride: ["சவாரி", "राइड"],
  Activity: ["செயல்பாடு", "गतिविधि"],
  Wallet: ["வாலெட்", "वॉलेट"],
  Account: ["கணக்கு", "खाता"],
  Drive: ["ஓட்டு", "ड्राइव"],
  Earnings: ["வருமானம்", "कमाई"],
  Documents: ["ஆவணங்கள்", "दस्तावेज़"],

  // Home
  "Good morning": ["காலை வணக்கம்", "सुप्रभात"],
  "Good afternoon": ["மதிய வணக்கம்", "शुभ दोपहर"],
  "Good evening": ["மாலை வணக்கம்", "शुभ संध्या"],
  there: ["நண்பரே", "दोस्त"],
  "Where to?": ["எங்கே செல்ல வேண்டும்?", "कहाँ जाना है?"],
  Later: ["பிறகு", "बाद में"],
  "Pickup near {place}": ["{place} அருகில் பிக்அப்", "{place} के पास पिकअप"],
  Home: ["வீடு", "घर"],
  Work: ["அலுவலகம்", "ऑफ़िस"],
  "From {place}": ["{place} இலிருந்து", "{place} से"],

  // Trip statuses (as sent by the server)
  "Finding a driver": ["டிரைவரைத் தேடுகிறோம்", "ड्राइवर ढूंढ रहे हैं"],
  "Driver on the way": ["டிரைவர் வந்துகொண்டிருக்கிறார்", "ड्राइवर आ रहे हैं"],
  "Driver has arrived": ["டிரைவர் வந்துவிட்டார்", "ड्राइवर पहुँच गए हैं"],
  "On trip": ["பயணத்தில்", "यात्रा में"],
  Completed: ["முடிந்தது", "पूरी हुई"],
  Cancelled: ["ரத்து செய்யப்பட்டது", "रद्द"],
  "No driver found": ["டிரைவர் கிடைக்கவில்லை", "कोई ड्राइवर नहीं मिला"],

  // Booking
  "Pickup location": ["பிக்அப் இடம்", "पिकअप स्थान"],
  "Add a stop": ["நிறுத்தம் சேர்க்கவும்", "स्टॉप जोड़ें"],
  pickup: ["பிக்அப்", "पिकअप"],
  stop: ["நிறுத்தம்", "स्टॉप"],
  drop: ["இறங்கும் இடம்", "ड्रॉप"],
  "Set {field} on map": ["வரைபடத்தில் {field} அமைக்கவும்", "मैप पर {field} चुनें"],
  "Set {field}": ["{field} அமைக்கவும்", "{field} चुनें"],
  "Confirm {field}": ["{field} உறுதிசெய்", "{field} पक्का करें"],
  "Move the map to put the pin exactly where you are.": [
    "நீங்கள் இருக்கும் இடத்தில் பின் வருமாறு வரைபடத்தை நகர்த்தவும்.",
    "पिन को अपनी सही जगह पर लाने के लिए मैप खिसकाएँ।",
  ],
  Cancel: ["ரத்து", "रद्द करें"],
  "Choose a ride": ["சவாரியைத் தேர்ந்தெடுக்கவும்", "राइड चुनें"],
  Now: ["இப்போது", "अभी"],
  "{n}× high demand": ["{n}× அதிக தேவை", "{n}× ज़्यादा माँग"],
  "Prices are high right now. Tell me when they drop": [
    "இப்போது கட்டணம் அதிகம். குறைந்ததும் சொல்லுங்கள்",
    "अभी किराया ज़्यादा है। कम होने पर बताएँ",
  ],
  "We'll tell you when prices drop (for the next 2 hours)": [
    "கட்டணம் குறைந்ததும் சொல்கிறோம் (அடுத்த 2 மணி நேரம்)",
    "किराया कम होते ही बताएँगे (अगले 2 घंटे)",
  ],
  "{n} min away": ["{n} நிமிடத்தில்", "{n} मिनट दूर"],
  "No cars nearby": ["அருகில் வாகனம் இல்லை", "पास में कोई गाड़ी नहीं"],
  "Fare breakdown": ["கட்டண விவரம்", "किराये का ब्योरा"],
  "Total (upfront)": ["மொத்தம் (முன்கூட்டியே)", "कुल (पहले से तय)"],
  "Ride preferences": ["சவாரி விருப்பங்கள்", "राइड की पसंद"],
  "Quiet ride": ["அமைதியான பயணம்", "शांत राइड"],
  "AC on": ["AC வேண்டும்", "AC चालू"],
  "Extra luggage": ["கூடுதல் லக்கேஜ்", "ज़्यादा सामान"],
  "Woman driver": ["பெண் டிரைவர்", "महिला ड्राइवर"],
  "Women drivers nearby are asked first. If none is free, we'll find you the next best driver.": [
    "அருகிலுள்ள பெண் டிரைவர்களிடம் முதலில் கேட்கப்படும். யாரும் இல்லையெனில், அடுத்த சிறந்த டிரைவரைத் தருவோம்.",
    "पास की महिला ड्राइवरों से पहले पूछा जाता है। कोई खाली न हो तो अगला सबसे अच्छा ड्राइवर मिलेगा।",
  ],
  "Tip your driver": ["டிரைவருக்கு டிப்ஸ்", "ड्राइवर को टिप दें"],
  "(optional, 100% to them)": ["(விருப்பம், 100% அவருக்கே)", "(वैकल्पिक, 100% उन्हें)"],
  "No tip": ["டிப்ஸ் இல்லை", "टिप नहीं"],
  Cash: ["ரொக்கம்", "कैश"],
  Card: ["கார்டு", "कार्ड"],
  "Wallet balance {amount}": ["வாலெட் இருப்பு {amount}", "वॉलेट बैलेंस {amount}"],
  "Promo code": ["புரோமோ குறியீடு", "प्रोमो कोड"],
  Apply: ["பயன்படுத்து", "लागू करें"],
  "Book {ride} · {fare}": ["{ride} புக் செய் · {fare}", "{ride} बुक करें · {fare}"],
  " + ₹{tip} tip": [" + ₹{tip} டிப்ஸ்", " + ₹{tip} टिप"],
  "Schedule {ride} · {when}": ["{ride} முன்பதிவு · {when}", "{ride} शेड्यूल करें · {when}"],

  // Rider trip
  "Finding your {ride}": ["உங்கள் {ride} தேடப்படுகிறது", "आपकी {ride} ढूंढ रहे हैं"],
  "Matching you with a nearby driver": ["அருகிலுள்ள டிரைவருடன் இணைக்கிறோம்", "पास के ड्राइवर से जोड़ रहे हैं"],
  "Taking a while? Boost your request": ["தாமதமா? உங்கள் கோரிக்கையை பூஸ்ட் செய்யுங்கள்", "देर हो रही है? अपनी रिक्वेस्ट बूस्ट करें"],
  "Cancel request": ["கோரிக்கையை ரத்து செய்", "रिक्वेस्ट रद्द करें"],
  "Arriving in {time}": ["{time}-ல் வருகிறார்", "{time} में पहुँचेंगे"],
  "Your driver is here": ["உங்கள் டிரைவர் வந்துவிட்டார்", "आपके ड्राइवर आ गए हैं"],
  "{time} to drop": ["இறங்க {time}", "ड्रॉप तक {time}"],
  "{distance} away · meet at {place}": ["{distance} தொலைவில் · {place}-ல் சந்திக்கவும்", "{distance} दूर · {place} पर मिलें"],
  "Meet at {place}": ["{place}-ல் சந்திக்கவும்", "{place} पर मिलें"],
  "Free waiting: {n} min left": ["இலவச காத்திருப்பு: {n} நிமிடம் மீதம்", "मुफ़्त इंतज़ार: {n} मिनट बाकी"],
  "Waiting {n} min · waiting charges apply": [
    "{n} நிமிடம் காத்திருப்பு · காத்திருப்புக் கட்டணம் உண்டு",
    "{n} मिनट इंतज़ार · वेटिंग चार्ज लगेगा",
  ],
  "{distance} left · drop by {clock}": ["{distance} மீதம் · {clock}க்குள் இறக்கம்", "{distance} बाकी · {clock} तक ड्रॉप"],
  Call: ["அழை", "कॉल"],
  "Share trip": ["பயணத்தைப் பகிர்", "राइड शेयर करें"],
  Help: ["உதவி", "मदद"],
  "Pay cash": ["ரொக்கமாகச் செலுத்தவும்", "कैश में भुगतान"],
  "Pay by {method}": ["{method} மூலம் செலுத்தவும்", "{method} से भुगतान"],
  upfront: ["முன்கூட்டியே", "पहले से तय"],
  "Trip completed · {time}": ["பயணம் முடிந்தது · {time}", "राइड पूरी · {time}"],
  "How was your ride with {name}?": ["{name} உடனான பயணம் எப்படி இருந்தது?", "{name} के साथ राइड कैसी रही?"],
  "Add a comment (optional)": ["கருத்து சேர்க்கவும் (விருப்பம்)", "टिप्पणी जोड़ें (वैकल्पिक)"],
  "Submit rating": ["மதிப்பீட்டை அனுப்பு", "रेटिंग भेजें"],
  "Thanks for your rating ⭐": ["மதிப்பீட்டுக்கு நன்றி ⭐", "रेटिंग के लिए धन्यवाद ⭐"],
  "Fare details": ["கட்டண விவரம்", "किराये का ब्योरा"],
  Total: ["மொத்தம்", "कुल"],
  Again: ["மீண்டும்", "फिर से"],
  "Lost something in the car?": ["காரில் ஏதாவது தவறவிட்டீர்களா?", "गाड़ी में कुछ छूट गया?"],
  "Cancel this ride?": ["இந்த சவாரியை ரத்து செய்யவா?", "यह राइड रद्द करें?"],
  "Keep ride": ["சவாரியைத் தொடரவும்", "राइड जारी रखें"],
  "Cancel ride": ["சவாரியை ரத்து செய்", "राइड रद्द करें"],

  // Driver
  "You're online": ["நீங்கள் ஆன்லைனில் உள்ளீர்கள்", "आप ऑनलाइन हैं"],
  "You're offline": ["நீங்கள் ஆஃப்லைனில் உள்ளீர்கள்", "आप ऑफ़लाइन हैं"],
  "Finding trips near you": ["அருகிலுள்ள பயணங்களைத் தேடுகிறோம்", "आपके पास की राइड ढूंढ रहे हैं"],
  "Go online to start earning": ["சம்பாதிக்க ஆன்லைனுக்கு வாருங்கள்", "कमाई शुरू करने के लिए ऑनलाइन जाएँ"],
  "You can't go online yet": ["இன்னும் ஆன்லைனுக்கு வர முடியாது", "आप अभी ऑनलाइन नहीं जा सकते"],
  "Fix in Documents": ["ஆவணங்களில் சரிசெய்யவும்", "दस्तावेज़ों में ठीक करें"],
  "Tap the map to move your car": ["காரை நகர்த்த வரைபடத்தைத் தட்டவும்", "गाड़ी खिसकाने के लिए मैप पर टैप करें"],
  Accept: ["ஏற்றுக்கொள்", "स्वीकार करें"],
  Decline: ["நிராகரி", "मना करें"],
  Pickup: ["பிக்அப்", "पिकअप"],
  Drop: ["இறக்கம்", "ड्रॉप"],
  "Scan rider's QR code": ["பயணியின் QR குறியீட்டை ஸ்கேன் செய்", "राइडर का QR कोड स्कैन करें"],
  "Or enter the 4-digit PIN they read out": [
    "அல்லது அவர் சொல்லும் 4 இலக்க PIN-ஐ உள்ளிடவும்",
    "या राइडर का बताया 4 अंकों का PIN डालें",
  ],
  Start: ["தொடங்கு", "शुरू करें"],
  "I've arrived": ["வந்துவிட்டேன்", "पिकअप पर पहुँच गए"],
  "Cancel trip": ["பயணத்தை ரத்து செய்", "ट्रिप रद्द करें"],
  "Rider didn't show up": ["பயணி வரவில்லை", "राइडर नहीं आए"],
  "Complete trip": ["பயணத்தை முடி", "ट्रिप पूरी करें"],
  "Trip complete": ["பயணம் முடிந்தது", "ट्रिप पूरी"],
  "Rate rider & continue": ["பயணியை மதிப்பிட்டுத் தொடரவும்", "राइडर को रेटिंग दें और आगे बढ़ें"],
  "You earned": ["நீங்கள் சம்பாதித்தது", "आपकी कमाई"],

  // Account
  Language: ["மொழி", "भाषा"],
  "Dark mode": ["டார்க் மோட்", "डार्क मोड"],
  "Light mode": ["லைட் மோட்", "लाइट मोड"],
  "Log out": ["வெளியேறு", "लॉग आउट"],
};

const STORAGE_KEY = "rp.lang";

function stored(): Language {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "ta" || value === "hi") return value;
  } catch {
    /* storage may be unavailable */
  }
  return "en";
}

let current: Language = typeof window === "undefined" ? "en" : stored();
const listeners = new Set<() => void>();

export function getLanguage(): Language {
  return current;
}

export function setLanguage(language: Language) {
  current = language;
  if (typeof document !== "undefined") document.documentElement.lang = language;
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    /* storage may be unavailable */
  }
  listeners.forEach((fn) => fn());
}

/** Translate into the current language; English (or anything missing) passes through. */
export function t(text: string, vars?: Record<string, string | number>): string {
  const row = current === "en" ? undefined : STRINGS[text];
  const out = row ? row[current === "ta" ? 0 : 1] : text;
  return vars ? out.replace(/\{(\w+)\}/g, (match, key: string) => (key in vars ? String(vars[key]) : match)) : out;
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useLanguage(): [Language, (l: Language) => void] {
  return [useSyncExternalStore(subscribe, getLanguage, () => "en" as Language), setLanguage];
}

/** `const t = useT()` re-renders the component when the language changes. */
export function useT(): typeof t {
  useLanguage();
  return t;
}
