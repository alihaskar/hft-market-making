import random
import datetime
import pathlib
from typing import Optional
from collections import OrderedDict

import pandas as pd

from simulator import *


class Strategy:
    LOGS_DIR = pathlib.Path('output/logs')

    def __init__(self, sim: ExchangeSimulator, max_position: float, order_lifetime: int) -> None:
        """
        Args:
            sim:
                Exchange simulator object.
            max_position:
                Maximum allowed absolute value of position size in quote asset
                at any given moment.
            order_lifetime:
                How much time (in nanoseconds) an unfilled order stays active
                before being canceled.
        """
        self.sim: 'ExchangeSimulator' = sim
        self.max_position: float = max_position
        self.order_lifetime: int = order_lifetime

        # Current client time (in nanoseconds).
        # Upon receiving a new update from the simulator, it is set to `receive_ts` of the update.
        self.current_time: Optional[int] = None
        # Local version of the order book
        self.orderbook: Optional[OrderbookSnapshotUpdate] = None
        # Client ID that will be assigned to the next created order
        self.client_order_id: int = 1
        # Client version of active orders dictionary. Key: client_order_id, Value: Order.
        self.active_orders: OrderedDict[int, Order] = OrderedDict()
        # TODO: implement pending orders
        # When client send place order request to the exchange simulator,
        # orders are moved here until the response confirms the placement
        self.pending_orders: OrderedDict[int, Order] = OrderedDict()
        # Current position size in quote asset
        self.position_size_quote: float = 0
        # Strategy log file
        time_str = datetime.datetime.now().strftime('%d.%m.%Y-%H:%M:%S')
        log_filename = f'strategy-{time_str}.log'
        self.log = open(Strategy.LOGS_DIR / log_filename, 'w')

    def run(self) -> None:
        print('Running the strategy...')
        while True:
            update = self.sim.tick()
            self.log.write(str(update) + '\n')

            if update is None:
                print('\nDone.')
                self.log.close()
                break

            if type(update) == MdUpdate:
                if update.orderbook is not None:
                    self.orderbook = update.orderbook
                    self.current_time = self.orderbook.receive_ts

                    order_best_bid = Order(
                        client_ts=self.current_time + 20, client_order_id=self.next_order_id(),
                        side='BID', size=0.001, price=self.orderbook.bids[0][0])
                    order_best_ask = Order(
                        client_ts=self.current_time + 20, client_order_id=self.next_order_id(),
                        side='ASK', size=0.001, price=self.orderbook.asks[0][0])

                    if self.position_size_quote < -self.max_position:
                        self.place_order(order_best_bid)
                    elif self.position_size_quote > self.max_position:
                        self.place_order(order_best_ask)
                    else:
                        side = random.choice(['BID', 'ASK'])
                        if side == 'BID':
                            self.place_order(order_best_bid)
                        else:
                            self.place_order(order_best_ask)

                elif update.trade is not None:
                    self.current_time = update.trade.receive_ts
                else:
                    self.current_time = update.receive_ts
                if self.orderbook is None:
                    continue

            elif type(update) == OwnTrade:
                own_trade = update
                self.current_time = own_trade.receive_ts
                if own_trade.client_order_id in self.active_orders:
                    self.active_orders.pop(own_trade.client_order_id)
                if own_trade.side == 'BID':
                    self.position_size_quote += own_trade.size * own_trade.price
                else:
                    self.position_size_quote -= own_trade.size * own_trade.price

            elif type(update) == ActionResponse:
                response = update
                self.current_time = response.action.receive_ts
                if type(response.action) == Order:
                    order = response.action
                    if response.code == ResponseCode.OK:
                        self.active_orders[order.client_order_id] = order
                if type(response.action) == OrderCancel:
                    pass

            # Cancel orders that are too old
            to_cancel = []
            for key, order in self.active_orders.items():
                if self.current_time - order.client_ts > self.order_lifetime:
                    to_cancel.append(key)
                else:
                    break
            for key in to_cancel:
                order = self.active_orders.pop(key)
                order_cancel = OrderCancel(self.current_time, client_order_id=order.client_order_id)
                self.sim.cancel_order(order_cancel)

    def place_order(self, order: Order):
        self.active_orders[order.client_order_id] = order
        self.sim.place_order(order)

    def next_order_id(self):
        """Returns the next client order ID"""
        cur_id = self.client_order_id
        self.client_order_id += 1

        return cur_id


if __name__ == "__main__":
    lobs_path = 'data/1/btcusdt:Binance:LinearPerpetual/lobs.csv'
    trades_path = 'data/1/btcusdt:Binance:LinearPerpetual/trades.csv'

    sim = ExchangeSimulator(lobs_path, trades_path,
                            exec_latency=10_000_000, updates_latency=10_000_000,
                            account_size=20000, fee=0.001,
                            min_ts=None, max_ts=pd.Timestamp('2022-06-23 00:20:00'))
    strategy = Strategy(sim, max_position=10000, order_lifetime=100_000_000)
    strategy.run()
    value_history = sim.get_value_history()

    import plotly.express as px
    fig = px.line(value_history, x='exchange_ts', y='account_value')
    fig.update_layout(xaxis_title='Exchange time', yaxis_title='Account value',
                      title='Account value history')
    fig.show()

    time_str = datetime.datetime.now().strftime('%d.%m.%Y-%H:%M:%S')
    plot_filename = f'value-history-{time_str}.png'
    fig.write_image(f'output/plots/{plot_filename}')
