"""Security guards around the LLM: what goes in (questions, sources) and what comes out (answers).

Retrieved text is untrusted: anyone who can get a document into the corpus can
write words the model will read. Four deterministic layers, each measured in
docs/18-security-prompt-injection.md against real attacks on the real model:

1. clean_question: reject control characters (a NUL byte crashed Postgres with
   a 500) and strip invisible format characters (zero-width, bidi overrides).
2. fence_source: each source sits inside <source id="n"> … </source>, and any
   text in the source that imitates that fence or our "[n] Company 2022 Form
   10-K" header is defused, so a document can't close its own fence or pose
   as a different, trusted source.
3. injection_signals: phrases that address the model rather than an investor
   ("ignore previous instructions", "reply with INSUFFICIENT_CONTEXT", a
   markdown image). A source that trips one is dropped before the prompt.
4. enforce_output_policy: the answer may not contain links or images. A 10-K
   answer never needs one, and a link or image the model was talked into
   writing is how injected text phishes the reader or leaks the question.

None of this makes injection impossible; layer 3 is a pattern list that a
paraphrase evades. Layers 2 and 4 are the ones that hold regardless of what
the model decides, which is why the measurements report them separately.
"""

import re
import unicodedata
from dataclasses import dataclass

ALLOWED_CONTROL = {"\n", "\t", "\r"}


def clean_question(text: str) -> str:
    """Reject control characters; drop invisible format characters (Unicode category Cf)."""
    bad = sorted({f"U+{ord(ch):04X}" for ch in text
                  if unicodedata.category(ch) == "Cc" and ch not in ALLOWED_CONTROL})
    if bad:
        raise ValueError(f"control characters are not allowed: {', '.join(bad)}")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


# --- fencing ------------------------------------------------------------------------------------

FENCE_TAG = re.compile(r"<\s*(/?)\s*(source|sources|question|system|instructions)\b", re.IGNORECASE)
# A line that looks like the header we put above each source: "[3] AMD 2022 Form 10-K · page 7 · …"
FORGED_HEADER = re.compile(r"^(\s*)\[(\d+)\](?=[^\n]*\b(?:10-K|page|Form)\b)", re.IGNORECASE | re.MULTILINE)


def defuse(text: str) -> tuple[str, int]:
    """Neutralise fence tags and forged source headers inside a source; returns (text, number of edits).

    "<" becomes "‹" only inside a fence-like tag, and "[3]" at the start of a
    header-like line becomes "(3)". Ordinary 10-K text is unchanged: no chunk
    in our corpus contains either pattern (measured over all 7,411 chunks).
    """
    text, n_tags = FENCE_TAG.subn(lambda m: "‹" + m.group(1) + m.group(2), text)
    text, n_headers = FORGED_HEADER.subn(lambda m: f"{m.group(1)}({m.group(2)})", text)
    return text, n_tags + n_headers


def fence_source(n: int, header: str, text: str) -> str:
    return f'<source id="{n}">\n{header}\n{text}\n</source>'


# --- detection ----------------------------------------------------------------------------------

INJECTION_PATTERNS = {
    "override": re.compile(r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|"
                           r"these|your|the)\b[^.\n]{0,20}\b(?:instructions?|rules?|prompts?|directions?)\b", re.I),
    "addresses_model": re.compile(r"\b(?:assistant|AI model|language model|LLM|chatbot)\b[^.\n]{0,40}\b(?:must|should|"
                                  r"shall|will|needs? to|is instructed)\b", re.I),
    "role_marker": re.compile(r"(?:^|\n)\s*(?:system|assistant|user|developer)\s*(?:prompt|message|note)?\s*:", re.I),
    "system_prompt": re.compile(r"\b(?:system prompt|system override|new instructions?|jailbreak)\b", re.I),
    "refusal_token": re.compile(r"\bINSUFFICIENT_CONTEXT\b"),
    "markdown_image": re.compile(r"!\[[^\]]*\]\("),
    "respond_with": re.compile(r"\b(?:respond|reply|answer|begin your (?:answer|response))\b[^.\n]{0,30}\b(?:with|by "
                               r"saying|exactly|only)\b[^.\n]{0,10}[\"'“‘]", re.I),
}


def injection_signals(text: str) -> list[str]:
    """Names of the patterns that fire on this text (empty for ordinary filing text)."""
    return [name for name, rx in INJECTION_PATTERNS.items() if rx.search(text)]


# --- output policy ------------------------------------------------------------------------------

MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?:|www\.|//)[^)]*\)")
URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)
HTML_TAG = re.compile(r"<\s*(?:img|a|script|iframe)\b[^>]*>", re.IGNORECASE)


@dataclass(frozen=True)
class OutputCheck:
    text: str
    images_removed: int
    links_removed: int


def enforce_output_policy(answer: str) -> OutputCheck:
    """Remove images, links, raw URLs and HTML tags from an answer; count what was removed."""
    text, n_img = MD_IMAGE.subn("", answer)
    text, n_html = HTML_TAG.subn("", text)
    text, n_mdlink = MD_LINK.subn(lambda m: m.group(1), text)   # keep the link text, drop the target
    text, n_url = URL.subn("[link removed]", text)
    return OutputCheck(text, n_img + n_html, n_mdlink + n_url)


class StreamingOutputFilter:
    """Apply the output policy to a token stream without letting a link or image reach the client.

    Text is released only up to the last whitespace (a URL never contains
    whitespace, so it is always whole when checked), and never past an
    unclosed "![" or "<" (an image's alt text can contain spaces). The final
    answer event still carries the fully cleaned text; this only guarantees
    that the streamed deltas never contain what the policy removes.
    """

    def __init__(self):
        self.pending = ""
        self.images_removed = 0
        self.links_removed = 0

    def _safe_end(self) -> int:
        end = max(self.pending.rfind(" "), self.pending.rfind("\n")) + 1
        for opener, closer in (("![", ")"), ("<", ">")):
            i = self.pending.rfind(opener, 0, end)
            if i != -1 and self.pending.find(closer, i) == -1:
                end = min(end, i)
        return end

    def _release(self, text: str) -> str:
        check = enforce_output_policy(text)
        self.images_removed += check.images_removed
        self.links_removed += check.links_removed
        return check.text

    def feed(self, delta: str) -> str:
        self.pending += delta
        end = self._safe_end()
        out, self.pending = self.pending[:end], self.pending[end:]
        return self._release(out) if out else ""

    def flush(self) -> str:
        out, self.pending = self.pending, ""
        return self._release(out) if out else ""
