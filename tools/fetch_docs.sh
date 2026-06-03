#!/usr/bin/env bash
# Re-populate docs/vendor/ (gitignored). See docs/SOURCES.md for what each item is.
set -euo pipefail
cd "$(dirname "$0")/../docs/vendor"
mkdir -p papers gw pufferlib fumbbl bloodbowlbase

# Papers
cd papers
curl -sL -o bloodbowl-challenge-justesen2019.pdf "https://njustesen.github.io/njustesen/publications/justesen2019blood.pdf"
curl -sL -o bloodbowl-deeprl-justesen2018.pdf "https://njustesen.github.io/njustesen/publications/justesen2018blood.pdf"
curl -sL -o roe-rarity-of-events-justesen2018.pdf "https://arxiv.org/pdf/1803.07131"
curl -sL -o mimicbot-2108.09478.pdf "https://arxiv.org/pdf/2108.09478"
curl -sL -o invalid-action-masking-2006.14171.pdf "https://arxiv.org/pdf/2006.14171"
curl -sL -o stochastic-muzero-iclr2022.pdf "https://openreview.net/pdf?id=X6D9bAHhBQ1"
curl -sL -o pufferlib-2406.12905.pdf "https://arxiv.org/pdf/2406.12905"
curl -sL -o mini-alphastar-2104.06890.pdf "https://arxiv.org/pdf/2104.06890"
cd ..

# GW official (asset URLs rotate; check docs/SOURCES.md notes if 404)
curl -sL -o gw/bb-faq-errata-nov2025.pdf "https://assets.warhammer-community.com/eng_14-11_bloodbowl_faq_errata-ngh7bivuzu-vslz4fw2nm.pdf"

# PufferLib docs
for page in docs blog ocean; do
  curl -sL -o "pufferlib/$page.html" "https://puffer.ai/$page.html"
done

# FUMBBL API notes
curl -sL -o fumbbl/api-notes-730.html "https://fumbbl.com/p/notes?op=view&id=730"

# BB2025 rules mirror (polite: rate-limited)
cd bloodbowlbase
wget --quiet --recursive --level=4 --no-parent --wait=0.7 --random-wait \
  --adjust-extension --convert-links --restrict-file-names=windows \
  --domains=bloodbowlbase.ru --include-directories=/bb2025 \
  --user-agent="bloodbowl-rl-research (personal project; polite mirror)" \
  "https://bloodbowlbase.ru/bb2025/" || true
echo "Done. $(find . -name '*.html' | wc -l) pages mirrored."
