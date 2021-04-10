import functools
import logging
import json

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

import os

import sql_observer
from generate_plot import generate_plot

from typing import (
    TYPE_CHECKING,
    Callable,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
    no_type_check,
    Dict,
    cast,
    Sequence,
)

BASE_URL = 'https://openexchangerates.org/api'
ENDPOINT_LATEST = BASE_URL + '/latest.json'
ENDPOINT_HISTORICAL = BASE_URL + '/historical/%s.json'


RT = TypeVar('RT')


def log(
    func: Callable[..., RT], *args: object, **kwargs: object  # pylint: disable=W0613
) -> Callable[..., RT]:
    logger = logging.getLogger(func.__module__)

    @functools.wraps(func)
    def decorator(*args: object, **kwargs: object) -> RT:  # pylint: disable=W0613
        logger.debug('Entering: %s', func.__name__)
        result = func(*args, **kwargs)
        logger.debug(result)
        logger.debug('Exiting: %s', func.__name__)
        return result

    return decorator


@log
def exchange(balance, rate, converse=False):
    if rate != 0:
        return round(balance * (rate if converse else 1/rate), 3)
    else:
        return 0


def get_rate(time="", name="", base="USD", timeout=10):
    api_key = os.environ['api_key']

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


def show_details(update, context):
    query = update.callback_query

    if query.data == "0":
        context.bot.answer_callback_query(update.callback_query.id,
                                          text="No exchange rate data is available for the selected currency.",
                                          show_alert=True)
    elif query.data:
        with open(query.data + ".png", "rb") as f:
            context.bot.send_photo(chat_id=update.effective_chat.id, photo=f)
    query.delete_message()
    query.answer()


def get_latest():
    sql = sql_observer.SQL("db.db")
    timestamp = int((datetime.now() - timedelta(minutes=10)).timestamp())
    rates = sql.get_last_rates(timestamp)
    if rates:
        rates = json.loads(rates.replace("\'", "\""))
    else:
        rates = get_rate()
        sql.save_rates(timestamp=int(datetime.now().timestamp()), base="USD", rates=rates)

    return rates


def get_value(value, update, context):
    try:
        if "$" in value:
            value = value.replace("$", "")
        value = float(value)
    except BaseException:
        return send_error(update, context, "You should enter correct value after '/exchange'")
    return value


def get_currency(split_message):
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


def send_error(update, context, error="Error"):
    context.bot.send_message(chat_id=update.effective_chat.id, text=error)
    return False


def help_command(update, context):
    """
        Sends help text
    """
    if update.edited_message:
        return

    logging.warning(f"{update.message.from_user.id}:help_command()")

    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Help:\n"
                                  "/list or /lst - returns list of all available rates\n\n"

                                  "/exchange $10 to CAD or /exchange 10 USD to CAD -  converts to the second currency "
                                  "with two decimal precision and returns\n\n"

                                  "/history USD/CAD for 7 days - returns an image graph chart which shows the exchange "
                                  "rate graph/chart of the selected currency for the last days")


def list_command(update, context):
    """
        Sends latest rates
    """
    if update.edited_message:
        return

    logging.warning(f"{update.message.from_user.id}:list_command()")

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
        return send_error(update, context, "You should enter value that >0")

    if "$" in message or "USD" in message.upper():
        currency = get_currency(split_message)
        if currency["currency"] != " ":
            converted_value = exchange(value, currency["rate"], currency["converse"])
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=f"{converted_value} {currency['currency']}")
        else:
            send_error(update, context, "There is no entered currency")
    else:
        send_error(update, context, "You should use base currency '$' or 'USD' to exchange successful")


def exchange_command(update, context):
    """
        Returns converted r"USD/EUR" to ("USD", "EUR") or sends error text & returns False
    """
    if update.edited_message:
        return

    logging.warning(f"{update.message.from_user.id}:exchange_command()")

    message = update.message.text

    if "\n" in message:
        return send_error(update, context, "You should enter data without enters")

    if 4 <= len(update.message.text.split()) <= 5:
        send_converted_value(message, update, context)
    else:
        send_error(update, context, "Use this format: /exchange [$10] to [CAD] or /exchange [10] [USD] to [CAD]")


def get_split_name(name, update, context):
    """
        Returns converted r"USD/EUR" to ["USD", "EUR"] or sends error text & returns False
    """
    split_name = name.split("/")
    if len(split_name) != 2 or not split_name[0] or not split_name[1]:
        return send_error(update, context, "Use this format: /history [USD]/[CAD] for [7] days")

    if split_name[0].upper() != "USD":
        return send_error(update, context, "This bot supports only USD base currency. (USD should be first)")

    elif split_name[0].upper() == split_name[1].upper():
        return send_error(update, context, "USD should be used with another currency")

    split_name = [i.upper() for i in split_name]
    return split_name


def get_days(split_message, update, context):
    try:
        days = int(split_message[3])
        if days > 30 or days < 2:
            raise ValueError
    except ValueError:
        return send_error(update, context, "Entered less then 2 or more then 30 days")
    except BaseException:
        return send_error(update, context, "Use this format: /history [USD]/[CAD] for [7] days")
    return days


def create_keyboard(callback_data="0"):
    return [
                [
                    InlineKeyboardButton("Details", callback_data=callback_data),
                ],
            ]


def create_markup(split_name, days):
    time = datetime.now()
    array = []

    name = f"{split_name[0]}-{split_name[1]}"
    for i in range(days):
        str_time = time.strftime("%Y-%m-%d")
        try:
            array.append((str_time, get_rate(time=str_time, name=split_name[1])[split_name[1]]))
        except BaseException:
            keyboard = create_keyboard(callback_data="0")
            break
        time -= timedelta(days=1)
    else:
        array.reverse()

        keyboard = create_keyboard(callback_data=name.replace("/", "-"))

        p = Process(target=generate_plot, args=(array, name,))
        p.start()
        p.join()
    return InlineKeyboardMarkup(keyboard)


def send_graph(split_message, update, context):
    name = split_message[1]  # USD/CAD
    if "/" not in name:
        return send_error(update, context, "Use this format: /history [USD]/[CAD] for [7] days")

    split_name = get_split_name(name, update, context)
    if not split_name:
        return

    days = get_days(split_message, update, context)
    if not days:
        return

    message = update.message.reply_text('Wait finishing of process')
    reply_markup = create_markup(split_name, days)
    message.edit_text('Click button to get graph', reply_markup=reply_markup)


def history_command(update, context):
    if update.edited_message:
        return

    logging.warning(f"{update.message.from_user.id}:history_command()")

    split_message = update.message.text.split()

    if len(split_message) == 5:
        send_graph(split_message, update, context)
    else:
        return send_error(update, context, "Use this format: /history [USD]/[CAD] for [7] days")


def main():
    logging.warning("Bot is running")
    token = os.environ['token']
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

    logging.warning("Bot is starting")
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
