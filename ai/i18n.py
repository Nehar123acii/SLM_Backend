"""Multilingual explanation & template fallbacks (English, Hindi, Kannada).

Supports `"en"` (English), `"hi"` (Hindi), and `"kn"` (Kannada) explanations.
When the SLM returns an empty explanation or fails to produce the requested
language script, deterministic template fallbacks are used.
"""

from __future__ import annotations

import re

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_KANNADA_RE = re.compile(r"[\u0C80-\u0CFF]")

COLUMN_CATEGORY_TEMPLATES: dict[str, dict[str, str]] = {
    "GOVERNMENT_ID": {
        "en": "Column '{col}' contains government-issued identity numbers ({ident}) classified as {tier}.",
        "hi": "कॉलम '{col}' में सरकारी पहचान संख्या ({ident}) है, जिसे {tier} के रूप में वर्गीकृत किया गया है।",
        "kn": "'{col}' ಕಾಲಮ್ ಸರ್ಕಾರಿ ಗುರುತಿನ ಸಂಖ್ಯೆಯನ್ನು ({ident}) ಹೊಂದಿದ್ದು, ಇದನ್ನು {tier} ಎಂದು ವರ್ಗೀಕರಿಸಲಾಗಿದೆ.",
    },
    "CONTACT_INFO": {
        "en": "Column '{col}' stores personal contact details ({ident}) used to reach an individual.",
        "hi": "कॉलम '{col}' में व्यक्तिगत संपर्क विवरण ({ident}) संग्रहीत हैं।",
        "kn": "'{col}' ಕಾಲಮ್ ವ್ಯಕ್ತಿಯ ಸಂಪರ್ಕ ವಿವರಗಳನ್ನು ({ident}) ಒಳಗೊಂಡಿದೆ.",
    },
    "IDENTITY_DEMOGRAPHIC": {
        "en": "Column '{col}' holds personal identity or demographic attributes ({ident}).",
        "hi": "कॉलम '{col}' में व्यक्तिगत पहचान या जनसांख्यिकीय जानकारी ({ident}) है।",
        "kn": "'{col}' ಕಾಲಮ್ ವೈಯಕ್ತಿಕ ಗುರುತು ಅಥವಾ ಜನಸಂಖ್ಯಾ ಮಾಹಿತಿಯನ್ನು ({ident}) ಹೊಂದಿದೆ.",
    },
    "FINANCIAL_DATA": {
        "en": "Column '{col}' contains financial or payment details ({ident}) requiring strict protection.",
        "hi": "कॉलम '{col}' में वित्तीय या भुगतान विवरण ({ident}) हैं जिन्हें कड़ी सुरक्षा की आवश्यकता है।",
        "kn": "'{col}' ಕಾಲಮ್ ಆರ್ಥಿಕ ಅಥವಾ ಪಾವತಿ ವಿವರಗಳನ್ನು ({ident}) ಒಳಗೊಂಡಿದೆ ಮತ್ತು ಹೆಚ್ಚಿನ ಭದ್ರತೆ ಅಗತ್ಯವಿದೆ.",
    },
    "HEALTH_MEDICAL": {
        "en": "Column '{col}' contains clinical or health-related personal information ({ident}).",
        "hi": "कॉलम '{col}' में स्वास्थ्य या चिकित्सा से संबंधित व्यक्तिगत जानकारी ({ident}) है।",
        "kn": "'{col}' ಕಾಲಮ್ ಆರೋಗ್ಯ ಅಥವಾ ವೈದ್ಯಕೀಯ ಸಂಬಂಧಿತ ವೈಯಕ್ತಿಕ ಮಾಹಿತಿಯನ್ನು ({ident}) ಒಳಗೊಂಡಿದೆ.",
    },
    "CHILDREN_DATA": {
        "en": "Column '{col}' indicates personal data of a minor under 18, requiring verifiable parental consent under DPDP Section 9.",
        "hi": "कॉलम '{col}' 18 वर्ष से कम आयु के नाबालिग के डेटा को दर्शाता है, जिसके लिए DPDP धारा 9 के तहत माता-पिता की सहमति आवश्यक है।",
        "kn": "'{col}' ಕಾಲಮ್ 18 ವರ್ಷಕ್ಕಿಂತ ಕಡಿಮೆ ವಯಸ್ಸಿನ ಅಪ್ರಾಪ್ತರ ಡೇಟಾವನ್ನು ಸೂಚಿಸುತ್ತದೆ; DPDP ಸೆಕ್ಷನ್ 9 ರ ಅಡಿಯಲ್ಲಿ ಪೋಷಕರ ಒಪ್ಪಿಗೆ ಅಗತ್ಯವಿದೆ.",
    },
    "BIOMETRIC_GENETIC": {
        "en": "Column '{col}' references biometric or genetic identifiers ({ident}) requiring critical safeguards.",
        "hi": "कॉलम '{col}' में बायोमेट्रिक या जेनेटिक पहचान ({ident}) का संदर्भ है जिसके लिए उच्च सुरक्षा आवश्यक है।",
        "kn": "'{col}' ಕಾಲಮ್ ಬಯೋಮೆಟ್ರಿಕ್ ಅಥವಾ ಜೆನೆಟಿಕ್ ಗುರುತನ್ನು ({ident}) ಹೊಂದಿದ್ದು ಕಟ್ಟುನಿಟ್ಟಿನ ಸುರಕ್ಷತೆ ಅಗತ್ಯವಿದೆ.",
    },
    "AUTHENTICATION_SECRET": {
        "en": "Column '{col}' stores authentication secrets or credentials ({ident}) and must never be exposed.",
        "hi": "कॉलम '{col}' में प्रमाणीकरण गोपनीय जानकारी ({ident}) है और इसे कभी भी उजागर नहीं किया जाना चाहिए।",
        "kn": "'{col}' ಕಾಲಮ್ ದೃಢೀಕರಣ ರಹಸ್ಯಗಳನ್ನು ({ident}) ಹೊಂದಿದ್ದು, ಇದನ್ನು ಎಂದಿಗೂ ಬಹಿರಂಗಪಡಿಸಬಾರದು.",
    },
    "BEHAVIORAL_LOCATION": {
        "en": "Column '{col}' tracks behavioral, device, or location data ({ident}).",
        "hi": "कॉलम '{col}' व्यवहार, डिवाइस या स्थान डेटा ({ident}) को ट्रैक करता है।",
        "kn": "'{col}' ಕಾಲಮ್ ಸಾಧನ ಅಥವಾ ಸ್ಥಳ ಸಂಬಂಧಿತ ಮಾಹಿತಿಯನ್ನು ({ident}) ಹೊಂದಿದೆ.",
    },
    "BUSINESS_NON_PERSONAL": {
        "en": "Column '{col}' contains business or system metadata ({ident}) rather than individual personal data.",
        "hi": "कॉलम '{col}' में व्यक्तिगत डेटा के बजाय व्यावसायिक या सिस्टम डेटा ({ident}) है।",
        "kn": "'{col}' ಕಾಲಮ್ ವೈಯಕ್ತಿಕ ಡೇಟಾದ ಬದಲಿಗೆ ವ್ಯವಹಾರ ಅಥವಾ ಸಿಸ್ಟಮ್ ಮಾಹಿತಿಯನ್ನು ({ident}) ಹೊಂದಿದೆ.",
    },
    "UNKNOWN_AMBIGUOUS": {
        "en": "Column '{col}' has ambiguous signals and requires manual human review to confirm personal data status.",
        "hi": "कॉलम '{col}' के संकेत अस्पष्ट हैं और व्यक्तिगत डेटा की पुष्टि के लिए मानवीय समीक्षा आवश्यक है।",
        "kn": "'{col}' ಕಾಲಮ್ ಅಸ್ಪಷ್ಟವಾಗಿದೆ ಮತ್ತು ವೈಯಕ್ತಿಕ ಡೇಟಾವನ್ನು ಖಚಿತಪಡಿಸಲು ಮಾನವ ಪರಿಶೀಲನೆ ಅಗತ್ಯವಿದೆ.",
    },
}

