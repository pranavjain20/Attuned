"""Generate score histogram for accumulated fatigue playlist."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from db.schema import get_connection
from db.queries import get_all_classified_songs, get_recent_playlist_track_uris
from matching.query_engine import compute_selection_scores
from matching.cohesion import select_cohesive_songs
from matching.state_mapper import get_state_neuro_profile

conn = get_connection()
profile = get_state_neuro_profile("accumulated_fatigue")
all_songs = get_all_classified_songs(conn)
songs = [s for s in all_songs if s.get("release_year") and s["release_year"] > 0]
recent = get_recent_playlist_track_uris(conn, "2026-03-13", days=2)
scored = compute_selection_scores(songs, profile, recent)
indices, stats = select_cohesive_songs(scored)
conn.close()

all_scores = [s[1] for s in scored]
selected_scores = [scored[idx][1] for idx in indices]

fig, ax = plt.subplots(figsize=(12, 6))
bins = np.linspace(0, max(all_scores) + 0.05, 40)
ax.hist(all_scores, bins=bins, color="#636e72", alpha=0.6,
        label=f"All candidates ({len(all_scores)})", edgecolor="white", linewidth=0.5)
ax.hist(selected_scores, bins=bins, color="#e17055", alpha=0.85,
        label=f"Selected for playlist ({len(selected_scores)})", edgecolor="white", linewidth=0.5)
ax.set_xlabel("Selection Score (neuro_match x confidence)", fontsize=12)
ax.set_ylabel("Number of Songs", fontsize=12)
ax.set_title("Accumulated Fatigue — Mar 13 (Recovery 19%)\n"
             "Score Distribution: 483 songs with full data", fontsize=14, fontweight="bold")
ax.legend(fontsize=11)
ax.annotate(
    f"Neuro: Para 0.95 / Symp 0.00 / Grnd 0.05\n"
    f"Selected: {min(selected_scores):.3f} – {max(selected_scores):.3f}\n"
    f"Pool median: {np.median(all_scores):.3f}\n"
    f"Cohesion: {stats.get('mean_similarity', 0):.3f}",
    xy=(0.98, 0.95), xycoords="axes fraction",
    ha="right", va="top", fontsize=10,
    bbox=dict(boxstyle="round,pad=0.5", facecolor="wheat", alpha=0.8),
)
plt.tight_layout()
plt.savefig("fatigue_score_histogram.png", dpi=150)
print("Saved to fatigue_score_histogram.png")
