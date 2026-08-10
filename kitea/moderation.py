"""Lightweight abuse/obscenity filter — stdlib only (no dependency allowed).

The site is a public, live demo: any free-text a visitor submits (report
descriptions, offers of help, simulated staff updates) passes through
`check()` first, and abusive text is rejected rather than stored.

Approach: normalise the text (lowercase, undo common leetspeak, merge
letter-spaced obfuscation like "f u c k", collapse repeated characters)
and match a compact wordlist on WORD BOUNDARIES — the same collapse is
applied to the wordlist so "fuuuuck" matches "fuck". Boundary matching
avoids the Scunthorpe problem: legitimate words that merely contain a
flagged substring (class, assess, Scunthorpe, push it) are not flagged.
This is a demo-grade guard, not a moderation platform; a pilot would use
a maintained service.
"""

from __future__ import annotations

import re

# Compact, deliberately-obvious set: strong profanity and slurs. Matched
# whole-word after normalisation. Not exhaustive by design.
_TERMS = {
    "fuck", "shit", "bitch", "cunt", "asshole", "bastard", "dick", "piss",
    "slut", "whore", "wanker", "bollocks", "prick", "twat", "motherfucker",
    "faggot", "nigger", "nigga", "retard", "spastic", "coon", "chink",
    "paki", "kike", "tranny", "dyke", "kill yourself", "kys",
}

_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
    "9": "g", "@": "a", "$": "s", "!": "i", "|": "i",
})

_COLLAPSE = re.compile(r"(.)\1+")       # any run of a char -> one
_NONLETTER = re.compile(r"[^a-z ]+")
_SINGLE_RUN = re.compile(r"\b(?:[a-z] ){2,}[a-z]\b")  # "f u c k" -> merge
_MULTISPACE = re.compile(r"\s+")


def _collapse(s: str) -> str:
    return _COLLAPSE.sub(r"\1", s)


# collapsed single-word terms (fuuuck -> fuck matches; bollocks -> bolocks)
_WORD_TERMS = {_collapse(t) for t in _TERMS if " " not in t}
_PHRASE_TERMS = {t for t in _TERMS if " " in t}


def _normalise(text: str) -> str:
    t = text.lower().translate(_LEET)
    t = _NONLETTER.sub(" ", t)
    t = _MULTISPACE.sub(" ", t).strip()
    # merge letter-spaced obfuscation: "f u c k" -> "fuck"
    t = _SINGLE_RUN.sub(lambda m: m.group(0).replace(" ", ""), t)
    return t


def check(text: str) -> tuple[bool, str | None]:
    """Return (ok, reason). ok is False when abusive language is detected;
    `reason` is a short, user-facing message when not ok.
    """
    if not text:
        return True, None
    norm = _normalise(text)
    for phrase in _PHRASE_TERMS:
        if phrase in norm:
            return False, "offensive language"
    for tok in norm.split():
        c = _collapse(tok)
        if c in _WORD_TERMS:
            return False, "offensive language"
        # inflected forms: fuck->fucking/fucker/fucked, bitch->bitching.
        # Strip a common suffix and re-test against the exact term set;
        # this stays whole-word (no mid-word substring), so legitimate
        # words like "pushing"->"push" or "assessing"->"assess" are safe.
        for suf in ("ing", "ers", "er", "ed", "in", "y", "s"):
            if len(c) > len(suf) + 2 and c.endswith(suf) and c[:-len(suf)] in _WORD_TERMS:
                return False, "offensive language"
    return True, None


def is_clean(text: str) -> bool:
    return check(text)[0]
