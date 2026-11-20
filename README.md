```
             __  _                                  __        __
  ___  ___  / /_(_)__  ___  ___ ___  ___ ____  ___ / /  ___  / /_
 / _ \/ _ \/ __/ / _ \/ _ \(_-</ _ \/ _ `/ _ \(_-</ _ \/ _ \/ __/
/_//_/\___/\__/_/\___/_//_/___/_//_/\_,_/ .__/___/_//_/\___/\__/
offline copies of public notion pages  /_/


this used to be a custom scraper until i found singlefile,
which already renders, inlines and crawls pages.
what's left is a small script that expands notion's toggles.


usage:

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

needs node.js and chrome.


why the flags:

    --browser-height        notion only renders blocks near the viewport
    --browser-wait-until    notion never goes network idle
    --block-fonts           notion's css pulls in every font, ~8 mb per page
    --crawl-rewrite-rule    notion links pages as /<id>, /p/<id> and ?pvs=<n>
    --max-parallel-workers  more get rate limited and silently drop pages
    cd snapshot             --crawl-replace-URLs only rewrites the working dir


references:

- singlefile: https://github.com/gildas-lormeau/single-file-cli
```

| <img width="685" src="assets/export.jpeg"> | <img width="685" src="assets/snapshot.jpeg"> | <img width="685" src="assets/original.jpeg"> |
| :---------------------------------------------: | :-----------------------------------------------: | :-----------------------------------------------: |
|               Export with Notion                |        Scraped with ✨NotionSnapshot✨        |                   Original page                   |
