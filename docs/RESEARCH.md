# Attuned — Research Findings

**Date:** March 16, 2026
**Purpose:** Captures the published research that informs Attuned's design decisions. Every threshold, formula, and property range in the system traces back to findings documented here. This is the "why" behind the technical choices.

---

## 1. How Music Affects the Autonomic Nervous System

The core premise of Attuned: specific, measurable properties of music modulate the autonomic nervous system in predictable ways. This section documents what properties matter, how much, and with what evidence.

### 1.1 Tempo — The Dominant Factor

Tempo is the single strongest predictor of how music affects the ANS. The relationship is roughly linear: slower tempo increases parasympathetic (vagal) activity, faster tempo increases sympathetic activity.

- **Bretherton et al., 2019 (Music Perception):** Baroreflex sensitivity (BRS) was significantly greater at 60 BPM than at 120 BPM (p < 0.001) and 180 BPM (p = 0.022). The effect was driven entirely by parasympathetic activity — sympathetic nerve activity did NOT differ between tempos. This means slower tempo doesn't suppress the sympathetic system; it boosts vagal tone on top of it.

- **Bernardi et al., 2006 (Heart):** Music listening increased blood pressure, heart rate, and LF:HF ratio proportional to tempo. A 2-minute pause afterward decreased all of these. Faster = more sympathetic, slower = more parasympathetic.

- **Ooishi et al., 2017 (PLOS ONE):** Slow-tempo music increased salivary oxytocin and HF-HRV (parasympathetic marker). Fast-tempo music decreased cortisol and increased LF/HF ratio (sympathetic marker).

- **Kim et al., 2024 (J Exerc Rehabil):** 60-80 BPM music inhibited sympathetic activity, decreasing LFR and increasing HFR. Fast music (120-140 BPM) increased LFR from 45-53% to 48-57%.

- **Dey et al., 2017 (Scientific Reports):** Heart rate modulates toward the acoustic tempo (entrainment). If resting HR < 80, listening to 80 BPM drums raised HR. If resting HR > 80, it lowered HR.

**Design decision:** Tempo gets the highest weight in neurological scoring (0.35). Recovery states target 50-70 BPM. Energy states target 120-150 BPM.

### 1.2 Energy / Loudness — Strong Arousal Predictor

Arousal (energy level) has a stronger effect on physiology than valence (positive vs negative emotional tone). This is a key distinction — a loud, fast minor-key song is more physiologically activating than a quiet, slow major-key song, even though the first is "negative" and the second is "positive."

- **International Journal of Psychophysiology (2024, systematic review):** Arousal dimension has a stronger effect on physiology than valence dimension across multiple studies.

- Rock/high-energy music activates the sympathetic nervous system, raising HR, breathing rate, and BP. After high-energy music stops, there is a parasympathetic rebound (Ellis & Thayer, 2010).

**Design decision:** Energy gets the second-highest weight (0.25). Combined with tempo, these two properties account for 60% of the neurological scoring.

### 1.3 Acousticness — Relaxation Context

Acoustic instruments (piano, guitar, strings) tend to activate the parasympathetic response more than electronic/synthesized sounds.

- **Scarratt et al., 2023 (PMC):** Sleep and study playlists are characterized by higher acousticness, higher instrumentalness, lower energy, lower tempo, and lower loudness compared to general playlists.

- **Thoma et al., 2013 (PLOS ONE):** Classical/acoustic music effectively reduced cortisol, HR, and BP in a controlled stress paradigm.

**Design decision:** Acousticness gets weight 0.10. Recovery states target >0.7.

### 1.4 Instrumentalness — Cognitive Load

Instrumental music is more effective for parasympathetic activation than vocal music because lyrics add cognitive load. This is especially relevant for recovery states where the goal is to reduce mental processing demands.

- **Journal of Cultural Cognitive Science (2024):** Instrumental music more beneficial for cognitive tasks than music with lyrics due to cognitive load.

- **BMC Psychology (2023):** Non-vocal music associated with lower arousal.

**Design decision:** Instrumentalness is included as a classification field (was missing from original PRD). Gets weight 0.10 in scoring. Recovery states prefer instrumentalness >0.5.

### 1.5 Key and Mode (Major vs Minor) — Secondary Modulator

