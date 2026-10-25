"""
scripts/generate_locales.py
===========================
Generates locales/en.json, locales/hi.json, locales/kn.json and locales/review_status.json.
Validates 1:1 key parity and placeholder symmetry.
"""

import json
import os
import re
from pathlib import Path

LOCALES_DIR = Path("locales")
LOCALES_DIR.mkdir(parents=True, exist_ok=True)

EN: dict[str, str] = {
    # -------------------------------------------------------------
    # Flags / Rules (whats_right, whats_not, how_to_fix, title)
    # -------------------------------------------------------------
    "flags.health_data_safeguards.title": "Health data security safeguards",
    "flags.health_data_safeguards.whats_right": "No issue found by Kavach's checks: Health data is mapped to confirmed medical care purposes with safeguards.",
    "flags.health_data_safeguards.whats_not": "Health and diagnostic records detected without confirmed legal purpose or verified safeguards.",
    "flags.health_data_safeguards.how_to_fix": "Deploy robust encryption at rest and in transit, restrict access to authorized clinicians, and confirm the medical care purpose.",

    "flags.aadhaar_in_chat.title": "Aadhaar present in WhatsApp/chat or free text",
    "flags.aadhaar_in_chat.whats_right": "No issue found by Kavach's checks: Chat channels verified free of unmasked Aadhaar numbers.",
    "flags.aadhaar_in_chat.whats_not": "Unmasked Aadhaar numbers detected in exported WhatsApp chat conversations or unstructured notes.",
    "flags.aadhaar_in_chat.how_to_fix": "Immediately purge or redact unmasked Aadhaar numbers from chat channels and mandate masking in communications.",

    "flags.aadhaar_multiple_files.title": "Aadhaar stored in more than one file",
    "flags.aadhaar_multiple_files.whats_right": "No issue found by Kavach's checks: Aadhaar data is consolidated in a single restricted file.",
    "flags.aadhaar_multiple_files.whats_not": "Aadhaar numbers are duplicated across multiple disparate spreadsheets or forms.",
    "flags.aadhaar_multiple_files.how_to_fix": "Consolidate Aadhaar records into one designated repository and execute an erasure plan for redundant files.",

    "flags.unrestricted_shared_source.title": "Personal data in an unrestricted shared source",
    "flags.unrestricted_shared_source.whats_right": "Owner reports no shared folders (not verified by Kavach).",
    "flags.unrestricted_shared_source.whats_not": "Customer or patient data is accessible via unmanaged shared personal devices or personal drives.",
    "flags.unrestricted_shared_source.how_to_fix": "Migrate all customer spreadsheets to password-protected enterprise cloud storage with access logging.",

    "flags.minors_parental_consent.title": "Possible minors present, parental consent needed",
    "flags.minors_parental_consent.whats_right": "Owner reports no unconsented processing of children's personal data (not verified by Kavach).",
    "flags.minors_parental_consent.whats_not": "Records of individuals under 18 years of age processed without verifiable parental or guardian consent.",
    "flags.minors_parental_consent.how_to_fix": "Implement verifiable parental consent verification prior to processing personal data of children.",

    "flags.employee_data_lawful_basis.title": "Employee data processing lawful basis",
    "flags.employee_data_lawful_basis.whats_right": "No issue found by Kavach's checks: Employee records mapped to recognized employment lawful basis.",
    "flags.employee_data_lawful_basis.whats_not": "Staff records lack confirmed employment purpose documentation or privacy notice.",
    "flags.employee_data_lawful_basis.how_to_fix": "Document employment purpose for staff records under Section 7(i) and issue staff privacy notices.",

    "flags.notice_at_collection.title": "No notice at collection points",
    "flags.notice_at_collection.whats_right": "Owner reports a notice is shown (not verified by Kavach).",
    "flags.notice_at_collection.whats_not": "CCTV or intake collection points operate without visible, plain-language privacy notices.",
    "flags.notice_at_collection.how_to_fix": "Place prominent signage near CCTV cameras and add collection notices on registration forms.",

    "flags.breach_contact_process.title": "No breach contact/process",
    "flags.breach_contact_process.whats_right": "Owner reports a designated breach contact person and notification procedure are established (not verified by Kavach).",
    "flags.breach_contact_process.whats_not": "No designated contact person or incident process to intimate the Board and affected people without delay.",
    "flags.breach_contact_process.how_to_fix": "Designate a privacy/breach officer, document notification workflows, and review the breach checklist.",

    "flags.retention_policy.title": "No retention policy",
    "flags.retention_policy.whats_right": "Owner reports a written data retention and scheduled disposal policy is documented (not verified by Kavach).",
    "flags.retention_policy.whats_not": "No written policy exists to periodically erase personal data once legal and business purposes expire.",
    "flags.retention_policy.how_to_fix": "Adopt a data retention schedule and implement regular erasure cycles for expired records.",

    "flags.data_on_personal_phones.title": "Data on personal phones",
    "flags.data_on_personal_phones.whats_right": "Owner reports staff are prohibited from holding customer records on personal phones (not verified by Kavach).",
    "flags.data_on_personal_phones.whats_not": "Staff, doctors, or contractors retain unencrypted customer files or chat backups on personal devices.",
    "flags.data_on_personal_phones.how_to_fix": "Enforce a formal mobile device policy requiring enterprise accounts and prohibiting local storage on personal phones.",

    "flags.vendors_unwritten_agreement.title": "Vendors/processors without written agreement",
    "flags.vendors_unwritten_agreement.whats_right": "Owner reports written Data Processing Agreements are executed with all processors (not verified by Kavach).",
    "flags.vendors_unwritten_agreement.whats_not": "Personal data shared with third-party labs, IT software, or contractors without binding written DPAs.",
    "flags.vendors_unwritten_agreement.how_to_fix": "Execute written Data Processing Agreements defining processing duties with every external vendor.",

    "flags.data_sprawl_files.title": "Same person data in many files (data sprawl)",
    "flags.data_sprawl_files.whats_right": "No issue found by Kavach's checks: Entity profiles consolidated with no excessive file sprawl.",
    "flags.data_sprawl_files.whats_not": "Individual data subjects are fragmented across three or more separate spreadsheets or systems.",
    "flags.data_sprawl_files.how_to_fix": "Unify duplicate customer records and archive obsolete copies using an erasure plan.",

    "flags.unknown_purposes.title": "Unconfirmed processing purposes for data columns",
    "flags.unknown_purposes.whats_right": "No issue found by Kavach's checks: All detected identifier columns have confirmed processing purposes.",
    "flags.unknown_purposes.whats_not": "One or more personal data columns lack a confirmed processing purpose.",
    "flags.unknown_purposes.how_to_fix": "Review the question queue and confirm the legitimate business purpose for each column.",

    "flags.no_named_contact.title": "No designated breach response point of contact",
    "flags.no_named_contact.whats_right": "Owner reports designated breach notification officer established (not verified by Kavach).",
    "flags.no_named_contact.whats_not": "Organization has not appointed a named contact person responsible for breach intimation.",
    "flags.no_named_contact.how_to_fix": "Designate a named contact person and implement the breach response checklist.",

    # -------------------------------------------------------------
    # Questionnaire Questions
    # -------------------------------------------------------------
    "questions.cctv.title": "CCTV surveillance on premises",
    "questions.cctv.question": "Do you operate CCTV cameras in patient, customer, or office premises? Requires visible collection notice (s.5).",

    "questions.personal_phones.title": "Staff personal mobile devices",
    "questions.personal_phones.question": "Do staff, contractors, or doctors store patient or customer records on personal phones? (s.8(5)).",

    "questions.vendors.title": "Vendors without written agreements",
    "questions.vendors.question": "Do you share personal data with external labs, software providers, or accountants without written DPAs? (s.8(2)).",

    "questions.breach_contact.title": "Designated breach point of contact",
    "questions.breach_contact.question": "Have you established a breach notification procedure and published a designated point of contact? (s.8(6)).",

    "questions.retention_policy.title": "Documented data retention policy",
    "questions.retention_policy.question": "Do you have a written schedule to periodically delete personal data once purpose has expired? (s.8(7)).",

    "questions.children_served.title": "Direct processing of minors' data",
    "questions.children_served.question": "Do you knowingly serve or retain data of children under 18 requiring verifiable parental consent? (s.9).",

    "questions.shared_folder.title": "Customer files in shared or open folder",
    "questions.shared_folder.question": "Do you keep customer or patient files in a shared or open folder, such as a shared drive or a group chat anyone can open?",

    "questions.collection_notice.title": "Notice at collection touchpoints",
    "questions.collection_notice.question": "Do you tell people why you collect their details, for example a sign at the desk or a line on your registration form?",

    # -------------------------------------------------------------
    # Purpose Labels
    # -------------------------------------------------------------
    "purposes.appointment_booking.label": "Appointment booking",
    "purposes.billing_payment.label": "Billing and payment",
    "purposes.tax_records.label": "Tax and accounting records",
    "purposes.medical_care.label": "Medical care and diagnostics",
    "purposes.employment_payroll.label": "Employment and payroll",
    "purposes.marketing_offers.label": "Marketing and promotional offers",
    "purposes.legal_obligation.label": "Legal and compliance obligation",
    "purposes.security_fraud.label": "Security and fraud prevention",
    "purposes.other.label": "Other business purpose",

    # -------------------------------------------------------------
    # Checklist Items (6 core stages)
    # -------------------------------------------------------------
    "checklist.contain.title": "Contain the Incident",
    "checklist.contain.task": "Isolate affected machines and disconnect from network. Do not power down unthinkingly (ask your IT adviser). Revoke compromised user credentials, active tokens, and admin sessions.",

    "checklist.preserve_evidence.title": "Preserve Evidence",
    "checklist.preserve_evidence.task": "Do not wipe or reformat affected machines. Photograph ransom note or error screen if ransomware. Export and archive system access logs, firewalls, and audit trails. Record exact timestamps of discovery and containment.",

    "checklist.assess.title": "Assess Blast Radius & Obligations",
    "checklist.assess.task": "Assess blast radius: estimate affected data categories, number of data principals, and minor records involved. Check other-law reporting duties (to verify) (e.g. CERT-In reporting obligations, sectoral guidelines).",

    "checklist.notify.title": "Statutory & Principal Notifications",
    "checklist.notify.task": "Submit Stage 1 preliminary intimation to the Data Protection Board of India without delay. Intimate affected data principals without delay with clear protective advice. Prepare Stage 2 detailed report within 72 hours (or submit written extension request).",

    "checklist.recover.title": "Business Recovery",
    "checklist.recover.task": "Address core business recovery questions: 1) How long can the business run without the system? 2) How much data can it lose? Restore systems from clean, isolated offline backups (ask your IT adviser).",

    "checklist.review.title": "Post-Incident Review",
    "checklist.review.task": "Conduct thorough post-incident review. Document findings, patch identified vulnerabilities, update access control policies, and provide refresher privacy safeguards training.",

    # -------------------------------------------------------------
    # Notices & Disclaimers
    # -------------------------------------------------------------
    "notices.not_legal_advice": "This readiness report is generated by Kavach as a technical self-assessment tool and does not constitute formal legal advice. Consult qualified legal counsel for DPDP Act 2023 compliance.",
    "notices.citations_to_verify": "All legal citations and rule interpretations marked (to verify) are draft guidance based on DPDP Act 2023 and DPDP Rules 2025 and require human legal verification before reliance.",
    "notices.readiness_aid_title": "Readiness Aid Notice",
    "notices.readiness_aid_body": "This audit report is an automated readiness tool and technical compliance summary. Citations unverified. Consult legal counsel for formal compliance.",
    "notices.footer": "Readiness aid, not legal advice. Citations unverified.",
    "notices.green_wording": "No issue found by Kavach's checks",
    "notices.machine_translated": "machine-translated, not yet reviewed",
    "notices.clause_a_title": "Clause (a) What Happened",
    "notices.clause_b_title": "Clause (b) Likely Consequences",
    "notices.clause_c_title": "Clause (c) Mitigation Measures",
    "notices.clause_d_title": "Clause (d) Safety Steps You Can Take",
    "notices.clause_e_title": "Clause (e) Business Contact",
    "notices.notice_header": "Notice of Data Security Incident to Data Principal",
    "notices.draft_watermark": "DRAFT SIMULATION - DPDP Act Readiness (May 2027)",
    "notices.retention_warning": "Data retention window expiring soon. Please export your compliance evidence pack before business data is purged.",

    # -------------------------------------------------------------
    # Report Headings
    # -------------------------------------------------------------
    "reports.headings.title": "Kavach Compliance Readiness Report",
    "reports.headings.subtitle": "Digital Personal Data Protection Act (DPDP Act) Technical Audit Snapshot",
    "reports.headings.actions": "Prioritised Recommended Actions (Max 8)",
    "reports.headings.purpose_coverage": "Purpose Specification Coverage",
    "reports.headings.rule_assessments": "Compliance Rule Assessments",
    "reports.headings.rights_cases": "Data Principal Rights Cases",
    "reports.headings.erasure_receipts": "Erasure Compliance Receipts",
    "reports.headings.breach_simulations": "Breach Simulations (Marked SIMULATION)",
    "reports.headings.audit_ledger": "Cryptographic Audit Ledger",
    "reports.headings.limitations": "Scope & Limitations",

    # -------------------------------------------------------------
    # Actions (with {count} placeholder)
    # -------------------------------------------------------------
    "actions.unknown_purposes.title": "Unconfirmed processing purposes for personal data columns",
    "actions.unknown_purposes.reason": "{count} personal data column(s) lack a confirmed processing purpose under DPDP Act.",
    "actions.unknown_purposes.how_to_fix": "Review unconfirmed data columns and link each to a legitimate business purpose.",
    "actions.general.items_count": "Assessed {count} operational compliance items across active datasets.",
}

