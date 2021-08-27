#!/usr/bin/env python
import argparse
import difflib
import re
import sys
import tokenize

from identify import identify

SUBTOKENIZE_PY_SPLIT_REGEX = re.compile(r"[\s_'\"]")
SUBTOKENIZE_TEXT_SPLIT_REGEX = re.compile(r"[_\-]")
NON_WORDSTR_REGEX = re.compile(r"^[^\w]+$")
DISABLE_COMMENT_REGEX = re.compile(r"check\-misspellings\s*:\s*off")
ENABLE_COMMENT_REGEX = re.compile(r"check\-misspellings\s*:\s*on")
DISABLE_COMMENT_PY_REGEX = re.compile(r"#\s*check\-misspellings\s*:\s*off")
HAS_URI_SCHEME_REGEX = re.compile(r"^https?\:\/\/")
IS_DOMAIN_REGEX = re.compile(r"\.(org|net|com|us|co\.uk|io)$")

BUILTIN_CORPUS = [
    # standard UNIX-y things
    "tmp",
    "usr",
    "glob",
    "globs",
    "dir",
    "dirs",
    "dirname",
    # HTML things
    "href",
    "td",
    "tr",
    "thead",
    "tfoot",
    "hr",
    "div",
    "pre",
    "src",
    "alt",
    "img",
    # standard software terms, not typically found in a dictionary
    "dns",
    "fqdn",
    "scope",
    "viewable",
    "extensible",
    "vars",
    "cli",
    "admin",
    "admins",
    "docstring",
    "namespace",
    "namespaces",
    "backend",
    "attr",
    "readme",
    "param",
    "params",
    "config",
    "linting",
    "lints",
    "http",
    "https",
    "regex",
    "regexes",
    "messaging",
    "workspace",
    "behaviors",
    "urls",
    "uri",
    "org",
    "com",
    "edu",
    "repos",
    "api",
    "analytics",
    "app",
    # known tools, languages, etc
    "wget",
    "cd",
    "mv",
    "chmod",
    "chown",
    "mkdir",
    "diff",
    "vi",
    "tr",
    "git",
    "shellcheck",
    "shfmt",
    "flake8",
    "pylint",
    "pyflakes",
    "bundler",
    "venv",
    "virtualenv",
    "awscli",
    "validator",
    "memcache",
    "memcached",
    "py",
    "java",
    "javascript",
    "js",
    "json",
    "yaml",
    "rb",
    "py",
    "rbenv",
    "erb",
    "python3",
    "highlightjs",
    "readthedocs",
    "asciidoctor",
    "asciidoc",
    "adoc",
    "markdown",
    # known service and product names
    "linux",
    "github",
    "ubuntu",
    "rhel",
    "centos",
    "amazonaws",
    "S3",
    # known service and tool-related env vars
    "GITHUB_SHA",
    "GITHUB_ENV",
    "GITHUB_PATH",
    "GITHUB_WORKSPACE",
    "GITHUB_BASE_REF",
    "GITHUB_TOKEN",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
]


def should_skip_token(tok):
    if tok == "":
        return True
    if HAS_URI_SCHEME_REGEX.match(tok):
        return True
    if IS_DOMAIN_REGEX.match(tok):
        return True
    if NON_WORDSTR_REGEX.match(tok):
        return True

    try:  # skip numeric values
        float(tok)
        return True
    except ValueError:
        pass

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
            if not should_skip_token(st):
                yield st, offset, lineno
            offset += len(st) + 1


def pyfile_token_stream(filename):
    with open(filename, "rb") as fp:
        for token in tokenize.tokenize(fp.readline):
            token_ty, token_str, startpos, endpos, line = token
            if DISABLE_COMMENT_PY_REGEX.search(line):  # skip disabled lines
                continue
            if " " in token_str or "_" in token_str:
                subtokens = list(subtokenize_py_token(token_str))
            else:
                subtokens = [(token_str, 0, 0)]

            subtokens = [(x, y, z) for (x, y, z) in subtokens]

            for subtoken, col_offset, line_offset in subtokens:
                lineno, pos = startpos
                yield (
                    token_str,
                    line.split("\n")[line_offset],
                    lineno,
                    (pos if line_offset == 0 else 0) + col_offset,
                )


