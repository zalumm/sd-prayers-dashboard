"""
San Diego Masjid Prayer Times Scraper
=======================================
Fetches live prayer/iqamah times for all 12 SD masjids and writes
a unified prayer_times.json grouped by data strategy.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROUP 1 — INTEGRATION (Masjidal / Athan+)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  These masjids are on the Masjidal platform. Times update automatically.
  Pull from their embed URL — no scraping needed.

  Al-Ribat       → Athan+ embed  timing.athanplus.com  masjid_id=VKpDmoKP ✅
  Masjid Hamza   → Masjidal widget masjidal.com/widget  masjid_id=adJq9xAk ✅
  Masjid Al Huda → Masjidal WP plugin (times rendered in homepage HTML)    ✅

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROUP 2 — SCRAPE (Static HTML on website)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  These masjids manually maintain times on their site.
  Scrape weekly/seasonally to catch updates.

  ICSD Main       → icsd.org        (Goodbricks/Wix)
  ICSD East County → icsdec.org     (Goodbricks/Wix)
  Masjidul Taqwa  → masjidultaqwasandiego.org (Jumu'ah only)
  Masjid As-Sunnah → masjidassunnahsd.com (no times yet — monitor)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROUP 3 — FALLBACK (AlAdhan calculated adhan times)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  No website or inaccessible site. AlAdhan API used for calculated
  ADHAN times only — NOT iqamah. Contact masjid for real iqamah.

  MCC San Diego   → PDF calendar only
  ACIC            → SSL expired
  Masjid Al-Firdaws → no website
  Masjid An-Nur   → no website
  Masjid Omar     → no website

Run daily via cron:
  0 1 * * * python3 /path/to/sd_masjid_scraper.py >> /path/to/scraper.log 2>&1

Config: sd_masjid_data_config.json  (master source of truth for all IDs & metadata)
Output: prayer_times.json           (generated each run, grouped by strategy)
"""

import json
import re
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────

OUTPUT_FILE = Path(__file__).parent / "prayer_times.json"
TODAY = date.today().isoformat()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# AlAdhan API — San Diego, ISNA method, Shafi asr
ALADHAN_URL = (
    "https://api.aladhan.com/v1/timingsByCity"
    "?city=San+Diego&country=US&method=2&school=0"
)

# Athan+ (Masjidal) embed URL — renders full adhan+iqamah in parseable HTML
ATHANPLUS_EMBED = "https://timing.athanplus.com/masjid/widgets/embed?theme=3&masjid_id={masjid_id}"

# Masjidal simple widget URL — also renders in parseable HTML
MASJIDAL_WIDGET = "https://masjidal.com/widget/simple/v3?masjid_id={masjid_id}"


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def fetch(url, timeout=15):
    """GET url, return response text or None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, verify=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  ✗ fetch failed: {url}\n    → {e}")
        return None


def fetch_json(url, timeout=15):
    """GET url, return parsed JSON or None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ✗ fetch_json failed: {url}\n    → {e}")
        return None


def empty_times(note=""):
    return {
        "fajr": None, "dhuhr": None, "asr": None,
        "maghrib": None, "isha": None,
        "jumuah": [], "sunrise": None,
        "source": "unavailable", "last_updated": TODAY,
        "notes": note
    }


def clean_time(raw):
    """Normalize '5:45AM' / '5:45 am' / '5:45\u202fAM' → '5:45 AM'"""
    if not raw:
        return None
    raw = str(raw).strip().upper()
    raw = raw.replace("\u202f", " ").replace("\xa0", " ").replace("\u2009", " ")
    m = re.match(r"(\d{1,2}:\d{2})\s*(AM|PM)?", raw)
    if m:
        t, mer = m.group(1), m.group(2)
        return f"{t} {mer}".strip() if mer else t
    return raw


def aladhan_fallback(note="Calculated adhan times (no iqamah data for this masjid)"):
    """AlAdhan API — calculated adhan times for San Diego."""
    data = fetch_json(ALADHAN_URL)
    if not data or data.get("code") != 200:
        return empty_times("AlAdhan API unavailable — " + note)
    t = data["data"]["timings"]
    return {
        "fajr":    clean_time(t.get("Fajr")),
        "dhuhr":   clean_time(t.get("Dhuhr")),
        "asr":     clean_time(t.get("Asr")),
        "maghrib": clean_time(t.get("Maghrib")),
        "isha":    clean_time(t.get("Isha")),
        "sunrise": clean_time(t.get("Sunrise")),
        "jumuah":  [],
        "source":  "aladhan_api_calculated",
        "last_updated": TODAY,
        "notes": note
    }