HI: dict[str, str] = {
    # -------------------------------------------------------------
    # Flags / Rules (whats_right, whats_not, how_to_fix, title)
    # -------------------------------------------------------------
    "flags.health_data_safeguards.title": "स्वास्थ्य डेटा सुरक्षा उपाय",
    "flags.health_data_safeguards.whats_right": "No issue found by Kavach's checks: स्वास्थ्य डेटा को उचित सुरक्षा उपायों के साथ पुष्ट चिकित्सा देखभाल उद्देश्यों से जोड़ा गया है।",
    "flags.health_data_safeguards.whats_not": "पुष्ट कानूनी उद्देश्य या सत्यापित सुरक्षा उपायों के बिना स्वास्थ्य और नैदानिक रिकॉर्ड मिले।",
    "flags.health_data_safeguards.how_to_fix": "स्टोरेज और ट्रांसमिशन में मजबूत एन्क्रिप्शन लागू करें, अधिकृत डॉक्टरों तक पहुंच सीमित करें, और चिकित्सा उद्देश्य की पुष्टि करें।",

    "flags.aadhaar_in_chat.title": "व्हाट्सएप/चैट या खुले टेक्स्ट में आधार उपस्थित",
    "flags.aadhaar_in_chat.whats_right": "No issue found by Kavach's checks: चैट माध्यमों में बिना मास्क किए आधार नंबर नहीं पाए गए।",
    "flags.aadhaar_in_chat.whats_not": "व्हाट्सएप चैट एक्सपोर्ट या असंरचित नोट्स में खुले आधार नंबर पाए गए।",
    "flags.aadhaar_in_chat.how_to_fix": "चैट से खुले आधार नंबर तुरंत हटाएं या मास्क करें और संचार में मास्किंग अनिवार्य करें।",

    "flags.aadhaar_multiple_files.title": "आधार एक से अधिक फाइलों में संग्रहीत",
    "flags.aadhaar_multiple_files.whats_right": "No issue found by Kavach's checks: आधार डेटा एक ही सुरक्षित फाइल में समेकित है।",
    "flags.aadhaar_multiple_files.whats_not": "आधार नंबर कई अलग-अलग स्प्रेडशीट या फॉर्मों में बिखरे हुए हैं।",
    "flags.aadhaar_multiple_files.how_to_fix": "आधार रिकॉर्ड को एक निर्दिष्ट भंडार में समेकित करें और अतिरिक्त प्रतियों के लिए विलोपन योजना चलाएं।",

    "flags.unrestricted_shared_source.title": "अप्रतिबंधित साझा स्रोत में व्यक्तिगत डेटा",
    "flags.unrestricted_shared_source.whats_right": "Owner reports no shared folders (not verified by Kavach).",
    "flags.unrestricted_shared_source.whats_not": "ग्राहक या मरीज का डेटा असुरक्षित साझा व्यक्तिगत उपकरणों या ड्राइव पर उपलब्ध है।",
    "flags.unrestricted_shared_source.how_to_fix": "सभी ग्राहक स्प्रेडशीट को पासवर्ड-संरक्षित उद्यम क्लाउड स्टोरेज में स्थानांतरित करें।",

    "flags.minors_parental_consent.title": "नाबालिगों का डेटा, माता-पिता की सहमति आवश्यक",
    "flags.minors_parental_consent.whats_right": "Owner reports no unconsented processing of children's personal data (not verified by Kavach).",
    "flags.minors_parental_consent.whats_not": "18 वर्ष से कम उम्र के बच्चों का डेटा सत्यापन योग्य अभिभावक सहमति के बिना संसाधित किया जा रहा है।",
    "flags.minors_parental_consent.how_to_fix": "बच्चों के व्यक्तिगत डेटा को प्रोसेस करने से पहले सत्यापन योग्य माता-पिता की सहमति लागू करें।",

    "flags.employee_data_lawful_basis.title": "कर्मचारी डेटा प्रोसेसिंग का वैध आधार",
    "flags.employee_data_lawful_basis.whats_right": "No issue found by Kavach's checks: कर्मचारी रिकॉर्ड मान्यता प्राप्त रोजगार वैध आधार से जुड़े हैं।",
    "flags.employee_data_lawful_basis.whats_not": "स्टाफ रिकॉर्ड में रोजगार उद्देश्य दस्तावेज या गोपनीयता नोटिस की कमी है।",
    "flags.employee_data_lawful_basis.how_to_fix": "धारा 7(i) के तहत स्टाफ रिकॉर्ड के लिए रोजगार उद्देश्य दर्ज करें और स्टाफ गोपनीयता नोटिस जारी करें।",

    "flags.notice_at_collection.title": "संग्रह बिंदुओं पर नोटिस अनुपस्थित",
    "flags.notice_at_collection.whats_right": "Owner reports a notice is shown (not verified by Kavach).",
    "flags.notice_at_collection.whats_not": "सीसीटीवी या पंजीकरण बिंदुओं पर दृश्यमान, सरल भाषा में गोपनीयता नोटिस नहीं है।",
    "flags.notice_at_collection.how_to_fix": "सीसीटीवी कैमरों के पास प्रमुख बोर्ड लगाएं और पंजीकरण फॉर्मों पर संग्रह नोटिस जोड़ें।",

    "flags.breach_contact_process.title": "डेटा उल्लंघन संपर्क/प्रक्रिया अनुपस्थित",
    "flags.breach_contact_process.whats_right": "Owner reports a designated breach contact person and notification procedure are established (not verified by Kavach).",
    "flags.breach_contact_process.whats_not": "बोर्ड और प्रभावित व्यक्तियों को बिना देरी सूचित करने के लिए कोई नामित अधिकारी या प्रक्रिया नहीं है।",
    "flags.breach_contact_process.how_to_fix": "एक गोपनीयता/उल्लंघन अधिकारी नामित करें, सूचना कार्यप्रवाह बनाएं, और चेकलिस्ट की समीक्षा करें।",

    "flags.retention_policy.title": "डेटा प्रतिधारण नीति का अभाव",
    "flags.retention_policy.whats_right": "Owner reports a written data retention and scheduled disposal policy is documented (not verified by Kavach).",
    "flags.retention_policy.whats_not": "उद्देश्य पूरा होने के बाद व्यक्तिगत डेटा को समय-समय पर हटाने की कोई लिखित नीति नहीं है।",
    "flags.retention_policy.how_to_fix": "डेटा प्रतिधारण समय-सारणी अपनाएं और समाप्त रिकॉर्ड के लिए नियमित विलोपन चक्र लागू करें।",

    "flags.data_on_personal_phones.title": "व्यक्तिगत फोन पर डेटा",
    "flags.data_on_personal_phones.whats_right": "Owner reports staff are prohibited from holding customer records on personal phones (not verified by Kavach).",
    "flags.data_on_personal_phones.whats_not": "कर्मचारी या डॉक्टर व्यक्तिगत उपकरणों पर अनएन्क्रिप्टेड ग्राहक फाइलें रखते हैं।",
    "flags.data_on_personal_phones.how_to_fix": "एक औपचारिक मोबाइल डिवाइस नीति लागू करें जो व्यक्तिगत फोन पर स्थानीय भंडारण को प्रतिबंधित करे।",

    "flags.vendors_unwritten_agreement.title": "लिखित अनुबंध के बिना वेंडर/प्रोसेसर",
    "flags.vendors_unwritten_agreement.whats_right": "Owner reports written Data Processing Agreements are executed with all processors (not verified by Kavach).",
    "flags.vendors_unwritten_agreement.whats_not": "तीसरे पक्ष के लैब, सॉफ्टवेयर या ठेकेदारों के साथ बिना बाध्यकारी लिखित DPA के डेटा साझा किया गया है।",
    "flags.vendors_unwritten_agreement.how_to_fix": "प्रत्येक बाहरी विक्रेता के साथ प्रसंस्करण कर्तव्यों को परिभाषित करने वाला लिखित अनुबंध करें।",

    "flags.data_sprawl_files.title": "एक ही व्यक्ति का डेटा कई फाइलों में बिखरा (डेटा फैलाव)",
    "flags.data_sprawl_files.whats_right": "No issue found by Kavach's checks: डेटा प्रोफाइल बिना अत्यधिक फैलाव के समेकित हैं।",
    "flags.data_sprawl_files.whats_not": "व्यक्तिगत डेटा तीन या अधिक अलग-अलग स्प्रेडशीट या प्रणालियों में बिखरा हुआ है।",
    "flags.data_sprawl_files.how_to_fix": "डुप्लिकेट रिकॉर्ड को एकीकृत करें और विलोपन योजना का उपयोग करके अप्रचलित प्रतियों को हटाएं।",

    "flags.unknown_purposes.title": "डेटा कॉलम के लिए अपुष्ट प्रसंस्करण उद्देश्य",
    "flags.unknown_purposes.whats_right": "No issue found by Kavach's checks: सभी पहचाने गए पहचानकर्ता कॉलम में पुष्ट प्रसंस्करण उद्देश्य हैं।",
    "flags.unknown_purposes.whats_not": "एक या अधिक व्यक्तिगत डेटा कॉलम में पुष्ट प्रसंस्करण उद्देश्य का अभाव है।",
    "flags.unknown_purposes.how_to_fix": "प्रश्न कतार की समीक्षा करें और प्रत्येक कॉलम के लिए वैध व्यावसायिक उद्देश्य की पुष्टि करें।",

    "flags.no_named_contact.title": "कोई नामित उल्लंघन प्रतिक्रिया संपर्क व्यक्ति नहीं",
    "flags.no_named_contact.whats_right": "Owner reports designated breach notification officer established (not verified by Kavach).",
    "flags.no_named_contact.whats_not": "संस्था ने उल्लंघन सूचना के लिए जिम्मेदार कोई नामित संपर्क व्यक्ति नियुक्त नहीं किया है।",
    "flags.no_named_contact.how_to_fix": "एक नामित संपर्क व्यक्ति तय करें और उल्लंघन प्रतिक्रिया चेकलिस्ट लागू करें।",

    # -------------------------------------------------------------
    # Questionnaire Questions
    # -------------------------------------------------------------
    "questions.cctv.title": "परिसर में सीसीटीवी निगरानी",
    "questions.cctv.question": "क्या आप मरीज, ग्राहक या कार्यालय परिसर में सीसीटीवी कैमरे संचालित करते हैं? (धारा 5 के तहत दृश्यमान नोटिस आवश्यक)।",

    "questions.personal_phones.title": "कर्मचारियों के व्यक्तिगत मोबाइल उपकरण",
    "questions.personal_phones.question": "क्या कर्मचारी या डॉक्टर व्यक्तिगत फोन पर मरीज या ग्राहक रिकॉर्ड रखते हैं? (धारा 8(5))।",

    "questions.vendors.title": "लिखित समझौते के बिना वेंडर",
    "questions.vendors.question": "क्या आप बिना लिखित DPA के बाहरी लैब, सॉफ्टवेयर प्रदाताओं या अकाउंटेंट के साथ डेटा साझा करते हैं? (धारा 8(2))।",

    "questions.breach_contact.title": "नामित डेटा उल्लंघन संपर्क बिंदु",
    "questions.breach_contact.question": "क्या आपने उल्लंघन सूचना प्रक्रिया स्थापित की है और एक नामित संपर्क बिंदु प्रकाशित किया है? (धारा 8(6))।",

    "questions.retention_policy.title": "दस्तावेजी डेटा प्रतिधारण नीति",
    "questions.retention_policy.question": "क्या आपके पास उद्देश्य समाप्त होने पर डेटा को हटाने की लिखित समय-सारणी है? (धारा 8(7))।",

    "questions.children_served.title": "नाबालिगों के डेटा का सीधा प्रसंस्करण",
    "questions.children_served.question": "क्या आप जानबूझकर 18 वर्ष से कम उम्र के बच्चों का डेटा रखते हैं जिसके लिए माता-पिता की सहमति आवश्यक है? (धारा 9)।",

    "questions.shared_folder.title": "साझा या खुले फ़ोल्डर में ग्राहक फ़ाइलें",
    "questions.shared_folder.question": "क्या आप ग्राहक या मरीज की फाइलों को किसी साझा ड्राइव या खुले ग्रुप चैट में रखते हैं?",

    "questions.collection_notice.title": "संग्रह बिंदुओं पर सूचना",
    "questions.collection_notice.question": "क्या आप लोगों को बताते हैं कि आप उनका विवरण क्यों एकत्र करते हैं, जैसे रिसेप्शन पर बोर्ड या फॉर्म पर नोटिस?",

    # -------------------------------------------------------------
    # Purpose Labels
    # -------------------------------------------------------------
    "purposes.appointment_booking.label": "अपॉइंटमेंट बुकिंग",
    "purposes.billing_payment.label": "बिलिंग और भुगतान",
    "purposes.tax_records.label": "कर और लेखा रिकॉर्ड",
    "purposes.medical_care.label": "चिकित्सा देखभाल और निदान",
    "purposes.employment_payroll.label": "रोजगार और पेरोल",
    "purposes.marketing_offers.label": "विपणन और प्रचार संबंधी ऑफर",
    "purposes.legal_obligation.label": "कानूनी और अनुपालन दायित्व",
    "purposes.security_fraud.label": "सुरक्षा और धोखाधड़ी रोकथाम",
    "purposes.other.label": "अन्य व्यावसायिक उद्देश्य",

    # -------------------------------------------------------------
    # Checklist Items (6 core stages)
    # -------------------------------------------------------------
    "checklist.contain.title": "घटना पर नियंत्रण पाएं",
    "checklist.contain.task": "प्रभावित मशीनों को अलग करें और नेटवर्क से काटें। बिना सोचे-समझे सिस्टम बंद न करें (आईटी सलाहकार से पूछें)। प्रभावित क्रेडेंशियल्स रद्द करें।",

    "checklist.preserve_evidence.title": "सबूत सुरक्षित रखें",
    "checklist.preserve_evidence.task": "प्रभावित मशीनों को फॉर्मेट न करें। रैनसम नोट या स्क्रीन की फोटो लें। सिस्टम एक्सेस लॉग और ऑडिट ट्रेल सुरक्षित रूप से एक्सपोर्ट करें।",

    "checklist.assess.title": "प्रभाव क्षेत्र और कानूनी दायित्वों का आकलन",
    "checklist.assess.task": "प्रभाव का आकलन करें: डेटा श्रेणियों, प्रभावित लोगों और नाबालिगों की संख्या का अनुमान लगाएं। अन्य कानूनी रिपोर्टिंग कर्तव्यों (जैसे CERT-In) की जांच करें।",

    "checklist.notify.title": "वैधानिक और मुख्य सूचनाएं",
    "checklist.notify.task": "डेटा प्रोटेक्शन बोर्ड को बिना देरी प्रारंभिक सूचना भेजें। प्रभावित व्यक्तियों को सुरक्षा सलाह के साथ सूचित करें। 72 घंटों में विस्तृत रिपोर्ट तैयार करें।",

    "checklist.recover.title": "व्यापार पुनःप्राप्ति",
    "checklist.recover.task": "सिस्टम के बिना व्यवसाय कितने समय चल सकता है? स्वच्छ और सुरक्षित ऑफलाइन बैकअप से सिस्टम को पुनर्स्थापित करें (आईटी सलाहकार से पूछें)।",

    "checklist.review.title": "घटना-पश्चात समीक्षा",
    "checklist.review.task": "विस्तृत घटना-पश्चात समीक्षा करें। पहचानी गई कमियों को ठीक करें, नीतियां अपडेट करें और कर्मचारियों को गोपनीयता प्रशिक्षण दें।",

    # -------------------------------------------------------------
    # Notices & Disclaimers
    # -------------------------------------------------------------
    "notices.not_legal_advice": "यह तत्परता रिपोर्ट कवच द्वारा एक तकनीकी स्व-मूल्यांकन उपकरण के रूप में तैयार की गई है और यह कानूनी सलाह नहीं है। DPDP अधिनियम 2023 के अनुपालन के लिए योग्य कानूनी वकील से परामर्श करें।",
    "notices.citations_to_verify": "सभी कानूनी उद्धरण और व्याख्याएं मसौदा मार्गदर्शन हैं और इन पर निर्भर रहने से पहले कानूनी सत्यापन आवश्यक है।",
    "notices.readiness_aid_title": "तत्परता सहायता सूचना",
    "notices.readiness_aid_body": "यह ऑडिट रिपोर्ट एक स्वचालित तत्परता उपकरण और तकनीकी सारांश है। उद्धरण असत्यापित हैं। औपचारिक अनुपालन के लिए कानूनी सलाह लें।",
    "notices.footer": "Readiness aid, not legal advice. Citations unverified.",
    "notices.green_wording": "No issue found by Kavach's checks",
    "notices.machine_translated": "machine-translated, not yet reviewed",
    "notices.clause_a_title": "खंड (a) क्या हुआ",
    "notices.clause_b_title": "खंड (b) संभावित परिणाम",
    "notices.clause_c_title": "खंड (c) शमन के उपाय",
    "notices.clause_d_title": "खंड (d) सुरक्षा उपाय जो आप ले सकते हैं",
    "notices.clause_e_title": "खंड (e) व्यावसायिक संपर्क",
    "notices.notice_header": "डेटा प्रिंसिपल को डेटा सुरक्षा घटना की सूचना",
    "notices.draft_watermark": "DRAFT SIMULATION - DPDP Act Readiness (May 2027)",
    "notices.retention_warning": "डेटा प्रतिधारण अवधि जल्द ही समाप्त हो रही है। कृपया डेटा हटाए जाने से पहले अपना अनुपालन साक्ष्य पैक एक्सपोर्ट करें।",

    # -------------------------------------------------------------
    # Report Headings
    # -------------------------------------------------------------
    "reports.headings.title": "कवच अनुपालन तत्परता रिपोर्ट",
    "reports.headings.subtitle": "डिजिटल व्यक्तिगत डेटा संरक्षण अधिनियम (DPDP Act) तकनीकी ऑडिट स्नैपशॉट",
    "reports.headings.actions": "प्राथमिकता वाले अनुशंसित कार्य (अधिकतम 8)",
    "reports.headings.purpose_coverage": "उद्देश्य विनिर्देश कवरेज",
    "reports.headings.rule_assessments": "अनुपालन नियम मूल्यांकन",
    "reports.headings.rights_cases": "डेटा प्रिंसिपल अधिकार मामले",
    "reports.headings.erasure_receipts": "डेटा विलोपन अनुपालन रसीदें",
    "reports.headings.breach_simulations": "डेटा उल्लंघन सिमुलेशन (चिह्नित SIMULATION)",
    "reports.headings.audit_ledger": "क्रिप्टोग्राफिक ऑडिट लेजर",
    "reports.headings.limitations": "दायरा और सीमाएं",

    # -------------------------------------------------------------
    # Actions (with {count} placeholder)
    # -------------------------------------------------------------
    "actions.unknown_purposes.title": "व्यक्तिगत डेटा कॉलम के लिए अपुष्ट प्रसंस्करण उद्देश्य",
    "actions.unknown_purposes.reason": "{count} व्यक्तिगत डेटा कॉलम(ओं) में DPDP अधिनियम के तहत पुष्ट उद्देश्य का अभाव है।",
    "actions.unknown_purposes.how_to_fix": "अपुष्ट डेटा कॉलम की समीक्षा करें और प्रत्येक को एक वैध व्यावसायिक उद्देश्य से जोड़ें।",
    "actions.general.items_count": "सक्रिय डेटासेट में {count} परिचालन अनुपालन मदों का मूल्यांकन किया गया।",
}

