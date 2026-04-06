#pragma once
// Zaya OS Kernel JSON — minimal read/write JSON for kernel modules
// No external dependencies. Supports objects, arrays, strings, numbers, bools, null.

#include <string>
#include <vector>
#include <map>
#include <variant>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <cmath>

namespace zaya {

struct JVal;
using JObject = std::map<std::string, JVal>;
using JArray  = std::vector<JVal>;

struct JVal : std::variant<std::nullptr_t, bool, double, std::string, JArray, JObject> {
    using variant::variant;

    bool is_null()   const { return std::holds_alternative<std::nullptr_t>(*this); }
    bool is_bool()   const { return std::holds_alternative<bool>(*this); }
    bool is_number() const { return std::holds_alternative<double>(*this); }
    bool is_string() const { return std::holds_alternative<std::string>(*this); }
    bool is_array()  const { return std::holds_alternative<JArray>(*this); }
    bool is_object() const { return std::holds_alternative<JObject>(*this); }

    const std::string& str()    const { return std::get<std::string>(*this); }
    double             num()    const { return std::get<double>(*this); }
    int                integer()const { return static_cast<int>(std::get<double>(*this)); }
    bool               boolean()const { return std::get<bool>(*this); }
    const JArray&      arr()    const { return std::get<JArray>(*this); }
    JArray&            arr()          { return std::get<JArray>(*this); }
    const JObject&     obj()    const { return std::get<JObject>(*this); }
    JObject&           obj()          { return std::get<JObject>(*this); }

    // Get with default
    const JVal& get(const std::string& key, const JVal& def) const {
        if (!is_object()) return def;
        auto it = obj().find(key);
        return it != obj().end() ? it->second : def;
    }

    const JVal& operator[](const std::string& key) const {
        return std::get<JObject>(*this).at(key);
    }

    bool has(const std::string& key) const {
        if (!is_object()) return false;
        return obj().count(key) > 0;
    }
};

// ─── Parser ─────────────────────────────────────────────

namespace detail {

inline void skip_ws(const std::string& s, size_t& i) {
    while (i < s.size() && std::isspace(s[i])) i++;
}

inline std::string parse_str(const std::string& s, size_t& i) {
    i++; // skip "
    std::string out;
    while (i < s.size() && s[i] != '"') {
        if (s[i] == '\\') {
            i++;
            if (i < s.size()) {
                switch (s[i]) {
                    case '"': case '\\': case '/': out += s[i]; break;
                    case 'n': out += '\n'; break;
                    case 't': out += '\t'; break;
                    case 'r': out += '\r'; break;
                    default: out += s[i]; break;
                }
            }
        } else {
            out += s[i];
        }
        i++;
    }
    if (i < s.size()) i++; // skip closing "
    return out;
}

inline JVal parse_val(const std::string& s, size_t& i);

inline JVal parse_obj(const std::string& s, size_t& i) {
    i++; // skip {
    JObject obj;
    skip_ws(s, i);
    if (i < s.size() && s[i] == '}') { i++; return obj; }
    while (i < s.size()) {
        skip_ws(s, i);
        std::string key = parse_str(s, i);
        skip_ws(s, i);
        if (i < s.size() && s[i] == ':') i++;
        skip_ws(s, i);
        obj[key] = parse_val(s, i);
        skip_ws(s, i);
        if (i < s.size() && s[i] == ',') { i++; continue; }
        if (i < s.size() && s[i] == '}') { i++; break; }
    }
    return obj;
}

inline JVal parse_arr(const std::string& s, size_t& i) {
    i++; // skip [
    JArray arr;
    skip_ws(s, i);
    if (i < s.size() && s[i] == ']') { i++; return arr; }
    while (i < s.size()) {
        skip_ws(s, i);
        arr.push_back(parse_val(s, i));
        skip_ws(s, i);
        if (i < s.size() && s[i] == ',') { i++; continue; }
        if (i < s.size() && s[i] == ']') { i++; break; }
    }
    return arr;
}

inline JVal parse_val(const std::string& s, size_t& i) {
    skip_ws(s, i);
    if (i >= s.size()) return nullptr;
    if (s[i] == '"') return parse_str(s, i);
    if (s[i] == '{') return parse_obj(s, i);
    if (s[i] == '[') return parse_arr(s, i);
    if (s[i] == 't') { i += 4; return true; }
    if (s[i] == 'f') { i += 5; return false; }
    if (s[i] == 'n') { i += 4; return nullptr; }
    // number
    size_t start = i;
    if (s[i] == '-') i++;
    while (i < s.size() && (std::isdigit(s[i]) || s[i] == '.' || s[i] == 'e' || s[i] == 'E' || s[i] == '+' || s[i] == '-')) i++;
    return std::stod(s.substr(start, i - start));
}

} // namespace detail

inline JVal json_parse(const std::string& s) {
    size_t i = 0;
    return detail::parse_val(s, i);
}

// ─── Serializer ─────────────────────────────────────────

inline std::string json_dump(const JVal& v, int indent = -1, int depth = 0) {
    auto pad = [&](int d) -> std::string {
        return indent < 0 ? "" : std::string(d * indent, ' ');
    };
    auto nl = [&]() -> std::string { return indent < 0 ? "" : "\n"; };
    auto sp = [&]() -> std::string { return indent < 0 ? "" : " "; };

    if (v.is_null()) return "null";
    if (v.is_bool()) return v.boolean() ? "true" : "false";
    if (v.is_number()) {
        double d = v.num();
        if (d == std::floor(d) && std::abs(d) < 1e15)
            return std::to_string(static_cast<long long>(d));
        char buf[64];
        snprintf(buf, sizeof(buf), "%.6g", d);
        return buf;
    }
    if (v.is_string()) {
        std::string out = "\"";
        for (char c : v.str()) {
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\t': out += "\\t"; break;
                case '\r': out += "\\r"; break;
                default: out += c;
            }
        }
        return out + "\"";
    }
    if (v.is_array()) {
        const auto& a = v.arr();
        if (a.empty()) return "[]";
        std::string out = "[" + nl();
        for (size_t i = 0; i < a.size(); i++) {
            out += pad(depth + 1) + json_dump(a[i], indent, depth + 1);
            if (i + 1 < a.size()) out += ",";
            out += nl();
        }
        return out + pad(depth) + "]";
    }
    if (v.is_object()) {
        const auto& o = v.obj();
        if (o.empty()) return "{}";
        std::string out = "{" + nl();
        size_t idx = 0;
        for (const auto& [k, val] : o) {
            out += pad(depth + 1) + "\"" + k + "\":" + sp() + json_dump(val, indent, depth + 1);
            if (++idx < o.size()) out += ",";
            out += nl();
        }
        return out + pad(depth) + "}";
    }
    return "null";
}

// ─── File I/O ───────────────────────────────────────────

inline JVal json_load_file(const std::string& path) {
    std::ifstream f(path);
    if (!f) return JObject{};
    std::stringstream ss;
    ss << f.rdbuf();
    return json_parse(ss.str());
}

inline void json_save_file(const std::string& path, const JVal& v) {
    std::ofstream f(path);
    f << json_dump(v, 2);
}

} // namespace zaya
