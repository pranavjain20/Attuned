#!/usr/bin/env python3
"""Quick test: LLM vs Essentia for energy and acousticness on 25 test songs."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI

# Load API key
env_path = PROJECT_ROOT / ".env"
api_key = ""
for line in env_path.read_text().splitlines():
    if line.startswith("OPENAI_API_KEY="):
        api_key = line.split("=", 1)[1].strip()
        break

client = OpenAI(api_key=api_key)

SONGS = [
    ("Pal Pal Dil Ke Paas", "Kishore Kumar"), ("Chaand Taare", "Abhijeet"),
    ("Chand Sifarish", "Jatin-Lalit"), ("Yun Hi Chala Chal", "Udit Narayan"),
    ("Dil Kya Kare", "Adnan Sami"), ("Namo Namo", "Amit Trivedi"),
    ("Deva Deva", "Pritam"), ("Apna Bana Le", "Sachin-Jigar"),
    ("Kun Faya Kun", "A.R. Rahman"), ("Raataan Lambiyan", "Tanishk Bagchi"),
    ("Jashn-E-Bahaaraa", "A.R. Rahman"), ("Tum Se Hi", "Pritam"),
    ("Naina Da Kya Kasoor", "Amit Trivedi"), ("One Love", "Blue"),
    ("Levitating", "Dua Lipa"), ("Watermelon Sugar", "Harry Styles"),
    ("Maps", "Maroon 5"), ("Quit Playing Games (With My Heart)", "Backstreet Boys"),
    ("Excuses", "AP Dhillon"), ("Softly", "Karan Aujla"),
    ("Cheques", "Shubh"), ("Amplifier", "Imran Khan"),
    ("One Love", "Shubh"), ("Ride It", "Jay Sean"),
    ("Maan Meri Jaan", "King"),
]

EXP_ENERGY = {
    "Kun Faya Kun": "low", "Chaand Taare": "low", "Chand Sifarish": "low",
    "Pal Pal Dil Ke Paas": "low", "Quit Playing Games (With My Heart)": "low",
    "Dil Kya Kare": "medium", "Jashn-E-Bahaaraa": "medium", "Tum Se Hi": "medium",
    "Namo Namo": "medium", "Maan Meri Jaan": "medium", "Apna Bana Le": "medium",
    "Maps": "medium", "Ride It": "medium",
    "Raataan Lambiyan": "high", "Levitating": "high", "Watermelon Sugar": "high",
    "Excuses": "high", "Softly": "high", "One Love": "high",
    "Naina Da Kya Kasoor": "high", "Amplifier": "high", "Cheques": "medium",
    "Yun Hi Chala Chal": "medium",
}

EXP_ACOUSTIC = {
    "Pal Pal Dil Ke Paas": "high", "Chaand Taare": "high", "Chand Sifarish": "high",
    "Yun Hi Chala Chal": "medium", "Dil Kya Kare": "medium",
    "Namo Namo": "high", "Kun Faya Kun": "high", "Jashn-E-Bahaaraa": "high",
    "Tum Se Hi": "medium", "Naina Da Kya Kasoor": "low",
    "Levitating": "low", "Watermelon Sugar": "low",
    "Excuses": "low", "Softly": "low", "Amplifier": "low", "Cheques": "low",
    "Apna Bana Le": "medium", "Raataan Lambiyan": "low",
    "Maps": "low", "One Love": "low",
    "Ride It": "low", "Maan Meri Jaan": "medium",
    "Quit Playing Games (With My Heart)": "medium",
}


def bucket(v):
    if v <= 0.4:
        return "low"
    elif v <= 0.65:
        return "medium"
    return "high"


def main():
    song_lines = [f'{i+1}. "{n}" by {a}' for i, (n, a) in enumerate(SONGS)]

    prompt = (
        "For each song, provide two scores (0.0 to 1.0):\n"
        "1. energy: How intense/active the song feels. High=fast,loud,driving. Low=slow,soft,calm.\n"
        "2. acousticness: How acoustic/organic vs electronic. High=acoustic instruments. Low=electronic.\n"
        "Return JSON with index (1-based), energy (float), acousticness (float).\n\n"
        + "\n".join(song_lines)
    )

    print("Calling GPT-4o-mini...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "props",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "songs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "index": {"type": "integer"},
                                    "energy": {"type": "number"},
                                    "acousticness": {"type": "number"},
                                },
                                "required": ["index", "energy", "acousticness"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["songs"],
                    "additionalProperties": False,
                },
            },
        },
    )

    result = json.loads(response.choices[0].message.content)
    llm = {item["index"]: item for item in result["songs"]}

    # Essentia data
    ess_path = PROJECT_ROOT / "scripts" / "property_eval_results.json"
    ess_data = json.loads(ess_path.read_text())
    ess_by_name = {r["name"]: r for r in ess_data if r.get("status") == "ok"}

    # Percentile thresholds for Essentia flatness-based acousticness
    all_flat = sorted(
        [r.get("acousticness_flatness", 0) for r in ess_data if r.get("status") == "ok"]
    )
    p33 = all_flat[len(all_flat) // 3]
    p66 = all_flat[2 * len(all_flat) // 3]

    el, ee_c, al, ae_c = 0, 0, 0, 0
    te, ta = 0, 0

    header = f"{'Song':<40} {'LLM_E':>5} {'Ess_E':>5} {'Exp':>6} {'L':>2} {'E':>2}  {'LLM_A':>5} {'Ess_A':>5} {'Exp':>6} {'L':>2} {'E':>2}"
    print(f"\n{header}")
    print("-" * 100)

    for i, (name, artist) in enumerate(SONGS, 1):
        l_vals = llm.get(i, {})
        e_vals = ess_by_name.get(name, {})

        le = l_vals.get("energy", 0)
        la = l_vals.get("acousticness", 0)
        ee_v = min(1.0, e_vals.get("rms_raw", 0) / 0.35) if e_vals else None
        ea_v = e_vals.get("acousticness_flatness") if e_vals else None

        if ea_v is not None:
            ea_bkt = "high" if ea_v >= p66 else ("medium" if ea_v >= p33 else "low")
        else:
            ea_bkt = "?"

        ex_e = EXP_ENERGY.get(name, "?")
        ex_a = EXP_ACOUSTIC.get(name, "?")
        le_b = bucket(le)
        ee_b = bucket(ee_v) if ee_v is not None else "?"
        la_b = bucket(la)

        lec = "\u2713" if le_b == ex_e else "\u2717"
        eec = "\u2713" if ee_b == ex_e else "\u2717"
        lac = "\u2713" if la_b == ex_a else "\u2717"
        eac = "\u2713" if ea_bkt == ex_a else "\u2717"

        if ex_e != "?":
            te += 1
            if le_b == ex_e:
                el += 1
            if ee_b == ex_e:
                ee_c += 1
        if ex_a != "?":
            ta += 1
            if la_b == ex_a:
                al += 1
            if ea_bkt == ex_a:
                ae_c += 1

        label = f"{artist[:16]} \u2014 {name[:20]}"
        ee_s = f"{ee_v:.2f}" if ee_v is not None else "  \u2014"
        ea_s = f"{ea_v:.2f}" if ea_v is not None else "  \u2014"
        print(
            f"{label:<40} {le:>5.2f} {ee_s:>5} {ex_e:>6} {lec:>2} {eec:>2}"
            f"  {la:>5.2f} {ea_s:>5} {ex_a:>6} {lac:>2} {eac:>2}"
        )

    print("-" * 100)
    print(
        f"\nENERGY:       LLM = {el}/{te} ({el/te*100:.0f}%)"
        f"  |  Essentia = {ee_c}/{te} ({ee_c/te*100:.0f}%)"
    )
    print(
        f"ACOUSTICNESS: LLM = {al}/{ta} ({al/ta*100:.0f}%)"
        f"  |  Essentia = {ae_c}/{ta} ({ae_c/ta*100:.0f}%)"
    )


if __name__ == "__main__":
    main()
