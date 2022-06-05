__author__ = 'Shawn Fu (shawn13aby@gmail.com)'

import logging as log
import sqlite3
import json
from flask import Flask, request, abort
import os
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    QuickReply,
    QuickReplyButton,
    MessageAction,
)
import requests
from datetime import datetime
import pytz
import re

log.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s',
                level=log.INFO)

app = Flask(__name__)
line_bot_api = LineBotApi(os.environ['LINE_TOKEN'])
handler = WebhookHandler(os.environ['LINE_SECRET'])


@app.route("/")
def index():
    return '<h1>healthy</h1>'


@app.route('/callback', methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    log.debug('Request body: ' + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        log.error('Invalid signature. Please check your channel access token/channel secret.')
        abort(400)

    return 'OK'


def _get_tw_stock(stock):
    params = {
        'type': 'tick',
        'perd': '1m',
        'mkt': '10',
        'sym': stock,
        'callback': ''
    }
    response = requests.get('https://tw.quote.finance.yahoo.net/quote/q',
                            params=params).text.strip('(;)')
    response = json.loads(response.replace('"143":09', '"143":10'))
    mem = response['mem']
    last_tick = response['tick'][-1]
    time = str(last_tick['t'])
    yyyy = time[:4]
    MM = time[4:6]
    dd = time[6:8]
    HH = time[8:10]
    mm = time[10:]
    price = last_tick['p']
    change = mem['184']
    rate_of_change = mem['185']
    volumn = mem['404']
    name = mem['name']
    return f'{name}\n{yyyy}-{MM}-{dd} {HH}:{mm}\n現\u3000價: {price}\n漲\u3000跌: {change} ({rate_of_change:.2f} %)\n成交量: {volumn}'


def _get_index_stock(stock):
    response = requests.get(
        f'https://query2.finance.yahoo.com/v7/finance/options/{stock}',
        headers={'User-Agent': 'Mozilla/5.0'})
    response = json.loads(response.text)
    quote = response['optionChain']['result'][0]['quote']
    time = datetime.fromtimestamp(
        quote['regularMarketTime'],
        pytz.timezone('America/New_York')).strftime("%Y-%m-%d %H:%M")
    price = quote['regularMarketPrice']
    change = quote['regularMarketChange']
    rate_of_change = quote['regularMarketChangePercent']
    volumn = quote['regularMarketVolume']
    return f'{stock}\n{time}\n現\u3000價: {price:.2f}\n漲\u3000跌: {change:.2f} ({rate_of_change:.2f} %)\n成交量: {volumn:d}'


def _get_watch_list(l, reply):
    if l:
        stock = l.pop()
        try:
            if stock == '#001':
                reply = f'{reply}\n{_get_tw_stock(stock)}'
            elif stock in tw_stock_name_id_dict.values():
                reply = f'{reply}\n{_get_tw_stock(stock)}'
            elif stock in index_stock_name_id_dict.values():
                reply = f'{reply}\n{_get_index_stock(stock)}'
        except:
            reply = f'{reply}\n\n目前無法取得{stock}\n'
        return _get_watch_list(l, reply)
    else:
        return reply


def _watch_list_add(cur, l, user, stock):
    if stock not in l:
        l.append(stock)
        cur.execute(f'INSERT OR REPLACE INTO kuko VALUES("{user}", "{l}")')
        return f'成功關注{stock}'
    return f'已經關注{stock}'


def _watch_list_remove(cur, l, user, stock):
    if stock in l:
        l.remove(stock)
        cur.execute(f'INSERT OR REPLACE INTO kuko VALUES("{user}", "{l}")')
        return f'成功移除{stock}'
    return f'尚未關注{stock}'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        message = event.message.text
        user_id = event.source.user_id

        con = sqlite3.connect('kuko.db')
        cur = con.cursor()
        kuko_list = []
        cur.execute(f'SELECT stock FROM kuko WHERE id = "{user_id}"')
        row = cur.fetchone()
        if row:
            log.info(f'id: {user_id}, stock: {row[0]}')
            kuko_list = eval(row[0])

        # logic
        if message == '關注清單':
            kuko_list.append('#001')
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=_get_watch_list(kuko_list, message)))
        else:
            for k, v in tw_stock_name_id_dict.items():
                if re.match(r'^\+', message) and (message[1:] == k
                                                  or message[1:] == v):
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text=_watch_list_add(cur, kuko_list, user_id, v)))
                    con.commit()
                    return
                elif re.match(r'^\-', message) and (message[1:] == k
                                                    or message[1:] == v):
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=_watch_list_remove(
                            cur, kuko_list, user_id, v)))
                    con.commit()
                    return
                elif message == k or message == v:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text=_get_tw_stock(v),
                            quick_reply=QuickReply(items=[
                                QuickReplyButton(action=MessageAction(
                                    label='關注', text='+' + message)),
                                QuickReplyButton(action=MessageAction(
                                    label='移除', text='-' + message))
                            ])))
                    return
            for k, v in index_stock_name_id_dict.items():
                if re.match(r'^\+', message) and (message[1:] == k
                                                  or message[1:] == v):
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text=_watch_list_add(cur, kuko_list, user_id, v)))
                    con.commit()
                    return
                elif re.match(r'^\-', message) and (message[1:] == k
                                                    or message[1:] == v):
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=_watch_list_remove(
                            cur, kuko_list, user_id, v)))
                    con.commit()
                    return
                elif message == k or message == v:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text=_get_index_stock(v),
                            quick_reply=QuickReply(items=[
                                QuickReplyButton(action=MessageAction(
                                    label='關注', text='+' + message)),
                                QuickReplyButton(action=MessageAction(
                                    label='移除', text='-' + message))
                            ])))
                    return
    finally:
        con.close()


if __name__ == '__main__':
    con = sqlite3.connect('kuko.db')
    cur = con.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS kuko (id text primary key, stock text)')
    con.commit()
    con.close()
    with open('tw_stock.json') as tw_stock_name_id_json:
        tw_stock_name_id_dict = json.load(tw_stock_name_id_json)
    with open('index_stock.json') as index_stock_name_id_json:
        index_stock_name_id_dict = json.load(index_stock_name_id_json)
    app.run('0.0.0.0')
