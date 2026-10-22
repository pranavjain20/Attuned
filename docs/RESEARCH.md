# Attuned — Research

**Last checked:** October 21, 2026

This document says what published research Attuned rests on, and just as importantly, what it does not rest on. Research is cited for one thing only: showing that the problem Attuned tackles is real. Everything Attuned does about that problem (the signals, weights, thresholds and song-scoring rules) is our own design. We were inspired by what we read, but no study prescribes it.

Earlier versions of this file cited many more sources. Several were removed after checking showed they were misattributed or did not say what we had claimed. Git history keeps the old versions.

## Terms used here

- **HRV (heart rate variability):** how much the gap between heartbeats varies. Higher HRV usually means the body's "rest and digest" side is more active.
- **Parasympathetic / sympathetic:** the two sides of the autonomic nervous system, the part that runs heart rate and breathing without you thinking about it. Parasympathetic is "rest and digest"; sympathetic is "fight or flight".
- **Association:** two things move together. It does not show that one causes the other.
- **Between-person:** people who average more of X also tend to have more of Y. It compares different people.
- **Within-person:** on days when *you* have more X than your own usual, you also have more Y. An app that reads one person's data needs this kind.
- **Readiness score:** a single daily number from a wearable that says how ready your body is to train. WHOOP's is called Recovery.

---

## 1. The problem, in three claims

### Claim 1: How you sleep is tied to how you feel the next day

- **Triantafillou et al. 2019 (JMIR Mental Health).** 208 adults rated their sleep quality and mood on a phone every day for 6 weeks. Most had depression, anxiety or both; about a quarter were controls. When each person's ratings were compared with their own average, sleep quality was linked to next-day mood about 2.6 times as strongly as mood was linked to that night's sleep (b = .344 vs .132). On raw ratings, the two directions were about equal. Everything was self-reported, and it is an association.
  - *How it shaped Attuned:* sleep is a first-class input, and every signal is compared with the person's own average rather than with population norms.
- **Le et al. 2025 (Annals of Behavioral Medicine).** 96 healthy young adults, 15 nights each, with sleep measured by an EEG device (a headband that reads brain waves). Between people, those who got 30 more minutes of deep sleep in place of light sleep reported more positive mood on waking (+0.38). Within a person, there was no link to positive mood, but a night with less REM sleep than usual was followed by slightly more negative mood. Observational.
  - *How it shaped Attuned:* deep sleep and REM are tracked as separate signals instead of being folded into "total sleep".
- **Pierson-Bartel & Ujma 2024 (Scientific Reports).** 246 people, 1,318 nights, measured with a home EEG headband. On nights when a person slept more efficiently than their own usual, they rated their sleep better. Sleep efficiency was the most important single measure. But objective sleep explained only about a fifth of how people rated their sleep, and the outcome was perceived sleep quality, not mood.
  - *How it shaped Attuned:* sleep efficiency is one of the heaviest signals. The "only a fifth" result is also a reminder that body data is not the same as feeling.
- **Van Dongen et al. 2003 (SLEEP).** 48 adults spent 4, 6 or 8 hours in bed per night for 14 days. Six hours or less built up thinking and reaction-time deficits comparable to up to two nights without any sleep. People's own sleepiness ratings levelled off, so they largely did not notice how impaired they were. This was a controlled lab experiment, so here short sleep did cause the deficits.
  - *How it shaped Attuned:* rolling sleep debt is tracked as its own signal, because short sleep adds up even when you don't feel it.

### Claim 2: Readiness scores and how you feel can come apart

- **Yang et al. 2019 (Sleep).** 21 healthy adults spent 22 days in a hospital lab, with repeated blocks of restricted sleep followed by recovery nights. HRV bounced back above normal on recovery nights, while deep sleep simply returned to baseline. HRV and sleep stages recovered on different timetables, and full recovery of the nervous system took at least three nights.
  - *How it shaped Attuned:* a single good HRV night is not allowed to override what sleep says.
- **Lundstrom et al. 2024 (International Journal of Sports Science & Coaching).** 23 college swimmers wore WHOOP straps during heavy training. Raw HRV tracked their scores on a validated stress questionnaire (r ≈ −0.46), but WHOOP's Recovery score showed no significant relationship with it. (WHOOP's Strain score tracked stress only in the 10 men, in an unexpected direction.) A small study, and an association.
  - *How it shaped Attuned:* it reads the raw signals (HRV, resting heart rate, sleep stages) instead of relying on the Recovery score alone.

### Claim 3: Music changes your mental and physical state

- **Bernardi, Porta & Sleight 2006 (Heart).** 24 people (12 musicians, 12 non-musicians) heard six music styles from 55 to 150 beats per minute (BPM). Breathing, blood pressure and heart rate rose with faster tempo, in proportion to the speed. A 2-minute silence afterwards lowered heart rate, blood pressure and breathing even below the starting level. The authors found that all measures "were related to the tempo but not to music preference."
  - *How it shaped Attuned:* tempo gets the largest weight when scoring a song, and it is scored on a smooth curve rather than in buckets.
