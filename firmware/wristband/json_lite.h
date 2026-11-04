// Tiny helpers to read fields from a flat, one-line JSON command such as
//   {"cmd":"start","exercise":"bicep_curl","set":1,"target":12}
// Enough for the band's command protocol without pulling in a JSON library.
// Plain C++ so it can be unit-tested on a PC.
#pragma once

#include <stddef.h>

// Copies the string value of `key` into `out` (always NUL-terminated). Returns false if missing.
bool jsonGetString(const char* json, const char* key, char* out, size_t outSize);

// Reads a numeric value of `key`. Returns false if missing or not a number.
bool jsonGetNumber(const char* json, const char* key, float* out);

// Reads true/false (also accepts 1/0). Returns false if missing.
bool jsonGetBool(const char* json, const char* key, bool* out);
