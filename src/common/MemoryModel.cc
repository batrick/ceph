#include "debug.h"

#include "include/compat.h"

#include "MemoryModel.h"
#if defined(__linux__)
#include <malloc.h>
#endif

#include <charconv>

#include "common/fmt_common.h"


#define dout_subsys ceph_subsys_

using namespace std;
using mem_snap_t = MemoryModel::mem_snap_t;

MemoryModel::MemoryModel(CephContext *cct_) : cct(cct_) {}

inline bool MemoryModel::cmp_against(
    const std::string &ln,
    std::string_view param,
    long &v) const
{
  if (ln.size() < (param.size() + 10)) {
    return false;
  }
  if (ln.starts_with(param)) {
    auto p = ln.c_str();
    auto s = p + param.size();
    // charconv does not like leading spaces
    while (*s && isblank(*s)) {
      s++;
    }
    from_chars(s, p + ln.size(), v);
    return true;
  }
  return false;
}


std::optional<int64_t> MemoryModel::get_mapped_heap()
{
  if (!proc_maps.is_open()) {
    ldout(cct, 0) << fmt::format(
			 "MemoryModel::get_mapped_heap() unable to open {}",
			 proc_maps_fn)
		  << dendl;
    return std::nullopt;
  }
  // always rewind before reading
  proc_maps.clear();
  proc_maps.seekg(0);

  int64_t heap = 0;

  while (proc_maps.is_open() && !proc_maps.eof()) {
    string line;
    getline(proc_maps, line);

    const char *start = line.c_str();
    const char *dash = start;
    while (*dash && *dash != '-')
      dash++;
    if (!*dash)
      continue;
    const char *end = dash + 1;
    while (*end && *end != ' ')
      end++;
    if (!*end)
      continue;
    unsigned long long as = strtoll(start, 0, 16);
    unsigned long long ae = strtoll(dash + 1, 0, 16);

    end++;
    const char *mode = end;

    int skip = 4;
    while (skip--) {
      end++;
      while (*end && *end != ' ')
	end++;
    }
    if (*end)
      end++;

    long size = ae - as;

    /*
     * anything 'rw' and anon is assumed to be heap.
     */
    if (mode[0] == 'r' && mode[1] == 'w' && !*end)
      heap += size;
  }

  return heap;
}


std::optional<mem_snap_t> MemoryModel::full_sample()
{
  if (!proc_status.is_open()) {
    ldout(cct, 0) << fmt::format(
			 "MemoryModel::sample() unable to open {}",
			 proc_stat_fn)
		  << dendl;
    return std::nullopt;
  }
  // always rewind before reading
  proc_status.clear();
  proc_status.seekg(0);

  mem_snap_t s;
  // we will be looking for 6 entries
  int yet_to_find = 6;

  while (!proc_status.eof() && yet_to_find > 0) {
    string ln;
    getline(proc_status, ln);

    if (cmp_against(ln, "VmSize:", s.size) ||
	cmp_against(ln, "VmRSS:", s.rss) || cmp_against(ln, "VmHWM:", s.hwm) ||
	cmp_against(ln, "VmLib:", s.lib) ||
	cmp_against(ln, "VmPeak:", s.peak) ||
	cmp_against(ln, "VmData:", s.data)) {
      yet_to_find--;
    }
  }

  // get heap size
  s.heap = static_cast<long>(get_mapped_heap().value_or(0));
  return s;
}

void MemoryModel::sample(mem_snap_t *p)
{
  auto s = full_sample();
  if (s) {
    last = *s;
    if (p)
      *p = last;
  }
}
