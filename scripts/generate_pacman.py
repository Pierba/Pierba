#!/usr/bin/env python3
"""
Draw the contribution graph as a Pac-Man maze and animate Pac-Man eating it.

The output is two self-contained, **animated SVG** files — one for each GitHub colour
scheme — written into `dist/`:

    dist/github-pacman.svg        light theme
    dist/github-pacman-dark.svg   dark theme

Why a plain SVG and not a canvas or a GIF:
a profile `README` is rendered as sanitised markdown, so no JavaScript ever runs there and
the images are proxied through GitHub's camo cache. An SVG carrying its own `CSS`
`@keyframes` is the only format that animates by itself, scales to any width, stays a few
tens of kilobytes and survives that proxy — which is also why the snake this replaces was
built the same way.

The animation is `CSS` only, and deliberately restricted to the two properties that behave
identically in every renderer:

  * `opacity`  — a contribution square fades to the empty-cell colour underneath it the
                 moment Pac-Man's mouth reaches it, so the graph is eaten in place.
  * `translate` — Pac-Man and the ghosts move.

No `transform-origin`, no `rotate()`, no `scale()`: those depend on the SVG `transform-box`
resolution, which is the one part of the spec renderers disagree on. The chomping mouth is
therefore an arcade-style **sprite flip-book** — a handful of wedge paths cross-faded with
`step-end` timing — rather than a rotation, and the same trick turns Pac-Man around at the
end of every row.

Data comes from the GitHub GraphQL API (`contributionsCollection`), the same source that
feeds the graph on the profile page, so the maze is the real calendar. Without a token —
running it by hand — a deterministic demo calendar is generated instead, so the rendering
can be checked locally without credentials.
"""

from   datetime       import date, datetime
from   math           import cos, radians, sin
import argparse
import config
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

USER: str = os.environ.get("GITHUB_USER", config.USERNAME)
TOKEN: str | None = os.environ.get("GITHUB_TOKEN")
DIST: str = os.path.join(os.path.dirname(__file__), "..", "dist")

DAYS: int = 7  # Rows of the graph, one per weekday

# GraphQL enum -> index into the four contribution colours, 0 meaning no contribution
LEVELS: dict[str, int] = {
    "NONE":            0,
    "FIRST_QUARTILE":  1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE":  3,
    "FOURTH_QUARTILE": 4,
}

MONTHS: tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

# The two palettes GitHub itself uses, so the graph is indistinguishable from the real one
THEMES: dict[str, dict] = {
    "light": {
        "empty":  "#ebedf0",
        "scale":  ("#9be9a8", "#40c463", "#30a14e", "#216e39"),
        "text":   "#57606a",
        "pacman": "#e3b341",
        "ghosts": ("#f85149", "#db61a2", "#1f9cb0", "#8250df"),
        "eye":    "#ffffff",
        "pupil":  "#24292f",
    },
    "dark": {
        "empty":  "#161b22",
        "scale":  ("#0e4429", "#006d32", "#26a641", "#39d353"),
        "text":   "#8b949e",
        "pacman": "#f2cc60",
        "ghosts": ("#ff7b72", "#f778ba", "#56d4dd", "#d2a8ff"),
        "eye":    "#f0f6fc",
        "pupil":  "#0d1117",
    },
}

FONT: str = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


# =============================================================================
# (1) GATHER THE CONTRIBUTION CALENDAR
# =============================================================================

