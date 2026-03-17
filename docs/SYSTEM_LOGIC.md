# System Logic — How Attuned Thinks

This document captures the reasoning behind Attuned's design decisions. It bridges the raw research (RESEARCH.md) and the product spec (PRD.md) by explaining **how the pieces connect**, **why each piece matters**, and **what happens when things go right or wrong**.

Written in plain language. Updated as understanding deepens.

---

## 1. The Two Sides of the Bridge

Attuned connects two worlds:

- **WHOOP** tells us what your autonomic nervous system (ANS) needs right now, based on multi-day physiological trends.
- **Song properties** tell us what each song *does* to your ANS — whether it calms it down, fires it up, or grounds it emotionally.

The matching engine is the bridge: WHOOP says "your body is in state X," song properties say "this song produces effect Y," and the engine finds songs where Y matches what X needs.

---

## 2. Song Properties — The Levers That Move Your Nervous System

Every song has measurable properties. Research shows these properties have real, measurable effects on the autonomic nervous system. Some matter a lot. Some barely move the needle.

### 2.1 Property Weights (Ranked by Physiological Impact)

| Song Property | Weight | What It Does to Your Body |
|---|---|---|
| **Tempo (BPM)** | 0.35 (35%) | The strongest single lever. Slow tempo (50-70 BPM) increases parasympathetic activity — your heart rate drops, breathing slows, vagal tone increases. Fast tempo (120-150 BPM) does the opposite — sympathetic activation, heart rate rises, alertness increases. Your heart rate literally entrains toward the beat. This is the most well-documented effect in music-ANS research (Bretherton 2019, Bernardi 2006, Kim 2024). |
| **Energy/Loudness** | 0.25 (25%) | The second strongest lever. Arousal (energy level) has a stronger effect on physiology than emotional content. A loud, fast minor-key song is more physiologically activating than a quiet, slow major-key song. High-energy music activates the sympathetic nervous system — heart rate, breathing rate, blood pressure all rise. After high-energy music stops, a parasympathetic rebound occurs. Combined with tempo, these two properties account for **60% of the neurological scoring**. |
| **Acousticness** | 0.10 (10%) | Acoustic instruments (piano, guitar, strings) activate parasympathetic response more than electronic/synthesized sounds. Classical and acoustic music has been shown to reduce cortisol, heart rate, and blood pressure (Thoma 2013, Scarratt 2023). Recovery states target acousticness >0.7. |
| **Instrumentalness** | 0.10 (10%) | Instrumental music is more effective for parasympathetic activation because lyrics add cognitive load. Your brain has to process language, which keeps it more active. Non-vocal music is associated with lower arousal. Recovery states prefer instrumentalness >0.5. Exception: Emotional Processing Deficit allows vocals because emotional connection outweighs the cognitive load concern. |
| **Valence** | 0.10 (10%) | Happy vs. sad. Valence matters more for subjective experience (how you *feel*) than for direct ANS effects. But the combination of valence and energy matters a lot. High valence + low energy = serene (parasympathetic). High valence + high energy = excited (sympathetic). Low valence + high energy = angry/fearful (strong sympathetic). |
| **Mode (Major/Minor)** | 0.05 (5%) | Major key = bright, positive. Minor key = reflective, introspective. The physiological effect is small but detectable. Major mode decreases cortisol more than minor (Khalfa 2002), making it slightly better for stress reduction. Minor mode elicits slightly higher arousal. Recovery states prefer major. |
| **Danceability** | 0.05 (5%) | Rhythmic regularity gives a sense of control and predictability. Not a strong ANS driver on its own, but contributes to the overall profile. |

### 2.2 Why These Weights

Tempo and energy together account for 60% because they have the strongest, most replicated evidence for directly modulating autonomic state. Acousticness and instrumentalness together account for 20% — they set the "context" (acoustic/calm vs. electronic/stimulating) but aren't as powerful as tempo and energy alone. Valence, mode, and danceability together account for the remaining 20% — they matter for the subjective experience and fine-tuning, but they won't override the effect of tempo and energy.

