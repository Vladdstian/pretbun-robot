# pretbun-robot

The daily price collector for Lista Bună, a family app that compares grocery prices in Romania.

It reads the public price data that retailers report to **Monitorul Prețurilor** (monitorulpreturilor.info), the official price-comparison service. A few online shops and delivery apps are read only where their terms and robots.txt allow it.

- **Pacing:** one request at a time, with at least a second between requests, and an honest User-Agent.
- **What it does:** places products in general items ("Unt 82%"), keeps only changed prices, and saves daily files to the app's private storage.
- **What isn't here:** the app, its accounts and its users' data are not in this repository.

Runs on GitHub Actions: `.github/workflows/robot.yml`.