Major mode = bright, positive. Minor mode = reflective, introspective. The effect on physiology is real but smaller than tempo or energy.

- **Khalfa et al., 2002 (Neuroscience Letters):** Major mode produced larger skin conductance responses, faster HR, and faster respiration than minor mode.

- **Zhang et al., 2024 (Frontiers in Psychology):** Minor mode elicited higher arousal than major. But major mode decreased salivary cortisol significantly more than minor. Major = better for stress reduction; minor = deeper emotional engagement.

**Design decision:** Mode gets weight 0.05. Recovery states prefer major (cortisol reduction). The effect size is notably smaller than tempo.

### 1.6 Valence — Subjectively Important, Physiologically Weak

Valence (emotional positiveness) matters more for subjective experience than for direct ANS effects. The combination with energy is what matters: high valence + low energy = serene (parasympathetic). High valence + high energy = excited (sympathetic). Low valence + high energy = angry/fearful (strong sympathetic).

- Joyful music (high valence) shifts toward sympathetic activity vs silence (Frontiers in Physiology).
- But arousal matters more than valence for measurable physiological changes.

**Design decision:** Valence gets weight 0.10 (up from initial estimate of 0.08, because subjective experience matters for playlist quality even if the ANS effect is smaller).

### 1.7 Familiarity — Critical for Emotional Grounding

Familiar, personally meaningful music amplifies all physiological benefits. This isn't just a "nice to have" — it's a documented neurochemical effect.

- **Chanda & Levitin, 2013 (Trends in Cognitive Sciences):** Familiar music triggers stronger dopamine release via the reward circuit. Music activates the same endorphin pathways as food and social bonding.

- **European Heart Journal (2024):** Personal preferred music ranked most preferred by 74.8% of participants. The autonomic benefits of music are stronger with personally preferred music.

**Design decision:** All recommendations come from the user's own library. Preference weighting prioritizes songs the user has explicitly liked or played frequently. For the emotional grounding state specifically, familiarity is weighted as heavily as any acoustic property.

---

## 2. The Iso Principle — Playlist Sequencing

The iso principle, from music therapy, says: start the music close to the listener's current state and gradually transition toward the desired state. Don't jump from 60 BPM to 140 BPM — the nervous system resists abrupt shifts.

### 2.1 Core Concept

- **Heiderscheit & Madson, 2015:** Clinically defined as matching the fit between the person's current state (emotion, affect, arousal) and the music's properties (tempo, mode, energy), then gradually shifting the music toward the target state.

- **Starcke & von Georgi, 2024 (Musicae Scientiae):** Iso-principle-based listening (match then shift) successfully modulated affective state in controlled conditions.

### 2.2 Transition Rate

No published standard exists for exact BPM-per-song transition rates. However:

- **Saarikallio et al., 2021 (IJERPH):** Using only 2 songs created too-abrupt shifts. More than 2 songs (ideally 3-5+) are required for effective gradual transition.

- **Li et al., 2024:** Computational implementation generated music traversing the valence-arousal circumplex in 30-second increments across 15-minute sessions.

- "Weightless" (Marconi Union), clinically studied: starts at 60 BPM, slows to ~50 BPM within a single 8-minute track. Reduced anxiety by 65% and physiological resting rates by 35% (MindLab study).

### 2.3 Derived Algorithm

From the aggregate research, no single paper gives us exact numbers, but the following is well-supported by the combined evidence:

- First 1-2 songs: match current state within +/- 5 BPM and +/- 0.1 energy
- Each subsequent song: shift 10-15 BPM and 0.1-0.15 energy toward target
- Minimum 3 transition songs (2 is too abrupt)
- 8-10 songs for a full mood journey (clinical practice guideline)
- Total playlist duration: 15-30 minutes

**Design decision:** Sequencer implements this algorithm. For a 15-20 song playlist, the first 2-3 songs match the detected physiological state, the middle transitions, and the last 3-4 arrive at the target.

---

## 3. HRV Trend Analysis — Sports Science

How to detect fatigue, overtraining, and recovery status from HRV data. This directly informs the state classifier.

### 3.1 Use LnRMSSD, Not Raw RMSSD

The field standard is to log-transform RMSSD before computing baselines, rolling averages, and trends. The log transform normalizes the skewed distribution of raw RMSSD values.