If you had to pick just two properties to get right, pick tempo and energy. If those are wrong, the playlist won't work regardless of everything else. If those are right and everything else is slightly off, the playlist will still roughly do what it should.

### 2.3 The Three Neurological Scores

Every song gets three scores (0.0 to 1.0) based on these properties:

**Parasympathetic Activation Score** — How calming is this song?
- Peaks when: BPM ~60, low energy, high acousticness, instrumental, moderate-positive valence, major key, low danceability
- Used for: Accumulated Fatigue, Physical Recovery Deficit, recovery states

**Sympathetic Activation Score** — How energizing is this song?
- Peaks when: BPM ~135, high energy, low acousticness, vocals present, high valence, high danceability
- Used for: Peak Readiness, energy states

**Emotional Grounding Score** — How grounding/comforting is this song?
- Peaks when: BPM ~75, moderate energy (~0.35), acoustic, moderate-positive valence, some vocals OK, major key
- Used for: Emotional Processing Deficit, Single Bad Night

The scoring uses gaussian curves — a song scores highest when its properties are closest to the ideal center for that score, and the score decays smoothly as properties move away from center. This means a song at 65 BPM still scores well for parasympathetic (center 60), but a song at 100 BPM scores very low. The decay is smooth, not a hard cutoff.

---

## 3. WHOOP Metrics — Reading Your Body's State

WHOOP gives us multiple metrics every morning. They aren't equally important. Some drive the state classification directly, some confirm it, some just flag edge cases.

### 3.1 Metric Importance Ranking

| Metric | Role in System | Importance | States It Drives |
|---|---|---|---|
| **HRV (LnRMSSD)** | Primary signal — direct ANS readout | **#1 — Foundation** | Accumulated Fatigue, Single Bad Night, Peak Readiness, Baseline |
| **Deep sleep duration** | Physical recovery indicator | **#2 — State splitter** | Physical Recovery Deficit (when low) vs. Emotional Processing Deficit (when adequate) |
| **REM sleep duration** | Cognitive/emotional recovery indicator | **#2 — State splitter** | Emotional Processing Deficit (when low) vs. Physical Recovery Deficit (when adequate) |
| **Resting heart rate (RHR)** | Stress/fatigue confirmation | **#3 — Amplifier** | Accumulated Fatigue (rising RHR + declining HRV = strong composite signal) |
| **Sleep debt (7-day cumulative)** | Chronic deficit tracker | **#3 — Amplifier** | Accumulated Fatigue (>5 hours contributes to the trigger) |
| **HRV CV (coefficient of variation)** | Stability/confidence modifier | **#4 — Modifier** | No state directly — adjusts confidence in readings and nudges song ranges toward calming |
| **Recovery score (WHOOP composite)** | Sanity check | **#5 — Sanity check** | Confirms Peak Readiness (green) and Baseline (yellow). Flags disagreements with classifier. |
| **SpO2 + Skin temperature** | Illness/anomaly flags | **#6 — Edge case** | Not in state classifier — flagged if abnormal for awareness |

### 3.2 What Each Metric Does and What Breaks If It's Wrong

#### HRV (LnRMSSD) — #1, Foundation

**What it is:** Heart rate variability — the variation in time between heartbeats, measured during sleep. We use the natural log of RMSSD (LnRMSSD) because raw RMSSD has a skewed distribution. The log transform makes it normally distributed, which makes baselines, standard deviations, and trends mathematically sound.

**Why it's #1:** HRV is the most direct, well-validated measure of autonomic nervous system balance available from any consumer wearable. WHOOP's HRV has 99% agreement with clinical-grade ECG (Antwerp University Hospital validation). It accounts for ~65% of WHOOP's own recovery score. And crucially — the autonomic nervous system is exactly what music modulates. HRV tells us the state of the system that music affects.

