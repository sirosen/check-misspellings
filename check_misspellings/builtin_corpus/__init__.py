from .known_env_vars import KNOWN_ENV_VARS
from .language_terms import (
    BASH_TERMS,
    C_TERMS,
    JAVA_TERMS,
    JS_TERMS,
    MARKDOWN_TERMS,
    RUBY_TERMS,
)
from .os_terms import LINUX_TERMS, MACOS_TERMS, UNIX_TERMS
from .proper_nouns import PROPER_NOUNS
from .python_terms import PYTHON_TERMS
from .scowl_wordlist import SCOWL_CORPUS
from .software_terms import SOFTWARE_TERMS
from .web_terms import HTML_TERMS, HTTP_TERMS, SSL_TERMS

# these additions aren't part of any software-specific set of words
# they're just common (valid?) usages which don't appear in the SCOWL list
BASE_CORPUS_ADDITIONS = [
    "another's",
    "unintuitively",
]

FULL_CORPUS = (
    SCOWL_CORPUS
    + BASE_CORPUS_ADDITIONS
    + HTML_TERMS
    + HTTP_TERMS
    + C_TERMS
    + JAVA_TERMS
    + JS_TERMS
    + SSL_TERMS
    + KNOWN_ENV_VARS
    + LINUX_TERMS
    + MACOS_TERMS
    + MARKDOWN_TERMS
    + PROPER_NOUNS
    + PYTHON_TERMS
    + RUBY_TERMS
    + BASH_TERMS
    + SOFTWARE_TERMS
    + UNIX_TERMS
)
