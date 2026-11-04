#include "json_lite.h"

#include <stdlib.h>
#include <string.h>

namespace {

// Finds the first character of the value for "key" (after the colon and spaces).
const char* findValue(const char* json, const char* key) {
    if (json == nullptr || key == nullptr) return nullptr;
    const size_t keyLen = strlen(key);
    const char* p = json;
    while ((p = strchr(p, '"')) != nullptr) {
        const char* tokenStart = ++p;
        // walk to the closing quote of this string token
        while (*p && *p != '"') {
            if (*p == '\\' && p[1]) p++;
            p++;
        }
        if (*p != '"') return nullptr;  // unterminated string
        const size_t tokenLen = (size_t)(p - tokenStart);
        p++;  // past the closing quote

        const char* q = p;
        while (*q == ' ' || *q == '\t') q++;
        const bool isKey = (*q == ':');
        if (isKey && tokenLen == keyLen && strncmp(tokenStart, key, keyLen) == 0) {
            q++;
            while (*q == ' ' || *q == '\t') q++;
            return q;
        }
    }
    return nullptr;
}

}  // namespace

bool jsonGetString(const char* json, const char* key, char* out, size_t outSize) {
    if (out == nullptr || outSize == 0) return false;
    out[0] = '\0';
    const char* v = findValue(json, key);
    if (v == nullptr || *v != '"') return false;
    v++;
    size_t i = 0;
    while (*v && *v != '"') {
        char c = *v++;
        if (c == '\\' && *v) c = *v++;
        if (i + 1 < outSize) out[i++] = c;
    }
    out[i] = '\0';
    return *v == '"';
}

bool jsonGetNumber(const char* json, const char* key, float* out) {
    const char* v = findValue(json, key);
    if (v == nullptr) return false;
    char* end = nullptr;
    const double d = strtod(v, &end);
    if (end == v) return false;
    if (out) *out = (float)d;
    return true;
}

bool jsonGetBool(const char* json, const char* key, bool* out) {
    const char* v = findValue(json, key);
    if (v == nullptr) return false;
    if (strncmp(v, "true", 4) == 0 || *v == '1') {
        if (out) *out = true;
        return true;
    }
    if (strncmp(v, "false", 5) == 0 || *v == '0') {
        if (out) *out = false;
        return true;
    }
    return false;
}
