# Makefile

# RGB LED Matrixライブラリへのパス
RGB_LIB_DISTRIBUTION=./rpi-rgb-led-matrix

# ヘッダーとライブラリのパス設定
INCDIR=$(RGB_LIB_DISTRIBUTION)/include
LIBDIR=$(RGB_LIB_DISTRIBUTION)/lib
RGB_LIBRARY_NAME=rgbmatrix
RGB_LIBRARY=$(LIBDIR)/lib$(RGB_LIBRARY_NAME).a

# コンパイラ設定
LDFLAGS+=-L$(LIBDIR) -l$(RGB_LIBRARY_NAME) -lrt -lm -lpthread
CXXFLAGS+=-I$(INCDIR) -O3 -g -Wextra -Wno-unused-parameter

# ビルドターゲット
draw_matrix: draw_matrix.o
	$(CXX) $(CXXFLAGS) draw_matrix.o -o $@ $(LDFLAGS)

draw_matrix.o: draw_matrix.cc
	$(CXX) $(CXXFLAGS) -c draw_matrix.cc

clean:
	rm -f draw_matrix.o draw_matrix