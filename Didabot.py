import threading
import time
from telegram_interface import TelegramBot
from exchange_connector import ExchangeConnector
from strategies import grid, ai_assist
from utils import logger
import config

drawdown_count = 0
last_buy_price = None
last_sell_price = None
last_trailing_high = None

bot_running = False
fifo_log = []
historical_prices = []

exchange = ExchangeConnector(config.API_KEY, config.API_SECRET)
tg = TelegramBot(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID)
trade_logger = logger.TradeLogger("trades_Didabot.csv")

def bot_loop():
    tg.send_message("🟢 Didabot klaar. Gebruik /startbot of /stopbot.")
    grid.init_grid()
    global bot_running, historical_prices
    global drawdown_count, last_buy_price, bot_running, last_sell_price, last_trailing_high
    while True:
        if bot_running:
            try:
                prijs = exchange.get_price(config.SYMBOL)
                historical_prices.append(prijs)
                if len(historical_prices) > 100:
                    historical_prices = historical_prices[-100:]

                # Drawdown exit & re-entry
                balans = exchange.exchange.fetch_balance()
                eth = balans['ETH']['free'] if 'ETH' in balans else 0
                if last_buy_price and eth > 0:
                    delta = prijs - last_buy_price
                    verkoopreden = None
                    if delta <= -2.0:
                        verkoopreden = "Drawdown ($2 onder koopprijs)"
                    elif delta >= 2.0:
                        verkoopreden = "Winst ($2 boven koopprijs)"
                    if verkoopreden:
                        eth = round(eth, 6)
                        if eth <= 0:
                            tg.send_message("❌ Geen ETH beschikbaar om te verkopen.")
                        else:
                            try:
                                order = exchange.exchange.create_market_sell_order(config.SYMBOL, eth)
                                tg.send_message(f"✅ Verkocht ({verkoopreden}): {eth:.6f} ETH @ ${prijs:.2f}")
                                last_sell_price = prijs
                                last_trailing_high = prijs  # Start trailing buy vanaf deze prijs
                            except Exception as e:
                                tg.send_message(f"❌ Fout bij verkoop: {e}")
                                return
                            balans = exchange.exchange.fetch_balance()
                            usdt = balans['USDT']['free'] if 'USDT' in balans else 0
                            eth_na = balans['ETH']['free'] if 'ETH' in balans else 0
                            pnl = (prijs - last_buy_price) * eth if last_buy_price else 0
                            tg.send_message(f"💰 Balans na verkoop:\nUSDT: {usdt}\nETH: {eth_na}\nPNL: ${pnl:.2f}")
                            drawdown_count += 1 if delta <= -2.0 else 0
                            last_buy_price = None
                            if drawdown_count >= 3:
                                bot_running = False
                                tg.send_message("⏸️ Didabot gepauzeerd na 3x drawdown exit!")
                            elif delta <= -2.0:
                                usd = config.POSITION_SIZE
                                amount = round(usd / prijs, 6)
                                try:
                                    order = exchange.exchange.create_market_buy_order(config.SYMBOL, amount)
                                    target_sell = prijs + 2.0
                                    tg.send_message(f"🔄 Opnieuw gekocht na drawdown: {amount:.6f} ETH @ ${prijs:.2f}\nNieuwe verkooptarget: ${target_sell:.2f}")
                                    last_buy_price = prijs
                                    last_trailing_high = None
                                except Exception as e:
                                    tg.send_message(f"❌ Fout bij heraankoop na drawdown: {e}")
                # Trailing buy na winst: wacht tot prijs 2% stijgt, koop bij 1.5% daling vanaf top
                if last_trailing_high and eth == 0:
                    if prijs > last_trailing_high:
                        last_trailing_high = prijs
                    # 2% stijging vanaf laatste verkoopprijs
                    stijging = (last_trailing_high - last_sell_price) / last_sell_price if last_sell_price else 0
                    daling = (last_trailing_high - prijs) / last_trailing_high if last_trailing_high else 0
                    if stijging >= 0.02 and daling >= 0.015:
                        usd = config.POSITION_SIZE
                        amount = round(usd / prijs, 6)
                        try:
                            order = exchange.exchange.create_market_buy_order(config.SYMBOL, amount)
                            target_sell = prijs + 2.0
                            tg.send_message(f"🟢 TRAILING BUY: {amount:.6f} ETH @ ${prijs:.2f}\nNieuwe verkooptarget: ${target_sell:.2f}")
                            last_buy_price = prijs
                            last_trailing_high = None
                            last_sell_price = None
                        except Exception as e:
                            tg.send_message(f"❌ Fout bij trailing buy: {e}")
                # Normale grid orders
                grid_buy_price = grid.place_grid_orders(prijs, exchange, tg, trade_logger)
                if grid_buy_price:
                    last_buy_price = grid_buy_price
                    target_sell = grid_buy_price + 2.0
                    tg.send_message(f"🟢 GRID KOOP: {config.POSITION_SIZE / grid_buy_price:.6f} ETH @ ${grid_buy_price:.2f}\nTarget verkoopprijs: ${target_sell:.2f}")
                advies = ai_assist.get_ai_advice(prijs, historical_prices)
                if advies:
                    tg.send_message(f"{advies}")

                # Trailing stoploss logica
                if last_buy_price and eth > 0:
                    delta = prijs - last_buy_price
                    # trailing_stoploss wordt geactiveerd bij snelle stijging
                    if delta >= 4.0:
                        # trailing stoploss: verkoop als prijs 1 dollar onder hoogste prijs na stijging
                        if not hasattr(config, 'TRAILING_STOP'): config.TRAILING_STOP = False
                        if not hasattr(config, 'TRAILING_HIGH'): config.TRAILING_HIGH = last_buy_price
                        if not config.TRAILING_STOP:
                            config.TRAILING_STOP = True
                            config.TRAILING_HIGH = prijs
                            tg.send_message(f"🚀 Trailing stoploss geactiveerd! Hoogste prijs: ${prijs:.2f}")
                        elif prijs > config.TRAILING_HIGH:
                            config.TRAILING_HIGH = prijs
                        elif prijs < config.TRAILING_HIGH - 1.0:
                            eth = round(eth, 6)
                            try:
                                order = exchange.exchange.create_market_sell_order(config.SYMBOL, eth)
                                tg.send_message(f"🔔 Trailing stoploss verkocht: {eth:.6f} ETH @ ${prijs:.2f}")
                            except Exception as e:
                                tg.send_message(f"❌ Fout bij trailing stoploss verkoop: {e}")
                                return
                            balans = exchange.exchange.fetch_balance()
                            usdt = balans['USDT']['free'] if 'USDT' in balans else 0
                            eth_na = balans['ETH']['free'] if 'ETH' in balans else 0
                            pnl = (prijs - last_buy_price) * eth if last_buy_price else 0
                            tg.send_message(f"💰 Balans na trailing stoploss:\nUSDT: {usdt}\nETH: {eth_na}\nPNL: ${pnl:.2f}")
                            last_buy_price = None
                            config.TRAILING_STOP = False
                            config.TRAILING_HIGH = None
            except Exception as e:
                tg.send_message(f"⚠️ Fout: {e}")
        time.sleep(0.2)