**How we use it:**
- 30-day rolling average defines your personal "normal"
- 7-day rolling average smooths daily noise
- Today's value relative to your 30-day average determines if you're above, at, or below your norm
- Trend over 3-7 days matters more than any single day

**Thresholds:**
- >=10% below 30-day average: caution (common during hard training, not alarming alone)
- >=20% below 30-day average, sustained 3+ days: concern (predicts illness or non-functional overreaching)
- 7+ consecutive days below baseline: red flag regardless of magnitude
- At or above 30-day average + green recovery: supports Peak Readiness

**If HRV reads too high (healthier than reality):**
The worst failure mode in the system. You could be fatigued but the system thinks you're fine. You get an upbeat, energizing playlist when your nervous system needs rest. Playing high-energy music to a fatigued ANS is counterproductive — it pushes a system that's already struggling in the wrong direction.

**If HRV reads too low (worse than reality):**
System over-corrects. You get a calming playlist on a day you feel great. Annoying but not harmful — calming music won't hurt a healthy nervous system. This is a safe failure mode.

**If HRV is missing:**
Cannot classify state at all. System should refuse to generate a playlist rather than guess. HRV is non-negotiable.

#### Deep Sleep Duration — #2, State Splitter

**What it is:** The stage of sleep responsible for physical recovery — muscle repair, growth hormone release, immune function. Measured in milliseconds by WHOOP. Normal range: 15-20% of total sleep time.

**Why it's #2:** Deep sleep is the *only* metric that can distinguish Physical Recovery Deficit from Emotional Processing Deficit. Without it, those two states collapse into one generic "bad sleep" bucket, and the music would be less targeted. The distinction matters because a body that didn't physically recover needs different music (slow, acoustic, soothing) than a mind that didn't emotionally process (warm, familiar, vocals OK).

**How we use it:**
- Personal 30-day rolling average and standard deviation
- Compare tonight's deep sleep to your personal norm

**Thresholds:**
- >1.0 SD below personal mean: "below norm" (caution)
- >1.5 SD below personal mean: "significantly below" (concern — triggers Physical Recovery Deficit if REM is adequate)
- <10% of total sleep time OR <1 hour absolute: significant deficit regardless of personal baseline

**If deep sleep reads low when it wasn't:**
You get Physical Recovery Deficit — body-soothing, slow music (55-80 BPM, high acousticness). Unnecessary intervention but not harmful. Calming music to a recovered body is just... calming.

**If deep sleep reads normal when it was actually bad:**
System misses that your body didn't physically recover. You might get Baseline or Peak Readiness with more energizing music when your muscles and immune system needed rest. This matters for athletes or after intense physical days.

#### REM Sleep Duration — #2, State Splitter

**What it is:** The stage of sleep responsible for cognitive and emotional recovery — memory consolidation, emotional regulation, learning. Normal range: 20-25% of total sleep time.

**Why it's #2 (tied with deep sleep):** Same logic — REM is the only metric that can identify Emotional Processing Deficit specifically. Low REM means emotional regulation may be impaired the next day. You might feel foggy, reactive, or have difficulty concentrating. This calls for emotionally grounding music — warm, familiar, comforting — which is different from the physically restorative music that Physical Recovery Deficit needs.

**How we use it:**
- Same approach as deep sleep: personal 30-day rolling average and SD
- Compare tonight's REM to your personal norm

**Thresholds:**
- >1.0 SD below personal mean: below norm
- >1.5 SD below personal mean: concern — triggers Emotional Processing Deficit if deep sleep is adequate
- <15% of total sleep time: significant deficit regardless of baseline

**If REM reads low when it wasn't:**
You get Emotional Processing Deficit — warm, grounding music (65-90 BPM, vocals OK, moderate acousticness). Unnecessary but harmless. Grounding music doesn't hurt an emotionally balanced person.

**If REM reads normal when it was actually bad:**
System misses emotional processing gap. You get normal music when you might benefit from something grounding. Most impactful on high-stress days where emotional regulation matters.