FINDING_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "OVER_COLLECTION": {
        "explanation": {
            "en": "Collecting {cols} for '{purpose}' exceeds what is necessary for the stated business purpose.",
            "hi": "'{purpose}' के उद्देश्य के लिए {cols} एकत्र करना आवश्यक व्यावसायिक उद्देश्य से अधिक है।",
            "kn": "'{purpose}' ಉದ್ದೇಶಕ್ಕಾಗಿ {cols} ಸಂಗ್ರಹಿಸುವುದು ಅಗತ್ಯಕ್ಕಿಂತ ಹೆಚ್ಚಿನ ವೈಯಕ್ತಿಕ ಮಾಹಿತಿಯಾಗಿದೆ.",
        },
        "remediation": {
            "en": "Remove {cols} from collection forms and datasets unless strictly required by law.",
            "hi": "जब तक कानून द्वारा अनिवार्य न हो, {cols} को डेटासेट और फॉर्म से हटा दें।",
            "kn": "ಕಾನೂನಿನ ಪ್ರಕಾರ ಕಡ್ಡಾಯವಲ್ಲದಿದ್ದರೆ {cols} ಕಾಲಮ್‌ಗಳನ್ನು ಡೇಟಾಸೆಟ್‌ನಿಂದ ತೆಗೆದುಹಾಕಿ.",
        },
    },
    "MISSING_CONSENT_BASIS": {
        "explanation": {
            "en": "Personal data in {cols} is processed without a linked DPDP consent notice.",
            "hi": "{cols} में व्यक्तिगत डेटा को बिना किसी संबद्ध DPDP सहमति सूचना के संसाधित किया जा रहा है।",
            "kn": "{cols} ನಲ್ಲಿರುವ ವೈಯಕ್ತಿಕ ಡೇಟಾವನ್ನು DPDP ಒಪ್ಪಿಗೆ ನೋಟಿಸ್ ಇಲ್ಲದೆ ಸಂಸ್ಕರಿಸಲಾಗುತ್ತಿದೆ.",
        },
        "remediation": {
            "en": "Link a clear DPDP Section 5 & 6 privacy notice and record consent before processing.",
            "hi": "प्रोसेसिंग से पहले DPDP धारा 5 और 6 के अनुसार स्पष्ट गोपनीयता सूचना और सहमति जोड़ें।",
            "kn": "ಡೇಟಾ ಸಂಸ್ಕರಿಸುವ ಮೊದಲು DPDP ಸೆಕ್ಷನ್ 5 ಮತ್ತು 6 ರ ಪ್ರಕಾರ ಸ್ಪಷ್ಟ ಒಪ್ಪಿಗೆ ನೋಟಿಸ್ ಲಗತ್ತಿಸಿ.",
        },
    },
    "EXCESSIVE_ACCESS": {
        "explanation": {
            "en": "Sensitive or critical personal data ({cols}) is exposed to broad access scope ({scope}).",
            "hi": "संवेदनशील या महत्वपूर्ण व्यक्तिगत डेटा ({cols}) व्यापक एक्सेस ({scope}) के लिए खुला है।",
            "kn": "ಸೂಕ್ಷ್ಮ ಅಥವಾ ಪ್ರಮುಖ ವೈಯಕ್ತಿಕ ಡೇಟಾ ({cols}) ವ್ಯಾಪಕ ಪ್ರವೇಶಕ್ಕೆ ({scope}) ತೆರೆದಿದೆ.",
        },
        "remediation": {
            "en": "Restrict dataset access to authorised roles only and disable public or all-staff sharing.",
            "hi": "डेटासेट एक्सेस केवल अधिकृत भूमिकाओं तक सीमित करें और सार्वजनिक या सभी स्टाफ शेयरिंग बंद करें।",
            "kn": "ಡೇಟಾಸೆಟ್ ಪ್ರವೇಶವನ್ನು ಅಧಿಕೃತ ಸಿಬ್ಬಂದಿಗೆ ಮಾತ್ರ ಸೀಮಿತಗೊಳಿಸಿ ಮತ್ತು ಸಾರ್ವಜನಿಕ ಹಂಚಿಕೆಯನ್ನು ನಿಲ್ಲಿಸಿ.",
        },
    },
    "MISSING_RETENTION_POLICY": {
        "explanation": {
            "en": "Personal data ({cols}) is retained without a defined retention period.",
            "hi": "व्यक्तिगत डेटा ({cols}) बिना किसी निर्धारित डेटा प्रतिधारण (retention) अवधि के रखा गया है।",
            "kn": "ವೈಯಕ್ತಿಕ ಡೇಟಾವನ್ನು ({cols}) ಯಾವುದೇ ನಿಗದಿತ ಉಳಿಸಿಕೊಳ್ಳುವ ಅವಧಿಯಿಲ್ಲದೆ ಸಂಗ್ರಹಿಸಲಾಗಿದೆ.",
        },
        "remediation": {
            "en": "Configure a retention schedule in days and purge records once the purpose is fulfilled.",
            "hi": "दिनों में डेटा प्रतिधारण अवधि निर्धारित करें और उद्देश्य पूरा होने पर रिकॉर्ड हटा दें।",
            "kn": "ಡೇಟಾ ಉಳಿಸಿಕೊಳ್ಳುವ ಅವಧಿಯನ್ನು ನಿಗದಿಪಡಿಸಿ ಮತ್ತು ಉದ್ದೇಶ ಪೂರ್ಣಗೊಂಡ ನಂತರ ಡೇಟಾವನ್ನು ಅಳಿಸಿ.",
        },
    },
    "UNSAFE_COMBINATION": {
        "explanation": {
            "en": "High-risk identifiers and financial/health/secret attributes ({cols}) are stored together in a single dataset.",
            "hi": "उच्च-जोखिम पहचानकर्ता और वित्तीय/स्वास्थ्य/गोपनीय फ़ील्ड ({cols}) एक ही डेटासेट में एक साथ संग्रहीत हैं।",
            "kn": "ಅತಿ ಸೂಕ್ಷ್ಮ ಗುರುತಿನ ಸಂಖ್ಯೆಗಳು ಮತ್ತು ಆರ್ಥಿಕ/ಆರೋಗ್ಯ ಮಾಹಿತಿ ({cols}) ಒಂದೇ ಡೇಟಾಸೆಟ್‌ನಲ್ಲಿ ಒಟ್ಟಿಗೆ ಸಂಗ್ರಹಿಸಲಾಗಿದೆ.",
        },
        "remediation": {
            "en": "Separate or tokenize critical identifiers instead of storing them alongside profile/medical records.",
            "hi": "महत्वपूर्ण पहचानकर्ताओं को प्रोफ़ाइल या मेडिकल रिकॉर्ड के साथ रखने के बजाय अलग या टोकनाइज़ करें।",
            "kn": "ಪ್ರಮುಖ ಗುರುತಿನ ಸಂಖ್ಯೆಗಳನ್ನು ಪ್ರತ್ಯೇಕಿಸಿ ಅಥವಾ ಟೋಕನೈಸ್ ಮಾಡಿ.",
        },
    },
    "CHILDREN_DATA_SAFEGUARD_REQUIRED": {
        "explanation": {
            "en": "Dataset includes children's personal data ({cols}), which requires verifiable parental consent under DPDP Section 9.",
            "hi": "डेटासेट में बच्चों का व्यक्तिगत डेटा ({cols}) शामिल है, जिसके लिए DPDP धारा 9 के तहत माता-पिता की सत्यापन योग्य सहमति आवश्यक है।",
            "kn": "ಡೇಟಾಸೆಟ್ ಮಕ್ಕಳ ವೈಯಕ್ತಿಕ ಡೇಟಾವನ್ನು ({cols}) ಒಳಗೊಂಡಿದೆ; ಇದಕ್ಕೆ DPDP ಸೆಕ್ಷನ್ 9 ರ ಅಡಿಯಲ್ಲಿ ಪೋಷಕರ ದೃಢೀಕೃತ ಒಪ್ಪಿಗೆ ಅಗತ್ಯವಿದೆ.",
        },
        "remediation": {
            "en": "Verify parental consent workflow and prohibit behavioral tracking or targeted advertising for minors.",
            "hi": "माता-पिता की सहमति प्रक्रिया को सत्यापित करें और नाबालिगों की ट्रैकिंग या लक्षित विज्ञापन प्रतिबंधित करें।",
            "kn": "ಪೋಷಕರ ಒಪ್ಪಿಗೆ ಪ್ರಕ್ರಿಯೆಯನ್ನು ಪರಿಶೀಲಿಸಿ ಮತ್ತು ಮಕ್ಕಳ ಟ್ರ್ಯಾಕಿಂಗ್ ಅಥವಾ ಜಾಹೀರಾತುಗಳನ್ನು ನಿಷೇಧಿಸಿ.",
        },
    },
    "THIRD_PARTY_SHARING_RISK": {
        "explanation": {
            "en": "Dataset containing sensitive/critical fields ({cols}) is marked for third-party sharing.",
            "hi": "संवेदनशील/महत्वपूर्ण फ़ील्ड ({cols}) वाला डेटासेट तृतीय-पक्ष (third-party) साझाकरण के लिए चिह्नित है।",
            "kn": "ಸೂಕ್ಷ್ಮ ಮಾಹಿತಿಯನ್ನು ({cols}) ಹೊಂದಿರುವ ಡೇಟಾಸೆಟ್ ಅನ್ನು ಮೂರನೇ ವ್ಯಕ್ತಿಗಳೊಂದಿಗೆ ಹಂಚಿಕೊಳ್ಳಲಾಗುತ್ತಿದೆ.",
        },
        "remediation": {
            "en": "Ensure a valid Data Processing Agreement is in place and mask critical fields before sharing.",
            "hi": "डेटा प्रोसेसिंग समझौता सुनिश्चित करें और साझा करने से पहले महत्वपूर्ण फ़ील्ड को मास्क करें।",
            "kn": "ಡೇಟಾ ಸಂಸ್ಕರಣಾ ಒಪ್ಪಂದವನ್ನು ಖಚಿತಪಡಿಸಿಕೊಳ್ಳಿ ಮತ್ತು ಹಂಚಿಕೊಳ್ಳುವ ಮೊದಲು ಪ್ರಮುಖ ಮಾಹಿತಿಯನ್ನು ಮರೆಮಾಚಿ.",
        },
    },
    "VERSION_DRIFT_ESCALATION": {
        "explanation": {
            "en": "New high-sensitivity personal columns ({cols}) were introduced compared to the previous dataset version.",
            "hi": "पिछले डेटासेट संस्करण की तुलना में नए उच्च-संवेदनशील कॉलम ({cols}) जोड़े गए हैं।",
            "kn": "ಹಿಂದಿನ ಡೇಟಾಸೆಟ್ ಆವೃತ್ತಿಗೆ ಹೋಲಿಸಿದರೆ ಹೊಸ ಅತಿ ಸೂಕ್ಷ್ಮ ಕಾಲಮ್‌ಗಳನ್ನು ({cols}) ಸೇರಿಸಲಾಗಿದೆ.",
        },
        "remediation": {
            "en": "Review the schema change with the compliance lead and update the consent notice if needed.",
            "hi": "अनुपालन प्रमुख के साथ बदलाव की समीक्षा करें और आवश्यकतानुसार सहमति सूचना अपडेट करें।",
            "kn": "ಈ ಬದಲಾವಣೆಯನ್ನು ಅನುಪಾಲನಾ ತಂಡದೊಂದಿಗೆ ಪರಿಶೀಲಿಸಿ ಮತ್ತು ಒಪ್ಪಿಗೆ ನೋಟಿಸ್ ಅನ್ನು ನವೀಕರಿಸಿ.",
        },
    },
}

