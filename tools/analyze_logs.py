"""DESN-SW-008/011: 保存済み実機ログの完全性・形式・周期を再集計する。"""
import argparse
from collections import Counter
import json
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if not line.startswith("#")]


def analyze(directory):
    path = Path(directory)
    tx, rx, control = (rows(path / name) for name in ("tx.txt", "rx.txt", "error.txt"))
    metadata = json.loads((path / "tx.txt").read_text().splitlines()[1][2:])
    profiles = {p["profile_id"]: p for p in metadata["config"]["profiles"]}
    done = [e for e in tx if e["type"] == "TX_DONE"]
    final = next(e for e in control if e["type"] == "SESSION_END")
    start = next(e for e in control if e.get("command") == "START_SESSION")
    assert final["stats"]["rx"] == len(rx) and final["stats"]["tx_done"] == len(done)
    assert final["dropped"] == 0 and final["stop_confirmed"] and final["drain_complete"]
    assert len({(e["boot_id"], e["session_id"], e["seq"]) for e in done}) == len(done)
    for e in rx:
        assert start["start_time_us"] <= e["device_us"] < start["deadline_us"]
        assert not e["ide"] and e["fdf"] and e["brs"] and e["length"] == 64
        assert e["data"] == {0x100: "00" * 64, 0x200: "FF" * 64}[e["can_id"]]
    series = {}
    for pid, p in profiles.items():
        events = [e for e in done if e["profile_id"] == pid]
        for e in events:
            assert all(e[f] == p[f] for f in ("can_id", "ide", "fdf", "brs", "data", "period_ms"))
            assert e["txreq_us"] <= e["device_us"]
        intervals = [b["txreq_us"] - a["txreq_us"] for a, b in zip(events, events[1:])]
        late = [e["late_us"] for e in events]
        series[pid] = {"count": len(events), "period_ms": p["period_ms"],
                       "txreq_interval_us": {"min": min(intervals), "mean": sum(intervals) / len(intervals),
                                             "max": max(intervals)} if intervals else None,
                       "service_late_us_max": max(late) if late else None,
                       "service_late_over_2ms": sum(t > 2000 for t in late),
                       "txreq_at_or_after_deadline": sum(e["txreq_us"] >= start["deadline_us"] for e in events)}
    return {"directory": str(path), "metadata": metadata, "final": final, "series": series,
            "rx_id_counts": dict(Counter(hex(e["can_id"]) for e in rx)),
            "rx_payload_and_window": "PASS", "tx_payload_and_counts": "PASS",
            "errors": [e for e in control if e["type"] == "ERROR"],
            "measurement_note": "txreq_usはWRITE_SAFE発行直前のTBC読値。late_usは送信処理着手の遅れでありTXREQ反映の厳密測定ではない。"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = analyze(args.directory)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output)
    print(output)
