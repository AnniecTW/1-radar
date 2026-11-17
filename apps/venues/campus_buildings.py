"""Campus buildings where events happen, for matching flyer locations (Snap-a-Flyer) and map pins.

Names and street addresses come from the University of Illinois Facilities & Services "Building List
A-Z" (fs.illinois.edu, checked Nov 2026). Aliases are the short names people print on flyers.
`seed_campus_buildings` looks up each address with MapTiler to get its map position, except where
`lat`/`lon` are given here.

`existing` buildings may already be in the database under exactly this name: for those the command
only adds aliases and the short code, and never moves their pin.
"""

BUILDINGS = [
    # name, code, address, city, aliases
    {'name': 'Smith Memorial Hall', 'address': '805 S Mathews Ave', 'city': 'Urbana',
     'aliases': ['Smith Music Hall', 'Smith Recital Hall']},
    {'name': 'Henry Administration Building', 'address': '506 S Wright St', 'city': 'Urbana',
     'aliases': ['David Dodds Henry Administration Building', 'Henry Admin Building', 'Henry Building']},
    {'name': 'Student Dining and Residential Programs Building', 'code': 'SDRP',
     'address': '301 E Gregory Dr', 'city': 'Champaign',
     'aliases': ['Ikenberry Commons', 'Ikenberry Dining Center', 'Ikenberry']},
    {'name': 'Altgeld Hall', 'address': '1409 W Green St', 'city': 'Urbana', 'aliases': []},
    {'name': 'Lincoln Hall', 'address': '702 S Wright St', 'city': 'Urbana', 'aliases': []},
    {'name': 'Gregory Hall', 'address': '810 S Wright St', 'city': 'Urbana', 'aliases': []},
    {'name': 'English Building', 'address': '608 S Wright St', 'city': 'Urbana', 'aliases': []},
    {'name': 'Natural History Building', 'code': 'NHB', 'address': '1301 W Green St', 'city': 'Urbana',
     'aliases': []},
    {'name': 'Noyes Laboratory', 'address': '505 S Mathews Ave', 'city': 'Urbana',
     'aliases': ['Noyes Laboratory of Chemistry', 'Noyes Lab']},
    {'name': 'Business Instructional Facility', 'code': 'BIF', 'address': '515 E Gregory Dr',
     'city': 'Champaign', 'aliases': []},
    {'name': 'Wohlers Hall', 'address': '1206 S Sixth St', 'city': 'Champaign', 'aliases': []},
    {'name': 'David Kinley Hall', 'code': 'DKH', 'address': '1407 W Gregory Dr', 'city': 'Urbana',
     'aliases': []},
    {'name': 'Campus Instructional Facility', 'code': 'CIF', 'address': '1405 W Springfield Ave',
     'city': 'Urbana', 'aliases': []},
    {'name': 'Electrical and Computer Engineering Building', 'code': 'ECEB', 'address': '306 N Wright St',
     'city': 'Urbana', 'aliases': ['ECE Building']},
    {'name': 'Digital Computer Laboratory', 'code': 'DCL', 'address': '1304 W Springfield Ave',
     'city': 'Urbana', 'aliases': []},
    {'name': 'Everitt Laboratory', 'address': '1406 W Green St', 'city': 'Urbana',
     'aliases': ['William L. Everitt Laboratory', 'Everitt Lab']},
    {'name': 'Loomis Laboratory', 'address': '1110 W Green St', 'city': 'Urbana',
     'aliases': ['Loomis Laboratory of Physics', 'Loomis Lab']},
    {'name': 'Engineering Hall', 'address': '1308 W Green St', 'city': 'Urbana', 'aliases': []},
    {'name': 'Beckman Institute', 'address': '405 N Mathews Ave', 'city': 'Urbana',
     'aliases': ['Beckman Institute for Advanced Science and Technology']},
    {'name': 'Davenport Hall', 'address': '607 S Mathews Ave', 'city': 'Urbana', 'aliases': []},
    {'name': 'Mumford Hall', 'address': '1301 W Gregory Dr', 'city': 'Urbana', 'aliases': []},
    {'name': 'Illini Union Bookstore', 'code': 'IUB', 'address': '807 S Wright St', 'city': 'Champaign',
     'aliases': []},
    {'name': 'Huff Hall', 'address': '1206 S Fourth St', 'city': 'Champaign', 'aliases': ['George Huff Hall']},
    {'name': 'Main Library', 'address': '1408 W Gregory Dr', 'city': 'Urbana', 'aliases': ['University Library']},
    # Coordinates from Wikipedia ("Memorial Stadium (Champaign)").
    {'name': 'Memorial Stadium', 'address': '1402 S First St', 'city': 'Champaign', 'aliases': [],
     'lat': 40.09917, 'lon': -88.23583},
    # Already in Radar's demo data: only aliases and codes are added.
    {'name': 'Illini Union', 'address': '1401 W Green St', 'city': 'Urbana', 'aliases': ['The Union'],
     'existing': True},
    {'name': 'State Farm Center', 'address': '1800 S First St', 'city': 'Champaign',
     'aliases': ['Assembly Hall'], 'existing': True},
    {'name': 'Foellinger Auditorium', 'address': '709 S Mathews Ave', 'city': 'Urbana',
     'aliases': ['Foellinger'], 'existing': True},
    {'name': 'Krannert Center for the Performing Arts', 'code': 'KCPA', 'address': '500 S Goodwin Ave',
     'city': 'Urbana', 'aliases': ['Krannert Center'], 'existing': True},
    {'name': 'Activities and Recreation Center (ARC)', 'code': 'ARC', 'address': '201 E Peabody Dr',
     'city': 'Champaign', 'aliases': ['Activities & Recreation Center'], 'existing': True},
    {'name': 'Campus Recreation Center East', 'code': 'CRCE', 'address': '1102 W Gregory Dr', 'city': 'Urbana',
     'aliases': ['Campus Recreation Center - East'], 'existing': True},
    {'name': 'Siebel Center for Computer Science', 'address': '201 N Goodwin Ave', 'city': 'Urbana',
     'aliases': ['Thomas M. Siebel Center for Computer Science', 'Siebel CS'], 'existing': True},
    {'name': 'Grainger Engineering Library', 'address': '1301 W Springfield Ave', 'city': 'Urbana',
     'aliases': ['Grainger Library', 'Grainger Engineering Library Information Center'], 'existing': True},
    {'name': 'Undergraduate Library', 'code': 'UGL', 'aliases': [], 'existing': True},
    {'name': 'Main Quad', 'aliases': ['the Quad'], 'existing': True},
]

# Campus centre and a box around Champaign-Urbana: lookups outside it are rejected.
CAMPUS_CENTER = (-88.2272, 40.1020)  # lon, lat
CAMPUS_BBOX = (-88.30, 40.05, -88.17, 40.15)  # west, south, east, north
