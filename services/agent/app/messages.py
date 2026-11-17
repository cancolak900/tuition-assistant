"""Fixed texts the agent writes itself (payment results), in the language of the conversation.

Payment outcomes are never worded by the LLM, so it cannot claim a payment that did not happen.
Supported: English (default) and Turkish.
"""

import re

TURKISH_CHARS = set("çğıöşüÇĞİÖŞÜ")
TURKISH_WORDS = re.compile(
    r"\b(ne|nedir|neden|nasıl|kaç|zaman|mı|mi|mu|mü|var|yok|ve|ile|için|borç\w*|borc\w*|bakiye\w*|öde\w*|ode\w*|dolar|lira|taksit\w*|"
    r"burs\w*|dönem\w*|donem\w*|harç\w*|harc\w*|ücret\w*|ucret\w*|merhaba|lütfen|lutfen|evet|hayır|teşekkür\w*|tesekkur\w*)\b",
    re.IGNORECASE,
)
ENGLISH_WORDS = re.compile(r"\b(the|what|when|how|is|my|pay|balance|can|i|please|tuition|deadline|fee)\b", re.IGNORECASE)

TEXTS = {
    "en": {
        "cancelled": "Payment cancelled. Nothing was paid for {term}.",
        "success": "Payment successful: {amount} {currency} for {term}. Remaining balance: {balance} {currency}. Transaction id: {tx}.",
        "already": "This payment was already processed: {amount} {currency} for {term}. Remaining balance: {balance} {currency}. Transaction id: {tx}.",
        "unknown": "I could not reach the payment service, so I do not know yet if the payment went through. Press Confirm again; you will not be charged twice.",
        "failed": "The payment was not made: {reason}",
    },
    "tr": {
        "cancelled": "Ödeme iptal edildi. {term} için hiçbir ödeme yapılmadı.",
        "success": "Ödeme başarılı: {term} için {amount} {currency} ödendi. Kalan bakiye: {balance} {currency}. İşlem numarası: {tx}.",
        "already": "Bu ödeme daha önce işlenmişti: {term} için {amount} {currency}. Kalan bakiye: {balance} {currency}. İşlem numarası: {tx}.",
        "unknown": "Ödeme servisine ulaşamadım, bu yüzden ödemenin gerçekleşip gerçekleşmediğini henüz bilmiyorum. Onayla'ya tekrar basın; iki kez ödeme alınmaz.",
        "failed": "Ödeme yapılmadı: {reason}",
    },
}


def detect_language(text: str) -> str | None:
    """'tr', 'en', or None when the message gives no clear signal (then the session keeps its language)."""
    if any(ch in TURKISH_CHARS for ch in text):
        return "tr"
    tr, en = len(TURKISH_WORDS.findall(text)), len(ENGLISH_WORDS.findall(text))
    if tr > en:
        return "tr"
    if en > tr:
        return "en"
    return None


def text(language: str, key: str, **values: str) -> str:
    return TEXTS.get(language, TEXTS["en"])[key].format(**values)
