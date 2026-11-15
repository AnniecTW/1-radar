# Radar: Development Progress and Roadmap (P2-A3)

As of November 15, 2026. The Django foundation, AI search and a first version of Snap-a-Flyer are working. The main work left before the December 8 final submission is embedding-based recommendations, evaluation with real flyers, and deployment.

| Task | Current Status | Responsible Member | Expected Completion |
| --- | --- | --- | --- |
| Django Core Features | Mostly done: accounts with email and campus verification, onboarding, organizations with roles, event creation, RSVP and waitlist, profiles, notifications. Left: check-in screen for hosts. | Afrillian Ramadhan (sign up/login, onboarding, organizations), Ilona (event creation, profiles, preferences, saves and likes, notifications), Annie Chien (dashboard, permissions); Ayush Shukla (host check-in screen) | Nov 24, 2026 |
| Database and APIs | Done for the draft: 13 apps, 27 models, migrations, map JSON API, attendee CSV export. Left: query tuning once real data grows. | Ilona (database and models), Annie Chien (map JSON API) | Nov 22, 2026 |
| AI Integration | AI search working with keyword fallback. Snap-a-Flyer working with a manual-form fallback; tested on 7 real flyers (7/7 read, 40 of 42 required fields filled, 4 of 7 matched to a campus building, 2.9 s average). Left: embedding-based recommendations, HEIC and PDF flyers, image moderation. | Annie Chien (semantic search, recommendations), Ayush Shukla (Snap-a-Flyer) | Nov 30, 2026 |
| Evaluation and Testing | 253 automated tests, all passing (55 for Snap-a-Flyer and campus buildings, with the model mocked). Search tested on 28 queries: 14/14 easy, 7/14 hard. Left: 5-test results table, failure analysis, one measured improvement. | Ayush Shukla; Annie Chien (search evaluation) | Dec 3, 2026 |
| Deployment | Not started. Production settings only allow localhost. | Annie Chien | Dec 1, 2026 |
| Documentation | README and README_AI written, including Snap-a-Flyer setup. Left: deployment steps, evaluation results, cost and scalability write-up. | Ilona (README), Annie Chien (README_AI), Ayush Shukla (remaining write-ups) | Dec 7, 2026 |