# ─────────────────────────────────────────────────────────
# Athan+ / Masjidal Live Scrapers
# ─────────────────────────────────────────────────────────

def scrape_athanplus(masjid_id, name=""):
    """
    Fetch timing.athanplus.com embed page and parse adhan + iqamah times.
    The embed renders full HTML — no JS needed.

    Confirmed working for:
      Al-Ribat → VKpDmoKP
    """
    url = ATHANPLUS_EMBED.format(masjid_id=masjid_id)
    print(f"  → Athan+ embed: {url}")
    html = fetch(url)
    if not html:
        print(f"  ⚠ Athan+ fetch failed for {masjid_id}, falling back to AlAdhan")
        return aladhan_fallback(f"Athan+ unavailable for masjid_id={masjid_id}")

    soup = BeautifulSoup(html, "lxml")

    # Grab the first day's table (today)
    # Structure: table rows with [prayer_name, STARTS_time, IQAMAH_time]
    result = empty_times()
    result["source"] = f"athanplus_live (masjid_id={masjid_id})"
    result["last_updated"] = TODAY
    result["notes"] = f"Live iqamah times via Athan+/Masjidal. masjid_id={masjid_id}"

    prayer_map = {
        "fajr": "fajr", "dhuhr": "dhuhr", "zuhr": "dhuhr",
        "asr": "asr", "maghrib": "maghrib", "isha": "isha",
        "sunrise": "sunrise"
    }

    # Find all tables — first one is today
    tables = soup.find_all("table")
    if tables:
        rows = tables[0].find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 2:
                prayer_name = cells[0].lower().strip()
                key = prayer_map.get(prayer_name)
                if key:
                    # col1 = adhan/starts, col2 = iqamah (if present)
                    adhan_time = clean_time(cells[1]) if len(cells) > 1 else None
                    iqamah_time = clean_time(cells[2]) if len(cells) > 2 else None
                    # Prefer iqamah if available, else use adhan
                    result[key] = iqamah_time if iqamah_time else adhan_time

    # Jumuah
    text = soup.get_text(" ", strip=True).upper()
    jumuah_matches = re.findall(r"JUMUAH\s+([\d:]+\s*[AP]M)", text)
    if not jumuah_matches:
        jumuah_matches = re.findall(r"JUM[^\d]*([\d:]+\s*[AP]M)", text)
    result["jumuah"] = [clean_time(t) for t in dict.fromkeys(jumuah_matches)]

    if result["fajr"] or result["isha"]:
        return result

    # If parsing produced nothing, fall back
    print(f"  ⚠ Athan+ parsing produced no times for {masjid_id}, falling back to AlAdhan")
    return aladhan_fallback(f"Athan+ parse failed for masjid_id={masjid_id}")


