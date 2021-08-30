from .common import SUBTOKENIZE_TEXT_SPLIT_REGEX, should_skip_token
from .py_tok import pyfile_token_stream
from .text_tok import textfile_token_stream

# ordered mapping of tags to tokenizers
TOKENIZER_MAPPING = [
    ("python", pyfile_token_stream),
    ("text", textfile_token_stream),
]


__all__ = (
    "SUBTOKENIZE_TEXT_SPLIT_REGEX",
    "TOKENIZER_MAPPING",
    "should_skip_token",
)
