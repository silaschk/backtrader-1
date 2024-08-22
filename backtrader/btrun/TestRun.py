import datetime
from matplotlib import pyplot as plt
import pandas as pd
import backtrader as bt
from ib_insync import IB, Stock, util
from ibapi.wrapper import EWrapper
from ibapi.client import EClient
from ibapi.contract import Contract
import threading
import time

# Subclass EWrapper to handle historical data
class TestWrapper(EWrapper):
    def __init__(self):
        self.data_received = []
        super().__init__()

    def historicalData(self, reqId: int, bar):
        print("HistoricalData. ReqId:", reqId, "BarData.", bar)
        self.data_received.append(bar)

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        print("HistoricalDataEnd. ReqId:", reqId, "from", start, "to", end)

    def historicalDataUpdate(self, reqId: int, bar):
        print("HistoricalDataUpdate. ReqId:", reqId, "BarData.", bar)
        self.data_received.append(bar)

# Create a new class for the IB client
class TestClient(EClient):
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)

# Define the main class that combines the wrapper and client
class IBApiApp(TestWrapper, TestClient):
    def __init__(self):
        TestWrapper.__init__(self)
        TestClient.__init__(self, wrapper=self)

    def start(self):
        thread = threading.Thread(target=self.run)
        thread.start()
        setattr(self, "_thread", thread)
        time.sleep(1)  # Give the thread time to start

    def stop(self):
        self.done = True
        self.disconnect()

# Define the strategy
class OpeningRangeStrategy(bt.Strategy):
    params = (
        ('target', 2),
        ('risk', 1),
        ('stop', 1),
        ('check_time', (9, 30)),
        ('entry_time', 60),
        ('scale_out', 0.5),
    )

    def __init__(self):
        self.opening_range_high = None
        self.opening_range_low = None
        self.order = None
        self.opened = False
        self.check_time = self.params.check_time
        self.entry_time = self.params.entry_time
        self.stop_price = None
        self.take_profit = None 

        # Adding indicators
        self.stochastic = bt.indicators.Stochastic(self.data)
        self.ema72 = bt.indicators.EMA(self.data.close, period=72)
        self.ema89 = bt.indicators.EMA(self.data.close, period=89)

    def next(self):
        current_time = self.data.datetime.time()

        # Define the opening range
        if not self.opening_range_high and current_time >= datetime.time(*self.check_time):
            self.opening_range_high = self.data.high[0]
            self.opening_range_low = self.data.low[0]

        # Check for breakout above the opening range within the specified time
        if self.opening_range_high and not self.opened and datetime.time(9, 30) <= current_time <= datetime.time(11, 0):
            range_size = self.opening_range_high - self.opening_range_low
            if self.data.close[0] >= self.opening_range_high + range_size:
                self.opened = True

        # Check for retracement and hammer candle within the specified time
        if self.opened and self.data.close[0] < self.opening_range_high and datetime.time(9, 30) <= current_time <= datetime.time(11, 0):
            if self.data.close[0] >= self.opening_range_low:
                if self.is_hammer():
                    self.buy()
                    self.stop_price = self.data.close[0] - (self.params.stop * range_size)
                    self.take_profit = self.data.close[0] + (self.params.target * range_size)
                    self.opened = False

        # Manage position after 60 minutes
        if len(self) >= self.entry_time:
            if self.position.size:
                self.close()

    def is_hammer(self):
        # Check for hammer candle pattern
        body_size = abs(self.data.open[0] - self.data.close[0])
        tail_size = self.data.low[0] - min(self.data.open[0], self.data.close[0])
        return tail_size >= 0.5 * body_size

    def stop(self):
        if self.position.size:
            self.close()

# Instantiate Cerebro and add the strategy
cerebro = bt.Cerebro()
cerebro.addstrategy(OpeningRangeStrategy)

# Set up the IB client
ib_app = IBApiApp()
ib_app.connect('127.0.0.1', 7497, clientId=1)  # Ensure that TWS or IB Gateway is running
ib_app.start()

# Fetch data from Interactive Brokers using the API
contract = Contract()
contract.symbol = 'SPY'
contract.secType = 'STK'
contract.exchange = 'SMART'
contract.currency = 'USD'

# Add print statements to help debug the issue
print("Attempting to request historical data...")

# Request historical data
ib_app.reqHistoricalData(
    reqId=1,
    contract=contract,
    endDateTime='',
    durationStr='1 D',
    barSizeSetting='1 min',
    whatToShow='TRADES',
    useRTH=True,
    formatDate=1,
    keepUpToDate=False,
    chartOptions=[]
)

# Wait for the data to be received
time.sleep(10)  # Increase if needed based on network latency

# Check if data was received
if not ib_app.data_received:
    raise ValueError("No data returned from Interactive Brokers.")
else:
    print("Data received successfully.")

# Convert BarData objects to a list of dictionaries
data_dicts = []
for bar in ib_app.data_received:
    data_dicts.append({
        'date': bar.date,
        'open': bar.open,
        'high': bar.high,
        'low': bar.low,
        'close': bar.close,
        'volume': bar.volume
    })

# Convert the list of dictionaries to a DataFrame
df = pd.DataFrame(data_dicts)

if df is not None and not df.empty:
    df.rename(columns={
        'date': 'datetime',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume'
    }, inplace=True)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)

    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
else:
    raise ValueError("DataFrame conversion failed or DataFrame is empty.")

# Set the starting cash for the strategy
cerebro.broker.setcash(100000.0)

# Set the commission for trading (IB charges commissions per trade)
cerebro.broker.setcommission(commission=0.001)

# Run the strategy
cerebro.run()

# Plot the results with date and time on the x-axis
fig = cerebro.plot(style='candlestick', volume=False, iplot=False)[0][0]
fig.autofmt_xdate()  # Automatically format x-axis for date and time
plt.show()

# Stop the IB client and disconnect
ib_app.stop()
