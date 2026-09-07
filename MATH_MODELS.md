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

  ## 6. Contingent Upside & Right-Tail Variance
- **Upside Score ($V_{upside}$):**
  - **Veterans:** Derived from the standard deviation ($\sigma$) of historical weekly fantasy points to isolate high-variance ceilings.
  - **Rookies / Backup RBs:** Calculated via Contingent Value. $\text{Contingent Value} = E[FP_{starter}] \cdot 0.75$.
  - Both metrics are combined and normalized into a single $V_{upside}$ score ranging from 0 to 1 across the available player pool.
- **Dynamic Utility Shift:**
  - The master utility function $U_i(t)$ introduces a new upside coefficient $\epsilon \cdot V_{upside}$.
  - In early rounds (filling starters), $\alpha$ (safety/DVORP) is weighted heavily and $\epsilon$ is near zero.
  - In late rounds (filling bench slots), $\alpha$ dynamically decays and $\epsilon$ scales up, prioritizing asymmetric upside targets over low-ceiling veterans.

  ## 7. Positional Tiers & Run Detection
- **Clustering:** 
  - Apply 1D K-Means or natural breaks clustering to the $xFP$ of the top available players at each position (QB, RB, WR, TE) to establish discrete scoring tiers.
- **Scarcity Multiplier ($S_m$):**
  - If a player is the last remaining asset in a high-value tier, apply a scarcity multiplier ($S_m \ge 1.0$).
  - If $N_{tier}$ (players remaining in the current tier) $= 1$, $S_m = 1.15$.
  - If $N_{tier}$ $= 2$, $S_m = 1.05$.
  - The Master Decision Utility Function $U_i(t)$ is multiplied by $S_m$ to prioritize halting a positional run.

  ## 8. Dynasty Multi-Year Valuation & Age Curves ($V_{dynasty}$)
- **Active Flag:** Triggered when `LeagueConfig.is_dynasty == True` (or format is set to Dynasty in the UI).
- **Multi-Year Horizon Discount ($H=3, r=0.15$):**
  $$V_{dynasty}(i) = \sum_{h=0}^{H-1} \frac{E[FP_i] \cdot A_{factor}(\text{pos}, \text{age}_i + h)}{(1 + r)^h}$$
- **RB Age Curve ($A_{factor}$):** Peak $\le 25$ (1.0 multiplier), ages 26-27 (0.80), 28-29 (0.55), 30+ (0.30).
- **WR Age Curve ($A_{factor}$):** Peak $\le 28$ (1.0 multiplier), ages 29-30 (0.85), 31-32 (0.65), 33+ (0.40).
- **TE Age Curve ($A_{factor}$):** Peak $\le 29$ (1.0 multiplier), ages 30-31 (0.85), 32-33 (0.65), 34+ (0.40).
- **QB Age Curve ($A_{factor}$):** Peak $\le 31$ (1.0 multiplier), ages 32-34 (0.90), 35-37 (0.75), 38+ (0.50).
- **Engine Integration:** In Dynasty mode, replace the single-season baseline $E[FP_i]$ in the $DVORP$ calculation with the annualized dynasty utility value $V_{dynasty}(i)$. Maintain all contingent upside, tier scarcity, and $P_{MB}$ mechanics.