QUERY: str = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          firstDay
          contributionDays { weekday contributionLevel }
        }
      }
    }
  }
}
"""


def fetch_calendar(login: str, token: str) -> list[dict]:
    """
    Ask the GraphQL API for the last year of contributions.

    The REST API cannot answer this: the calendar is only exposed through GraphQL,
    which is why this is the one call in the repository that is not a plain GET.

    Args:
        login: the account whose calendar is wanted.
        token: any token able to read public profile data. In Actions the automatic
            `GITHUB_TOKEN` is enough — the calendar of a public profile is public.

    Returns:
        The list of weeks, oldest first, each a dict with `firstDay` and `contributionDays`.

    Raises:
        urllib.error.HTTPError: on any failing status.
        RuntimeError: when the API answers with a GraphQL `errors` block, which comes
            back as HTTP 200 and would otherwise pass silently.
    """

    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data    = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8"),
        headers = {
            "Accept":        "application/vnd.github+json",
            "Content-Type":  "application/json",
            "User-Agent":    f"{login}-profile-readme",
            "Authorization": f"Bearer {token}",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as result:
        body = json.load(result)

    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]


def demo_calendar(weeks: int = 53) -> list[dict]:
    """
    A stand-in calendar for running the script without a token.

    Levels are drawn from a `sha256` of the day index, so a local render is byte-identical
    between runs and a diff only ever shows a change that was really made to the drawing
    code. Weekends are thinned out, otherwise the demo graph reads as noise rather than as
    somebody's commit history.

    Args:
        weeks: how many columns to invent.

    Returns:
        The same shape `fetch_calendar` returns.
    """

    names = list(LEVELS)
    start = date.today().toordinal() - (weeks * DAYS - 1)

    out = []
    for week in range(weeks):
        days = []
        for day in range(DAYS):
            seed = hashlib.sha256(f"{week}:{day}".encode("utf-8")).digest()
            level = seed[0] * 5 // 256                       # 0..4, uniform
            if day in (0, 6) and seed[1] % 3:                # quieter weekends
                level = max(0, level - 2)
            if seed[2] % 5 == 0:                             # a few blank days anywhere
                level = 0
            days.append({"weekday": day, "contributionLevel": names[level]})
        out.append({
            "firstDay": date.fromordinal(start + week * DAYS).isoformat(),
            "contributionDays": days,
        })
    return out


def grid(weeks: list[dict]) -> tuple[dict[tuple[int, int], int], list[tuple[int, str]]]:
    """
    Flatten the API answer into something the drawing code can index.

    Args:
        weeks: the weeks as returned by `fetch_calendar` or `demo_calendar`.

    Returns:
        A `(cells, months)` pair, where `cells` maps `(column, row)` to a level in 0..4 —
        missing keys are days outside the calendar, at the very start or the very end —
        and `months` is the `(column, label)` list for the header, one entry per month that
        opens far enough from the previous one to leave room for its own label.
    """

    cells: dict[tuple[int, int], int] = {}
    months: list[tuple[int, str]] = []
    previous_month, previous_column = None, -99

    for column, week in enumerate(weeks):
        for day in week["contributionDays"]:
            cells[(column, day["weekday"])] = LEVELS.get(day["contributionLevel"], 0)

        month = datetime.fromisoformat(week["firstDay"]).month
        if month != previous_month and column - previous_column >= 3:
            months.append((column, MONTHS[month - 1]))
            previous_month, previous_column = month, column
        elif month != previous_month:
            previous_month = month

    return cells, months


# =============================================================================
# (2) THE ROUTE PAC-MAN TAKES
# =============================================================================

class Route:
    """
    Pac-Man's boustrophedon sweep over the graph, and the clock that goes with it.

    Row 0 is eaten left to right, row 1 right to left, and so on, which is the only path
    that covers every square without ever crossing itself — a maze-like route would leave
    squares behind or need Pac-Man to walk back over holes he already ate.

    Everything downstream is timing: the keyframe percentages of the movement, of the
    turn-arounds, and the instant each individual square has to fade. They all have to be
    derived from the same clock or the mouth stops lining up with the square it is eating.

    Attributes:
        weeks:     number of columns in the graph.
        duration:  one full loop in seconds, tail included.
        waypoints: `(second, x, y)` triples, the corners of the path.
        starts:    per row, the second Pac-Man reaches that row's first square.
    """

    def __init__(self, weeks: int, x0: float, y0: float):
        """
        Args:
            weeks:  number of columns.
            x0, y0: user-space coordinates of the top-left corner of the grid.
        """

        self.weeks = weeks
        self._x0, self._y0 = x0, y0

        step, turn = config.PACMAN_STEP, config.PACMAN_TURN
        lead = config.PACMAN_LEAD

        # Off-canvas on the left, so Pac-Man walks in rather than popping into existence,
        # and so the ghosts have somewhere to wait out their delay unseen
        second = lead * step
        waypoints = [(0.0, self.x(-lead), self.y(0)), (second, self.x(0), self.y(0))]
        starts = []

        for row in range(DAYS):
            if row:                                  # drop straight down onto the next row
                second += turn
                waypoints.append((second, waypoints[-1][1], self.y(row)))
            starts.append(second)

            second += (weeks - 1) * step
            waypoints.append((second, self.x(weeks - 1 if row % 2 == 0 else 0), self.y(row)))

        second += lead * step                        # and out the other side
        waypoints.append((second, self.x(weeks - 1 + lead), self.y(DAYS - 1)))

        self.starts = starts
        self.duration = second + config.PACMAN_TAIL  # the pause on the emptied graph
        self.waypoints = waypoints + [(self.duration, waypoints[-1][1], self.y(DAYS - 1))]

    def x(self, column: float) -> float:
        """Centre of a column in user space; fractional and negative columns are off-grid."""
        return self._x0 + column * config.PACMAN_PITCH + config.PACMAN_CELL / 2

    def y(self, row: float) -> float:
        """Centre of a row in user space."""
        return self._y0 + row * config.PACMAN_PITCH + config.PACMAN_CELL / 2

    def pct(self, second: float) -> float:
        """A second on the clock as a keyframe percentage, rounded to hundredths."""
        return round(second / self.duration * 100, 2)

    def eaten(self, column: int, row: int) -> float:
        """
        The second Pac-Man's centre crosses one square.

        Args:
            column: column index.
            row:    row index, 0..6.

        Returns:
            The time in seconds from the start of the loop.
        """

        travelled = column if row % 2 == 0 else self.weeks - 1 - column
        return self.starts[row] + travelled * config.PACMAN_STEP

    def facing(self) -> list[tuple[float, float, bool]]:
        """
        When Pac-Man looks right and when he looks left.

        The flip happens halfway down each drop, where he is between two rows and pointing
        nowhere in particular, so the sprite never appears to turn while still eating.

        Returns:
            `(from_second, to_second, looks_right)` covering the whole loop end to end.
        """

        half = config.PACMAN_TURN / 2
        edges = [0.0] + [self.starts[row] - half for row in range(1, DAYS)] + [self.duration]
        return [(edges[row], edges[row + 1], row % 2 == 0) for row in range(DAYS)]


# =============================================================================
# (3) SPRITES
# =============================================================================

def wedge(radius: float, mouth: float, right: bool) -> str:
    """
    One frame of the chomp: a disc with a wedge bitten out of it.

    Args:
        radius: the sprite radius in user space.
        mouth:  half the mouth opening in degrees. 0 is a closed disc.
        right:  which way the mouth points.

    Returns:
        The `d` attribute of the path, drawn around a local origin of `0,0` so the group
        holding it can simply be translated onto the grid.
    """

    if mouth <= 0.5:                                  # a wedge of nothing is not a circle
        return (f"M0,-{radius}A{radius},{radius} 0 1,0 0,{radius}"
                f"A{radius},{radius} 0 1,0 0,-{radius}Z")

    x = round(radius * cos(radians(mouth)), 2) * (1 if right else -1)
    y = round(radius * sin(radians(mouth)), 2)

    # The drawn arc is the long way round (large-arc), so the gap left behind is the mouth.
    # Mirroring the sprite mirrors the direction the arc is swept in, hence the flag flip.
    sweep = 0 if right else 1
    return f"M0,0L{x},{-y}A{radius},{radius} 0 1,{sweep} {x},{y}Z"


def ghost(radius: float, colour: str, theme: dict) -> str:
    """
    A ghost, drawn around a local origin of `0,0`.

    Args:
        radius: half the ghost's width.
        colour: body fill.
        theme:  the palette, for the eyes.

    Returns:
        The markup for one ghost, without any positioning.
    """

    r = radius
    foot, wave = r * 0.86, r * 0.34

    # Domed head, then three feet zig-zagged back to the left edge
    body = [f"M{-r},{-r * 0.15}A{r},{r} 0 0,1 {r},{-r * 0.15}", f"L{r},{foot}"]
    for i in range(3):
        body.append(f"L{round(r - (i * 2 + 1) * r / 3, 2)},{round(foot - wave, 2)}"
                    f"L{round(r - (i * 2 + 2) * r / 3, 2)},{foot}")
    body.append("Z")

    eye_x, eye_y = r * 0.38, r * 0.18
    return (
        f'<path d="{"".join(body)}" fill="{colour}"/>'
        f'<ellipse cx="{-eye_x}" cy="{-eye_y}" rx="{r * 0.3}" ry="{r * 0.37}" fill="{theme["eye"]}"/>'
        f'<ellipse cx="{eye_x}" cy="{-eye_y}" rx="{r * 0.3}" ry="{r * 0.37}" fill="{theme["eye"]}"/>'
        f'<circle cx="{-eye_x}" cy="{-eye_y * 0.4}" r="{r * 0.17}" fill="{theme["pupil"]}"/>'
        f'<circle cx="{eye_x}" cy="{-eye_y * 0.4}" r="{r * 0.17}" fill="{theme["pupil"]}"/>'
    )


# =============================================================================
# (4) STYLESHEET
# =============================================================================

def stylesheet(route: Route, times: dict[float, int]) -> str:
    """
    Every `@keyframes` rule the drawing needs.

    One rule per distinct instant a square is eaten. There is no way around generating
    them: `animation-delay` shifts a whole cycle rather than one point inside it, so two
    squares that vanish at different times but reappear together cannot share a rule.
    Percentages are rounded to hundredths first, which collapses squares that fall on the
    same instant and keeps the file at a few tens of kilobytes.

    Args:
        route: the finished route, for the clock.
        times: maps each rounded eat-percentage to the index of its rule.

    Returns:
        The content of the `style` element.
    """

    d = route.duration
    fade = round(config.PACMAN_FADE / d * 100, 2)
    hold = 96.0                                 # squares stay eaten, then grow back in the tail

    css = [
        f".g{{animation-duration:{d:.2f}s;animation-iteration-count:infinite;"
        "animation-timing-function:linear;animation-fill-mode:backwards}",
        ".s{animation-timing-function:step-end}",
    ]

    # --- squares -------------------------------------------------------------
    for at, index in times.items():
        gone = min(round(at + fade, 2), hold - 0.01)
        css.append(f".e{index}{{animation-name:e{index}}}"
                   f"@keyframes e{index}{{0%,{at}%{{opacity:1}}"
                   f"{gone}%,{hold}%{{opacity:0}}100%{{opacity:1}}}}")

    # --- movement ------------------------------------------------------------
    # `translate` only: it is the one transform whose result cannot depend on how a
    # renderer resolves `transform-box` and `transform-origin` for an SVG group.
    stops = "".join(
        f"{route.pct(second)}%{{transform:translate({x:.1f}px,{y:.1f}px)}}"
        for second, x, y in route.waypoints
    )
    css.append(f"@keyframes walk{{{stops}}}.walk{{animation-name:walk}}")

    # --- which way the sprite looks -----------------------------------------
    for name, looking in (("faceR", True), ("faceL", False)):
        keys = []
        for start, end, right in route.facing():
            keys.append(f"{route.pct(start)}%{{opacity:{1 if right is looking else 0}}}")
        css.append(f"@keyframes {name}{{{''.join(keys)}}}.{name}{{animation-name:{name}}}")

    # --- the chomp itself ----------------------------------------------------
    frames = len(config.PACMAN_MOUTH) * 2 - 2          # open, then back closed again
    css.append(f".chomp{{animation-duration:{config.PACMAN_CHOMP}s;"
               "animation-iteration-count:infinite;animation-timing-function:step-end}")
    for i in range(frames):
        on, off = round(i * 100 / frames, 2), round((i + 1) * 100 / frames, 2)
        head = "" if i == 0 else "0%{opacity:0}"
        css.append(f".c{i}{{animation-name:c{i}}}"
                   f"@keyframes c{i}{{{head}{on}%{{opacity:1}}{off}%{{opacity:0}}}}")

    return "".join(css)


# =============================================================================
# (5) DRAWING
# =============================================================================

def draw(weeks: list[dict], theme_name: str) -> str:
    """
    The whole SVG for one colour scheme.

    Args:
        weeks:      the calendar.
        theme_name: a key of `THEMES`.

    Returns:
        The SVG document as a string.
    """

    theme = THEMES[theme_name]
    cells, months = grid(weeks)
    columns = len(weeks)

    cell, gap, pitch = config.PACMAN_CELL, config.PACMAN_GAP, config.PACMAN_PITCH
    radius = config.PACMAN_RADIUS

    pad_l, pad_t, pad_r, pad_b = 30, 24, 14, 26        # labels above and to the left, legend below
    width = pad_l + columns * pitch - gap + pad_r
    height = pad_t + DAYS * pitch - gap + pad_b

    route = Route(columns, pad_l, pad_t)

    # Squares that hold something get a rule keyed on when they are eaten; blanks never move
    times: dict[float, int] = {}
    for (column, row), level in cells.items():
        if level:
            times.setdefault(route.pct(route.eaten(column, row)), len(times))

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Pac-Man eating the contribution graph of {USER}">',
        f"<title>Pac-Man eating the contribution graph of {USER}</title>",
        f"<style>{stylesheet(route, times)}</style>",
        f'<g font-family="{FONT}" font-size="9" fill="{theme["text"]}">',
    ]

    # --- labels --------------------------------------------------------------
    for column, label in months:
        out.append(f'<text x="{route.x(column) - cell / 2:.0f}" y="{pad_t - 8}">{label}</text>')
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(f'<text x="0" y="{route.y(row) + 3:.0f}">{label}</text>')

    # --- legend --------------------------------------------------------------
    legend_y = pad_t + DAYS * pitch - gap + 14
    legend_x = width - pad_r - 5 * pitch - 62
    out.append(f'<text x="{legend_x}" y="{legend_y + 8}">Less</text>')
    for i, colour in enumerate((theme["empty"], *theme["scale"])):
        out.append(f'<rect x="{legend_x + 28 + i * pitch}" y="{legend_y}" '
                   f'width="{cell}" height="{cell}" rx="2" fill="{colour}"/>')
    out.append(f'<text x="{legend_x + 33 + 5 * pitch}" y="{legend_y + 8}">More</text>')
    out.append("</g>")

    # --- the maze ------------------------------------------------------------
    # Every square is drawn twice: an empty one that never moves, and, where there were
    # contributions, a coloured one on top that fades away. Fading a fill from one colour
    # to another would need a rule per colour as well as per instant; fading opacity over
    # a square that is already the right colour needs one rule per instant, and the eaten
    # graph is left looking exactly like an empty week on the real profile.
    out.append("<g>")
    for (column, row) in cells:
        out.append(f'<rect x="{route.x(column) - cell / 2:.0f}" y="{route.y(row) - cell / 2:.0f}" '
                   f'width="{cell}" height="{cell}" rx="2" fill="{theme["empty"]}"/>')
    out.append("</g><g>")
    for (column, row), level in cells.items():
        if not level:
            continue
        index = times[route.pct(route.eaten(column, row))]
        out.append(f'<rect class="g e{index}" x="{route.x(column) - cell / 2:.0f}" '
                   f'y="{route.y(row) - cell / 2:.0f}" width="{cell}" height="{cell}" '
                   f'rx="2" fill="{theme["scale"][level - 1]}"/>')
    out.append("</g>")

    # --- ghosts, then Pac-Man on top ----------------------------------------
    # They ride the same keyframes, started late, which is what makes them trail him.
    # `animation-fill-mode: backwards` parks them off-canvas until their turn comes.
    for i, colour in enumerate(theme["ghosts"][:config.PACMAN_GHOSTS]):
        delay = round((i + 1) * config.PACMAN_TRAIL, 2)
        out.append(f'<g class="g walk" style="animation-delay:{delay}s">'
                   f"{ghost(radius * 0.92, colour, theme)}</g>")

    # One moving group carrying two sprites that take turns being visible: the left-facing
    # Pac-Man is a mirrored copy rather than a flipped one, for the same reason the mouth
    # is a flip-book — a `scale(-1,1)` would need an origin, and `translate` does not.
    mouths = list(config.PACMAN_MOUTH) + list(reversed(config.PACMAN_MOUTH))[1:-1]
    out.append('<g class="g walk">')
    for facing, right in (("faceR", True), ("faceL", False)):
        out.append(f'<g class="g s {facing}">')
        for i, mouth in enumerate(mouths):
            out.append(f'<path class="chomp c{i}" d="{wedge(radius, mouth, right)}" '
                       f'fill="{theme["pacman"]}"/>')
        out.append("</g>")
    out.append("</g></svg>")

    return "".join(out)


# =============================================================================
# (6) EXECUTOR
# =============================================================================

def main():
    """
    Fetch the calendar once and write both themes.

    Raises:
        SystemExit: when the API cannot be reached and `--demo` was not asked for, so a
            failed run leaves the previous SVGs on the branch instead of publishing an
            empty graph.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="skip the API and invent a calendar, for rendering locally")
    parser.add_argument("--out", default=DIST, help="directory to write the SVGs into")
    args = parser.parse_args()

    if args.demo or not TOKEN:
        if not args.demo:
            print("no GITHUB_TOKEN in the environment — falling back to a demo calendar")
        weeks = demo_calendar()
    else:
        try:
            weeks = fetch_calendar(USER, TOKEN)
        except (urllib.error.URLError, RuntimeError, KeyError) as error:
            sys.exit(f"could not read the contribution calendar of {USER}: {error}")

    if not weeks:
        sys.exit("the contribution calendar came back empty — refusing to draw nothing")

    os.makedirs(args.out, exist_ok=True)
    for name, filename in (("light", "github-pacman.svg"), ("dark", "github-pacman-dark.svg")):
        path = os.path.join(args.out, filename)
        with open(file=path, mode="w", encoding="utf-8") as file:
            file.write(draw(weeks, name))
        print(f"  wrote   {path}  ({os.path.getsize(path) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
