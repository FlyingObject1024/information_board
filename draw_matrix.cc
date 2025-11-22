// draw_matrix.cc
// コンパイルコマンド例:
// g++ -o draw_matrix draw_matrix.cc -Iinclude -Llib -lrgbmatrix -lrt -lm -lpthread -O3

#include "led-matrix.h"
#include "graphics.h"
#include "json.hpp" // nlohmann/json

#include <unistd.h>
#include <signal.h>
#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <map>
#include <chrono>
#include <thread>
#include <ctime>
#include <cstdio>
#include <iomanip>

using namespace rgb_matrix;
using json = nlohmann::json;

// --- 定数・設定 ---
const std::string FONT_FILE = "fonts/BestTen-DOT.bdf";
const std::string DEPARTURE_FILE = "information_json_files/departure.json";
const std::string OPERATION_FILE = "information_json_files/operation.json";
const std::string WEATHER_FILE = "information_json_files/weather_forecast.json";

// 終了シグナル処理
volatile bool interrupt_received = false;
static void InterruptHandler(int signo)
{
    interrupt_received = true;
}

// 色定義
struct ColorRGB
{
    uint8_t r, g, b;
};
const ColorRGB COL_BLACK = {0, 0, 0};
const ColorRGB COL_WHITE = {255, 255, 255};
const ColorRGB COL_RED = {255, 0, 0};
const ColorRGB COL_GREEN = {0, 255, 0};
const ColorRGB COL_BLUE = {0, 0, 255};
const ColorRGB COL_MAGENTA = {255, 0, 255};
const ColorRGB COL_ORANGE = {255, 172, 0};
const ColorRGB COL_YELLOW = {255, 255, 0};
const ColorRGB COL_CYAN = {0, 255, 255};

// 列車種別ごとの色マップ
std::vector<std::pair<std::string, ColorRGB>> type_color_map = {
    {"快速急行", COL_ORANGE},
    {"通勤特快", COL_MAGENTA},
    {"中央特快", COL_BLUE},
    {"区間快速", COL_GREEN},
    {"各駅停車", COL_BLUE},
    {"新快速", COL_BLUE},
    {"特快", COL_MAGENTA},
    {"特急", COL_RED},
    {"急行", COL_RED},
    {"快速", COL_RED},
    {"準急", COL_GREEN},
    {"普通", COL_GREEN},
    {"各駅", COL_BLUE},
    {"各停", COL_BLUE}};

Color ToMatrixColor(const ColorRGB &c)
{
    return Color(c.r, c.g, c.b);
}

// データ保持用構造体
struct DisplayData
{
    json departure;
    json operation;
    json weather;
    std::vector<std::string> scroll_messages;
    std::vector<ColorRGB> scroll_colors;
};

// JSON読み込みヘルパー
json load_json(const std::string &path)
{
    std::ifstream i(path);
    if (!i.is_open())
        return nullptr;
    try
    {
        json j;
        i >> j;
        return j;
    }
    catch (...)
    {
        return nullptr;
    }
}

// スクロールメッセージの構築
void update_scroll_messages(DisplayData &data)
{
    data.scroll_messages.clear();
    data.scroll_colors.clear();

    // ★★★ 追加: 日付メッセージ ★★★
    {
        std::time_t t_now = std::time(nullptr);
        std::tm *tm_now = std::localtime(&t_now);
        const char *wday_name[] = {"日", "月", "火", "水", "木", "金", "土"};

        char date_buf[64];
        // "本日は MM月DD日（{曜日}）です" の形式を作成
        std::sprintf(date_buf, "本日は %02d月%02d日（%s）です",
                     tm_now->tm_mon + 1,
                     tm_now->tm_mday,
                     wday_name[tm_now->tm_wday]);

        data.scroll_messages.push_back(std::string(date_buf));
        data.scroll_colors.push_back(COL_WHITE); // 白で表示
    }

    // 1. 運行情報 (見合わせ・遅延)
    if (!data.operation.is_null())
    {
        // (見合わせ)
        if (data.operation.contains("suspend") && data.operation["suspend"].is_array())
        {
            for (const auto &item : data.operation["suspend"])
            {
                std::string name = item.value("name", "");
                std::string detail = item.value("detail", "詳細不明");
                data.scroll_messages.push_back("【運転見合わせ】 " + name + ": " + detail);
                data.scroll_colors.push_back(COL_RED);
            }
        }
        // (遅延)
        if (data.operation.contains("delay") && data.operation["delay"].is_array())
        {
            for (const auto &item : data.operation["delay"])
            {
                std::string name = item.value("name", "");
                std::string detail = item.value("detail", "詳細不明");
                data.scroll_messages.push_back("【遅延】 " + name + ": " + detail);
                data.scroll_colors.push_back(COL_YELLOW);
            }
        }
    }

    // 2. 天気予報
    if (!data.weather.is_null())
    {
        try
        {
            std::string area = data.weather.value("area_name", "不明");
            std::string weather = data.weather.value("weather", "不明");
            std::string office = data.weather.value("publishing_office", " 気象庁");
            std::string report_time = data.weather.value("report_time", " ");
            data.scroll_messages.push_back("【" + office + " " + report_time + "発表】" + area + "の天気: " + weather);
            data.scroll_colors.push_back(COL_WHITE);
        }
        catch (...)
        {
        }
    }

    // 運行終了メッセージ/エラーメッセージの追加
    if (data.departure.is_null() || data.departure.empty())
    {
        data.scroll_messages.push_back("エラーが発生しています。情報が取得できていません");
        data.scroll_colors.push_back(COL_RED);
    }

    if (data.scroll_messages.empty())
    {
        data.scroll_messages.push_back("平常運転");
        data.scroll_colors.push_back(COL_GREEN);
    }
}