REQUEST_EXPLANATION_TEMPLATES: dict[str, str] = {
    "en": "Detected DPDP rights request ({req_type}) covering [{sub_types}]. Human verification and approval are required before taking action.",
    "hi": "DPDP अधिकार अनुरोध ({req_type}) पहचाना गया जिसमें [{sub_types}] शामिल हैं। कोई भी कार्रवाई करने से पहले मानवीय सत्यापन और स्वीकृति आवश्यक है।",
    "kn": "DPDP ಹಕ್ಕುಗಳ ವಿನಂತಿಯನ್ನು ({req_type}: [{sub_types}]) ಗುರುತಿಸಲಾಗಿದೆ. ಯಾವುದೇ ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ಮಾನವ ಪರಿಶೀಲನೆ ಮತ್ತು ಅನುಮೋದನೆ ಅಗತ್ಯವಿದೆ.",
}

REQUEST_DRAFT_TEMPLATES: dict[str, str] = {
    "en": (
        "Dear Data Principal, thank you for contacting our Privacy Desk (Case #{case_id}). "
        "To protect your personal data, please complete identity verification via your registered contact. "
        "Once verified, our team will review and process your {req_type} request in accordance with the DPDP Act, 2023."
    ),
    "hi": (
        "प्रिय डेटा प्रिंसिपल, हमारे गोपनीयता डेस्क (केस #{case_id}) से संपर्क करने के लिए धन्यवाद। "
        "आपके व्यक्तिगत डेटा की सुरक्षा के लिए, कृपया अपने पंजीकृत संपर्क के माध्यम से पहचान सत्यापन पूरा करें। "
        "सत्यापन के बाद, हमारी टीम DPDP अधिनियम, 2023 के अनुसार आपके {req_type} अनुरोध पर कार्रवाई करेगी।"
    ),
    "kn": (
        "ಆತ್ಮೀಯ ಗ್ರಾಹಕರೇ, ನಮ್ಮ ಗೌಪ್ಯತಾ ಕೇಂದ್ರವನ್ನು (ಪ್ರಕರಣ #{case_id}) ಸಂಪರ್ಕಿಸಿದ್ದಕ್ಕಾಗಿ ಧನ್ಯವಾದಗಳು. "
        "ನಿಮ್ಮ ವೈಯಕ್ತಿಕ ಮಾಹಿತಿಯ ಸುರಕ್ಷತೆಗಾಗಿ, ದಯವಿಟ್ಟು ನಿಮ್ಮ ನೋಂದಾಯಿತ ಸಂಪರ್ಕದ ಮೂಲಕ ಗುರುತಿನ ದೃಢೀಕರಣವನ್ನು ಪೂರ್ಣಗೊಳಿಸಿ. "
        "ದೃಢೀಕರಣದ ನಂತರ, DPDP ಕಾಯ್ದೆ 2023 ರ ಪ್ರಕಾರ ನಿಮ್ಮ {req_type} ವಿನಂತಿಯನ್ನು ನಮ್ಮ ತಂಡವು ಪರಿಶೀಲಿಸುತ್ತದೆ."
    ),
}

