#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import time
import datetime
import json
import os
import sys
import subprocess
import get_train_info
import get_weather_info

# --- 設定 ---
INFO_DIR = "information_json_files"
OPERATION_INFO_FILE = os.path.join(INFO_DIR, "operation.json")
DEPARTURE_INFO_FILE = os.path.join(INFO_DIR, "departure.json")
FIRST_LAST_INFO_FILE = os.path.join(INFO_DIR, "first_last_train.json")
WEATHER_INFO_FILE = os.path.join(INFO_DIR, "weather_forecast.json")

# 駅設定（from: 設定する駅, to: 上下線の列車が向かう先の例を2つ記入する）
STATIONS_CONFIG = {
    "from": "登戸",
    "to": ["新宿", "町田"]
}

# C++プログラムのパス
DRAW_PROGRAM_PATH = "./draw_matrix"

# --- グローバル変数 ---
search_thread = None
last_search_time = datetime.datetime.min
search_lock = threading.Lock()

#  始発・終電の更新フラグ 
is_first_last_train_updated_today = False

# --- ユーティリティ ---
def get_current_time():
    return datetime.datetime.now()

def create_info_dir():
    if not os.path.exists(INFO_DIR):
        os.makedirs(INFO_DIR)

def write_json(filepath, data):
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath) # アトミックな置き換え
    except IOError as e:
        print(f"Error writing JSON: {e}", file=sys.stderr)

def read_json(filepath):
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

# --- タスク関数群 ---
def search_first_last_trains_task():
    print("Searching first/last trains...")
    now = get_current_time()
    search_date = get_train_info.get_search_date_for_first_last(now)
    try:
        results = get_train_info.search_first_last_trains(
            STATIONS_CONFIG["from"], STATIONS_CONFIG["to"], search_date
        )
        write_json(FIRST_LAST_INFO_FILE, results)
        print("First/last train info updated.")
    except Exception as e:
        print(f"Error in first/last search: {e}")

def search_departure_info_task():
    """  始発・終電判定ロジック  """
    print("Searching departure info...")
    now = get_current_time()
    
    # 検索時刻を「現在時刻の15分後」に設定
    # 10分前トリガーで実行された際、次の列車（14分以内に発車する列車は除外）を取得するため。
    search_dt_base = get_train_info.get_search_datetime_for_departure(now)
    search_dt = search_dt_base + datetime.timedelta(minutes=15)
    print(f"Base time: {search_dt_base}, Searching for trains around (Now + 15min): {search_dt}")
    
    try:
        # 1. 経路情報を取得 (15分後の時刻で検索)
        results, detour_message = get_train_info.search_departure_info(
            STATIONS_CONFIG["from"], STATIONS_CONFIG["to"], search_dt
        )
        
        # 2. 始発・終電情報をファイルから読み込む
        first_last_data = read_json(FIRST_LAST_INFO_FILE)

        # 3. 取得した経路情報(results)にステータスを追加
        if first_last_data:
            for dest_name, info in results.items():
                if not info: # 経路が見つからなかった場合
                    continue
                
                current_dep_time = info.get("departure_time")
                if not current_dep_time:
                    continue

                # デフォルトステータス
                info["status"] = "" 
                
                if dest_name in first_last_data:
                    try:
                        # (get_train_info が返すJSONのキー構造を想定)
                        first_time = first_last_data[dest_name].get("first_train_time")
                        last_time = first_last_data[dest_name].get("last_train_time")

                        if current_dep_time == first_time:
                            info["status"] = "始発"
                        elif current_dep_time == last_time:
                            info["status"] = "終電"
                            
                    except Exception as e:
                        print(f"Error processing first/last data for {dest_name}: {e}")
        
        # 4. ステータスが追加された results をJSONに書き込む
        write_json(DEPARTURE_INFO_FILE, results)
        
    except Exception as e:
        print(f"Error in departure search: {e}")
        # エラー時は空のJSON（またはnull）を書き込む
        write_json(DEPARTURE_INFO_FILE, None)


def get_operation_info_task():
    print("Updating operation info...")
    try:
        operation_data = get_train_info.get_operation_info()
        operation_data["last_updated"] = get_current_time().isoformat()
        write_json(OPERATION_INFO_FILE, operation_data)
    except Exception as e:
        print(f"Error in operation info: {e}")
        write_json(OPERATION_INFO_FILE, None) # エラー時はnull

def get_weather_info_task():
    print("Updating weather info...")
    try:
        weather_data = get_weather_info.get_weather_info( 
            STATIONS_CONFIG["from"], get_current_time()
        )
        if weather_data:
            write_json(WEATHER_INFO_FILE, weather_data)
        else:
            # get_weather_info が None を返した場合 (キャッシュ使用中など)
            # 意図的に null を書き込むか、古いファイルを保持するかを選択
            # ここでは何もしない（古い情報を表示し続ける）
            print("Weather info using cache or failed, not writing new file.")
    except Exception as e:
        print(f"Error in weather info: {e}")
        write_json(WEATHER_INFO_FILE, None) # エラー時はnull

def search_thread_task():
    global last_search_time, search_thread
    with search_lock:
        try:
            search_departure_info_task()
            get_operation_info_task()
            get_weather_info_task()
        except Exception as e:
            print(f"Search thread error: {e}")
        finally:
            last_search_time = get_current_time()
            search_thread = None