**Method (Plews/Buchheit):**
1. Record morning RMSSD daily (WHOOP does this during sleep)
2. Transform: `LnRMSSD = ln(RMSSD)`
3. 7-day simple moving average: `LnRMSSD_7day = mean(LnRMSSD[day-6 : day])`
4. Smallest Worthwhile Change (SWC): `mean +/- 0.5 * SD` of the rolling window
5. If the 7-day average falls below `mean - SWC`, that signals a meaningful negative trend

**Source:** Plews et al. 2012 (Eur J Appl Physiol), Buchheit 2014 (Frontiers in Physiology)

**Design decision:** All HRV computations use LnRMSSD. The WHOOP API gives raw `hrv_rmssd_milli` — we log-transform immediately on storage.

### 3.2 HRV Decline Thresholds

There is no universal "X% per day" slope threshold. The field uses individual-baseline-relative approaches:

- **>=10% below 30-day average (LnRMSSD):** Caution. Common during peak training blocks. Not concerning if it recovers.
- **>=20% below 30-day average, sustained 7+ days:** Concern. Predicts upper-respiratory illness or non-functional overreaching.
- **>=25% below or inability to recover after deload:** Strong overtraining signal.
- **7+ consecutive days below baseline:** Red flag regardless of magnitude.

**Source:** Plews et al. 2012 found that in a non-functionally over-reached triathlete, the CV of 7-day rolling LnRMSSD showed "large linear reductions towards NFOR at -0.65%/week."

**Design decision:** State classifier uses >=20% below 30-day LnRMSSD average as the primary trigger for Accumulated Fatigue. >=10% flags caution.

### 3.3 HRV Coefficient of Variation (CV)

`CV = (SD of 7 daily LnRMSSD values) / (Mean of 7 daily LnRMSSD values) * 100`

- **<10%:** Elite-level stability
- **10-20%:** Normal for active individuals. Buchheit 2014: "day-to-day variations in training load entail CV = 10-20% for LnRMSSD"
- **>15%:** Elevated variability — investigate
- **>20%:** Significant instability

**Critical nuance:** Very low CV + low absolute HRV = bad (system is suppressed/locked, not responsive). Always interpret CV alongside absolute LnRMSSD.

**Design decision:** CV is computed but used as a secondary signal, not a primary state classifier input. Flagged in the state explanation when elevated.

### 3.4 Resting Heart Rate

- **+5 bpm above 30-day personal average, sustained 3+ days:** Caution
- **+7 bpm above, sustained 3+ days:** Concern

Important: sleeping/nocturnal HR is more reliable than waking RHR (removes confounders). WHOOP measures this.

**Composite signal:** HRV declining + RHR increasing = strong fatigue signal (multiplicative evidence). HRV declining + RHR stable = possible early fatigue. HRV stable + RHR increasing = likely acute stressor (illness, alcohol), not training fatigue.

**Source:** Multiple coaching sources converge on +5 bpm as the practical threshold. A 2003 review notes mixed evidence, but when combined with HRV decline, the composite is strong.

**Design decision:** RHR trend is part of the Accumulated Fatigue composite: HRV declining AND RHR rising AND sleep debt accumulating. Not used alone.

---

## 4. Sleep Architecture

### 4.1 Normal Ranges

- **Deep sleep (N3/SWS):** 15-20% of total sleep time. ~1.5-2 hours per night. Declines with age (young adults: 20-25%, ages 30-50: 15-20%).
- **REM sleep:** 20-25% of total sleep time. ~1.5-2 hours per night. Concentrates in later cycles (last third of the night).

**Source:** NCBI StatPearls clinical reference, Sleep Foundation

### 4.2 Deficit Thresholds

Using personal baselines (rolling 30-day mean and SD):

- **<1.0 SD below personal mean:** Caution (below norm)
- **<1.5 SD below personal mean:** Concern (significantly below norm)
- **Deep sleep <10% of total or <1 hour absolute:** Significant deficit regardless of personal baseline
- **REM <15% of total:** Significant deficit

In a normal distribution, values beyond 1.5 SD occur ~6.7% of the time — a good balance of sensitivity and specificity for flagging real deficits vs normal variation.

**Baseline reliability:** Need at least 14-21 days of data before personal means and SDs are reliable. Use rolling 30-day window.

