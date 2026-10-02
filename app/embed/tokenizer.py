"""The embedding model's own tokenizer, used to measure chunk sizes.

Chunk sizes are counted in *these* tokens — not characters, not LLM tokens —
because the embedding model is what silently truncates input past its limit.
"""

from functools import lru_cache

from transformers import AutoTokenizer, PreTrainedTokenizerFast

from app.config import get_settings


@lru_cache(maxsize=1)
def get_tokenizer() -> PreTrainedTokenizerFast:
    s = get_settings()
    tokenizer = AutoTokenizer.from_pretrained(
        s.embedding_model, revision=s.embedding_model_revision, cache_dir=s.model_cache_dir
    )
    # We tokenize whole documents to get offsets; this only silences the
    # "sequence longer than 512" warning — nothing is fed to the model here.
    tokenizer.model_max_length = 10**9
    return tokenizer


def count_tokens(text: str) -> int:
    """Content tokens, excluding the [CLS]/[SEP] the model adds around every input."""
    return len(get_tokenizer()(text, add_special_tokens=False)["input_ids"])


def token_spans(text: str) -> list[tuple[int, int]]:
    """Character [start, end) of every content token — the bridge from token
    windows back to character offsets."""
    enc = get_tokenizer()(text, add_special_tokens=False, return_offsets_mapping=True)
    return [tuple(span) for span in enc["offset_mapping"]]