BREACH_EXPLANATION_TEMPLATES: dict[str, str] = {
    "en": (
        "Incident classified as {breach_type} with {severity} severity affecting {categories}. "
        "Under DPDP Act Section 8(6), human/legal review is required before notifying the Data Protection Board and affected individuals."
    ),
    "hi": (
        "इस घटना को {severity} गंभीरता के साथ {breach_type} के रूप में वर्गीकृत किया गया है जो {categories} को प्रभावित करती है। "
        "DPDP अधिनियम की धारा 8(6) के तहत, डेटा प्रोटेक्शन बोर्ड और प्रभावित व्यक्तियों को सूचित करने से पहले मानवीय/कानूनी समीक्षा आवश्यक है।"
    ),
    "kn": (
        "ಈ ಘಟನೆಯನ್ನು {severity} ತೀವ್ರತೆಯೊಂದಿಗೆ {breach_type} ಎಂದು ವರ್ಗೀಕರಿಸಲಾಗಿದೆ ಮತ್ತು ಇದು {categories} ಮೇಲೆ ಪರಿಣಾಮ ಬೀರುತ್ತದೆ. "
        "DPDP ಕಾಯ್ದೆ ಸೆಕ್ಷನ್ 8(6) ರ ಅಡಿಯಲ್ಲಿ ಡೇಟಾ ರಕ್ಷಣಾ ಮಂಡಳಿ ಮತ್ತು ಪೀಡಿತ ವ್ಯಕ್ತಿಗಳಿಗೆ ತಿಳಿಸುವ ಮೊದಲು ಮಾನವ/ಕಾನೂನು ಪರಿಶೀಲನೆ ಕಡ್ಡಾಯವಾಗಿದೆ."
    ),
}


