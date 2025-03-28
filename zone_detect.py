import MetaTrader5 as mt5
import pandas as pd

# Connect to MT5
if not mt5.initialize():
    print("Failed to connect to MT5. Error:", mt5.last_error())
    quit()
else:
    print("Connected to MT5 successfully!")

# Define symbol and timeframe
symbol = "Volatility 150 (1s) Index"  # Change to your preferred index
timeframe = mt5.TIMEFRAME_D1          # Daily timeframe
bars = 350                            # Fetch the last 350 candles

# Get historical data
rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
if rates is None:
    print("No historical data retrieved. Error:", mt5.last_error())
    mt5.shutdown()
    quit()

# Convert to DataFrame
df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s')  # Convert timestamp to datetime

# -----------------------------
# Define helper functions
# -----------------------------
def is_basing_candle(row):
    """Return True if the candle is a basing candle."""
    body = abs(row['close'] - row['open'])
    total_range = row['high'] - row['low']
    return body < (0.5 * total_range)

def is_sell_candle(row):
    """Return True if the candle is a sell candle (bearish)."""
    return row['close'] < row['open']

def is_buy_candle(row):
    """Return True if the candle is a buy candle (bullish)."""
    return row['close'] > row['open']

# Mark basing candles in the DataFrame
df['basing'] = df.apply(is_basing_candle, axis=1)

# -----------------------------
# Identify the freshest untested Supply and Demand Zones
# -----------------------------
supply_zone = None  # To be stored as (lower_boundary, upper_boundary, timestamp)
demand_zone = None  # To be stored as (upper_boundary, lower_boundary, timestamp)

n = len(df)
# Iterate from the newest candle backward
for i in range(n - 2, -1, -1):
    # If candle i is basing, begin a group of consecutive basing candles.
    if df.iloc[i]['basing']:
        group_indices = [i]
        j = i - 1
        while j >= 0 and df.iloc[j]['basing']:
            group_indices.append(j)
            j -= 1
        
        # Get timestamp of the first basing candle in the group
        zone_time = df.iloc[group_indices[-1]]['time']

        # Compute group boundaries for the basing candles
        group_open = df.loc[group_indices, 'open']
        group_close = df.loc[group_indices, 'close']
        group_high = df.loc[group_indices, 'high']
        group_low = df.loc[group_indices, 'low']
        
        # For Supply Zone candidate:
        candidate_supply_low = min(group_open.min(), group_close.min())
        candidate_supply_high = group_high.max()
        # For Demand Zone candidate:
        candidate_demand_high = max(group_open.max(), group_close.max())
        candidate_demand_low = group_low.min()
        
        # Use the candle immediately after the group as the confirmation candle.
        if i + 1 < n:
            confirmation = df.iloc[i + 1]
            
            # Check for Supply Zone: Confirmation candle should be a sell candle and close below candidate_supply_low.
            if is_sell_candle(confirmation) and confirmation['close'] < candidate_supply_low:
                # Verify untested: no candle after the confirmation candle should have its close inside the candidate supply zone.
                untested = True
                for k in range(i + 2, n):
                    if candidate_supply_low <= df.iloc[k]['close'] <= candidate_supply_high:
                        untested = False
                        break
                if untested:
                    supply_zone = (candidate_supply_low, candidate_supply_high, zone_time)
                    break  # Stop searching once a valid supply zone is found
            
            # Check for Demand Zone: Confirmation candle should be a buy candle and close above candidate_demand_high.
            if is_buy_candle(confirmation) and confirmation['close'] > candidate_demand_high:
                untested = True
                for k in range(i + 2, n):
                    if candidate_demand_low <= df.iloc[k]['close'] <= candidate_demand_high:
                        untested = False
                        break
                if untested:
                    demand_zone = (candidate_demand_high, candidate_demand_low, zone_time)
                    break  # Stop searching once a valid demand zone is found

# -----------------------------
# Print the detected zones with their exact times
# -----------------------------
if supply_zone:
    print("\n🚀 **Untested Supply Zone**")
    print(f"  - Range: {supply_zone[0]:.2f} to {supply_zone[1]:.2f}")
    print(f"  - Identified at: {supply_zone[2]}")
else:
    print("\n⚠ No untested Supply Zone found.")

if demand_zone:
    print("\n🌊 **Untested Demand Zone**")
    print(f"  - Range: {demand_zone[0]:.2f} to {demand_zone[1]:.2f}")
    print(f"  - Identified at: {demand_zone[2]}")
else:
    print("\n⚠ No untested Demand Zone found.")

# Get current price from MT5
tick = mt5.symbol_info_tick(symbol)
if tick:
    current_price = tick.bid
    print("\n📌 **Current Price:** {:.2f}".format(current_price))
else:
    print("\n❌ Failed to get current price. Error:", mt5.last_error())

# Shutdown MT5 connection
mt5.shutdown()
