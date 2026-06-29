# Match Simulation Engine — Rehash Spec

Status: design agreed, not yet implemented. Targets `cricket_engine.py` only
(the `match_simulator.py` LLM layer just narrates fixed facts and is unaffected).

---

## 1. Problem statement

The engine simulates batting and bowling in two independent passes
(`simulate_innings` → batting; `_assign_wickets` / `_bowling_card` → wickets &
runs sprinkled afterward). This produces five symptoms:

1. One player dominates disproportionately (unbounded `expovariate` scores).
2. Sparse stats inflate performance (a 5-match avg is trusted like a 100-match avg).
3. Non-bowlers take wickets (Warner qualifies on `bowl_avg > 0`).
4. Part-timers get too many overs/wickets (no over budget).
5. Series too one-sided (no team-vs-team coupling; small edges compound).

**Root cause:** batting and bowling are uncoupled — scores come from each
batsman's own average, wickets are distributed post-hoc over a too-loose bowler
pool, and the opposition's quality never enters the batting calculation.

---

## 2. Scope

**In scope**

- **Fix 1** — Bayesian regression of `bat_avg` / `bowl_avg` toward pool means (Problem 2).
- **Fix 2** — bowler eligibility + over budget + coupled bowling card (Problems 3, 4).
- **Coupling (Level 1+2)** — batting mean depends on the opposition attack;
  bowling card derived from records, overs, and pitch (Problems 1, 5 + the fundamental decoupling).

**Explicitly out of scope**

- ~~Old Fix 4 (top-down win-probability anchor)~~ — replaced by unit-level coupling
  with a damping knob `β`, which is the principled version of the same goal.
- ~~Old Fix 5 (post-hoc rescale of top scorer)~~ — breaks scorecard consistency.
  Fix 1 + coupling already substantially mitigate Problem 1 (e.g. a 3-innings
  player regresses from avg 78 → 45.7). A hard **draw-time** tail cap remains
  available as an optional lever *if the eval shows freak scores persist* — but
  no post-hoc rescaling.
- **Level 3 (ball/partnership-level attribution — "Steyn bowled Kohli")** — large
  rewrite that buys narration attribution, not better outcomes. Deferred.
- **Strike rate / economy modeling** — see §7. Deferred; data not available.

---

## 3. Architecture changes

| Pass | Today | After |
|---|---|---|
| Batting | score = f(own avg, pitch) | score = f(own **adj** avg, pitch, **opposition attack**) |
| Bowler pool | anyone with `bowl_avg > 0` | role-based eligibility + over budget |
| Wickets | weighted by skill × pitch | weighted by **overs** × skill × pitch, capped |
| Runs conceded | random fraction of total | derived from overs × economy, summed to total |

The batting loop's *structure* is unchanged — we only feed it better inputs and
one extra opposition term. The bowling card is rebuilt from real drivers.

---

## 4. Fix 1 — Bayesian regression

```
adjusted = (n · raw_avg + k · pool_mean) / (n + k)
```

Applied to both `bat_avg` and `bowl_avg`, with **different n, k, and pool means**:

| skill | n (sample size) | field | k (start) | pool means (Test / ODI / T20I) |
|---|---|---|---|---|
| bat_avg | innings batted | `innings_bat` (fallback `matches`) | 15 | 39.2 / 36.0 / 28.1 |
| bowl_avg | wickets taken | `wickets` | 40 | 30.5 / 31.0 / 23.1 |

- Pool means are **fixed constants** computed once from `data/players.json`
  (specialist filters: batsmen `bat_avg≥20 & innings_bat≥40`; bowlers `wickets≥50`).
  Not recomputed per match (that would be circular).
- `raw ≤ 0 → return pool_mean` (unknown player = league average).
- Order of operations everywhere: **raw → regress → pitch**.

**Implementation:** two accessors `_adj_bat(player, fmt)` / `_adj_bowl(player, fmt)`
(idempotent, no dict mutation), swapped into the 5 read-sites:
`batting_order` (142), `_top_bat_avg` (177), `simulate_innings` bat read (232),
`_bowling_strength` (169), `_assign_wickets` (191).
`is_bowler` (137) stays on **raw** stats — eligibility is Fix 2's job.

---

## 5. Coupling — batting mean depends on the opposition attack (Level 1)

```
attack_strength    = mean over front-line bowlers of (1 / adj_bowl_avg) × pitch_mult(type)
league_avg_attack  = (1 / pool_mean_bowl) × (pace + spin) / 2          # self-consistent anchor
multiplier         = (league_avg_attack / attack_strength) ** β        # β in (0,1]
mean               = adj_bat × format_const × pitch_bat × multiplier
```