**The Deep/REM split is the most unique thing about Attuned.** Most recovery apps just say "you slept badly." We say "your body recovered but your mind didn't" or "your mind recovered but your body didn't" — and serve different music for each.

#### Resting Heart Rate (RHR) — #3, Amplifier

**What it is:** Heart rate during deepest sleep. Lower = better recovered. WHOOP measures nocturnal HR, which is more reliable than waking RHR because it removes confounders (caffeine, stress, activity).

**Why it's #3:** RHR doesn't drive any state by itself. It *amplifies* the HRV signal. The combination of HRV declining + RHR rising is much stronger evidence of fatigue than either alone. It's multiplicative confirmation:
- HRV declining + RHR rising = strong fatigue signal (Accumulated Fatigue)
- HRV declining + RHR stable = possible early fatigue (could be acute stressor)
- HRV stable + RHR rising = likely acute stressor (illness, alcohol), not training fatigue

**Thresholds:**
- +5 bpm above 30-day personal average, sustained 3+ days: caution
- +7 bpm above, sustained 3+ days: concern

**If rising trend is missed:**
Accumulated Fatigue might not trigger, or triggers later. HRV decline alone is still a signal, but the composite is much stronger. Missing RHR means we might be slower to detect fatigue.

**If falsely shows rising:**
Could push toward Accumulated Fatigue prematurely. But the state requires HRV decline AND RHR rise AND sleep debt — all three must align. One wrong input alone won't trigger the most aggressive intervention.

#### Sleep Debt (7-day Cumulative) — #3, Amplifier

**What it is:** The gap between how much sleep you needed and how much you got, accumulated over 7 days. Computed as: `daily_debt = max(0, sleep_need - actual_sleep)`, summed over 7 days. WHOOP provides sleep_needed (broken down into baseline + debt component + strain component + nap offset).

**Why it's #3:** Sleep debt captures something HRV alone can't — chronic under-sleeping that hasn't yet crashed your HRV. You can run a moderate sleep deficit for days before HRV drops, but the cognitive impairment is already happening. It's the "you're headed for trouble" signal.

**Thresholds (Van Dongen & Dinges, 2003):**
- >5 hours over 7 days (~45 min/night deficit): moderate concern. Cognitive impairment detectable in lab conditions.
- >10 hours over 7 days (~1.5h/night deficit): significant. Equivalent to ~1 night of total sleep deprivation. Critically — subjects were unaware of their impairment.

**Recovery timeline:** 1 hour of debt takes up to 4 days of adequate sleep to fully recover. Full elimination of chronic debt may require 9+ days. Weekend catch-up provides partial but not complete recovery.

**If underestimated:**
Accumulated Fatigue might not trigger when it should. Same as RHR — it weakens detection but doesn't completely break it because the composite requires all three signals.

**If overestimated:**
Pushes toward Accumulated Fatigue when you might just be in Single Bad Night or Baseline. You get more aggressive calming music than needed. Safe failure mode — conservative.

#### HRV Coefficient of Variation (CV) — #4, Modifier

**What it is:** A measure of how stable or erratic your HRV has been over the past 7 days. Not a "thing your body is doing" — it's a measure of *consistency*.

`CV = (Standard Deviation of 7 daily LnRMSSD values) / (Mean of 7 daily LnRMSSD values) * 100`

**Ranges:**
- <10%: Elite-level stability. Nervous system responding consistently.
- 10-20%: Normal for active people. Training, travel, stress, alcohol — all cause daily fluctuation.
- >15%: Elevated variability — investigate.
- >20%: Significant instability. Nervous system getting jerked around.

**Why it's #4:** CV doesn't drive any state. It *modifies how we use the other metrics*. It answers two questions:

1. **How much should we trust today's single HRV reading?** High CV means today's number could be a spike or a dip in a volatile pattern — less trustworthy as a snapshot.
2. **Should we add extra stabilization to the music regardless of state?** An erratic nervous system benefits from consistent, predictable music even if the headline state looks OK.

**The three CV scenarios:**

