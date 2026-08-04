#!/usr/bin/env python3
"""
Regenerate the `Tech Stack` badges and the `Projects developed` table in the `README`
from every public repository owned by the user.

A project is named with its repository `Name`, described by the repository's `About` field
and stacked with the repository's detected `Languages`,
so the profile is driven entirely by repositories metadata.

A repository whose `About` field is unset gets an empty description
and no code `Language` detected sets the stack as empty.

The `Tech Stack` badges are the union of the languages across every project.

Badge colours are derived from a hash of the language name.
They look arbitrary but are stable across runs:
a colour that really was random would redraw the `README` every run and commit it, for nothing.

The generated blocks replace whatever sits between the `START` and `END` markers in the `README`.
"""

from   collections    import Counter
import colorsys
import config
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

USER: str = os.environ.get("GITHUB_USER", config.USERNAME)
TOKEN: str | None = os.environ.get("GITHUB_TOKEN")
README: str = os.path.join(os.path.dirname(__file__), "..", "README.md")

# Repos that should never appear in the table (the profile repo itself, ...)
SKIP: set[str] = {USER.lower()}

# One row of the table: the three strings gather() collects per repository, plus its list of languages
# A plain assignment, so no typing import is needed: built-in generics land in Python 3.9 and the | union in 3.10
Project = dict[str, str | list[str]]


# =============================================================================
# (1) GATHER PUBLIC REPOSITORIES
# =============================================================================

def api(path: str) -> dict | list | None:
    """
    GET a JSON document from the GitHub API.

    Args:
        path: API path starting with a slash, e.g. "/users/PLACEHOLDER/repos".

    Returns:
        The parsed JSON body, a dict or a list depending on the endpoint.

    Raises:
        urllib.error.HTTPError: on any failing status.
    """

    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{USER}-profile-readme",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
    )

    try:
        with urllib.request.urlopen(request, timeout = 30) as result:
            return json.load(result)
    except urllib.error.HTTPError:
        raise


def repos() -> list[dict]:
    """
    Get the list of repositories owned by the user.
    Forks, archived, private and repositories in `SKIP` are left out.
    Most recently pushed first.

    Returns:
        A list of repository dicts exactly as the GitHub API returns them,
        sorted by push date descending.
    """

    repos, page = [], 1
    while True:
        batch = api(f"/users/{USER}/repos?type=owner&per_page=100&page={page}")
        if not batch:
            break
        repos += batch
        page += 1

    keep = [ repo for repo in repos
            if not repo["fork"] and not repo["archived"] and not repo["private"]
            and repo["name"].lower() not in SKIP
    ]
    return sorted(keep, key=lambda repo: repo["pushed_at"], reverse=True)


# =============================================================================
# (2) LANGUAGES
# =============================================================================

def repo_languages(repo: str) -> list[str]:
    """
    The languages GitHub detected, biggest first, slivers dropped.

    This is the data behind the coloured `Languages` bar on the repository page.
    Anything under `MIN_SHARE` of the repository is noise and is left out.
    A repository GitHub detected no code in simply yields nothing.

    Args:
        repo: repository name (without the owner prefix).

    Returns:
        Language names ordered by bytes of code descending, at most `MAX_STACK` of them.
        Empty when GitHub detected no code.
    """

    sizes = api(f"/repos/{USER}/{repo}/languages") or {}
    total = sum(sizes.values())
    if not total:
        return []
    return [ name for name, size in sorted(sizes.items(), key=lambda kv: -kv[1]) if size / total >= config.MIN_SHARE
    ][:config.MAX_STACK]


def _luminance(rgb: tuple[float, float, float]) -> float:
    """
    WCAG relative luminance of an RGB triple given in 0..1.

    Args:
        rgb: an iterable of three floats in 0..1, red then green then blue.

    Returns:
        The relative luminance as a float in 0..1, 0 being black and 1 white.
    """

    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    return r * 0.2126 + g * 0.7152 + b * 0.0722

def _band(byte: int, low_high: tuple[float, float]) -> float:
    """
    Spread one digest byte across a range.

    Args:
        byte:     a value in 0..255 taken from the digest.
        low_high: the (low, high) bounds to map it onto.

    Returns:
        A float between low and high inclusive.
    """

    low, high = low_high
    return low + (byte / 255) * (high - low)

def language_color(language: str) -> str:
    """
    A stable, vivid hex colour for a language name.

    sha256 rather than hash(): Python randomises hash() per process, which would repaint every badge on every run.
    The digest picks a hue anywhere on the wheel, then a saturation and a lightness inside their bands.

    `COLOR_SALT` is mixed in before hashing.
    It re-rolls the whole palette at once,
    which is the only lever available when a few languages happen to draw neighbouring hues,
    since a function given one name cannot know which hues the others already took.

    Lightness is then pulled down until the colour clears `MAX_LUMINANCE`.
    That step is what HLS alone cannot give:
    the same lightness reads far brighter in yellow-green than in blue, so leaving lightness where the digest put it
    would keep some hues readable under white text and not others.

    Args:
        language: the language name, matched case-insensitively.

    Returns:
        Six uppercase hex digits with no leading '#', e.g. "A8541C".
    """

    digest = hashlib.sha256(f"{language.lower()}#{config.COLOR_SALT}".encode("utf-8")).digest()

    # Two bytes for the hue, so it lands on one of 65536 points of the wheel
    # rather than 256, and one byte each for the other two axes.
    hue = int.from_bytes(digest[0:2], "big") / 65535
    lightness = _band(digest[2], config.LIGHTNESS)
    saturation = _band(digest[3], config.SATURATION)

    # Step down a percent at a time rather than solving for the lightness, since
    # luminance depends on the hue and there is no closed form for it
    rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
    while _luminance(rgb) > config.MAX_LUMINANCE and lightness > 0.10:
        lightness -= 0.01
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)

    return "".join(f"{round(channel * 255):02X}" for channel in rgb)


