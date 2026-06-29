"""
Compare current vs fixed engine on a 10-match Test series:
India Test XI (stronger) vs India Limited XI (weaker in Tests).

Metrics: top-scorer share, top-wkt-taker share, non-front-line wicket fraction
(per match), bowler wickets-vs-overs correlation + stronger-team win rate
(series), and a top-5 batsmen raw/adjusted/series-average table.
"""

import json
import random
from collections import defaultdict

import cricket_engine as v1
import cricket_engine_v2 as v2

DATA = json.load(open("data/players.json"))
BY_NAME = {p["name"]: p for p in DATA}

TEST_XI = ["Sunil Gavaskar", "Virender Sehwag", "Rahul Dravid", "Sachin Tendulkar",
           "Virat Kohli", "VVS Laxman", "Rishabh Pant", "Kapil Dev",
           "Ravichandran Ashwin", "Anil Kumble", "Jasprit Bumrah"]
LIMITED_XI = ["Rohit Sharma", "Ishan Kishan", "Kannaur Lokesh Rahul", "Suryakumar Yadav",
              "Yuvraj Singh", "MS Dhoni", "Suresh Raina", "Hardik Pandya",
              "Axar Patel", "Bhuvneshwar Kumar", "Shardul Thakur"]

VENUES = ["Wankhede Stadium, Mumbai", "Eden Gardens, Kolkata", "Melbourne Cricket Ground",
          "Sydney Cricket Ground", "Lord's, London", "Newlands, Cape Town",
          "Galle International Stadium", "WACA Ground, Perth",
          "Dubai International Cricket Stadium", "Basin Reserve, Wellington"]

TEST_NAME, LTD_NAME = "India Test XI", "India Limited XI"
team_test = [BY_NAME[n] for n in TEST_XI]
team_ltd = [BY_NAME[n] for n in LIMITED_XI]


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / (vx * vy) ** 0.5 if vx > 0 and vy > 0 else float("nan")


def match_metrics(m):
    """Per-match: top-scorer share, top-wkt share, non-front-line wkt fraction."""
    runs, team_runs = defaultdict(int), defaultdict(int)
    wkts, team_wkts = defaultdict(int), defaultdict(int)
    nonfront_w, total_w = 0, 0
    for inn in m["innings"]:
        bt, bw = inn["batting_team"], inn["bowling_team"]
        for b in inn["batting"]:
            runs[(bt, b["name"])] += b["runs"]
            team_runs[bt] += b["runs"]
        for bo in inn["bowling"]:
            wkts[(bw, bo["name"])] += bo["wickets"]
            team_wkts[bw] += bo["wickets"]
            total_w += bo["wickets"]
            p = BY_NAME.get(bo["name"])
            if p is None or v2.bowl_tier(p, "Test") != "front":
                nonfront_w += bo["wickets"]

    def top_share(per_player, per_team):
        shares = []
        for t in per_team:
            if per_team[t] <= 0:
                continue
            top = max((v for (tt, _), v in per_player.items() if tt == t), default=0)
            shares.append(top / per_team[t])
        return max(shares) if shares else 0.0

    return {
        "top_scorer_share": top_share(runs, team_runs),
        "top_wkt_share": top_share(wkts, team_wkts),
        "nonfront_wkt_frac": (nonfront_w / total_w) if total_w else 0.0,
    }


def run_series(engine, seed=42):
    random.seed(seed)
    matches, ov_wk = [], []
    wins = defaultdict(int)
    bat_runs, bat_outs = defaultdict(int), defaultdict(int)   # series batting avg
    for venue in VENUES:
        m = engine.simulate_test(team_test, team_ltd, TEST_NAME, LTD_NAME, venue)
        matches.append({"venue": venue, "winner": m["winner"], **match_metrics(m)})
        if m["winner"]:
            wins[m["winner"]] += 1
        for inn in m["innings"]:
            for b in inn["batting"]:
                bat_runs[b["name"]] += b["runs"]
                if b["out"]:
                    bat_outs[b["name"]] += 1
            for bo in inn["bowling"]:
                ov_wk.append((bo["overs"], bo["wickets"]))
    return {
        "matches": matches,
        "win_rate": wins[TEST_NAME] / len(VENUES),
        "wins": dict(wins),
        "draws": len(VENUES) - sum(wins.values()),
        "wkt_over_corr": pearson([o for o, _ in ov_wk], [w for _, w in ov_wk]),
        "bat_runs": dict(bat_runs),
        "bat_outs": dict(bat_outs),
    }