def scrape_masjidal_widget(masjid_id, name=""):
    """
    Fetch masjidal.com simple widget and parse prayer times from rendered HTML.

    Confirmed working for:
      Masjid Hamza → adJq9xAk
    """
    url = MASJIDAL_WIDGET.format(masjid_id=masjid_id)
    print(f"  → Masjidal widget: {url}")
    html = fetch(url)
    if not html:
        print(f"  ⚠ Masjidal widget fetch failed for {masjid_id}, falling back to AlAdhan")
        return aladhan_fallback(f"Masjidal widget unavailable for masjid_id={masjid_id}")

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True).upper()

    result = empty_times()
    result["source"] = f"masjidal_widget_live (masjid_id={masjid_id})"
    result["last_updated"] = TODAY
    result["notes"] = f"Live iqamah times via Masjidal widget. masjid_id={masjid_id}"

    prayer_map = {
        "fajr": "fajr", "dhuhr": "dhuhr", "zuhr": "dhuhr",
        "asr": "asr", "maghrib": "maghrib", "isha": "isha",
        "sunrise": "sunrise"
    }

    # Masjidal widget v3 structure per prayer:
    #   "FAJR ATHAN 4:54AM 5:30AM IQAMAH"
    # Iqamah is the time that appears immediately BEFORE the "IQAMAH" label.
    TIME_RE = r"([\d]{1,2}:[\d]{2}\s*[AP]M)"
    for prayer, key in prayer_map.items():
        # Primary: PRAYER ATHAN time time IQAMAH — capture second time (iqamah)
        pat = rf"{prayer.upper()}\s+ATHAN\s+{TIME_RE}\s+{TIME_RE}\s+IQAMAH"
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result[key] = clean_time(m.group(2))
            continue
        # Fallback A: time immediately before IQAMAH, within prayer block
        pat2 = rf"{prayer.upper()}.*?{TIME_RE}\s+IQAMAH"
        m2 = re.search(pat2, text, re.IGNORECASE | re.DOTALL)
        if m2:
            result[key] = clean_time(m2.group(1))
            continue
        # Fallback B: any time after prayer name
        pat3 = rf"{prayer.upper()}[^0-9]*?{TIME_RE}"
        m3 = re.search(pat3, text, re.IGNORECASE)
        if m3:
            result[key] = clean_time(m3.group(1))

    # Jumu'ah — Masjidal widget shows times around the JUMU'AH label:
    #   "1:15PM JUMU'AH 2:15PM SUNRISE"
    # Capture time immediately before AND immediately after the label.
    jumuah_times = []
    m_before = re.search(rf"{TIME_RE}\s+JUM(?:U|')?AH", text, re.IGNORECASE)
    if m_before:
        jumuah_times.append(clean_time(m_before.group(1)))
    m_after = re.search(r"JUM(?:U|')?AH\s+" + TIME_RE, text, re.IGNORECASE)
    if m_after:
        t = clean_time(m_after.group(1))
        if t and t not in jumuah_times:
            jumuah_times.append(t)
    result["jumuah"] = jumuah_times

    if result["fajr"] or result["isha"]:
        return result

    print(f"  ⚠ Masjidal widget parse produced no times for {masjid_id}, falling back to AlAdhan")
    return aladhan_fallback(f"Masjidal widget parse failed for masjid_id={masjid_id}")


# ─────────────────────────────────────────────────────────
# HTML Scrapers (static sites)
# ─────────────────────────────────────────────────────────

def scrape_icsd():
    """ICSD Main — Goodbricks/Wix static HTML, times in plain text."""
    print("  → Scraping icsd.org...")
    html = fetch("https://www.icsd.org")
    if not html:
        return aladhan_fallback("ICSD site unavailable")

    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True).upper()
    result = empty_times()
    result["source"] = "scraped_icsd.org"
    result["last_updated"] = TODAY

    patterns = {
        "fajr":    r"FAJR[:\s]+([^\n]{3,40}?)(?=DHUHR|ASR|MAGHRIB|ISHA|JUMUAH|$)",
        "dhuhr":   r"DHUHR[:\s]+([\d:]+\s*[AP]M)",
        "asr":     r"ASR[:\s]+([\d:]+\s*[AP]M)",
        "maghrib": r"MAGHRIB[:\s]+([^\n]{3,40}?)(?=ISHA|JUMUAH|$)",
        "isha":    r"ISHA[:\s]+([\d:]+\s*[AP]M)",
    }
    for prayer, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result[prayer] = m.group(1).strip()

    jumuah = re.findall(r"(?:1ST|2ND)\s+JUMUAH[:\s]+([\d:]+\s*[AP]M)", text)
    result["jumuah"] = [clean_time(t) for t in jumuah]
    result["notes"] = "Iqamah times manually maintained by ICSD — updated seasonally"
    return result


