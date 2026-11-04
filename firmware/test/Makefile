# PC unit tests for the band's plain-C++ code.
#   make -C firmware/test        build and run
SRC = test_main.cpp ../wristband/rep_detector.cpp ../wristband/json_lite.cpp ../wristband/exercise_table.cpp
CXXFLAGS = -std=c++17 -Wall -Wextra -O1

run: test_runner
	./test_runner

test_runner: $(SRC) ../wristband/*.h
	$(CXX) $(CXXFLAGS) -o $@ $(SRC) -lm

clean:
	rm -f test_runner test_runner.exe

.PHONY: run clean