def check_search_trigger(current_time, departure_data):
    """ 検索スレッドを起動すべきか判定 (10分前ロジック) """
    global search_thread, last_search_time
    
    # 1. スレッドが実行中か？
    if search_thread and search_thread.is_alive():
        return False

    # 2. 前回の検索から1分経過したか？ (クールダウン)
    # (ネットワークエラー時や終電後に無限ループしないように)
    if current_time - last_search_time < datetime.timedelta(minutes=1):
        return False
        
    # 3. JSONデータがない場合 (起動直後など)
    if not departure_data or not isinstance(departure_data, dict):
        print("No departure data, triggering initial search.")
        return True
        
    # 4. 発車時刻の15分前か？
    # 複数の行先のうち、最も早い発車時刻を基準にする
    
    try:
        earliest_departure = datetime.time.max
        found_data = False
        
        for station_to, info in departure_data.items():
            if info and info.get("departure_time"):
                dep_time_str = info["departure_time"]
                # "06:50" のような文字列を time オブジェクトに
                dep_time = datetime.datetime.strptime(dep_time_str, "%H:%M").time()
                if dep_time < earliest_departure:
                    earliest_departure = dep_time
                found_data = True
        
        if not found_data:
            print("No valid departure times found (after last train?), triggering search.")
            return True

        # 5. 発車時刻の15分前を計算
        # (current_time は datetime.datetime, earliest_departure は datetime.time)
        dep_dt = datetime.datetime.combine(current_time.date(), earliest_departure)
        
        # 6. 0時付近の日付またぎ対応 (3時基準)
        if dep_dt.time() < datetime.time(3, 0) and current_time.time() > datetime.time(21, 0):
            # 発車時刻が深夜 (0-3時) で、現在時刻が夜 (21-24時) の場合、
            # 発車時刻は「明日」のはず
            dep_dt += datetime.timedelta(days=1)
        
        # (例: 01:00に 00:30 の終電データ(過去)が残っている場合)
        if dep_dt < current_time and (current_time - dep_dt).total_seconds() > 3600:
             # 1時間以上過去のデータなら、次の検索トリガー（終電後）として扱う
             print("Departure time is in the past, triggering search.")
             return True
        
        # 7. トリガー時刻を計算
        trigger_dt = dep_dt - datetime.timedelta(minutes=14)
        
        # 8. トリガー時刻を過ぎていたら検索実行
        if current_time >= trigger_dt:
            print(f"Trigger time {trigger_dt.time()} (10min before {earliest_departure}) reached. Triggering search.")
            return True

    except Exception as e:
        print(f"Error in check_search_trigger: {e}")
        return True # エラー時はとりあえず検索

    return False
# --- メインループ ---
def main_loop():
    global search_thread, is_first_last_train_updated_today
    print("Starting main loop (Data Fetcher)...")
    
    # C++の描画プロセスを起動
    print(f"Launching C++ renderer: {DRAW_PROGRAM_PATH}")
    renderer_process = subprocess.Popen(
        ["sudo", DRAW_PROGRAM_PATH],
        cwd=os.getcwd()
    )
    
    # 起動時の時刻でフラグを初期化
    initial_now = get_current_time()
    if initial_now.hour == 2:
        is_first_last_train_updated_today = False
        print("Started at 2 AM. Waiting for 3 AM update.")
    else:
        # 起動時に search_first_last_trains_task が実行済みのためTrue
        is_first_last_train_updated_today = True
        print("First/last train flag set to True for today.")


    try:
        while True:
            now = get_current_time()
            
            # C++プロセスが死んでいたら再起動
            if renderer_process.poll() is not None:
                print("Warning: Renderer process died. Restarting...")
                renderer_process = subprocess.Popen(["sudo", DRAW_PROGRAM_PATH], cwd=os.getcwd())

            # 1. 始発・終電の更新チェック (午前3時)
            if now.hour == 3 and not is_first_last_train_updated_today:
                print("It's 3 AM. Triggering daily first/last train info update...")
                is_first_last_train_updated_today = True
                
                # 非同期で始発・終電検索を実行
                first_last_thread = threading.Thread(target=search_first_last_trains_task, daemon=True)
                first_last_thread.start()
            
            # 2. フラグリセット (午前2時)
            elif now.hour == 2 and is_first_last_train_updated_today:
                print("It's 2 AM. Resetting daily update flag for next day.")
                is_first_last_train_updated_today = False

            # 3. データの読み込み（トリガー判定用）
            dep_data = read_json(DEPARTURE_INFO_FILE)
            
            # 4. 検索が必要かチェックして実行
            if check_search_trigger(now, dep_data):
                if not search_thread or not search_thread.is_alive():
                    search_thread = threading.Thread(target=search_thread_task, daemon=True)
                    search_thread.start()

            time.sleep(10) # 10秒に1回チェック

    except KeyboardInterrupt:
        print("Stopping...")
        if renderer_process.poll() is None:
            subprocess.run(["sudo", "kill", str(renderer_process.pid)])
    except Exception as e:
        print(f"Main loop error: {e}")
        if renderer_process.poll() is None:
            subprocess.run(["sudo", "kill", str(renderer_process.pid)])

if __name__ == "__main__":
    create_info_dir()
    
    # 起動時に始発・終電を「同期的」に取得
    print("Performing initial search for first/last trains...")
    search_first_last_trains_task()
    
    # 起動時に通常検索を「非同期」に取得
    print("Performing initial search for departure/weather...")
    search_thread = threading.Thread(target=search_thread_task, daemon=True)
    search_thread.start()
    
    # メインループ開始
    main_loop()