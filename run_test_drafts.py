"""Run Test-only drafts, then simulations."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from itertools import combinations
from eval import (
    PERSONAS, PERSONA_MODEL, DRAFT_TIMEOUT, DRAFTS_DIR,
    run_draft, save_draft, run_simulations_from_file, ensure_server,
)

persona_ids = list(PERSONAS.keys())
all_pairings = list(combinations(persona_ids, 2))
fmt = "Test"

print(f"\n Cricket Fantasy Eval — Test Drafts")
print(f"  {len(all_pairings)} pairings")
print(f"  Persona model: {PERSONA_MODEL}")
print(f"  Timeout: {DRAFT_TIMEOUT // 60} minutes per draft")
print(flush=True)

log = []
completed = 0
timed_out = 0
failed = 0
saved_files = []

for p1, p2 in all_pairings:
    try:
        result = run_draft(p1, p2, fmt, log)
        filepath = save_draft(result)
        saved_files.append(filepath)
        print(f"  -> Saved: {filepath}", flush=True)
        if result["complete"]:
            completed += 1
        else:
            timed_out += 1
    except Exception as e:
        print(f"\n  DRAFT FAILED: {PERSONAS[p1]['display_name']} vs {PERSONAS[p2]['display_name']}: {e}", flush=True)
        import traceback; traceback.print_exc()
        failed += 1

print(f"\n  === DRAFTS DONE ===", flush=True)
print(f"  Completed: {completed}, Timed out: {timed_out}, Failed: {failed}", flush=True)

# Now run simulations
print(f"\n  === STARTING SIMULATIONS ===", flush=True)
for filepath in saved_files:
    try:
        run_simulations_from_file(filepath, log)
    except Exception as e:
        print(f"  SIM FAILED for {filepath}: {e}", flush=True)

print(f"\n  === ALL DONE ===", flush=True)
