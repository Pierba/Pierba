# =============================================================================
# CREDENTIALS
# =============================================================================
USERNAME = "Pierba"


# =============================================================================
# TABLE
# =============================================================================
MAX_DESCRIPTION = 220   # Max length of the description
MAX_STACK       = 6     # Max number of languages per project
MIN_SHARE       = 0.05  # Ignore languages below this % of the repository
INCLUDE_FORKS   = True  # Show forked repositories too, each labelled with the repository it came from


# =============================================================================
# BADGES
# =============================================================================
SATURATION = (0.85, 1.00)  # Near-full, so every hue reads as a colour and not a grey
LIGHTNESS  = (0.34, 0.50)  # Kept wide so same-hue languages still differ in depth

# Mixed into the hash before the colour is derived, so it re-rolls every badge at once while staying identical from run to run
# A hash spreads names uniformly, so a few languages can always land on neighbouring hues by chance and read as the same colour
# Bump this to any other number to draw the whole palette again
COLOR_SALT = 148

# The ceiling badge colours are darkened to contrast against white text
# Is (1 + 0.05) / (L + 0.05), so 0.25 is 3.5:1, enough for the bold, shadowed uppercase shields renders
MAX_LUMINANCE = 0.25


# =============================================================================
# PAC-MAN
# =============================================================================
# Geometry, in SVG user units. CELL and GAP are GitHub's own contribution-graph metrics,
# so the drawn maze lines up with the graph on the profile page
PACMAN_CELL   = 11              # Side of one contribution square
PACMAN_GAP    = 3               # Space between two squares
PACMAN_PITCH  = PACMAN_CELL + PACMAN_GAP
PACMAN_RADIUS = 8               # Pac-Man's radius, deliberately wider than a square so he overlaps the row he is eating

# Timing, in seconds. STEP is what sets the speed: it is the time to cross one column,
# so the whole loop is roughly (7 x weeks x STEP) and every other value below is a trim on it
PACMAN_STEP  = 0.05             # One column
PACMAN_TURN  = 0.32             # The drop from one row down to the next
PACMAN_FADE  = 0.22             # How long an eaten square takes to disappear
PACMAN_TAIL  = 1.6              # Pause on the emptied graph before it grows back and the loop restarts
PACMAN_LEAD  = 4                # Columns walked off-canvas before the first square and after the last

# Sprites
PACMAN_CHOMP  = 0.4             # One open-close of the mouth
PACMAN_MOUTH  = (0, 12, 24, 36, 44)  # Half-angles, in degrees, of the flip-book frames. Played out and back
PACMAN_GHOSTS = 4               # 0 to 4. They only chase, they never catch him
PACMAN_TRAIL  = 0.28            # Delay between one ghost and the next, so they string out behind him