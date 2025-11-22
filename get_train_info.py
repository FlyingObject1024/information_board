#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
列車情報 (運行、発車、始発終電) の取得・解析モジュール
(このファイルは infomation_board.py から呼び出されることを想定)
"""

import sys
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error
from bs4 import BeautifulSoup
from typing import List
import requests
import json # JSONパーサーを追加
import logging # logging モジュールをインポート

logging.basicConfig(
    level=logging.DEBUG, # 表示するログの最小レベルをDEBUGに設定
    stream=sys.stdout,   # 出力先を標準出力(コンソール)に設定
    format="%(asctime)s [%(levelname)s] %(message)s" # ログのフォーマット
)

# --- ロガーのセットアップ ---
# このモジュール用のロガーを取得
# 実際の設定 (レベル、フォーマットなど) は呼び出し元 (infomation_board.py) で行う
logger = logging.getLogger(__name__)

# --- 定数 (このモジュール固有) ---
TRAIN_TYPES = [
    'ホリデー快速おくたま', 'ホリデー快速あきがわ', 'エアポート快特', 
    'アクセス特急', 'S-TRAIN', 'TJライナー', 'F-LINER', 'Fライナー', # Fライナーの表記ゆれ対応
    '区間快速', '通勤快速', '中央特快', '青梅特快', '特別快速', 
    '通勤特快', '新快速', '区間急行', '区間準急', '通勤準急', '快速急行', 
    '各駅停車', '各停', '快速', '特快', '急行', '準急', '特急', '普通'
]
COMPANY_NAMES = [
    'ＪＲ', 'JR', '東京メトロ', '都営', '京王', '小田急', '京急', '京成', '東武', '西武', '東急'
]

# --- 運行情報クラス ---
class NowTrainInfomation:
    
    def categorize_routes(self,route_list: dict) -> tuple[list, list, list]:
        """
        route_list を「運転見合わせ」「遅延」「その他」に分類する
        (変更なし)
        """
        delay_list = []
        suspend_list = []
        trouble_list = []

        for name, value in route_list.items():
            status = value.get("status", "")
            detail = value.get("detail", "")
            
            # 会社名を取得（見つからない場合のデフォルトも設定）
            company = value.get("company", "社名未定義")
            
            if not detail:
                continue

            # entry に company を含める
            entry = {'name': name, 'detail': detail, 'company': company}

            if status in ["運転状況", "運転情報", "列車遅延", "運転再開"]:
                delay_list.append(entry)
            elif status == "運転見合わせ":
                suspend_list.append(entry)
            else:
                trouble_list.append(entry)
        
        return suspend_list, delay_list, trouble_list

    def generate_message(self, route_type: str, route_names: List[dict]) -> str:
        """(ロギング用) 路線名のみを抽出して表示"""
        if not route_names:
            return ""
        
        # ログメッセージには会社名を含めない（元の仕様を維持）
        names_only = [item['name'] for item in route_names]
        message = f"{route_type}"
        message += ", ".join(names_only)
        # print(message, flush=True) -> logger.info() に変更
        logger.info(message)
        return message

    """
    遅延情報を取得する (JSON (__NEXT_DATA__) 解析版)
    """
    def get_train_operation_information(self,area_num: int = 4):
        # print("列車運行情報を取得します", flush=True) -> logger.info()
        logger.info("列車運行情報を取得します")
        html_data = None
        text = "" # ログ表示用

        try:
            url = f'https://transit.yahoo.co.jp/diainfo/area/{area_num}'
            html_data = requests.get(url)
            html_data.raise_for_status()

        except Exception as e:
            # print(f"get_train_operation_information Error: {e}", flush=True) -> logger.error()
            logger.error(f"get_train_operation_information Error: {e}")
            text = "運行情報が読み込めませんでした"
            return text, {"suspend_list": [], "delay_list": [], "trouble_list": []}

        soup = BeautifulSoup(html_data.text, 'html.parser')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        
        route_list = {} 

        if not next_data_script:
            # print("Warning: __NEXT_DATA__ script tag not found...", flush=True) -> logger.warning()
            logger.warning("Warning: __NEXT_DATA__ script tag not found. Falling back to old parser (if available).")
            text = "運行情報ページ構造が変更された可能性があります。"
        
        else:
            try:
                data = json.loads(next_data_script.string)
                trouble_rails = data.get("props", {}).get("pageProps", {}).get("troubleRails", [])

                if not trouble_rails:
                    text = "現在、遅延情報はありません"
                
                for item in trouble_rails:
                    property = item.get("routeInfo", {}).get("property", {})
                    route_name = property.get("displayName", "不明な路線")
                    diainfo_list = property.get("diainfo", [])
                    
                    if diainfo_list:
                        primary_info = diainfo_list[0]
                        status = primary_info.get("status", "")
                        detail_message = primary_info.get("message", "")
                        
                        # 会社名を displayName (route_name) から特定する
                        company_name = "社名未定義"
                        for c in COMPANY_NAMES:
                            # 路線名が会社名で始まるかチェック (例: "ＪＲ埼京線")
                            if route_name.startswith(c):
                                company_name = c
                                break
                        
                        route_list[route_name] = {
                            "status": status,
                            "detail": detail_message,
                            "company": company_name
                        }

            except json.JSONDecodeError as e:
                # print(f"Error: Failed to parse __NEXT_DATA__ JSON: {e}", flush=True) -> logger.error()
                logger.error(f"Error: Failed to parse __NEXT_DATA__ JSON: {e}")
                text = "運行情報(JSON)の解析に失敗しました。"
            except Exception as e:
                # print(f"Error: Failed to parse __NEXT_DATA__ structure: {e}", flush=True) -> logger.error()
                logger.error(f"Error: Failed to parse __NEXT_DATA__ structure: {e}")
                text = "運行情報(JSON)の構造解析に失敗しました。"

        suspend_list = []
        delay_list = []
        trouble_list = []

        if len(route_list) == 0 and not text:
            text = "現在、遅延情報はありません"
        elif route_list:
            suspend_list, delay_list, trouble_list = self.categorize_routes(route_list)
            
            # コンソールへの表示 (ロギング)
            text += self.generate_message("運転見合わせ: ", suspend_list)
            text += self.generate_message("遅延情報有り: ", delay_list)
            text += self.generate_message("お知らせ有り: ", trouble_list)

        return text, {
            "suspend_list": suspend_list,
            "delay_list": delay_list,
            "trouble_list": trouble_list
        }

# --- 共通ユーティリティ (時刻計算) ---
def get_search_date_for_first_last(base_time):
    return (base_time - datetime.timedelta(hours=3)).date()

def get_search_datetime_for_departure(base_time):
    return base_time + datetime.timedelta(minutes=10)

# --- HTML取得・解析 (検索スレッド) ---
def fetch_transit_html(params):
    """Yahoo!乗換案内のHTMLを取得"""
    
    base_url = "https://transit.yahoo.co.jp/search/result?"
    params.update({
        'type': '1', 'ticket': 'ic', 'expkind': '1', 'ws': '3', 
        's': '0', 'shin': '0', 'via': '',
    })
    
    query_string = urllib.parse.urlencode(params)
    url = base_url + query_string
    
    # print(f"Fetching: {url}", flush=True) -> logger.debug() (デバッグ情報)
    # logger.debug(f"Fetching: {url}") # 必要に応じてコメント解除
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36'
        }
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                html = response.read().decode('utf-8')
                return html
            else:
                # print(f"Warning: fetch_transit_html received status {response.status}", flush=True) -> logger.warning()
                logger.warning(f"Warning: fetch_transit_html received status {response.status}")
                return None
                
    except urllib.error.URLError as e:
        # ConnectionError は呼び出し元で処理
        raise ConnectionError(f"Network error accessing {url}: {e}")
        
    except Exception as e:
        # print(f"Warning: Error in fetch_transit_html: {e}", flush=True) -> logger.warning()
        logger.warning(f"Warning: Error in fetch_transit_html: {e}")
        return None

def parse_train_type_and_line(line_name_raw):
    """路線名（生）から「種別」と「路線名」を抽出"""
    train_type = "各駅停車"
    line_name = line_name_raw
    # print(line_name_raw, flush=True) -> logger.debug() (詳細すぎるためデバッグレベル)
    logger.debug(f"Parsing line_name_raw: {line_name_raw}")
    
    for t in TRAIN_TYPES:
        if t in line_name_raw:
            train_type = t
            line_name = line_name.replace(t, '')
            break
            
    for c in COMPANY_NAMES:
        line_name = line_name.replace(c, '')
        
    return train_type.strip(), line_name.strip()

def parse_destination(dest_raw):
    """行先（生）から '行' を削除 (変更なし)"""
    if dest_raw.endswith('行'):
        return dest_raw[:-1]
    return dest_raw

def parse_route_info(soup, is_first_last=False):
    """
    HTMLから「ルート1」の情報を解析
    """
    
    local_message = ""
    
    route_div = soup.find("div", id="route01")
    if not route_div:
        if soup.find(class_="attention"):
            msg = soup.find(class_="attention").get_text(strip=True)
            if "終電時刻を過ぎています" in msg:
                if not is_first_last:
                    local_message = "終電時刻を過ぎています。"
            elif "現在発車する列車はありません" in msg:
                local_message = "現在発車する列車はありません。"
        
        detour_info = soup.find("div", id="detourinfo")
        if detour_info:
            detour_text_span = detour_info.find("span", class_="subText")
            if detour_text_span:
                detour_text = detour_text_span.get_text(strip=True)
                if detour_text and "遅延" in detour_text:
                    # print(f"Detour info found: {detour_text}", flush=True) -> logger.info()
                    logger.info(f"Detour info found: {detour_text}")
                    local_message = detour_text
                    
        return None, local_message

    route_detail = route_div.find("div", class_="routeDetail")
    if not route_detail:
        # print("Warning: parse_route_info: div.routeDetail not found.", flush=True) -> logger.warning()
        logger.warning("Warning: parse_route_info: div.routeDetail not found.")
        return None, local_message

    stations = route_detail.find_all("div", class_="station", recursive=False)
    fare_sections = route_detail.find_all("div", class_="fareSection", recursive=False)
    
    if not stations or len(stations) < 2:
        # print("Warning: parse_route_info: Not enough stations found.", flush=True) -> logger.warning()
        logger.warning("Warning: parse_route_info: Not enough stations found.")
        return None, local_message
    
    try:
        departure_time = stations[0].find("ul", class_="time").li.get_text(strip=True)
        arrival_time_li = stations[-1].find("ul", class_="time")
        if not arrival_time_li:
            arrival_time_li = stations[-1].find(class_="time")
        arrival_time = arrival_time_li.li.get_text(strip=True)

    except AttributeError:
        # print("Warning: parse_route_info: Failed to parse overall times.", flush=True) -> logger.warning()
        logger.warning("Warning: parse_route_info: Failed to parse overall times.")
        return None, local_message

    if is_first_last:
        return {"departure": departure_time, "arrival": arrival_time}, local_message

    segments = []
    
    if len(stations) != len(fare_sections) + 1:
        # print(f"Warning: parse_route_info: Mismatch stations...", flush=True) -> logger.warning()
        logger.warning(f"Warning: parse_route_info: Mismatch stations ({len(stations)}) and sections ({len(fare_sections)}).")
    
    num_segments = min(len(stations) - 1, len(fare_sections))
    
    for i in range(num_segments):
        section = fare_sections[i]
        try:
            transport_div = section.find("li", class_="transport").div
            
            # transport_div が None の場合のチェックを追加
            if not transport_div:
                logger.warning(f"Warning: parse_route_info: transport div not found in segment {i}.")
                continue

            destination_raw_span = transport_div.find("span", class_="destination")
            
            if destination_raw_span:
                destination_raw = destination_raw_span.get_text(strip=True)
                line_name_raw_full = transport_div.get_text(strip=True)
                line_name_raw = line_name_raw_full.replace(destination_raw, '').strip()
            else:
                line_name_raw = transport_div.get_text(strip=True)
                destination_raw = ""
            
            # ログ出力を見やすくするためにコロンを追加
            logger.info("raw_line_info: " + line_name_raw)
            
            train_type, line_name = parse_train_type_and_line(line_name_raw)
            destination = parse_destination(destination_raw)
            
            seg_dep_time_lis = stations[i].find("ul", class_="time").find_all("li")
            seg_arr_time = stations[i+1].find("ul", class_="time").li.get_text(strip=True)
            
            if len(seg_dep_time_lis) > 1:
                seg_dep_time = seg_dep_time_lis[1].get_text(strip=True)
            else:
                seg_dep_time = seg_dep_time_lis[0].get_text(strip=True)

            segments.append({
                "line": line_name, "type": train_type, "destination": destination,
                "departure": seg_dep_time, "arrival": seg_arr_time
            })
            
        except AttributeError as e:
            # print(f"Warning: parse_route_info: Failed to parse segment {i}: {e}", flush=True) -> logger.warning()
            logger.warning(f"Warning: parse_route_info: Failed to parse segment {i}: {e}")
            continue
            
    if not segments:
        # print("Error: parse_route_info: No segments parsed.", flush=True) -> logger.error()
        logger.error("Error: parse_route_info: No segments parsed.")
        return None, local_message
        
    return {
        "departure_time": departure_time,
        "arrival_time": arrival_time,
        "segments": segments
    }, local_message


# --- 検索タスク (infomation_board.py から呼び出される) ---
def search_first_last_trains(station_from: str, stations_to: List[str], search_date: datetime.date):
    """
    始発・終電情報を検索 (ネットワークアクセス)
    """
    
    params_date = {
        'y': search_date.year, 'm': f"{search_date.month:02}", 'd': f"{search_date.day:02}",
        'hh': 6, 'm1': 0, 'm2': 0,
    }
    
    results = {}
    
    for station_to in stations_to:
        results[station_to] = {}
        
        logger.info(f"   Fetching first train for {station_to}...")
        params_first = params_date.copy()
        params_first.update({'from': station_from, 'to': station_to, 'type': '3'})
        
        html_first = fetch_transit_html(params_first) 
        
        if html_first:
            soup_first = BeautifulSoup(html_first, 'html.parser')
            first_train_info, _ = parse_route_info(soup_first, is_first_last=True)
            results[station_to]["first_train"] = first_train_info
        else:
            # print(f"Error: Failed to get first train info for {station_to}", flush=True) -> logger.error()
            logger.error(f"Error: Failed to get first train info for {station_to}")
            results[station_to]["first_train"] = None
        
        #time.sleep(1.5)

        # print(f"   Fetching last train for {station_to}...", flush=True) -> logger.info()
        logger.info(f"   Fetching last train for {station_to}...")
        params_last = params_date.copy()
        params_last.update({'from': station_from, 'to': station_to, 'type': '2'})
        
        html_last = fetch_transit_html(params_last)
        
        if html_last:
            soup_last = BeautifulSoup(html_last, 'html.parser')
            last_train_info, _ = parse_route_info(soup_last, is_first_last=True)
            results[station_to]["last_train"] = last_train_info
        else:
            # print(f"Error: Failed to get last train info for {station_to}", flush=True) -> logger.error()
            logger.error(f"Error: Failed to get last train info for {station_to}")
            results[station_to]["last_train"] = None

        #time.sleep(1.5)
        
    return results

def check_if_first_train(departure_data, first_last_data) -> str:
    """
    取得した情報が始発かどうかを判定し、メッセージを返す
    """
    local_message = ""
    
    if not departure_data or not first_last_data:
        return local_message
        
    try:
        is_all_first_train = True
        
        has_data = any(info for info in departure_data.values())
        if not has_data:
            is_all_first_train = True
        
        else:
            for station_to, info in departure_data.items():
                if not info:
                    continue

                dep_time = info["departure_time"]
                
                if (station_to not in first_last_data or 
                    not first_last_data[station_to] or
                    not first_last_data[station_to].get("first_train")):
                    
                    # print(f"Warning: Missing first train data for {station_to}...", flush=True) -> logger.warning()
                    logger.warning(f"Warning: Missing first train data for {station_to} in check_if_first_train")
                    is_all_first_train = False
                    continue

                first_dep_time = first_last_data[station_to]["first_train"]["departure"]
                
                if dep_time != first_dep_time:
                    is_all_first_train = False
                    break
        
        if is_all_first_train:
            # print("Current display is for the first train.", flush=True) -> logger.info()
            logger.info("Current display is for the first train.")
            local_message = "終電の時刻を過ぎています。現在の表示は始発時刻です。"
            
    except Exception as e:
        # print(f"Warning: Error in check_if_first_train: {e}", flush=True) -> logger.warning()
        logger.warning(f"Warning: Error in check_if_first_train: {e}")

    return local_message

def search_departure_info(station_from: str, stations_to: List[str], search_dt: datetime.datetime):
    """
    (定期的) 直近の発着情報を検索
    """

    params_date = {
        'y': search_dt.year, 'm': f"{search_dt.month:02}", 'd': f"{search_dt.day:02}",
        'hh': f"{search_dt.hour:02}", 'm1': search_dt.minute // 10, 'm2': search_dt.minute % 10,
        'type': '1'
    }
    
    results = {}
    local_message = ""

    for station_to in stations_to:
        logger.info(f"   Fetching departure info for {station_to}...")
        params = params_date.copy()
        params.update({'from': station_from, 'to': station_to})
        
        html = fetch_transit_html(params)
        
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            route_info, msg = parse_route_info(soup)
            results[station_to] = route_info
            if msg:
                local_message = msg
        else:
            results[station_to] = None
        
        #time.sleep(1.5)

    return results, local_message

def get_operation_info():
    """
    遅延情報を取得 (詳細情報を含む)
    """
    
    train_info = NowTrainInfomation()
    train_operation_text, train_operation_dict = train_info.get_train_operation_information()
    
    # print(f"   operation: {train_operation_text}", flush=True) -> logger.info()
    # train_operation_text は既に generate_message でログ出力されているため、ここでは不要
    logger.info(f"Operation info fetch complete.") # 完了ログ
    
    operation_data = {
        "suspend": train_operation_dict.get("suspend_list", []),
        "delay": train_operation_dict.get("delay_list", []),
        "trouble": train_operation_dict.get("trouble_list", [])
    }
    return operation_data