- `format_const`: Test 0.92, ODI 0.80, T20I 0.72 (unchanged from `_bat_mean`).
- The anchor guarantees a **league-average, balanced attack → multiplier = 1.0**,
  i.e. today's behaviour. Only better/worse-than-average attacks move it.
- Pitch enters each bowler's term *and* the anchor symmetrically, so a balanced
  average attack stays at 1.0 on any surface; only better-*suited* attacks (e.g.
  spin on a turner) shift it. Surface scoring-ease is handled separately by `pitch_bat`.
- **`β` is the coupling-strength dial and the primary lever for one-sidedness.**
  β=0 → coupling off (today); β=1 → full. Start ~0.5, sweep in the eval until
  the stronger team wins ~60–65% of matches. Coupling *increases* separation, so
  per-match variance / β are what keep series from becoming blowouts.

Worked example (Clarke, adj_bat 48.4, neutral pitch, base mean 44.5, β=1):
average attack → 44.5; elite attack → ~36; weak attack → ~54.

---

## 6. Fix 2 — eligibility, over budget, coupled bowling card

Given a finished batting pass: total **R**, wickets **W**, innings overs **O**.

**6.1 Eligibility (who may bowl)**
- `role ∈ {Bowler, All-rounder}` → eligible.
- `role ∈ {Batsman, Wicket-keeper}` → 0 overs, **unless** part-time exception:
  `wickets / matches ≥ ~0.3` → may bowl as 5th option.
- Keyed off **role + raw wickets**, never `bowl_avg`.

**6.2 Over budget (sum to O)**
- Front-line bowlers share **~85%** of O; part-timers **~15%**; non-bowlers 0%.
- Within a tier, overs ∝ `(1 / adj_bowl_avg) × pitch_mult`.
- Per-bowler cap **≈ 40% of O**; front-liner min spell **~8–10 overs**.

**6.3 Wicket attribution (sum to W)**
- `weight_i = overs_i × (1 / adj_bowl_avg_i) × pitch_mult_i`.
- Distribute W by weight (multinomial); cap each at **`round(overs_i / 3)`**
  (≈ best-case 18 balls/wicket — the ceiling of an elite spell; mainly stops a
  3-over part-timer drawing 6).

**6.4 Runs-conceded attribution (sum ≈ R)**
- `weight_i = overs_i × economy_i`, where `economy_i = base × (adj_bowl_avg_i / pool_mean_bowl) ** 0.3`.
- Normalize to ~95% of R (remaining ~5% = extras / run-outs not credited).

**6.5 Conservation invariants**
- Σ overs = O, Σ wickets = W, Σ runs ≈ R. These are what make the card believable.

---

## 7. Strike rate — deferred (data gap)

Conceptually SR matters: **first-order for ODI/T20** (ball-capped innings — SR
drives the total), **second-order for Tests** (affects overs consumed → time →
draw/result). Modeling only `bowl_avg` also collapses attacking-but-expensive vs
defensive-but-cheap bowlers into one (`bowl_avg = economy × balls-per-wicket / 6`).

**But the dataset has no strike-rate, economy, or balls field** (confirmed across
all 344 players). Any SR model would be fabricated. Decision:
- **Tests (current work): defer.** Second-order; keep the format-level random SR
  band in `_balls_faced`. Note as a known limitation.
- **ODI/T20 (future): harvest real strike rates** via the existing ESPN scraper
  before modeling — faking it is worse than the current average-only model.
- The economy term in §6.4 is itself an average-derived **proxy**, to be replaced
  by real data if/when harvested.

---

## 8. What stays the same

Pitch profiles & venue overrides; follow-on and 450-over Test budget; day-by-day
mapping (`test_day_cards`); POTM & Player-of-Series accounting; parallel LLM
narration over fixed facts; `aggregate_series` structure.

---

## 9. Rule ledger — [P]rincipled / [E]mpirical / [K]nob

| # | Rule | Tag |
|---|---|---|
| 1 | `adjusted = (n·raw + k·mean)/(n+k)` | P |
| 2 | `n_bat = innings_bat` (fallback matches) | P |
| 3 | `n_bowl = wickets` (innings_bowl unreliable) | P |
| 4 | pool means 39.2/30.5, 36.0/31.0, 28.1/23.1 | E |
| 5 | specialist filters for pool means | K |
| 6 | `k_bat = 15`, `k_bowl = 40` | K |
| 7 | `raw ≤ 0 → pool_mean` | P |
| 8 | order: raw → regress → pitch | P |
| 9 | eligibility by role, not bowl_avg | P |
| 10 | part-time exception `wkts/matches ≥ 0.3` | K |
| 11 | overs split 85% / 15% / 0% | E |
| 12 | overs ∝ (1/adj_bowl_avg) × pitch_mult | P |
| 13 | per-bowler over cap ≈ 40% of O | E |
| 14 | front-liner min spell ~8–10 overs | K |
| 15 | wickets weighted by overs × skill × pitch | P |
| 16 | wicket cap `round(overs/3)` (≈18 balls/wkt floor) | K (floor) |
| 17 | runs ∝ overs × economy; economy from adj_bowl_avg | P (structure) |
| 18 | economy exponent `0.3` | K |
| 19 | extras fraction ~5% | K |
| 20 | conservation: Σovers=O, Σwkts=W, Σruns≈R | P |
| 21 | coupling damping `β` (start ~0.5) | K |

