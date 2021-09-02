import argparse
import difflib
import re
import sys
import unicodedata

from identify import identify

from .builtin_corpus import FULL_CORPUS
from .tokenizers import (
    SUBTOKENIZE_TEXT_SPLIT_REGEX,
    TOKENIZER_MAPPING,
    should_skip_token,
)

# experimentally found cutoffs which match letter inversions
# easily but have minimal incorrect matches
LENGTH_BASED_SIMILARITY_CUTOFFS = (
    (4, 0.825),
    (10, 0.85),
)
CAMEL_AND_TITLE_CASE_ITER_REGEX = re.compile(r"(^|[A-Z])[^A-Z]+")
TRAILING_DIGIT_REGEX = re.compile(r"\d+$")


class _Context:
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


CONTEXT = _Context()


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


def should_skip_file(filename, tags):
    if "symlink" in tags:
        return True
    if "binary" in tags:
        return True
    if "directory" in tags:
        return True
    return False


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

    if _case_insensitive_str_in_corpus(token.replace("\\", ""), corpus):
        return True

    # check for "myfoo" where "foo" is in the corpus, as this is a
    # common/classic way of writing examples
    # likewise, check for "newfoo", "oldfoo"
    if token.lower().startswith("my") and _case_insensitive_str_in_corpus(
        token[2:], full_corpus
    ):
        return True
    if (
        token.lower().startswith("new") or token.lower().startswith("old")
    ) and _case_insensitive_str_in_corpus(token[3:], full_corpus):
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
            (
                _case_insensitive_str_in_corpus(x, full_corpus)
                or should_skip_token(x, CONTEXT)
            )
            for x in SUBTOKENIZE_TEXT_SPLIT_REGEX.split(token)
        ):
            return True
    # check camelCase and TitleCase words
    if all(
        (
            _case_insensitive_str_in_corpus(m.group(0), full_corpus)
            or should_skip_token(m.group(0), CONTEXT)
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


def check_tokenstream(filename, tokenizer, context, lengthmap):
    full_corpus = lengthmap[0]
    for token, line, lineno, pos in tokenizer(filename, context):
        location_item = (token, line.rstrip("\n"), pos, lineno)

        current_corpus = corpus_for_token(token, lengthmap)
        if token_in_corpus(token, current_corpus, full_corpus):
            continue
        if token in context.non_error_non_corpus_words:
            continue
        if token in context.found_error_matches:
            if filename not in context.found_error_locations:
                context.found_error_locations[filename] = []
            context.found_error_locations[filename].append(location_item)
            continue

        if context.show_not_in_corpus:
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
            if filename not in context.found_error_locations:
                context.found_error_locations[filename] = []
            context.found_error_matches[token] = matches
            context.found_error_locations[filename].append(location_item)
            failed = True
            if context.failfast:
                return

        if not failed:
            context.non_error_non_corpus_words.add(token)
    return


def print_file_errors(filename, errors):
    print("\033[1m" + filename + "\033[0m:")
    for token, line, pos, lineno in errors:
        matches = CONTEXT.found_error_matches[token]
        if CONTEXT.show_all_matches:
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
    if CONTEXT.ascii_ize:
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
    CONTEXT.set_args(args)

    lengthmap = parse_corpus(args.corpus)

    for filename in args.files:
        if filename in args.exclude:
            continue
        if CONTEXT.verbose:
            print(f"check: {filename}")
        tags = identify.tags_from_path(filename)
        if should_skip_file(filename, tags):
            continue

        tokenizer = None
        for tok_tag, tag_tokenizer in TOKENIZER_MAPPING:
            if tok_tag in tags:
                tokenizer = tag_tokenizer
                break
        if not tokenizer:
            print(f"WARNING: cannot check {filename} as it is not a supported filetype")
            continue

        check_tokenstream(filename, tokenizer, CONTEXT, lengthmap)
        if CONTEXT.found_error_matches:
            if CONTEXT.failfast:
                break
    if CONTEXT.found_error_matches:
        print("Spelling errors were encountered.")
        for filename in args.files:
            if filename in CONTEXT.found_error_locations:
                print_file_errors(filename, CONTEXT.found_error_locations[filename])
        sys.exit(1)

    print("ok -- spellcheck done")


if __name__ == "__main__":
    main()
