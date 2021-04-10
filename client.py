import functools
import logging
import json
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    Filters,
)

from datetime import datetime
from datetime import timedelta
from urllib.parse import urlencode
from urllib.request import urlopen
from multiprocessing import Process

import sql_observer
from generate_plot import generate_plot

from typing import (
    Callable,
    TypeVar,
)

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

rootLogger.setLevel(logging.INFO)

BASE_URL = 'https://openexchangerates.org/api'
ENDPOINT_LATEST = BASE_URL + '/latest.json'
ENDPOINT_HISTORICAL = BASE_URL + '/historical/%s.json'


HELP_TEXT = """
Help:
/list or /lst - returns list of all available rates

/exchange $10 to CAD or /exchange 10 USD to CAD -  converts to the second currency
with two decimal precision and returns

/history USD/CAD for 7 days - returns an image graph chart which shows the exchange
rate graph/chart of the selected currency for the last days

Example:
- /list
- /exchange $10 to EUR
- /exchange 10$ to EUR
- /exchange 10 USD to EUR
- /exchange 10 EUR to $
- /history USD/EUR for 5 days
- /history USD/CAD for 7 days
- /history USD/SZL for 20 days
"""

DETAILS_TEXT = "Details"
CLICK_BUTTON_TEXT = 'Click button to get graph'
WAIT_PROCESS_TEXT = 'Wait finishing of process'
EXCHANGE_FORMAT_TEXT = "Use this format: /exchange [$10] to [CAD] or /exchange [10] [USD] to [CAD]"
HISTORY_FORMAT_TEXT = "Use this format: /history [USD]/[CAD] for [7] days"

DAYS_ERROR = "Entered less then 2 or more then 30 days"
EXCHANGE_ERROR = "No exchange rate data is available for the selected currency."
CORRECT_VALUE_ERROR = "You should enter correct value after '/exchange'"
LESS_ZERO_ERROR = "You should enter value that >0"
NO_CURRENCY_ERROR = "There is no entered currency"
USD_BASE_ERROR = "You should use base currency '$' or 'USD' to exchange successful"
USD_ALONE_ERROR = "USD should be used with another currency"
USD_FIRST_ERROR = "This bot supports only USD base currency. (USD should be first)"


RT = TypeVar('RT')


def log(func: Callable[..., RT],) -> Callable[..., RT]:
    logger = logging.getLogger(func.__module__)

    @functools.wraps(func)
    def decorator(*args: object, **kwargs: object) -> RT:
        logger.debug('Entering: %s', func.__name__)
        result = func(*args, **kwargs)
        logger.debug(result)
        logger.debug('Exiting: %s', func.__name__)
        return result

    return decorator


@log
def exchange(balance, rate, converse=False):
    """
        Exchanges:
         currency1 to currency2 if converse=True
         currency2 to currency1 if converse=False
    """
    if rate != 0:
        return round(balance * (rate if converse else 1/rate), 3)
    else:
        return 0


@log
def get_rate(time="", name="", base="USD", timeout=10):
    """
        Gets rates from web service
    """
    # Heroku using
    api_key = os.environ['api_key']

    # PC using
    # with open("settings.json", "r") as r:
    #     api_key = json.load(r)["api_key"]

    str_time = datetime.now().strftime("%Y-%m-%d")

    if time == "" or str_time == time:
        url = (f"{ENDPOINT_LATEST}?"
               f"{urlencode({'app_id': api_key, 'base': base})}")
    else:
        url = (f"{ENDPOINT_HISTORICAL % time}?"
               f"{urlencode({'app_id': api_key, 'base': base, 'symbols': name})}")

    response = urlopen(url, timeout=timeout).read()
    return json.loads(response)['rates']


