import MetaTrader5 as mt5
import pandas as pd
import numpy as np

# 1. Connect to MetaTrader 5
if not mt5.initialize():
    print("Failed to connect to MT5")
    mt5.shutdown()
    quit()
print("Connected to MT5 successfully!")

# 2. Define symbol, timeframe, and number of bars (150 bars)
symbol = "Volatility 25 (1s) Index"   # Change as needed
timeframe = mt5.TIMEFRAME_D1            # Daily timeframe (150 days)
bars = 150

# 3. Get historical data (the most recent 150 bars)
rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
if rates is None:
    print("Failed to get historical data")
    mt5.shutdown()
    quit()

# 4. Convert rates to a DataFrame and convert timestamps
df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s')

# 5. Identify swing points using a sliding window method
#    We use a window of 1 (comparing to the immediate previous and next bar)
swing_points = []
window = 1
for i in range(window, len(df) - window):
    current = df.iloc[i]
    prev = df.iloc[i - window]
    nxt = df.iloc[i + window]
    # If current close is higher than both neighbors, mark as swing high
    if current['close'] > prev['close'] and current['close'] > nxt['close']:
        swing_points.append({'time': current['time'], 'price': current['close'], 'type': 'swing_high'})
    # If current close is lower than both neighbors, mark as swing low
    elif current['close'] < prev['close'] and current['close'] < nxt['close']:
        swing_points.append({'time': current['time'], 'price': current['close'], 'type': 'swing_low'})
swing_df = pd.DataFrame(swing_points)

# 6. Refine swing point labels (comparing each swing to the previous swing of the same type)
refined_swings = []
last_high = None
last_low = None
for idx, row in swing_df.iterrows():
    if row['type'] == 'swing_high':
        if last_high is None:
            refined_type = 'Initial Swing High'
        else:
            if row['price'] > last_high:
                refined_type = 'Higher Swing High'
            else:
                refined_type = 'Lower Swing High'
        last_high = row['price']
        refined_swings.append({'time': row['time'], 'price': row['price'], 'refined_type': refined_type})
    elif row['type'] == 'swing_low':
        if last_low is None:
            refined_type = 'Initial Swing Low'
        else:
            if row['price'] > last_low:
                refined_type = 'Higher Swing Low'
            else:
                refined_type = 'Lower Swing Low'
        last_low = row['price']
        refined_swings.append({'time': row['time'], 'price': row['price'], 'refined_type': refined_type})
refined_df = pd.DataFrame(refined_swings)

# 7. Determine the trend using consecutive "sets" of swing points.
#    A "set" in an uptrend: either (Higher Swing Low -> Higher Swing High) or (Higher Swing High -> Higher Swing Low)
#    A "set" in a downtrend: either (Lower Swing Low -> Lower Swing High) or (Lower Swing High -> Lower Swing Low)
set_count = 0
previous_set = None  # will be either 'up' or 'down'
trend = "No Clear Trend"

# Process the refined swing points in chronological order
for i in range(len(refined_df) - 1):
    current = refined_df.iloc[i]
    next_point = refined_df.iloc[i + 1]
    current_set = None
    
    # For an uptrend set, both points must be from the "higher" category.
    if current['refined_type'] in ['Higher Swing Low', 'Higher Swing High'] and \
       next_point['refined_type'] in ['Higher Swing Low', 'Higher Swing High']:
        current_set = 'up'
    # For a downtrend set, both points must be from the "lower" category.
    elif current['refined_type'] in ['Lower Swing Low', 'Lower Swing High'] and \
         next_point['refined_type'] in ['Lower Swing Low', 'Lower Swing High']:
        current_set = 'down'
    else:
        current_set = 'undefined'
    
    if current_set != 'undefined':
        if previous_set is None:
            previous_set = current_set
            set_count = 1
        elif current_set == previous_set:
            set_count += 1
        else:
            previous_set = current_set
            set_count = 1

    # If two consecutive sets of the same type are detected, confirm the trend.
    if set_count >= 2:
        trend = 'Uptrend' if previous_set == 'up' else 'Downtrend'
        break

print("Detected Trend based on the last 150 bars:", trend)
# Shutdown the MT5 connection
mt5.shutdown()

