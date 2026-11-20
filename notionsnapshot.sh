#!/bin/sh
# usage: ./notionsnapshot.sh <public notion url> [output dir]
set -eu

script="$(cd "$(dirname "$0")" && pwd)/assets/inject.js"
cache="$HOME/.cache/notionsnapshot"
mkdir -p "${2:-snapshot}" "$cache"
chrome=$(npx -y @puppeteer/browsers@2.10.0 install chrome@stable --path "$cache" | tail -1 | cut -d' ' -f2)

# --crawl-replace-URLs only rewrites links in files of the working directory
cd "${2:-snapshot}"

# --user-data-dir: persistent http cache, else notion rate limits repeated runs
# --browser-height: notion only renders blocks near the viewport
# --block-fonts: notion's css references every font it has, ~8 mb per page
# --crawl-rewrite-rule: notion links each page as /<id>, /p/<id> and ?pvs=<n>
# --max-parallel-workers: parallel browsers get rate limited and pages are silently dropped
npx -y single-file-cli@2.0.75 "$1" \
  --browser-executable-path="$chrome" \
  --browser-arg="--user-data-dir=$cache/profile" \
  --browser-height=20000 \
  --browser-wait-until=load \
  --browser-script="$script" \
  --block-fonts=true \
  --block-videos=false \
  --block-audios=false \
  --crawl-links=true \
  --crawl-max-depth=0 \
  --crawl-replace-URLs=true \
  --crawl-rewrite-rule='^(https://[^/]+/)(p/)?([^?]*).*$ $1$3' \
  --max-parallel-workers=1 \
  --filename-template="{url-last-segment}.html"
