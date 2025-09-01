import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta

# ───── Example raw H1 result ─────
raw_h1 = """
Volatility 25 (1s) Index →  D1: Demand-leaning  @ 2025-05-31  |  zone bounds: (692109.9310, 699337.6420, 604226.3870, 590332.7540)
    H1: Demand-leaning  @ 2025-08-31 22:00  |  zone bounds: (636518.9250, 638085.0600, 628201.1805, 625998.9660)
    ⇒ 📌Exploit confirmed: still in Demand-leaning | cmp @ 630483.3800
"""

# ───── Segment 1: parse H1 base start + leg‑in ─────
h1_line    = [l for l in raw_h1.splitlines() if "H1:" in l][0]
# extract leaning
leaning    = h1_line.split("H1:")[1].split("@")[0].strip()
# extract base-start timestamp
time_str   = h1_line.split("@")[1].split("|")[0].strip()   # "2025-07-25 16:00"
base_start = datetime.strptime(time_str, "%Y-%m-%d %H:%M") # → 2025-07-25 16:00
leg_in_time = base_start - timedelta(hours=1)              # one bar before

print(f"--- Segment 1 ---")
print(f"Parsed H1 leaning:     {leaning}")
print(f"Base start at:         {base_start}")
print(f"Leg‑in time at:        {leg_in_time}\n")

# ───── Segment 2: fetch and print M10 bars ─────
symbol        = raw_h1.split("→")[0].strip()
m10_tf        = mt5.TIMEFRAME_M10

if not mt5.initialize():
    raise RuntimeError("MT5 init failed.")
m10_bars = mt5.copy_rates_range(symbol, m10_tf, leg_in_time, datetime.now())
mt5.shutdown()

df10 = pd.DataFrame(m10_bars)
df10['time'] = pd.to_datetime(df10['time'], unit='s')
df10.set_index('time', inplace=True)

print(f"--- Segment 2 ---")
print(f"Fetched {len(df10)} M10 bars for {symbol}")
print("\nFirst 5 M10 bars:")
print(df10.head().to_string(index=False))
print("\nLast 5 M10 bars:")
print(df10.tail().to_string(index=False), "\n")

# ───── Segment 3: detect candidate 10 m zones ─────
def is_basing(row):
    return abs(row.close - row.open) < 0.5 * (row.high - row.low)

def is_buy(row):
    return (row.close > row.open) and (not is_basing(row))

def is_sell(row):
    return (row.close < row.open) and (not is_basing(row))

# Distal‑override logic (identical to exploit_detect01.py)
def apply_override(core_prox, core_dist, conf, leg_in, highs, lows):
    # Supply case: conf sell
    if conf.close < conf.open:
        if leg_in.close > leg_in.open:
            return max(core_dist, leg_in.high, conf.high)
        else:
            return max(highs.max(), conf.high)
    # Demand case: conf buy
    else:
        if leg_in.close < leg_in.open:
            return min(core_dist, leg_in.low, conf.low)
        else:
            return min(lows.min(), conf.low)

hunt_demand = (leaning == "Demand-leaning")