- **Ooishi et al. 2017 (PLOS ONE).** Slow-tempo music raised salivary oxytocin and the parasympathetic part of HRV, and lowered heart rate. Fast-tempo music lowered cortisol (a stress hormone) and shifted heart rhythm toward the sympathetic side.
  - *How it shaped Attuned:* slow songs are aimed at rest and fast songs at energy, because both directions measurably shift the body.
- **Mojtabavi et al. 2020 (Complementary Therapies in Clinical Practice).** A systematic review (a structured summary of all the studies it could find) of 29 studies with 1,368 people. Music raised HRV and parasympathetic activity in 26 of them. The authors warn that most studies had a high risk of bias.
  - *How it shaped Attuned:* it gives general confidence that music moves the same HRV signal WHOOP reads. Because of the bias warning, we treat it as direction, not as precise numbers.
- **Salimpoor et al. 2011 (Nature Neuroscience).** Brain scans showed dopamine (the brain's reward chemical) released both while people anticipated the peak moment of music they had chosen because it gives them chills, and at the peak itself.
  - *How it shaped Attuned:* playlists come only from the user's own library, since self-chosen music engages the reward system.
- **Hennessy et al. 2025 (Human Brain Mapping).** 57 participants. Personally nostalgic songs activated self-reflection and reward networks in the brain more than familiar or unfamiliar songs matched for sound.
  - *How it shaped Attuned:* the "grounding" state leans on warm, familiar songs from your own history.

**What this does not show.** Neither Salimpoor nor Hennessy found that your own music changes your *body* more than other music. Bernardi found the body followed tempo, not preference. So the honest claim is: tempo moves your body, and personally meaningful songs have stronger reward and emotional effects in the brain. We do not claim your own music is physically more calming.

---

## 2. What WHOOP publicly says about Recovery

Only WHOOP's own public statements are used here. WHOOP does not publish the Recovery formula or its weights, so we make no claims about how the score is calculated beyond what WHOOP says.

- Recovery is "a daily measure of how prepared your body is to perform", and it "dictates how much Strain your body is ready to handle" ([WHOOP Recovery 101](https://www.whoop.com/us/en/thelocker/how-does-whoop-recovery-work-101/)).
- WHOOP says HRV, resting heart rate, sleep and respiratory rate are factored into Recovery ([Recovery 101](https://www.whoop.com/us/en/thelocker/how-does-whoop-recovery-work-101/); [WHOOP HRV explainer](https://www.whoop.com/us/en/thelocker/heart-rate-variability-hrv/)).
- WHOOP says Recovery "relies mostly on HRV, with resting heart rate adding context and sleep adding support" ([WHOOP Podcast 29](https://www.whoop.com/us/en/thelocker/podcast-29-heart-rate-variability-hrv/)).
- WHOOP measures HRV during sleep and says it "calculates it during your deepest sleep each night" ([WHOOP HRV explainer](https://www.whoop.com/us/en/thelocker/heart-rate-variability-hrv/)). WHOOP's wording on exactly which part of the night has changed over time.
- Recovery is calculated when you wake up and "does not change over the day" unless you edit your sleep ([WHOOP developer docs, WHOOP 101](https://developer.whoop.com/docs/whoop-101/)).
- Green is 67–100%, yellow 34–66%, red 0–33% ([Recovery 101](https://www.whoop.com/us/en/thelocker/how-does-whoop-recovery-work-101/)).
- WHOOP itself says "multi-day suppression is a stronger sign" than a single reading ([WHOOP Podcast 29](https://www.whoop.com/us/en/thelocker/podcast-29-heart-rate-variability-hrv/)).

In short: Recovery is built to answer "how ready is my body to take on strain today?" Attuned asks a different question, "how am I likely to feel today, and what music fits?" Claim 2 above is why we think those answers can differ.

---

## 3. Our design (Pranav's own choices)

Everything in this section is a design choice. It was inspired by the reading above, but no study gives these numbers, and none of them should be described as "research-backed".

- **11 signals.** Sleep efficiency, deep sleep, deep-sleep share, REM, total sleep, 7-night sleep debt, HRV, HRV change since yesterday, HRV 7-day trend, resting heart rate and resting heart rate change. Each is turned into a z-score (how many standard deviations today sits from your own 30-day average). WHOOP's Recovery score is not one of them, because it is built from these same signals.
- **Sleep weighted over heart signals, roughly 2:1.** The sleep signals together carry about twice the weight of the HRV and heart-rate signals together. The research supports the direction (sleep matters for how you feel); the ratio is ours.
- **Feeling score.** A daily 0–100 estimate of how Pranav is likely to feel: a weighted average of the signals, ranked among his earlier days and mapped onto his own WHOOP Recovery history so both scores have the same share of red, yellow and green days. Its form, weights and mapping are ours.
- **Sleep-debt cap.** More than 7 hours of debt over 7 days can never count as a good sign, even if it is less debt than your usual.
- **Short-night cap.** After less than 6 hours of sleep, high sleep efficiency or a high deep-sleep share can never count as a good sign.
- **Thresholds.** 14 days of data before personal baselines are trusted, 60 earlier scored days before the 0–100 mapping is used, z-scores clamped at ±2.5.
- **Three states.** Every song and every day is described as a mix of rest (parasympathetic), energy (sympathetic) and grounding (emotional steadiness). A day's mix is set by where its feeling score ranks among earlier days, blended between three fixed points (calm, steady, energy) whose values are ours.
- **Song profiler.** Song scores weight tempo most, then energy, then acousticness, instrumentalness, valence, mode and danceability, plus a mood-tag table. The weights, curve shapes and tag values are ours.
- **Tempo rule.** How audio readings and the classifier's estimate are combined into one tempo, and the 55–165 BPM window, are ours.
- **Cohesion engine.** Playlists are built to sound coherent (genre, era, tempo, mood), using our own similarity weights and caps.

---

## 4. Limits

- **Small studies.** Several sources are small (23 swimmers, 21 lab participants, 24 listeners). Mojtabavi's review warns that most music–HRV studies have a high risk of bias.
- **Mostly associations.** Apart from controlled experiments like Van Dongen 2003 and the music listening studies, these findings show things moving together, not one causing the other.
- **Different questions.** Pierson-Bartel measured perceived sleep quality, not mood. The music studies measured short listening sessions in a lab, not a morning playlist.
- **Our own validation is limited.** Checks of Attuned's weights and labels have used Pranav's own WHOOP and listening data. That is one person, not a study, and the results may not hold for anyone else.

---

## 5. References

Sleep and feeling
- Triantafillou S, Saeb S, Lattie EG, Mohr DC, Kording KP (2019). Relationship Between Sleep Quality and Mood: Ecological Momentary Assessment Study. *JMIR Mental Health* 6(3):e12613. https://doi.org/10.2196/12613
- Le F, Yap Y, Dumuid D, Wiley JF (2025). Daily, prospective associations between sleep architecture and affect: insights from Bayesian multilevel compositional data analysis. *Annals of Behavioral Medicine* 59(1):kaaf050. https://doi.org/10.1093/abm/kaaf050
- Pierson-Bartel R, Ujma PP (2024). Objective sleep quality predicts subjective sleep ratings. *Scientific Reports* 14:5943. https://doi.org/10.1038/s41598-024-56668-0
- Van Dongen HPA, Maislin G, Mullington JM, Dinges DF (2003). The cumulative cost of additional wakefulness: dose-response effects on neurobehavioral functions and sleep physiology from chronic sleep restriction and total sleep deprivation. *SLEEP* 26(2):117-126. https://doi.org/10.1093/sleep/26.2.117

Readiness scores and feeling
- Yang H, Haack M, Dang R, Gautam S, Simpson NS, Mullington JM (2019). Heart rate variability rebound following exposure to persistent and repetitive sleep restriction. *Sleep* 42(2):zsy226. https://doi.org/10.1093/sleep/zsy226
- Lundstrom EA, De Souza MJ, Koltun KJ, Strock NCA, Canil HN, Williams NI (2024). Wearable technology metrics are associated with energy deficiency and psychological stress in elite swimmers. *International Journal of Sports Science & Coaching* 19(4):1578-1587. https://doi.org/10.1177/17479541231206424

Music and state
- Bernardi L, Porta C, Sleight P (2006). Cardiovascular, cerebrovascular, and respiratory changes induced by different types of music in musicians and non-musicians: the importance of silence. *Heart* 92(4):445-452. https://doi.org/10.1136/hrt.2005.064600
- Ooishi Y, Mukai H, Watanabe K, Kawato S, Kashino M (2017). Increase in salivary oxytocin and decrease in salivary cortisol after listening to relaxing slow-tempo and exciting fast-tempo music. *PLOS ONE* 12(12):e0189075. https://doi.org/10.1371/journal.pone.0189075
- Mojtabavi H, Saghazadeh A, Valenti VE, Rezaei N (2020). Can music influence cardiac autonomic system? A systematic review and narrative synthesis to evaluate its impact on heart rate variability. *Complementary Therapies in Clinical Practice* 39:101162. https://doi.org/10.1016/j.ctcp.2020.101162
- Salimpoor VN, Benovoy M, Larcher K, Dagher A, Zatorre RJ (2011). Anatomically distinct dopamine release during anticipation and experience of peak emotion to music. *Nature Neuroscience* 14(2):257-262. https://doi.org/10.1038/nn.2726
- Hennessy S, Janata P, Ginsberg T, Kaplan J, Habibi A (2025). Music-Evoked Nostalgia Activates Default Mode and Reward Networks Across the Lifespan. *Human Brain Mapping* 46(4):e70181. https://doi.org/10.1002/hbm.70181

WHOOP (company pages, not research)
- WHOOP, "WHOOP Recovery Explained": https://www.whoop.com/us/en/thelocker/how-does-whoop-recovery-work-101/
- WHOOP, "Heart Rate Variability (HRV)": https://www.whoop.com/us/en/thelocker/heart-rate-variability-hrv/
- WHOOP Podcast 29, "Heart Rate Variability": https://www.whoop.com/us/en/thelocker/podcast-29-heart-rate-variability-hrv/
- WHOOP developer docs, "WHOOP 101": https://developer.whoop.com/docs/whoop-101/
