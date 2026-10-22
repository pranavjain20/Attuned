# Attuned — Privacy Policy

**Last updated:** October 21, 2026

Attuned is a personal project. It runs on my own computer for me and a small group of friends who connect their own WHOOP and Spotify accounts. It is not a commercial service.

## Data collected

- WHOOP recovery and sleep data, through the WHOOP API, with each person's own authorization.
- Spotify listening history, liked songs and top tracks, through the Spotify API, with each person's own authorization.
- Messages sent to the WhatsApp DJ, if a person uses it.

## How it's used

Data is stored in a local SQLite database, one per person, on my computer. It is used only to compute each person's daily feeling score and to build playlists from their own Spotify library.

## Services that receive data

To do that, Attuned sends limited data to these services:

- **OpenAI and Anthropic:** song names, artists and descriptive tags, to classify songs; and the text of WhatsApp DJ requests with a short plain-language summary of the day's score, to pick songs. No WHOOP account details are sent.
- **Twilio:** WhatsApp DJ messages, which pass through Twilio to reach Attuned.
- **Soundcharts and YouTube:** song names and artists, to look up tempo and fetch short audio clips for analysis.
- **Spotify:** the playlists Attuned creates are saved to the person's own Spotify account.

## What's public

My own day-by-day page (my scores, health metrics and playlists) is published on purpose, as a demonstration. Friends' data is never published.

## No tracking

No analytics, advertising or tracking of any kind.

## Contact

Pranav Jain — github.com/pranavjain20