@log
def show_details(update, context):
    """
        Sends photo or returns popup notification
    """
    query = update.callback_query

    if query.data == "0":
        context.bot.answer_callback_query(update.callback_query.id,
                                          text=EXCHANGE_ERROR,
                                          show_alert=True)
    elif query.data:
        with open(query.data + ".png", "rb") as f:
            context.bot.send_photo(chat_id=update.effective_chat.id, photo=f)
            logging.info(f"Sends graph:'{query.data}.png' to {update.effective_chat.id}")

    query.delete_message()
    query.answer()


@log
def get_latest():
    """
        Returns latest rates from:
         Last request was >10min: web service
         Last request was <10min: local database
    """

    sql = sql_observer.SQL("db.db")
    timestamp = int((datetime.now() - timedelta(minutes=10)).timestamp())
    rates = sql.get_last_rates(timestamp)
    if rates:
        logging.info(f"Getting rates from local database")
        rates = json.loads(rates.replace("\'", "\""))
    else:
        logging.info(f"Getting rates from web service")
        rates = get_rate()
        sql.save_rates(timestamp=int(datetime.now().timestamp()), base="USD", rates=rates)

    return rates


@log
def get_value(value, update, context):
    """
        Returns value: float to exchange
    """
    try:
        if "$" in value:
            value = value.replace("$", "")
        value = float(value)
    except BaseException:
        return send_error(update, context, CORRECT_VALUE_ERROR)
    return value


@log
def get_currency(split_message):
    """
        Sends currency: dict
        Example:
            {"rate": 1, "converse": True, "currency": " "}
            {"rate": 0.89, "converse": True, "currency": "EUR"}
    """
    currency = {"rate": 1, "converse": True, "currency": " "}
    rates = get_latest()
    if len(split_message) == 4:
        if "$" in split_message[1] and split_message[3].upper() in rates:
            currency["currency"] = split_message[3].upper()

    elif len(split_message) == 5:
        if ("$" in split_message[2] or "USD" in split_message[2].upper()) and split_message[4].upper() in rates:
            currency["currency"] = split_message[4].upper()
        elif split_message[2].upper() in rates:
            currency["currency"] = split_message[2].upper()
            currency["converse"] = False

    if currency["currency"] != " ":
        currency["rate"] = rates[currency["currency"]]
    return currency


@log
def send_error(update, context, error="Error"):
    """
        Sends error text and returns False
    """
    context.bot.send_message(chat_id=update.effective_chat.id, text=error)
    return False


@log
def help_command(update, context):
    """
        Sends help text
    """
    if update.edited_message:
        return

    logging.info(f"{update.message.from_user.id}:help_command()")
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text=HELP_TEXT)


@log
def list_command(update, context):
    """
        Sends latest rates
    """
    if update.edited_message:
        return

    logging.info(f"{update.message.from_user.id}:list_command()")

    rates = get_latest()
    message = "\n".join(map(lambda x: f"{x}: {round(rates[x], 2)}", rates))
    context.bot.send_message(chat_id=update.effective_chat.id, text=message)


def send_converted_value(message, update, context):
    """
        Returns converted r"USD/EUR" to ("USD", "EUR") or sends error text & returns False
    """
    split_message = message.split()

    value = get_value(split_message[1], update, context)
    if not value:
        return
    elif value < 0:
        return send_error(update, context, LESS_ZERO_ERROR)

    if "$" in message or "USD" in message.upper():
        currency = get_currency(split_message)
        if currency["currency"] != " ":
            converted_value = exchange(value, currency["rate"], currency["converse"])
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=f"{converted_value} {currency['currency'] if currency['converse'] else '$'}")
        else:
            send_error(update, context, NO_CURRENCY_ERROR)
    else:
        send_error(update, context, USD_BASE_ERROR)


@log
def exchange_command(update, context):
    """
        Returns converted r"USD/EUR" to ("USD", "EUR") or sends error text & returns False
    """
    if update.edited_message:
        return

    logging.info(f"{update.message.from_user.id}:exchange_command()")

    message = update.message.text

    if "\n" in message:
        return send_error(update, context, "You should enter data without enters")

    if 4 <= len(update.message.text.split()) <= 5:
        send_converted_value(message, update, context)
    else:
        send_error(update, context, EXCHANGE_FORMAT_TEXT)


