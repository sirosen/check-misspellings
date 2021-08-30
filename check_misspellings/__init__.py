#!/usr/bin/env python
import argparse
import difflib
import re
import sys
import tokenize
import unicodedata
import uuid

from identify import identify

from .builtin_corpus import FULL_CORPUS

# experimentally found cutoffs which match letter inversions
# easily but have minimal incorrect matches
LENGTH_BASED_SIMILARITY_CUTOFFS = (
    (4, 0.825),
    (10, 0.85),
)
SUBTOKENIZE_PY_SPLIT_REGEX = re.compile(r"[^\w'\"]")
SUBTOKENIZE_TEXT_SPLIT_REGEX = re.compile(r"[_\-]")
CAMEL_AND_TITLE_CASE_ITER_REGEX = re.compile(r"(^|[A-Z])[^A-Z]+")
NON_WORDSTR_REGEX = re.compile(r"^[^\w]+$")
DISABLE_COMMENT_REGEX = re.compile(r"check\-misspellings\s*:\s*off")
ENABLE_COMMENT_REGEX = re.compile(r"check\-misspellings\s*:\s*on")
DISABLE_COMMENT_PY_REGEX = re.compile(r"#\s*check\-misspellings\s*:\s*off")
HAS_URI_SCHEME_REGEX = re.compile(r"^https?\:\/\/")
IS_DOMAIN_REGEX = re.compile(r"\.(org|net|com|us|co\.uk|io)$")
TRAILING_DIGIT_REGEX = re.compile(r"\d+$")
HEX_COLOR_REGEX = re.compile(r"#([0-9a-f]{6}|[0-9a-f]{3})")
URI_REGEX = re.compile(r"https?\:\/\/\w+\.\w+(\.\w+)*\/[^\s]*")
TEXT_WORD_REGEX = re.compile(
    r"""
    (\#[0-9a-f]{6}(?!\w))   # 6-letter hex colors
    | (\#[0-9a-f]{3}(?!\w)) # 3-letter hex colors
    | ([\w\-\\']+)          # normal words
    """,
    re.VERBOSE,
)
PYTHON_LETTER_QUOTE_PREFIXES = [
    f"{x}{y}" for x in ["r", "u", "b", "f"] for y in ["'", '"']
]


class _Settings:
    def __init__(self):
        self.min_word_length = 4
        self.ascii_ize = True
        self.verbose = False
        self.failfast = False
        self.show_not_in_corpus = False
        self.show_all_matches = False

        # shared cache
        self.non_error_non_corpus_words = set()
        # keyed by word
        self.found_error_locations = {}
        self.found_error_matches = {}

    def set_args(self, args):
        self.min_word_length = args.min_word_len
        self.ascii_ize = args.ascii_ize
        self.verbose = args.verbose
        self.failfast = args.failfast
        self.show_not_in_corpus = args.show_not_in_corpus
        self.show_all_matches = args.show_all_matches


SETTINGS = _Settings()


_SAVED_CORPUS_SLICES = {}


def _slice_corpus_to_size(corpus, size):
    if size not in _SAVED_CORPUS_SLICES:
        _SAVED_CORPUS_SLICES[size] = set(x for x in corpus if len(x) == size)
    return _SAVED_CORPUS_SLICES[size]


def lengthmapped_corpus(corpus, upperbound=15):
    # split a corpus into chunks by length, so that we can do more efficient
    # matching by only trying to match words against appropriate length words
    # the keys are the lengths of words to be matches, and the values are
    # slices of the original corpus

    # special: 0 for 'whole corpus'
    lengthmap = {0: corpus}
    # start at 2 -- words of length 1 will never match anything
    for i in range(2, upperbound):
        lengthmap[i] = set()
        for j in range(2, upperbound * 2):
            # bound by the real_quick_ratio used in difflib
            # if this is not above the minimum cutoff, the words cannot
            # possibly match
            if ((2 * min(i, j)) / (i + j)) >= 0.8:
                lengthmap[i] = lengthmap[i] | _slice_corpus_to_size(corpus, j)
    return lengthmap


def corpus_for_token(token, lengthmap):
    n = len(token)
    if n in lengthmap:
        return lengthmap[n]
    return lengthmap[0]


