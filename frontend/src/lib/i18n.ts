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

  // Availability
  "Not running now": ["இப்போது இயங்கவில்லை", "अभी उपलब्ध नहीं"],
  "Switch to {ride}": ["{ride}-க்கு மாறவும்", "{ride} चुनें"],
  "Or search anyway with a boost (100% to the driver)": [
    "அல்லது பூஸ்ட் உடன் தேடவும் (100% டிரைவருக்கு)",
    "या बूस्ट के साथ खोजें (100% ड्राइवर को)",
  ],
  "No boost": ["பூஸ்ட் இல்லை", "बूस्ट नहीं"],
  "Try again": ["மீண்டும் முயற்சி செய்", "फिर कोशिश करें"],

  // Fair Share Meter and Driver Wellbeing
  "Where your {amount} went": ["உங்கள் {amount} எங்கே போனது", "आपके {amount} कहाँ गए"],
  "{n}% to your driver": ["{n}% உங்கள் டிரைவருக்கு", "{n}% आपके ड्राइवर को"],
  "Your driver": ["உங்கள் டிரைவர்", "आपके ड्राइवर"],
  "Ride Pulse commission": ["Ride Pulse கமிஷன்", "Ride Pulse कमीशन"],
  "Booking fee": ["புக்கிங் கட்டணம்", "बुकिंग शुल्क"],
  "Airport access fee": ["விமான நிலைய கட்டணம்", "एयरपोर्ट शुल्क"],
  "Your discount (paid by Ride Pulse)": ["உங்கள் தள்ளுபடி (Ride Pulse செலுத்தியது)", "आपकी छूट (Ride Pulse ने दी)"],
  "GST (to the government)": ["GST (அரசுக்கு)", "GST (सरकार को)"],
  "Boosts and tips go 100% to the driver.": ["பூஸ்ட் மற்றும் டிப்ஸ் 100% டிரைவருக்கே.", "बूस्ट और टिप 100% ड्राइवर को जाते हैं।"],
  "Real earnings · last 7 days": ["உண்மையான வருமானம் · கடந்த 7 நாட்கள்", "असली कमाई · पिछले 7 दिन"],
  "{n} h online": ["{n} மணி ஆன்லைன்", "{n} घंटे ऑनलाइन"],
  "per hour after costs": ["செலவுகளுக்குப் பின் ஒரு மணிக்கு", "खर्च के बाद प्रति घंटा"],
  "{time} driving": ["{time} ஓட்டியது", "{time} ड्राइविंग"],
  "break in {time}": ["{time}-ல் ஓய்வு", "{time} में ब्रेक"],
  "break due": ["ஓய்வு நேரம்", "ब्रेक का समय"],
  "Rest break": ["ஓய்வு இடைவேளை", "आराम का ब्रेक"],

  // Bid your fare and Sure Ride
  "Offer your fare": ["உங்கள் கட்டணத்தைச் சொல்லுங்கள்", "अपना किराया बताएँ"],
  "Usual fare {fare}": ["வழக்கமான கட்டணம் {fare}", "सामान्य किराया {fare}"],
  "Your offer": ["உங்கள் சலுகை", "आपका ऑफ़र"],
  "Your offer: {fare}": ["உங்கள் சலுகை: {fare}", "आपका ऑफ़र: {fare}"],
  "Drivers may accept or counter. Lower offers can take longer.": [
    "டிரைவர்கள் ஏற்கலாம் அல்லது எதிர்ச் சலுகை தரலாம். குறைந்த சலுகைக்கு நேரம் ஆகலாம்.",
    "ड्राइवर मान सकते हैं या जवाबी ऑफ़र दे सकते हैं। कम ऑफ़र में देर लग सकती है।",
  ],
  "A higher offer gets you a driver faster. The extra is all theirs.": [
    "அதிக சலுகை விரைவில் டிரைவரைப் பெற்றுத் தரும். கூடுதல் தொகை முழுவதும் அவருக்கே.",
    "ज़्यादा ऑफ़र से ड्राइवर जल्दी मिलता है। अतिरिक्त राशि पूरी उनकी।",
  ],
  "Sure Ride · +{fee}": ["உறுதிப் பயணம் · +{fee}", "श्योर राइड · +{fee}"],
  "Driver at your pickup within {n} min, or {refund} back in your wallet": [
    "{n} நிமிடத்துக்குள் டிரைவர் வருவார், இல்லையெனில் {refund} உங்கள் வாலெட்டுக்கு",
    "{n} मिनट में ड्राइवर पिकअप पर, वरना {refund} आपके वॉलेट में",
  ],
  "Drivers can accept your price or send a counter-offer. They'll show up here.": [
    "டிரைவர்கள் உங்கள் விலையை ஏற்கலாம் அல்லது எதிர்ச் சலுகை அனுப்பலாம். அவை இங்கே தெரியும்.",
    "ड्राइवर आपकी क़ीमत मान सकते हैं या जवाबी ऑफ़र भेज सकते हैं। वे यहाँ दिखेंगे।",
  ],
  "Driver booked at their price": ["அவர் விலையில் டிரைவர் புக் ஆனார்", "उनकी क़ीमत पर ड्राइवर बुक हुआ"],
  "Rider offers {offer} · usual fare {usual}": ["பயணி {offer} தருகிறார் · வழக்கம் {usual}", "राइडर {offer} दे रहे हैं · सामान्य {usual}"],
  "Or counter-offer": ["அல்லது எதிர்ச் சலுகை", "या जवाबी ऑफ़र दें"],

  // Parcels
  "Send a parcel": ["பார்சல் அனுப்பு", "पार्सल भेजें"],
  "Documents, keys, food: delivered by bike": ["ஆவணங்கள், சாவி, உணவு: பைக்கில் டெலிவரி", "दस्तावेज़, चाबी, खाना: बाइक से डिलीवरी"],
  "Parcel details": ["பார்சல் விவரங்கள்", "पार्सल का ब्योरा"],
  Recipient: ["பெறுபவர்", "पाने वाले"],
  "Their mobile": ["அவர் மொபைல்", "उनका मोबाइल"],
  Food: ["உணவு", "खाना"],
  Electronics: ["மின்னணுப் பொருட்கள்", "इलेक्ट्रॉनिक्स"],
  Clothes: ["துணிகள்", "कपड़े"],
  Keys: ["சாவிகள்", "चाबियाँ"],
  Other: ["மற்றவை", "अन्य"],
  Weight: ["எடை", "वज़न"],
  "up to {n} kg": ["{n} கிலோ வரை", "{n} किलो तक"],
  "Note for the driver": ["டிரைவருக்குக் குறிப்பு", "ड्राइवर के लिए नोट"],
  "To {name}": ["{name}-க்கு", "{name} को"],
  "Delivered {when}": ["டெலிவரி ஆனது {when}", "डिलीवर हुआ {when}"],
  "Delivery code (we've sent it to {name} too)": ["டெலிவரி குறியீடு ({name}-க்கும் அனுப்பினோம்)", "डिलीवरी कोड ({name} को भी भेजा है)"],
  "Driver is here to pick up your parcel": ["உங்கள் பார்சலை எடுக்க டிரைவர் வந்துள்ளார்", "ड्राइवर आपका पार्सल लेने आ गए हैं"],
  "Parcel arriving in {time}": ["பார்சல் {time}-ல் சேரும்", "पार्सल {time} में पहुँचेगा"],
  "New parcel delivery": ["புதிய பார்சல் டெலிவரி", "नई पार्सल डिलीवरी"],
  "Deliver to {name}": ["{name}-க்கு டெலிவரி", "{name} को डिलीवर करें"],
  "Delivery code from the recipient": ["பெறுபவரிடமிருந்து டெலிவரி குறியீடு", "पाने वाले से डिलीवरी कोड"],
  "Mark delivered": ["டெலிவரி முடிந்தது", "डिलीवर्ड मार्क करें"],

  // Rentals and intercity
  Parcel: ["பார்சல்", "पार्सल"],
  "Send by bike": ["பைக்கில் அனுப்பு", "बाइक से भेजें"],
  Rentals: ["வாடகை", "रेंटल"],
  "By the hour": ["மணிநேர அடிப்படையில்", "घंटे के हिसाब से"],
  Intercity: ["வெளியூர்", "इंटरसिटी"],
  Outstation: ["வெளியூர் பயணம்", "आउटस्टेशन"],
  "A car and driver for as long as you need. Make stops, run errands; it ends wherever you finish.": [
    "தேவையான நேரம் வரை கார் மற்றும் டிரைவர். நிறுத்தங்கள், வேலைகள்; நீங்கள் முடிக்கும் இடத்தில் முடியும்.",
    "जितनी देर चाहिए, कार और ड्राइवर। रुकें, काम निपटाएँ; जहाँ आप खत्म करें वहीं खत्म।",
  ],
  "Outstation trips with a driver. Tolls, parking and state permits are paid on the way.": [
    "டிரைவருடன் வெளியூர் பயணம். சுங்கம், பார்க்கிங், மாநில அனுமதி வழியில் செலுத்தப்படும்.",
    "ड्राइवर के साथ आउटस्टेशन यात्रा। टोल, पार्किंग और स्टेट परमिट रास्ते में चुकाएँ।",
  ],
  "No intercity destinations from here yet.": ["இங்கிருந்து இன்னும் வெளியூர் இடங்கள் இல்லை.", "यहाँ से अभी कोई इंटरसिटी गंतव्य नहीं।"],
  "One way": ["ஒரு வழி", "एक तरफ़"],
  "Round trip": ["போய் வர", "आना-जाना"],
  "{n} days": ["{n} நாட்கள்", "{n} दिन"],
  "About {distance} by road, one way": ["சாலை வழியாக சுமார் {distance}, ஒரு வழி", "सड़क से लगभग {distance}, एक तरफ़"],
  "Extra km and minutes beyond the package are added at the end.": [
    "தொகுப்பைத் தாண்டிய கி.மீ. மற்றும் நிமிடங்கள் இறுதியில் சேர்க்கப்படும்.",
    "पैकेज से ज़्यादा किमी और मिनट अंत में जोड़े जाते हैं।",
  ],

  "Rental · {h} h / {km} km": ["வாடகை · {h} மணி / {km} கி.மீ.", "रेंटल · {h} घंटे / {km} किमी"],
  "Intercity to {place} · {km} km · {how}": ["{place}-க்கு வெளியூர் · {km} கி.மீ. · {how}", "{place} के लिए इंटरसिटी · {km} किमी · {how}"],
  "round trip, {n} days": ["போய் வர, {n} நாட்கள்", "आना-जाना, {n} दिन"],
  "one way": ["ஒரு வழி", "एक तरफ़"],

  // Chat quick replies (must match rides/translate.py's phrasebook)
  "I'm at the pickup point": ["நான் பிக்அப் இடத்தில் இருக்கிறேன்", "मैं पिकअप पॉइंट पर हूँ"],
  "Please come to the main gate": ["தயவுசெய்து பிரதான வாயிலுக்கு வாருங்கள்", "कृपया मेन गेट पर आइए"],
  "I'll be there in 2 min": ["2 நிமிடத்தில் வருகிறேன்", "मैं 2 मिनट में पहुँचता हूँ"],
  "Okay 👍": ["சரி 👍", "ठीक है 👍"],
  "I'm on my way": ["வந்துகொண்டிருக்கிறேன்", "मैं आ रहा हूँ"],
  "I've reached the pickup": ["பிக்அப் இடத்திற்கு வந்துவிட்டேன்", "मैं पिकअप पर पहुँच गया हूँ"],
  "Stuck in traffic, 5 more minutes": ["டிராஃபிக்கில் சிக்கியுள்ளேன், இன்னும் 5 நிமிடம்", "ट्रैफ़िक में फँसा हूँ, 5 मिनट और"],

  // Eco, Fare Lock, Language Bridge
  "You saved {kg} kg of CO₂ vs driving your own car · +{n} eco points": [
    "சொந்தக் காரை ஓட்டுவதை விட {kg} கிலோ CO₂ சேமித்தீர்கள் · +{n} சூழல் புள்ளிகள்",
    "अपनी कार चलाने के मुक़ाबले {kg} किलो CO₂ बचाया · +{n} इको पॉइंट",
  ],
  "Your eco score": ["உங்கள் சூழல் மதிப்பெண்", "आपका इको स्कोर"],
  "eco points": ["சூழல் புள்ளிகள்", "इको पॉइंट"],
  Redeem: ["பெறு", "रिडीम करें"],
  Electric: ["மின்சார வாகனம்", "इलेक्ट्रिक"],
  "Lock this fare for your commute": ["உங்கள் தினசரிப் பயணத்துக்கு இந்தக் கட்டணத்தைப் பூட்டு", "रोज़ के सफ़र के लिए यह किराया लॉक करें"],
  "Lock this fare": ["இந்தக் கட்டணத்தைப் பூட்டு", "यह किराया लॉक करें"],
  "Fare locked": ["கட்டணம் பூட்டப்பட்டது", "किराया लॉक है"],
  "Fare Locks": ["பூட்டிய கட்டணங்கள்", "लॉक किए किराए"],
  week: ["வாரம்", "हफ़्ता"],
  "Translated · show original": ["மொழிபெயர்க்கப்பட்டது · மூலத்தைக் காட்டு", "अनुवादित · मूल देखें"],
  "Show translation": ["மொழிபெயர்ப்பைக் காட்டு", "अनुवाद देखें"],
  Mon: ["திங்", "सोम"],
  Tue: ["செவ்", "मंगल"],
  Wed: ["புத", "बुध"],
  Thu: ["வியா", "गुरु"],
  Fri: ["வெள்", "शुक्र"],
  Sat: ["சனி", "शनि"],
  Sun: ["ஞாயி", "रवि"],

  "No rides are available here right now. Please try again in a little while.": [
    "இப்போது இங்கே சவாரிகள் கிடைக்கவில்லை. சிறிது நேரம் கழித்து முயற்சிக்கவும்.",
    "अभी यहाँ कोई राइड उपलब्ध नहीं है। थोड़ी देर बाद कोशिश करें।",
  ],
  "No cars are available for this right now.": ["இதற்கு இப்போது கார்கள் இல்லை.", "अभी इसके लिए कोई कार उपलब्ध नहीं है।"],

  // Safety+
  "Is everything OK?": ["எல்லாம் சரியாக இருக்கிறதா?", "क्या सब ठीक है?"],
  "Are you OK?": ["நீங்கள் நலமா?", "क्या आप ठीक हैं?"],
  "The car hasn't moved for a while": ["கார் சிறிது நேரமாக நகரவில்லை", "गाड़ी कुछ देर से रुकी हुई है"],
  "The car is far from the route": ["கார் வழித்தடத்திலிருந்து விலகியுள்ளது", "गाड़ी रास्ते से काफ़ी हट गई है"],
  "The trip is taking much longer than expected": ["பயணம் எதிர்பார்த்ததை விட அதிக நேரம் ஆகிறது", "राइड उम्मीद से काफ़ी लंबी हो रही है"],
  "We lost the car's location": ["காரின் இருப்பிடம் கிடைக்கவில்லை", "गाड़ी की लोकेशन नहीं मिल रही"],
  "If we don't hear back in a few minutes, our safety team will check on you.": [
    "சில நிமிடங்களில் பதில் வராவிட்டால், எங்கள் பாதுகாப்புக் குழு உங்களைத் தொடர்புகொள்ளும்.",
    "कुछ मिनट में जवाब न मिला तो हमारी सेफ़्टी टीम आपसे संपर्क करेगी।",
  ],
  "I'm OK": ["நான் நலம்", "मैं ठीक हूँ"],
  "Get help": ["உதவி வேண்டும்", "मदद चाहिए"],
  "Thanks. We'll keep watching the trip.": ["நன்றி. பயணத்தைத் தொடர்ந்து கவனிக்கிறோம்.", "धन्यवाद। हम राइड पर नज़र रखेंगे।"],
  "Our safety team has been alerted and will call you now.": [
    "எங்கள் பாதுகாப்புக் குழுவுக்குத் தெரிவிக்கப்பட்டது, இப்போது அழைப்பார்கள்.",
    "हमारी सेफ़्टी टीम को सूचना दे दी गई है, वे अभी कॉल करेंगे।",
  ],
  "Night Safe ride": ["இரவு பாதுகாப்புப் பயணம்", "नाइट सेफ़ राइड"],
  "End the trip at the drop point.": ["இறங்கும் இடத்தில் மட்டும் பயணத்தை முடிக்கவும்.", "ट्रिप ड्रॉप पॉइंट पर ही पूरी करें।"],
  "The rider confirmed an earlier stop.": ["பயணி முன்கூட்டியே இறங்க உறுதிசெய்தார்.", "राइडर ने पहले उतरने की पुष्टि की है।"],
  "Night Safe is on": ["இரவு பாதுகாப்பு இயக்கத்தில்", "नाइट सेफ़ चालू है"],
  "Your contacts are following this ride.": ["உங்கள் நம்பிக்கைக்குரியவர்கள் இந்தப் பயணத்தைப் பார்க்கிறார்கள்.", "आपके संपर्क इस राइड को देख रहे हैं।"],
  "Extra safety checks are on.": ["கூடுதல் பாதுகாப்புச் சோதனைகள் இயக்கத்தில்.", "अतिरिक्त सेफ़्टी जाँच चालू है।"],
  "End here": ["இங்கே முடி", "यहीं उतरें"],
  "End your ride here?": ["இங்கேயே பயணத்தை முடிக்கவா?", "यहीं राइड खत्म करें?"],
  "Yes, drop me here": ["ஆம், இங்கே இறக்கவும்", "हाँ, मुझे यहीं उतारें"],
  "I'm home safe": ["நான் பாதுகாப்பாக வீடு சேர்ந்தேன்", "मैं सुरक्षित घर पहुँच गया/गई"],
  "We've told your contacts you're home safe.": ["நீங்கள் பாதுகாப்பாக சேர்ந்ததை உங்கள் நம்பிக்கைக்குரியவர்களுக்குத் தெரிவித்தோம்.", "हमने आपके संपर्कों को बता दिया कि आप सुरक्षित पहुँच गए।"],
  "Your contacts know you're home safe.": ["நீங்கள் பாதுகாப்பாக சேர்ந்தது உங்கள் நம்பிக்கைக்குரியவர்களுக்குத் தெரியும்.", "आपके संपर्कों को पता है कि आप सुरक्षित पहुँच गए।"],
  "Night Safe mode": ["இரவு பாதுகாப்பு முறை", "नाइट सेफ़ मोड"],
  "Trusted contacts": ["நம்பிக்கைக்குரியவர்கள்", "भरोसेमंद संपर्क"],
  "Add a trusted contact": ["நம்பிக்கைக்குரியவரைச் சேர்", "भरोसेमंद संपर्क जोड़ें"],
  "Night rides": ["இரவுப் பயணங்கள்", "रात की राइड"],
  "Every ride": ["ஒவ்வொரு பயணமும்", "हर राइड"],
  "Only when I share": ["நான் பகிரும்போது மட்டும்", "सिर्फ़ जब मैं शेयर करूँ"],
  "Share my trips": ["என் பயணங்களைப் பகிர்", "मेरी राइड शेयर करें"],
  Name: ["பெயர்", "नाम"],
  "Mobile number": ["மொபைல் எண்", "मोबाइल नंबर"],
  Save: ["சேமி", "सेव करें"],

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
