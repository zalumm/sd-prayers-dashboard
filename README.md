# SD Prayers Dashboard

A mobile-first prayer times dashboard for 13 masajid in San Diego, CA.

**Live site:** https://zalumm.github.io/sd-prayers-dashboard

---

## Features

- Iqamah times for 13 San Diego masajid
- Nearest masjid sorting via geolocation
- Next prayer countdown with full adhan schedule
- Jumu'ah times with session labels
- Filter by data source (Live / Published / Calculated)
- Auto-updated daily via GitHub Actions

## Masajid

| Masjid | Data Source |
|---|---|
| Muslim Community Center (MCC) | The Masjid App |
| Darululoom San Diego | The Masjid App |
| Masjid Ar-Ribat Al-Islami | Athan+ |
| Masjid Hamza — Islamic Center of Mira Mesa | Masjidal |
| Masjid Al Huda — Huda Community Center | Masjidal |
| Islamic Center of San Diego (ICSD) | Website scrape |
| Islamic Center of San Diego — East County | Website scrape |
| Masjidul Taqwa | AlAdhan calculated |
| Masjid As-Sunnah | AlAdhan calculated |
| Afghan Community Islamic Center (ACIC) | AlAdhan calculated |
| Islamic Center of El Cajon — Masjid Al-Firdaws | AlAdhan calculated |
| Islamic Center of Mid City — Masjid An-Nur | AlAdhan calculated |
| Islamic Center of Logan Heights — Masjid Omar | AlAdhan calculated |

## How It Works

```
GitHub Actions (daily 3 AM PT)
  → runs files/sd_masjid_scraper.py
  → commits updated prayer_times.json
  → GitHub Pages serves the new data
  → visitors get fresh times on next load
```

Adhan times use the ISNA calculation method via [AlAdhan API](https://aladhan.com). Iqamah times are sourced directly from each masjid's platform. Always confirm times with your local masjid.

## Manual Scrape

Go to **Actions → Update Prayer Times → Run workflow** to trigger a manual update.

## Stack

- Vanilla HTML/CSS/JS — no build step
- Python scraper (`requests` + `BeautifulSoup4`)
- GitHub Pages for hosting
- GitHub Actions for automation
