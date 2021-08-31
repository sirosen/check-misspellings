import re
import tokenize

from .common import should_skip_token

DISABLE_COMMENT_PY_REGEX = re.compile(r"#\s*check\-misspellings\s*:\s*off")
SUBTOKENIZE_PY_SPLIT_REGEX = re.compile(r"[^\w'\"]")

PYTHON_LETTER_QUOTE_PREFIXES = [
    f"{x}{y}" for x in ["r", "u", "b", "f"] for y in ["'", '"']
]


def subtokenize_py_token(token_str, context):
    if should_skip_token(token_str, context):
        return
    if should_skip_token(token_str.strip("'\""), context):
        return

    for lineno, subtoken_line in enumerate(token_str.split("\n")):
        subtokens = SUBTOKENIZE_PY_SPLIT_REGEX.split(subtoken_line)
        offset = 0
        for st in subtokens:
            add_offset = len(st) + 1

            # trim trailing and leading quotes, including 'r"', 'u"', etc
            while any(st.startswith(x) for x in PYTHON_LETTER_QUOTE_PREFIXES):
                st = st[2:]
                offset += 2
            while st.startswith('"') or st.startswith("'"):
                st = st[1:]
                offset += 1
            while st.endswith('"') or st.endswith("'"):
                st = st[:-1]

            if not should_skip_token(st, context):
                yield st, offset, lineno
            offset += add_offset


def pyfile_token_stream(filename, context):
    with open(filename, "rb") as fp:
        for token in tokenize.tokenize(fp.readline):
            token_ty, token_str, startpos, endpos, line = token
            if DISABLE_COMMENT_PY_REGEX.search(line):  # skip disabled lines
                continue

            for subtoken, col_offset, line_offset in subtokenize_py_token(
                token_str, context
            ):
                lineno, pos = startpos
                yield (
                    subtoken,
                    line.split("\n")[line_offset],
                    lineno,
                    (pos if line_offset == 0 else 0) + col_offset,
                )
