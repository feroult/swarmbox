#!/bin/bash
# Swarmbox messaging utilities
# Simple, sober design to complement the colorful banner

# Minimal color palette - just muted tones
GRAY='\033[0;90m'
WHITE='\033[0;37m'
RESET='\033[0m'

# Simple message functions - no fancy icons
msg() {
    echo -e "${WHITE}${1}${RESET}"
}

msg_detail() {
    echo -e "${GRAY}  ${1}${RESET}"
}

msg_blank() {
    echo ""
}
