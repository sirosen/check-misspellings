#!/usr/bin/env python
import argparse
import difflib
import re
import sys
import tokenize

from identify import identify

SUBTOKENIZE_SPLIT_REGEX = re.compile(r"\s|\_")
DISABLE_COMMENT_REGEX = re.compile(r"\#\s*check\-misspellings\s*:\s*off")


def subtokenize_token(token_str):
    subtokens = SUBTOKENIZE_SPLIT_REGEX.split(token_str)
    offset = 0
    for st in subtokens:
        yield st, offset
        offset += len(st) + 1


def check_python_file(filename, corpus):
    errors = []
    with open(filename, "rb") as fp:
        for token in tokenize.tokenize(fp.readline):
            token_ty, token_str, startpos, endpos, line = token
            if DISABLE_COMMENT_REGEX.search(line):  # skip disabled lines
                continue
            if " " in token_str or "_" in token_str:
                subtokens = list(subtokenize_token(token_str))
            else:
                subtokens = [(token_str, 0)]

            for subtoken, offset in subtokens:
                matches = difflib.get_close_matches(subtoken, corpus, n=1, cutoff=0.8)
                if matches:
                    lineno, pos = startpos
                    errors.append(
                        (
                            line.rstrip("\n"),
                            pos + offset,
                            lineno,
                            f"appears similar to {matches}",
                        )
                    )
                    print(token)
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
    corpus = set()
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
    parser.add_argument("files", nargs="+", help="Files to check.")
    args = parser.parse_args()

    corpus = parse_corpus(args.corpus)

    failures = {}
    for filename in args.files:
        tags = identify.tags_from_path(filename)
        if "python" in tags:
            checker = check_python_file
        else:
            raise ValueError(
                f"cannot check {filename} as it is not a supported filetype"
            )

        found_errors = checker(filename, corpus)
        if found_errors:
            failures[filename] = found_errors
    if failures:
        print("Spelling errors were encountered.")
        for filename in args.files:
            if filename in failures:
                print_file_errors(filename, failures[filename])
        sys.exit(1)

    print("ok -- spellcheck done")
