import re

from .common import (
    CAPTURING_URI_REGEX,
    DISABLE_COMMENT_REGEX,
    ENABLE_COMMENT_REGEX,
    HAS_URI_SCHEME_REGEX,
    should_skip_token,
)

TEXT_WORD_REGEX = re.compile(
    r"""
    (\#[0-9a-f]{6}(?!\w))   # 6-letter hex colors
    | (\#[0-9a-f]{3}(?!\w)) # 3-letter hex colors
    | ([\w\-\\']+)          # normal words
    """,
    re.VERBOSE,
)


def tokenize_text_line(line):
    # skip URIs by splitting on them, then word-matching on the remaining parts
    offset = 0
    for chunk in CAPTURING_URI_REGEX.split(line):
        if chunk is None:
            continue
        if not HAS_URI_SCHEME_REGEX.match(chunk):
            for match in TEXT_WORD_REGEX.finditer(chunk):
                yield match.start() + offset, match.group()
        offset += len(chunk)


def textfile_token_stream(filename, context):
    # capture URIs or words (URIs are common in, e.g., bash scripts)
    # accept hex colors, if only to rule them out
    # important: include `\\` so that we can handle `\n` or `\t`
    subtokenize_regex = re.compile(r"\\(n|r|t)")

    enabled = True

    with open(filename) as f:
        for lineno, line in enumerate(f):
            if not enabled:
                if ENABLE_COMMENT_REGEX.search(line):
                    enabled = True
                continue
            if DISABLE_COMMENT_REGEX.search(line):
                enabled = False
                continue

            # convert to 4-ist spacing for consistent printing later on
            line = line.replace("\t", "    ")
            for start_pos, token in tokenize_text_line(line):
                if should_skip_token(token, context):
                    continue

                offset = 0
                for st in subtokenize_regex.split(token):
                    # strip leading and trailing escapes (which were captured
                    # by the word regex above) or leading and trailing
                    # quotation marks
                    #
                    # while so doing, keep the current offset accurate for the
                    # current word and make sure that the future offset (for
                    # the next word) will be correct as well
                    while st.startswith("\\") or st.startswith("'"):
                        st = st[1:]
                        offset += 1
                    add_to_offset = len(st) + 1
                    while st.endswith("\\") or st.endswith("'"):
                        st = st[:-1]
                    if not should_skip_token(st, context):
                        yield st, line, lineno + 1, start_pos + offset
                    offset += add_to_offset
