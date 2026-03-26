# Attuned — Research Findings

**Date:** March 16, 2026
**Purpose:** Captures the published research that informs Attuned's design decisions. Every threshold, formula, and property range in the system traces back to findings documented here. This is the "why" behind the technical choices.

### A Note on Evidence Quality

This system is **evidence-informed**, not **evidence-based** in the clinical sense. Every design decision traces to published research, and the directional relationships are well-established (slower tempo → more parasympathetic activation, familiar music → stronger dopamine response). However, the mathematical precision of the formulas (specific weights, sigma values, threshold numbers) exceeds what any single study validates. The research tells us *which* properties matter and *in which direction* — our specific numbers are informed starting points that will be calibrated against real-world playlist quality. This is appropriate for a personal tool, but it would be incorrect to claim clinical-grade precision.

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

- **Karageorghis & Priest, 2012 (Sports Medicine):** Comprehensive review of music in sport and exercise. Confirmed tempo as the primary driver of psychophysical response, with energy/rhythm as secondary factors. Provided the framework for categorizing music as "sedative" (<80 BPM) vs "stimulative" (>120 BPM).

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

**Confounding note:** The Thoma 2013 finding is partially confounded — the classical/acoustic music used in the study was also lower tempo and lower energy than the control conditions. It's difficult to isolate acousticness from the tempo/energy effect. The independent contribution of acousticness to parasympathetic activation is plausible but less cleanly demonstrated than tempo's contribution. This is reflected in its lower weight (0.10 vs 0.35).

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

- "Weightless" (Marconi Union): starts at 60 BPM, slows to ~50 BPM within a single 8-minute track. The MindLab study that reported these numbers (65% anxiety reduction, 35% physiological reduction) was not peer-reviewed and was conducted for a marketing partnership. The directional finding (gradual tempo deceleration within a single track reduces anxiety) is consistent with the broader iso principle literature, but the specific numbers should not be treated as rigorous evidence.

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

There is no universal "X% per day" slope threshold. The field uses individual-baseline-relative approaches based on the Smallest Worthwhile Change (SWC = 0.5 × SD):

- **<0.5 SD below 30-day mean (Smallest Worthwhile Change):** Caution. Common during peak training blocks.
- **<1.0 SD below 30-day mean, sustained 3+ days:** Concern. Predicts upper-respiratory illness or non-functional overreaching. Triggers Accumulated Fatigue composite.
- **<1.5 SD below 30-day mean:** Significant. Strong overtraining signal.
- **7+ consecutive days below baseline:** Red flag regardless of magnitude.

This approach follows what Plews and Buchheit actually recommend: using the individual's own standard deviation as the ruler, rather than fixed percentages. A 20% decline means something very different for someone with an SD of 2ms vs 10ms. The SWC (0.5 × SD) adapts to individual HRV variability.

**Source:** Plews et al. 2012 found that in a non-functionally over-reached triathlete, the CV of 7-day rolling LnRMSSD showed "large linear reductions towards NFOR at -0.65%/week."

**Design decision:** State classifier uses LnRMSSD < (30-day mean - 1.0 × SD), sustained 3+ days, as the primary trigger for Accumulated Fatigue. <0.5 SD flags caution.

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

**Note on danceability:** The 0.05 weight for danceability reflects that its direct ANS evidence is the weakest of all seven properties. The rationale (rhythmic regularity provides a sense of predictability and control) is grounded in music psychology but lacks direct autonomic measurement studies comparable to tempo or energy. It's included because rhythm regularity is a meaningful perceptual quality, but its weight reflects the evidence gap.

### 7.2 Score Formulas (Starting Points — Tune on Real Data)

Sigmoid for parasympathetic/sympathetic (monotonic relationship), Gaussian for grounding (true peak).

**Function definitions:**

```
sigmoid_decay(x, plateau_below, decay_above) = 1.0 / (1.0 + exp((x - midpoint) / steepness))
  where midpoint = (plateau_below + decay_above) / 2, steepness = (decay_above - plateau_below) / 6

sigmoid_rise(x, decay_below, plateau_above) = 1.0 / (1.0 + exp(-(x - midpoint) / steepness))
  where midpoint = (decay_below + plateau_above) / 2, steepness = (plateau_above - decay_below) / 6

gaussian(x, center, sigma) = exp(-0.5 * ((x - center) / sigma)^2)
  — peaks at 1.0 when x = center, decays smoothly
```

