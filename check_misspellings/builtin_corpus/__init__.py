from .html_terms import HTML_TERMS
from .http_terms import HTTP_TERMS
from .known_env_vars import KNOWN_ENV_VARS
from .language_terms import (
    JAVA_TERMS,
    JS_TERMS,
    MARKDOWN_TERMS,
    PYTHON_TERMS,
    RUBY_TERMS,
)
from .os_terms import MACOS_TERMS
from .proper_nouns import PROPER_NOUNS
from .scowl_wordlist import SCOWL_CORPUS
from .software_terms import SOFTWARE_TERMS
from .unix_terms import UNIX_TERMS

FULL_CORPUS = (
    SCOWL_CORPUS
    + HTML_TERMS
    + HTTP_TERMS
    + JAVA_TERMS
    + JS_TERMS
    + KNOWN_ENV_VARS
    + MACOS_TERMS
    + MARKDOWN_TERMS
    + PROPER_NOUNS
    + PYTHON_TERMS
    + RUBY_TERMS
    + SOFTWARE_TERMS
    + UNIX_TERMS
)