def scrape_icsd_ec():
    """
    ICSD East County — Goodbricks/Wix static HTML.
    Full iqamah schedule:
      Fajr 5:45 AM · Dhuhr 1:15 PM · Asr 4:45 PM
      Maghrib 5 mins after sunset · Isha 8:45 PM
    4 Jumu'ah khutbah sessions (20 min each including prayer):
      11:30 AM (Arabic) · 12:15 PM (English) · 1:00 PM (Arabic) · 1:45 PM (English)
    """
    print("  → Scraping icsdec.org...")
    html = fetch("https://www.icsdec.org")
    if not html:
        return aladhan_fallback("ICSD East County site unavailable")

    # Strip zero-width spaces and other invisible Unicode before parsing
    raw = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    raw = re.sub(r"[\u200b\u200c\u200d\u00ad\u2060\ufeff]", "", raw)
    text = raw.upper()

    result = empty_times()
    result["source"] = "scraped_icsdec.org"
    result["last_updated"] = TODAY

    # ── Daily iqamah times ─────────────────────────────────────────
    prayer_patterns = {
        "fajr":    r"FAJR[^\d]*([\d:]+\s*[AP]M)",
        "dhuhr":   r"(?:DHUHR|ZUHR)[^\d]*([\d:]+\s*[AP]M)",
        "asr":     r"ASR[^\d]*([\d:]+\s*[AP]M)",
        "maghrib": r"MAGHRIB[^\d]*(\d+\s*MINS?\s*AFTER\s*SUNSET|[\d:]+\s*[AP]M)",
        "isha":    r"ISHA[^\d A-Z]*([\d:]+\s*[AP]M)",
    }
    for prayer, pat in prayer_patterns.items():
        m = re.search(pat, text)
        if m:
            result[prayer] = clean_time(m.group(1)) if re.search(r"\d+:\d+", m.group(1)) else m.group(1).strip().title()

    # ── 4 Jumu'ah / Khutbah sessions ──────────────────────────────
    # Strategy A: labeled "(IN ARABIC)" / "(IN ENGLISH)" after the time
    jumuah = re.findall(r"([\d:]+\s*[AP]M)\s*\(IN\s*(?:ARABIC|ENGLISH)\)", text)
    # Strategy B: times after "KHUTBAH" keyword (handles "1ST KHUTBAH: 11:30 AM")
    if not jumuah:
        jumuah = re.findall(r"(?:\d+(?:ST|ND|RD|TH)\s+)?KHUTBAH[:\s]*([\d:]+\s*[AP]M)", text)
    # Strategy C: any time between 11 AM–2 PM near "FRIDAY" keyword (last resort)
    if not jumuah:
        block = re.search(r"FRIDAY.*?(?=\n\n|\Z)", text, re.DOTALL)
        if block:
            jumuah = re.findall(r"([\d:]+\s*[AP]M)", block.group(0))

    result["jumuah"] = [clean_time(t) for t in dict.fromkeys(jumuah)]

    # ── Static fallback if site changes layout ─────────────────────
    if not result["fajr"] and not result["dhuhr"]:
        result.update({
            "fajr": "5:45 AM", "dhuhr": "1:15 PM", "asr": "4:45 PM",
            "maghrib": "5 mins after sunset", "isha": "8:45 PM",
            "source": "scraped_icsdec.org (static fallback)",
        })
    if not result["jumuah"]:
        result["jumuah"] = ["11:30 AM", "12:15 PM", "1:00 PM", "1:45 PM"]

    result["notes"] = (
        "ICSD East County — full iqamah schedule. "
        "4 Jumu'ah khutbah sessions (20 min each including prayer): "
        "Arabic at 11:30 AM & 1:00 PM; English at 12:15 PM & 1:45 PM."
    )
    return result


def scrape_taqwa():
    """Masjidul Taqwa — custom HTML site, Jumu'ah only."""
    print("  → Scraping masjidultaqwasandiego.org...")
    html = fetch("https://www.masjidultaqwasandiego.org")
    if not html:
        return aladhan_fallback("Masjidul Taqwa site unavailable")

    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True).upper()
    result = empty_times()
    result["source"] = "scraped_masjidultaqwasandiego.org"
    result["last_updated"] = TODAY

    for prayer, pat in {
        "fajr":    r"FAJR[^\d]*([\d:]+\s*[AP]M)",
        "dhuhr":   r"(?:DHUHR|ZUHR)[^\d]*([\d:]+\s*[AP]M)",
        "asr":     r"ASR[^\d]*([\d:]+\s*[AP]M)",
        "maghrib": r"MAGHRIB[^\d]*([\d:]+\s*[AP]M)",
        "isha":    r"ISHA[^\d]*([\d:]+\s*[AP]M)",
    }.items():
        m = re.search(pat, text)
        if m:
            result[prayer] = clean_time(m.group(1))

    m = re.search(r"JUM(?:U|\')?AH[^\d]*([\d:]+)", text)
    result["jumuah"] = [clean_time(m.group(1)) + " PM"] if m else ["1:00 PM"]
    result["notes"] = "Jumu'ah 1:00–1:30 PM. Full daily schedule via iOS Taqwa App."
    return result