KN: dict[str, str] = {
    # -------------------------------------------------------------
    # Flags / Rules (whats_right, whats_not, how_to_fix, title)
    # -------------------------------------------------------------
    "flags.health_data_safeguards.title": "ಆರೋಗ್ಯ ಡೇಟಾ ಭದ್ರತಾ ರಕ್ಷಣೆಗಳು",
    "flags.health_data_safeguards.whats_right": "No issue found by Kavach's checks: ಆರೋಗ್ಯ ಡೇಟಾವನ್ನು ಸೂಕ್ತ ರಕ್ಷಣೆಗಳೊಂದಿಗೆ ದೃಢೀಕರಿಸಿದ ವೈದ್ಯಕೀಯ ಚಿಕಿತ್ಸಾ ಉದ್ದೇಶಗಳಿಗೆ ಹೊಂದಿಸಲಾಗಿದೆ.",
    "flags.health_data_safeguards.whats_not": "ದೃಢೀಕೃತ ಕಾನೂನು ಉದ್ದೇಶ ಅಥವಾ ಪರಿಶೀಲಿಸಿದ ರಕ್ಷಣೆಗಳಿಲ್ಲದೆ ಆರೋಗ್ಯ ಮತ್ತು ರೋಗನಿರ್ಣಯದ ದಾಖಲೆಗಳು ಕಂಡುಬಂದಿವೆ.",
    "flags.health_data_safeguards.how_to_fix": "ಸ್ಟೋರೇಜ್ ಮತ್ತು ವರ್ಗಾವಣೆಯಲ್ಲಿ ಕಟ್ಟುನಿಟ್ಟಾದ ಎನ್‌ಕ್ರಿಪ್ಶನ್ ಬಳಸಿ, ವೈದ್ಯರಿಗೆ ಮಾತ್ರ ಪ್ರವೇಶ ಸೀಮಿತಗೊಳಿಸಿ ಮತ್ತು ವೈದ್ಯಕೀಯ ಉದ್ದೇಶ ದೃಢೀಕರಿಸಿ.",

    "flags.aadhaar_in_chat.title": "ವಾಟ್ಸಾಪ್/ಚಾಟ್ ಅಥವಾ ಮುಕ್ತ ಪಠ್ಯದಲ್ಲಿ ಆಧಾರ್ ಸಂಖ್ಯೆಗಳು",
    "flags.aadhaar_in_chat.whats_right": "No issue found by Kavach's checks: ಚಾಟ್ ಸಂಭಾಷಣೆಗಳಲ್ಲಿ ಮಾಸ್ಕ್ ಮಾಡದ ಆಧಾರ್ ಸಂಖ್ಯೆಗಳು ಇಲ್ಲದಿರುವುದು ದೃಢಪಟ್ಟಿದೆ.",
    "flags.aadhaar_in_chat.whats_not": "ರಫ್ತು ಮಾಡಿದ ವಾಟ್ಸಾಪ್ ಚಾಟ್‌ಗಳಲ್ಲಿ ಅಥವಾ ಟಿಪ್ಪಣಿಗಳಲ್ಲಿ ಮಾಸ್ಕ್ ಮಾಡದ ಆಧಾರ್ ಸಂಖ್ಯೆಗಳು ಪತ್ತೆಯಾಗಿವೆ.",
    "flags.aadhaar_in_chat.how_to_fix": "ಚಾಟ್‌ಗಳಿಂದ ಮಾಸ್ಕ್ ಮಾಡದ ಆಧಾರ್ ಸಂಖ್ಯೆಗಳನ್ನು ತಕ್ಷಣವೇ ಅಳಿಸಿ ಮತ್ತು ಸಂವಹನದಲ್ಲಿ ಮಾಸ್ಕಿಂಗ್ ಕಡ್ಡಾಯಗೊಳಿಸಿ.",

    "flags.aadhaar_multiple_files.title": "ಆಧಾರ್ ಒಂದಕ್ಕಿಂತ ಹೆಚ್ಚು ಫೈಲ್‌ಗಳಲ್ಲಿ ಸಂಗ್ರಹವಾಗಿದೆ",
    "flags.aadhaar_multiple_files.whats_right": "No issue found by Kavach's checks: ಆಧಾರ್ ಡೇಟಾವನ್ನು ಒಂದೇ ನಿರ್ಬಂಧಿತ ಫೈಲ್‌ನಲ್ಲಿ ಕ್ರೋಢೀಕರಿಸಲಾಗಿದೆ.",
    "flags.aadhaar_multiple_files.whats_not": "ಆಧಾರ್ ಸಂಖ್ಯೆಗಳು ಅನೇಕ ಪ್ರತ್ಯೇಕ ಸ್ಪ್ರೆಡ್‌ಶೀಟ್‌ಗಳಲ್ಲಿ ಅಥವಾ ಫಾರ್ಮ್‌ಗಳಲ್ಲಿ ನಕಲುಗೊಂಡಿವೆ.",
    "flags.aadhaar_multiple_files.how_to_fix": "ಆಧಾರ್ ದಾಖಲೆಗಳನ್ನು ಒಂದೇ ಸುರಕ್ಷಿತ ಸ್ಥಳದಲ್ಲಿ ಕ್ರೋಢೀಕರಿಸಿ ಮತ್ತು ಅನಗತ್ಯ ಫೈಲ್‌ಗಳಿಗಾಗಿ ಅಳಿಸುವ ಯೋಜನೆ ಜಾರಿಗೊಳಿಸಿ.",

    "flags.unrestricted_shared_source.title": "ನಿರ್ಬಂಧವಿಲ್ಲದ ಹಂಚಿಕೆಯ ಡ್ರೈವ್‌ನಲ್ಲಿ ವೈಯಕ್ತಿಕ ಡೇಟಾ",
    "flags.unrestricted_shared_source.whats_right": "Owner reports no shared folders (not verified by Kavach).",
    "flags.unrestricted_shared_source.whats_not": "ಗ್ರಾಹಕ ಅಥವಾ ರೋಗಿಯ ಮಾಹಿತಿಯು ನಿರ್ವಹಣೆಯಿಲ್ಲದ ವೈಯಕ್ತಿಕ ಸಾಧನಗಳಲ್ಲಿ ಅಥವಾ ಹಂಚಿಕೆಯ ಫೋಲ್ಡರ್‌ಗಳಲ್ಲಿ ಲಭ್ಯವಿದೆ.",
    "flags.unrestricted_shared_source.how_to_fix": "ಎಲ್ಲಾ ಗ್ರಾಹಕ ಸ್ಪ್ರೆಡ್‌ಶೀಟ್‌ಗಳನ್ನು ಪಾಸ್‌ವರ್ಡ್-ರಕ್ಷಿತ ಕ್ಲೌಡ್ ಸ್ಟೋರೇಜ್‌ಗೆ ಸ್ಥಳಾಂತರಿಸಿ.",

    "flags.minors_parental_consent.title": "ಅಪ್ರಾಪ್ತರ ಡೇಟಾ, ಪೋಷಕರ ಒಪ್ಪಿಗೆ ಅಗತ್ಯ",
    "flags.minors_parental_consent.whats_right": "Owner reports no unconsented processing of children's personal data (not verified by Kavach).",
    "flags.minors_parental_consent.whats_not": "18 ವರ್ಷಕ್ಕಿಂತ ಕಡಿಮೆ ವಯಸ್ಸಿನ ಮಕ್ಕಳ ದಾಖಲೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿದ ಪೋಷಕರ ಒಪ್ಪಿಗೆಯಿಲ್ಲದೆ ಸಂಸ್ಕರಿಸಲಾಗುತ್ತಿದೆ.",
    "flags.minors_parental_consent.how_to_fix": "ಮಕ್ಕಳ ವೈಯಕ್ತಿಕ ಮಾಹಿತಿಯನ್ನು ಸಂಸ್ಕರಿಸುವ ಮೊದಲು ಪರಿಶೀಲಿಸಬಹುದಾದ ಪೋಷಕರ ಒಪ್ಪಿಗೆಯನ್ನು ಜಾರಿಗೊಳಿಸಿ.",

    "flags.employee_data_lawful_basis.title": "ನೌಕರರ ಡೇಟಾ ಸಂಸ್ಕರಣೆಯ ಕಾನೂನುಬದ್ಧ ಆಧಾರ",
    "flags.employee_data_lawful_basis.whats_right": "No issue found by Kavach's checks: ಉದ್ಯೋಗಿ ದಾಖಲೆಗಳನ್ನು ಮಾನ್ಯ ಉದ್ಯೋಗ ಉದ್ದೇಶದ ಆಧಾರಕ್ಕೆ ಲಿಂಕ್ ಮಾಡಲಾಗಿದೆ.",
    "flags.employee_data_lawful_basis.whats_not": "ಸಿಬ್ಬಂದಿ ದಾಖಲೆಗಳಲ್ಲಿ ಉದ್ಯೋಗ ಉದ್ದೇಶದ ದಸ್ತಾವೇಜು ಅಥವಾ ಗೌಪ್ಯತಾ ಸೂಚನೆಯ ಕೊರತೆಯಿದೆ.",
    "flags.employee_data_lawful_basis.how_to_fix": "ಸೆಕ್ಷನ್ 7(i) ಅಡಿಯಲ್ಲಿ ಉದ್ಯೋಗಿ ಉದ್ದೇಶವನ್ನು ದಾಖಲಿಸಿ ಮತ್ತು ಸಿಬ್ಬಂದಿ ಗೌಪ್ಯತಾ ಸೂಚನೆಗಳನ್ನು ನೀಡಿ.",

    "flags.notice_at_collection.title": "ಡೇಟಾ ಸಂಗ್ರಹಣಾ ಸ್ಥಳಗಳಲ್ಲಿ ನೋಟಿಸ್ ಇಲ್ಲದಿರುವುದು",
    "flags.notice_at_collection.whats_right": "Owner reports a notice is shown (not verified by Kavach).",
    "flags.notice_at_collection.whats_not": "ಸಿಸಿಟಿವಿ ಅಥವಾ ನೋಂದಣಿ ಕೌಂಟರ್‌ಗಳಲ್ಲಿ ಸ್ಪಷ್ಟ, ಸರಳ ಭಾಷೆಯ ಗೌಪ್ಯತಾ ನೋಟಿಸ್ ಇಲ್ಲದೆ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿವೆ.",
    "flags.notice_at_collection.how_to_fix": "ಸಿಸಿಟಿವಿ ಕ್ಯಾಮೆರಾಗಳ ಬಳಿ ಪ್ರಮುಖ ಬೋರ್ಡ್ ಹಾಕಿ ಮತ್ತು ನೋಂದಣಿ ಫಾರ್ಮ್‌ಗಳಲ್ಲಿ ಸಂಗ್ರಹಣಾ ನೋಟಿಸ್ ಸೇರಿಸಿ.",

    "flags.breach_contact_process.title": "ಉಲ್ಲಂಘನೆ ಸಂಪರ್ಕ ವ್ಯಕ್ತಿ/ಪ್ರಕ್ರಿಯೆ ಇಲ್ಲದಿರುವುದು",
    "flags.breach_contact_process.whats_right": "Owner reports a designated breach contact person and notification procedure are established (not verified by Kavach).",
    "flags.breach_contact_process.whats_not": "ಮಂಡಳಿ ಮತ್ತು ಪೀಡಿತ ಜನರಿಗೆ ವಿಳಂಬವಿಲ್ಲದೆ ತಿಳಿಸಲು ಯಾವುದೇ ಅಧಿಕೃತ ಸಂಪರ್ಕ ವ್ಯಕ್ತಿ ಅಥವಾ ಪ್ರಕ್ರಿಯೆಯಿಲ್ಲ.",
    "flags.breach_contact_process.how_to_fix": "ಗೌಪ್ಯತಾ ಅಧಿಕಾರಿಯನ್ನು ನೇಮಿಸಿ, ಅಧಿಸೂಚನೆ ಪ್ರಕ್ರಿಯೆಯನ್ನು ದಾಖಲಿಸಿ ಮತ್ತು ಚೆಕ್‌ಲಿಸ್ಟ್ ಪರಿಶೀಲಿಸಿ.",

    "flags.retention_policy.title": "ಡೇಟಾ ಉಳಿಸಿಕೊಳ್ಳುವ ನೀತಿಯ ಕೊರತೆ",
    "flags.retention_policy.whats_right": "Owner reports a written data retention and scheduled disposal policy is documented (not verified by Kavach).",
    "flags.retention_policy.whats_not": "ಕಾನೂನು ಮತ್ತು ವ್ಯವಹಾರ ಉದ್ದೇಶ ಮುಗಿದ ನಂತರ ವೈಯಕ್ತಿಕ ಡೇಟಾವನ್ನು ಅಳಿಸಲು ಲಿಖಿತ ನೀತಿ ಇಲ್ಲ.",
    "flags.retention_policy.how_to_fix": "ಡೇಟಾ ಉಳಿಸಿಕೊಳ್ಳುವ ವೇಳಾಪಟ್ಟಿಯನ್ನು ಅಳವಡಿಸಿಕೊಳ್ಳಿ ಮತ್ತು ಹಳೆಯ ದಾಖಲೆಗಳನ್ನು ನಿಯಮಿತವಾಗಿ ಅಳಿಸಿ.",

    "flags.data_on_personal_phones.title": "ವೈಯಕ್ತಿಕ ಫೋನ್‌ಗಳಲ್ಲಿ ಡೇಟಾ ಸಂಗ್ರಹ",
    "flags.data_on_personal_phones.whats_right": "Owner reports staff are prohibited from holding customer records on personal phones (not verified by Kavach).",
    "flags.data_on_personal_phones.whats_not": "ಸಿಬ್ಬಂದಿ ಅಥವಾ ವೈದ್ಯರು ಎನ್‌ಕ್ರಿಪ್ಟ್ ಮಾಡದ ಗ್ರಾಹಕರ ಫೈಲ್‌ಗಳನ್ನು ವೈಯಕ್ತಿಕ ಸಾಧನಗಳಲ್ಲಿ ಇರಿಸಿಕೊಂಡಿದ್ದಾರೆ.",
    "flags.data_on_personal_phones.how_to_fix": "ವೈಯಕ್ತಿಕ ಮೊಬೈಲ್ ಸಾಧನಗಳಲ್ಲಿ ಸ್ಥಳೀಯ ಸಂಗ್ರಹಣೆಯನ್ನು ನಿಷೇಧಿಸುವ ಅಧಿಕೃತ ನೀತಿಯನ್ನು ಜಾರಿಗೊಳಿಸಿ.",

    "flags.vendors_unwritten_agreement.title": "ಲಿಖಿತ ಒಪ್ಪಂದವಿಲ್ಲದ ಪೂರೈಕೆದಾರರು/ಸಂಸ್ಕಾರಕರು",
    "flags.vendors_unwritten_agreement.whats_right": "Owner reports written Data Processing Agreements are executed with all processors (not verified by Kavach).",
    "flags.vendors_unwritten_agreement.whats_not": "ಲಿಖಿತ ಡೇಟಾ ಸಂಸ್ಕರಣಾ ಒಪ್ಪಂದವಿಲ್ಲದೆ ಮೂರನೇ ವ್ಯಕ್ತಿಯ ಲ್ಯಾಬ್‌ಗಳು ಅಥವಾ ಸಾಫ್ಟ್‌ವೇರ್ ಜೊತೆ ಡೇಟಾ ಹಂಚಿಕೊಳ್ಳಲಾಗಿದೆ.",
    "flags.vendors_unwritten_agreement.how_to_fix": "ಪ್ರತಿಯೊಬ್ಬ ಬಾಹ್ಯ ಪೂರೈಕೆದಾರರೊಂದಿಗೆ ಸಂಸ್ಕರಣಾ ಕರ್ತವ್ಯಗಳನ್ನು ವಿವರಿಸುವ ಲಿಖಿತ ಒಪ್ಪಂದಗಳನ್ನು ಮಾಡಿಕೊಳ್ಳಿ.",

    "flags.data_sprawl_files.title": "ಒಬ್ಬನೇ ವ್ಯಕ್ತಿಯ ಡೇಟಾ ಹಲವು ಫೈಲ್‌ಗಳಲ್ಲಿ ಹರಡಿದೆ (ಡೇಟಾ ಹರಡುವಿಕೆ)",
    "flags.data_sprawl_files.whats_right": "No issue found by Kavach's checks: ಅನಗತ್ಯ ಹರಡುವಿಕೆಯಿಲ್ಲದೆ ಪ್ರೊಫೈಲ್‌ಗಳನ್ನು ಕ್ರೋಢೀಕರಿಸಲಾಗಿದೆ.",
    "flags.data_sprawl_files.whats_not": "ವೈಯಕ್ತಿಕ ಮಾಹಿತಿಯು ಮೂರು ಅಥವಾ ಹೆಚ್ಚಿನ ಪ್ರತ್ಯೇಕ ಸ್ಪ್ರೆಡ್‌ಶೀಟ್‌ಗಳಲ್ಲಿ ಅಥವಾ ವ್ಯವಸ್ಥೆಗಳಲ್ಲಿ ಹಂಚಿಹೋಗಿದೆ.",
    "flags.data_sprawl_files.how_to_fix": "ನಕಲಿ ದಾಖಲೆಗಳನ್ನು ಒಗ್ಗೂಡಿಸಿ ಮತ್ತು ಹಳೆಯ ಪ್ರತಿಗಳನ್ನು ಅಳಿಸುವ ಯೋಜನೆ ಮೂಲಕ ತೆಗೆದುಹಾಕಿ.",

    "flags.unknown_purposes.title": "ಡೇಟಾ ಕಾಲಮ್‌ಗಳಿಗೆ ದೃಢೀಕರಿಸದ ಸಂಸ್ಕರಣಾ ಉದ್ದೇಶಗಳು",
    "flags.unknown_purposes.whats_right": "No issue found by Kavach's checks: ಎಲ್ಲಾ ಗುರುತಿನ ಕಾಲಮ್‌ಗಳು ದೃಢೀಕೃತ ಸಂಸ್ಕರಣಾ ಉದ್ದೇಶಗಳನ್ನು ಹೊಂದಿವೆ.",
    "flags.unknown_purposes.whats_not": "ಒಂದು ಅಥವಾ ಹೆಚ್ಚಿನ ವೈಯಕ್ತಿಕ ಡೇಟಾ ಕಾಲಮ್‌ಗಳಿಗೆ ದೃಢೀಕೃತ ಸಂಸ್ಕರಣಾ ಉದ್ದೇಶವಿಲ್ಲ.",
    "flags.unknown_purposes.how_to_fix": "ಪ್ರಶ್ನೆಗಳನ್ನು ಪರಿಶೀಲಿಸಿ ಮತ್ತು ಪ್ರತಿ ಕಾಲಮ್‌ಗೆ ಮಾನ್ಯವಾದ ವ್ಯವಹಾರ ಉದ್ದೇಶವನ್ನು ದೃಢೀಕರಿಸಿ.",

    "flags.no_named_contact.title": "ಯಾವುದೇ ಉಲ್ಲಂಘನೆ ಸಂಪರ್ಕ ವ್ಯಕ್ತಿ ನಿಯೋಜಿಸಲಾಗಿಲ್ಲ",
    "flags.no_named_contact.whats_right": "Owner reports designated breach notification officer established (not verified by Kavach).",
    "flags.no_named_contact.whats_not": "ಉಲ್ಲಂಘನೆಯ ಮಾಹಿತಿ ನೀಡಲು ಸಂಸ್ಥೆಯು ಯಾವುದೇ ನಿರ್ದಿಷ್ಟ ಸಂಪರ್ಕ ವ್ಯಕ್ತಿಯನ್ನು ನೇಮಿಸಿಲ್ಲ.",
    "flags.no_named_contact.how_to_fix": "ಹೆಸರಿಸಲಾದ ಸಂಪರ್ಕ ಅಧಿಕಾರಿಯನ್ನು ನೇಮಿಸಿ ಮತ್ತು ಉಲ್ಲಂಘನೆ ಪ್ರತಿಕ್ರಿಯೆ ಚೆಕ್‌ಲಿಸ್ಟ್ ಅನ್ನು ಜಾರಿಗೆ ತನ್ನಿ.",

    # -------------------------------------------------------------
    # Questionnaire Questions
    # -------------------------------------------------------------
    "questions.cctv.title": "ಆವರಣದಲ್ಲಿ ಸಿಸಿಟಿವಿ ಕಣ್ಗಾವಲು",
    "questions.cctv.question": "ನೀವು ರೋಗಿಗಳು, ಗ್ರಾಹಕರು ಅಥವಾ ಕಚೇರಿ ಆವರಣದಲ್ಲಿ ಸಿಸಿಟಿವಿ ಕ್ಯಾಮೆರಾಗಳನ್ನು ಬಳಸುತ್ತೀರಾ? (ಸೆಕ್ಷನ್ 5 ರ ಅಡಿಯಲ್ಲಿ ನೋಟಿಸ್ ಕಡ್ಡಾಯ).",

    "questions.personal_phones.title": "ಸಿಬ್ಬಂದಿಯ ವೈಯಕ್ತಿಕ ಮೊಬೈಲ್ ಸಾಧನಗಳು",
    "questions.personal_phones.question": "ಸಿಬ್ಬಂದಿ ಅಥವಾ ವೈದ್ಯರು ರೋಗಿ ಅಥವಾ ಗ್ರಾಹಕರ ದಾಖಲೆಗಳನ್ನು ವೈಯಕ್ತಿಕ ಫೋನ್‌ಗಳಲ್ಲಿ ಇರಿಸಿಕೊಳ್ಳುತ್ತಾರೆಯೇ? (ಸೆಕ್ಷನ್ 8(5)).",

    "questions.vendors.title": "ಲಿಖಿತ ಒಪ್ಪಂದವಿಲ್ಲದ ಪೂರೈಕೆದಾರರು",
    "questions.vendors.question": "ನೀವು ಲಿಖಿತ ಒಪ್ಪಂದಗಳಿಲ್ಲದೆ ಬಾಹ್ಯ ಲ್ಯಾಬ್‌ಗಳು ಅಥವಾ ಸಾಫ್ಟ್‌ವೇರ್ ಸಂಸ್ಥೆಗಳೊಂದಿಗೆ ಡೇಟಾ ಹಂಚಿಕೊಳ್ಳುತ್ತೀರಾ? (ಸೆಕ್ಷನ್ 8(2)).",

    "questions.breach_contact.title": "ನಿರ್ದಿಷ್ಟ ಉಲ್ಲಂಘನೆ ಸಂಪರ್ಕ ವ್ಯಕ್ತಿ",
    "questions.breach_contact.question": "ನೀವು ಉಲ್ಲಂಘನೆ ಅಧಿಸೂಚನೆ ಪ್ರಕ್ರಿಯೆಯನ್ನು ಸ್ಥಾಪಿಸಿದ್ದೀರಾ ಮತ್ತು ಸಂಪರ್ಕ ಅಧಿಕಾರಿಯನ್ನು ಪ್ರಕಟಿಸಿದ್ದೀರಾ? (ಸೆಕ್ಷನ್ 8(6)).",

    "questions.retention_policy.title": "ದಾಖಲಿತ ಡೇಟಾ ಉಳಿಸಿಕೊಳ್ಳುವ ನೀತಿ",
    "questions.retention_policy.question": "ಉದ್ದೇಶ ಮುಗಿದ ನಂತರ ವೈಯಕ್ತಿಕ ಡೇಟಾವನ್ನು ನಿಯಮಿತವಾಗಿ ಅಳಿಸಲು ನಿಮ್ಮ ಬಳಿ ಲಿಖಿತ ವೇಳಾಪಟ್ಟಿ ಇದೆಯೇ? (ಸೆಕ್ಷನ್ 8(7)).",

    "questions.children_served.title": "ಅಪ್ರಾಪ್ತರ ಡೇಟಾದ ನೇರ ಸಂಸ್ಕರಣೆ",
    "questions.children_served.question": "ನೀವು ಪೋಷಕರ ಒಪ್ಪಿಗೆ ಅಗತ್ಯವಿರುವ 18 ವರ್ಷಕ್ಕಿಂತ ಕಡಿಮೆ ವಯಸ್ಸಿನ ಮಕ್ಕಳ ಡೇಟಾವನ್ನು ಉಳಿಸಿಕೊಳ್ಳುತ್ತೀರಾ? (ಸೆಕ್ಷನ್ 9).",

    "questions.shared_folder.title": "ಹಂಚಿಕೆಯ ಫೋಲ್ಡರ್‌ನಲ್ಲಿ ಗ್ರಾಹಕರ ಫೈಲ್‌ಗಳು",
    "questions.shared_folder.question": "ಗ್ರಾಹಕರ ಅಥವಾ ರೋಗಿಗಳ ಫೈಲ್‌ಗಳನ್ನು ಯಾರಾದರೂ ತೆರೆಯಬಹುದಾದ ಹಂಚಿಕೆಯ ಡ್ರೈವ್ ಅಥವಾ ಗ್ರೂಪ್ ಚಾಟ್‌ನಲ್ಲಿ ಇರಿಸುತ್ತೀರಾ?",

    "questions.collection_notice.title": "ಸಂಗ್ರಹಣಾ ಸ್ಥಳಗಳಲ್ಲಿ ನೋಟಿಸ್",
    "questions.collection_notice.question": "ಜನರಿಂದ ವಿವರಗಳನ್ನು ಏಕೆ ಸಂಗ್ರಹಿಸುತ್ತೀರಿ ಎಂದು ಅವರಿಗೆ ತಿಳಿಸುತ್ತೀರಾ (ಉದಾಹರಣೆಗೆ ಕೌಂಟರ್‌ನಲ್ಲಿ ಬೋರ್ಡ್ ಅಥವಾ ಫಾರ್ಮ್‌ನಲ್ಲಿ ಸೂಚನೆ)?",

    # -------------------------------------------------------------
    # Purpose Labels
    # -------------------------------------------------------------
    "purposes.appointment_booking.label": "ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಬುಕಿಂಗ್",
    "purposes.billing_payment.label": "ಬಿಲ್ಲಿಂಗ್ ಮತ್ತು ಪಾವತಿ",
    "purposes.tax_records.label": "ತೆರಿಗೆ ಮತ್ತು ಲೆಕ್ಕಪತ್ರ ದಾಖಲೆಗಳು",
    "purposes.medical_care.label": "ವೈದ್ಯಕೀಯ ಆರೈಕೆ ಮತ್ತು ರೋಗನಿರ್ಣಯ",
    "purposes.employment_payroll.label": "ಉದ್ಯೋಗ ಮತ್ತು ವೇತನದಾರರ ಪಟ್ಟಿ",
    "purposes.marketing_offers.label": "ಮಾರ್ಕೆಟಿಂಗ್ ಮತ್ತು ಪ್ರಚಾರದ ಕೊಡುಗೆಗಳು",
    "purposes.legal_obligation.label": "ಕಾನೂನು ಮತ್ತು ಅನುಸರಣೆ ಬಾಧ್ಯತೆ",
    "purposes.security_fraud.label": "ಭದ್ರತೆ ಮತ್ತು ವಂಚನೆ ತಡೆಗಟ್ಟುವಿಕೆ",
    "purposes.other.label": "ಇತರ ವ್ಯಾಪಾರ ಉದ್ದೇಶ",

    # -------------------------------------------------------------
    # Checklist Items (6 core stages)
    # -------------------------------------------------------------
    "checklist.contain.title": "ಘಟನೆಯನ್ನು ನಿಯಂತ್ರಿಸಿ",
    "checklist.contain.task": "ಬಾಧಿತ ಯಂತ್ರಗಳನ್ನು ಪ್ರತ್ಯೇಕಿಸಿ ಮತ್ತು ನೆಟ್‌ವರ್ಕ್‌ನಿಂದ ಸಂಪರ್ಕ ಕಡಿತಗೊಳಿಸಿ. ಯೋಚಿಸದೆ ಸಿಸ್ಟಮ್ ಆಫ್ ಮಾಡಬೇಡಿ (ಐಟಿ ಸಲಹೆಗಾರರನ್ನು ಕೇಳಿ). ರಾಜಿ ಮಾಡಿಕೊಂಡ ರುಜುವಾತುಗಳನ್ನು ರದ್ದುಗೊಳಿಸಿ.",

    "checklist.preserve_evidence.title": "ಸಾಕ್ಷ್ಯಾಧಾರಗಳನ್ನು ಸಂರಕ್ಷಿಸಿ",
    "checklist.preserve_evidence.task": "ಬಾಧಿತ ಕಂಪ್ಯೂಟರ್‌ಗಳನ್ನು ಫಾರ್ಮ್ಯಾಟ್ ಮಾಡಬೇಡಿ. ದೋಷ ಸಂದೇಶ ಅಥವಾ ರಾನ್‌ಸಮ್ ಟಿಪ್ಪಣಿಯ ಫೋಟೋ ತೆಗೆಯಿರಿ. ಸಿಸ್ಟಮ್ ಆಕ್ಸೆಸ್ ಲಾಗ್‌ಗಳನ್ನು ಸುರಕ್ಷಿತವಾಗಿ ರಫ್ತು ಮಾಡಿ.",

    "checklist.assess.title": "ಪರಿಣಾಮ ಮತ್ತು ಬಾಧ್ಯತೆಗಳ ಮೌಲ್ಯಮಾಪನ",
    "checklist.assess.task": "ಪರಿಣಾಮವನ್ನು ಅಂದಾಜಿಸಿ: ಡೇಟಾ ವರ್ಗಗಳು, ಬಾಧಿತ ವ್ಯಕ್ತಿಗಳು ಮತ್ತು ಮಕ್ಕಳ ದಾಖಲೆಗಳ ಸಂಖ್ಯೆಯನ್ನು ಲೆಕ್ಕಹಾಕಿ. ಇತರ ಕಾನೂನು ವರದಿ ಮಾಡುವ ಕರ್ತವ್ಯಗಳನ್ನು (CERT-In) ಪರಿಶೀಲಿಸಿ.",

    "checklist.notify.title": "ಕಾನೂನುಬದ್ಧ ಮತ್ತು ಗ್ರಾಹಕ ಅಧಿಸೂಚನೆಗಳು",
    "checklist.notify.task": "ಡೇಟಾ ರಕ್ಷಣಾ ಮಂಡಳಿಗೆ ತಕ್ಷಣವೇ ಪ್ರಾಥಮಿಕ ಮಾಹಿತಿಯನ್ನು ಸಲ್ಲಿಸಿ. ಬಾಧಿತ ವ್ಯಕ್ತಿಗಳಿಗೆ ರಕ್ಷಣಾ ಸಲಹೆಯೊಂದಿಗೆ ತಿಳಿಸಿ. 72 ಗಂಟೆಗಳಲ್ಲಿ ವಿವರವಾದ ವರದಿ ಸಿದ್ಧಪಡಿಸಿ.",

    "checklist.recover.title": "ವ್ಯವಹಾರ ಮರುಸ್ಥಾಪನೆ",
    "checklist.recover.task": "ವ್ಯವಸ್ಥೆಯಿಲ್ಲದೆ ವ್ಯಾಪಾರ ಎಷ್ಟು ದಿನ ನಡೆಯಬಹುದು? ಸ್ವಚ್ಛ ಮತ್ತು ಪ್ರತ್ಯೇಕ ಆಫ್‌ಲೈನ್ ಬ್ಯಾಕ್‌ಅಪ್‌ಗಳಿಂದ ಸಿಸ್ಟಮ್‌ಗಳನ್ನು ಮರುಸ್ಥಾಪಿಸಿ (ಐಟಿ ಸಲಹೆಗಾರರನ್ನು ಕೇಳಿ).",

    "checklist.review.title": "ಘಟನೆಯ ನಂತರದ ಪರಿಶೀಲನೆ",
    "checklist.review.task": "ಘಟನೆಯ ನಂತರ ಸಂಪೂರ್ಣ ಪರಿಶೀಲನೆ ನಡೆಸಿ. ಗುರುತಿಸಲಾದ ನ್ಯೂನತೆಗಳನ್ನು ಸರಿಪಡಿಸಿ, ನೀತಿಗಳನ್ನು ನವೀಕರಿಸಿ ಮತ್ತು ಸಿಬ್ಬಂದಿಗೆ ಗೌಪ್ಯತಾ ತರಬೇತಿ ನೀಡಿ.",

    # -------------------------------------------------------------
    # Notices & Disclaimers
    # -------------------------------------------------------------
    "notices.not_legal_advice": "ಈ ಸನ್ನದ್ಧತೆಯ ವರದಿಯನ್ನು ಕವಚವು ತಾಂತ್ರಿಕ ಸ್ವಯಂ-ಮೌಲ್ಯಮಾಪನ ಸಾಧನವಾಗಿ ರಚಿಸಿದೆ ಮತ್ತು ಇದು ಕಾನೂನು ಸಲಹೆಯಲ್ಲ. DPDP ಕಾಯ್ದೆ 2023 ರ ಅನುಸರಣೆಗಾಗಿ ಅರ್ಹ ಕಾನೂನು ಸಲಹೆಗಾರರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
    "notices.citations_to_verify": "ಎಲ್ಲಾ ಕಾನೂನು ಉಲ್ಲೇಖಗಳು ಕರಡು ಮಾರ್ಗದರ್ಶನವಾಗಿದ್ದು, ಇವುಗಳ ಮೇಲೆ ಅವಲಂಬಿಸುವ ಮೊದಲು ಮಾನವ ಕಾನೂನು ಪರಿಶೀಲನೆ ಅಗತ್ಯವಿದೆ.",
    "notices.readiness_aid_title": "ಸನ್ನದ್ಧತಾ ಸಹಾಯ ಸೂಚನೆ",
    "notices.readiness_aid_body": "ಈ ಆಡಿಟ್ ವರದಿಯು ಸ್ವಯಂಚಾಲಿತ ತಾಂತ್ರಿಕ ಸಾರಾಂಶವಾಗಿದೆ. ಉಲ್ಲೇಖಗಳು ದೃಢೀಕರಿಸಲ್ಪಟ್ಟಿಲ್ಲ. ಅಧಿಕೃತ ಅನುಸರಣೆಗಾಗಿ ಕಾನೂನು ಸಲಹೆ ಪಡೆಯಿರಿ.",
    "notices.footer": "Readiness aid, not legal advice. Citations unverified.",
    "notices.green_wording": "No issue found by Kavach's checks",
    "notices.machine_translated": "machine-translated, not yet reviewed",
    "notices.clause_a_title": "ಖಂಡ (a) ಏನಾಯಿತು",
    "notices.clause_b_title": "ಖಂಡ (b) ಸಂಭವನೀಯ ಪರಿಣಾಮಗಳು",
    "notices.clause_c_title": "ಖಂಡ (c) ಪರಿಹಾರ ಕ್ರಮಗಳು",
    "notices.clause_d_title": "ಖಂಡ (d) ನೀವು ತೆಗೆದುಕೊಳ್ಳಬಹುದಾದ ಸುರಕ್ಷತಾ ಕ್ರಮಗಳು",
    "notices.clause_e_title": "ಖಂಡ (e) ವ್ಯವಹಾರ ಸಂಪರ್ಕ",
    "notices.notice_header": "ಡೇಟಾ ಪ್ರಿನ್ಸಿಪಾಲ್‌ಗೆ ಭದ್ರತಾ ಘಟನೆಯ ಸೂಚನೆ",
    "notices.draft_watermark": "DRAFT SIMULATION - DPDP Act Readiness (May 2027)",
    "notices.retention_warning": "ಡೇಟಾ ಉಳಿಸಿಕೊಳ್ಳುವ ಅವಧಿ ಶೀಘ್ರದಲ್ಲೇ ಮುಕ್ತಾಯಗೊಳ್ಳಲಿದೆ. ಡೇಟಾ ಅಳಿಸುವ ಮೊದಲು ದಯವಿಟ್ಟು ನಿಮ್ಮ ಸಾಕ್ಷ್ಯ ಪ್ಯಾಕ್ ಅನ್ನು ರಫ್ತು ಮಾಡಿ.",

    # -------------------------------------------------------------
    # Report Headings
    # -------------------------------------------------------------
    "reports.headings.title": "ಕವಚ ಅನುಸರಣೆ ಸನ್ನದ್ಧತಾ ವರದಿ",
    "reports.headings.subtitle": "ಡಿಜಿಟಲ್ ವೈಯಕ್ತಿಕ ಡೇಟಾ ಸಂರಕ್ಷಣಾ ಕಾಯ್ದೆ (DPDP Act) ತಾಂತ್ರಿಕ ಆಡಿಟ್ ಸಾರಾಂಶ",
    "reports.headings.actions": "ಆದ್ಯತೆಯ ಶಿಫಾರಸು ಮಾಡಿದ ಕ್ರಮಗಳು (ಗರಿಷ್ಠ 8)",
    "reports.headings.purpose_coverage": "ಉದ್ದೇಶ ನಿರ್ದಿಷ್ಟತೆಯ ವ್ಯಾಪ್ತಿ",
    "reports.headings.rule_assessments": "ಅನುಸರಣೆ ನಿಯಮ ಮೌಲ್ಯಮಾಪನಗಳು",
    "reports.headings.rights_cases": "ಡೇಟಾ ಪ್ರಿನ್ಸಿಪಾಲ್ ಹಕ್ಕುಗಳ ಪ್ರಕರಣಗಳು",
    "reports.headings.erasure_receipts": "ಡೇಟಾ ಅಳಿಸುವಿಕೆ ಅನುಸರಣೆ ರಶೀದಿಗಳು",
    "reports.headings.breach_simulations": "ಉಲ್ಲಂಘನೆ ಸಿಮ್ಯುಲೇಶನ್‌ಗಳು (ಗುರುತಿಸಲಾದ SIMULATION)",
    "reports.headings.audit_ledger": "ಕ್ರಿಪ್ಟೋಗ್ರಾಫಿಕ್ ಆಡಿಟ್ ಲೆಡ್ಜರ್",
    "reports.headings.limitations": "ವ್ಯಾಪ್ತಿ ಮತ್ತು ಮಿತಿಗಳು",

    # -------------------------------------------------------------
    # Actions (with {count} placeholder)
    # -------------------------------------------------------------
    "actions.unknown_purposes.title": "ವೈಯಕ್ತಿಕ ಡೇಟಾ ಕಾಲಮ್‌ಗಳಿಗೆ ದೃಢೀಕರಿಸದ ಸಂಸ್ಕರಣಾ ಉದ್ದೇಶಗಳು",
    "actions.unknown_purposes.reason": "{count} ವೈಯಕ್ತಿಕ ಡೇಟಾ ಕಾಲಮ್‌ಗಳಿಗೆ DPDP ಕಾಯ್ದೆಯಡಿಯಲ್ಲಿ ದೃಢೀಕೃತ ಉದ್ದೇಶವಿಲ್ಲ.",
    "actions.unknown_purposes.how_to_fix": "ದೃಢೀಕರಿಸದ ಕಾಲಮ್‌ಗಳನ್ನು ಪರಿಶೀಲಿಸಿ ಮತ್ತು ಪ್ರತಿಯೊಂದನ್ನು ಮಾನ್ಯ ವ್ಯಾಪಾರ ಉದ್ದೇಶಕ್ಕೆ ಲಿಂಕ್ ಮಾಡಿ.",
    "actions.general.items_count": "ಸಕ್ರಿಯ ಡೇಟಾಸೆಟ್‌ಗಳಲ್ಲಿ {count} ಕಾರ್ಯಾಚರಣೆಯ ಅನುಸರಣೆ ಅಂಶಗಳನ್ನು ಮೌಲ್ಯಮಾಪನ ಮಾಡಲಾಗಿದೆ.",
}