candidates = []
for i in range(1, len(df10)-2):
    # 1) identify a basing candle
    if not is_basing(df10.iloc[i]):
        continue

    # 2) collect the full base (consecutive basing candles)
    idxs = [i]
    j = i-1
    while j >= 0 and is_basing(df10.iloc[j]):
        idxs.append(j)
        j -= 1
    idxs = sorted(idxs)
    base_end_time = df10.iloc[idxs[-1]].name

    # 3) compute core boundaries from the whole group
    base_time   = df10.iloc[idxs[0]].name
    if pd.to_datetime(base_time) < pd.to_datetime(base_start): continue
    o = df10.iloc[idxs]['open']
    c = df10.iloc[idxs]['close']
    h = df10.iloc[idxs]['high']
    l = df10.iloc[idxs]['low']

    sup_prox = float(min(o.min(), c.min()))
    sup_dist = float(h.max())
    dem_prox = float(max(o.max(), c.max()))
    dem_dist = float(l.min())

    # 4) get confirmation and leg-in
    conf   = df10.iloc[i+1]
    leg_in = df10.iloc[i-1]
        # 4b) make sure our “leg-out” isn’t itself a basing candle
    if is_basing(conf):
        continue

    # 5) apply distal override
    sup_dist = apply_override(sup_prox, sup_dist, conf, leg_in, h, l) \
               if conf.close < conf.open else sup_dist
    dem_dist = apply_override(dem_prox, dem_dist, conf, leg_in, h, l) \
               if conf.close > conf.open else dem_dist

    # 6) compute work-with and filter by zone_type + confirmation
    if not hunt_demand:
        R         = sup_dist - sup_prox
        prox_work = sup_prox - 0.15 * R
        dist_work = sup_dist + 0.20 * R

        if conf.close < conf.open:  # true supply signal
            candidates.append((
                "Supply", base_time, base_end_time,
                sup_prox, sup_dist,
                prox_work, dist_work
            ))

    else:
        R         = abs(dem_dist - dem_prox)
        prox_work = dem_prox + 0.15 * R
        dist_work = dem_dist - 0.20 * R

        if conf.close > conf.open:  # true demand signal
            candidates.append((
                "Demand", base_time, base_end_time,
                dem_prox, dem_dist,
                prox_work, dist_work
            ))


print(f"--- Segment 3: Candidate 10 m {('Demand' if hunt_demand else 'Supply')} Zones ---")
for typ, bt, bt_end, cp, cd, pw, dw in candidates:
    print(f" • {bt} to {bt_end} core=[{cp:.4f}, {cd:.4f}]  work=[{pw:.4f}, {dw:.4f}]")
print("\n--- Segment 3 complete ---")


# ───── Segment 4a: Untested Integrity (3 pts) ─────
# Assumes: df10 indexed by datetime; candidates list of tuples:
# ("Demand"|"Supply", base_start, base_end, core_prox, core_dist, work_prox, work_dist)

scored_candidates = []   # will hold dicts for later scoring/printing
bar_skip_after_base = 2  # number of bars to skip after base_end (1 => the next candle)

# ensure index is datetime
if not isinstance(df10.index, pd.DatetimeIndex):
    df10['time'] = pd.to_datetime(df10['time'], unit='s')
    df10.set_index('time', inplace=True)

for cand in candidates:
    # unpack tuple (keeps it minimal and explicit)
    typ, base_start, base_end, core_p, core_d, work_p, work_d = cand

    # ensure timestamps are pandas.Timestamp
    base_end_ts = pd.to_datetime(base_end)

    # find index position of base_end (use bfill so if exact label missing we pick next available)
    pos = df10.index.get_indexer([base_end_ts], method='bfill')[0]
    if pos == -1:
        # base_end not present and no later bar -> no post-base bars to check
        post_slice = df10.iloc[0:0]  # empty
    else:
        start_pos = pos + bar_skip_after_base
        if start_pos >= len(df10):
            post_slice = df10.iloc[0:0]  # empty
        else:
            post_slice = df10.iloc[start_pos:]

    # count touches and find first touch (if any)
    first_touch_time = None
    first_touch_row = None
    touches = 0
    if not post_slice.empty:
        if typ.lower() == 'supply':
            hit_mask = post_slice['high'] >= work_p
            touches = int(hit_mask.sum())
            if touches:
                first_idx = hit_mask.idxmax()  # returns first True index
                first_touch_time = first_idx
                first_touch_row = post_slice.loc[first_idx]
        else:  # 'demand'
            hit_mask = post_slice['low'] <= work_p
            touches = int(hit_mask.sum())
            if touches:
                first_idx = hit_mask.idxmax()
                first_touch_time = first_idx
                first_touch_row = post_slice.loc[first_idx]

    # map touches to pts: 0 -> 3.0, 1 -> 1.5, >=2 -> 0.0
    if touches == 0:
        pts_untested = 3.0
    elif touches == 1:
        pts_untested = 1.5
    else:
        pts_untested = 0.0

    scored_candidates.append({
        'type': typ,
        'base_start': pd.to_datetime(base_start),
        'base_end': base_end_ts,
        'core_prox': float(core_p),
        'core_dist': float(core_d),
        'work_prox': float(work_p),
        'work_dist': float(work_d),
        'touches': touches,
        'pts_untested': pts_untested,
        'first_touch_time': first_touch_time,
        'first_touch_row': first_touch_row  # DataFrame row (can be None)
    })