def should_skip_token(tok):
    if tok == "":
        return True
    if len(tok) < SETTINGS.min_word_length:
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


def should_skip_file(filename, tags):
    if "symlink" in tags:
        return True
    if "binary" in tags:
        return True
    if "directory" in tags:
        return True
    return False


def subtokenize_py_token(token_str):
    if should_skip_token(token_str):
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

            if not should_skip_token(st):
                yield st, offset, lineno
            offset += add_offset


def pyfile_token_stream(filename):
    with open(filename, "rb") as fp:
        for token in tokenize.tokenize(fp.readline):
            token_ty, token_str, startpos, endpos, line = token
            if DISABLE_COMMENT_PY_REGEX.search(line):  # skip disabled lines
                continue

            for subtoken, col_offset, line_offset in subtokenize_py_token(token_str):
                lineno, pos = startpos
                yield (
                    subtoken,
                    line.split("\n")[line_offset],
                    lineno,
                    (pos if line_offset == 0 else 0) + col_offset,
                )


def check_python_file(filename, lengthmap):
    return check_tokenstream(filename, pyfile_token_stream(filename), lengthmap)


def tokenize_text_line(line):
    # skip URIs by splitting on them, then word-matching on the remaining parts
    offset = 0
    for chunk in URI_REGEX.split(line):
        if chunk is None:
            continue
        if not HAS_URI_SCHEME_REGEX.match(chunk):
            for match in TEXT_WORD_REGEX.finditer(chunk):
                yield match.start() + offset, match.group()
        offset += len(chunk)


def textfile_token_stream(filename):
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
                if should_skip_token(token):
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
                    if not should_skip_token(st):
                        yield st, line, lineno + 1, start_pos + offset
                    offset += add_to_offset


def check_text_file(filename, lengthmap):
    return check_tokenstream(filename, textfile_token_stream(filename), lengthmap)


def _title(s):
    # don't use '.title()' because on "foo's" it produces "Foo'S"
    if not s:
        return s
    return s[0].upper() + s[1:]


def _case_insensitive_str_in_corpus(s, corpus):
    return s in corpus or s.lower() in corpus or _title(s) in corpus


def token_in_corpus(token, corpus, full_corpus):
    if _case_insensitive_str_in_corpus(token, corpus):
        return True

    # check for "myfoo" where "foo" is in the corpus, as this is a
    # common/classic way of writing examples
    if token.lower().startswith("my") and _case_insensitive_str_in_corpus(
        token[2:], full_corpus
    ):
        return True

    # allow loose hyphenate and '_'-separation handling
    # "one-time" matches "onetime"
    # "single-use" matches "single", "use"
    if "-" in token or "_" in token:
        if _case_insensitive_str_in_corpus(
            token.replace("-", "").replace("_", ""), corpus
        ):
            return True
        if all(
            (_case_insensitive_str_in_corpus(x, full_corpus) or should_skip_token(x))
            for x in SUBTOKENIZE_TEXT_SPLIT_REGEX.split(token)
        ):
            return True
    # check camelCase and TitleCase words
    if all(
        (
            _case_insensitive_str_in_corpus(m.group(0), full_corpus)
            or should_skip_token(m.group(0))
        )
        for m in CAMEL_AND_TITLE_CASE_ITER_REGEX.finditer(token)
    ):
        return True
    # check to see if the token is in the corpus when trailing digits are
    # removed, e.g. 'project1, project2' match 'project'
    trailing_digits = TRAILING_DIGIT_REGEX.search(token)
    if trailing_digits:
        if _case_insensitive_str_in_corpus(token[: trailing_digits.start()], corpus):
            return True
    return False


def get_cutoff_for_token(tok):
    n = len(tok)
    last = 0.88
    for (x, y) in LENGTH_BASED_SIMILARITY_CUTOFFS:
        if n >= x:
            last = y
    return last


