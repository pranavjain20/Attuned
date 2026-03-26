# Playlist Cohesion Research

Why picking the "right" 20 songs individually doesn't make a good playlist — and what DJs, Spotify engineers, and music therapists say about fixing it.

## The Problem

You have 1,360 classified songs. Each one has a neurological profile (parasympathetic, sympathetic, grounding scores). For a given physiological state like "accumulated fatigue," you score them all and pick the top 20.

Every song is individually correct. But the playlist sounds like a dumpster: Chaiyya Chaiyya → Roddy Ricch → The Beatles → Arijit Kumar. They all score high on parasympathetic activation, but they're from completely different sonic universes. Nobody would listen to this voluntarily.

**A playlist isn't the sum of its parts. Songs must belong in the same room.**

## What the Research Says

### DJ Craft: Harmonic Mixing and Flow

Professional DJs have known this forever. The art isn't picking good songs — it's creating **flow** between them.

- **Harmonic mixing (Camelot Wheel)**: Songs in compatible keys blend smoothly. Moving from 8A to 9A or 8B creates tension/release that feels intentional. Random key jumps feel jarring. *(We can't do this yet — 97.6% of our key data is NULL. Essentia could fill this later.)*
- **BPM corridors**: DJs stay within ±5-8 BPM during a set, slowly ramping up or down. Jumping from 70 BPM to 140 BPM breaks the groove even if both songs "match the mood."
- **Energy arcs**: Great sets have shape. They build, peak, and resolve. They don't oscillate randomly between high and low energy.

**How we use this**: BPM similarity is weighted 0.20 in our cohesion function. Songs >20 BPM apart score <0.14 similarity (Gaussian decay, σ=10). This keeps the tempo corridor tight. Energy similarity adds another 0.10. Key/harmonic matching is a future improvement when we have the data.

### Spotify Engineering: Algorithmic Playlists

Spotify's engineering blog and patents reveal their approach to making Discover Weekly and Daily Mix feel coherent:

- **Genre coherence is the #1 signal.** Spotify's research found that users tolerate a lot of variation in energy, tempo, and mood — but mixing genres destroys the listening experience. A playlist that's all indie rock but spans 80-130 BPM still feels "right." A playlist that bounces between K-pop, country, and metal feels broken, even at identical tempos.
- **"Audio neighborhoods"**: Spotify clusters songs into sonic neighborhoods based on co-listening patterns and audio features. Songs frequently listened to in the same sessions cluster together. Their collaborative filtering essentially discovers "what belongs in the same room" from aggregate user behavior.
- **Anchor songs**: Daily Mix starts from songs you love and expands outward. Rather than optimizing globally, it seeds from known preferences and adds the most similar candidates first. This greedy expansion from a seed is exactly our approach.

**How we use this**: Genre tags have the highest weight (0.30) in our similarity function. Mood tags are second (0.25). Together, these two "same room" signals account for 55% of the similarity score. Our seed-and-expand algorithm mirrors Spotify's anchor-based approach — start from the song with the best combination of neurological score and similarity to its neighbors, then greedily add the most similar candidate to the growing cluster.

### Music Therapy: The Iso Principle

Music therapy research (Altschuler, 1948; Thaut, 2005) established the **iso principle**: to affect physiological state, you start with music that matches the patient's current state and gradually transition toward the desired state.

- **Entrainment**: The autonomic nervous system synchronizes with rhythmic stimuli. Heart rate follows tempo. Breathing follows phrasing. But this only works if the transition is gradual — abrupt shifts break entrainment.
- **Genre consistency aids entrainment**: Research by Thaut & Hoemberg (2014) showed that rhythmic entrainment is more effective when the musical style remains consistent. The brain processes genre as a context signal — switching genres forces a "reset" that disrupts the physiological coupling.
- **Emotional processing requires safety**: For states like emotional processing deficit, the playlist needs to create a safe, consistent emotional container. Whiplashing between completely different emotional textures prevents the processing that grounding music is supposed to facilitate.

**How we use this**: By selecting a cohesive cluster of songs, we create the conditions for entrainment to work. All songs in the playlist share genre, mood, and tempo characteristics — the body can "lock in" to the musical environment. The sequencer (future work) will arrange songs within the cluster to follow the iso principle: starting near current state, transitioning toward target.

### Acoustic Psychology: Coherence and Listening Fatigue

Research on perceptual fluency (Reber, Schwarz & Winkielman, 2004) shows:

- **Processing fluency**: Stimuli that are easy to process feel more pleasant. A coherent playlist requires less cognitive processing — the brain forms expectations (genre, tempo range, production style) and each subsequent song confirms those expectations.
- **Listening fatigue**: Genre-hopping forces the auditory cortex to constantly recalibrate. This is mentally exhausting and counterproductive when the goal is physiological recovery or activation.
- **Production era matters**: A 1970s recording and a 2023 recording have fundamentally different sonic textures (dynamic range, frequency distribution, spatial imaging) even if they share genre and tempo. This creates a subtle "wrong room" feeling. *(Future work: we don't have release year data yet.)*

**How we use this**: Our acousticness similarity (weight 0.05) partially captures production texture differences. Songs with similar acousticness tend to share production era characteristics. This is a proxy — the real fix is fetching release year from Spotify and adding it as a cohesion dimension.

## Our Implementation: Seed-and-Expand

### Algorithm

1. **Score**: All 1,360 songs get a neurological score (existing — unchanged).
2. **Pool**: Take the top 60 candidates. All are neurologically appropriate for the detected state.
3. **Similarity matrix**: Compute pairwise similarity between all 60 candidates across genre, mood, BPM, energy, acousticness, danceability, and valence.
4. **Seed**: Pick the candidate with the best `neuro_score × neighborhood_density`. This is a song that's both a great neurological match AND has many similar songs nearby in the pool. An isolated outlier with a perfect neuro score won't be picked as seed.
5. **Expand**: Greedily add the candidate with the highest average similarity to songs already in the playlist. This naturally grows a coherent cluster.
6. **Stop at 20.** If we can't reach 15 songs above the similarity threshold, progressively relax the threshold (3 attempts, reducing by 0.03 each time).

### Similarity Weights

| Dimension | Weight | Reasoning |
|-----------|--------|-----------|
| Genre tags | 0.30 | Strongest coherence signal. Bollywood with Bollywood. |
| Mood tags | 0.25 | Energy flavor. "Party" ≠ "aggressive" ≠ "motivational" |
| BPM | 0.20 | Tempo corridor. Gaussian decay, σ=10 |
| Energy | 0.10 | Energy level consistency |
| Acousticness | 0.05 | Production texture |
| Danceability | 0.05 | Groove match |
| Valence | 0.05 | Emotional tone |

### Why This Works for a 679-Song Library

With a small personal library, strict cohesion could be too aggressive — you might only have 8 Bollywood songs that score high for a given state, making it impossible to fill 20 slots from one genre cluster. The progressive relaxation handles this: first try with similarity threshold 0.15, then 0.12, then 0.09, then 0.06. This lets the cluster grow to include "adjacent" genres (e.g., Hindi pop alongside Bollywood) when the core cluster is too small.

## What We Can't Do Yet (Future Work)

1. **Key/harmonic matching**: 97.6% of key data is NULL. Essentia analysis would fill this, enabling Camelot wheel-based harmonic transitions.
2. **Release year/era**: Not in our database. A 90s rock track next to a 2023 indie track creates subtle discord. Fix: fetch `album.release_date` from Spotify API.
3. **Vocal timbre**: No data. Would need audio fingerprinting or embeddings.
4. **Co-listening patterns**: We have extended streaming history showing what was played in the same sessions. Future work could mine session-level co-occurrence to discover personal "sonic neighborhoods."

## References

- Altschuler, I.M. (1948). A psychiatrist's experience with music as a therapeutic agent. *Music and Medicine*.
- Reber, R., Schwarz, N., & Winkielman, P. (2004). Processing fluency and aesthetic pleasure. *Personality and Social Psychology Review*, 8(4), 364-382.
- Thaut, M.H. (2005). *Rhythm, Music, and the Brain*. Routledge.
- Thaut, M.H., & Hoemberg, V. (2014). *Handbook of Neurologic Music Therapy*. Oxford University Press.
- Spotify Engineering Blog: "How Spotify's Algorithm Works" (various years).