def check_python_file(filename, corpus, args):
    return check_tokenstream(pyfile_token_stream(filename), corpus, args)


def textfile_token_stream(filename):
    # capture URIs or words (URIs are common in, e.g., bash scripts)
    word_regex = re.compile(r"(https?\:\/\/\w+\.\w+(\.\w+)*[^\s]*)|[\w\-]+")

    enabled = True

    with open(filename) as f:
        for lineno, line in enumerate(f):
            for match in word_regex.finditer(line):
                if not enabled:
                    if ENABLE_COMMENT_REGEX.search(line):
                        enabled = True
                if DISABLE_COMMENT_REGEX.search(line):
                    enabled = False
                    continue
                token = match.group()
                if not should_skip_token(token):
                    yield token, line, lineno + 1, match.start()


def check_text_file(filename, corpus, args):
    return check_tokenstream(textfile_token_stream(filename), corpus, args)


def token_in_corpus(token, corpus):
    if token in corpus:
        return True
    if token.lower() in corpus:
        return True
    if token.title() in corpus:
        return True
    # allow loose hyphenate and '_'-separation handling
    # "one-time" matches "onetime"
    # "single-use" matches "single", "use"
    if "-" in token or "_" in token:
        if token.replace("-", "").replace("_", "") in corpus:
            return True
        if all(x in corpus for x in SUBTOKENIZE_TEXT_SPLIT_REGEX.split(token)):
            return True
    return False


def check_tokenstream(tokens, corpus, args):
    set_corpus = set(corpus)
    non_error_non_corpus_words = set()
    errors = []
    for token, line, lineno, pos in tokens:
        if token_in_corpus(token, set_corpus):
            continue
        if token in non_error_non_corpus_words:
            continue

        if args.show_not_in_corpus:
            print(f"non-corpus word: {token}")

        failed = False
        # experimentally found cutoff which matches letter inversions
        # easily but has minimal incorrect matches
        matches = difflib.get_close_matches(token, corpus, cutoff=0.825)
        if matches:
            # exclude substring matches, e.g. 'support' matches 'supported'
            found_exact = any([(token in m or m in token) for m in matches])
            if not found_exact:
                errors.append(
                    (line.rstrip("\n"), pos, lineno, f"appears similar to {matches[0]}")
                )
                failed = True
                if args.failfast:
                    return errors

        if not failed:
            non_error_non_corpus_words.add(token)
    return errors


def print_file_errors(filename, errors):
    print("\033[1m" + filename + "\033[0m:")
    for line, pos, lineno, message in errors:
        lineprefix = "line {}: ".format(lineno)
        print(lineprefix + line)
        print(
            "\033[0;33m" + " " * (len(lineprefix) + pos) + "^-- " + message + "\033[0m"
        )


def parse_corpus(filenames):
    corpus = set(BUILTIN_CORPUS)
    for filename in filenames:
        with open(filename) as fp:
            for line in fp:
                line = line.strip()
                if line.startswith("#") or line == "":
                    continue
                corpus.add(line)
    return list(corpus)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        required=True,
        action="append",
        help=(
            "REQUIRED. "
            "The path to a file containing newline-delimited known words. "
            "Comments (with '#') and empty lines are allowed in the corpus. "
            "This option may be passed multiple times."
        ),
    )
    parser.add_argument("-v", action="store_true", dest="verbose", default=False)
    parser.add_argument("--use-system-dict", action="store_true", default=False)
    parser.add_argument("--show-not-in-corpus", action="store_true", default=False)
    parser.add_argument("--failfast", action="store_true", default=False)
    parser.add_argument("files", nargs="+", help="Files to check.")
    args = parser.parse_args()

    if args.use_system_dict:
        if sys.platform.startswith("linux"):
            args.corpus.append("/usr/share/dict/words")
        else:
            print("Warning: No known system dict for current platform.")

    corpus = parse_corpus(args.corpus)

    failures = {}
    for filename in args.files:
        if args.verbose:
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

        found_errors = checker(filename, corpus, args)
        if found_errors:
            failures[filename] = found_errors
            if args.failfast:
                break
    if failures:
        print("Spelling errors were encountered.")
        for filename in args.files:
            if filename in failures:
                print_file_errors(filename, failures[filename])
        sys.exit(1)

    print("ok -- spellcheck done")


if __name__ == "__main__":
    main()