**Parasympathetic activation score** (0.0-1.0, higher = more calming):
```
tempo_score     = sigmoid_decay(bpm, plateau_below=60, decay_above=90) * 0.35
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
tempo_score     = sigmoid_rise(bpm, decay_below=100, plateau_above=130) * 0.35
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

**Why sigmoid for parasympathetic/sympathetic, Gaussian for grounding:** Gaussian implies there's a peak and decline — that calming effect peaks at exactly 60 BPM and a song at 55 BPM is less calming. The research doesn't support this. Bretherton 2019 and Kim 2024 show parasympathetic activation increases as tempo decreases — it's monotonic, not bell-curved. A sigmoid correctly models "slower is better" with a plateau (you don't get infinitely calmer at 20 BPM). Same logic for sympathetic: "faster is more activating" plateaus rather than peaking. Grounding keeps Gaussian because 75 BPM is genuinely a centered target — too slow loses engagement, too fast loses calm.

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

### Poor Recovery (moderately calming, not aggressive)
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

## 9. Sleep Quality and Next-Day Subjective State

### 9.1 Sleep Quality Predicts How You Feel More Than How You Slept

The key insight for Attuned: playlists target how you FEEL, not your lab-measured cognitive performance. A person who slept great last night doesn't want "slow down" even if the week has been rough. The research strongly supports subjective state being disproportionately driven by last night's sleep.

- **Holding et al. (PMC6456824):** Bidirectional relationship between sleep quality and affect: sleep quality predicts next-day positive affect with a coefficient 2.6× larger than the reverse direction (affect → sleep). Sleep quality is the single strongest predictor of next-morning subjective state.

- **Nature Scientific Reports (2024):** Sleep efficiency is the strongest objective correlate of subjective sleep quality — stronger than total duration, onset latency, or wake-after-sleep-onset. People who spend more of their time in bed actually sleeping rate their sleep significantly better.

- **PMC12208346:** Reallocating just 30 minutes from light sleep to deep sleep improves positive affect by +0.38, independent of total sleep duration. It's not about sleeping longer — it's about sleeping better. The quality of sleep architecture matters more than quantity.

- **Dinges et al. / Belenky et al. (cumulative fatigue literature):** One good night does NOT fully reverse accumulated fatigue objectively. Cognitive performance, reaction time, and physiological markers require multiple recovery nights. However, subjective experience is disproportionately driven by the most recent night — people feel dramatically better after one good night even when objective impairment persists.

**Design decision:** Added a restorative sleep gate to the accumulated fatigue classifier. If last night meets all four conditions (no deep deficit, no REM deficit, efficiency >=85%, total >=6h), skip the fatigue classification and fall through to baseline. The playlist should match how the person feels, not what the week's trend says. Backtest: 62 of 150 fatigue days flipped to baseline. All had genuinely restorative sleep.

### 9.2 Sleep Efficiency as a Quality Marker

Sleep efficiency (time asleep / time in bed) emerges as the most reliable single proxy for sleep quality:

- Values >=85% are the clinical standard for "good" sleep efficiency (AASM)
- Below 85% is a diagnostic criterion for insomnia
- In the Nature Sci Rep 2024 study, efficiency predicted subjective quality better than any stage-specific metric

The restorative sleep gate uses 85% as the efficiency threshold — the clinical boundary between good and poor sleep efficiency.

---

## 10. Mood Tag Affinity — How Emotional Labels Map to Autonomic Dimensions

### 10.1 The Problem with Binary Mood Tags

The original system used three binary sets: parasympathetic tags (calm, peaceful, etc.), sympathetic tags (energetic, upbeat, etc.), and grounding tags (nostalgic, warm, etc.). A tag was either in a set (1.0) or not (0.0). This had three problems:

1. **No gradation:** "Motivational" was identical to "energetic" for sympathetic scoring, but motivational has a cognitive/grounding component that pure energy doesn't.
2. **No cross-dimensional contribution:** "Sad" was purely parasympathetic, but sad music has a strong grounding effect through self-referential processing.
3. **25% unassigned:** 449 tag instances across 45 unique tags defaulted to neutral 0.5 because they weren't in any set.

### 10.2 Russell's Circumplex Model (1980)

The foundational framework for mapping emotions to dimensions. All emotions can be placed on a 2D space of valence (positive–negative) × arousal (high–low). This maps cleanly onto the three autonomic dimensions:

- High arousal, positive valence → sympathetic activation (energetic, excited, euphoric)
- Low arousal, positive valence → parasympathetic (calm, serene, peaceful)
- Low arousal, negative valence → parasympathetic + grounding (sad, melancholic, reflective)
- High arousal, negative valence → sympathetic but different character (angry, anxious, intense)

The circumplex provides the theoretical backbone: mood tags don't live on a single dimension. Every tag has a position in the arousal-valence space that maps to a specific blend of para/symp/grnd weights.

### 10.3 Neurochemistry of Music-Mood Interactions

**Chanda & Levitin 2013 (Trends in Cognitive Sciences, PubMed 23541122):** Identified four neurochemical domains through which music modulates mood:

1. **Reward/Dopamine:** Music triggers dopamine release in the nucleus accumbens — the same reward pathway as food and social bonding. Drives the pleasure response to familiar, preferred, and anticipated music.
2. **Stress/Cortisol:** Calming music reduces cortisol levels. The parasympathetic pathway.
3. **Immunity:** Music influences immune function markers (IgA, natural killer cells). Less directly relevant to playlists but supports the physiological basis.
4. **Social/Oxytocin:** Group music and emotionally resonant music elevate oxytocin levels. Drives the "connection" feeling in grounding music.

**Salimpoor et al. 2011 (Nature Neuroscience, nn.2726):** Dopamine release occurs both during anticipation of a musical peak and during the experience itself. Familiar music triggers stronger anticipatory dopamine — supporting the familiarity effect and explaining why recently-played songs feel more rewarding.

**Keeler et al. 2015 (PMC4585277):** Group singing elevated oxytocin levels. While this studied group contexts, the oxytocin pathway is relevant to why devotional and community-oriented music (bhajans, spiritual songs) has grounding effects.

### 10.4 Mood Regulation Strategies

**Saarikallio & Erkkilä 2007:** Identified seven mood regulation strategies people use with music:

1. **Revival** — using music to get energy (sympathetic)
2. **Entertainment** — maintaining/improving positive mood (sympathetic + grounding)
3. **Solace** — seeking comfort when sad (parasympathetic + grounding)
4. **Mental work** — using music to think through problems (grounding)
5. **Diversion** — forgetting worries through music (sympathetic)
6. **Discharge** — releasing anger/sadness through music (sympathetic, despite negative valence)
7. **Strong sensation** — seeking intense emotional experience (sympathetic + grounding)

These strategies map to specific mood tags. "Motivational" aligns with revival + diversion (primarily sympathetic but with grounding). "Melancholic" aligns with solace + mental work (parasympathetic + grounding). The strategies informed the specific affinity weights.

### 10.5 Default Mode Network (DMN) and Self-Referential Processing

Three studies establish that certain types of music activate the brain's default mode network — the system responsible for self-reflection, memory, and emotional processing. This is the neurological basis for grounding scores.

**Taruffi et al. 2017 (Nature Scientific Reports, srep14396):** Sad music is the strongest DMN activator for self-referential processing. Listeners reported increased mind-wandering, memories, and introspective thought during sad music compared to happy or neutral music. This is why "sad" has a high grounding weight (0.55) — it triggers the exact processing that emotional grounding targets.

**Wilkins et al. 2014 (Nature Scientific Reports, srep6130):** Preferred/familiar music engages DMN more than unfamiliar music, supporting introspective processing. This is separate from the dopamine/reward pathway — familiar music activates both reward (dopamine) and self-referential (DMN) circuits.

**Barrett et al. 2023 (PMC11907061):** Nostalgia activates both DMN and reward networks simultaneously. Nostalgic music triggers autobiographical memory retrieval (DMN) alongside pleasure (reward). This dual activation explains why nostalgic songs feel both comforting and pleasurable — they ground you in personal history while activating reward circuits.

### 10.6 The Consolation Theory of Sad Music

**Huron 2011 (Music Perception, Sage 1029864911401171):** The prolactin consolation theory explains why people enjoy sad music. Sad stimuli trigger prolactin release (a consoling neurochemical), but because the sadness is vicarious (not a real loss), the listener gets the consolation without the grief. This creates a pleasant, bittersweet experience.

This explains the counterintuitive finding that sad music can be comforting rather than depressing. For mood tag affinity, "sad" and "melancholic" tags get parasympathetic weight (calming) AND grounding weight (emotional processing), not sympathetic activation. Sad music doesn't activate — it consoles and grounds.

### 10.7 Design Decision: The MOOD_AFFINITY Table

Based on the aggregate research, the binary frozensets were replaced with a `MOOD_AFFINITY` dictionary mapping 64 mood tags to (parasympathetic, sympathetic, grounding) weight triples. Examples:

| Tag | Para | Symp | Grnd | Rationale |
|---|---|---|---|---|
| calm | 0.80 | 0.00 | 0.30 | Classic parasympathetic, some grounding through stillness |
| energetic | 0.00 | 0.85 | 0.05 | Pure sympathetic activation |
| motivational | 0.00 | 0.65 | 0.25 | Revival strategy — energizing but with cognitive/grounding component |
| sad | 0.60 | 0.00 | 0.55 | Prolactin consolation (para) + DMN self-referential (grnd) |
| nostalgic | 0.35 | 0.00 | 0.75 | Barrett 2023 — DMN + reward, primarily grounding |
| spiritual | 0.65 | 0.00 | 0.55 | Parasympathetic + oxytocin grounding (Keeler 2015) |
| devotional | 0.70 | 0.00 | 0.50 | Deeper parasympathetic than spiritual, similar grounding |
| triumphant | 0.00 | 0.75 | 0.15 | Strong sympathetic with slight grounding from achievement |
| bittersweet | 0.40 | 0.00 | 0.65 | Consolation + strong self-referential processing |

`compute_mood_score` now returns a weighted average across all tags instead of a binary fraction. A song tagged ["motivational", "upbeat"] scores sympathetic = mean(0.65, 0.80) = 0.725, not 1.0. A song tagged ["spiritual", "peaceful"] scores parasympathetic = mean(0.65, 0.80) = 0.725 and grounding = mean(0.55, 0.30) = 0.425.

---

## 11. Playlist Cohesion — Why Individual Song Quality Isn't Enough

Picking the 20 highest-scoring songs individually doesn't make a good playlist. Songs must belong in the same sonic space.

### DJ Craft: Harmonic Mixing and Flow

Professional DJs maintain flow through harmonic mixing (compatible keys via the Camelot Wheel), BPM corridors (±5-8 BPM within a set), and energy arcs (build, peak, resolve — not random oscillation).

### Spotify Engineering: Algorithmic Playlists

Spotify's engineering research found genre coherence is the #1 signal — users tolerate variation in energy, tempo, and mood, but mixing genres destroys the experience. Their "audio neighborhoods" cluster songs by co-listening patterns, discovering "what belongs in the same room" from aggregate behavior.

### Music Therapy: The Iso Principle Applied to Playlists

Music therapists use the iso principle for playlist construction: start near the current state, gradually transition toward the desired state. Clinical research shows 3-5+ songs are needed for effective transition — 2 songs creates too-abrupt shifts (Saarikallio et al., 2021).

### Era Cohesion

Production technology creates sonic eras. Songs from different decades sound fundamentally different even in the same genre. Bollywood has longer stable periods punctuated by sudden breaks (A.R. Rahman in 1992, Honey Singh in 2011). Western music evolves more continuously. Genre-aware Gaussian decay on release year handles this: hip-hop σ=2 (tight eras), ghazal σ=12 (loose eras), Bollywood σ=6.

_Full era cohesion analysis: reference/era_cohesion_research.md. Full playlist cohesion research: reference/playlist_cohesion_research.md._

---

## References

### Music and ANS
- Bretherton et al., 2019 — Controlled Tempo Manipulations (Music Perception)
- Bernardi et al., 2006 — Cardiovascular/respiratory changes from music (Heart)
- Ooishi et al., 2017 — Oxytocin/cortisol and tempo (PLOS ONE)
- Kim et al., 2024 — Music tempo and HRV during exercise (J Exerc Rehabil)
- Dey et al., 2017 — Heart rate entrainment to acoustic tempo (Scientific Reports)
- Karageorghis & Priest, 2012 — Music in Sport and Exercise (Sports Medicine)
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

### Sleep Quality and Subjective State
- Holding et al. (PMC6456824) — Bidirectional sleep quality / affect relationship
- Nature Scientific Reports, 2024 — Sleep efficiency as strongest correlate of subjective sleep quality
- PMC12208346 — Light→deep sleep reallocation improves positive affect
- Dinges et al. — Cumulative fatigue and recovery timelines
- Belenky et al. — Sleep restriction and recovery of sustained performance

### Mood, Emotion, and Music Neuroscience
- Russell, 1980 — Circumplex Model of Affect (valence × arousal)
- Saarikallio & Erkkilä, 2007 — Seven mood regulation strategies with music
- Taruffi et al., 2017 — Sad music and DMN activation (Nature Scientific Reports, srep14396)
- Wilkins et al., 2014 — Preferred music engages DMN (Nature Scientific Reports, srep6130)
- Barrett et al., 2023 — Nostalgia activates DMN + reward networks (PMC11907061)
- Keeler et al., 2015 — Group music and oxytocin elevation (PMC4585277)
- Salimpoor et al., 2011 — Dopamine release during music anticipation (Nature Neuroscience, nn.2726)
- Huron, 2011 — Prolactin consolation theory for sad music (Music Perception, Sage 1029864911401171)

### LLM Classification
- Yang et al., 2025 — LLMs for Automated Music Emotion Annotation (arXiv)
- Deezer/RecSys, 2025 — Biases in LLM-Generated Musical Taste Profiles
- OpenAI — Structured Outputs Documentation