def matches_requested_language(text: str, language: str) -> bool:
    """Return True if text is non-empty and contains expected script characters for hi/kn."""
    if not text or not text.strip():
        return False
    lang = language.lower().strip()
    if lang == "hi":
        return bool(_DEVANAGARI_RE.search(text))
    if lang == "kn":
        return bool(_KANNADA_RE.search(text))
    return True


def format_column_explanation(
    column_name: str,
    data_category: str,
    specific_identifier_type: str,
    sensitivity_tier: str,
    language: str = "en",
) -> str:
    """Return a localized explanation for a classified column."""
    lang = language if language in {"en", "hi", "kn"} else "en"
    cat_map = COLUMN_CATEGORY_TEMPLATES.get(
        data_category, COLUMN_CATEGORY_TEMPLATES["UNKNOWN_AMBIGUOUS"]
    )
    template = cat_map.get(lang, cat_map["en"])
    return template.format(
        col=column_name,
        ident=specific_identifier_type,
        tier=sensitivity_tier,
    )


def format_finding_texts(
    finding_type: str,
    affected_columns: list[str],
    business_purpose: str,
    access_scope: str,
    language: str = "en",
) -> tuple[str, str]:
    """Return localized (explanation, recommended_remediation) for a privacy finding."""
    lang = language if language in {"en", "hi", "kn"} else "en"
    entry = FINDING_TEMPLATES.get(finding_type, FINDING_TEMPLATES["OVER_COLLECTION"])
    cols_str = ", ".join(f"'{c}'" for c in affected_columns) if affected_columns else "columns"
    explanation = entry["explanation"].get(lang, entry["explanation"]["en"]).format(
        cols=cols_str,
        purpose=business_purpose,
        scope=access_scope,
    )
    remediation = entry["remediation"].get(lang, entry["remediation"]["en"]).format(
        cols=cols_str,
        purpose=business_purpose,
        scope=access_scope,
    )
    return explanation, remediation