# Validation
missing_in_hi = set(EN.keys()) - set(HI.keys())
missing_in_kn = set(EN.keys()) - set(KN.keys())
extra_in_hi = set(HI.keys()) - set(EN.keys())
extra_in_kn = set(KN.keys()) - set(EN.keys())

assert not missing_in_hi, f"Missing in hi: {missing_in_hi}"
assert not missing_in_kn, f"Missing in kn: {missing_in_kn}"
assert not extra_in_hi, f"Extra in hi: {extra_in_hi}"
assert not extra_in_kn, f"Extra in kn: {extra_in_kn}"

# Placeholders validation
placeholder_re = re.compile(r"\{[a-zA-Z0-9_]+\}")
for k in EN:
    en_vars = sorted(placeholder_re.findall(EN[k]))
    hi_vars = sorted(placeholder_re.findall(HI[k]))
    kn_vars = sorted(placeholder_re.findall(KN[k]))
    assert en_vars == hi_vars, f"Placeholder mismatch in hi for {k}: {en_vars} vs {hi_vars}"
    assert en_vars == kn_vars, f"Placeholder mismatch in kn for {k}: {en_vars} vs {kn_vars}"

print(f"Validated {len(EN)} keys successfully across en, hi, kn!")

# Write files
with open(LOCALES_DIR / "en.json", "w", encoding="utf-8") as f:
    json.dump(EN, f, indent=2, ensure_ascii=False)

with open(LOCALES_DIR / "hi.json", "w", encoding="utf-8") as f:
    json.dump(HI, f, indent=2, ensure_ascii=False)

with open(LOCALES_DIR / "kn.json", "w", encoding="utf-8") as f:
    json.dump(KN, f, indent=2, ensure_ascii=False)

# review_status.json starts empty
with open(LOCALES_DIR / "review_status.json", "w", encoding="utf-8") as f:
    json.dump([], f, indent=2)

print("Wrote locales/en.json, hi.json, kn.json, review_status.json")
