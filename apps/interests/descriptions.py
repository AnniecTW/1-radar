"""Internal descriptions for the seeded interests, keyed by slug. Shared by migration 0003 and seed_mock_data."""

# What each seeded interest covers, written like an event listing because it is compared with event
# embeddings. Internal only: the onboarding picker still shows just the name.
DESCRIPTIONS = {
    'tech': 'Tech: coding workshops, hackathons, AI and software talks, robotics, app demos',
    'career': 'Career: career fairs, resume reviews, interview prep, internship and job info sessions',
    'study': 'Study: study groups, tutoring, exam review sessions, library workshops, quiet study nights',
    'science': 'Science: research talks, lab open houses, science seminars, astronomy nights, poster sessions',
    'cultural': (
        'Cultural: cultural student association events, heritage celebrations, international nights, '
        'language exchanges'
    ),
    'food': 'Food: free food, food festivals, cooking classes, tastings, potlucks, bake sales',
    'gaming': 'Gaming: video game tournaments, board game nights, esports, tabletop and card games',
    'networking': 'Networking: mixers, alumni meetups, professional socials, meet-and-greets',
    'arts': 'Arts: art exhibits, gallery openings, painting and craft workshops, theater, dance performances',
    'music': 'Music: concerts, open mics, jam sessions, choir and band performances, DJ nights',
    'film': 'Film: movie screenings, film festivals, filmmaking workshops, director talks',
    'writing': 'Writing: poetry readings, writing workshops, book clubs, author talks, open mic poetry',
    'sports': 'Sports: intramural games, varsity games, pickup basketball and soccer, watch parties',
    'wellness': 'Wellness: meditation, mental health workshops, stress relief, mindfulness, self-care events',
    'outdoors': 'Outdoors: hikes, camping trips, park cleanups, outdoor adventures, nature walks',
    'fitness': 'Fitness: yoga, group workouts, running clubs, dance fitness, gym classes',
    'volunteering': (
        'Volunteering: volunteer shifts, service projects, fundraisers, community cleanups, charity drives'
    ),
    'faith': 'Faith: worship services, religious student groups, interfaith dialogues, prayer and study gatherings',
    'entrepreneurship': (
        'Entrepreneurship: startup pitches, founder talks, business plan competitions, innovation workshops'
    ),
    'activism': 'Activism: rallies, advocacy workshops, voter registration, social justice discussions, town halls',
}
