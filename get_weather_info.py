#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
気象情報取得モジュール (気象庁JSON版)
(infomation_board.py から呼び出されることを想定)
"""

import datetime
import requests
import json
import os
from typing import Optional, Dict

# --- infomation_board.py と定義を合わせる ---
INFO_DIR = "infomation_json_files"
WEATHER_INFO_FILE = os.path.join(INFO_DIR, "weather_forecast.json")
# 生のJSONを保存するファイル
JMA_RAW_JSON_FILE = os.path.join(INFO_DIR, "jma_forecast_raw.json")

# --- 気象庁 定数 ---
# エリアコード (130000 = 東京都)
AREA_CODE = "130000" 
JSON_URL = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{AREA_CODE}.json"
# 気象庁のデータが更新された最新時刻 (AMEDAS基準だが、予報の更新目安として使用)
LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"

def read_json_local(filepath: str) -> Optional[Dict]:
    """(ローカル) JSONファイルを読み込む"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Warning: Failed to read local weather JSON: {e}")
        # エラー時は None を返し、ネットワーク取得を強制する
        return None

def write_json_local(filepath: str, data: Dict):
    """(ローカル) JSONファイルに書き出す"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Warning: Failed to write local raw weather JSON {filepath}: {e}")
    except TypeError as e:
        print(f"Warning: Failed to serialize raw weather JSON {filepath}: {e}")


def get_latest_time_from_jma() -> Optional[str]:
    """気象庁のデータ最終更新時刻を取得"""
    try:
        # タイムアウトを5秒に設定
        with requests.get(LATEST_TIME_URL, timeout=5) as response:
            response.raise_for_status()
            # "2025-11-07T03:00:00+09:00" のような文字列が返る
            return response.text.strip()
    except Exception as e:
        print(f"Failed to get latest_time.txt: {e}")
        return None

def fetch_weather_from_jma(base_time: datetime.datetime) -> Optional[Dict]:
    """(ネットワークアクセス) 気象庁から新しい天気情報を取得する"""
    print("Updating weather info...")
    try:
        # 1. 気象庁のデータ最終更新時刻 (予報発表時刻とは別)
        jma_latest_time_str = get_latest_time_from_jma()
        
        # 2. 天気予報JSON
        jma_json = requests.get(JSON_URL, timeout=5).json()

        # 2b. ★生のJSONをそのまま保存する
        try:
            write_json_local(JMA_RAW_JSON_FILE, jma_json)
            print(f"Saved raw JMA JSON to {JMA_RAW_JSON_FILE}")
        except Exception as e:
            # 生JSONの保存失敗は警告に留め、処理は続行する
            print(f"Warning: Failed to save raw JMA JSON: {e}")

        # 3. JSONをパース
        
        # jma_json[0] は「今日・明日の予報」
        forecast_today = jma_json[0]
        
        # 天気情報発表元
        publishing_office = forecast_today.get("publishingOffice", "不明な発表元")
        
        report_time_str = forecast_today["reportDatetime"]
        report_time = datetime.datetime.fromisoformat(report_time_str).strftime("%H:%M")
        
        # timeSeries[0] は「天気・風・波」
        weather_wind_wave = forecast_today["timeSeries"][0]
        
        # ★timeSeries[2] は「気温」 (主要都市名はこちらを参照)
        temperature_data = forecast_today["timeSeries"][2]
        
        # ★area_name は 気温情報(timeSeries[2])の主要都市名(areas[0]) を使用
        # (例: "東京" や "横浜")
        area_name = temperature_data["areas"][0]["area"]["name"]
        
        # 天気・風・波は、広域予報 (weather_wind_wave) の [areas[0]] を使用
        # (例: "東京地方" や "東部")
        area_weather_data = weather_wind_wave["areas"][0]
        
        # timeDefines[0] (今日) の情報を取得
        # (インデックス0が今日、1が明日)
        weather = area_weather_data["weathers"][0] # 例: "晴れ"
        wind = area_weather_data["winds"][0]       # 例: "南西の風　後　北の風"
        wave = area_weather_data["waves"][0]       # 例: "０．５メートル" (東京湾)

        # 4. 保存するデータを作成
        weather_data = {
            "publishing_office": publishing_office, # ★追加
            "area_name": area_name,             # ★取得元変更
            "report_time": report_time,         # 予報の発表時刻
            "weather": weather,
            "wind": wind,
            "wave": wave,
            "jma_latest_update": jma_latest_time_str, # 要求された気象庁のデータ更新時刻
            "last_fetched": base_time.isoformat()     # このプログラムが最後に取得した時刻
        }
        
        print("Weather info updated successfully.")
        return weather_data

    except requests.exceptions.RequestException as e:
        print(f"Error fetching JMA weather data: {e}")
        return None
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        # JSONの中身が期待通りでない場合
        print(f"Error parsing JMA weather JSON: {e}")
        return None

def get_weather_info(location_name: str, base_time: datetime.datetime) -> Optional[Dict]:
    """
    気象情報を取得 (1時間に1回キャッシュ)
    location_name は STATIONS_CONFIG["from"] を受け取るが、
    エリアコードは固定 (130000) を使用する。
    
    infomation_board.py の write_json に渡すための辞書を返す。
    """
    
    # 1. キャッシュファイルを読む
    cached_data = read_json_local(WEATHER_INFO_FILE)
    
    # 2. 1時間経過したかチェック
    if cached_data and "last_fetched" in cached_data:
        try:
            # 最後に「このプログラムが」取得した時刻
            last_fetched_time = datetime.datetime.fromisoformat(cached_data["last_fetched"])
            
            if base_time - last_fetched_time < datetime.timedelta(hours=1):
                print("Skipping weather info update (less than 1 hour ago).")
                # 1時間経っていないので「キャッシュしたデータ」をそのまま返す
                return cached_data
        except (ValueError, TypeError):
            # JSON内の時刻フォーマットが不正なら、取得に進む
            pass 

    # 3. ネットワークアクセス (1時間経過 or キャッシュなし)
    new_weather_data = fetch_weather_from_jma(base_time)
    
    if new_weather_data:
        # 新しいデータを返す (書き込みは infomation_board.py が行う)
        return new_weather_data
    else:
        # 取得に失敗した場合、古いキャッシュがあればそれを返す (更新しない)
        # (ネットワークエラー時に古い情報を表示し続けるため)
        if cached_data:
            print("Failed to fetch new weather, returning old cache.")
            return cached_data
        else:
            # キャッシュもなく、取得にも失敗した場合
            return None