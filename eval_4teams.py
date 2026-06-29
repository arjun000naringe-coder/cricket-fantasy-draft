"""
Round-robin eval on the fixed engine: 4 teams, each pair plays 20 Tests.
Metrics: per-match top-scorer share, top-wkt share, non-front-line wkt fraction;
series-wide wkts-vs-overs correlation; full win matrix; top-5 batsmen raw/adj/series.
"""

import json
import random
import itertools
from collections import defaultdict

import cricket_engine_v2 as v2

DATA = json.load(open("data/players.json"))
BY_NAME = {p["name"]: p for p in DATA}

TEAMS = {
    "World Test XI": ["Sunil Gavaskar", "Matthew Hayden", "Ricky Ponting", "Sachin Tendulkar",
                      "Brian Lara", "Jacques Kallis", "Kumar Sangakkara", "Shane Warne",
                      "Muttiah Muralitharan", "Glenn McGrath", "Dale Steyn"],
    "Spinning XI": ["Sunil Gavaskar", "Matthew Hayden", "Ricky Ponting", "Sachin Tendulkar",
                    "Brian Lara", "Kumar Sangakkara", "Muttiah Muralitharan", "Shane Warne",
                    "Ravichandran Ashwin", "Anil Kumble", "Rangana Herath"],
    "Allrounders XI": ["Garry Sobers", "Jacques Kallis", "Ben Stokes", "Imran Khan Niazi",
                       "Shakib Al Hasan", "Ravindra Jadeja", "Kapil Dev", "Shaun Pollock",
                       "Ian Botham", "Daniel Vettori", "Wasim Akram"],
    "Pacers Only": ["Sunil Gavaskar", "Matthew Hayden", "Ricky Ponting", "Sachin Tendulkar",
                    "Brian Lara", "Kumar Sangakkara", "Jasprit Bumrah", "Malcolm Marshall",
                    "Glenn McGrath", "Dale Steyn", "Curtly Ambrose"],
}

VENUES = ["Wankhede Stadium, Mumbai", "Eden Gardens, Kolkata", "Melbourne Cricket Ground",
          "Sydney Cricket Ground", "Lord's, London", "Newlands, Cape Town",
          "Galle International Stadium", "WACA Ground, Perth",
          "Dubai International Cricket Stadium", "Basin Reserve, Wellington"]

N_PER_PAIR = 20

# sanity: every name resolves
for t, names in TEAMS.items():
    missing = [n for n in names if n not in BY_NAME]
    assert not missing, f"{t}: missing {missing}"

teams = {t: [BY_NAME[n] for n in names] for t, names in TEAMS.items()}


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / (vx * vy) ** 0.5 if vx > 0 and vy > 0 else float("nan")


def match_metrics(m):
    runs, tr = defaultdict(int), defaultdict(int)
    wk, tw = defaultdict(int), defaultdict(int)
    nf, tot = 0, 0
    for inn in m["innings"]:
        bt, bw = inn["batting_team"], inn["bowling_team"]
        for b in inn["batting"]:
            runs[(bt, b["name"])] += b["runs"]; tr[bt] += b["runs"]
        for bo in inn["bowling"]:
            wk[(bw, bo["name"])] += bo["wickets"]; tw[bw] += bo["wickets"]; tot += bo["wickets"]
            p = BY_NAME.get(bo["name"])
            if p is None or v2.bowl_tier(p, "Test") != "front":
                nf += bo["wickets"]

    def top(per_pl, per_tm):
        sh = []
        for t in per_tm:
            if per_tm[t] > 0:
                sh.append(max((v for (tt, _), v in per_pl.items() if tt == t), default=0) / per_tm[t])
        return max(sh) if sh else 0.0

    return top(runs, tr), top(wk, tw), (nf / tot if tot else 0.0)


