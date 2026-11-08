"""Display settings for discovery pages: an icon (Lucide name) and colour per category slug."""

CATEGORY_CHIP_COUNT = 7
WEEKEND_SUMMARY_ROWS = 6
MIN_SIGNUPS_TO_SHOW = 10
SIGNUP_WINDOW_DAYS = 30

DEFAULT_CATEGORY_STYLE = ('tag', 'slate')

# Colour names map to CSS classes (.tone-<name>) in landing.css, all drawn from the cream/terracotta palette.
CATEGORY_STYLES = {
    'activism': ('megaphone', 'rose'),
    'arts': ('palette', 'terra'),
    'career': ('briefcase', 'navy'),
    'cultural': ('globe', 'teal'),
    'entrepreneurship': ('rocket', 'amber'),
    'faith': ('church', 'plum'),
    'film': ('clapperboard', 'slate'),
    'fitness': ('dumbbell', 'green'),
    'food': ('utensils', 'amber'),
    'gaming': ('gamepad-2', 'plum'),
    'music': ('music', 'rose'),
    'networking': ('network', 'navy'),
    'outdoors': ('trees', 'green'),
    'science': ('flask-conical', 'teal'),
    'sports': ('volleyball', 'terra'),
    'study': ('book-open', 'blue'),
    'tech': ('cpu', 'blue'),
    'volunteering': ('hand-heart', 'rose'),
    'wellness': ('leaf', 'green'),
    'writing': ('pen-line', 'slate'),
}

# Hero backgrounds for trending events that have no cover image of their own. Display only; nothing is
# saved to the event. Free photos under the Unsplash License (https://unsplash.com/license).
UNSPLASH_PHOTO_URL = 'https://images.unsplash.com/photo-{photo_id}?auto=format&fit=crop&w=1600&q=80'
DEFAULT_HERO_PHOTO = '1638616122105-804db5fbef63'  # campus clock tower in autumn
_TECH = '1531482615713-2afd69097998'  # students coding together
_STUDY = '1523240795612-9a054b0db644'  # group study in a library
_SPORTS = '1517466787929-bc90951d0974'  # soccer on a campus field
_MUSIC = '1501386761578-eac5c94b800a'  # concert crowd
_GATHERING = '1517457373958-b7bdd4587205'  # evening gathering under string lights
_VOLUNTEER = '1559027615-cd4628902d4a'  # volunteer at an event
_FRIENDS = '1529156069898-49953e39b3ac'  # friends arm in arm
CATEGORY_HERO_PHOTOS = {
    'tech': _TECH, 'science': _TECH, 'gaming': _TECH, 'entrepreneurship': _TECH,
    'study': _STUDY, 'writing': _STUDY, 'career': _STUDY, 'networking': _STUDY,
    'sports': _SPORTS, 'fitness': _SPORTS, 'outdoors': _SPORTS,
    'music': _MUSIC, 'film': _MUSIC,
    'cultural': _GATHERING, 'faith': _GATHERING,
    'volunteering': _VOLUNTEER, 'activism': _VOLUNTEER,
    'wellness': _FRIENDS,
    'arts': '1757085242652-f8cd4d3de889',  # people painting at a table
    'food': '1686574086026-9f02b82f4765',  # sharing food on a picnic blanket
}
