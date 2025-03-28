import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt

# 1. Connect to MetaTrader 5
if not mt5.initialize():
    print("Failed to connect to MT5")
    mt5.shutdown()
    quit()
print("Connected to MT5 successfully!")

# 2. Define symbol, timeframe, and number of bars (150 bars)
symbol = "Volatility 25 (1s) Index"  # Change as needed
timeframe = mt5.TIMEFRAME_D1         # Daily timeframe (150 days)
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

# 5. Identify swing points using a sliding window of 1 but checking 4 candles to the left and 4 to the right.
# We'll iterate from index 4 to len(df)-4 to ensure we have 4 candles on each side.
swing_points = []
for i in range(4, len(df) - 4):
    current = df.iloc[i]
    # Explicitly check the 4 candles before and after:
    left_highs = [df.iloc[i - j]['high'] for j in range(1, 5)]
    right_highs = [df.iloc[i + j]['high'] for j in range(1, 5)]
    left_lows = [df.iloc[i - j]['low'] for j in range(1, 5)]
    right_lows = [df.iloc[i + j]['low'] for j in range(1, 5)]
    candle_range = current['high'] - current['low']
    
    # Swing High: current candle's high is greater than all 4 preceding and 4 following candle highs
    if current['high'] > max(left_highs) and current['high'] > max(right_highs):
        swing_points.append({
            'time': current['time'],
            'price': current['high'],
            'type': 'swing_high',
            'index': i,
            'candle_range': candle_range
        })
    # Swing Low: current candle's low is lower than all 4 preceding and 4 following candle lows
    if current['low'] < min(left_lows) and current['low'] < min(right_lows):
        swing_points.append({
            'time': current['time'],
            'price': current['low'],
            'type': 'swing_low',
            'index': i,
            'candle_range': candle_range
        })
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
            refined_type = 'Higher Swing High' if row['price'] > last_high else 'Lower Swing High'
        last_high = row['price']
        refined_swings.append({
            'time': row['time'],
            'price': row['price'],
            'refined_type': refined_type,
            'index': row['index'],
            'candle_range': row['candle_range']
        })
    elif row['type'] == 'swing_low':
        if last_low is None:
            refined_type = 'Initial Swing Low'
        else:
            refined_type = 'Higher Swing Low' if row['price'] > last_low else 'Lower Swing Low'
        last_low = row['price']
        refined_swings.append({
            'time': row['time'],
            'price': row['price'],
            'refined_type': refined_type,
            'index': row['index'],
            'candle_range': row['candle_range']
        })
refined_df = pd.DataFrame(refined_swings)

# 6b. Group consecutive refined swing points of the same type (within 10 candles).
# If the pip difference for their respective highs/lows is less than 50% of the maximum candle range among them,
# select only the best point (highest for swing highs, lowest for swing lows) and discard the rest.
def group_swing_points(ref_df, category):
    # Filter by category: 'High' or 'Low'
    df_cat = ref_df[ref_df['refined_type'].str.contains(category)].sort_values(by='index')
    if df_cat.empty:
        return df_cat
    groups = []
    current_group = [df_cat.iloc[0]]
    for i in range(1, len(df_cat)):
        current_point = df_cat.iloc[i]
        previous_point = current_group[-1]
        # Group if within 10 candles difference in index
        if current_point['index'] - previous_point['index'] <= 10:
            current_group.append(current_point)
        else:
            groups.append(pd.DataFrame(current_group))
            current_group = [current_point]
    if current_group:
        groups.append(pd.DataFrame(current_group))
    
    final_points = []
    for group in groups:
        if len(group) >= 2:
            price_diff = group['price'].max() - group['price'].min()  # For highs, difference in price; for lows, similarly
            max_range = group['candle_range'].max()
            if price_diff < 0.5 * max_range:
                if category == 'High':
                    best_point = group.loc[group['price'].idxmax()]  # highest for swing highs
                else:
                    best_point = group.loc[group['price'].idxmin()]  # lowest for swing lows
                final_points.append(best_point)
            else:
                for idx in group.index:
                    final_points.append(group.loc[idx])
        else:
            for idx in group.index:
                final_points.append(group.loc[idx])
    return pd.DataFrame(final_points)

final_highs = group_swing_points(refined_df, 'High')
final_lows = group_swing_points(refined_df, 'Low')
final_refined_df = pd.concat([final_highs, final_lows]).sort_values(by='index')

# Print only the final refined swing points
print("Final Refined Swing Points:")
print(final_refined_df.to_string(index=False))

# 7. Prepare data for mplfinance charting.
df.set_index('time', inplace=True)

# Create two additional series to mark swing highs and swing lows.
swing_high_series = pd.Series(data=np.nan, index=df.index)
swing_low_series = pd.Series(data=np.nan, index=df.index)

for idx, row in final_refined_df.iterrows():
    t = row['time']
    if "High" in row['refined_type']:
        swing_high_series[t] = row['price']
    elif "Low" in row['refined_type']:
        swing_low_series[t] = row['price']

# 8. Plot the OHLC (candlestick) chart with the final refined swing points overlaid.
apds = [
    mpf.make_addplot(swing_high_series, type='scatter', markersize=100, marker='^', color='red'),
    mpf.make_addplot(swing_low_series, type='scatter', markersize=100, marker='v', color='blue')
]

mpf.plot(df, type='candle', style='charles', title="150 Bars OHLC with Final Detected Swing Points",
         volume=False, addplot=apds)

# Shutdown MT5 connection

mt5.shutdown()
