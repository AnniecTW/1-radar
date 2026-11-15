# Radar: Development Progress and Roadmap (P2-A3)

As of November 15, 2026. The Django foundation and AI search are working. The main work left before the December 8 final submission is Snap-a-Flyer, embedding-based recommendations, evaluation, and deployment.

| Task | Current Status | Responsible Member | Expected Completion |
| --- | --- | --- | --- |
| Django Core Features | Mostly done: accounts with email and campus verification, onboarding, organizations with roles, event creation, RSVP and waitlist, profiles, notifications. Left: flyer upload and review screen, check-in screen for hosts. | Afrillian Ramadhan (sign up/login, onboarding, organizations), Ilona (event creation, profiles, preferences, saves and likes, notifications), Annie Chien (dashboard, permissions); Ayush Shukla (host check-in screen) | Nov 24, 2026 |
| Database and APIs | Done for the draft: 13 apps, 27 models, migrations, map JSON API, attendee CSV export. Left: flyer upload and status APIs. | Ilona (database and models), Annie Chien (map JSON API) | Nov 22, 2026 |
| AI Integration | AI search working with keyword fallback. Recommendations rule-based. Snap-a-Flyer tested against the model API only; task queue (Celery and Redis) not set up. | Annie Chien (semantic search, recommendations), Ayush Shukla (Snap-a-Flyer) | Nov 30, 2026 |
| Evaluation and Testing | 198 automated tests, all passing. Search tested on 28 queries: 14/14 easy, 7/14 hard. Left: 5-test results table, failure analysis, one measured improvement. | Ayush Shukla; Annie Chien (search evaluation) | Dec 3, 2026 |
| Deployment | Not started. Production settings only allow localhost. | Annie Chien | Dec 1, 2026 |
| Documentation | README and README_AI written. Left: deployment steps, evaluation results, cost and scalability write-up. | Ilona (README), Annie Chien (README_AI), Ayush Shukla (remaining write-ups) | Dec 7, 2026 |