def badge(language: str) -> str:
    """
    A shields.io badge image for a language, coloured from its name.

    Args:
        language: the language name, used as both the visible label and the seed the colour is derived from.

    Returns:
        A markdown image tag pointing at shields.io.
    """

    # shields reads a literal dash as a field separator and an underscore as a space
    label = urllib.parse.quote(language.replace("-", "--").replace("_", "__"))
    return f"![{language}](https://img.shields.io/badge/{label}-{language_color(language)}?style=for-the-badge)"

def build_stack(projects: list[Project]) -> str:
    """
    A badge per language, the ones used across most projects first.

    Args:
        projects: the project dicts returned by gather().

    Returns:
        The badges as markdown, one per line.
    """

    counts = Counter(language for project in projects for language in project["stack"])

    # Ties break alphabetically so the order can never wobble between runs
    order = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return "\n".join(badge(language) for language, _ in order)


# =============================================================================
# (3) TABLE
# =============================================================================

def cell(text: str) -> str:
    """
    Make a string safe to drop inside a markdown table cell.

    Args:
        text: text, possibly spanning several lines or holding the pipes that would otherwise split the row into extra columns.

    Returns:
        A single-line string with pipes escaped, cut at a word boundary once it runs past `MAX_DESCRIPTION` characters.
    """

    text = " ".join(text.split()).replace("|", "\\|")
    if len(text) > config.MAX_DESCRIPTION:
        text = text[: config.MAX_DESCRIPTION - 1].rsplit(" ", 1)[0] + "…"
    return text


def build_table(projects: list[Project]) -> str:
    """
    The markdown table for the `Projects developed` block.

    Args:
        projects: the project dicts returned by gather().

    Returns:
        The whole table as markdown, header and separator rows included.
    """

    header = ["| Project | What it is | Stack |", "| :--- | :--- | :--- |"]

    rows = [
        f"| **[{cell(project['title'])}]({project['url']})** | {cell(project['description'])} | "
        f"{' '.join(f'`{language}`' for language in project['stack'])} |"
        for project in projects
    ]
    return "\n".join(header + rows)


# =============================================================================
# (4) EXECUTOR
# =============================================================================

def gather() -> list[Project]:
    """
    One pass over the public repositories.

    Prints one line per repository as it goes, naming an empty `About` field or
    an empty `Language` list so a blank cell on the profile is traceable to the
    run that produced it.

    Returns:
        A list of project dicts, each with the keys: title, description, url and stack.
    """

    projects = []
    for repo in repos():
        description = repo["description"] or ""
        stack = repo_languages(repo["name"])

        projects.append({
            "title":       repo["name"],
            "description": description,
            "url":         repo["html_url"],
            "stack":       stack
        })

        missing = [ what for what, value in (("About", description), ("Languages", stack)) if not value ]
        note = f"  (empty {' and '.join(missing)})" if missing else ""
        print(f"  added   {repo['name']}{note}")
    return projects


def replace(readme: str, name: str, body: str) -> str:
    """
    Swap the content sitting between one pair of `START` - `END` markers.

    Args:
        readme: the full `README` text.
        name:   the marker name, e.g. `PROJECTS` for `<!-- PROJECTS:START -->`.
        body:   the replacement content, inserted with a blank line either side.

    Returns:
        The `README` text with that one block replaced, everything else intact.

    Raises:
        SystemExit: when either marker is missing, so a mangled `README` fails
            the run rather than being half-written.
    """

    start, end = f"<!-- {name}:START -->", f"<!-- {name}:END -->"
    if start not in readme or end not in readme:
        sys.exit(f"markers {start} / {end} not found in README.md")
    return re.sub(
        rf"{re.escape(start)}.*?{re.escape(end)}",
        lambda _: f"{start}\n\n{body}\n\n{end}",
        readme,
        flags=re.DOTALL,
    )


def main():
    """
    Rebuild both blocks and write the `README` only when something changed.

    Leaving the file untouched on an identical result is what lets the workflow skip its commit.

    Raises:
        SystemExit: when no public repository was found, so an API failure cannot wipe the table.
    """

    projects = gather()
    if not projects:
        sys.exit("no projects found — refusing to write an empty README")

    with open(file=README, mode="r", encoding="utf-8") as file:
        readme = original = file.read()

    readme = replace(readme, "PROJECTS", build_table(projects))
    readme = replace(readme, "STACK", build_stack(projects))
    if readme == original:
        print("README.md already up to date")
        return

    with open(file=README, mode="w", encoding="utf-8") as file:
        file.write(readme)
    print("README.md updated")

if __name__ == "__main__":
    main()