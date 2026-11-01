from django.shortcuts import render


def dashboard(request):
    events = [
        {
            'title': 'Python Study Jam', 'date': 'Tomorrow', 'time': '5:00 – 7:00 PM',
            'venue': 'Grainger Library, Rm 3th', 'category': 'Study', 'secondary': 'Tech',
            'description': 'Group study session with guided Python projects. All skill levels welcome!',
            'insight': 'Great for building skills and meeting fellow CS students.', 'going': '48',
            'image': 'https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=900&q=85',
        },
        {
            'title': 'Volleyball Meetup', 'date': 'This Fri', 'time': '6:00 – 8:00 PM',
            'venue': 'AFH Moria Court', 'category': 'Sports', 'secondary': 'Social',
            'description': 'Casual volleyball games for all skill levels. Come play, meet new people, and unwind!',
            'insight': 'Popular with students looking to stay active and meet friends.', 'going': '62',
            'image': 'https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=900&q=85',
        },
        {
            'title': 'Art & Coffee', 'date': 'This Sat', 'time': '10:00 AM – 12:00 PM',
            'venue': 'Expresso Royale', 'category': 'Arts', 'secondary': 'Social',
            'description': 'Bring your sketchbook, grab a coffee, and create together. All are welcome!',
            'insight': 'Bring your sketchbook, grab a coffee, and let your creativity flow.', 'going': '36',
            'image': 'https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=900&q=85',
        },
        {
            'title': 'AI Workshop: Build with LLMs', 'date': 'Sat, Oct 25', 'time': '3:00 – 4:00 PM',
            'venue': 'Siebel Center, Sim 7004', 'category': 'AI / Tech', 'secondary': 'Workshop',
            'description': 'Hands-on workshop to build local projects with OpenAI APIs, for your experience level.',
            'insight': 'Top pick for students interested in practical course-work projects.', 'going': '112',
            'image': 'https://images.unsplash.com/photo-1531482615713-2afd69097998?auto=format&fit=crop&w=900&q=85',
        },
    ]
    trending = [
        {'title': 'Champaign Night Market', 'meta': 'Thu, Oct 24 · Uncain Square Hall', 'image': 'https://images.unsplash.com/photo-1517457373958-b7bdd4587205?auto=format&fit=crop&w=900&q=85'},
        {'title': 'UIUC Focal Point Concert', 'meta': 'Sat, Oct 27 · Foellinger Auditorium', 'image': 'https://images.unsplash.com/photo-1501386761578-eac5c94b800a?auto=format&fit=crop&w=900&q=85'},
        {'title': 'Boneyard Creek Cleanup', 'meta': 'Sun, Oct 27 · Boneyard Creek Trail', 'image': 'https://images.unsplash.com/photo-1559027615-cd4628902d4a?auto=format&fit=crop&w=900&q=85'},
    ]
    return render(request, 'dashboard.html', {'events': events, 'trending': trending})
