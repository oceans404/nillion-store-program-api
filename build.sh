#!/bin/bash
pip install -r requirements.txt
curl -s https://nilup.nilogy.xyz/install.sh | bash
export PATH="$HOME/.nilup/bin:$PATH"
nilup install latest --nada-dsl
nilup use latest