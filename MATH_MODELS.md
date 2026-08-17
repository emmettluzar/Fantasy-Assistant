# Mathematical Foundations & Decision Formulas

## 1. Dynamic League Configuration Schema
Every calculation must dynamically accept a `LeagueConfig` dictionary with defaults:
- `scoring`:
  - `pass_yd`: 0.04 (1 pt / 25 yds)
  - `pass_td`: 4.0 (or 6.0)
  - `pass_int`: -2.0
  - `rush_yd`: 0.1 (1 pt / 10 yds)
  - `rush_td`: 6.0
  - `rec`: 1.0 (PPR), 0.5 (Half-PPR), or 0.0 (Standard)
  - `rec_yd`: 0.1 (1 pt / 10 yds)
  - `rec_td`: 6.0
  - `te_rec_bonus`: 0.0 (or 0.5 - 1.0 for TE Premium)
  - `fumble_lost`: -2.0
- `roster_slots`:
  - `QB`: 1, `RB`: 2, `WR`: 2, `TE`: 1, `FLEX`: 1, `SUPERFLEX`: 0, `BENCH`: 6
- `teams_count`: 12

## 2. Expected Fantasy Points (xFP) & Usage
- **xFP Formulation:**
  xFP = sum_p( P(Comp_p) * (AirYds_p * v_rec_yd + E[YAC_p] * v_rec_yd + v_rec) + E[RushYds_p] * v_rush_yd + E[TD_p] * v_td + E[2PT_p] * v_2pt )
  (Multipliers v_* are drawn directly from the active `LeagueConfig.scoring`).

- **Weighted Opportunity Rating (WOPR):**
  WOPR = 1.5 * TargetShare + 0.7 * AirYardsShare

## 3. Dynamic Value Over Replacement Player (DVORP)
- **Baseline Formulation:**
  DVORP_i(t) = E[FP_i] - E[FP_repl(p, t)]
  - Replacement count `n(p)` is dynamically calculated: `n(p) = teams_count * roster_slots[p] + (flex_allocation)`.
  - In Superflex configurations (`SUPERFLEX >= 1`), QB replacement baseline expands to `teams_count * (roster_slots['QB'] + roster_slots['SUPERFLEX'])`.

## 4. Make-It-Back Probability (P_MB)
- **Model:**
  P_MB(i, r_next) = 1 - Phi( (r_next - ADP_i) / sigma_i )
  - Phi: Cumulative Distribution Function (CDF) of standard normal distribution (`scipy.stats.norm.cdf`).
  - r_next: User's next scheduled pick number.
  - sigma_i: Historical standard deviation of player's ADP (default = 4.5 if missing).

## 5. Master Decision Utility Score U_i(t)
- **Ranking Function:**
  U_i(t) = alpha * DVORP_i(t) + beta * (1 - P_MB(i, r_next)) + gamma * R_need(p) - delta * P_bye(i)
  - Default weights: alpha = 0.40, beta = 0.35, gamma = 0.20, delta = 0.05
  - R_need(p): Multiplier based on remaining open starter slots for position p on the user's roster.
  - P_bye(i): Penalty applied if player shares bye week with primary starters.