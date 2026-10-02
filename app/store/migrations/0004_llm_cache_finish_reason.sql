-- 0004: remember why a cached response ended. Gemini 3.x Flash counts hidden
-- "thinking" tokens against max_tokens, so an answer can be cut off
-- (finish_reason = 'length'); a cache hit must still report it as truncated.
ALTER TABLE llm_cache ADD COLUMN finish_reason text;