| CV + HRV | What's Happening | Music Strategy |
|---|---|---|
| **Low CV + high HRV** | Stable and recovered. Best case. | Trust the state classification. Use normal ranges. If Peak Readiness, go high energy. |
| **Low CV + low HRV** | Suppressed, locked system. Not bouncing around — stuck low. | Deep parasympathetic: 50-70 BPM, high acousticness, instrumental, gentle. System needs to be coaxed back up. |
| **High CV + any HRV** | Erratic, dysregulated. Even if today's number looks OK, the week has been unstable. | Stabilization priority. Shift ranges toward calming regardless of today's number. Consistent, predictable music. Higher acousticness, moderate tempo (60-80 BPM), rhythmically steady. |

**Critical nuance:** Very low CV + low absolute HRV looks like "stability" but it's actually bad — the system is suppressed and non-responsive, not genuinely stable. Always interpret CV alongside the absolute HRV level.

**If CV reads too high (falsely shows instability):**
System nudges song selection toward calming when it didn't need to. Playlist is slightly more conservative than optimal. Minor impact.

**If CV reads too low (misses real instability):**
System trusts a single-day HRV reading that might be misleading. Could pick the wrong state, but primary metrics still drive classification. CV just adds caution.

**If ignored entirely:**
The system still works. You lose an early-warning signal and a confidence modifier, but no state depends on CV alone. Research (Buchheit 2014) showed rising CV over weeks was one of the earliest warning signs of overtraining — it showed up *before* performance dropped — so it's valuable but not load-bearing.

#### Recovery Score — #5, Sanity Check

**What it is:** WHOOP's proprietary composite number (0-100%), color-coded green/yellow/red. Composed of ~65% HRV, ~20% RHR, ~15% respiratory rate, plus sleep/SpO2/skin temp contributions. All normalized against 30-day rolling baseline, then run through a proprietary non-linear transformation.

**Why it's only #5:** Research directly compared raw HRV vs. the composite recovery score. In a study of 23 elite NCAA swimmers (Lundstrom 2024), raw HRV correlated significantly with validated stress measures — but the Recovery Score showed *no correlation* with any stress/recovery variable. The composite algorithm actually lost a signal that existed in the raw data. The recovery score collapses multiple dimensions into one number, losing the distinctions needed for our six-state classification (you can't tell Physical Recovery Deficit from Emotional Processing Deficit from a single number).

**How we use it:**
- Confirms Peak Readiness: green (>=67%) alongside strong raw metrics
- Confirms Baseline: yellow (34-66%) with no deficit signals
- Flags disagreements: if classifier says "Peak Readiness" but recovery is red, something needs investigation

**If wrong or ignored:**
Almost no impact on playlist quality. We use raw metrics for classification. Recovery score is a cross-check, not a driver.

#### SpO2 + Skin Temperature — #6, Edge Case

**What they are:** Blood oxygen saturation (normally 95-100%) and skin temperature deviation from baseline. Drops in SpO2 or spikes in skin temp can indicate illness onset, altitude effects, or other medical concerns.

**Why they're #6:** Not connected to the music-ANS pathway. These are health monitoring signals, not playlist inputs. If SpO2 drops significantly or skin temp spikes, we'd flag it in the playlist explanation for awareness, but music isn't the intervention for illness.

**If wrong or missing:** Zero impact on playlist generation.

---

## 4. System Design Properties

### 4.1 Graceful Degradation

The system is designed so the most important metrics are also the most reliable ones:

