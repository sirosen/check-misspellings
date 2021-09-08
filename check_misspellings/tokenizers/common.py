import re
import uuid
_URI_RE_S = r"https?\:\/\/\w+\.\w+(\.\w+)*\/[^\s]*"

HAS_URI_SCHEME_REGEX = re.compile(r"^https?\:\/\/")
HEX_COLOR_REGEX = re.compile(r"#([0-9a-f]{6}|[0-9a-f]{3})")
IS_DOMAIN_REGEX = re.compile(r"\.(org|net|com|us|co\.uk|io)$")
NON_WORDSTR_REGEX = re.compile(r"^[^\w]+$")
SUBTOKENIZE_TEXT_SPLIT_REGEX = re.compile(r"[_\-]")
URI_REGEX = re.compile(_URI_RE_S)
CAPTURING_URI_REGEX = re.compile("(" + _URI_RE_S + ")")
DISABLE_COMMENT_REGEX = re.compile(r"check\-misspellings\s*:\s*off")
ENABLE_COMMENT_REGEX = re.compile(r"check\-misspellings\s*:\s*on")


def should_skip_token(tok, context):
    if tok == "":
        return True
    if len(tok) < context.min_word_length:
        return True

    # skip any values which match these non-text types
    try:
        float(tok)
        return True
    except ValueError:
        pass
    try:
        uuid.UUID(tok)
        return True
    except ValueError:
        pass

    if HEX_COLOR_REGEX.fullmatch(tok):
        return True
    if HAS_URI_SCHEME_REGEX.match(tok):
        return True
    if IS_DOMAIN_REGEX.match(tok):
        return True
    if NON_WORDSTR_REGEX.match(tok):
        return True

    return False
