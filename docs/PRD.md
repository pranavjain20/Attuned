# Attuned: Product Requirements

This describes Attuned as it is now. It replaces an earlier planning document from March 2026, which described a design I've since changed (see [DECISIONS.md](DECISIONS.md)).

## The problem

WHOOP's recovery score answers one question well: how prepared is my body to perform today? It leans mostly on HRV (heart rate variability, a sign of whether the nervous system has recovered overnight). That's the right question for an athlete deciding how hard to train.

Most people who wear a WHOOP aren't deciding how hard to train. They look at the number in the morning to find out how they're going to feel, and on some days the number and the feeling point in opposite directions. On April 7, 2026 my WHOOP said 81% and I felt drained; my HRV had bounced back but my REM sleep was well below my usual. The next day it said 59% and I felt the best I had all week.

There's a second problem. Even a better number changes nothing on its own. "Your score is 42" doesn't tell you what to do, and people rarely change habits because of a score.

## Who it's for

- **First, me:** a long-time WHOOP wearer who isn't training for competition and wants to know how the day is likely to feel.
- **Then, people like me:** WHOOP wearers who listen to music most days and would use something that needs no extra effort. A few friends run it on their own WHOOP and Spotify accounts.
- **Not for:** athletes planning training load (WHOOP's recovery already serves them), or anyone looking for medical or mental-health advice.

## Goals

1. **Answer "how am I likely to feel today?"** with one 0–100 number built from my WHOOP data, compared with my own usual rather than with population averages.
2. **Make it comparable to WHOOP at a glance.** Same scale and same red/yellow/green bands, so the only thing that differs is which days each one calls good or bad.
3. **Explain every score in plain words,** using real numbers against my usual ("You got 1.2 h of REM sleep, less than your usual 1.7 h"), and say why it differs from WHOOP when it does.
4. **Turn the score into something I already do:** a daily playlist from my own library, chosen for what should help given how I'll likely feel.
5. **Let me ask for music in my own words** and have today's score tune the answer without overriding what I asked for.
6. **Be honest about what's known.** Research is cited only for the problem. Every design choice is labelled as mine.

## Non-goals

- Replacing or "correcting" WHOOP's recovery. It answers a different question and answers it well.
- Diagnosing anything, or claiming a measurable effect of a playlist on mood or physiology.
- Recommending songs outside your own library.
- Matching your mood. A low day doesn't get sad songs; it gets music meant to help you settle.
- A mobile app, accounts, or hosting for strangers. It runs locally.

## The experience

**Each morning, automatically.** Attuned syncs last night's WHOOP data, scores the day, and pushes a dated playlist to Spotify, for example "Apr 7 — Ease Into It". The name and description say what the music is for ("Built to keep you level").

**The day page.** One page per day, in this order:

- **Two rings.** The Attuned score first, WHOOP's recovery second, both on the same 0–100 scale and colours.
- **Why they differ.** What drove WHOOP's score (the change in HRV), then each sleep change as a percentage with one line on what it means for how you'll feel, for example "You slept 5% less than usual. Even small amounts of lost sleep make it harder to focus, and they add up over days without you noticing." Each meaning line says only what a study in the research doc supports.
- **What moved the score.** Up to three signals, each with today's value and my usual, and an arrow for which way it pushed.
- **Health metrics.** HRV, resting heart rate, sleep, REM, deep sleep, sleep efficiency and 7-night sleep debt.
- **Today's playlist,** styled like Spotify: album art, a summary of what's in it ("Slower, softer, mostly calm, romantic Bollywood songs from your library"), why that kind of music should help with linked sources, and one plain reason under each song ("A romantic Bollywood song that keeps the mood level. A long-time favourite.").

**The WhatsApp DJ.** I text a request and get a Spotify playlist back. The request drives the picks. The Attuned score only calibrates them: a vague "something upbeat" on a low day might get "moderate or full energy?" in reply. A specific request is honoured whatever the score says.

## How the playlist follows the score

- **Low score** (my lower days): built to help me settle. Slower, softer, calmer songs.
- **Middle score** (a usual day): built to keep me level. Steady, warm, familiar songs.
- **High score** (my best days): built to give me a lift. Brighter, faster songs.

The shift is gradual. A slightly lower score gives a slightly calmer playlist, with no sudden jumps at a threshold.

## How I'd know it works

**Already checked**

- The score separates from WHOOP on the days I expected. April 7 (felt drained, WHOOP 81) scores 57 on Attuned.
- On my history, the score moves with WHOOP most days but disagrees in a consistent pattern: lower than WHOOP after a night of broken or short sleep with a high HRV, higher than WHOOP after a long, deep night with a low HRV.
- The playlist actually follows the score. Calm days and energy days now draw from separate songs, and calm-day songs are measurably slower and softer than energy-day songs.
- Every explanation is generated from the real numbers and checked for false statements (for example, it never calls a short night "unbroken sleep").

**Not yet shown**

- **That the score matches how people feel.** So far it has been checked against one person's memory of specific days. That's a hypothesis, not evidence.
- **That it beats WHOOP for this question.** April 8, the day I felt best, scores 59 on both.

**The next step: daily check-ins.** A one-tap "how do you feel?" each morning, before seeing either score. Then:

- **The success criterion:** over several weeks, the Attuned score agrees with the check-ins more often than WHOOP's recovery does, for more than one person.
- **The calibration:** the check-ins replace WHOOP's red/yellow/green proportions as the scale, and show whether sleep really deserves twice the weight of the heart signals.
- **For the music:** do people play the daily playlist, skip less, and say it fit the day?

## What I deliberately didn't build

- **A 1:1 copy of WHOOP's inputs.** WHOOP's recovery isn't an input to the Attuned score. Including it would count HRV, heart rate and sleep twice and make the Attuned ring a partial echo of the WHOOP ring next to it.
- **Mood buttons or questionnaires inside the playlist flow.** The daily playlist needs no input. Check-ins are planned for testing the score, not as a step before music.
- **Songs from outside your library.** Familiar songs are what you'd choose to play anyway, and they avoid the risk of a recommendation you hate on a bad morning.
- **Extra smoothing between days.** The playlist changes when the day changes. Smoothing it would mean ignoring today's score.
- **Claims the research doesn't make.** No "research-backed weights", no "your own music calms you more" (the studies don't show that), no health claims under songs.
