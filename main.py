import os
import time
import sys
from datetime import datetime, timedelta, time as dt_time
from dhanhq import DhanContext, HistoricalData, Order, Portfolio
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

load_dotenv()

class Share():
    def __init__(self, name: str, security_id: str, exchange_segment: str = "NSE", quantity: int = 1, order_type: str = "MARKET", product_type: str = "CNC"):
        self.name = name
        self.security_id = security_id
        self.exchange_segment = exchange_segment
        self.quantity = quantity
        self.order_type = order_type
        self.product_type = product_type

client_id = os.getenv("client_id")
access_token = os.getenv("access_token")

dhan_context = DhanContext(client_id=client_id, access_token=access_token)
historical_client = HistoricalData(dhan_context)
order_client = Order(dhan_context)
portfolio = Portfolio(dhan_context=dhan_context)

Shares = [
    Share(name="RELIANCE", security_id="2885"),
    Share(name="HDFC_BANK", security_id="1333"),
    Share(name="BHARTI_AIRTEL", security_id="10604"),
    Share(name="ICICI_BANK", security_id="4963"),
    Share(name="SBI", security_id="3045"),
    Share(name="TCS", security_id="11536"),
    Share(name="BAJAJ_FINANCE", security_id="317"),
    Share(name="LARSEN_&_TOUBRO", security_id="11483"),
    Share(name="LIC", security_id="9480"),
    Share(name="MARUTI", security_id="10999"),
    Share(name="NESTLE",security_id="17963")
]

print("Starting EMA Crossover Bot...")

while True:
    now_time = datetime.now().time()
    end_time = dt_time(14, 45, 0)

    # 1. End of Day Square-Off
    if now_time >= end_time:
        print("After market hours. Squaring off long positions...")
        positions = portfolio.get_positions()
        
        if positions and isinstance(positions, list): 
            for position in positions:
                net_qty = position.get("netQty", 0)
                
                if net_qty > 0: 
                    response = order_client.place_order(
                        security_id=position["securityId"], 
                        exchange_segment="NSE", 
                        transaction_type="SELL", 
                        quantity=net_qty, 
                        order_type="MARKET", 
                        product_type=position["productType"], 
                        price=0
                    )
                    print(f"Tried final close (SELL) for {position.get('tradingSymbol', position['securityId'])}\nResponse: {response}")

        print("Square-off complete. Exiting...")
        sys.exit()
        
    try:
        now = datetime.now()
        # Strict Date Formatting for API
        to_date_str = now.strftime("%Y-%m-%d %H:%M:%S")
        from_date_str = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

        # 2. Fetch current positions before looping through stocks to prevent naked shorting
        current_positions = {}
        positions_response = portfolio.get_positions()
        
        # Parse the response safely
        if isinstance(positions_response, list):
            pos_list = positions_response
        elif isinstance(positions_response, dict) and 'data' in positions_response:
            pos_list = positions_response['data']
        else:
            pos_list = []
            
        # Build a lookup dictionary: {"securityId": netQty}
        for pos in pos_list:
            net_qty = pos.get("netQty", 0) 
            current_positions[str(pos.get("securityId"))] = net_qty

        # 3. Evaluate Strategy
        for share in Shares:
            response = historical_client.intraday_minute_data(
                security_id=share.security_id,
                exchange_segment=share.exchange_segment,
                instrument_type="EQUITY",
                from_date=from_date_str,
                to_date=to_date_str,
                interval=5
            )
            
            if response and isinstance(response, dict) and 'close' in response:
                d = pd.DataFrame(response)
                
                if d.empty:
                    continue

                d["EMA_5"] = d.ta.ema(close="close", length=5)
                d["EMA_10"] = d.ta.ema(close="close", length=10)
                d.dropna(inplace=True)

                if len(d) >= 2:
                    ema5_prev, ema5_curr = d["EMA_5"].iloc[-2], d["EMA_5"].iloc[-1]
                    ema10_prev, ema10_curr = d["EMA_10"].iloc[-2], d["EMA_10"].iloc[-1]

                    # CROSS UP -> BULLISH (BUY)
                    if (ema5_prev < ema10_prev) and (ema5_curr > ema10_curr):
                        print(f"[{share.name}] Bullish Crossover Detected! Going Long...")
                        status = order_client.place_order(
                            security_id=share.security_id,
                            exchange_segment=share.exchange_segment, 
                            transaction_type="BUY", 
                            quantity=share.quantity, 
                            order_type=share.order_type, 
                            product_type=share.product_type,
                            price=0
                        )
                        print(f"Order Status: {status}\n")

                    # CROSS DOWN -> BEARISH (SELL) - With Position Check
                    elif (ema5_prev > ema10_prev) and (ema5_curr < ema10_curr):
                        # Look up how many shares we currently hold of this specific stock
                        held_qty = current_positions.get(share.security_id, 0)
                        
                        if held_qty > 0:
                            print(f"[{share.name}] Bearish Crossover Detected! Exiting Long...")
                            # Sell the minimum of what we hold vs the share quantity config
                            sell_qty = min(share.quantity, held_qty)
                            
                            status = order_client.place_order(
                                security_id=share.security_id, 
                                exchange_segment=share.exchange_segment, 
                                transaction_type="SELL", 
                                quantity=sell_qty, 
                                order_type=share.order_type, 
                                product_type=share.product_type, 
                                price=0
                            )
                            print(f"Order Status: {status}\n")
                        else:
                            print(f"[{share.name}] Bearish Crossover, but 0 shares held. Skipping sell to avoid short.")
            else:
                print(f"Failed to fetch valid data for {share.name}")

    except Exception as e:
        print(f"An error occurred during execution: {e}")

    time.sleep(300)