**Wearable accuracy caveat:** WHOOP sleep staging has fair-to-moderate agreement with polysomnography (Cohen's kappa 0.21-0.53). Absolute percentages may be off, but within-device trends (deviations from your own baseline on the same device) remain useful.

**Design decision:** Physical Recovery Deficit triggers when deep sleep is >1.5 SD below personal mean AND REM is adequate (within 1.0 SD). Emotional Processing Deficit is the inverse.

### 4.3 Sleep Debt

**Computation:** `Daily_debt = max(0, sleep_need - actual_sleep)`. Rolling 7-day sum.

WHOOP provides `sleep_needed` breakdown (baseline + debt component + strain component + nap offset). We use WHOOP's sleep_needed as the target and compute cumulative deficit ourselves.

**Thresholds (Van Dongen & Dinges, 2003):**
- **>5 hours cumulative over 7 days (~45 min/night deficit):** Moderate concern. Cognitive impairment detectable in lab conditions.
- **>10 hours cumulative over 7 days (~1.5h/night deficit):** Significant. Equivalent to ~1 night of total sleep deprivation. Subjects were unaware of their impairment.

**Recovery timeline:** 1 hour of debt takes up to 4 days of adequate sleep to fully recover. Full elimination of chronic debt may require 9+ days. Weekend catch-up provides partial but not complete recovery.

**Design decision:** Sleep debt >5 hours (7-day rolling) contributes to the Accumulated Fatigue composite signal.

---

## 5. WHOOP Metric Importance — What Drives Accurate State Classification

Our state classifier needs to distinguish between six physiological states. The research below informed which WHOOP metrics carry the most weight and why.

### 5.1 Raw HRV (RMSSD) — The Strongest Individual Signal

HRV is the most direct, well-validated measure of autonomic nervous system state available from consumer wearables.

- **WHOOP HRV accuracy:** 99% agreement with clinical-grade ECG during sleep (Antwerp University Hospital validation), ICC of 0.99 in earlier studies. The raw measurement is highly reliable.
- **Plews et al., 2012:** 7-day rolling LnRMSSD averages are superior to single-day measurements for detecting overreaching and recovery status in athletes. Single-day values are noisy; trends are robust.
- **Lundstrom et al., 2024 (Int J Sports Science & Coaching):** Studied 23 elite NCAA swimmers during peak training. Raw HRV correlated significantly with sport-specific stress (r = -0.462) and total stress (r = -0.459), confirming HRV as a reliable stress/recovery indicator.

### 5.2 Raw HRV vs. Composite Recovery Score

The question of whether WHOOP's composite Recovery Score adds value beyond raw metrics has been studied directly.

- **Recovery score composition (publicly known):** ~65% HRV (RMSSD), ~20% RHR, ~15% respiratory rate, plus contributions from sleep duration, SpO2, and skin temperature. All values normalized against the user's 30-day rolling baseline, then passed through a proprietary non-linear transformation with dynamic weighting.
- **Healthy adult correlation:** r = 0.68 with subjective fatigue (Journal of Science and Medicine in Sport, 2023). This is a meaningful moderate-to-strong correlation — the score does reflect something real about how a healthy person feels. However, most of that predictive power comes from HRV itself, which accounts for ~65% of the score's weight.
- **Clinical populations:** Correlation drops to r = 0.31 (insomnia) and r = 0.22 (diabetics), populations where HRV is chronically suppressed (medRxiv 2024 systematic review, Khodr et al.).
- **The swimmer study comparison:** In the same Lundstrom 2024 study, raw HRV correlated significantly with validated stress measures — but the Recovery Score showed no correlation with any RESTQ stress/recovery variable (r values of -0.05, -0.18, -0.03, -0.01). The composite algorithm lost a signal that existed in the raw data.
- **Performance correlations:** WHOOP-conducted studies found Recovery Score correlated with basketball shooting accuracy (NCAA Div I case study) and baseball fastball velocity/exit bat speed (230 MLB minor league players, 2016). These are directionally meaningful but were not peer-reviewed or independently replicated.

### 5.3 Why Multi-Dimensional Metrics Matter for State Classification

- **Doherty, Lambe, Altini et al., 2025 (Translational Exercise Biomedicine):** Evaluated 14 composite health scores across 10 wearable manufacturers. Found "significant discrepancies in data collection timeframes, metric weighting, and proprietary scoring methodologies." None provided full validation studies. Composite scores collapse multiple dimensions into one number, losing the distinctions needed for specific state classification.
- **Altini (HRV4Training):** Composite scores often mix behavioral inputs (sleep duration, activity) with physiological outputs (HRV, RHR), confounding cause and effect. For state classification, we need the physiological response directly.
- **Our specific need:** Distinguishing "Physical Recovery Deficit" (low deep sleep, adequate REM) from "Emotional Processing Deficit" (low REM, adequate deep sleep) requires the individual sleep stage metrics. A single composite number cannot make this distinction. Similarly, "Accumulated Fatigue" (multi-day HRV decline + RHR rise + sleep debt) requires trend data across multiple metrics that a single-night composite flattens.

### 5.4 Where Recovery Score Adds Value

- **Sanity check:** If the classifier says "Peak Readiness" but Recovery is red, something needs investigation.
- **Peak Readiness and Baseline confirmation:** Green recovery (>=67%) supports Peak Readiness alongside raw metrics. Yellow (34-66%) supports Baseline.
- **Practical sports science use:** Professional teams across MLB, NBA, and NFL use Recovery Score dashboards. For coaches managing rosters, the green/yellow/red simplification has practical value as a quick heuristic — it just isn't granular enough for our six-state classification.

**Design decision:** The state classifier uses raw metrics (HRV, RHR, sleep stages, sleep debt) as primary inputs because they provide the multi-dimensional signal needed to distinguish between six states. Recovery Score is used as a complementary signal — confirming Peak Readiness/Baseline classification and flagging disagreements between the classifier and WHOOP's own assessment.

---

## 6. LLM Music Classification

### 6.1 How It Works

GPT-4o-mini classifies songs from memorized training data, not audio analysis. It's doing pattern matching — if the song appeared frequently in its training corpus, the metadata will be decent. If not, it fabricates plausible values.

### 6.2 Expected Accuracy by Property

Rough estimates from Yang et al. 2025, Deezer/RecSys 2025, and community reports:

- **BPM:** 85-90% within +/-5 BPM for popular songs. 30-40% for obscure. Models default to genre-typical BPM when unsure.
- **Key/Mode:** 80-85% for popular, 20-30% for obscure.
- **Energy/Danceability:** 70-80% for popular. Genre-correlated.
- **Valence:** Hardest — 60-70% for popular, 40-50% for obscure. Models cluster around 0.5 when uncertain.
- **Genre/Mood tags:** 85-90% for popular (LLM's strongest suit, abundant textual training data).

### 6.3 Known Biases

- **Popularity bias:** Well-known songs get accurate data, obscure songs get fabrications
- **Genre stereotyping:** Metal/rock profiles tend to be more accurate; rap, world music, French music less so (Deezer study)
- **Western music bias:** Better accuracy for English-language pop/rock than other traditions
- **Mid-range valence clustering:** When uncertain, model defaults to ~0.5
- **Temporal cutoff:** Songs released after training cutoff get worse accuracy

### 6.4 Design Decisions from This Research

- **Batch size: 5 songs per request.** Quality drops significantly above 10. At 5 per batch: 300 songs = 60 calls, still well under $1.
- **Scale: 0.0-1.0** for all features (matches Spotify conventions and the research ecosystem).
- **BPM: Exact integer,** not a range. Ranges produce useless wide bands. Apply +/-5 BPM tolerance in the matching layer.
- **Confidence field:** "high"/"medium"/"low". Critical for routing unknown songs. The prompt must explicitly tell the model it can say "I don't know" — otherwise it always fabricates.
- **Instrumentalness included:** Was missing from original spec. Needed because instrumental music is more effective for parasympathetic activation.
- **Structured Outputs with `strict: true`:** Guarantees valid JSON structure via constrained decoding. Does NOT enforce numeric ranges — need Pydantic validation pass for 0.0-1.0 clamping.
- **Reference anchors in the prompt:** Give the model concrete examples ("Energy 1.0 = 'Killing in the Name' by RATM. Energy 0.1 = 'Clair de Lune'") to calibrate its scale.

---

## 7. Neurological Scoring Formulas

### 7.1 Property Weights

Based on cumulative evidence from Section 1:

| Property | Weight | Rationale |
|---|---|---|
| Tempo (BPM) | 0.35 | Strongest single ANS predictor (Bretherton 2019, Bernardi 2006, Kim 2024) |
| Energy | 0.25 | Strong arousal predictor, highly correlated with sympathetic activation |
| Acousticness | 0.10 | Moderate relaxation context predictor (Thoma 2013, Scarratt 2023) |
| Instrumentalness | 0.10 | Reduces cognitive load, supports relaxation (BMC Psych 2023) |
| Valence | 0.10 | Weaker than arousal for physiology, but important for subjective experience |
| Mode (major/minor) | 0.05 | Detectable but small physiological effect (Khalfa 2002, Zhang 2024) |
| Danceability | 0.05 | Rhythm regularity, sense of control |

### 7.2 Score Formulas (Starting Points — Tune on Real Data)

**Parasympathetic activation score** (0.0-1.0, higher = more calming):
```
tempo_score     = gaussian(bpm, center=60, sigma=15)    * 0.35
energy_score    = (1.0 - energy)                        * 0.25
acoustic_score  = acousticness                          * 0.10
instrum_score   = instrumentalness                      * 0.10
valence_score   = gaussian(valence, center=0.35, sigma=0.2) * 0.10
mode_score      = (1.0 if major else 0.5)               * 0.05
dance_score     = gaussian(danceability, center=0.3, sigma=0.2) * 0.05

parasympathetic = sum of above
```

**Sympathetic activation score** (0.0-1.0, higher = more energizing):
```
tempo_score     = gaussian(bpm, center=135, sigma=20)   * 0.35
energy_score    = energy                                * 0.25
acoustic_score  = (1.0 - acousticness)                  * 0.10
instrum_score   = (1.0 - instrumentalness)              * 0.10
valence_score   = valence                               * 0.10
mode_score      = (0.8 if major else 1.0)               * 0.05
dance_score     = danceability                          * 0.05

sympathetic = sum of above
```

**Emotional grounding score** (0.0-1.0, higher = more grounding):
```
tempo_score     = gaussian(bpm, center=75, sigma=15)    * 0.30
energy_score    = gaussian(energy, center=0.35, sigma=0.15) * 0.20
acoustic_score  = acousticness                          * 0.15
valence_score   = gaussian(valence, center=0.45, sigma=0.2) * 0.15
instrum_score   = gaussian(instrumentalness, center=0.3, sigma=0.3) * 0.10
mode_score      = (1.0 if major else 0.6)               * 0.05
dance_score     = gaussian(danceability, center=0.4, sigma=0.2) * 0.05

grounding = sum of above
```

Where `gaussian(x, center, sigma) = exp(-0.5 * ((x - center) / sigma)^2)` — peaks at 1.0 when x = center, decays smoothly.

**Note:** These formulas are starting points. They will be calibrated against subjective listening tests ("does this playlist actually feel calming?") and adjusted. The weights and centers are all derived from the research in Sections 1-2 but the exact numbers will evolve.

---

## 8. State-to-Property Target Ranges

Research-backed target ranges for the matching engine. Each state maps to an ideal property profile. Songs are scored by how closely they match these targets.

### Accumulated Fatigue (genuinely restorative)
- BPM: 50-70 (sweet spot: 60)
- Energy: 0.1-0.3
- Acousticness: >0.7
- Instrumentalness: >0.5
- Valence: 0.2-0.5
- Mode: Major preferred
- **Rationale:** Multi-day decline needs genuine parasympathetic activation. Prioritize the properties with the strongest calming evidence.

### Physical Recovery Deficit (body-soothing, mind can engage)
- BPM: 55-80
- Energy: 0.1-0.4
- Acousticness: >0.6
- Instrumentalness: >0.3
- Valence: 0.3-0.6
- Mode: Major preferred
- **Rationale:** Deep sleep was inadequate — body needs rest. But REM was fine, so mind is clear. Can tolerate slightly more engaging music than Accumulated Fatigue.

### Emotional Processing Deficit (warm, familiar, grounding)
- BPM: 65-90
- Energy: 0.2-0.5
- Acousticness: 0.4-0.8
- Instrumentalness: 0.0-0.5 (vocals OK — emotional connection)
- Valence: 0.3-0.6
- Mode: Major preferred
- **Rationale:** REM was inadequate — emotional regulation may be impaired. Familiar, warm music supports emotional grounding. Vocals are acceptable (emotional connection > cognitive load concern here).

### Single Bad Night (moderately calming, not aggressive)
- BPM: 60-90
- Energy: 0.2-0.5
- Acousticness: >0.4
- Instrumentalness: no strong preference
- Valence: 0.3-0.7
- Mode: no strong preference
- **Rationale:** Temporary dip, baseline is strong. Wider ranges — the body doesn't need aggressive intervention, just gentle support.

### Baseline (varied, mood-appropriate)
- BPM: 70-110
- Energy: 0.3-0.6
- Acousticness: 0.2-0.7
- Instrumentalness: no strong preference
- Valence: 0.4-0.7
- Mode: no strong preference
- **Rationale:** No strong physiological signal. Widest ranges of any state. Music should be pleasant and balanced.

### Peak Readiness (anything goes)
- BPM: 90-150+
- Energy: 0.5-1.0
- Acousticness: no minimum
- Instrumentalness: no strong preference
- Valence: >0.5
- Mode: no strong preference
- **Rationale:** Body is primed. Match energy and positivity. No physiological constraint — this is the state where the system can lean into your highest-energy favorites.

---

## References

### Music and ANS
- Bretherton et al., 2019 — Controlled Tempo Manipulations (Music Perception)
- Bernardi et al., 2006 — Cardiovascular/respiratory changes from music (Heart)
- Ooishi et al., 2017 — Oxytocin/cortisol and tempo (PLOS ONE)
- Kim et al., 2024 — Music tempo and HRV during exercise (J Exerc Rehabil)
- Dey et al., 2017 — Heart rate entrainment to acoustic tempo (Scientific Reports)
- Khalfa et al., 2002 — Skin conductance and musical emotions (Neuroscience Letters)
- Zhang et al., 2024 — Major/minor mode physiological responses (Frontiers in Psychology)
- Chanda & Levitin, 2013 — Neurochemistry of Music (Trends in Cognitive Sciences)
- Thoma et al., 2013 — Music and Stress Response (PLOS ONE)
- Scarratt et al., 2023 — Sleep/study music features (PMC)
- Ellis & Thayer, 2010 — Music and ANS function (PMC)

### Iso Principle
- Heiderscheit & Madson, 2015 — Clinical case study (Augsburg University)
- Saarikallio et al., 2021 — Emotion modulation and iso principle (IJERPH)
- Starcke & von Georgi, 2024 — Iso principle modulates affective state (Musicae Scientiae)
- Li et al., 2024 — Generated Therapeutic Music via ISO Principle (ResearchGate)

### HRV and Sports Science
- Plews et al., 2012 — HRV in elite triathletes (Eur J Appl Physiol)
- Buchheit, 2014 — Monitoring training status with HR measures (Frontiers in Physiology)
- PMC, 2024 — HRV Applications in Strength and Conditioning

### Sleep
- Van Dongen & Dinges, 2003 — Cumulative Cost of Additional Wakefulness (SLEEP)
- NCBI StatPearls — Physiology, Sleep Stages
- Sleep Foundation — Deep Sleep, Stages of Sleep, Sleep Debt

### WHOOP Validation and Metric Importance
- medRxiv, 2024 — Systematic Review of WHOOP Accuracy (Khodr et al.)
- PMC, 2022 — Validation of Six Wearable Devices
- Lundstrom et al., 2024 — Raw HRV vs Recovery Score in NCAA Swimmers (Int J Sports Science & Coaching)
- Doherty, Lambe, Altini et al., 2025 — Composite Health Scores in Consumer Wearables (Translational Exercise Biomedicine)
- Altini, M. — Measurements vs Made Up Scores (HRV4Training / Substack)
- Antwerp University Hospital — WHOOP HRV Accuracy Validation (PMC)

### LLM Classification
- Yang et al., 2025 — LLMs for Automated Music Emotion Annotation (arXiv)
- Deezer/RecSys, 2025 — Biases in LLM-Generated Musical Taste Profiles
- OpenAI — Structured Outputs Documentation
