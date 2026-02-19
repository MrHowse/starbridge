"""
Triage Puzzle — Medical station.

Patient cards with symptoms → identify pathogen → assign treatment steps
in the correct order, under time pressure.

Difficulty controls the number of patients and whether any are pre-diagnosed:
  1 → 2 patients, 1 pre-diagnosed  (easiest: one answer given as example)
  2 → 2 patients, 0 pre-diagnosed
  3 → 3 patients, 0 pre-diagnosed
  4 → 4 patients, 0 pre-diagnosed
  5 → 5 patients, 0 pre-diagnosed

Science → Medical assist:
  reveal_pathogen — Science pathogen analysis reveals the pathogen for
                    one undiagnosed patient (makes identification trivial
                    for that patient; player still orders treatment steps).
"""
from __future__ import annotations

import random
from typing import Any

from server.puzzles.base import PuzzleInstance
from server.puzzles.engine import register_puzzle_type

# ---------------------------------------------------------------------------
# Data tables
# ---------------------------------------------------------------------------

PATHOGENS: list[str] = [
    "Velorian Flu",
    "Kessler Plague",
    "Nebula Fever",
    "Quantum Pox",
    "Void Rot",
]

SYMPTOM_MAP: dict[str, list[str]] = {
    "Velorian Flu":   ["fever", "dry_cough", "fatigue"],
    "Kessler Plague": ["rash", "nausea", "joint_pain"],
    "Nebula Fever":   ["hallucinations", "fever", "light_sensitivity"],
    "Quantum Pox":    ["blistering", "vertigo", "nausea"],
    "Void Rot":       ["tissue_necrosis", "blackout", "muscle_weakness"],
}

TREATMENT_MAP: dict[str, list[str]] = {
    "Velorian Flu":   ["quarantine", "antiviral", "rest"],
    "Kessler Plague": ["quarantine", "antibiotic", "rest"],
    "Nebula Fever":   ["isolation", "neuro_stabilizer", "antiviral"],
    "Quantum Pox":    ["quarantine", "immunosuppressant", "antiseptic"],
    "Void Rot":       ["isolation", "cell_regenerator", "neural_support"],
}

# (num_patients, pre_diagnosed_count)
_DIFFICULTY_PARAMS: dict[int, tuple[int, int]] = {
    1: (2, 1),
    2: (2, 0),
    3: (3, 0),
    4: (4, 0),
    5: (5, 0),
}


# ---------------------------------------------------------------------------
# Puzzle class
# ---------------------------------------------------------------------------


class TriagePuzzle(PuzzleInstance):
    """Medical station triage puzzle."""

    def generate(self, **kwargs: Any) -> dict:
        num_patients, pre_diagnosed = _DIFFICULTY_PARAMS.get(self.difficulty, (2, 0))

        chosen_pathogens = random.sample(PATHOGENS, num_patients)

        self._patients: list[dict] = []
        for i, pathogen in enumerate(chosen_pathogens):
            self._patients.append({
                "id":               f"patient_{i}",
                "pathogen":         pathogen,
                "symptoms":         list(SYMPTOM_MAP[pathogen]),
                "treatment_steps":  list(TREATMENT_MAP[pathogen]),
                "pre_diagnosed":    i < pre_diagnosed,
            })

        # Track which patients have been diagnosed (via assist or pre-diagnosis)
        self._diagnosed_flags: dict[str, bool] = {
            p["id"]: p["pre_diagnosed"] for p in self._patients
        }

        # Build the payload — hide pathogen for undiagnosed patients
        patients_data = [
            {
                "id":       p["id"],
                "symptoms": p["symptoms"],
                "pathogen": p["pathogen"] if p["pre_diagnosed"] else None,
            }
            for p in self._patients
        ]

        # Full set of all treatment steps across all pathogens (sorted, unique)
        all_treatments = sorted({
            step
            for steps in TREATMENT_MAP.values()
            for step in steps
        })

        return {
            "patients":             patients_data,
            "available_pathogens":  list(PATHOGENS),
            "available_treatments": all_treatments,
        }

    def validate_submission(self, data: dict) -> bool:
        """Return True iff every patient is correctly diagnosed.

        Expected shape::

            {
                "diagnoses": {
                    "patient_0": {
                        "pathogen":        "Velorian Flu",
                        "treatment_steps": ["quarantine", "antiviral", "rest"],
                    },
                    ...
                }
            }
        """
        diagnoses = data.get("diagnoses")
        if not isinstance(diagnoses, dict):
            return False

        for patient in self._patients:
            pid = patient["id"]
            if pid not in diagnoses:
                return False
            diag = diagnoses[pid]
            if not isinstance(diag, dict):
                return False
            if diag.get("pathogen") != patient["pathogen"]:
                return False
            if diag.get("treatment_steps") != patient["treatment_steps"]:
                return False

        return True

    def apply_assist(self, assist_type: str, data: dict) -> dict:
        """Apply an assist to the puzzle.

        ``reveal_pathogen`` — Science pathogen analysis.
            Reveals the pathogen for the first undiagnosed patient and marks
            that patient as diagnosed so the assist isn't applied twice.
            Returns ``{"patient_id": str, "pathogen": str}`` or ``{}`` when
            all patients are already diagnosed.
        """
        if assist_type == "reveal_pathogen":
            for patient in self._patients:
                pid = patient["id"]
                if not self._diagnosed_flags[pid]:
                    self._diagnosed_flags[pid] = True
                    return {
                        "patient_id": pid,
                        "pathogen":   patient["pathogen"],
                    }
            return {}  # All patients already diagnosed

        return {}


register_puzzle_type("triage", TriagePuzzle)