def series_avg(res, name):
    r, o = res["bat_runs"].get(name, 0), res["bat_outs"].get(name, 0)
    return r / o if o else float(r)


def fmt(x, n=2):
    return f"{x:.{n}f}" if x == x else "nan"   # nan-safe


def main():
    r1 = run_series(v1)
    r2 = run_series(v2)

    print("=" * 78)
    print(f"  {TEST_NAME} (stronger)  vs  {LTD_NAME}   — 10 Tests, 10 venues")
    print("=" * 78)

    print("\nPER-MATCH METRICS (current → fixed)\n")
    print(f"{'#':>2} {'venue':28s} | top-bat% | top-wkt% | nonfront-wkt%")
    for i, (a, b) in enumerate(zip(r1["matches"], r2["matches"]), 1):
        v = a["venue"][:28]
        print(f"{i:>2} {v:28s} | {a['top_scorer_share']*100:4.0f} →{b['top_scorer_share']*100:3.0f} "
              f"| {a['top_wkt_share']*100:4.0f} →{b['top_wkt_share']*100:3.0f} "
              f"| {a['nonfront_wkt_frac']*100:4.0f} →{b['nonfront_wkt_frac']*100:3.0f}")

    def avg(ms, k):
        return sum(x[k] for x in ms) / len(ms)

    print("\nSERIES AGGREGATES")
    print(f"{'metric':32s} | {'current':>10s} | {'fixed':>10s}")
    print(f"{'mean top-scorer share':32s} | {avg(r1['matches'],'top_scorer_share')*100:9.1f}% | {avg(r2['matches'],'top_scorer_share')*100:9.1f}%")
    print(f"{'mean top-wkt-taker share':32s} | {avg(r1['matches'],'top_wkt_share')*100:9.1f}% | {avg(r2['matches'],'top_wkt_share')*100:9.1f}%")
    print(f"{'mean non-front-line wkt frac':32s} | {avg(r1['matches'],'nonfront_wkt_frac')*100:9.1f}% | {avg(r2['matches'],'nonfront_wkt_frac')*100:9.1f}%")
    print(f"{'bowler wkts-vs-overs corr':32s} | {fmt(r1['wkt_over_corr']):>10s} | {fmt(r2['wkt_over_corr']):>10s}")
    print(f"{'stronger-team win rate':32s} | {r1['win_rate']*100:9.0f}% | {r2['win_rate']*100:9.0f}%")
    print(f"{'  W/D/L (TestXI)':32s} | {r1['wins'].get(TEST_NAME,0)}/{r1['draws']}/{r1['wins'].get(LTD_NAME,0):>3} | "
          f"{r2['wins'].get(TEST_NAME,0)}/{r2['draws']}/{r2['wins'].get(LTD_NAME,0):>3}")

    print("\nTOP-5 BATSMEN — raw / adjusted / series avg")
    for label, names in ((TEST_NAME, TEST_XI), (LTD_NAME, LIMITED_XI)):
        top5 = sorted(names, key=lambda n: -v2._num(v2._fmt(BY_NAME[n], "Test").get("bat_avg") or 0))[:5]
        print(f"\n  {label}")
        print(f"  {'player':22s} | {'raw':>6s} | {'adj':>6s} | {'series(cur)':>11s} | {'series(fix)':>11s}")
        for n in top5:
            p = BY_NAME[n]
            raw = v2._num(v2._fmt(p, "Test").get("bat_avg") or 0)
            adj = v2._adj_bat(p, "Test")
            print(f"  {n:22s} | {raw:6.2f} | {adj:6.2f} | {series_avg(r1,n):11.2f} | {series_avg(r2,n):11.2f}")

    json.dump({"current": r1, "fixed": r2}, open("eval_compare_output.json", "w"), indent=2)
    print("\n[written eval_compare_output.json]")


if __name__ == "__main__":
    main()