def format_request_texts(
    case_id: str,
    primary_request_type: str,
    detected_sub_types: list[str],
    language: str = "en",
) -> tuple[str, str]:
    """Return localized (explanation, draft_response_for_staff_review)."""
    lang = language if language in {"en", "hi", "kn"} else "en"
    sub_str = ", ".join(detected_sub_types) if detected_sub_types else primary_request_type
    explanation = REQUEST_EXPLANATION_TEMPLATES.get(
        lang, REQUEST_EXPLANATION_TEMPLATES["en"]
    ).format(req_type=primary_request_type, sub_types=sub_str)
    draft = REQUEST_DRAFT_TEMPLATES.get(lang, REQUEST_DRAFT_TEMPLATES["en"]).format(
        case_id=case_id, req_type=primary_request_type
    )
    return explanation, draft


def format_breach_explanation(
    breach_type: str,
    severity: str,
    affected_categories: list[str],
    language: str = "en",
) -> str:
    """Return a localized explanation for a breach assessment."""
    lang = language if language in {"en", "hi", "kn"} else "en"
    cats = ", ".join(affected_categories) if affected_categories else "personal data"
    return BREACH_EXPLANATION_TEMPLATES.get(
        lang, BREACH_EXPLANATION_TEMPLATES["en"]
    ).format(breach_type=breach_type, severity=severity, categories=cats)
