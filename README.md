```
    _   __      __  _                _____                        __          __
   / | / /___  / /_(_)___  ____     / ___/____  ____ _____  _____/ /_  ____  / /_
  /  |/ / __ \/ __/ / __ \/ __ \    \__ \/ __ \/ __ `/ __ \/ ___/ __ \/ __ \/ __/
 / /|  / /_/ / /_/ / /_/ / / / /   ___/ / / / / /_/ / /_/ (__  ) / / / /_/ / /_
/_/ |_/\____/\__/_/\____/_/ /_/   /____/_/ /_/\__,_/ .___/____/_/ /_/\____/\__/
the ultimate notion scraper                       /_/

This used to be a custom scraper until I figured out there's already a tool for that lol.
Now it's one SingleFile command plus a tiny script that expands Notion's toggles:

$ mkdir snapshot && cd snapshot
$ npx single-file-cli@2.0.75 https://sueszli.notion.site/NotionSnapshot-Test-tiny-page-4dfa05657f774b45993542da4a8530c2 \
    --browser-script=../assets/inject.js \
    --browser-height=20000 \
    --browser-wait-until=load \
    --block-fonts=true \
    --block-videos=false \
    --block-audios=false \
    --crawl-links=true \
    --crawl-max-depth=0 \
    --crawl-replace-URLs=true \
    --crawl-rewrite-rule='^(https://[^/]+/)(p/)?([^?]*).*$ $1$3' \
    --max-parallel-workers=1 \
    --filename-template='{url-last-segment}.html'

Needs Node.js and Chrome. Why the flags:

  --browser-height        notion only renders blocks near the viewport
  --browser-wait-until    notion never goes network idle
  --block-fonts           notion's css pulls in every font it has, ~8 mb per page
  --crawl-rewrite-rule    notion links each page as /<id>, /p/<id> and ?pvs=<n>
  --max-parallel-workers  more than 1 gets rate limited and silently drops pages
  cd snapshot             --crawl-replace-URLs only rewrites files in the working dir

Built on SingleFile: https://github.com/gildas-lormeau/single-file-cli
```

| <img width="685" src="assets/export.jpeg"> | <img width="685" src="assets/snapshot.jpeg"> | <img width="685" src="assets/original.jpeg"> |
| :---------------------------------------------: | :-----------------------------------------------: | :-----------------------------------------------: |
|               Export with Notion                |        Scraped with ✨NotionSnapshot✨        |                   Original page                   |
