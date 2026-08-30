"""
exporter.py -- Serialises the rule-annotated state to JSON and CSV.

Phase 11 of the ScoreVision pipeline.
The input must be the full annotated_state dict produced by bowling_rules.check_rules()
which itself operates on the §3 schema from temporal_fusion.StateTracker.

CSV columns (one row per bowler×frame):
  lane_number, row_label, bowler_name, is_team_row, frame,
  pinfall, cumulative, computed_cumulative, confidence, occluded,
  frame_rule_check, row_total, row_rule_check, unlabeled_metric
"""

import csv
import json
import os


def export_to_json(state: dict, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"Exported JSON -> {output_path}")


def export_to_csv(state: dict, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fieldnames = [
        "lane_number", "row_label", "bowler_name", "is_team_row", "frame",
        "pinfall", "cumulative", "computed_cumulative",
        "confidence", "occluded", "frame_rule_check",
        "row_total", "row_rule_check", "unlabeled_metric",
    ]

    lane          = state.get("lane_number", "")
    unlabeled     = state.get("unlabeled_metric", "")
    ts_range      = state.get("source_timestamp_range_sec", [None, None])

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row_data in state.get("rows", []):
            row_label   = row_data.get("row_label", "")
            bowler_name = row_data.get("bowler_name", "")
            is_team_row = row_data.get("is_team_row", False)
            row_total   = row_data.get("total", "")
            row_rc      = row_data.get("rule_check", "")
            frames      = row_data.get("frames", {})

            for frame_num in range(1, 11):
                key   = str(frame_num)
                fdata = frames.get(key, {})
                writer.writerow({
                    "lane_number":        lane,
                    "row_label":          row_label,
                    "bowler_name":        bowler_name,
                    "is_team_row":        is_team_row,
                    "frame":              frame_num,
                    "pinfall":            fdata.get("pinfall",            ""),
                    "cumulative":         fdata.get("cumulative",         ""),
                    "computed_cumulative":fdata.get("computed_cumulative",""),
                    "confidence":         fdata.get("confidence",         ""),
                    "occluded":           fdata.get("occluded",           ""),
                    "frame_rule_check":   fdata.get("rule_check",         "UNKNOWN" if fdata else "NOT_REACHED"),
                    "row_total":          row_total,
                    "row_rule_check":     row_rc,
                    "unlabeled_metric":   unlabeled,
                })

    print(f"Exported CSV  -> {output_path}")


def self_check(json_path: str, csv_path: str):
    """
    Quick consistency check: confirm JSON and CSV agree on every populated cell.
    Prints any discrepancies found; prints a summary count.
    """
    with open(json_path, encoding="utf-8") as f:
        state = json.load(f)

    # Build a lookup from JSON
    json_vals = {}
    for row_data in state.get("rows", []):
        rl = row_data["row_label"]
        for fn, fdata in row_data.get("frames", {}).items():
            json_vals[(rl, int(fn))] = (fdata.get("pinfall"), fdata.get("cumulative"))

    mismatches = 0
    checked    = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rl  = row["row_label"]
            fn  = int(row["frame"])
            key = (rl, fn)
            if key not in json_vals:
                continue
            j_pf, j_cum = json_vals[key]
            c_pf  = row["pinfall"] or ""
            j_pf_str = j_pf or ""
            c_cum_str = row["cumulative"].strip()
            c_cum = int(c_cum_str) if c_cum_str and c_cum_str.lstrip("-").isdigit() else None
            checked += 1
            if j_pf_str != c_pf or j_cum != c_cum:
                print(f"  MISMATCH ({rl}, frame {fn}): JSON=({j_pf_str},{j_cum}) CSV=({c_pf},{c_cum})")
                mismatches += 1

    print(f"Self-check: {checked} cells compared, {mismatches} mismatches.")