def main():
    random.seed(7)
    win = {a: defaultdict(int) for a in TEAMS}     # win[a][b] = a's wins vs b
    draws = defaultdict(int)                        # draws[frozenset(a,b)]
    pair_metrics = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    ov_wk = []
    bat_runs = {t: defaultdict(int) for t in TEAMS}
    bat_outs = {t: defaultdict(int) for t in TEAMS}

    for a, b in itertools.combinations(TEAMS, 2):
        for i in range(N_PER_PAIR):
            venue = VENUES[i % len(VENUES)]
            m = v2.simulate_test(teams[a], teams[b], a, b, venue)
            w = m["winner"]
            if w == a:
                win[a][b] += 1
            elif w == b:
                win[b][a] += 1
            else:
                draws[frozenset((a, b))] += 1
            ts, tw, nf = match_metrics(m)
            pm = pair_metrics[(a, b)]
            pm[0] += ts; pm[1] += tw; pm[2] += nf; pm[3] += 1
            for inn in m["innings"]:
                tm = inn["batting_team"]
                for bt in inn["batting"]:
                    bat_runs[tm][bt["name"]] += bt["runs"]
                    if bt["out"]:
                        bat_outs[tm][bt["name"]] += 1
                for bo in inn["bowling"]:
                    ov_wk.append((bo["overs"], bo["wickets"]))

    names = list(TEAMS)
    print("=" * 76)
    print("  ROUND-ROBIN — 4 teams, 20 Tests each pair (120 Tests), fixed engine")
    print("=" * 76)

    print("\nWIN MATRIX  (row's wins vs column; D = drawn)")
    print(f"  {'':16s}" + "".join(f"{n[:13]:>14s}" for n in names) + f"{'  W- D- L':>12s}")
    totals = {t: [0, 0, 0] for t in names}
    for a in names:
        cells = ""
        for b in names:
            if a == b:
                cells += f"{'—':>14s}"
            else:
                d = draws[frozenset((a, b))]
                cells += f"{f'{win[a][b]}-{win[b][a]} (D{d})':>14s}"
                totals[a][0] += win[a][b]; totals[a][2] += win[b][a]; totals[a][1] += d
        w, dr, l = totals[a]
        print(f"  {a:16s}" + cells + f"{f'{w}-{dr}-{l}':>12s}")

    print("\nSTANDINGS (across all 60 matches per team)")
    order = sorted(names, key=lambda t: -totals[t][0])
    for t in order:
        w, dr, l = totals[t]
        print(f"  {t:16s}  W {w:3d}   D {dr:3d}   L {l:3d}   win% {100*w/60:4.0f}")

    print("\nPER-PAIRING METRIC MEANS")
    print(f"  {'matchup':34s} | top-bat% | top-wkt% | nonfront%")
    for (a, b), pm in pair_metrics.items():
        c = pm[3]
        print(f"  {a+' v '+b:34s} | {100*pm[0]/c:6.1f}   | {100*pm[1]/c:6.1f}   | {100*pm[2]/c:6.1f}")

    allc = sum(pm[3] for pm in pair_metrics.values())
    mt = [sum(pm[k] for pm in pair_metrics.values()) / allc for k in range(3)]
    print("\nOVERALL")
    print(f"  mean top-scorer share     {100*mt[0]:5.1f}%")
    print(f"  mean top-wkt-taker share  {100*mt[1]:5.1f}%")
    print(f"  mean non-front wkt frac   {100*mt[2]:5.1f}%")
    print(f"  wkts-vs-overs correlation {pearson([o for o,_ in ov_wk],[w for _,w in ov_wk]):5.2f}")

    print("\nTOP-5 BATSMEN PER TEAM — raw / adj / series avg")
    for t in names:
        top5 = sorted(set(TEAMS[t]), key=lambda n: -v2._num(v2._fmt(BY_NAME[n], "Test").get("bat_avg") or 0))[:5]
        print(f"\n  {t}")
        for n in top5:
            p = BY_NAME[n]
            raw = v2._num(v2._fmt(p, "Test").get("bat_avg") or 0)
            adj = v2._adj_bat(p, "Test")
            r, o = bat_runs[t][n], bat_outs[t][n]
            sa = r / o if o else float(r)
            print(f"    {n:24s} | raw {raw:6.2f} | adj {adj:6.2f} | series {sa:6.2f}")

    json.dump({"win": {a: dict(win[a]) for a in win},
               "standings": totals, "overall": mt}, open("eval_4teams_output.json", "w"), indent=2)


if __name__ == "__main__":
    main()