def check_commands():
    global bot_running
    last_update_id = None
    while True:
        update = tg.get_last_command(last_update_id)
        if update:
            cmd = update['text']
            parts = cmd.strip().split()
            if parts[0] == "/startbot":
                bot_running = True
                tg.send_message("✅ DidaBot gestart")
            elif parts[0] == "/stopbot":
                bot_running = False
                tg.send_message("🛑 DidaBot gestopt")
            elif parts[0] == "/setgrid" and len(parts) == 4:
                try:
                    start = float(parts[1])
                    end = float(parts[2])
                    levels = int(parts[3])
                    config.GRID_START = start
                    config.GRID_END = end
                    config.GRID_LEVELS = levels
                    grid.init_grid()
                    tg.send_message(f"📐 Grid ingesteld:\nStart: ${start}\nEind: ${end}\nLevels: {levels}")
                except:
                    tg.send_message("❌ Ongeldige invoer. Gebruik: /setgrid 2200 2700 6")
            elif parts[0] == "/balans":
                try:
                    balans = exchange.exchange.fetch_balance()
                    usdt = balans['USDT']['free'] if 'USDT' in balans else 0
                    eth = balans['ETH']['free'] if 'ETH' in balans else 0
                    tg.send_message(f"💰 Bybit Balans:\nUSDT: {usdt}\nETH: {eth}")
                except Exception as e:
                    tg.send_message(f"❌ Kan balans niet ophalen: {e}")
            elif parts[0].lower() == "/buy":
                try:
                    prijs = exchange.get_price(config.SYMBOL)
                    usd = config.POSITION_SIZE
                    amount = round(usd / prijs, 6)
                    order = exchange.exchange.create_market_buy_order(config.SYMBOL, amount)
                    target_sell = prijs + 2.0
                    tg.send_message(f"🟢 KOOP: {amount:.6f} ETH @ ${prijs:.2f} voor ${usd}\nTarget verkoopprijs: ${target_sell:.2f}")
                    balans = exchange.exchange.fetch_balance()
                    usdt = balans['USDT']['free'] if 'USDT' in balans else 0
                    eth = balans['ETH']['free'] if 'ETH' in balans else 0
                    tg.send_message(f"💰 Balans na koop:\nUSDT: {usdt}\nETH: {eth}")
                    # Reset drawdown counter en zet last_buy_price
                    global drawdown_count, last_buy_price
                    drawdown_count = 0
                    last_buy_price = prijs
                    # Reset trailing stop
                    if hasattr(config, 'TRAILING_STOP'): config.TRAILING_STOP = False
                    if hasattr(config, 'TRAILING_HIGH'): config.TRAILING_HIGH = None
                except Exception as e:
                    tg.send_message(f"❌ Fout bij koop: {e}")
            elif parts[0].lower() == "/sell":
                try:
                    balans = exchange.exchange.fetch_balance()
                    eth_free = balans['ETH']['free'] if 'ETH' in balans else 0
                    tg.send_message(f"[LOG] /sell commando: eth_free={eth_free}")
                    eth = round(eth_free, 6)
                    if eth <= 0:
                        tg.send_message(f"❌ Geen ETH beschikbaar om te verkopen.")
                    else:
                        prijs = exchange.get_price(config.SYMBOL)
                        tg.send_message(f"[LOG] /sell: Probeer te verkopen {eth} ETH @ prijs {prijs}")
                        try:
                            order = exchange.exchange.create_market_sell_order(config.SYMBOL, eth)
                            tg.send_message(f"🔴 VERKOOP: {eth:.6f} ETH @ ${prijs:.2f}")
                        except Exception as e:
                            tg.send_message(f"❌ Fout bij verkoop: {e}")
                            return
                        balans = exchange.exchange.fetch_balance()
                        usdt = balans['USDT']['free'] if 'USDT' in balans else 0
                        eth_na = balans['ETH']['free'] if 'ETH' in balans else 0
                        tg.send_message(f"💰 Balans na verkoop:\nUSDT: {usdt}\nETH: {eth_na}")
                        # Toon PNL indien mogelijk
                        if last_buy_price:
                            pnl = (prijs - last_buy_price) * eth
                            tg.send_message(f"📊 PNL: ${pnl:.2f}")
                            last_buy_price = None
                except Exception as e:
                    tg.send_message(f"❌ Fout bij verkoop: {e}")
            elif parts[0] == "/setsize" and len(parts) == 2:
                try:
                    new_size = float(parts[1])
                    config.POSITION_SIZE = new_size
                    tg.send_message(f"✅ Aankoopbedrag aangepast naar ${new_size}")
                except Exception as e:
                    tg.send_message(f"❌ Ongeldige invoer. Gebruik: /setsize 100")
            last_update_id = update['update_id']
        time.sleep(5)

threading.Thread(target=bot_loop).start()
threading.Thread(target=check_commands).start()