def scrape_huda():
    """
    Masjid Al Huda — WordPress + Masjidal plugin.
    Masjidal renders full adhan+iqamah times directly in the page HTML.
    No masjid_id needed — parse times from the rendered output.
    """
    print("  → Scraping hudacommunitycenter.org (Masjidal plugin HTML)...")
    html = fetch("http://hudacommunitycenter.org")
    if not html:
        return aladhan_fallback("Huda Community Center site unavailable")

    soup = BeautifulSoup(html, "lxml")

    result = empty_times()
    result["source"] = "scraped_hudacommunitycenter.org (Masjidal plugin)"
    result["last_updated"] = TODAY
    result["notes"] = "Live iqamah times scraped from Masjidal WordPress plugin rendered HTML"

    # The plugin renders list items like:
    # <img src="d_fajr.png"> Fajr \n 5:15 AM  5:45 AM
    # We grab all text and parse with regex
    text = soup.get_text(" ", strip=True).upper()

    prayer_map = {
        "FAJR": "fajr", "DHUHR": "dhuhr", "ASR": "asr",
        "MAGHRIB": "maghrib", "ISHA": "isha"
    }

    for label, key in prayer_map.items():
        # Pattern: PRAYER_NAME adhan_time iqamah_time (two consecutive times)
        pat = rf"{label}\s+([\d:]+\s*[AP]M)\s*([\d:]+\s*[AP]M)?"
        m = re.search(pat, text)
        if m:
            # Prefer second time (iqamah), fallback to first (adhan)
            result[key] = clean_time(m.group(2)) if m.group(2) else clean_time(m.group(1))

    # Jumu'ah
    khutbah = re.search(r"KHUTBAH\s+([\d:]+\s*[AP]M)", text)
    jumuah_prayer = re.search(r"JUM[^\d]*([\d:]+\s*[AP]M)", text)
    result["jumuah"] = []
    if khutbah:
        result["jumuah"].append(f"Khutbah: {clean_time(khutbah.group(1))}")
    if jumuah_prayer:
        result["jumuah"].append(f"Prayer: {clean_time(jumuah_prayer.group(1))}")

    if result["fajr"] or result["isha"]:
        return result

    # If nothing parsed, fall back
    print("  ⚠ Huda HTML parse produced no times, falling back to AlAdhan")
    return aladhan_fallback("Huda site parse failed — Masjidal plugin may have changed")


def scrape_sunnah():
    """Masjid As-Sunnah — Astro static site, no prayer times. AlAdhan fallback."""
    print("  → Checking masjidassunnahsd.com for prayer times...")
    html = fetch("https://www.masjidassunnahsd.com")
    if html:
        text = BeautifulSoup(html, "lxml").get_text(" ", strip=True).upper()
        found = {}
        for prayer, pat in {
            "fajr":    r"FAJR[^\d]*([\d:]+\s*[AP]M)",
            "dhuhr":   r"(?:DHUHR|ZUHR)[^\d]*([\d:]+\s*[AP]M)",
            "asr":     r"ASR[^\d]*([\d:]+\s*[AP]M)",
            "maghrib": r"MAGHRIB[^\d]*([\d:]+\s*[AP]M)",
            "isha":    r"ISHA[^\d]*([\d:]+\s*[AP]M)",
        }.items():
            m = re.search(pat, text)
            if m:
                found[prayer] = clean_time(m.group(1))

        if found:
            result = empty_times()
            result.update(found)
            result["source"] = "scraped_masjidassunnahsd.com"
            result["last_updated"] = TODAY
            result["notes"] = "Prayer times scraped from masjidassunnahsd.com"
            return result

    return aladhan_fallback(
        "No prayer times on masjidassunnahsd.com — showing calculated adhan. "
        "Contact: (619) 535-8340 or @masjidassunnahsd"
    )


