# === exchange_connector.py ===
import ccxt
import logging

class ExchangeConnector:
    def __init__(self, api_key, secret):
        try:
            self.exchange = ccxt.bybit({
                'apiKey': api_key,
                'secret': secret,
                'enableRateLimit': True,
                'options': {'recvWindow': 10000}
            })
        except Exception as e:
            logging.error(f"Fout bij verbinden met Bybit: {e}")
            self.exchange = None

    def get_price(self, symbol):
        try:
            if self.exchange:
                ticker = self.exchange.fetch_ticker(symbol)
                price = ticker.get('last')
                if price is None:
                    logging.error(f"Geen geldige prijs ontvangen voor {symbol}: {ticker}")
                return price
            else:
                logging.error("Geen exchange verbinding beschikbaar.")
                return None
        except Exception as e:
            logging.error(f"Fout bij ophalen prijs: {e}")
            return None
