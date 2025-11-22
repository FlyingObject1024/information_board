本リポジトリのコードはRaspberry Pi Zero実機で動作させたもののコピーではあるものの、検証が不十分です。

# ファイル構造

~~~
/infomation_board
┣/rpi-rgb-led-matrix // ライブラリファイル群（リポジトリ段階では未配置）
┃
┣/fonts
┃　┗ Bestten-DOT.bdf       // .bdf形式の10x10フォントファイル
┃
┣/infomation_file
┃　┣ departure.json        // 発車情報
┃　┣ first_last_train.json // 始発＆終電情報
┃　┣ operation.json        // 運行情報
┃　┣ jma_forecast_raw.json // 天気情報生データ
┃　┗ weather_forecast.json // 天気
┃
┣ get_train_info.py    // 列車情報取得
┣ get_weather_info.py  // 天気情報取得
┣ draw_matrix.cc       // 表示系のプログラム
┣ json.hpp             // json解析ライブラリ
┣ MakeFile             // draw_matrix.cc コンパイル用MakeFile
┗ infomation_board.py  // メインのプログラム
~~~

# rpi-rgb-led-matrix ライブラリ リンク
hzeller/rpi-rgb-led-matrix: Controlling up to three chains of 64x64, 32x32, 16x32 or similar RGB LED displays using Raspberry Pi GPIO
https://github.com/hzeller/rpi-rgb-led-matrix

# json.hpp ライブラリ リンク
nlohmann/json: JSON for Modern C++ 
https://github.com/nlohmann/json/blob/develop/single_include/nlohmann/json.hpp

# フォント配布元
ベストテンFONT - フロップデザインフォント - BOOTH
https://booth.pm/ja/items/2747965