def scrape_darululoom():
    """
    Darululoom San Diego (Crescent Academy) — The Masjid App (claimed, live iqamah).
    URL: https://themasjidapp.org/195/prayers
    3 Jumu'ah sessions each with separate adhan + iqamah times.
    """
    print("  → Fetching themasjidapp.org/195/prayers (Darululoom SD)...")
    html = fetch("https://themasjidapp.org/195/prayers")
    if not html:
        return aladhan_fallback("Darululoom The Masjid App unavailable")

    soup = BeautifulSoup(html, "lxml")
    result = empty_times()
    result["source"] = "themasjidapp_live (id=195)"
    result["last_updated"] = TODAY
    result["notes"] = "Live iqamah times via The Masjid App (Darululoom claimed, staff-managed). 3 Jumu'ah sessions."

    prayer_map = {
        "fajr": "fajr", "dhuhr": "dhuhr", "asr": "asr",
        "maghrib": "maghrib", "isha": "isha", "sunrise": "sunrise"
    }

    rows = soup.find_all("tr")
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) >= 2:
            name = cells[0].lower().strip()
            key = prayer_map.get(name)
            if key:
                begins = clean_time(cells[1]) if len(cells) > 1 else None
                iqama  = clean_time(cells[2]) if len(cells) > 2 else None
                result[key] = iqama if iqama and iqama != "—" else begins

    # Jumu'ah — 3 sessions: "1:00PM, 1:55PM, 3:00PM  Iqamah 01:15 PM, Iqamah 02:15 PM, Iqamah 03:20 PM"
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Jumuah\s+(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        raw = m.group(1)
        iqamah_times = re.findall(r"Iqamah\s+([\d:]+\s*[AP]M)", raw, re.IGNORECASE)
        if iqamah_times:
            result["jumuah"] = [clean_time(t) for t in iqamah_times]
        else:
            adhan_times = re.findall(r"[\d:]+\s*[AP]M", raw, re.IGNORECASE)
            result["jumuah"] = [clean_time(t) for t in adhan_times]

    if result["fajr"] or result["isha"]:
        return result

    print("  ⚠ Darululoom Masjid App parse produced no times, falling back to AlAdhan")
    return aladhan_fallback("Darululoom Masjid App parse failed")


def scrape_mcc():
    """
    MCC San Diego — The Masjid App (claimed, live iqamah).
    URL: https://themasjidapp.org/198/prayers
    Returns a clean HTML table: | Begins | Iqama | per prayer.
    """
    print("  → Fetching themasjidapp.org/198/prayers (MCC)...")
    html = fetch("https://themasjidapp.org/198/prayers")
    if not html:
        return aladhan_fallback("MCC The Masjid App unavailable")

    soup = BeautifulSoup(html, "lxml")
    result = empty_times()
    result["source"] = "themasjidapp_live (id=198)"
    result["last_updated"] = TODAY
    result["notes"] = "Live iqamah times via The Masjid App (MCC claimed, staff-managed)"

    prayer_map = {
        "fajr": "fajr", "dhuhr": "dhuhr", "asr": "asr",
        "maghrib": "maghrib", "isha": "isha", "sunrise": "sunrise"
    }

    # Table rows: prayer name | Begins time | Iqama time
    rows = soup.find_all("tr")
    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) >= 2:
            name = cells[0].lower().strip()
            key = prayer_map.get(name)
            if key:
                begins = clean_time(cells[1]) if len(cells) > 1 else None
                iqama  = clean_time(cells[2]) if len(cells) > 2 else None
                result[key] = iqama if iqama and iqama != "—" else begins

    # Jumu'ah — appears as bold text "Jumuah | 1:00PM, 2:00PM"
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Jumuah\s+([\d:]+\s*[AP]M.*?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        times = re.findall(r"[\d:]+\s*[AP]M", m.group(1), re.IGNORECASE)
        result["jumuah"] = [clean_time(t) for t in times]

    if result["fajr"] or result["isha"]:
        return result

    print("  ⚠ MCC Masjid App parse produced no times, falling back to AlAdhan")
    return aladhan_fallback("MCC Masjid App parse failed")


# ─────────────────────────────────────────────────────────
# Masjid Registry
# ─────────────────────────────────────────────────────────

MASJIDS = [
    # ── GROUP 1: INTEGRATION ──────────────────────────────────
    {
        "id": "darululoom_sd",
        "group": "integration",
        "name": "Darululoom San Diego (Crescent Academy)",
        "address": "6916 Miramar Rd, San Diego, CA 92121",
        "phone": "(858) 610-6626",
        "website": "https://darululoomsd.themasjidapp.org",
        "platform": "The Masjid App",
        "platform_id": 195,            # ✅ CONFIRMED — themasjidapp.org/195/prayers
        "masjidal_id": None,
        "scraper": scrape_darululoom,
    },
    {
        "id": "mcc_sandiego",
        "group": "integration",
        "name": "Muslim Community Center of Greater San Diego (MCC)",
        "address": "14698 Via Fiesta, San Diego, CA 92127",
        "phone": "(858) 756-5100",
        "website": "https://mccsandiego.org",
        "platform": "The Masjid App",
        "platform_id": 198,            # ✅ CONFIRMED — themasjidapp.org/198/prayers
        "masjidal_id": None,
        "scraper": scrape_mcc,
    },
    {
        "id": "alribat",
        "group": "integration",
        "name": "Al-Ribat Mosque (Masjid Ar-Ribat Al-Islami)",
        "address": "7173 Saranac St, San Diego, CA 92115",
        "phone": "(619) 589-6200",
        "website": "https://masjidribat.com",
        "masjidal_id": "VKpDmoKP",    # ✅ CONFIRMED — timing.athanplus.com
        "scraper": lambda: scrape_athanplus("VKpDmoKP", "Al-Ribat"),
    },
    {
        "id": "masjid_hamza",
        "group": "integration",
        "name": "Islamic Center of Mira Mesa (Masjid Hamza)",
        "address": "9625 Black Mountain Rd #204, San Diego, CA 92126",
        "phone": "(619) 571-2988",
        "website": "https://www.masjidhamzasandiego.com",
        "masjidal_id": "adJq9xAk",   # ✅ CONFIRMED — <a href> in page HTML
        "scraper": lambda: scrape_masjidal_widget("adJq9xAk", "Masjid Hamza"),
    },
    {
        "id": "masjid_alhuda",
        "group": "integration",
        "name": "Masjid Al Huda (Huda Community Center)",
        "address": "4175 Bonillo Dr, San Diego, CA 92115",
        "phone": "(619) 229-9300",
        "website": "http://hudacommunitycenter.org",
        "masjidal_id": "unknown",  # ID in PHP only — times scraped from rendered page HTML
        "scraper": scrape_huda,
    },

    # ── GROUP 2: SCRAPE ───────────────────────────────────────
    {
        "id": "icsd_main",
        "group": "scrape",
        "name": "Islamic Center of San Diego (ICSD)",
        "address": "7050 Eckstrom Ave, San Diego, CA 92111",
        "phone": "(858) 278-5240",
        "website": "https://www.icsd.org",
        "masjidal_id": None,
        "scraper": scrape_icsd,
    },
    {
        "id": "icsd_ec",
        "group": "scrape",
        "name": "Islamic Center of San Diego East County",
        "address": "833 Broadway, El Cajon, CA 92021",
        "phone": "(619) 631-7477",
        "website": "https://www.icsdec.org",
        "masjidal_id": None,
        "scraper": scrape_icsd_ec,
    },
    {
        "id": "masjidul_taqwa",
        "group": "scrape",
        "name": "Masjidul Taqwa",
        "address": "2575 Imperial Ave, San Diego, CA 92102",
        "phone": "(619) 239-6738",
        "website": "https://www.masjidultaqwasandiego.org",
        "masjidal_id": None,
        "scraper": scrape_taqwa,
    },
    {
        "id": "masjid_assunnah",
        "group": "scrape",
        "name": "Masjid As-Sunnah",
        "address": "4758 Federal Blvd, San Diego, CA 92102",
        "phone": "(619) 535-8340",
        "website": "https://www.masjidassunnahsd.com",
        "masjidal_id": None,
        "scraper": scrape_sunnah,
    },

    # ── GROUP 3: FALLBACK ─────────────────────────────────────
    {
        "id": "acic",
        "group": "fallback",
        "name": "Afghan Community Islamic Center (ACIC)",
        "address": "3333 Sandrock Rd, San Diego, CA 92123",
        "phone": "(858) 560-9191",
        "website": "https://acicmasjidtawheed.com",
        "masjidal_id": None,
        "scraper": lambda: aladhan_fallback("ACIC site SSL expired — using calculated times"),
    },
    {
        "id": "masjid_alfirdaws",
        "group": "fallback",
        "name": "Islamic Center of El Cajon (Masjid Al-Firdaws)",
        "address": "557 El Cajon Blvd, El Cajon, CA 92020",
        "phone": "(619) 571-2988",
        "website": None,
        "masjidal_id": None,
        "scraper": lambda: aladhan_fallback("No website — using calculated adhan times"),
    },
    {
        "id": "masjid_annur",
        "group": "fallback",
        "name": "Islamic Center of Mid City (Masjid An-Nur)",
        "address": "3872 50th St, San Diego, CA 92105",
        "phone": "(619) 571-2988",
        "website": None,
        "masjidal_id": None,
        "scraper": lambda: aladhan_fallback("No website — using calculated adhan times"),
    },
    {
        "id": "masjid_omar",
        "group": "fallback",
        "name": "Islamic Center of Logan Heights (Masjid Omar)",
        "address": "3487 Ocean View Blvd, San Diego, CA 92113",
        "phone": "(619) 571-2988",
        "website": None,
        "masjidal_id": None,
        "scraper": lambda: aladhan_fallback("No website — using calculated adhan times"),
    },
]


# ─────────────────────────────────────────────────────────
# Main Runner
# ─────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*60}")
    print(f"  SD Masjid Prayer Times Scraper — {TODAY}")
    print(f"{'='*60}\n")

    # ── Groups mirror sd_masjid_data_config.json ──
    groups = {
        "integration": {
            "_label": "LIVE INTEGRATION — Masjidal / Athan+ platform",
            "_note": "Times managed by masjid admins, update automatically. No scraping needed.",
            "masjids": []
        },
        "scrape": {
            "_label": "SCRAPED — Static HTML on website",
            "_note": "Times manually maintained on site. Scraped weekly/seasonally.",
            "masjids": []
        },
        "fallback": {
            "_label": "FALLBACK — AlAdhan calculated adhan times",
            "_note": "No website or inaccessible. These are calculated ADHAN times, NOT iqamah. Contact masjid for real iqamah.",
            "masjids": []
        }
    }

    for m in MASJIDS:
        group_key = m["group"]
        label = {
            "integration": "🟢 INTEGRATION",
            "scrape":      "🟡 SCRAPE",
            "fallback":    "🔴 FALLBACK"
        }[group_key]

        print(f"{label} → {m['name']}")
        try:
            times = m["scraper"]()
        except Exception as e:
            print(f"  ✗ Scraper crashed: {e}")
            traceback.print_exc()
            times = empty_times(f"Scraper error: {e}")

        entry = {
            "id":           m["id"],
            "name":         m["name"],
            "address":      m["address"],
            "phone":        m["phone"],
            "website":      m.get("website"),
            "data_group":   group_key,
            "masjidal_id":  m.get("masjidal_id"),
            "timings":      times,
        }
        groups[group_key]["masjids"].append(entry)

        t = times
        print(f"  Fajr:{t['fajr']}  Dhuhr:{t['dhuhr']}  "
              f"Asr:{t['asr']}  Maghrib:{t['maghrib']}  Isha:{t['isha']}")
        print(f"  Jumu'ah:{t['jumuah']}  [source:{t['source']}]\n")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": TODAY,
        "summary": {
            "total": sum(len(g["masjids"]) for g in groups.values()),
            "integration_count": len(groups["integration"]["masjids"]),
            "scrape_count":      len(groups["scrape"]["masjids"]),
            "fallback_count":    len(groups["fallback"]["masjids"]),
        },
        "groups": groups
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  🟢 Integration : {output['summary']['integration_count']} masjids")
    print(f"  🟡 Scrape      : {output['summary']['scrape_count']} masjids")
    print(f"  🔴 Fallback    : {output['summary']['fallback_count']} masjids")
    print(f"  Total          : {output['summary']['total']} masjids")
    print(f"\n✅ Saved → {OUTPUT_FILE}\n")
    return output


if __name__ == "__main__":
    run()