- **HRV (#1):** 99% agreement with clinical ECG. Hardest to get wrong.
- **Sleep stages (#2):** Fair-to-moderate agreement with polysomnography (kappa 0.21-0.53). Absolute numbers may be off, but within-device trends (deviations from *your own* baseline on the *same device*) remain useful.
- **Recovery score (#5):** Proprietary, opaque algorithm. But we don't depend on it.
- **SpO2/Skin temp (#6):** Noisiest metrics. But we don't depend on them either.

The less reliable the metric, the less we depend on it.

### 4.2 Composite State Protection

The most serious state — Accumulated Fatigue — requires three metrics to align (HRV declining + RHR rising + sleep debt accumulating). A single bad reading can't trigger the most aggressive intervention by itself. This protects against false positives, which matter because Accumulated Fatigue produces the most restrictive playlists (50-70 BPM, very low energy, highly acoustic).

### 4.3 Safe Failure Modes

For every metric, the system fails in the safe direction:

- Metric reads worse than reality → more calming music than needed → harmless
- Metric reads better than reality → more energizing music than needed → counterproductive

The "reads too low" failure is always safe. The "reads too high" failure is the one to guard against. This is why we use conservative thresholds and require multi-metric confirmation for the most aggressive states.

---

## 5. The Six States — How WHOOP Metrics Map to Song Strategies

Each state is triggered by specific WHOOP metric patterns and maps to specific song property ranges. This is the complete bridge from body to music.

### State 1: Accumulated Fatigue

**Trigger:** LnRMSSD >=20% below 30-day average, sustained 3+ days AND RHR rising (+5 bpm above baseline) AND sleep debt >5 hours (7-day rolling).

**What's happening:** Not just a bad morning. The body is trending downward across multiple metrics over multiple days. The autonomic nervous system is depleted.

**Music strategy:** Genuinely restorative. Maximum parasympathetic activation.

| Song Property | Target Range | Why |
|---|---|---|
| BPM | 50-70 (sweet spot: 60) | Slowest tempo range. Heart rate entrainment toward rest. |
| Energy | 0.1-0.3 | Minimal arousal. Let the nervous system down-regulate. |
| Acousticness | >0.7 | Acoustic instruments activate parasympathetic more than electronic. |
| Instrumentalness | >0.5 | No lyrics = no cognitive load = deeper calming. |
| Valence | 0.2-0.5 | Moderate. Not sad, not peppy. Neutral-warm. |
| Mode | Major preferred | Major key reduces cortisol more than minor. |

### State 2: Physical Recovery Deficit

**Trigger:** Deep sleep >1.5 SD below personal mean AND REM adequate (within 1.0 SD).

**What's happening:** Body didn't physically recover (muscle repair, immune function compromised) but mind is clear (emotional processing was adequate). You might feel physically heavy but mentally fine.

**Music strategy:** Soothe the body, but the mind can engage. Slightly wider ranges than Accumulated Fatigue.

| Song Property | Target Range | Why |
|---|---|---|
| BPM | 55-80 | Slow but not as restrictive. Body needs rest, mind can handle slightly more. |
| Energy | 0.1-0.4 | Low but allows some engagement. |
| Acousticness | >0.6 | Still strongly acoustic. |
| Instrumentalness | >0.3 | Some vocals OK since mind is clear. |
| Valence | 0.3-0.6 | Moderately positive. |
| Mode | Major preferred | Calming bias. |

### State 3: Emotional Processing Deficit

**Trigger:** REM >1.5 SD below personal mean AND deep sleep adequate (within 1.0 SD).

**What's happening:** Body recovered physically but emotional regulation may be impaired. You might feel physically fine but foggy, reactive, or emotionally sensitive. REM is when the brain processes emotions and consolidates memories.

**Music strategy:** Emotionally grounding. Warm, familiar, comforting. Vocals are actively helpful here (emotional connection matters more than cognitive load reduction).

| Song Property | Target Range | Why |
|---|---|---|
| BPM | 65-90 | Moderate. Not trying to put you to sleep — trying to ground you. |
| Energy | 0.2-0.5 | Moderate engagement. |
| Acousticness | 0.4-0.8 | Warm but not strictly acoustic. |
| Instrumentalness | 0.0-0.5 | Vocals OK — emotional connection is the priority. |
| Valence | 0.3-0.6 | Warm, not sad. |
| Mode | Major preferred | Emotional warmth. |

### State 4: Single Bad Night

**Trigger:** Today's LnRMSSD >=10% below average OR recovery <50%, BUT 7-day LnRMSSD trend is stable or rising.

**What's happening:** One rough night, but your baseline is strong. This isn't a pattern — it's a blip. Maybe you stayed up late, had alcohol, slept in a bad environment.

**Music strategy:** Moderately calming. Don't overreact. Wide ranges because the body doesn't need aggressive intervention.

| Song Property | Target Range | Why |
|---|---|---|
| BPM | 60-90 | Gentle but not ultra-slow. |
| Energy | 0.2-0.5 | Moderate. |
| Acousticness | >0.4 | Some acoustic preference but flexible. |
| Instrumentalness | No strong preference | Whatever fits. |
| Valence | 0.3-0.7 | Wide range. |
| Mode | No strong preference | Not driving the decision. |

### State 5: Baseline

**Trigger:** Yellow recovery (34-66%), no strong deficit signals. No significant HRV decline, no sleep architecture deficits exceeding 1.5 SD.

**What's happening:** Normal day. Nothing stands out positively or negatively. Your body is in its typical operating range.

**Music strategy:** Widest ranges. No physiological constraint. Music should be pleasant and balanced — a good general-purpose playlist from your library.

| Song Property | Target Range | Why |
|---|---|---|
| BPM | 70-110 | Widest tempo range of any state. |
| Energy | 0.3-0.6 | Middle of the road. |
| Acousticness | 0.2-0.7 | Very flexible. |
| Instrumentalness | No strong preference | Whatever fits. |
| Valence | 0.4-0.7 | Moderately positive. |
| Mode | No strong preference | Not driving the decision. |

### State 6: Peak Readiness

**Trigger:** Green recovery (>=67%), LnRMSSD at or above 30-day average, good sleep architecture (deep and REM within 1.0 SD), low sleep debt (<3 hours).

**What's happening:** Everything aligned. Your autonomic nervous system is balanced and resilient. You slept well, recovered well, and have no accumulated deficits.

**Music strategy:** Anything goes. This is the state where the system can lean into your highest-energy favorites. No physiological constraint — match energy and positivity.

| Song Property | Target Range | Why |
|---|---|---|
| BPM | 90-150+ | High energy. Full intensity if you want it. |
| Energy | 0.5-1.0 | Go big. |
| Acousticness | No minimum | Electronic, acoustic, whatever. |
| Instrumentalness | No strong preference | Whatever fits. |
| Valence | >0.5 | Positive, upbeat. |
| Mode | No strong preference | Not driving the decision. |

---

## 6. How HRV CV Modifies Everything Above

HRV CV sits outside the state classification. It doesn't pick your state — it modifies how confidently we act on the state and whether we add extra stabilization.

Think of it as a volume knob on the system's confidence:

- **Low CV:** Full confidence. The state classification is trustworthy. Use the target ranges as-is.
- **High CV:** Reduced confidence. Today's reading might be a spike in a volatile week. Nudge ranges toward calming/stabilizing regardless of state. Flag in the playlist description.

**How the modification works in practice:**

If you're classified as **Baseline** (normal day, wide ranges) but CV is 22%:
- Instead of BPM 70-110, favor the lower end (70-90)
- Instead of energy 0.3-0.6, favor 0.3-0.45
- Increase acousticness preference
- The playlist description notes: "HRV variability elevated this week — leaning toward stabilizing selections"

If you're classified as **Peak Readiness** but CV is 18%:
- Still Peak Readiness, but maybe don't go full 150 BPM
- Favor the lower end of the energy range
- The system is saying: "you look great today, but your week has been bumpy — maybe don't go maximum intensity"

If you're classified as **Accumulated Fatigue** and CV is also high:
- Already in the most restrictive state. CV doesn't change the ranges much — they're already maximally calming. But it reinforces that this isn't a false alarm.

**CV is most impactful for middle states** (Baseline, Single Bad Night) where the ranges are wide and there's room to shift. For extreme states (Accumulated Fatigue, Peak Readiness), the ranges are already narrow and CV has less room to modify them.
