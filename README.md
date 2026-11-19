# Job Bot

Finds fresher-friendly jobs by city (IT, support and other roles, plus remote jobs open to India), rates each one against **your resume**, and gives a button that opens the **company's own application form**. No Naukri, LinkedIn or Indeed links in between.

It never applies for you. You check the rating, click the button, and submit the form yourself.

Your resume is read on your own computer and is never uploaded anywhere.

## Quick start (Windows)

1. Install Python from https://www.python.org/downloads/ and **tick "Add python.exe to PATH"** on the first screen.
2. Make a folder, for example `C:\jobbot`, and put these in it:
   - `job_bot.py`
   - `run_bot.bat`
   - your resume, named `resume.pdf` (or `resume.docx`)
3. Double-click `run_bot.bat`. If Windows shows "protected your PC", click **More info**, then **Run anyway**.
4. Type your cities (for example `Pune,Mumbai`) and press Enter. Press Enter again to include remote jobs, or type `N` to skip them.
5. After about a minute, `jobs.html` opens in your browser.

Run it again every morning to see new openings.

## Manual way (Command Prompt, or Mac and Linux)

```
pip install pypdf python-docx
python job_bot.py --resume resume.pdf --locations "Pune,Kolhapur,Bangalore" --remote
```

On Windows use `py` instead of `python`. Then open `jobs.html`. To preview the page with sample data: `python job_bot.py --demo`

## Using the results page

- Jobs are sorted by rating (0 to 5 stars), and each shows the resume skills it matched.
- Filter by location, job type (Tech, Support, Business, Other), rating, or remote only.
- **Apply on company site** opens the company's own form. Tick **Applied** to remember it.
- `jobs.csv` has the same list for Excel.
- The bottom panel links to official career pages (Infosys BPM, Wipro, TCS, Mphasis, WNS, Amazon and more) for employers that don't publish a feed.

## Options

| What | Option |
|---|---|
| Cities | `--locations "Pune,Mumbai"` |
| Include remote jobs | `--remote` |
| Job title keywords you accept | `--roles "support,executive,analyst"` |
| Maximum experience asked | `--max-years 1` (default 2) |
| Include senior titles | `--include-senior` |
| Show fewer or more jobs | `--min-score 40` or `--min-score 10` (default 25) |
| Add a company | write it in `companies.txt`, or use `--add-url https://company.com/careers` |

## How the rating works (out of 100, shown as stars)

| Part | Points |
|---|---|
| Resume keywords found in the job text | 45 |
| Job title fits your target roles | 15 |
| Fresher-friendly (fresher, graduate, trainee, 0 to 2 years) | 25 |
| Location match | 15 |

## Adding more companies (the best way to get more jobs)

The bot reads companies' own hiring systems (Greenhouse, Lever, Ashby, Workable, SmartRecruiters). The built-in list is only a starter, and unknown names are skipped.

Create `companies.txt` next to `job_bot.py`, one line per system:

```
greenhouse: razorpay postman
lever: cred meesho
workable: some-company
```

Or let the bot detect it: `python job_bot.py --resume resume.pdf --add-url https://company.com/careers` and copy the line it prints into `companies.txt`.

## Limits

- Many local employers (BPOs, small IT firms, shops) use their own site, WhatsApp or walk-ins, so the bot can't see them. Use the career-page panel for those.
- Ratings are keyword-based. Read each job before applying.
- The experience requirement is guessed from the text. If a job hides it, the job is kept.
- Never pay anyone for a job.

## Privacy

Don't upload your own `resume.pdf`, `jobs.html` or `jobs.csv` if you publish this project.