// 描画切替グローバル変数
bool show_alternate_display = false;
auto last_toggle_time = std::chrono::steady_clock::now();
const int TOGGLE_SECONDS = 5; // 5秒ごとに切り替え

// メイン描画ループ
int main(int argc, char *argv[])
{
    // --- Matrix設定 ---
    RGBMatrix::Options defaults;
    defaults.hardware_mapping = "regular";
    defaults.rows = 32;
    defaults.cols = 128;
    defaults.chain_length = 1;
    defaults.parallel = 1;

    rgb_matrix::RuntimeOptions runtime_opt;
    runtime_opt.gpio_slowdown = 1;

    RGBMatrix *matrix = RGBMatrix::CreateFromOptions(defaults, runtime_opt);
    if (matrix == NULL)
        return 1;

    // --- フォント読み込み ---
    rgb_matrix::Font font;
    if (!font.LoadFont(FONT_FILE.c_str()))
    {
        fprintf(stderr, "Couldn't load font '%s'\n", FONT_FILE.c_str());
        return 1;
    }

    FrameCanvas *offscreen = matrix->CreateFrameCanvas();
    signal(SIGTERM, InterruptHandler);
    signal(SIGINT, InterruptHandler);

    DisplayData current_data;

    // スクロール管理変数
    int scroll_x = matrix->width();
    size_t msg_index = 0;

    // データ更新タイマー
    auto last_load_time = std::chrono::steady_clock::now();
    bool first_run = true;

    while (!interrupt_received)
    {
        auto now = std::chrono::steady_clock::now();

        // --- 1. データ読み込み (初回 または 2秒ごと) ---
        if (first_run || std::chrono::duration_cast<std::chrono::seconds>(now - last_load_time).count() >= 2)
        {
            current_data.departure = load_json(DEPARTURE_FILE);
            current_data.operation = load_json(OPERATION_FILE);
            current_data.weather = load_json(WEATHER_FILE);
            update_scroll_messages(current_data);

            last_load_time = now;
            first_run = false;
        }

        // --- 描画切替 (5秒ごと) ---
        if (std::chrono::duration_cast<std::chrono::seconds>(now - last_toggle_time).count() >= TOGGLE_SECONDS)
        {
            show_alternate_display = !show_alternate_display;
            last_toggle_time = now;
        }

        // --- 2. 描画クリア ---
        offscreen->Fill(0, 0, 0);

        // --- 3. 発車情報描画 ---
        int row_y_positions[] = {9, 20}; // 上段、中段のベースラインY座標
        int current_row = 0;

        if (!current_data.departure.is_null() && !current_data.departure.empty())
        {
            for (auto &el : current_data.departure.items())
            {
                if (current_row >= 2)
                    break;

                std::string dest_name = el.key();
                json val = el.value();

                if (!val.is_null() && val.contains("segments") && !val["segments"].empty())
                {
                    json seg = val["segments"][0];
                    std::string line_type = seg.value("type", "");
                    std::string dep_time = val.value("departure_time", "--:--");
                    std::string destination = seg.value("destination", "");
                    std::string status = val.value("status", "");

                    // 種別色
                    Color col_type = ToMatrixColor(COL_WHITE);
                    for (auto const &[key, val_color] : type_color_map)
                    {
                        if (line_type.find(key) != std::string::npos)
                        {
                            col_type = ToMatrixColor(val_color);
                            break;
                        }
                    }

                    // 時間計算と色決定（A面用）
                    std::string time_text = "";
                    Color time_col = ToMatrixColor(COL_GREEN);

                    if (status == "始発")
                    {
                        time_text = "始発";
                        time_col = ToMatrixColor(COL_BLUE);
                    }
                    else if (status == "終電")
                    {
                        time_text = "終電";
                        time_col = ToMatrixColor(COL_RED);
                    }
                    else
                    {
                        std::time_t t_now_calc = std::time(nullptr);
                        std::tm tm_now_calc = *std::localtime(&t_now_calc);
                        std::tm tm_dep = tm_now_calc;

                        int dep_hour, dep_min;
                        if (sscanf(dep_time.c_str(), "%d:%d", &dep_hour, &dep_min) == 2)
                        {
                            tm_dep.tm_hour = dep_hour;
                            tm_dep.tm_min = dep_min;
                            tm_dep.tm_sec = 0;

                            if (dep_hour < 3 && tm_now_calc.tm_hour >= 3)
                            {
                                tm_dep.tm_mday += 1;
                            }

                            std::time_t t_dep = std::mktime(&tm_dep);
                            double diff_seconds = std::difftime(t_dep, t_now_calc);
                            int diff_minutes = static_cast<int>(diff_seconds / 60.0) + 1;

                            if (diff_minutes > 99)
                            {
                                time_text = "始発";
                                time_col = ToMatrixColor(COL_BLUE);
                            }
                            else
                            {
                                time_text = std::to_string(diff_minutes) + "分後";
                                if (diff_minutes <= 17)
                                    time_col = ToMatrixColor(COL_RED);
                                else if (diff_minutes <= 20)
                                    time_col = ToMatrixColor(COL_YELLOW);
                                else
                                    time_col = ToMatrixColor(COL_GREEN);
                            }
                        }
                        else
                        {
                            time_text = "--:--";
                        }
                    }

                    // 表示切替ロジック
                    if (show_alternate_display)
                    {
                        // B面
                        rgb_matrix::DrawText(offscreen, font, 0, row_y_positions[current_row],
                                             col_type, NULL, line_type.c_str(), 0);
                        rgb_matrix::DrawText(offscreen, font, 50, row_y_positions[current_row],
                                             ToMatrixColor(COL_GREEN), NULL, dep_time.c_str(), 0);
                        rgb_matrix::DrawText(offscreen, font, matrix->width() - 50, row_y_positions[current_row],
                                             ToMatrixColor(COL_ORANGE), NULL, destination.c_str(), 0);
                    }
                    else
                    {
                        // A面
                        std::string direction_text = dest_name + "方面";
                        rgb_matrix::DrawText(offscreen, font, 0, row_y_positions[current_row],
                                             ToMatrixColor(COL_WHITE), NULL, direction_text.c_str(), 0);

                        rgb_matrix::DrawText(offscreen, font, 45, row_y_positions[current_row],
                                             time_col, NULL, time_text.c_str(), 0);

                        std::string dest_text = destination;
                        Color dest_col = ToMatrixColor(COL_ORANGE);

                        if (time_col.r == COL_RED.r && time_col.g == COL_RED.g && time_col.b == COL_RED.b)
                        {
                            dest_text = "駅まで走れ";
                            dest_col = ToMatrixColor(COL_RED);
                        }
                        else if (time_col.r == COL_YELLOW.r && time_col.g == COL_YELLOW.g && time_col.b == COL_YELLOW.b)
                        {
                            dest_text = "今すぐ出発";
                            dest_col = ToMatrixColor(COL_YELLOW);
                        }

                        rgb_matrix::DrawText(offscreen, font, matrix->width() - 50, row_y_positions[current_row],
                                             dest_col, NULL, dest_text.c_str(), 0);
                    }
                }
                current_row++;
            }
        }

        // --- 4. 現在時刻描画 (右下 y=31付近) ---
        std::time_t t_now_disp = std::time(nullptr);
        std::tm tm_now_disp = *std::localtime(&t_now_disp);

        // 奇数秒はコロンあり、偶数秒はコロンなし(スペース)
        char time_buffer[6];
        if (tm_now_disp.tm_sec % 2 != 0)
        {
            std::strftime(time_buffer, sizeof(time_buffer), "%H:%M", &tm_now_disp); // 奇数秒
        }
        else
        {
            std::strftime(time_buffer, sizeof(time_buffer), "%H %M", &tm_now_disp); // 偶数秒
        }
        std::string current_time_str(time_buffer);

        // --- 5. スクロールメッセージ描画 (最下段 y=31付近) ---
        if (!current_data.scroll_messages.empty())
        {
            if (msg_index >= current_data.scroll_messages.size())
                msg_index = 0;

            std::string &msg = current_data.scroll_messages[msg_index];
            Color msg_col = ToMatrixColor(current_data.scroll_colors[msg_index]);

            rgb_matrix::DrawText(offscreen, font, scroll_x, 31, msg_col, NULL, msg.c_str(), 0);

            scroll_x--;

            if (scroll_x < -((int)msg.size() * 6))
            {
                msg_index++;
                scroll_x = matrix->width();
            }
        }

        // 現在時刻の背景クリアと描画
        int time_x_pos = matrix->width() - 28;
        for (int clear_y = 22; clear_y <= 31; ++clear_y)
        {
            rgb_matrix::DrawLine(offscreen, time_x_pos - 1, clear_y, matrix->width(), clear_y, ToMatrixColor(COL_BLACK));
        }
        rgb_matrix::DrawText(offscreen, font, time_x_pos, 31, ToMatrixColor(COL_WHITE), NULL, current_time_str.c_str(), 0);

        // 区切り線
        rgb_matrix::DrawLine(offscreen, 0, 10, matrix->width(), 10, ToMatrixColor(COL_BLACK));
        rgb_matrix::DrawLine(offscreen, 0, 21, matrix->width(), 21, ToMatrixColor(COL_BLACK));

        // --- 6. 表示更新 ---
        offscreen = matrix->SwapOnVSync(offscreen);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    delete matrix;
    return 0;
}