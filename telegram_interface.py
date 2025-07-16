import requests
import logging

class TelegramBot:
    def send_log(self, text):
        # Stuur log/debug berichten naar Telegram, prefix met [LOG]
        self.send_message(f"[LOG] {text}")
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text):
        payload = {"chat_id": self.chat_id, "text": text}
        try:
            resp = requests.post(f"{self.url}/sendMessage", data=payload)
            if not resp.ok:
                logging.error(f"Telegram send_message failed: {resp.text}")
        except Exception as e:
            logging.error(f"Telegram send_message exception: {e}")

    def get_last_command(self, last_update_id):
        try:
            response = requests.get(f"{self.url}/getUpdates", timeout=10)
            data = response.json()
            updates = data.get("result", [])
            if updates:
                new = updates[-1]
                if 'message' in new and 'text' in new['message']:
                    if new['update_id'] != last_update_id:
                        return {'update_id': new['update_id'], 'text': new['message']['text']}
            return None
        except Exception as e:
            logging.error(f"Telegram get_last_command exception: {e}")
            return None