@log
def get_split_name(name, update, context):
    """
        Returns converted r"USD/EUR" to ["USD", "EUR"] or sends error text & returns False
    """
    split_name = name.split("/")
    if len(split_name) != 2 or not split_name[0] or not split_name[1]:
        return send_error(update, context, HISTORY_FORMAT_TEXT)

    if split_name[0].upper() != "USD":
        return send_error(update, context, USD_FIRST_ERROR)

    elif split_name[0].upper() == split_name[1].upper():
        return send_error(update, context, USD_ALONE_ERROR)

    split_name = [i.upper() for i in split_name]
    return split_name


@log
def get_days(split_message, update, context):
    """
        Returns days or sends error text & returns False
    """
    try:
        days = int(split_message[3])
        if days > 30 or days < 2:
            raise ValueError
    except ValueError:
        return send_error(update, context, DAYS_ERROR)
    except BaseException:
        return send_error(update, context, HISTORY_FORMAT_TEXT)
    return days


@log
def create_keyboard(callback_data="0"):
    return [
                [
                    InlineKeyboardButton(DETAILS_TEXT, callback_data=callback_data),
                ],
            ]


@log
def create_markup(split_name, days):
    """
        Returns markup with callback_data="USD-currency" or "0"
    """
    time = datetime.now()
    array = []

    name = f"{split_name[0]}-{split_name[1]}"
    currency = split_name[1]
    for i in range(days):
        try:
            str_time = time.strftime("%Y-%m-%d")
            date_rate = get_rate(time=str_time, name=currency)
            array.append((str_time, date_rate[currency]))
        except BaseException:
            keyboard = create_keyboard(callback_data="0")
            break
        else:
            time -= timedelta(days=1)
    else:
        array.reverse()

        keyboard = create_keyboard(callback_data=name)

        p = Process(target=generate_plot, args=(array, name,))
        p.start()
        p.join()
    return InlineKeyboardMarkup(keyboard)


@log
def send_graph(split_message, update, context):
    """
        Edits markup to wait message
    """
    name = split_message[1]  # r"USD/CAD"
    if "/" not in name:
        return send_error(update, context, HISTORY_FORMAT_TEXT)

    split_name = get_split_name(name, update, context)
    if not split_name:
        return

    days = get_days(split_message, update, context)
    if not days:
        return

    message = update.message.reply_text(WAIT_PROCESS_TEXT)
    reply_markup = create_markup(split_name, days)
    message.edit_text(CLICK_BUTTON_TEXT, reply_markup=reply_markup)


@log
def history_command(update, context):
    """
        Shows graph about currency rate
    """
    if update.edited_message:
        return

    logging.info(f"{update.message.from_user.id}:history_command()")

    split_message = update.message.text.split()

    if len(split_message) == 5:
        send_graph(split_message, update, context)
    else:
        return send_error(update, context, HISTORY_FORMAT_TEXT)


def main():
    logging.info("Bot is running")
    # Heroku using
    token = os.environ['token']

    # PC using
    # with open("settings.json", "r") as r:
    #     token = json.load(r)["token"]

    updater = Updater(token, use_context=True)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', help_command))
    dispatcher.add_handler(CommandHandler('help', help_command))
    # /start or /help

    dispatcher.add_handler(CommandHandler('list', list_command))
    dispatcher.add_handler(CommandHandler('lst', list_command))
    # /list or /lst

    dispatcher.add_handler(CommandHandler('exchange', exchange_command))
    # /exchange

    dispatcher.add_handler(CommandHandler('history', history_command))
    dispatcher.add_handler(CallbackQueryHandler(show_details))
    # /history

    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), help_command))
    # /help

    logging.info("Bot is starting")
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