# quick terminal summary for verification
print("\n--- Segment 4a: Untested Integrity results ---")
for s in scored_candidates:
    ft = s['first_touch_time'].strftime("%Y-%m-%d %H:%M:%S") if s['first_touch_time'] is not None else "None"
    print(f" • {s['type']} @ {s['base_start']} → base_end {s['base_end']}  touches={s['touches']:d}  pts={s['pts_untested']}  first_touch={ft}")

# === Segment 4b: Base Count (2 pts) ===
for s in scored_candidates:
    # base_end_time already tells us where the base finished
    # so we can compute how many 10m bars were in the base
    base_candles = int((s['base_end'] - s['base_start']).seconds / (10*60)) + 1

    if base_candles < 4:
        pts_base = 2.0
    elif base_candles < 6:
        pts_base = 1.0
    else:
        pts_base = 0.0

    s['base_candles'] = base_candles
    s['pts_base'] = pts_base

print("\n--- Segment 4b: Base Count results ---")
for s in scored_candidates:
    print(f" • {s['type']} @ {s['base_start']} base_candles={s['base_candles']} pts_base={s['pts_base']}")

# === Segment 4c: Extra Leg-Outs ===
for cand in scored_candidates:
    end_pos  = df10.index.get_loc(cand['base_end'])
    conf_pos = end_pos + 1

    legout_count = 0
    legout_times = []
    first_touch_time = None
    pts_legout = 0.0  # default

    if conf_pos < len(df10):
        conf_row = df10.iloc[conf_pos]

        # conf is always a legout if it’s directional
        if not is_basing(conf_row):
            if (cand['type']=="Supply" and conf_row.close < conf_row.open) or \
               (cand['type']=="Demand" and conf_row.close > conf_row.open):
                
                legout_count = 1
                legout_times.append(df10.index[conf_pos])

                # look for contiguous extra leg-outs
                k = conf_pos + 1
                while k < len(df10):
                    row = df10.iloc[k]
                    if is_basing(row): 
                        break

                    if cand['type']=="Supply" and row.close < row.open:
                        touches = row.high >= cand['work_prox']
                    elif cand['type']=="Demand" and row.close > row.open:
                        touches = row.low <= cand['work_prox']
                    else:
                        break  # opposite direction → stop

                    if touches:
                        first_touch_time = df10.index[k]
                        break
                    else:
                        legout_count += 1
                        legout_times.append(df10.index[k])
                    k += 1

    # scoring logic
    if legout_count > 1 and not first_touch_time:
        pts_legout = 2  # strong extended leg-out
    elif legout_count == 1:
        pts_legout = 1   # only conf, no extras
    else:
        pts_legout = 0.0   # touched or invalid

    cand['legout_count'] = legout_count
    cand['legout_times'] = legout_times
    cand['first_touch_time_c'] = first_touch_time
    cand['pts_legout'] = pts_legout

# print Segment 4c results
print("\n--- Segment 4c: Extra Leg-Outs ---")
for s in scored_candidates:
    print(f" • {s['type']} @ {s['base_start']} "
          f"legouts={s['legout_count']} "
          f"pts_legout={s['pts_legout']}")