**Calibration knobs (the full [K] set to sweep in the eval):**
specialist filters (5), `k_bat`/`k_bowl` (6), part-time threshold (10),
min spell (14), wicket-cap floor (16), economy exponent (18), extras fraction (19),
coupling `β` (21).

---

## 10. Next step before coding

Define eval metrics that pin the [K] knobs, run on seeded simulations:
- top-scorer share of team total (distribution)
- fraction of wickets to non-front-line bowlers (target ≈ 0)
- bowler wickets vs overs correlation
- stronger-team win rate over many series (target ~60–65%)
- bowling strike-rate distribution vs real Test data (sanity for rule 16)

---

## Appendix A — Randomness map (current engine)

Every place chance enters `cricket_engine.py`. Three tiers: **load-bearing**
(drives the whole match), **structural coin-flips** (discrete branch points), and
**cosmetic noise** (uniform jitter unrelated to anything — Level 2 deletes these).

| # | Site | Call | Distribution | Controls | Tier |
|---|---|---|---|---|---|
| 1 | `_toss` (339) | `random.choice([t1,t2])` | uniform 50/50 | toss winner | structural |
| 2 | `_toss` (346) | `random.random() < bowl_bias` | Bernoulli 0.4–0.62 | bat/bowl | structural |
| 3 | `simulate_innings` (219) | `0.9 + 0.2*random.random()` | uniform [0.9,1.1] | run-rate jitter | cosmetic |
| 4 | `simulate_innings` (235) | `random.random() < 0.07` | Bernoulli 7% | duck hazard | structural |
| 5 | `simulate_innings` (238) | `random.expovariate(1/mean)` | exponential | **each batsman's score** | **load-bearing** |
| 6 | `_balls_faced` (298–302) | `random.uniform(45,65)` … | uniform band | strike rate → balls | cosmetic* |
| 7 | `_balls_faced` (303) | `+ random.randint(0,6)` | uniform int | balls jitter | cosmetic |
| 8 | `_assign_wickets` (200) | `random.choices(bs, weights)` | weighted categorical | **which bowler gets each wicket** | **load-bearing** |
| 9 | `_bowling_card` (315) | `random.uniform(0.85,1.0)` | uniform | runs handed to bowlers | cosmetic |
| 10 | `_bowling_card` (319) | `random.uniform(0.7,1.3)` | uniform | overs per bowler | cosmetic |
| 11 | `_bowling_card` (322) | `random.uniform(0.7,1.3)` | uniform | runs conceded per bowler | cosmetic |
| 12 | `simulate_test` (410) | `random.random() < 0.6` | Bernoulli 60% | enforce follow-on | structural |

Plus, outside the engine: `pick_venue` (`match_simulator.py`) `random.choice` over a
country's grounds — selects the pitch.

**Key observations**

- **#5 is the engine.** Total, wickets, and result all flow from summing per-batsman
  exponential draws. Draws are **i.i.d. across batsmen** — no correlation, no
  partnerships, no collapses; that independence is a structural choice, not a knob.
- **#9–#11 are fake randomness.** A bowler's economy is currently a coin toss
  disconnected from skill, wickets, or overs bowled. Level 2 replaces these with
  values derived from over budget × economy(adj_bowl_avg), summed to the real total.
- **\*#6 (strike rate)** is a format-wide band, not player-specific — the strike-rate
  gap noted in §7.
- **No seeding.** The engine uses Python's global RNG with no `random.seed()`, so runs
  are non-reproducible. Fine for game-time; the Monte Carlo eval (§10) must seed (or
  thread a `random.Random(seed)` instance) so knob-sweeps are comparable.

**How the rehash touches each source**

| Source | Change |
|---|---|
| #5 exponential | Fix 1 reshapes its `mean`; coupling multiplies `mean` by opposition strength; `β` damps |
| #8 wicket lottery | Fix 2 reweights (overs × skill × pitch), restricts (eligibility), caps (`round(overs/3)`) |
| #9–#11 cosmetic | replaced by record-derived overs/runs (Level 2) |
| #6 strike rate | deferred — replace band with player SR only with real data (§7) |
| #1,#2,#4,#12 structural | unchanged |