def check_tokenstream(filename, tokens, lengthmap):
    full_corpus = lengthmap[0]
    for token, line, lineno, pos in tokens:
        location_item = (token, line.rstrip("\n"), pos, lineno)

        current_corpus = corpus_for_token(token, lengthmap)
        if token_in_corpus(token, current_corpus, full_corpus):
            continue
        if token in SETTINGS.non_error_non_corpus_words:
            continue
        if token in SETTINGS.found_error_matches:
            if filename not in SETTINGS.found_error_locations:
                SETTINGS.found_error_locations[filename] = []
            SETTINGS.found_error_locations[filename].append(location_item)
            continue

        if SETTINGS.show_not_in_corpus:
            print(f"non-corpus word: {token}")

        failed = False
        matches = difflib.get_close_matches(
            token, current_corpus, cutoff=get_cutoff_for_token(token)
        )
        # re-check lowercase version of the word when there are no matches
        if not matches and token != token.lower():
            matches = difflib.get_close_matches(
                token.lower(), current_corpus, cutoff=get_cutoff_for_token(token)
            )
        if matches:
            SETTINGS.found_error_matches[token] = matches
            SETTINGS.found_error_locations[filename] = [location_item]
            failed = True
            if SETTINGS.failfast:
                return

        if not failed:
            SETTINGS.non_error_non_corpus_words.add(token)
    return


def print_file_errors(filename, errors):
    print("\033[1m" + filename + "\033[0m:")
    for token, line, pos, lineno in errors:
        matches = SETTINGS.found_error_matches[token]
        if SETTINGS.show_all_matches:
            message = f"'{token}' appears similar to {','.join(matches)}"
        else:
            message = f"'{token}' appears similar to {matches[0]}"
        lineprefix = "line {}: ".format(lineno)
        print(lineprefix + line)
        print(
            "\033[0;33m" + " " * (len(lineprefix) + pos) + "^-- " + message + "\033[0m"
        )


def parse_corpus(filenames):
    corpus = set(FULL_CORPUS)
    for filename in filenames:
        with open(filename) as fp:
            for line in fp:
                line = line.strip()
                if line.startswith("#") or line == "":
                    continue
                corpus.add(line)
    if SETTINGS.ascii_ize:
        normalized = set(
            (
                unicodedata.normalize("NFKD", word)
                .encode("ascii", "ignore")
                .decode("utf-8")
            )
            for word in corpus
        )
        corpus = corpus | normalized
    return lengthmapped_corpus(corpus)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        action="append",
        default=[],
        help=(
            "The path to a file containing newline-delimited known words. "
            "Comments (with '#') and empty lines are allowed in the corpus. "
            "This option may be passed multiple times."
        ),
    )
    parser.add_argument("-v", action="store_true", dest="verbose", default=False)
    parser.add_argument("--show-not-in-corpus", action="store_true", default=False)
    parser.add_argument(
        "--no-ascii-ize",
        action="store_false",
        default=True,
        dest="ascii_ize",
        help="Don't ASCII-encode the corpus words to allow ASCII-content "
        "to match non-ASCII data. This strips accents, etc.",
    )
    parser.add_argument("--failfast", action="store_true", default=False)
    parser.add_argument(
        "--min-word-len",
        type=int,
        default=4,
        help=(
            "Word similarity checking is much less accurate on shorter strings. "
            "To improve performance, skip checking words less than the minimum "
            "word length. [default=4]"
        ),
    )
    parser.add_argument(
        "--show-all-matches",
        default=False,
        action="store_true",
        help=("Show all of the best matches for a word, not just the best one"),
    )
    parser.add_argument("--exclude", action="append", help="Files to skip", default=[])
    parser.add_argument("files", nargs="+", help="Files to check.")
    args = parser.parse_args()
    SETTINGS.set_args(args)

    lengthmap = parse_corpus(args.corpus)

    for filename in args.files:
        if filename in args.exclude:
            continue
        if SETTINGS.verbose:
            print(f"check: {filename}")
        tags = identify.tags_from_path(filename)
        if should_skip_file(filename, tags):
            continue

        if "python" in tags:
            checker = check_python_file
        elif "text" in tags:
            checker = check_text_file
        else:
            print(f"WARNING: cannot check {filename} as it is not a supported filetype")
            continue

        checker(filename, lengthmap)
        if SETTINGS.found_error_matches:
            if SETTINGS.failfast:
                break
    if SETTINGS.found_error_matches:
        print("Spelling errors were encountered.")
        for filename in args.files:
            if filename in SETTINGS.found_error_locations:
                print_file_errors(filename, SETTINGS.found_error_locations[filename])
        sys.exit(1)

    print("ok -- spellcheck done")


if __name__ == "__main__":
    main()
