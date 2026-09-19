/**
 * The interface in Hindi, by choice, kept on the device.
 *
 * A government instrument is used by everyone, and the person at the bin is
 * as likely to read Hindi as English. The toggle in the command bar switches
 * the chrome: navigation, page headers, the Workbench's verbs, the Scan
 * screen's labels, the sign-in page. Data never changes language: a
 * description is shown as the catalogue wrote it, a code is a code, and a
 * figure is a figure.
 *
 * `t(english)` returns the Hindi for a string the dictionary knows and the
 * English otherwise, so a string nobody translated yet is still readable and
 * a missing translation is never a blank. Keys are the English strings
 * themselves, which keeps the source honest: what the dictionary translates
 * is exactly what the screen says.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Lang = 'en' | 'hi'

const KEY = 'saman.lang'

const HI: Record<string, string> = {
  // navigation groups and entries
  Overview: 'अवलोकन',
  Review: 'समीक्षा',
  Analytics: 'विश्लेषण',
  Tools: 'उपकरण',
  Governance: 'शासन',
  Catalogue: 'कैटलॉग',
  Home: 'मुख्य पृष्ठ',
  Search: 'खोज',
  Workbench: 'वर्कबेंच',
  Substitutes: 'विकल्प',
  Executive: 'कार्यकारी',
  Opportunity: 'अवसर',
  Scan: 'स्कैन',
  'Smart-Create': 'स्मार्ट-क्रिएट',
  'Restricted mode': 'प्रतिबंधित मोड',
  Copilot: 'सहचालक',
  Onboard: 'ऑनबोर्ड',
  Migration: 'माइग्रेशन',
  Audit: 'ऑडिट',
  Admin: 'प्रशासन',
  // page headers
  'Executive dashboard': 'कार्यकारी डैशबोर्ड',
  'Audit trail': 'ऑडिट ट्रेल',
  Administration: 'प्रशासन',
  Compare: 'तुलना',
  'ERP migration': 'ERP माइग्रेशन',
  Label: 'लेबल',
  'Onboard a CPSE': 'एक CPSE ऑनबोर्ड करें',
  'Page not found': 'पृष्ठ नहीं मिला',
  'Pick two rows': 'दो पंक्तियाँ चुनें',
  'Adjudicate candidate matches with the evidence and any hard-constraint veto side by side.':
    'संभावित मिलानों पर साक्ष्य और किसी भी कठोर-बाध्यता वीटो के साथ, आमने-सामने निर्णय लें।',
  'Every CPSE catalogue, searched on the normalized text, so an abbreviated row is findable by its spelled-out form and the other way round.':
    'हर CPSE का कैटलॉग, सामान्यीकृत पाठ पर खोजा गया, ताकि संक्षिप्त पंक्ति पूरे रूप से मिले और पूरा रूप संक्षिप्त से।',
  'What is this part, do we already hold it under any name in any CPSE, and what is its national code. A barcode, a bin label, a GTIN or a part number all resolve here.':
    'यह पुर्ज़ा क्या है, क्या यह किसी CPSE में किसी नाम से पहले से है, और इसका राष्ट्रीय कोड क्या है। बारकोड, बिन लेबल, GTIN या पार्ट नंबर — सब यहाँ हल होते हैं।',
  'Check a description against the national catalogue before raising a new material code. The same matcher, veto layer and evidence the pipeline uses, applied one record early.':
    'नया मटीरियल कोड बनाने से पहले विवरण को राष्ट्रीय कैटलॉग से जाँचें। वही मैचर, वीटो परत और साक्ष्य, एक रिकॉर्ड पहले लागू।',
  'Harmonization progress across CPSEs. Every figure is computed from the database and reconciles with /api/metrics.':
    'CPSEs में समरूपीकरण की प्रगति। हर आँकड़ा डेटाबेस से गणना किया गया है और /api/metrics से मेल खाता है।',
  'Aggregation candidates, price variance per base unit, and stock that could move instead of being bought.':
    'संयुक्त खरीद के उम्मीदवार, प्रति आधार इकाई मूल्य-भिन्नता, और वह स्टॉक जो खरीदने के बजाय स्थानांतरित हो सकता है।',
  'Every mutation as a hash-chained event. Each hash covers its own sequence number, so the chain detects reordering as well as tampering.':
    'हर परिवर्तन एक हैश-श्रृंखलित घटना। हर हैश अपने क्रम-संख्या को भी ढकता है, इसलिए श्रृंखला छेड़छाड़ के साथ पुनर्क्रमण भी पकड़ती है।',
  'Users and roles, sovereign mode, and which engine is live in each tier.':
    'उपयोगकर्ता और भूमिकाएँ, सॉवरेन मोड, और हर स्तर पर कौन-सा इंजन चल रहा है।',
  'Upload a catalogue, confirm how its columns map, review a dry run, then ingest and run the pipeline.':
    'कैटलॉग अपलोड करें, स्तंभों की मैपिंग पुष्ट करें, ड्राई रन देखें, फिर इनजेस्ट कर पाइपलाइन चलाएँ।',
  'Ask about the material master in plain language. Answers cite their sources and show the query behind them; free-form SQL is never generated or run.':
    'मटीरियल मास्टर के बारे में सादी भाषा में पूछें। उत्तर अपने स्रोत बताते हैं और पीछे की क्वेरी दिखाते हैं; मुक्त SQL कभी नहीं बनती या चलती।',
  'Any two rows, scored now by the same matcher the pipeline uses. Nothing is stored or decided here.':
    'कोई भी दो पंक्तियाँ, उसी मैचर से अभी स्कोर की गईं जिसे पाइपलाइन उपयोग करती है। यहाँ कुछ भी संग्रहीत या तय नहीं होता।',
  'Interchangeable parts the pipeline found, with the equipment they touch. A technical authority approves each one, with a reason, before it may be fitted.':
    'पाइपलाइन को मिले विनिमेय पुर्ज़े, उन उपकरणों के साथ जिन्हें वे छूते हैं। लगाने से पहले एक तकनीकी प्राधिकारी हर एक को कारण सहित मंज़ूर करता है।',
  'Find what two CPSEs have in common without either handing over a catalogue. Each side encodes its own descriptions locally; only the encodings are compared.':
    'दो CPSEs में क्या समान है, बिना किसी के कैटलॉग सौंपे। हर पक्ष अपने विवरण स्थानीय रूप से एनकोड करता है; केवल एनकोडिंग की तुलना होती है।',
  'Write the CNMC cross-reference into the material master. A record with open transactions is held; a superseded material is blocked, never deleted; every batch can be rolled back.':
    'CNMC क्रॉस-रेफ़रेंस मटीरियल मास्टर में लिखें। खुले लेनदेन वाला रिकॉर्ड रोका जाता है; प्रतिस्थापित मटीरियल अवरुद्ध होता है, कभी हटाया नहीं; हर बैच वापस लौटाया जा सकता है।',
  'A QR for a phone, a Code 128 for a barcode gun, and every name the material goes by. Stick it on the bin.':
    'फ़ोन के लिए QR, बारकोड गन के लिए Code 128, और मटीरियल के सारे नाम। इसे बिन पर चिपकाएँ।',
  'Two rows, side by side.': 'दो पंक्तियाँ, आमने-सामने।',
  'Loading…': 'लोड हो रहा है…',
  'Unavailable.': 'उपलब्ध नहीं।',
  // workbench
  'Auto-high': 'स्वतः-उच्च',
  Grey: 'धूसर',
  'Auto-low': 'स्वतः-निम्न',
  Approve: 'स्वीकृत',
  Reject: 'अस्वीकृत',
  'Open cluster': 'क्लस्टर खोलें',
  Undo: 'पूर्ववत',
  'Assigned to me': 'मुझे सौंपे गए',
  'All classes': 'सभी वर्ग',
  'All CPSEs': 'सभी CPSE',
  'Clear filters': 'फ़िल्टर हटाएँ',
  'Most informative first': 'सबसे जानकारीपूर्ण पहले',
  'Nothing left in this band': 'इस बैंड में कुछ नहीं बचा',
  'Reload queue': 'कतार फिर लोड करें',
  'Issue CNMC': 'CNMC जारी करें',
  'Decide this page': 'यह पृष्ठ तय करें',
  // scan
  'Look up': 'खोजें',
  'Stock count': 'स्टॉक गिनती',
  Code: 'कोड',
  'Scan the bin label or the part': 'बिन लेबल या पुर्ज़ा स्कैन करें',
  'Type a code, or point a barcode scanner here and pull the trigger.':
    'कोड टाइप करें, या बारकोड स्कैनर यहाँ रखकर ट्रिगर दबाएँ।',
  'Scan with the camera': 'कैमरे से स्कैन करें',
  'Photograph the marking': 'मार्किंग की फ़ोटो लें',
  'Counted quantity': 'गिनी गई मात्रा',
  'Record & next': 'दर्ज करें और अगला',
  'Recent scans on this device': 'इस डिवाइस पर हाल के स्कैन',
  'Wrong item? The part in hand is not this one': 'गलत वस्तु? हाथ में यह पुर्ज़ा नहीं है',
  'Open the full record': 'पूरा रिकॉर्ड खोलें',
  'Print a label': 'लेबल छापें',
  'system says': 'सिस्टम कहता है',
  // sign-in and shell
  'Sign in': 'साइन इन',
  'Sign out': 'साइन आउट',
  'Sign in as': 'इस रूप में साइन इन करें',
  Password: 'पासवर्ड',
  'Search SAMAN': 'SAMAN में खोजें',
  'Ask SAMAN': 'SAMAN से पूछें',
  'Keyboard shortcuts': 'कीबोर्ड शॉर्टकट',
  'Skip to content': 'सामग्री पर जाएँ',
}

type LangValue = { lang: Lang; setLang: (l: Lang) => void; t: (s: string) => string }

const LangContext = createContext<LangValue>({ lang: 'en', setLang: () => {}, t: (s) => s })

function readLang(): Lang {
  try {
    return localStorage.getItem(KEY) === 'hi' ? 'hi' : 'en'
  } catch {
    return 'en'
  }
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => readLang())
  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* the choice still holds for this tab */
    }
  }, [])
  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])
  const t = useCallback((s: string) => (lang === 'hi' ? (HI[s] ?? s) : s), [lang])
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

export function useLang(): LangValue {
  return useContext(LangContext)
}

/** `t` alone, for components that only read. */
export function useT(): (s: string) => string {
  return useContext(LangContext).t
}

export const HINDI_STRINGS = Object.keys(HI).length
